"""Acceptance check: decide whether a run is actually finished, and say why not.

A mastery run "looks done" all the time when it is not. This module encodes the
four things that must all hold, so neither the agent nor the user has to eyeball
a log:

  0. **There is evidence.** An empty grid is `no_scan`, never a pass. Once, a
     broken scan printed `points=0 short=0` and the verdict came out `ok` - the
     same class of lie as a false "done" below, with less data.
  1. **No point is short.** Every scanned card whose ring is a number must be at
     the target. A card with no ring is 免考 and is excluded, not counted as 0.
  2. **The history is honest.** The final round of a point must be >= its target
     *and* the recorded per-round numbers must come from `/point/` pages. A run
     that "finished" with a `None` in its last slot hit the failure path where
     the quiz page never navigated and the answering progress (83.3) was read
     instead of mastery.
  3. **It is converging.** An unfinished point whose last three rounds are the
     same number will repeat that number forever: the plan did not change, so
     another round is a coin flip, not progress. That needs a probe pass (or a
     hand-fixed bank entry), not more rounds.

The stall is read from the recorded history rather than from bank growth, so the
check works on a finished run read back from `summary.json` - `bank_before` is
only available live and is kept as a secondary signal.

`verify.py` exits non-zero when any of these fail, so it can gate a report.
"""
import argparse
import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import bank  # noqa: E402
import config  # noqa: E402
import live  # noqa: E402
import probe  # noqa: E402 - only for `explain()`, so a report says WHY a stage stalled

# A mastery value that cannot come from the result page. The answering-progress
# bar reads 83.3 / 66.7 / 50 and mastery never lands there in practice; more
# importantly a `None` means no /point/ navigation at all.
SUSPECT = (83.3, 66.7, 33.3, 16.7)


def check(summary=None, rows=None, bank_path=None, bank_before=None, dom_rows=None):
    """Returns {"ok": bool, "problems": [...], "stats": {...}}.

    `rows` and `dom_rows` are the same thing under two names: the `live.scan()`
    grid. `dom_rows` exists so a simulated run can inject its own grid without
    pretending to have scanned a course page.
    """
    problems = []
    summary = summary if summary is not None else (config.load(config.SUMMARY) or {})
    if dom_rows is None:
        rows = rows if rows is not None else (config.load(config.DOM_MASTERY) or [])
    else:
        rows = dom_rows
    bank_path = bank_path or config.BANK

    done, todo, free = live.classify(rows)
    stats = {
        "points": len(rows),
        "at_target": len(done),
        "short": len(todo),
        "no_paper": len(free),
        "bank": len(bank.load(bank_path)),
        "target": config.TARGET,
    }

    # 0. no evidence is not a pass. An empty grid means nobody scanned the course
    # page (or the scan broke), and "0 points, 0 short" would otherwise read as a
    # perfectly clean run - the exact plausible-but-wrong verdict this file exists
    # to prevent.
    if not rows:
        problems.append({"kind": "no_scan",
                         "detail": "no mastery rows; run `python live.py` or `verify.py --refresh`"})

    # 1. every numeric ring at target
    for r in todo:
        problems.append({"kind": "short", "name": r[1], "mastery": r[2]})

    # 2. per-point history sanity
    pts = summary.get("points") or []
    if summary and not pts:
        problems.append({"kind": "no_summary", "detail": "summary.json has no points"})
    for p in pts:
        hist = p.get("hist") or []
        final = p.get("final")
        if p.get("stage") == "no_paper":
            continue          # the platform never opened a paper; not our failure
        if p.get("stage") == "done":
            if final is None or final < config.TARGET:
                problems.append({"kind": "false_done", "name": p.get("name"), "final": final})
            if hist and hist[-1] is None:
                problems.append({"kind": "no_point_page", "name": p.get("name"),
                                 "detail": "last round produced no mastery value"})
            for v in hist:
                if v in SUSPECT:
                    problems.append({"kind": "progress_bar_read_as_mastery",
                                     "name": p.get("name"), "value": v})
        else:
            problems.append({"kind": "unfinished", "name": p.get("name"),
                             "stage": p.get("stage"), "final": final,
                             "why": probe.explain(p.get("stage"))})

    # 3. convergence: an unfinished point whose rounds never moved is not going to
    # finish on its own. `bank_before` is only available to a live runner; the
    # stall itself is visible in the recorded history, so check that instead.
    stalled = []
    for p in pts:
        hist = [v for v in (p.get("hist") or []) if v is not None]
        if p.get("stage") == "done" or p.get("stage") == "no_paper":
            continue
        if len(hist) >= 3 and len(set(hist[-3:])) == 1:
            stalled.append({"kind": "not_converging", "name": p.get("name"),
                            "value": hist[-1],
                            "detail": "%d identical rounds at %s; the plan is not changing - "
                                      "run probe.py or fix the bank" % (3, hist[-1])})
    problems.extend(stalled)
    if bank_before is not None and stats["short"] and stats["bank"] <= bank_before:
        problems.append({"kind": "not_converging", "bank": True,
                         "detail": "bank stayed at %d while %d point(s) are short; run probe.py"
                                   % (stats["bank"], stats["short"])})

    return {"ok": not problems, "problems": problems, "stats": stats}


def fmt(res):
    s = res["stats"]
    lines = ["points=%d at_target=%d short=%d no_paper=%d bank=%d target=%g" % (
        s["points"], s["at_target"], s["short"], s["no_paper"], s["bank"], s["target"])]
    if res["ok"]:
        lines.append("VERDICT ok")
    else:
        lines.append("VERDICT not_ok (%d problem(s))" % len(res["problems"]))
        for p in res["problems"][:40]:
            lines.append("  - " + json.dumps(p, ensure_ascii=False))
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="验收：掌握率是否真的全部到 100")
    ap.add_argument("--refresh", action="store_true", help="重新扫描课程页（默认读 dom_mastery.json）")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    a = ap.parse_args(argv)
    rows = live.scan() if a.refresh else (config.load(config.DOM_MASTERY) or [])
    res = check(rows=rows)
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1))
    else:
        print(fmt(res))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
