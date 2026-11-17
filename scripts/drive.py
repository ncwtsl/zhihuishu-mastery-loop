"""Tab lifecycle for one attempt: open the paper, submit it, reap the tabs.

The single most expensive lesson in this file: the quiz tab can only be
submitted while it is the one showing the paper, and every submit navigates that
tab to `/point/`. Leaving those tabs behind is what eventually makes the browser
answer 500 on every new WebSocket handshake (43 were observed in one run).
"""
import json
import re
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import config  # noqa: E402
from cdp import WS, connect, ev, evaljs, targets  # noqa: E402
import quiz  # noqa: E402

LEARN = config.LEARN_URL
PREVIEW = config.PREVIEW_URL

# Tabs this skill owns; anything matching is disposable between attempts.
MINE = ("learnPage", "studentReviewTestOrExam", "/point/", "/examPreview/", "knowledgeStudy")


def require_browser():
    """Fail with an actionable message instead of IndexError on list[0]."""
    try:
        pages = targets()
    except Exception as e:
        raise RuntimeError(
            "CDP unreachable on port %d (%s).\n"
            "Launch Edge with the debugging port first:\n"
            "  ./scripts/launch_edge.sh %d\n"
            "then log in to zhihuishu by hand. See SKILL.md 前置条件."
            % (config.PORT, type(e).__name__, config.PORT))
    if not pages:
        raise RuntimeError("CDP is up on port %d but has no page tabs; open any page." % config.PORT)
    return pages


def _browser_ws():
    v = json.loads(urllib.request.urlopen(
        "http://127.0.0.1:%d/json/version" % config.PORT, timeout=10).read().decode("utf-8", "replace"))
    return v["webSocketDebuggerUrl"]


def close_targets(substr, keep=0):
    """Close pages whose URL contains `substr`. Returns how many were closed."""
    try:
        pages = [t for t in targets() if substr in (t.get("url") or "")]
    except Exception:
        return 0
    if keep:
        pages = pages[keep:]
    if not pages:
        return 0
    try:
        mw = connect(_browser_ws(), tries=3)
    except Exception:
        return 0
    n = 0
    try:
        for t in pages:
            try:
                mw.call("Target.closeTarget", {"targetId": t["id"]}, timeout=15)
                n += 1
            except Exception:
                pass
    finally:
        mw.close()
    return n


def reap(limit=14):
    """Keep the browser from drowning: if it holds too many tabs, drop ours.

    Only tabs this skill opened are candidates, newest kept. The user's own tabs
    (mail, docs, whatever they were reading) are never touched.
    """
    try:
        pages = targets()
    except Exception:
        return 0
    if len(pages) <= limit:
        return 0
    mine = [t for t in pages if any(m in (t.get("url") or "") for m in MINE)]
    excess = len(pages) - limit
    closed = 0
    for t in mine[:excess]:
        closed += close_targets((t.get("url") or "").split("?")[0][-28:], keep=0)
    return closed


def new_tab(url, wait=9.0):
    """Create a tab and return (ws, target).

    Waits for the target to appear rather than sleeping a flat 9 s, and retries
    the handshake: `Target.createTarget` succeeds long before the tab is
    attachable, and a busy browser 500s the first attempt.
    """
    require_browser()
    pages = targets()
    mw = connect(pages[-1]["webSocketDebuggerUrl"], tries=3)
    try:
        tid = mw.call("Target.createTarget", {"url": url}, timeout=25)["targetId"]
    finally:
        mw.close()
    deadline = time.time() + max(6.0, wait)
    ws_url = None
    while time.time() < deadline:
        for t in targets():
            if t.get("id") == tid:
                ws_url = t["webSocketDebuggerUrl"]
                break
        if ws_url:
            break
        config.sleep(0.4)
    if not ws_url:
        raise RuntimeError("tab never appeared: %s" % url[:90])
    ws = connect(ws_url, tries=5, base_delay=1.5)
    # Let the SPA boot; poll for a real document instead of a fixed sleep.
    for _ in range(30):
        try:
            ready = evaljs(ws, "document.readyState", timeout=10)
        except Exception:
            ready = None
        if ready in ("interactive", "complete"):
            return ws, {"id": tid}
        config.sleep(0.5)
    return ws, {"id": tid}


def open_quiz(kid, wait=9.0):
    """Fresh tab -> learnPage -> 去提升 -> 去提升. Returns (ws, base).

    Both clicks are conditional: on a point that already has a paper the second
    button is `.improve-btn`; on a 免考 point neither exists and the caller must
    report that instead of spinning. `base` is read here so callers do not have
    to poll for `baseInfor` themselves.
    """
    close_targets("learnPage")
    close_targets("studentReviewTestOrExam")
    config.sleep(0.8)
    lw, _ = new_tab(LEARN % kid, wait)
    try:
        for _ in range(20):
            hit = evaljs(lw, "!!document.querySelector('.simplified-mastery__action')", timeout=10)
            if hit:
                break
            config.sleep(1.0)
        evaljs(lw, "(function(){var b=document.querySelector('.simplified-mastery__action');if(b)b.click();})()", timeout=20)
        config.sleep(2.0)
        hit = evaljs(lw, "!!document.querySelector('.improve-btn')", timeout=10)
        if not hit:
            # 免考 / 平台未开练习卷: no paper exists for this point.
            raise NoPaper(kid)
        evaljs(lw, "(function(){var b=document.querySelector('.improve-btn');if(b)b.click();})()", timeout=20)
    except NoPaper:
        close_targets("learnPage")
        raise
    for _ in range(25):
        config.sleep(1.4)
        try:
            ws, _t = quiz.conn()
        except Exception:
            continue
        try:
            return ws, quiz.get_base(ws)
        except Exception:
            continue
    raise RuntimeError("quiz page did not open for %s" % kid)


class NoPaper(RuntimeError):
    """The knowledge point has no practice paper (免考 / 去练习)."""


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
        if(/\u786e\s*\u5b9a|\u63d0\s*\u4ea4|\u7ee7\s*\u7eed|\u786e\s*\u8ba4/.test(t)){btns[i].click();return 'OK:'+t;}
      }
      return 'NO_DIALOG';
    })()""", timeout=20)


def submit(ws, tries=3, wait=18.0):
    """Click submit and wait for the /point/ result page.

    Returns the /point/ URL, or None when the page never navigated. Callers must
    treat None as failure: reading the still-open quiz page yields the answering
    progress (83.3) and that number has been mistaken for mastery before.
    """
    for attempt in range(tries):
        r = _click_submit(ws)
        config.sleep(1.4)
        _confirm_dialog(ws)
        deadline = time.time() + wait
        while time.time() < deadline:
            config.sleep(1.2)
            try:
                u = evaljs(ws, "location.href", timeout=15)
            except Exception:
                u = None
            if isinstance(u, str) and "/point/" in u:
                return u
        print("SUBMIT_RETRY attempt=%d click=%s" % (attempt + 1, r), flush=True)
    return None


def point_text(ws, limit=1400):
    """Body text of the /point/ page, enough to read mastery + 已答对/总题数."""
    try:
        return evaljs(ws, "document.body.innerText.slice(0,%d)" % limit, timeout=15) or ""
    except Exception:
        return ""


def mastery_from_page(ws):
    """Read mastery off the /point/ page. Returns dict from bank.parse_point."""
    import bank
    for _ in range(6):
        txt = point_text(ws)
        got = bank.parse_point(txt)
        if got["mastery"] is not None:
            return got
        config.sleep(1.5)
    return bank.parse_point(point_text(ws))
