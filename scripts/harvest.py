"""Open examPreview for one attempt and extract all reference answers with option text."""
import sys, json, time, re
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from cdp import evaljs
import drive

import config

PREVIEW = config.PREVIEW_URL

JS = r"""
JSON.stringify((function(){
  var out=[];
  document.querySelectorAll('.exam-item').forEach(function(el){
    var t=(el.innerText||'').replace(/\u00a0/g,' ');
    out.push(t);
  });
  return out;
})())
"""


def harvest(ep, et, kid, wait=11):
    blocks = []
    for attempt in range(3):
        drive.close_targets("/examPreview/")
        pw, t = drive.new_tab(PREVIEW % (ep, et, kid), wait + attempt * 4)
        raw = evaljs(pw, JS, timeout=25)
        try:
            blocks = json.loads(raw) if isinstance(raw, str) else []
        except Exception:
            blocks = []
        if blocks:
            break
        print("HARVEST_EMPTY try=%d ep=%s et=%s" % (attempt + 1, ep, et), flush=True)
    drive.close_targets("/examPreview/")
    items = []
    for b in blocks:
        lines = [l.strip() for l in b.split("\n") if l.strip()]
        m = re.search(r"参考答案[：:]\s*([^\n]*)", b)
        if not m:
            continue
        ans = m.group(1).strip()
        # type + stem
        tname = None
        for l in lines[:4]:
            if l in ("单选题", "多选题", "判断题", "填空题", "简答题", "计算题"):
                tname = l
                break
        stem = ""
        for i, l in enumerate(lines):
            if re.match(r"^\d+[、.]", l):
                buf = []
                for l2 in lines[i+1:]:
                    if re.match(r"^[A-E][.、]", l2) or l2.startswith("参考答案") or re.match(r"^[对错]$", l2):
                        break
                    buf.append(l2)
                stem = " ".join(buf)
                break
        opts = []
        for l in lines:
            m2 = re.match(r"^([A-E])[.、]\s*(.*)$", l)
            if m2:
                opts.append((m2.group(2), m2.group(1)))
        letters = re.findall(r"[A-E]", ans.replace("、", ","))
        if not letters:
            if ans.startswith("对"):
                letters = ["A"]
            elif ans.startswith("错"):
                letters = ["B"]
        items.append({"typeName": tname, "ansText": ans, "letters": letters,
                      "stem": stem, "opts": [o[0] for o in opts], "raw": b[:900]})
    return items


if __name__ == "__main__":
    ep, et, kid = sys.argv[1], sys.argv[2], sys.argv[3]
    for it in harvest(ep, et, kid):
        print(it["letters"], "|", it["typeName"], "|", it["stem"][:80])
        print("   opts:", " / ".join(o[:40] for o in it["opts"]))
