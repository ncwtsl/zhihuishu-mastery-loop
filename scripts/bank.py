"""Answer bank: normalisation, lookup, near-miss diagnosis, point-page parsing.

Deliberately browser-free. Everything the skill's correctness rests on lives
here so `selftest.py` can prove it offline, without Edge, CDP or a login.
"""
import difflib
import html
import json
import os
import re
import sys

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
NBSP = "\u00a0"

# The paper renders options A..F (E shows up on image-heavy papers, and 判断题
# answers are 对/错 rather than a letter at all).
LETTERS = "ABCDEF"


def norm(s):
    """Bank key for a stem.

    Order matters: strip tags, THEN unescape entities, THEN collapse whitespace.
    Unescaping first would let `&lt;b&gt;` turn into a tag that the strip regex
    then eats, and the same question would key differently on two pages.
    """
    if not isinstance(s, str):
        return ""
    s = TAG_RE.sub(" ", s)
    s = html.unescape(s)
    s = s.replace(NBSP, " ")
    return WS_RE.sub("", s)


def letters_of(entry):
    """Coerce whatever is stored into a sorted letter string: 'AC'."""
    if isinstance(entry, dict):
        v = entry.get("letters")
    else:
        v = entry
    if not v:
        return ""
    if isinstance(v, str):
        v = list(v)
    out = sorted({str(x).strip().upper() for x in v if str(x).strip()})
    return "".join(out)


def load(path):
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def save(bank, path):
    """Atomic write: a killed run must never leave a truncated 200-entry bank."""
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(bank, f, ensure_ascii=False, indent=1, sort_keys=True)
    os.replace(tmp, path)


def lookup(bank, stem):
    """Exact normalised match, returning a letter string or None.

    Fuzzy prefix matching is deliberately absent: it once paired different
    questions and drove mastery DOWN to 20%. Use `near()` to *report* a
    suspicious neighbour, never to answer from it.
    """
    k = norm(stem)
    if not k:
        return None
    return letters_of(bank.get(k)) or None


def put(bank, stem, letters, type_name=None, opts=None, source=None):
    """Insert/refresh one entry. Returns True when the key was new.

    Updating MERGES: a manual correction that names only the letters must not
    wipe the type and options that harvest already recorded for the same key,
    otherwise the next `stats`/diagnosis sees an entry with no type at all.
    """
    k = norm(stem)
    letters = letters_of(letters)
    if not k or not letters:
        return False
    new = k not in bank
    old = bank.get(k) if isinstance(bank.get(k), dict) else {}
    entry = dict(old)
    entry["letters"] = list(letters)
    entry["type"] = type_name or old.get("type") or ""
    if opts:
        entry["opts"] = [norm(o)[:60] for o in opts]
    if source:
        entry["src"] = source
    bank[k] = entry
    return new


def near(bank, stem, n=3, cutoff=0.80):
    """Closest existing keys, for diagnosing a lookup that keeps missing.

    A hit here means the *question* is in the bank but under a different key -
    usually an entity/whitespace variant. Print both, fix `norm()`, do not guess.
    """
    k = norm(stem)
    if not k:
        return []
    keys = difflib.get_close_matches(k, list(bank.keys()), n=n, cutoff=cutoff)
    return [(kk, letters_of(bank.get(kk))) for kk in keys]


def parse_point(body):
    """Read mastery/correct/total/best out of the /point/ result page text.

    `body` is the text that starts with the mastery circle. Mastery is the
    percentage sitting directly above the literal 掌握度 label - NOT the first
    `%` on the page, and never the answering-progress value from the quiz page
    (`.answer-pro .pro`, which reads 83.3 and is a different thing entirely).
    """
    out = {"mastery": None, "correct": None, "total": None, "best": None}
    if not isinstance(body, str) or not body:
        return out
    # The mastery circle prints "100%" and then the label 掌握度 on the next line.
    m = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%\s*\n?\s*掌握度", body)
    if not m:
        # Single-line DOM dump: "100% 掌握度".
        m = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%\s*掌握度", body)
    if not m:
        # Last resort: first percentage, but only if 掌握度 appears at all.
        if "掌握度" in body:
            m = re.search(r"(\d{1,3}(?:\.\d+)?)\s*%", body)
    if m:
        out["mastery"] = float(m.group(1))
    mc = re.search(r"已答对\s*(\d+)", body)
    mt = re.search(r"总题数\s*(\d+)", body)
    mb = re.search(r"最好成绩\s*(\d{1,3}(?:\.\d+)?)\s*%", body)
    out["correct"] = int(mc.group(1)) if mc else None
    out["total"] = int(mt.group(1)) if mt else None
    out["best"] = float(mb.group(1)) if mb else None
    return out


def stalled(history, patience=3):
    """True when the last `patience` rounds all scored the same.

    A run that repeats 76.0 five times is not unlucky, it is wrong: the plan is
    identical, so the paper is regenerated from the same bank. Stop and probe
    (probe.py) or ask the user instead of burning the round budget.
    """
    if not history or len(history) < patience:
        return False
    tail = history[-patience:]
    if any(v is None for v in tail):
        return False
    return len(set(tail)) == 1


# --------------------------------------------------------------------- CLI
# The one case the loop genuinely cannot solve on its own is a question whose
# options are images: no OCR here, so the only cheap move is to ask the user
# "题3选什么" and write the letter down. That used to mean pasting a Python
# snippet; it is a single command now, and the command prints the key it wrote so
# a mismatch (entity/whitespace variant) is visible immediately.
def _say(msg):
    """Print without dying on a cp936/cp1252 console.

    The stems are Chinese, and a default Windows console encoding turns them into
    mojibake or a UnicodeEncodeError *after* the bank was already written — which
    looks like the write failed when it did not.
    """
    try:
        print(msg)
    except UnicodeEncodeError:
        enc = (sys.stdout.encoding or "utf-8")
        print(msg.encode(enc, "replace").decode(enc, "replace"))


def _recover(s):
    """Undo a cp936-style mis-decode of UTF-8 argv/stdin.

    Windows hands a native program its arguments as bytes converted with the ANSI
    code page, so a Chinese stem typed in a UTF-8 terminal arrives as mojibake —
    and a mojibake stem keys nothing, which shows up much later as a mystery MISS
    on a question the user just corrected. `os.fsencode` returns those original
    bytes, so decoding them as UTF-8 recovers the intended text whenever it
    really was UTF-8.
    """
    if not isinstance(s, str) or s.isascii():
        return s
    for enc in ("utf-8",):
        try:
            return os.fsencode(s).decode(enc)
        except (UnicodeDecodeError, UnicodeEncodeError, LookupError):
            pass
    return s


def _stdin_text():
    """Read stdin as bytes and decode it the way the terminal actually typed it.

    A pipe on a Chinese Windows box hands over cp936 bytes; a UTF-8 terminal hands
    over UTF-8. `sys.stdin.read()` picks one codec and silently corrupts the other
    — and `errors="replace"` on this path used to poison the bank with lone
    surrogates that then crashed `json.dump`. Try the plausible codecs, keep the
    first that decodes cleanly.
    """
    buf = getattr(sys.stdin, "buffer", None)
    data = buf.read() if buf is not None else sys.stdin.read().encode("utf-8", "replace")
    if isinstance(data, str):
        return data
    for enc in ("utf-8", "gbk", "cp936"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "replace")


def _stem_arg(raw):
    """`-` reads the stem from stdin.

    Asking the user to paste a stem holding `>`, `&` or newlines into a shell
    mangles it; a heredoc does not. Since a mangled stem silently keys nothing,
    this is the difference between a working correction and a mystery MISS.
    """
    if raw == "-":
        return _stdin_text()
    return _recover(raw)


def _clean(s):
    """Drop lone surrogates so a bad decode can never poison the bank file."""
    if not isinstance(s, str):
        return s
    return s.encode("utf-8", "replace").decode("utf-8", "replace")


def _cli(argv):
    import argparse

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(
        prog="bank.py",
        description="查看/补写题库（$ZHS_DATA/answers.json），不需要浏览器")
    ap.add_argument("--bank", default=None, help="题库路径，默认 $ZHS_DATA/answers.json")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_put = sub.add_parser("put", help="手工写入一条答案（图片题、人工确认过的题）")
    p_put.add_argument("stem", help="题干；给 - 则从标准输入读（含 > & 换行时更安全）")
    p_put.add_argument("letters", help="答案字母，如 C / AC")
    p_put.add_argument("--type", default=None, help="题型，如 判断题 / 单选题")
    p_put.add_argument("--opt", action="append", default=None,
                       help="选项文案，可重复给多次（判断题建议给，便于日后核对）")

    p_get = sub.add_parser("get", help="按题干查一条；未命中返回码 1 并列出最接近的")
    p_get.add_argument("stem")

    p_near = sub.add_parser("near", help="题库里最接近的几条（诊断 key 不一致）")
    p_near.add_argument("stem")
    p_near.add_argument("-n", type=int, default=3)

    sub.add_parser("stats", help="题库规模与题型/答案分布")

    a = ap.parse_args(argv)
    path = a.bank or _default_bank()
    b = load(path)

    if a.cmd == "put":
        stem = _clean(_stem_arg(a.stem))
        new = put(b, stem, a.letters, _recover(a.type),
                  [_recover(o) for o in (a.opt or [])] or None, source="manual")
        if not new and not letters_of(b.get(norm(stem))):
            _say("REFUSED empty stem or letters")
            return 2
        save(b, path)
        _say("%s %s -> %s   (bank=%d)"
             % ("NEW" if new else "UPDATED", norm(stem)[:60],
                letters_of(b.get(norm(stem))), len(b)))
        return 0
    if a.cmd == "get":
        stem = _clean(_stem_arg(a.stem))
        hit = lookup(b, stem)
        if hit:
            _say("%s  %s" % (hit, norm(stem)[:70]))
            return 0
        _say("MISS %s" % norm(stem)[:70])
        for k, v in near(b, stem):
            _say("  near %s  %s" % (v, k[:70]))
        return 1
    if a.cmd == "near":
        stem = _clean(_stem_arg(a.stem))
        rows = near(b, stem, n=a.n)
        if not rows:
            _say("no neighbour above cutoff; the question is genuinely absent")
            return 1
        for k, v in rows:
            _say("%s  %s" % (v, k[:80]))
        return 0
    # stats
    types, answers = {}, {}
    for v in b.values():
        t = (v.get("type") if isinstance(v, dict) else "") or "?"
        types[t] = types.get(t, 0) + 1
        let = letters_of(v)
        answers[let] = answers.get(let, 0) + 1
    _say("bank %d entries  %s" % (len(b), path))
    for t, n in sorted(types.items(), key=lambda kv: -kv[1]):
        _say("  type   %-8s %d" % (t, n))
    for let, n in sorted(answers.items(), key=lambda kv: -kv[1])[:12]:
        _say("  answer %-6s %d" % (let or "(empty)", n))
    bad = [k for k, v in b.items() if not letters_of(v)]
    if bad:
        _say("WARN %d entr(ies) without usable letters, e.g. %s" % (len(bad), bad[0][:60]))
    return 0


def _default_bank():
    """$ZHS_DATA/answers.json when config is importable, else ../data/answers.json.

    Imported lazily so `bank.py` stays usable on its own (it is the browser-free
    core, and `selftest.py` imports it before anything else sets up config).
    """
    try:
        import config  # noqa: F401 - only for its resolved BANK path
        return config.BANK
    except Exception:
        import os
        here = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(os.path.dirname(here), "data", "answers.json")


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
