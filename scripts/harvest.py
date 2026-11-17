"""Open examPreview for one attempt and extract every reference answer.

Two things here are load-bearing and were both learned the hard way:

1. `sort` is the paper position (1-based, in DOM order). Without it a harvested
   answer cannot be attributed to the question that got it wrong, which is what
   the self-audit in `batchall.run_point` depends on.
2. `对/错` on a 判断题 must be translated into the actual option letters of the
   paper. Storing the literal string "对" makes every 判断题 lookup miss.
"""
import json
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from cdp import evaljs  # noqa: E402
import drive  # noqa: E402

import config  # noqa: E402

PREVIEW = config.PREVIEW_URL

TYPE_NAMES = ("单选题", "多选题", "不定项选择题", "判断题", "填空题", "简答题", "计算题", "论述题")

JS = r"""
JSON.stringify((function(){
  var out=[];
  document.querySelectorAll('.exam-item').forEach(function(el,i){
    out.push([i+1,(el.innerText||'').replace(/\u00a0/g,' ')]);
  });
  return out;
})())
"""


def _stem_of(block):
    """The question text: the first line after the `1、` marker, up to the options."""
    lines = [l.strip() for l in block.split("\n") if l.strip()]
    for i, l in enumerate(lines):
        if re.match(r"^\d+[、.]", l):
            rest = re.sub(r"^\d+[、.]\s*", "", l)
            if rest:
                return rest
            buf = []
            for l2 in lines[i + 1:]:
                if re.match(r"^[A-F][.、]", l2) or l2.startswith("参考答案") or re.match(r"^[对错]$", l2):
                    break
                buf.append(l2)
            return " ".join(buf)
    return ""


def _options(lines):
    """[(letter, text)] in page order, plus the 判断题 option wording if present."""
    opts = []
    for l in lines:
        m = re.match(r"^([A-F])[.、]\s*(.*)$", l)
        if m:
            opts.append((m.group(1), m.group(2).strip()))
    return opts


def _judge_letters(opts, ans_text):
    """Map 对/错 onto the paper's own option letters.

    A 判断题 paper renders two options, conventionally A=对 B=错, but the labels
    are what the page prints, so read them instead of assuming. If the page
    prints only `对`/`错` as the answer with no option rows, fall back to A/B.
    """
    want = "对" if ans_text.startswith("对") else "错"
    for letter, text in opts:
        t = text.strip()
        if t.startswith("对") and want == "对":
            return [letter]
        if t.startswith("错") and want == "错":
            return [letter]
        if t in ("正确", "√") and want == "对":
            return [letter]
        if t in ("错误", "×") and want == "错":
            return [letter]
    return ["A"] if want == "对" else ["B"]


def parse_block(sort, block):
    lines = [l.strip() for l in block.split("\n") if l.strip()]
    m = re.search(r"参考答案[：:]\s*([^\n]*)", block)
    if not m:
        return None
    ans = m.group(1).strip()
    tname = None
    for l in lines[:5]:
        if l in TYPE_NAMES:
            tname = l
            break
    opts = _options(lines)
    if tname == "判断题" or (not tname and re.search(r"^[对错]$", ans)):
        letters = _judge_letters(opts, ans)
    else:
        letters = re.findall(r"[A-F]", ans.replace("、", ",").replace("，", ","))
    return {
        "sort": str(sort),
        "typeName": tname,
        "ansText": ans,
        "letters": sorted(set(letters)),
        "stem": _stem_of(block),
        "opts": [o[1] for o in opts],
        "raw": block[:900],
    }


def harvest(ep, et, kid, wait=11):
    """Open the preview for this attempt and return [{sort, stem, letters, ...}]."""
    blocks = []
    for attempt in range(3):
        drive.close_targets("/examPreview/")
        pw, _t = drive.new_tab(PREVIEW % (ep, et, kid), wait + attempt * 4)
        raw = evaljs(pw, JS, timeout=25)
        try:
            blocks = json.loads(raw) if isinstance(raw, str) else []
        except ValueError:
            blocks = []
        if blocks:
            break
        print("HARVEST_EMPTY try=%d ep=%s et=%s" % (attempt + 1, ep, et), flush=True)
    drive.close_targets("/examPreview/")
    items = []
    for pair in blocks:
        try:
            sort, block = pair
        except (TypeError, ValueError):
            continue
        it = parse_block(sort, block)
        if it and it["stem"] and it["letters"]:
            items.append(it)
    return items


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("usage: python harvest.py <examPaperId> <examTestId> <knowledgeId>")
        raise SystemExit(2)
    for it in harvest(sys.argv[1], sys.argv[2], sys.argv[3]):
        print("Q%s %-4s %s | %s" % (it["sort"], "".join(it["letters"]), it["typeName"],
                                    it["stem"][:70]))
        if it["opts"]:
            print("    opts:", " / ".join(o[:36] for o in it["opts"]))
