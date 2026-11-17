"""One command for the whole job: preflight -> baseline -> drive -> verdict.

The four steps were always run in this order, and every time one of them was
skipped the run wasted 40 minutes: driving without `doctor.py` means hammering a
logged-out browser, and driving without `live.py` means the grid the acceptance
check reads was never written.

This is a thin sequencer, not a fifth implementation. It calls the same `main`
functions a human would type, stops at the first step whose exit code says
"cannot continue", and passes through the switches that change the run.

    python run_all.py                  # the whole thing
    python run_all.py --resume         # skip points already at target
    python run_all.py --dry            # preflight + baseline only, no driving
    python run_all.py --fake           # offline rehearsal, no browser at all

Exit codes match the step that produced them:

    0  everything reached the target on its own
    1  preflight failed (`doctor.py`) - fix what it printed, then retry
    2  the course page produced no card at all (wrong id / logged out / painting)
    3  the run finished but some point is still short - see audit.md
"""
import argparse
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import batchall  # noqa: E402
import doctor  # noqa: E402
import live  # noqa: E402


def rule(title):
    print("\n" + "=" * 66)
    print(title)
    print("=" * 66, flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(description="doctor → live → batchall → 验收，一条命令跑完")
    ap.add_argument("--dry", action="store_true", help="只做预检与基线，不刷题")
    ap.add_argument("--fake", action="store_true", help="离线演练（不需要浏览器）")
    ap.add_argument("--refresh", action="store_true", help="重新扫描课程页")
    ap.add_argument("--resume", action="store_true", help="跳过已经达标的点")
    ap.add_argument("--no-probe", action="store_true", help="只直答不反解")
    ap.add_argument("--maxr", type=int, default=None, help="每个点最多几张卷")
    ap.add_argument("--probe", type=int, default=None, help="每个点反解预算")
    ap.add_argument("--limit", type=int, default=None, help="最多跑几个点")
    a = ap.parse_args(argv)

    if a.fake:
        rule("0/3 离线演练（--fake）")
        return batchall.main(["--fake"])

    rule("1/3 预检 doctor.py")
    code = doctor.main()
    if code != 0:
        # Every later step assumes a usable channel; carrying on would just
        # produce a log full of open_err and a summary that looks like a run.
        print("\n预检没过，后面的步骤没有意义。按上面 FAIL 后面的 fix 提示处理完再跑。")
        return 1

    rule("2/3 基线 live.py")
    rows = live.scan()
    live.report(rows)
    if not rows:
        print("\n课程页一张卡片都没解析到：检查 ZHS_COURSE / ZHS_CLASS，或确认页面已经登录。")
        return 2

    if a.dry:
        print("\n--dry 到此为止。要真跑就去掉 --dry。")
        return 0

    rule("3/3 刷题 batchall.py（每个点跑完即写 summary，可随时中断再 --resume）")
    args = []
    if a.refresh:
        args.append("--refresh")
    if a.resume:
        args.append("--resume")
    if a.no_probe:
        args.append("--no-probe")
    if a.maxr is not None:
        args += ["--maxr", str(a.maxr)]
    if a.probe is not None:
        args += ["--probe", str(a.probe)]
    if a.limit is not None:
        args += ["-", str(a.limit)]
    return batchall.main(args)


if __name__ == "__main__":
    sys.exit(main())
