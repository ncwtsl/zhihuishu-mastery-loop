"""In-page-batched driver: one evaljs per phase instead of per question."""
import sys, os, json, re, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from cdp import evaljs, page_ws, WS
import quiz, drive, harvest, auto

import config

JS = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "fast.js"), encoding="utf-8").read()


def inject(ws):
    evaljs(ws, JS, timeout=20)


def _j(x):
    if isinstance(x, str):
        return json.loads(x)
    return x


def read_all(ws, n):
    return _j(evaljs(ws, "window.__F.readAll(%d)" % n, timeout=90))


def answer_all(ws, plan):
    return _j(evaljs(ws, "window.__F.answerAll(%s)" % json.dumps(plan), timeout=120))


BASE_JS = ("JSON.stringify((function(){var el=document.querySelector('.reviewTestOrExam');"
           "if(!el||!el.__vue__)return {nc:1};var b=el.__vue__.$data.baseInfor||{};"
           "return {et:b.examTestId,ep:b.examPaperId,qc:b.questionCount};})())")


def get_base(ws, tries=8):
    """baseInfor is empty until the paper finishes rendering; poll instead of KeyError."""
    for _ in range(tries):
        b = _j(evaljs(ws, BASE_JS, timeout=20))
        if isinstance(b, dict) and b.get("qc"):
            return b
        time.sleep(1.5)
    raise RuntimeError("BASE_EMPTY")


def open_read(kid, tries=3):
    for attempt in range(tries):
        try:
            ws = drive.open_quiz(kid)
            time.sleep(1.5)
            inject(ws)
            base = get_base(ws)
            qs = read_all(ws, base["qc"])
            if len(qs) == base["qc"]:
                return ws, base, qs
            print("READ_SHORT %d/%d retry" % (len(qs), base["qc"]), flush=True)
        except Exception as e:
            print("OPEN_RETRY attempt=%d %s %s" % (attempt + 1, type(e).__name__, str(e)[:70]), flush=True)
            try:
                drive.close_targets("learnPage")
                drive.close_targets("studentReviewTestOrExam")
            except Exception:
                pass
        time.sleep(2)
    raise RuntimeError("OPEN_FAILED")


def submit_only(ws, kid, base):
    # drive.submit returns the /point/ url only when the submit really navigated.
    # Reading the page otherwise picks up the answer-progress percentage of the
    # still-open quiz page and records a bogus 60/80 instead of a mastery value.
    url = drive.submit(ws)
    if not url:
        print("SUBMIT_FAILED (no /point/ navigation)", flush=True)
        return None, [], 0, None, None
    time.sleep(2.5)
    txt = evaljs(ws, "document.body.innerText.slice(0,900)", timeout=15) or ""
    m = re.search(r"(\d+(?:\.\d+)?)%", txt)
    mast = float(m.group(1)) if m else None
    mc = re.search(r"已答对\s*(\d+)", txt)
    mt = re.search(r"总题数\s*(\d+)", txt)
    correct = int(mc.group(1)) if mc else None
    total = int(mt.group(1)) if mt else None
    # Every submit navigates the quiz tab to /point/. Leaving those tabs open
    # piles up dozens of them and slows every CDP call, so reap them here.
    try:
        drive.close_targets("/point/")
    except Exception as e:
        print("CLEAN_ERR", type(e).__name__, str(e)[:60], flush=True)
    got = []
    try:
        got = harvest.harvest(base["ep"], base["et"], kid, 9)
    except Exception as e:
        print("HARVEST_ERR", type(e).__name__, str(e)[:100], flush=True)
    bank = auto.load()
    new = 0
    for it in got:
        k = auto.norm(it["stem"])
        if not k or not it["letters"]:
            continue
        if k not in bank:
            new += 1
        bank[k] = {"letters": it["letters"], "type": it["typeName"],
                   "opts": [auto.norm(o)[:60] for o in it["opts"]]}
    auto.save(bank)
    return mast, got, new, correct, total


def round_once(kid, plan=None):
    ws, base, qs = open_read(kid)
    bank = auto.load()
    if plan is None:
        plan, unknown = {}, []
        for q in qs:
            a = auto.lookup(bank, q["stem"])
            if a:
                plan[str(q["sort"])] = a
            else:
                unknown.append(q)
        if unknown:
            json.dump({"kid": kid, "base": base, "qs": qs},
                      open(config.path("state_%s.json" % kid), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
            print("NEED_ANSWERS", [q["sort"] for q in unknown], flush=True)
            for q in unknown:
                print("---Q%s [%s]" % (q["sort"], q["typeName"]), flush=True)
                print("STEM:", re.sub(r"\s+", " ", q["stem"] or "")[:300], flush=True)
                for o in q["opts"]:
                    print("  %s. %s" % (o.get("sort"), re.sub(r"\s+", " ", o["text"] or "")[:170]), flush=True)
            return None, base, qs
    else:
        plan = {str(k): (v if isinstance(v, str) else "".join(v)) for k, v in plan.items()}
    rep = answer_all(ws, plan)
    bad = [k for k, v in rep.items() if not str(v).endswith("->2")]
    mast, got, new = submit_only(ws, kid, base)
    print("REP", json.dumps(rep, ensure_ascii=False), flush=True)
    print("MASTERY", mast, "BAD", bad, "HARVEST", len(got), "NEW", new, flush=True)
    return mast, base, qs


def loop(kid, target=100, maxr=8):
    hist = []
    for i in range(maxr):
        mast, _, _ = round_once(kid)
        if mast is None:
            print("STOP_NEED_ANSWERS", flush=True)
            return {"stage": "need_answers", "hist": hist}
        hist.append(mast)
        if mast >= target:
            return {"stage": "done", "mastery": mast, "hist": hist}
    return {"stage": "maxr", "hist": hist}


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "read":
        ws, base, qs = open_read(sys.argv[2])
        bank = auto.load()
        print("BASE", json.dumps(base, ensure_ascii=False))
        for q in qs:
            print("---Q%s [%s] known=%s" % (q["sort"], q["typeName"], auto.lookup(bank, q["stem"])), flush=True)
            print("STEM:", re.sub(r"\s+", " ", q["stem"] or "")[:300], flush=True)
            for o in q["opts"]:
                print("  %s. %s" % (o.get("sort"), re.sub(r"\s+", " ", o["text"] or "")[:170]), flush=True)
    elif cmd == "answer":
        kid = sys.argv[2]
        plan = json.loads(sys.argv[3])
        ws = quiz.conn()[0]
        inject(ws)
        js = ("JSON.stringify((function(){var b=document.querySelector('.reviewTestOrExam').__vue__.$data.baseInfor||{};"
              "return {et:b.examTestId,ep:b.examPaperId,qc:b.questionCount};})())")
        st = {"base": json.loads(evaljs(ws, js, timeout=20))}
        rep = answer_all(ws, {str(k): (v if isinstance(v, str) else "".join(v)) for k, v in plan.items()})
        bad = [k for k, v in rep.items() if not str(v).endswith("->2")]
        mast, got, new = submit_only(ws, kid, st["base"])
        print("BASE", json.dumps(st["base"], ensure_ascii=False))
        print("REP", json.dumps(rep, ensure_ascii=False), "BAD", bad, "MASTERY", mast, "HARVEST", len(got), "NEW", new)
    elif cmd == "loop":
        print(json.dumps(loop(sys.argv[2]), ensure_ascii=False))
