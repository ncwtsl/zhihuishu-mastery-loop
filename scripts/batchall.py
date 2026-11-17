"""Unattended driver: take every knowledge point to mastery 100.

What changed from the first version, and why each change matters:

* **A missed answer is now fixed immediately.** After every submit the paper's
  own 参考答案 page is compared against what was actually submitted; any
  disagreement is written back into the bank on the spot. The old loop only
  ever *added* answers it had never seen, so a wrong letter already in the bank
  survived every round and the point sat at 76 forever.
* **A stalled point escalates instead of retrying.** Three identical scores mean
  the plan is identical, so another round cannot help - `probe.py` takes over
  and searches the answer space using the 已答对 count as an oracle.
* **Commit is verified before submitting.** `fastpy.committed()` reads the real
  answerState; the old `endswith("->2")` test compared against a string the JS
  never produced, so "everything is answered" was always reported as false.
* **The run is resumable.** Each point's result lands in its own JSON and in
  `summary.json`, and `--resume` skips whatever already reached the target.
* **No-paper points are reported, not retried.** A 免考 card has no paper at all;
  `drive.NoPaper` carries that distinction to the summary instead of looking
  like a timeout.
"""
import argparse
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import bank  # noqa: E402
import config  # noqa: E402
import drive  # noqa: E402
import fastpy  # noqa: E402
import live  # noqa: E402
import oracle  # noqa: E402
import probe  # noqa: E402
import verify  # noqa: E402 - the run ends by grading itself, not by printing DONE


class _Live:
    """The browser-backed driver, behind the same five calls the simulator offers.

    `run_point` used to call `fastpy.*` directly, which is why the escalation path
    (probe) could never be tested without a logged-in browser - and that path is
    exactly the one that was broken for eight rounds in the field. Keeping the
    surface this small means `fake.Sim` can stand in for it and the whole loop,
    probe included, runs offline.
    """

    NoPaper = drive.NoPaper
    open_read = staticmethod(lambda kid: fastpy.open_read(kid))
    inject = staticmethod(lambda ws: fastpy.inject(ws))
    answer_all = staticmethod(lambda ws, plan: fastpy.answer_all(ws, plan))
    committed = staticmethod(lambda rep: fastpy.committed(rep))
    submit_only = staticmethod(lambda ws, kid, base: fastpy.submit_only(ws, kid, base))
    harvested_map = staticmethod(lambda items: fastpy.harvested_map(items))


LIVE = _Live()


class Log:
    """stdout + batchall.log + summary.json, all line-buffered."""

    def __init__(self):
        self.lines = []

    def __call__(self, msg):
        line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
        print(line, flush=True)
        self.lines.append(line)
        try:
            with open(config.LOG, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


log = Log()


def todo_list(refresh=False):
    """Knowledge points still short of the target.

    The DOM scan of the course page is authoritative: the JSON API needs an AES
    secret to read, while every card prints `aria-valuenow`. A point whose card
    has no progress ring at all is 免考 (no paper) and is returned separately so
    the caller can report it instead of driving it forever.
    """
    path = config.DOM_MASTERY
    rows = None
    if not refresh and os.path.exists(path):
        rows = config.load(path)
    if not rows:
        rows = live.scan()
    todo, freepoints, done = [], [], []
    for row in rows or []:
        try:
            kid, name, val = row[0], row[1], row[2]
        except (IndexError, TypeError):
            continue
        if val == "?":
            freepoints.append({"kid": kid, "name": name})
            continue
        try:
            m = float(val)
        except (TypeError, ValueError):
            continue
        if m >= config.TARGET:
            done.append({"kid": kid, "name": name, "mastery": m})
        else:
            todo.append({"kid": kid, "name": name, "mastery": m})
    todo.sort(key=lambda r: r["mastery"])          # cheapest wins first
    return todo, freepoints, done


def build_plan(qs, b):
    """{sort: letters} for a paper, plus the sorts answered from a guess."""
    plan, guessed = {}, []
    for q in qs:
        s = str(q["sort"])
        hit = bank.lookup(b, q.get("stem"))
        if hit:
            plan[s] = hit
        else:
            plan[s] = config.GUESS
            guessed.append(s)
    return plan, guessed


def play_round(drv, kid, name):
    """Open one paper, answer it from the bank, submit, and self-audit the result.

    Returns {"stage", "mastery", "correct", "total", "pending", "guessed",
    "mism", "items", "info"} - `stage` is only for the failure paths
    (no_paper / open_err / run_err / submit_failed); a played round always
    carries a mastery value or None.
    """
    try:
        ws, base, qs = drv.open_read(kid)
    except drv.NoPaper:
        return {"stage": "no_paper", "mastery": None}
    except Exception as e:
        log("%s OPEN_ERR %s %s" % (name, type(e).__name__, str(e)[:110]))
        return {"stage": "open_err", "mastery": None}

    b = bank.load(config.BANK)
    plan, guessed = build_plan(qs, b)
    try:
        drv.inject(ws)
        rep = drv.answer_all(ws, plan)
        _ok, pending = drv.committed(rep)
        if pending:
            # One retry pass over exactly the questions that did not commit.
            drv.answer_all(ws, {s: plan[s] for s in pending if s in plan})
            rep = drv.answer_all(ws, plan)
            _ok, pending = drv.committed(rep)
        res, items, info = drv.submit_only(ws, kid, base)
    except Exception as e:
        log("%s RUN_ERR %s %s" % (name, type(e).__name__, str(e)[:110]))
        return {"stage": "run_err", "mastery": None}
    if not res:
        return {"stage": "submit_failed", "mastery": None}

    # --- self-audit: the paper's own answer key vs what we sent --------------
    got = drv.harvested_map(items)
    mism = oracle.mismatches(plan, got)
    correct, total = res["correct"], res["total"]
    blind = sorted(set(str(q["sort"]) for q in qs) - set(got), key=str)
    if not mism and correct is not None and total and correct < total:
        # Three very different situations look identical from the count alone,
        # and telling them apart is the difference between "fix the parser",
        # "run the probe" and "check why the answer never committed":
        #   no harvest at all -> the 参考答案 page gave us nothing; nothing can
        #                        be attributed, so probe has to brute-force.
        #   harvest covered only part of the paper -> every answer we could
        #                        check is right, so the wrong one is on a question
        #                        the preview page hid (blind). Probe's job.
        #   harvest covered everything and all matched -> the bank is right and
        #                        the paper still scored us lower, i.e. the
        #                        answering mechanics dropped a question.
        if not got:
            log("%s NO_HARVEST correct=%s/%s: 解析页没给出任何参考答案，"
                "本轮无法归因；若连续如此就该走 probe 逐字母试" % (name, correct, total))
        elif blind:
            log("%s BLIND correct=%s/%s: 解析页只给了 %d/%s 题的答案，"
                "没覆盖的题号 %s 才是嫌疑（题库里能查到的都对）——这是 probe 的活"
                % (name, correct, total, len(got), total, blind))
        else:
            log("%s AUDIT_CLEAN correct=%s/%s but all %d answers matched the key: "
                "差异来自作答/提交（某题 answerState 没跟上），不是题库"
                % (name, correct, total, len(got)))
    fixed = 0
    if mism:
        b2 = bank.load(config.BANK)
        by_sort = {str(q["sort"]): q for q in qs}
        for m in mism:
            q = by_sort.get(m["sort"])
            if not q:
                continue
            bank.put(b2, q.get("stem"), m["want"], q.get("typeName"),
                     [o.get("text") for o in q.get("opts") or []], source="audit")
            fixed += 1
        bank.save(b2, config.BANK)
    # `verdict` collapses the four numbers into the one word a reader needs:
    # shy = the bank is still wrong somewhere, collapse = the answers never
    # committed (mechanics, not content), perfect = only the platform's
    # second-consecutive-round rule is holding the point below 100.
    log("%s mast=%s correct=%s/%s verdict=%s pending=%s guessed=%s harvest=%d new=%d fixed=%d bank=%d" % (
        name, res["mastery"], res["correct"], res["total"],
        oracle.verdict(res["correct"], res["total"]), len(pending or []),
        guessed, len(items), info.get("new", 0), fixed, info.get("bank", 0)))
    return {"stage": "ok", "mastery": res["mastery"], "correct": res["correct"],
            "total": res["total"], "pending": pending, "guessed": guessed,
            "mism": mism, "items": items, "info": info}


def run_point(kid, name, maxr=None, target=None, allow_probe=True, drv=None):
    """Drive one knowledge point to the target mastery. Never raises.

    The shape matters: a paper can score *perfect* and still be credited only
    94-96, so "the answers are all right" is not the end condition - the mastery
    number is. Anything that returns early on a perfect paper leaves the point at
    94 forever, which is exactly the state the field run reported as done.

    The round budget therefore covers the whole point, and the probe escalation
    does not end it: after the oracle finds a missing answer the normal loop keeps
    going to collect the second consecutive all-correct round.
    """
    drv = drv or LIVE
    maxr = maxr or config.MAXR
    target = config.TARGET if target is None else target
    hist = []
    probed = False
    failed = None
    cap = maxr * (2 if allow_probe else 1)

    while len(hist) < cap:
        out = play_round(drv, kid, name)
        if out["stage"] in ("no_paper", "open_err", "run_err", "submit_failed"):
            failed = out["stage"]
            log("%s %s" % (name, failed.upper()))
            break
        hist.append(out["mastery"])
        if out["mastery"] is not None and out["mastery"] >= target:
            log("%s DONE %s hist=%s" % (name, out["mastery"], hist))
            return {"kid": kid, "name": name, "stage": "done",
                    "mastery": out["mastery"], "hist": hist}
        if out["correct"] is None or not out["total"]:
            log("%s WARN result page had no 已答对/总题数; treating as unknown" % name)
        if bank.stalled(hist, patience=3):
            if not (allow_probe and not probed):
                log("%s STALLED at %s after %d identical rounds" % (name, out["mastery"], len(hist)))
                break
            probed = True
            log("%s STALLED at %s -> probe (cap=%d)" % (name, out["mastery"], config.PROBE))
            pout = probe.probe_point(kid, cap=config.PROBE, log=log, drv=drv)
            learned = pout.get("letters") or {}
            log("%s probe stage=%s learned=%s" % (
                name, pout["stage"], json.dumps(learned, ensure_ascii=False)))
            if pout["stage"] == "no_paper":
                failed = "no_paper"
                break
            if not learned and pout["stage"] not in ("perfect",):
                # Nothing new was learned; another bank round would repeat itself.
                return {"kid": kid, "name": name, "stage": "probe_" + pout["stage"],
                        "hist": hist, "letters": learned, "probe": pout["stage"]}
            # Fall through: the loop continues with the corrected bank, which is
            # what converts 94 into 100.

    if failed == "no_paper":
        return {"kid": kid, "name": name, "stage": "no_paper", "hist": hist}
    if failed:
        return {"kid": kid, "name": name, "stage": failed, "hist": hist}
    last = hist[-1] if hist else None
    stage = "done" if (last is not None and last >= target) else "short"
    return {"kid": kid, "name": name, "stage": stage, "mastery": last, "hist": hist}


def post_run_grid(todo, freepoints, done, summary):
    """The mastery grid as it stands *after* the run, without re-scanning.

    `verify.py` must be able to answer "is this finished?" at the end of a
    batchall run, but re-opening the course page costs a browser round trip and
    can come back short while the grid is still painting. The three inputs we
    already hold cover it:

      * points that were already at target before the run,
      * points the platform never opened a paper for (`?` ring),
      * every point just driven, valued by its final recorded mastery.

    A point that ended in a failure stage carries its last known mastery (or the
    pre-run value), so `verify` reports it as short rather than as absent.
    """
    by_kid = {}
    for r in done or []:
        by_kid[r["kid"]] = [r["kid"], r["name"], r.get("mastery"), "", ""]
    for r in freepoints or []:
        by_kid[r["kid"]] = [r["kid"], r["name"], "?", "", ""]
    for p in (summary or {}).get("points") or []:
        if p.get("stage") == "no_paper":
            by_kid[p["kid"]] = [p["kid"], p["name"], "?", "", ""]
            continue
        val = p.get("final")
        if val is None:
            prev = next((t for t in (todo or []) if t["kid"] == p["kid"]), None)
            val = prev.get("mastery") if prev else None
        if val is None:
            # A failure stage (open_err / run_err / submit_failed) has no mastery
            # at all. `live.classify` treats an unparseable ring as 免考, which
            # would silently excuse the point; -1 keeps it in `short` so the
            # acceptance check still reports it.
            val = -1.0
        by_kid[p["kid"]] = [p["kid"], p["name"], val, "", ""]
    return list(by_kid.values())


def write_summary(results, freepoints, started):
    rows = []
    for r in results:
        h = [x for x in (r.get("hist") or []) if x is not None]
        rows.append({
            "kid": r["kid"], "name": r["name"], "stage": r["stage"],
            "final": h[-1] if h else r.get("mastery"),
            "rounds": len(h), "hist": h,
        })
    # no_paper is NOT a failure: the platform never opened a paper, so no amount
    # of driving reaches 100. Keeping it out of `problems` is what stops a
    # finished run from being reported as unfinished.
    bad = [r for r in rows
           if r["stage"] != "no_paper"
           and (r["stage"] != "done" or (r["final"] or 0) < config.TARGET)]
    summary = {
        "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)),
        "elapsed_min": round((time.time() - started) / 60.0, 1),
        "target": config.TARGET,
        "points": rows,
        "no_paper": freepoints,
        "problems": [{"name": r["name"], "stage": r["stage"], "final": r["final"]} for r in bad],
    }
    config.dump(summary, config.SUMMARY)
    return summary


# Stage -> one line a human can act on. The wording lives in `probe.STAGES` so the
# audit, verify's `why` field and probe's own log all speak the same vocabulary;
# keeping a second copy here is how one of them silently drifts.
WHY = probe.STAGES


def write_audit(summary):
    """A human-readable report - the thing to hand the user when the run ends."""
    lines = ["# 知到掌握率刷题结果", "",
             "- 开始: %s" % summary["started"],
             "- 耗时: %.1f 分钟" % summary["elapsed_min"],
             "- 目标: %g%%" % summary["target"], ""]
    ok = [p for p in summary["points"]
          if p["stage"] == "done" and (p["final"] or 0) >= summary["target"]]
    free = [p for p in summary["points"] if p["stage"] == "no_paper"]
    rest = [p for p in summary["points"] if p not in ok and p not in free]

    lines.append("## 已达标 %d/%d" % (len(ok), len(summary["points"])))
    lines.append("")
    lines.append("| 知识点 | 最终掌握率 | 轮次 | 分数序列 |")
    lines.append("| --- | --- | --- | --- |")
    for p in ok:
        lines.append("| %s | %s%% | %d | %s |" % (
            p["name"], p["final"], p["rounds"], " → ".join("%g" % x for x in p["hist"])))

    if rest:
        lines += ["", "## 未达标 %d" % len(rest), "",
                  "| 知识点 | 阶段 | 最终 | 说明 |", "| --- | --- | --- | --- |"]
        for p in rest:
            lines.append("| %s | %s | %s | %s |" % (
                p["name"], p["stage"], p["final"],
                WHY.get(p["stage"], "见日志")))

    if free:
        lines += ["", "## 平台未开练习卷 %d（刷不到 100，属正常）" % len(free),
                  "",
                  "这些卡片显示「免考 / 去练习」，没有 `.improve-btn`，"
                  "平台根本没给练习卷。不是自动化失败，换个题库也刷不动。", ""]
        for f in free:
            lines.append("- %s" % f["name"])

    head = ("全部达标" if not rest else "有 %d 个点未达标" % len(rest))
    lines += ["", "## 结论", "", "%s；平台未开练习卷 %d 个。" % (head, len(free))]

    path = config.AUDIT
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description="把知到/智慧树知识点的掌握率刷到 100%")
    ap.add_argument("only", nargs="?", default=None,
                    help="逗号分隔的 knowledgeId；'-' 表示全部")
    ap.add_argument("limit", nargs="?", type=int, default=None, help="最多跑几个点")
    ap.add_argument("--refresh", action="store_true", help="重新扫描课程页再决定跑哪些点")
    ap.add_argument("--resume", action="store_true", help="跳过 summary.json 里已经达标的点")
    ap.add_argument("--maxr", type=int, default=None, help="每个点最多几张卷（默认 ZHS_MAXR=9）")
    ap.add_argument("--probe", type=int, default=None, help="每个点反解预算（默认 ZHS_PROBE=12）")
    ap.add_argument("--no-probe", action="store_true", help="只用题库直答，不做反解")
    ap.add_argument("--fake", action="store_true", help="不连浏览器：用内置夹具演练流程与报表")
    a = ap.parse_args(argv)

    if a.fake:
        import fake
        return fake.run()

    started = time.time()
    todo, freepoints, done = todo_list(refresh=a.refresh)
    if a.resume and os.path.exists(config.SUMMARY):
        prev = config.load(config.SUMMARY) or {}
        # `done` is the only success stage; `done_probe` was a name from the run
        # that stopped at 94 and called it finished.
        passed = {p["kid"] for p in prev.get("points", [])
                  if p.get("stage") == "done"
                  and (p.get("final") or 0) >= config.TARGET}
        before = len(todo)
        todo = [r for r in todo if r["kid"] not in passed]
        if before != len(todo):
            log("RESUME skipping %d point(s) already at target" % (before - len(todo)))
    if a.only and a.only != "-":
        want = {x.strip() for x in a.only.split(",") if x.strip()}
        todo = [r for r in todo if r["kid"] in want]
    if a.limit:
        todo = todo[:a.limit]
    if a.probe is not None:
        config.PROBE = a.probe

    log("START points=%d no_paper=%d already_done=%d data=%s" % (
        len(todo), len(freepoints), len(done), config.DATA))
    log("PLAN " + json.dumps([r["name"] for r in todo], ensure_ascii=False))
    if not (todo or freepoints or done):
        # An empty grid is not "everything is done" - it means the scan never saw
        # a card (wrong course id, logged out, page still painting). Saying
        # NOTHING_TO_DO here would report a broken scan as a finished course.
        log("NO_SCAN no card found; run `python doctor.py` then `python live.py`")
        return 2
    if not todo:
        log("NOTHING_TO_DO every parseable point is already at %g%%" % config.TARGET)

    results = []
    for idx, r in enumerate(todo, 1):
        log("[%d/%d] %s (now %s%%)" % (idx, len(todo), r["name"], r["mastery"]))
        res = run_point(r["kid"], r["name"], maxr=a.maxr, allow_probe=not a.no_probe)
        results.append(res)
        config.dump({"kid": r["kid"], "name": r["name"], "res": res},
                    config.path("result_%s.json" % r["kid"]))
        # Rewrite the summary after every point: a killed run keeps its progress.
        write_summary(results, freepoints, started)

    summary = write_summary(results, freepoints, started)
    audit = write_audit(summary)
    # Not "ALL_DONE": several points may have ended short, and the word DONE here
    # is what let an unfinished run look finished in a terminal window.
    log("RESULT " + json.dumps({r["name"]: r["stage"] for r in results}, ensure_ascii=False))
    log("SUMMARY %s" % config.SUMMARY)
    log("AUDIT   %s" % audit)

    # --- self-acceptance: say whether the run actually finished, not just that
    # the loop returned. Exiting 0 on a run that left points at 76 is the exact
    # failure this project exists to avoid, so the acceptance verdict gates the
    # exit code instead of being something a human has to remember to run.
    after = post_run_grid(todo, freepoints, done, summary)
    res = verify.check(summary=summary, rows=after)
    for line in verify.fmt(res).splitlines():
        log(line)
    return 0 if res["ok"] else 3


if __name__ == "__main__":
    sys.exit(main())
