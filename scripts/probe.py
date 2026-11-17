"""Resolve questions the bank answers wrong - using the paper itself as an oracle.

Why this file exists
--------------------
The old loop treated a shortfall as bad luck: if the bank held a wrong letter it
re-answered with the same letter, submitted, scored 76.0 again, and did that
until the round budget ran out. That is exactly what happened on 爱因斯坦光子假设
(`mast=76.0` eight times, `guessed=['1']` every round).

The result page reports `已答对 N/M`. That count is a real oracle: change the
letter for one question, resubmit, and a count that goes UP proves which letter
was wrong.

Attribution - the part that took a simulator to get right
---------------------------------------------------------
Before spending a paper, use what harvest already told us. The preview page lists
参考答案 for every question it can show, in paper order. Therefore:

  * harvest disagrees with what we submitted  -> that question is known wrong, free.
  * harvest agrees with what we submitted      -> that question is known RIGHT.
  * harvest does not mention the question      -> the only remaining suspects.

So the search starts from the *absence* of evidence, not from question 1. A
probe that starts at question 1 burns a paper learning that question 1 was
already correct, and then - because nothing changed - starts over and burns
another one. That is the loop the simulator caught.

Cost order: confirmed-wrong (free) -> blind/unreported -> judge (2 candidates)
-> single choice -> multi-select, and never a question already proven right.
"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import bank  # noqa: E402
import config  # noqa: E402
import drive  # noqa: E402
import fastpy  # noqa: E402
import oracle  # noqa: E402


class _Live:
    """Browser-backed driver surface, so `fake.Sim` can stand in for it offline."""

    NoPaper = drive.NoPaper
    open_read = staticmethod(lambda kid: fastpy.open_read(kid))
    inject = staticmethod(lambda ws: fastpy.inject(ws))
    answer_all = staticmethod(lambda ws, plan: fastpy.answer_all(ws, plan))
    committed = staticmethod(lambda rep: fastpy.committed(rep))
    submit_only = staticmethod(lambda ws, kid, base: fastpy.submit_only(ws, kid, base))
    harvested_map = staticmethod(lambda items: fastpy.harvested_map(items))


LIVE = _Live()


def _nopts(q):
    return len(q.get("opts") or []) or 4


def _same(a, b):
    return "".join(sorted(str(a or ""))) == "".join(sorted(str(b or "")))


def evidence(qs, plan, harvested, learned):
    """Split the paper by what the preview page proved about each question.

    Returns (wrong, right, unreported) as sort lists, where:
      wrong      - harvest says a different answer than we submitted (free fix)
      right      - harvest agrees with us; never spend a paper here again
      unreported - no evidence either way: the only questions worth testing
    """
    by_sort = {str(q["sort"]): q for q in qs}
    wrong, right, unreported = [], [], []
    for s in by_sort:
        if s in learned:
            right.append(s)
            continue
        if s in (harvested or {}):
            (right if _same(harvested[s], plan.get(s)) else wrong).append(s)
        else:
            unreported.append(s)
    return wrong, right, unreported


def rank_unknown(qs, unreported, plan):
    """Order the questions with no evidence: cheapest hypothesis first.

    A 判断题 has two candidates, a single-choice with four options has three
    wrong ones, and a multi-select can explode - so try the cheap ones first and
    leave the expensive ones for when a bigger budget is available.
    """
    by_sort = {str(q["sort"]): q for q in qs}
    scored = []
    for s in unreported:
        q = by_sort.get(s)
        if not q:
            continue
        tname = q.get("typeName") or ""
        if oracle.is_judge(tname):
            rank = 0
        elif oracle.is_multi(tname):
            rank = 2 if _nopts(q) <= 4 else 3
        else:
            rank = 1
        scored.append((rank, int(s) if s.isdigit() else 10 ** 6, s))
    scored.sort()
    return [s for _r, _n, s in scored], by_sort


def rank_targets(qs, plan, mism, unknown):
    """Backwards-compatible wrapper: known-wrong first, then unreported."""
    wrong = [str(m["sort"]) for m in mism]
    rest, by_sort = rank_unknown(qs, [str(u) for u in unknown if str(u) not in wrong], plan)
    order = [s for s in wrong if s in by_sort] + rest
    return order, by_sort


def _cands_for(q, plan, s):
    """Letter strings worth trying for question `s`: everything but the current one.

    Multi-select deliberately does NOT go through `oracle.wrong_alternatives`
    (that one returns [] for multi types, because it answers "what is certainly
    wrong" for single-answer questions only). Here the subset list is what we
    want, so `candidates()` is used directly and the current guess is filtered out.
    """
    tname = q.get("typeName") or ""
    n = _nopts(q)
    return [c for c in oracle.candidates(tname, n) if not _same(c, plan.get(s))]


def probe_point(kid, ws_first=None, cap=None, log=print, drv=None):
    """Search one knowledge point until a paper scores perfect, or the cap runs out.

    Returns {"stage", "letters": {sort: "AB"}, "rounds", "hist", "suspects"}.
    `letters` holds every answer the oracle confirmed during this call.
    """
    drv = drv or LIVE
    cap = cap if cap is not None else config.PROBE
    learned, proved_right = {}, set()
    hist, rounds = [], 0
    qs = base = ws = None
    if ws_first is not None:
        ws = ws_first
    last_result = None

    while rounds < cap:
        if ws is None:
            try:
                ws, base, qs = drv.open_read(kid)
            except drv.NoPaper:
                return {"stage": "no_paper", "letters": learned, "rounds": rounds, "hist": hist}
        b = bank.load(config.BANK)
        plan = {}
        for q in qs:
            s = str(q["sort"])
            hit = learned.get(s) or bank.lookup(b, q["stem"])
            plan[s] = hit or config.GUESS

        drv.inject(ws)
        rep = drv.answer_all(ws, plan)
        _ok, bad = drv.committed(rep)
        res, items, info = drv.submit_only(ws, kid, base)
        ws = None
        rounds += 1
        if not res:
            return {"stage": "submit_failed", "letters": learned, "rounds": rounds, "hist": hist}
        last_result = res
        hist.append(res["mastery"])
        correct, total = res["correct"], res["total"]
        got = drv.harvested_map(items)
        wrong, right, unreported = evidence(qs, plan, got, learned)
        proved_right.update(right)

        log("  probe r%d mast=%s correct=%s/%s pending=%s wrong=%s unreported=%s"
            % (rounds, res["mastery"], correct, total, len(bad or []), wrong, unreported))

        # --- free wins: the preview page handed us the answer ------------------
        by_sort_all = {str(q["sort"]): q for q in qs}
        for s in wrong:
            q = by_sort_all.get(s)
            if not q:
                continue
            want = got[s]
            if oracle.is_multi(q.get("typeName")) and len(wrong) > 1:
                # A multi-select mismatch cannot be attributed while other
                # questions are also wrong; the count would not move for it.
                continue
            learned[s] = want
            bank.put(b, q["stem"], want, q.get("typeName"),
                     [o.get("text") for o in q.get("opts") or []], source="probe")
            log("  probe FIX q%s -> %s (harvest said so, no extra paper)" % (s, want))
        if wrong:
            bank.save(b, config.BANK)

        if correct is not None and total and correct >= total:
            return {"stage": "perfect", "letters": learned, "rounds": rounds, "hist": hist}

        if correct is None or not total:
            return {"stage": "no_count", "letters": learned, "rounds": rounds, "hist": hist}

        # --- choose what to test next -----------------------------------------
        suspects = [s for s in unreported if s not in learned]
        suspects, by_sort = rank_unknown(qs, suspects, plan)
        if not suspects:
            # Everything harvest could see is right, yet the count is short.
            # Either harvest was truncated or the wrong answer is on a blind
            # question; fall back to everything we have not proved right.
            suspects = [s for s in by_sort if s not in proved_right and s not in learned]
            suspects, by_sort = rank_unknown(qs, suspects, plan)
        if not suspects:
            return {"stage": "exhausted", "letters": learned, "rounds": rounds,
                    "hist": hist, "suspects": []}

        s = suspects[0]
        q = by_sort[s]
        cands = _cands_for(q, plan, s)
        if not cands:
            log("  probe q%s has no testable alternative (%s, %d opts)"
                % (s, q.get("typeName"), _nopts(q)))
            proved_right.add(s)
            continue
        log("  probe q%s [%s] candidates=%s (baseline %s/%s)"
            % (s, q.get("typeName"), cands, correct, total))

        # --- test the candidates ----------------------------------------------
        samples = []
        for cand in cands:
            if rounds >= cap:
                break
            trial = oracle.plan_with(plan, {s: cand})
            try:
                ws2, base2, _qs2 = drv.open_read(kid)
            except drv.NoPaper:
                return {"stage": "no_paper", "letters": learned, "rounds": rounds, "hist": hist}
            drv.inject(ws2)
            drv.answer_all(ws2, trial)
            res2, items2, _i2 = drv.submit_only(ws2, kid, base2)
            ws2 = None
            rounds += 1
            if not res2:
                return {"stage": "submit_failed", "letters": learned, "rounds": rounds,
                        "hist": hist}
            c2, t2 = res2.get("correct"), res2.get("total")
            hist.append(res2.get("mastery"))
            log("    try q%s=%s -> %s/%s" % (s, cand, c2, t2))
            samples.append((cand, c2))
            if c2 is not None and t2 and c2 >= t2:
                learned[s] = cand
                bank.put(b, q["stem"], cand, q.get("typeName"),
                         [o.get("text") for o in q.get("opts") or []], source="probe")
                bank.save(b, config.BANK)
                log("  probe PERFECT q%s=%s" % (s, cand))
                return {"stage": "perfect", "letters": learned, "rounds": rounds, "hist": hist}
            # Harvest on the trial paper is authoritative even mid-search.
            got2 = drv.harvested_map(items2)
            if got2.get(s) and not _same(got2[s], cand):
                learned[s] = got2[s]
                bank.put(b, q["stem"], got2[s], q.get("typeName"),
                         [o.get("text") for o in q.get("opts") or []], source="probe")
                bank.save(b, config.BANK)
                log("    harvest resolved q%s -> %s (overriding trial %s)"
                    % (s, got2[s], cand))
                break

        best, best_c, ambiguous = oracle.pick_best(samples, baseline=correct)
        if best:
            learned[s] = best
            bank.put(b, q["stem"], best, q.get("typeName"),
                     [o.get("text") for o in q.get("opts") or []], source="probe")
            bank.save(b, config.BANK)
            log("  probe RESOLVED q%s=%s (correct %s, ambiguous=%s)" % (s, best, best_c, ambiguous))
            continue

        # No candidate beat the baseline: every letter we tried proves the
        # question was ALREADY right, and the wrong one is somewhere else.
        proved_right.add(s)
        log("  probe q%s is already correct (no candidate beat %s)" % (s, correct))
        if not ambiguous:
            # Nothing left to distinguish; do not spin on the same question.
            remaining = [x for x in by_sort if x not in proved_right]
            if not remaining:
                return {"stage": "stuck", "letters": learned, "rounds": rounds, "hist": hist}

    return {"stage": "budget", "letters": learned, "rounds": rounds, "hist": hist}


STAGES = {
    # --- what one knowledge point ended as (`run_point`) --------------------
    "done": "已达标",
    "short": "轮次用尽，仍未到目标掌握率；答案可能还没找全，下次 --resume 会重跑它",
    "maxr": "轮次用尽，仍未到 100",
    "no_paper": "平台未开练习卷（卡片是「免考 / 去练习」，没有 .improve-btn）",
    "open_err": "练习卷打不开，多为登录失效或 BASE_EMPTY（先 doctor.py）",
    "run_err": "作答/提交过程报错，见日志",
    "submit_failed": "点了提交但没跳到结果页，本轮无判分",
    # --- and what the escalation ended as (`probe_point` appended) ---------
    "probe_perfect": "答案已找全，但平台要连续第二次全对才结算 100 —— 再跑一次这个点即可",
    "probe_stuck": "所有候选字母都没让已答对数上升：错的那题不在可试范围内（可能多选选项过多）",
    "probe_exhausted": "没有可试的候选字母了",
    "probe_budget": "反解预算用完，调大 ZHS_PROBE 再跑",
    "probe_no_target": "无法归因到具体题目（解析页没给 已答对/总题数）",
    "probe_no_count": "结果页没有 已答对/总题数，反解无从判分",
    "probe_no_paper": "平台未开练习卷",
    "probe_submit_failed": "反解时提交后没跳到结果页",
    # --- bare names, when `probe_point` is reported on its own -------------
    "perfect": "已找到全部答案",
    "stuck": "候选字母都没让已答对数上升",
    "exhausted": "没有可试的候选字母了",
    "budget": "反解预算用完",
    "no_target": "无法归因到具体题目",
    "no_count": "结果页没有 已答对/总题数",
}


def explain(stage):
    """One line a report can print for any stage name this project produces.

    Every stage the loop can end in has a sentence here, because a report that
    says `unfinished: probe_stuck` and nothing else leaves the reader to go read
    the code. The table also covers the run-level names (`short`, `open_err`) so
    `verify` and `batchall` can share one vocabulary instead of each keeping a
    partial copy.
    """
    return STAGES.get(str(stage or ""), str(stage or "见日志"))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python probe.py <knowledgeId> [cap]")
        raise SystemExit(2)
    kid = sys.argv[1]
    cap = int(sys.argv[2]) if len(sys.argv) > 2 else config.PROBE
    out = probe_point(kid, cap=cap, log=lambda m: print(m, flush=True))
    print("RESULT", json.dumps(out, ensure_ascii=False))
