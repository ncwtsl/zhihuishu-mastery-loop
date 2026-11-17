"""Authoritative mastery scan of the knowledge-study page, plus a readable report.

The course JSON API (`list-knowledge-theme`) is encrypted with an AES `secretStr`
that can only be captured by hooking the page at load time, so it is not
something a repeatable skill should depend on. Every card, however, prints its
own progress ring as `aria-valuenow` - that is the number the student sees, so
that is the number to trust.

A card with **no ring at all** is a 免考 / 去练习 point: the platform never opened
a practice paper, so mastery cannot reach 100 no matter how many times it is
driven. Those are reported separately and never retried.
"""
import json
import os
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config  # noqa: E402
import drive  # noqa: E402
from cdp import evaljs  # noqa: E402

URL = config.STUDY_URL

JS = r"""
JSON.stringify((function(){
  var out=[];
  document.querySelectorAll('.item-content[knowledgeid], [knowledgeid].item-content').forEach(function(e){
    var p=e.querySelector('.el-progress');
    var t=e.querySelector('.item-title');
    var btn=e.querySelector('button, .btn, .item-btn');
    out.push([
      e.getAttribute('knowledgeid'),
      (t && (t.getAttribute('title') || t.innerText)) || '',
      p ? (p.getAttribute('aria-valuenow') || '?') : '?',
      ((e.innerText||'').replace(/\s+/g,' ')).slice(0,80),
      btn ? (btn.innerText||'').replace(/\s+/g,' ').trim() : ''
    ]);
  });
  return out;
})())
"""

MIN_EXPECTED = 20


def scan(wait=9.0, tries=3):
    """Open the course page and return [[kid, name, valuenow, text, button]].

    A short scan is dangerous in a way that is easy to miss: `batchall` drives
    exactly the points the scan returned, so a half-painted grid silently skips
    the rest of the course while everything downstream reports success. The
    previous scan's row count is therefore kept and used as a floor - if the new
    scan comes back smaller, retry harder and say so out loud.
    """
    drive.require_browser()
    prev = config.load(config.DOM_MASTERY) or []
    floor = len(prev)
    drive.close_targets("knowledgeStudy")
    ws, _t = drive.new_tab(URL, wait)
    rows, uniq = [], []
    for attempt in range(tries + 2):
        raw = evaljs(ws, JS, timeout=30)
        try:
            rows = json.loads(raw) if isinstance(raw, str) else []
        except ValueError:
            rows = []
        # Deduplicate (the selector matches nested nodes on some builds).
        seen = set()
        uniq = []
        for r in rows:
            if not r or not r[0] or r[0] in seen:
                continue
            seen.add(r[0])
            uniq.append(r)
        if len(uniq) >= max(MIN_EXPECTED, floor):
            break
        # The card grid renders lazily; a short list means it is still painting.
        config.sleep(4.0 + attempt * 2.0)
    if floor and len(uniq) < floor:
        print("SCAN_SHORT previous=%d now=%d: the grid came back smaller than last time, "
              "so some points were not seen and would be skipped. Re-run live.py, and "
              "check ZHS_COURSE / login state before trusting this grid." % (floor, len(uniq)),
              flush=True)
    config.dump(uniq, config.DOM_MASTERY)
    drive.close_targets("knowledgeStudy")
    return uniq


def classify(rows):
    """Split a scan into done / todo / no-paper. `?` is no-paper, not zero."""
    done, todo, free = [], [], []
    for r in rows or []:
        kid, name, val = r[0], r[1], r[2]
        if val == "?":
            free.append(r)
            continue
        try:
            m = float(val)
        except (TypeError, ValueError):
            free.append(r)          # unparseable ring == effectively unusable
            continue
        (done if m >= config.TARGET else todo).append((m, r))
    todo.sort(key=lambda x: x[0])
    return [r for _m, r in done], [r for _m, r in todo], free


def report(rows=None, quiet=False):
    if rows is None:
        rows = config.load(config.DOM_MASTERY) or []
    done, todo, free = classify(rows)
    line = ("total=%d done100=%d rest=%d free(no quiz)=%d" % (len(rows), len(done), len(todo), len(free)))
    if not quiet:
        print(line)
        for r in todo:
            print("  %5s%%  %s" % (r[2], r[1]))
        if free:
            print("  免考/无练习卷（平台未开，刷不到 100）:")
            for r in free:
                print("        - %s  [%s]" % (r[1], (r[4] or "无按钮")[:20]))
    return done, todo, free


if __name__ == "__main__":
    if "--cached" in sys.argv and os.path.exists(config.DOM_MASTERY):
        report()
    else:
        report(scan())
