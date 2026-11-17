"""Live DOM scan of the knowledge-study page: authoritative mastery circles."""
import sys, json, time
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from cdp import evaljs
import drive

import config

URL = config.STUDY_URL

JS = r"""
JSON.stringify((function(){var out=[];
document.querySelectorAll('.item-content[knowledgeid]').forEach(function(e){
  var p=e.querySelector('.el-progress');var t=e.querySelector('.item-title');
  out.push([e.getAttribute('knowledgeid'), t?t.getAttribute('title'):'',
            p?p.getAttribute('aria-valuenow'):'?',
            (e.innerText||'').replace(/\s+/g,' ').slice(0,60)]);});
return out;})())
"""


def scan(wait=9):
    drive.require_browser()
    drive.close_targets("knowledgeStudy")
    ws, t = drive.new_tab(URL, wait)
    raw = evaljs(ws, JS, timeout=30)
    try:
        rows = json.loads(raw) if isinstance(raw, str) else []
    except Exception:
        rows = []
    if len(rows) < 40:
        time.sleep(6)
        raw = evaljs(ws, JS, timeout=30)
        try:
            rows = json.loads(raw) if isinstance(raw, str) else []
        except Exception:
            rows = []
    json.dump(rows, open(config.DOM_MASTERY, "w", encoding="utf-8"), ensure_ascii=False)
    drive.close_targets("knowledgeStudy")
    return rows


def report(rows=None):
    rows = rows or json.load(open(config.DOM_MASTERY, encoding="utf-8"))
    done = [r for r in rows if r[2] == "100"]
    rest = [r for r in rows if r[2] not in ("100", "?")]
    free = [r for r in rows if r[2] == "?"]
    print("total=%d done100=%d rest=%d free(no quiz)=%d" % (len(rows), len(done), len(rest), len(free)))
    for r in rest:
        print("  %3s%%  %s" % (r[2], r[1]))
    return done, rest, free


if __name__ == "__main__":
    report(scan())
