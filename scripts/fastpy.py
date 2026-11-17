"""Python side of `fast.js`: one evaljs per phase, never one per question.

The correctness contract with fast.js:

  read_all   -> [{sort, typeName, stem, opts, state}] in paper order, no __LAG__
  answer_all -> {sort: "OK_AC/want=AC/state2"} - the trailing `state<N>` is the
                committed answerState. A question whose answer did not commit
                reports state1 and MUST be re-answered before submitting.
"""
import json
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import bank  # noqa: E402
import config  # noqa: E402
import drive  # noqa: E402
import harvest  # noqa: E402
import oracle  # noqa: E402
import quiz  # noqa: E402
from cdp import evaljs  # noqa: E402

JS = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fast.js"), encoding="utf-8").read()


def inject(ws):
    v = evaljs(ws, JS, timeout=25)
    if v != "FAST_READY":
        raise RuntimeError("fast.js did not install: %r" % (str(v)[:200],))
    return v


def _j(x):
    if isinstance(x, str):
        try:
            return json.loads(x)
        except ValueError:
            return None
    return x


def read_all(ws, n):
    qs = _j(evaljs(ws, "window.__F.readAll(%d)" % int(n), timeout=180))
    if not isinstance(qs, list) or len(qs) != int(n):
        raise RuntimeError("read_all short: %r/%d" % (len(qs) if isinstance(qs, list) else qs, int(n)))
    lags = [q.get("sort") for q in qs if q.get("stem") == "__LAG__"]
    if lags:
        raise RuntimeError("read_all lagged on %s" % lags)
    return qs


def answer_all(ws, plan):
    flat = {str(k): ("".join(v) if isinstance(v, (list, tuple)) else str(v)) for k, v in plan.items()}
    rep = _j(evaljs(ws, "window.__F.answerAll(%s)" % json.dumps(flat), timeout=240))
    return rep if isinstance(rep, dict) else {}


def committed(rep):
    """Sorts whose answer actually registered. `state2` is the only proof.

    The suffix is built by `fast.js swipeAll` as
    `'OK_'|'BAD_' + got + '/want=' + want + '/state' + answerState`, so the
    marker is a PREFIX (`OK_AC/...`), not an infix. Testing for `"_OK_"` here
    matched nothing fast.js ever emitted - a second incarnation of the dead
    `endswith("->2")` check this function replaced.
    """
    ok, bad = [], []
    for k, v in (rep or {}).items():
        s = str(v)
        m = re.search(r"state(\d+)$", s)
        if m and m.group(1) == "2" and s.startswith("OK_"):
            ok.append(k)
        else:
            bad.append(k)
    return ok, bad


def get_base(ws, tries=8):
    """Backwards-compatible alias; quiz.get_base owns the polling."""
    return quiz.get_base(ws, tries)


def open_read(kid, tries=3):
    """Open a fresh paper and read every question. Returns (ws, base, qs)."""
    last = None
    for attempt in range(tries):
        try:
            ws, base = drive.open_quiz(kid)
            config.sleep(1.0)
            inject(ws)
            qs = read_all(ws, base["qc"])
            return ws, base, qs
        except drive.NoPaper:
            raise
        except Exception as e:
            last = e
            print("OPEN_RETRY attempt=%d %s %s" % (attempt + 1, type(e).__name__, str(e)[:90]), flush=True)
            drive.close_targets("learnPage")
            drive.close_targets("studentReviewTestOrExam")
            drive.reap()
            config.sleep(2.0)
    raise RuntimeError("OPEN_FAILED: %s" % (last,))


def submit_only(ws, kid, base):
    """Submit the current paper, read the result page, harvest, fold into the bank.

    Returns (result, harvested, info) where result is the dict from
    `bank.parse_point` and info carries the per-question self-audit.
    """
    url = drive.submit(ws)
    if not url:
        print("SUBMIT_FAILED (no /point/ navigation)", flush=True)
        return None, [], {"stage": "submit_failed"}
    config.sleep(1.6)
    got = drive.mastery_from_page(ws)
    # Every submit navigates the quiz tab to /point/; leaving those tabs open is
    # what made the browser answer 500 to new handshakes.
    drive.close_targets("/point/")
    items = []
    try:
        items = harvest.harvest(base["ep"], base["et"], kid, 10)
    except Exception as e:
        print("HARVEST_ERR %s %s" % (type(e).__name__, str(e)[:120]), flush=True)
    bank_path = config.BANK
    b = bank.load(bank_path)
    new = 0
    for it in items:
        if bank.put(b, it["stem"], it["letters"], it.get("typeName"), it.get("opts"), source=kid):
            new += 1
    if items:
        bank.save(b, bank_path)
    drive.reap()
    info = {"stage": "ok", "new": new, "bank": len(b), "paper": base.get("paper")}
    return got, items, info


def harvested_map(items):
    """{sort: letters} from harvest items, for the self-audit."""
    out = {}
    for it in items or []:
        s = str(it.get("sort"))
        letters = "".join(bank.letters_of(it.get("letters")))
        if s.isdigit() and letters:
            out[s] = letters
    return out


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("usage: python fastpy.py read <kid>   |   python fastpy.py answer <kid> '<plan json>'")
        raise SystemExit(2)
    cmd = sys.argv[1]
    kid = sys.argv[2]
    if cmd == "read":
        ws, base, qs = open_read(kid)
        b = bank.load(config.BANK)
        print("BASE", json.dumps(base, ensure_ascii=False))
        for q in qs:
            hit = bank.lookup(b, q["stem"])
            print("---Q%s [%s] known=%s" % (q["sort"], q.get("typeName"), hit))
            print("STEM:", re.sub(r"\s+", " ", q.get("stem") or "")[:300])
            for o in q.get("opts") or []:
                print("  %s. %s" % (o.get("sort"), re.sub(r"\s+", " ", o.get("text") or "")[:170]))
            if not hit:
                for kk, ll in bank.near(b, q["stem"]):
                    print("    NEAR %s -> %s" % (ll, kk[:60]))
    elif cmd == "answer":
        plan = json.loads(sys.argv[3])
        ws, _t = quiz.conn()
        inject(ws)
        base = quiz.get_base(ws)
        rep = answer_all(ws, plan)
        ok, bad = committed(rep)
        print("REP", json.dumps(rep, ensure_ascii=False))
        print("COMMITTED", len(ok), "PENDING", bad)
        res, items, info = submit_only(ws, kid, base)
        print("RESULT", json.dumps(res, ensure_ascii=False), "INFO", json.dumps(info, ensure_ascii=False))
