"""Unattended: drive every knowledge point to mastery 100, guessing unknown items then learning from harvest."""
import sys, json, os, re, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from cdp import evaljs
import fastpy, auto, harvest, drive, quiz, config

LOG = config.LOG


def log(msg):
    line = "[%s] %s" % (time.strftime("%H:%M:%S"), msg)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def todo_list():
    """Prefer the live DOM scan (dom_mastery.json): authoritative mastery circles."""
    dom = json.load(open(config.DOM_MASTERY, encoding="utf-8"))
    rows = []
    for kid, name, val, _txt in dom:
        if val == "100":
            continue
        if val == "?":
            continue          # freeExam points have no quiz paper at all
        rows.append({"kid": kid, "name": name, "mastery": float(val)})
    return rows


def run_point(kid, name, maxr=9, target=100):
    hist = []
    for i in range(maxr):
        try:
            ws, base, qs = fastpy.open_read(kid)
        except Exception as e:
            log("OPEN_ERR %s %s %s" % (name, type(e).__name__, str(e)[:120]))
            return {"stage": "open_err", "hist": hist}
        bank = auto.load()
        plan, guessed = {}, []
        for q in qs:
            a = auto.lookup(bank, q["stem"])
            if a:
                plan[str(q["sort"])] = "".join(a)
            else:
                plan[str(q["sort"])] = "A"
                guessed.append(q["sort"])
        try:
            rep = fastpy.answer_all(ws, plan)
        except Exception as e:
            log("ANS_ERR %s %s %s" % (name, type(e).__name__, str(e)[:120]))
            return {"stage": "ans_err", "hist": hist}
        try:
            mast, got, new, correct, total = fastpy.submit_only(ws, kid, base)
        except Exception as e:
            log("SUB_ERR %s %s %s" % (name, type(e).__name__, str(e)[:120]))
            return {"stage": "sub_err", "hist": hist}
        hist.append(mast)
        log("%s r%d mast=%s correct=%s/%s guessed=%s harvested=%d new=%d bank=%d" % (
            name, i + 1, mast, correct, total, guessed, len(got), new, len(auto.load())))
        if correct is not None and total and correct < total and not got:
            log("%s WARN perfect!=True but harvest empty; answers may be stale" % name)
        if mast is not None and mast >= target:
            log("%s DONE 100 hist=%s" % (name, hist))
            return {"stage": "done", "mastery": mast, "hist": hist}
    log("%s MAXR hist=%s" % (name, hist))
    return {"stage": "maxr", "hist": hist}


def main(only=None, limit=None):
    rows = todo_list()
    if only:
        rows = [r for r in rows if r["kid"] in only]
    if limit:
        rows = rows[:limit]
    log("START points=%d %s" % (len(rows), [r["name"] for r in rows]))
    res = {}
    for r in rows:
        res[r["kid"]] = run_point(r["kid"], r["name"])
        json.dump({"kid": r["kid"], "name": r["name"], "res": res[r["kid"]]},
                  open(config.path("result_%s.json" % r["kid"]), "w", encoding="utf-8"), ensure_ascii=False)
    log("ALL_DONE " + json.dumps({r["name"]: res[r["kid"]]["stage"] for r in rows}, ensure_ascii=False))
    return res


if __name__ == "__main__":
    only = sys.argv[1].split(",") if len(sys.argv) > 1 and sys.argv[1] != "-" else None
    lim = int(sys.argv[2]) if len(sys.argv) > 2 else None
    main(only, lim)
