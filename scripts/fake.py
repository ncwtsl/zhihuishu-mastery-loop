"""A simulated platform that plugs in where the browser driver would.

`python batchall.py --fake` runs the real `batchall.run_point` and the real
`probe.probe_point` against this simulator instead of Edge. That matters because
the two things that were broken in the field are both on the *unhappy* path:

  * a bank holding a WRONG letter - the old loop resubmitted it until the round
    budget ran out (爱因斯坦光子假设: 76.0 eight times);
  * a paper that scores perfect but is not yet credited 100 - the platform needs
    a second consecutive all-correct round.

The simulator reproduces both, plus a question whose 参考答案 is missing from the
preview page (so the harvest self-audit cannot fix it and the oracle search in
`probe.py` has to brute-force the letter), a multi-select, a 判断题, and a
免考 point with no paper at all. Everything it returns has the same shape the
real driver returns, so the code under test is the shipping code.

No browser, no login, no network - which is also the state a fresh checkout is in.
"""
import json
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import bank  # noqa: E402
import config  # noqa: E402
import fastpy  # noqa: E402

# Platform behaviour, from the field run: first all-correct round scores 94-96
# and only a second consecutive one is credited 100.
FIRST_PERFECT = 94.0
SECOND_PERFECT = 100.0


class NoPaper(RuntimeError):
    pass


class Question:
    def __init__(self, sort, want, type_name="单选题", opts=None, blind=False):
        self.sort = str(sort)
        self.want = want              # ground-truth letters, e.g. "C" or "AB"
        self.type_name = type_name
        self.opts = opts or ["选项甲", "选项乙", "选项丙", "选项丁"]
        self.blind = blind            # preview page omits 参考答案 for this one

    @property
    def stem(self):
        return "%s 第%s题 %s" % (self.type_name, self.sort, self.opts[0])

    def as_js(self):
        """The shape fast.js `readAll` returns."""
        return {
            "sort": self.sort,
            "typeName": self.type_name,
            "stem": self.stem,
            "opts": [{"sort": chr(65 + i), "text": t} for i, t in enumerate(self.opts)],
            "state": "1",
        }


class Paper:
    """One knowledge point's practice paper, with its own scoring history."""

    def __init__(self, kid, name, questions, no_paper=False):
        self.kid = kid
        self.name = name
        self.questions = questions
        self.no_paper = no_paper
        self.perfect_streak = 0

    def score(self, plan):
        right = 0
        for q in self.questions:
            got = "".join(sorted(str(plan.get(q.sort) or "")))
            want = "".join(sorted(q.want))
            if got and got == want:
                right += 1
        return right

    def mastery(self, correct):
        total = len(self.questions) or 1
        if correct >= total:
            self.perfect_streak += 1
            return FIRST_PERFECT if self.perfect_streak < 2 else SECOND_PERFECT
        self.perfect_streak = 0
        # One wrong answer costs about 18 points on a 6-question paper.
        return round(100.0 * correct / total - 22.0 * (total - correct) / total, 1)

    def key_map(self):
        return {q.sort: q.want for q in self.questions}


def fixtures():
    """Three points: a poisoned+blind one, a mixed-type one, and a 免考 one."""
    k1 = Paper("k1", "爱因斯坦光子假设", [
        Question(1, "B"),
        Question(2, "A"),
        Question(3, "C", blind=True),      # bank says A, preview hides the answer
        Question(4, "D"),
        Question(5, "AB", type_name="多选题"),
        Question(6, "A"),
    ])
    k2 = Paper("k2", "光电效应", [
        Question(1, "B"),
        Question(2, "A", type_name="判断题", opts=["对", "错"]),
        Question(3, "A"),
        Question(4, "C", type_name="判断题", opts=["对", "错"]),
    ])
    k3 = Paper("k3", "导体表面电荷密度与尖端放电", [], no_paper=True)
    return {p.kid: p for p in (k1, k2, k3)}


def seed(papers):
    """Put every answer in the bank, except the ones the run has to discover.

    k1/q3 gets a deliberately WRONG letter (A instead of C) - that is the state
    the real bank was in, and the only way to exercise the audit and the oracle.
    k2 is left out entirely, so the first round guesses and learns from harvest.
    """
    b = {}
    for kid in ("k1",):
        for q in papers[kid].questions:
            letters = "A" if (kid, q.sort) == ("k1", "3") else q.want
            bank.put(b, q.stem, letters, q.type_name,
                     [{"sort": chr(65 + i), "text": t} for i, t in enumerate(q.opts)],
                     source="seed")
    return b


class Ws:
    """Stand-in for a page handle. Carries the plan that was submitted."""

    def __init__(self, paper, attempt):
        self.paper = paper
        self.attempt = attempt
        self.plan = {}


class Sim:
    """Exactly the driver surface `batchall.run_point` and `probe` call."""

    NoPaper = NoPaper

    def __init__(self, papers, log=print):
        self.papers = papers
        self.log = log
        self.attempts = 0          # papers opened == submissions (no wasted opens)
        self.submitted = 0

    # --- driver surface ---------------------------------------------------
    def open_read(self, kid):
        paper = self.papers.get(kid)
        if paper is None or paper.no_paper:
            raise NoPaper(kid)
        self.attempts += 1
        base = {"kid": kid, "qc": len(paper.questions), "et": "et%d" % self.attempts,
                "ep": "ep%d" % self.attempts, "paper": paper.name}
        return Ws(paper, self.attempts), base, [q.as_js() for q in paper.questions]

    def inject(self, ws):
        return "FAST_READY"

    def answer_all(self, ws, plan):
        flat = {str(k): ("".join(v) if isinstance(v, (list, tuple)) else str(v))
                for k, v in plan.items()}
        known = {q.sort for q in ws.paper.questions}
        ws.plan = {k: v for k, v in flat.items() if k in known}
        # Mirrors fast.js: every question reports its committed state. A missing
        # letter cannot commit, exactly like an empty click.
        return {s: ("OK_%s/want=%s/state2" % (v, v) if v else "BAD_/want=/state1")
                for s, v in flat.items() if s in known}

    def committed(self, rep):
        return fastpy.committed(rep)          # the real implementation, not a copy

    def submit_only(self, ws, kid, base):
        paper = ws.paper
        self.submitted += 1
        correct = paper.score(ws.plan)
        total = len(paper.questions)
        result = {"mastery": paper.mastery(correct), "correct": correct,
                  "total": total, "best": None}
        # The preview page: ground truth except for `blind` questions.
        items = []
        for q in paper.questions:
            if q.blind:
                continue
            items.append({"sort": q.sort, "typeName": q.type_name, "stem": q.stem,
                          "letters": list(q.want), "opts": q.opts})
        b = bank.load(config.BANK)
        new = 0
        for it in items:
            if bank.put(b, it["stem"], it["letters"], it.get("typeName"), it.get("opts"),
                        source="harvest"):
                new += 1
        if items:
            bank.save(b, config.BANK)
        return result, items, {"stage": "ok", "new": new, "bank": len(b), "paper": paper.name}

    def harvested_map(self, items):
        return fastpy.harvested_map(items)


def run(log=None):
    """Drive every fixture point through the real loop, then verify the run."""
    import os

    import batchall
    import verify

    log = log or batchall.log
    papers = fixtures()

    # Redirect every artefact into a scratch dir BEFORE anything is loaded, so a
    # rehearsal can never touch the user's real bank.
    data = os.environ.get("ZHS_DATA") or os.path.join(config.DATA, ".fake")
    os.makedirs(data, exist_ok=True)
    config.DATA = data
    config.BANK = os.path.join(data, "answers.json")
    config.LOG = os.path.join(data, "batchall.log")
    config.SUMMARY = os.path.join(data, "summary.json")
    config.AUDIT = os.path.join(data, "audit.md")
    config.DOM_MASTERY = os.path.join(data, "dom_mastery.json")
    for stale in (config.BANK, config.LOG, config.SUMMARY, config.AUDIT):
        if os.path.exists(stale):
            os.remove(stale)

    b = seed(papers)
    bank.save(b, config.BANK)
    log("FAKE data=%s bank=%d points=%d (1 poisoned+blind, 1 mixed type, 1 no-paper)"
        % (data, len(b), len(papers)))

    sim = Sim(papers, log)
    results = []
    for kid in ("k1", "k2", "k3"):
        paper = papers[kid]
        res = batchall.run_point(kid, paper.name, drv=sim, maxr=config.MAXR,
                                 allow_probe=True)
        results.append(res)
        log("FAKE %s -> stage=%s hist=%s" % (paper.name, res["stage"],
                                             [x for x in res.get("hist") or [] if x is not None]))

    free = [{"kid": p.kid, "name": p.name} for p in papers.values() if p.no_paper]
    # started=time.time() so the report shows a real clock, then zero the elapsed
    # time: a rehearsal ran in milliseconds and "29915410.9 分钟" in a report is
    # exactly the sort of plausible-but-wrong number this skill exists to avoid.
    started = time.time()
    summary = batchall.write_summary(results, free, started)
    summary["elapsed_min"] = 0.0
    config.dump(summary, config.SUMMARY)
    audit = batchall.write_audit(summary)

    # The grid `live.scan()` would have produced: "?" is a 免考 card with no ring,
    # which verify.py must exclude rather than count as zero.
    rows = [[r["kid"], r["name"],
             "?" if r["stage"] == "no_paper" else "%g" % (r.get("final") or 0)]
            for r in summary["points"]]
    res = verify.check(summary=summary, rows=None, bank_path=config.BANK,
                       bank_before=None, dom_rows=rows)
    print(verify.fmt(res))
    print("FAKE_RUNS papers_opened=%d submitted=%d bank=%d"
          % (sim.attempts, sim.submitted, len(bank.load(config.BANK))))
    print("FAKE_ARTIFACTS %s %s" % (config.SUMMARY, audit))
    print("FAKE_JSON " + json.dumps(
        {"results": [{k: v for k, v in r.items() if k != "letters"} for r in results],
         "verify": res["ok"]}, ensure_ascii=False))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(run())
