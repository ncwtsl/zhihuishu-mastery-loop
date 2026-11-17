"""Preflight: reachability, login state, course page, and the page's own selectors.

The point of this file is to fail *here*, with one actionable sentence, instead of
failing inside a 40-minute unattended run as `IndexError` on an empty tab list.

Checks, in the order that finds problems fastest:
  1. CDP port reachable and a browser is listening
  2. a tab exists on the zhihuishu origin (and is not a login page)
  3. the course URL for this ZHS_COURSE/ZHS_CLASS resolves to a real study page
  4. the three selectors the driver depends on are actually present:
     `.item-content[knowledgeid]`, `.el-progress`, `.simplified-mastery__action`
  5. the bank parses and its entries look sane
  6. tab hygiene: warn when this skill's own tabs have piled up

The data directory is checked first of all, because a read-only data dir fails
every path below it and costs nothing to rule out.
"""
import json
import os
import sys
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import bank  # noqa: E402
import cdp  # noqa: E402
import config  # noqa: E402
import drive  # noqa: E402

OK, WARN, FAIL = "OK  ", "WARN", "FAIL"
_state = {"failed": False, "warned": False}


def say(level, msg):
    print("%s %s" % (level, msg), flush=True)
    if level is FAIL:
        _state["failed"] = True
    elif level is WARN:
        _state["warned"] = True


def check_port():
    url = "http://127.0.0.1:%d/json/version" % config.PORT
    try:
        raw = urllib.request.urlopen(url, timeout=6).read().decode("utf-8", "replace")
        info = json.loads(raw)
    except Exception as e:
        say(FAIL, "CDP not reachable on port %d (%s)" % (config.PORT, type(e).__name__))
        say("", "  fix: ./scripts/launch_edge.sh %d" % config.PORT)
        say("", "       if Edge is already running without the flag, close it first -")
        say("", "       a running instance ignores the new launch arguments.")
        return None
    say(OK, "CDP up on %d: %s" % (config.PORT, (info.get("Browser") or "?")[:60]))
    return info


def check_tabs():
    try:
        pages = drive.targets()
    except Exception as e:
        say(FAIL, "cannot list tabs: %s" % e)
        return []
    zs = [p for p in pages if "zhihuishu.com" in (p.get("url") or "")]
    say(OK if pages else FAIL, "%d page tab(s), %d on zhihuishu.com" % (len(pages), len(zs)))
    mine = [p for p in pages if any(m in (p.get("url") or "") for m in drive.MINE)]
    if len(mine) > 6:
        say(WARN, "%d of this skill's tabs are still open; run drive.reap() or close them"
                   " - past ~40 the browser starts 500ing new handshakes" % len(mine))
    if not zs:
        say(WARN, "no zhihuishu tab open; open the course URL and log in by hand:")
        say("", "  " + config.STUDY_URL)
        return pages
    ws = cdp.connect(zs[0]["webSocketDebuggerUrl"])
    try:
        href = cdp.evaljs(ws, "location.href", timeout=15) or ""
        title = cdp.evaljs(ws, "document.title", timeout=15) or ""
    finally:
        ws.close()
    say(OK, "current zhihuishu tab: %s" % str(href)[:90])
    if "login" in str(href).lower() or "登录" in str(title):
        say(FAIL, "this tab is a login page - log in by hand (yidun slider needs a human)")
    elif "passport" in str(href):
        say(FAIL, "this tab is the passport/login host - complete login first")
    else:
        say(OK, "logged-in tab looks usable")
    return pages


SELECTOR_JS = r"""
JSON.stringify((function(){
  var q=function(s){return document.querySelectorAll(s).length;};
  return {
    cards: q('.item-content[knowledgeid]'),
    rings: q('.el-progress'),
    improve: q('.simplified-mastery__action'),
    url: location.href, title: document.title,
    hasRingValue: q('.el-progress[aria-valuenow]')
  };
})())
"""


def check_study_page():
    """Open the course page and confirm the selectors this skill reads exist."""
    try:
        drive.close_targets("knowledgeStudy")
        ws, _t = drive.new_tab(config.STUDY_URL, wait=10)
    except Exception as e:
        say(FAIL, "cannot open the study page: %s" % str(e)[:140])
        return
    try:
        info = {}
        for _ in range(8):
            raw = cdp.evaljs(ws, SELECTOR_JS, timeout=20)
            try:
                info = json.loads(raw) if isinstance(raw, str) else {}
            except ValueError:
                info = {}
            if info.get("cards"):
                break
            config.sleep(2.0)
    finally:
        drive.close_targets("knowledgeStudy")
    if not info.get("cards"):
        say(FAIL, "the study page rendered no card (expected .item-content[knowledgeid])")
        say("", "  check ZHS_COURSE=%s ZHS_CLASS=%s and that this account owns the course"
            % (config.COURSE, config.CLASS))
        return
    say(OK, "study page: %d cards, %d progress rings (%d with aria-valuenow)"
        % (info["cards"], info["rings"], info.get("hasRingValue", 0)))
    if not info.get("hasRingValue"):
        say(WARN, "no card exposes aria-valuenow; live.py would record every point as '?'")
    if info["cards"] - info.get("hasRingValue", 0) > 0:
        say(WARN, "%d card(s) have no ring - those are 免考/无练习卷 points, expected to stay unfilled"
            % (info["cards"] - info.get("hasRingValue", 0)))


def check_bank():
    b = bank.load(config.BANK)
    if not b:
        say(WARN, "bank is empty (%s); the first rounds will guess %s and learn from harvest"
            % (config.BANK, config.GUESS))
        return
    bad = [k for k, v in b.items() if not bank.letters_of(v)]
    say(OK if not bad else WARN, "bank: %d entries%s" % (
        len(b), (", %d without usable letters" % len(bad)) if bad else ""))
    if bad:
        for k in bad[:3]:
            say("", "  - %s" % k[:70])


def check_writable():
    probe = config.path(".write_probe")
    try:
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        say(OK, "data dir writable: %s" % config.DATA)
    except OSError as e:
        say(FAIL, "cannot write to %s (%s)" % (config.DATA, e))


def main():
    print("course=%s class=%s port=%d target=%g maxr=%d probe=%d"
          % (config.COURSE, config.CLASS, config.PORT, config.TARGET, config.MAXR, config.PROBE))
    print("study=%s" % config.STUDY_URL)
    check_writable()
    check_bank()
    if check_port() is None:
        return 1
    pages = check_tabs()
    if pages is None:
        pages = []
    if _state["failed"]:
        # No point hammering the site when we already know the run cannot work.
        print("\nVERDICT not_ready")
        return 1
    check_study_page()
    print("\nVERDICT " + ("not_ready" if _state["failed"] else
                          ("ready_with_warnings" if _state["warned"] else "ready")))
    return 1 if _state["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
