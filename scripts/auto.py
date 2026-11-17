"""Round runner: read quiz -> answer from bank (or stop for manual input) -> submit -> harvest."""
import sys, json, os, re, time, html
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from cdp import evaljs
import quiz, drive, harvest

import config

BANK = config.BANK
STATE = config.path("state.json")


def norm(s):
    if not isinstance(s, str):
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    # the paper sends &gt; &lt; &amp; and friends; unescape BEFORE stripping
    # whitespace or the same question harvested twice yields different keys
    s = html.unescape(s)
    s = s.replace("\u00a0", " ")
    return re.sub(r"\s+", "", s)


def load():
    if os.path.exists(BANK):
        try:
            return json.load(open(BANK, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save(b):
    json.dump(b, open(BANK, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def lookup(bank, stem):
    """Exact normalised match only. Fuzzy prefix matching silently mismatched
    different questions and drove mastery DOWN (observed 20%), so it is gone."""
    k = norm(stem)
    if k and k in bank:
        return bank[k]["letters"]
    return None


def show(q):
    print("---Q%s [%s]" % (q["sort"], q["typeName"]))
    print("STEM:", re.sub(r"\s+", " ", q["stem"] or "")[:300])
    for o in q["opts"]:
        print("  %s. %s" % (o.get("sort"), re.sub(r"\s+", " ", o["text"] or "")[:170]))


def read_round(kid):
    ws = drive.open_quiz(kid)
    time.sleep(2)
    js = ("JSON.stringify((function(){var v=document.querySelector('.reviewTestOrExam').__vue__;"
          "var b=v.$data.baseInfor||{};return {et:b.examTestId,ep:b.examPaperId,qc:b.questionCount};})())")
    base = json.loads(evaljs(ws, js, timeout=20))
    qs = drive.read_all(ws, base["qc"])
    json.dump({"kid": kid, "base": base, "qs": qs}, open(STATE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return base, qs


def do_submit(letters, kid, base):
    ws = quiz.conn()[0]
    quiz.answer_all(ws, letters, tries=4)
    st = quiz.states(ws)["st"]
    bad = [k for k, v in st.items() if v != 2]
    ok = drive.submit(ws)
    time.sleep(3)
    txt = evaljs(ws, "document.body.innerText.slice(0,200)", timeout=15) or ""
    m = re.search(r"(\d+(?:\.\d+)?)%", txt)
    mast = float(m.group(1)) if m else None
    got = []
    try:
        got = harvest.harvest(base["ep"], base["et"], kid, 11)
    except Exception as e:
        print("HARVEST_ERR", type(e).__name__, str(e)[:120])
    bank = load()
    new = 0
    for it in got:
        k = norm(it["stem"])
        if not k or not it["letters"]:
            continue
        if k not in bank:
            new += 1
        bank[k] = {"letters": it["letters"], "type": it["typeName"],
                   "opts": [norm(o)[:60] for o in it["opts"]]}
    save(bank)
    print("SUBMIT", ok, "MASTERY", mast, "BAD", bad, "HARVEST", len(got), "NEW", new, "BANK", len(bank))
    return mast


def read_only(kid):
    base, qs = read_round(kid)
    bank = load()
    unknown = [q for q in qs if not lookup(bank, q["stem"])]
    print("BASE", json.dumps(base, ensure_ascii=False), "UNKNOWN", len(unknown), "OF", len(qs))
    for q in unknown:
        show(q)
    return base, qs, unknown


def answer_now(kid, letters):
    st = json.load(open(STATE, encoding="utf-8"))
    base = st["base"]
    ans = {str(k): (v[0] if isinstance(v, list) and len(v) == 1 else v) for k, v in letters.items()}
    mast = do_submit(ans, kid, base)
    return mast


def loop(kid, max_rounds=8, target=100):
    seen = []
    for i in range(max_rounds):
        base, qs, unknown = read_only(kid)
        if unknown:
            print("STOP_NEED_ANSWERS", [q["sort"] for q in unknown])
            return {"kid": kid, "stage": "need_answers", "rounds": seen,
                    "base": base, "unknown": [q["sort"] for q in unknown]}
        bank = load()
        letters = {}
        for q in qs:
            a = lookup(bank, q["stem"])
            letters[str(q["sort"])] = a[0] if len(a) == 1 else a
        mast = do_submit(letters, kid, base)
        seen.append(mast)
        if mast and mast >= target:
            print("REACHED", mast, "ROUNDS", seen)
            return {"kid": kid, "stage": "done", "mastery": mast, "rounds": seen}
    print("GAVE_UP", seen)
    return {"kid": kid, "stage": "max_rounds", "rounds": seen}


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "read":
        read_only(sys.argv[2])
    elif cmd == "answer":
        print("MASTERY", answer_now(sys.argv[2], json.loads(sys.argv[3])))
    elif cmd == "loop":
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 8
        print(json.dumps(loop(sys.argv[2], n), ensure_ascii=False))
