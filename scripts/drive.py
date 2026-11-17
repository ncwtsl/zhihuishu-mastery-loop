"""Robust driver for one attempt: open quiz, read questions, answer, submit, harvest answers."""
import sys, json, time, re
from cdp import WS, page_ws, evaljs
import quiz

import config

LEARN = config.LEARN_URL
PREVIEW = config.PREVIEW_URL


def _targets():
    try:
        return json.loads(__import__("urllib.request").request.urlopen(
            "http://127.0.0.1:%d/json/list" % config.PORT, timeout=10).read().decode("utf-8", "replace"))
    except Exception:
        return []


def require_browser():
    """Fail with an actionable message instead of IndexError on list[0]."""
    pages = [t for t in _targets() if t.get("type") == "page"]
    if not pages:
        raise RuntimeError(
            "CDP unreachable on port %d. Launch Edge with a debugging port first:\n"
            "  msedge.exe --remote-debugging-port=%d --user-data-dir=<junction> --no-first-run\n"
            "and log in to zhihuishu by hand. See SKILL.md 前置条件."
            % (config.PORT, config.PORT))
    return pages


def close_targets(substr):
    require_browser()
    mw = WS(_targets()[0]["webSocketDebuggerUrl"])
    for t in _targets():
        if t.get("type") == "page" and substr in (t.get("url") or ""):
            try:
                mw.call("Target.closeTarget", {"targetId": t["id"]}, timeout=15)
            except Exception:
                pass


def new_tab(url, wait=9):
    pages = require_browser()
    mw = WS(pages[-1]["webSocketDebuggerUrl"])
    tid = mw.call("Target.createTarget", {"url": url}, timeout=25)["targetId"]
    time.sleep(wait)
    for t in _targets():
        if t.get("id") == tid:
            return WS(t["webSocketDebuggerUrl"]), t
    raise RuntimeError("tab not found")


def open_quiz(kid, wait=9):
    """Fresh tab -> learnPage -> 去提升 -> 去提升 → . Returns quiz WS."""
    close_targets("learnPage")
    close_targets("studentReviewTestOrExam")
    time.sleep(1)
    lw, _ = new_tab(LEARN % kid, wait)
    time.sleep(3)
    evaljs(lw, "(function(){var b=document.querySelector('.simplified-mastery__action');if(b)b.click();})()", timeout=20)
    time.sleep(3)
    evaljs(lw, "(function(){var b=document.querySelector('.improve-btn');if(b)b.click();})()", timeout=20)
    for _ in range(20):
        time.sleep(2)
        try:
            return quiz.conn()[0]
        except Exception:
            continue
    raise RuntimeError("quiz page did not open")


def read_all(ws, n):
    out = []
    for i in range(1, n + 1):
        quiz.jump(ws, i)
        time.sleep(1.1)
        out.append(quiz.read_question(ws))
    return out


def _click_submit(ws):
    return evaljs(ws, """(function(){
      var b=document.querySelector('.reviewDone');
      if(!b) return 'NO_BTN';
      if(b.disabled) return 'DISABLED';
      b.click();
      return 'CLICKED';
    })()""", timeout=20)


def _confirm_dialog(ws):
    """The submit flow sometimes shows an el-message-box asking to confirm."""
    return evaljs(ws, r"""(function(){
      var btns=document.querySelectorAll('.el-message-box__btns button, .el-dialog__footer button');
      for(var i=0;i<btns.length;i++){
        var t=(btns[i].innerText||'').trim();
        if(/\u786e\s*\u5b9a|\u63d0\s*\u4ea4|\u7ee7\s*\u7eed/.test(t)){btns[i].click();return 'OK:'+t;}
      }
      return 'NO_DIALOG';
    })()""", timeout=20)


def submit(ws, tries=3):
    """Click submit and wait for the /point/ result page.

    The button click is occasionally swallowed (element mid-render, or a confirm
    dialog appearing), so retry the click and accept any confirm dialog.
    """
    for attempt in range(tries):
        r = _click_submit(ws)
        time.sleep(1.5)
        _confirm_dialog(ws)
        for _ in range(9):
            time.sleep(2)
            try:
                u = evaljs(ws, "location.href", timeout=15)
            except Exception:
                u = None
            if isinstance(u, str) and "/point/" in u:
                return u
        print("SUBMIT_RETRY attempt=%d click=%s" % (attempt + 1, r), flush=True)
    return None
