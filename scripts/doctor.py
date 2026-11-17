"""Preflight: is the browser reachable, logged in, and on the course page?"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import config, cdp, drive

def main():
    print("course=%s class=%s port=%d" % (config.COURSE, config.CLASS, config.PORT))
    try:
        pages = drive.require_browser()
    except RuntimeError as e:
        print("FAIL", e)
        return 1
    print("OK   CDP reachable, %d page tab(s)" % len(pages))
    logged_in = [p for p in pages if "zhihuishu.com" in (p.get("url") or "")]
    if not logged_in:
        print("WARN no zhihuishu tab open; open the course URL and log in")
        return 2
    ws = cdp.WS(logged_in[0]["webSocketDebuggerUrl"])
    me = cdp.evaljs(ws, "location.href", timeout=15)
    print("OK   current tab:", (me or "")[:100])
    if "login" in (me or ""):
        print("FAIL this tab is a login page; log in by hand")
        return 3
    print("OK   looks usable")
    return 0

if __name__ == "__main__":
    sys.exit(main())
