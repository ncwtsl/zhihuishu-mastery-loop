"""Offline self-test: prove the load-bearing logic without Edge, CDP or a login.

Run this after any edit to bank.py / oracle.py / harvest.py / verify.py. Every
case here is a bug that actually shipped once, so a regression fails loudly
instead of quietly costing a 40-minute run.

    python selftest.py          # all cases
    python selftest.py -v       # show each case name
"""
import html
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import bank  # noqa: E402
import config  # noqa: E402
import harvest  # noqa: E402
import live  # noqa: E402
import oracle  # noqa: E402
import probe  # noqa: E402
import verify  # noqa: E402

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


# --------------------------------------------------------------------- bank
@case
def norm_unescape_order():
    """`E1&gt;E2` and `E1>E2` must be the same key, and tags must not be eaten
    after unescaping (unescape-then-strip would delete a literal `<b>`)."""
    a = bank.norm("光电效应中 <b>E1&gt;E2</b> 吗？")
    b = bank.norm("光电效应中 E1>E2 吗？")
    assert a == b, (a, b)
    lit = bank.norm("比较 &lt;b&gt; 与 <b>x</b>")
    assert "<b>" in lit, lit
    assert "x" in lit


@case
def norm_whitespace_and_nbsp():
    a = bank.norm("总题数\u00a06\n 已答对 6")
    assert a == bank.norm("总题数 6 已答对 6"), a


@case
def norm_non_string():
    assert bank.norm(None) == ""
    assert bank.norm(123) == ""


@case
def letters_of_shapes():
    assert bank.letters_of({"letters": ["C", "a"]}) == "AC"
    assert bank.letters_of(["B"]) == "B"
    assert bank.letters_of("BA") == "AB"
    assert bank.letters_of(None) == ""
    assert bank.letters_of({"letters": []}) == ""


@case
def lookup_is_exact_never_fuzzy():
    """A prefix match once paired two different questions and drove mastery to
    20%. `lookup` must return None, while `near` may still report the neighbour."""
    b = {}
    bank.put(b, "关于爱因斯坦光子假设，下列说法正确的是", "A")
    assert bank.lookup(b, "关于爱因斯坦光子假设，下列说法正确的是") == "A"
    assert bank.lookup(b, "关于爱因斯坦光子假设，下列说法") is None
    near = bank.near(b, "关于爱因斯坦光子假设，下列说法")
    assert near and near[0][1] == "A", near


@case
def put_reports_newness_and_keeps_shape():
    b = {}
    assert bank.put(b, "Q1", "b", "单选题", ["x", "y"]) is True
    assert bank.put(b, "Q1", "B", "单选题") is False
    entry = b[bank.norm("Q1")]
    assert entry["letters"] == ["B"] and entry["type"] == "单选题"
    assert bank.put(b, "", "A") is False
    assert bank.put(b, "Q2", "") is False


# ------------------------------------------------------------- parse_point
POINT_TEXT = """100%
掌握度
最好成绩 100%
总题数 6
已答对 6
继续提升
"""


@case
def parse_point_reads_mastery_not_progress():
    got = bank.parse_point(POINT_TEXT)
    assert got["mastery"] == 100.0, got
    assert got["correct"] == 6 and got["total"] == 6, got
    assert got["best"] == 100.0, got


@case
def parse_point_single_line_dom_dump():
    got = bank.parse_point("76% 掌握度 总题数 6 已答对 5")
    assert got["mastery"] == 76.0 and got["correct"] == 5 and got["total"] == 6, got


@case
def parse_point_ignores_answering_progress():
    """The quiz page prints 答题进度 83.3%. Reading that as mastery is what made
    a perfect run look like a failure; without the 掌握度 label there is no
    mastery on the page at all."""
    page = "答题进度\n83.3%\n1/6\n已答对 5"
    got = bank.parse_point(page)
    assert got["mastery"] is None, got
    assert got["correct"] == 5


@case
def parse_point_empty():
    assert bank.parse_point("")["mastery"] is None
    assert bank.parse_point(None)["mastery"] is None


@case
def parse_point_garbage_does_not_raise():
    got = bank.parse_point("掌握度")
    assert got["mastery"] is None


# ---------------------------------------------------------------- stalled
@case
def stalled_detects_repeat():
    assert bank.stalled([76.0, 76.0, 76.0], 3) is True
    assert bank.stalled([76.0, 78.0, 76.0], 3) is False
    assert bank.stalled([76.0, 76.0], 3) is False
    assert bank.stalled([None, None, None], 3) is False
    assert bank.stalled([], 3) is False


# ------------------------------------------------------------------ oracle
@case
def oracle_type_detection():
    assert oracle.is_judge("判断题") and oracle.is_judge("是非题")
    assert not oracle.is_judge("单选题")
    assert oracle.is_multi("多选题") and oracle.is_multi("不定项选择题")


@case
def oracle_candidates():
    assert oracle.candidates("单选题", 4) == ["A", "B", "C", "D"]
    assert oracle.candidates("判断题", 2) == ["A", "B"]
    combos = oracle.candidates("多选题", 3)
    assert "AB" in combos and "ABC" in combos and len(combos) == 7, combos
    assert oracle.candidates("多选题", 5) == [], "budget guard for wide multi-select"


@case
def oracle_judge_never_gets_more_than_two_candidates():
    """A 判断题 must stay at two candidates even when the caller passes 4.

    `_nopts()` in probe.py falls back to 4 when the parsed question carries no
    option list, which is the common shape on a real paper. Without this cap a
    probe would spend a paper each on C and D for a two-option question - and
    168 of the 205 answers in the real physics bank are 判断题, so that cost lands
    on almost every point that ever stalls.
    """
    assert oracle.candidates("判断题", 4) == ["A", "B"], oracle.candidates("判断题", 4)
    assert oracle.candidates("判断题", None) == ["A", "B"]
    assert oracle.candidates("是非题", 6) == ["A", "B"]
    assert oracle.candidates("单选题", 4) == ["A", "B", "C", "D"], "cap must not leak to single choice"


@case
def oracle_wrong_alternatives_excludes_answer():
    alts = oracle.wrong_alternatives("B", "单选题", 4)
    assert "B" not in alts and set(alts) == {"A", "C", "D"}, alts
    assert oracle.wrong_alternatives("AB", "多选题", 4) == []
    assert oracle.wrong_alternatives("", "单选题", 4) == []


@case
def oracle_pick_best_requires_strict_improvement():
    """A tie is not a fix: the count would be the same with the old answer."""
    best, c, amb = oracle.pick_best([("A", 4), ("B", 4)], baseline=4)
    assert best is None and c == 4, (best, c)
    best, c, amb = oracle.pick_best([("A", 4), ("B", 6)], baseline=4)
    assert best == "B" and c == 6 and amb == [], (best, c, amb)
    best, c, amb = oracle.pick_best([("A", None), ("B", 6)], baseline=4)
    assert best == "B"


@case
def oracle_pick_best_reports_ambiguity():
    best, c, amb = oracle.pick_best([("A", 6), ("B", 6)], baseline=4)
    assert best in ("A", "B") and sorted(amb) == ["A", "B"], (best, amb)


@case
def oracle_verdict():
    assert oracle.verdict(6, 6) == "perfect"
    assert oracle.verdict(5, 6) == "shy"
    assert oracle.verdict(0, 6) == "collapse"
    assert oracle.verdict(5, 6, expected=4) == "improved"
    assert oracle.verdict(None, 6) == "unknown"
    assert oracle.verdict(5, 0) == "unknown"


@case
def oracle_mismatches_attributes_by_sort():
    """The whole self-audit depends on this: wrong answer -> the exact question."""
    plan = {"1": "A", "2": "B", "3": "C"}
    harv = {"1": "A", "2": "D", "3": "C", "4": "A"}
    got = oracle.mismatches(plan, harv)
    assert [m["sort"] for m in got] == ["2"], got
    assert got[0]["got"] == "B" and got[0]["want"] == "D", got


@case
def oracle_mismatches_ignores_order_and_empty():
    plan = {"1": "AC", "2": "B"}
    harv = {"1": "CA"}
    assert oracle.mismatches(plan, harv) == []
    assert oracle.mismatches({}, {"1": "A"}) == []
    assert oracle.mismatches({"1": "A"}, {}) == []


@case
def oracle_budget():
    assert oracle.budget_ok(0, 3) is True
    assert oracle.budget_ok(3, 3) is False
    assert oracle.budget_ok(2, 9, cost_per_round=40, seconds_cap=100) is False
    assert oracle.budget_ok(1, 9, cost_per_round=40, seconds_cap=100) is True


# ----------------------------------------------------------------- harvest
JUDGE_BLOCK = """5、摩擦力总是阻碍物体运动。
判断题
A. 对
B. 错
参考答案：错"""

CHOICE_BLOCK = """2、一质点做匀速圆周运动，下列说法正确的是（ ）
单选题
A. 速度不变
B. 速率不变
C. 加速度为零
D. 合力为零
参考答案：B"""

MULTI_BLOCK = """6、下列属于矢量的是（ ）
多选题
A. 位移
B. 路程
C. 速度
D. 质量
参考答案：A、C"""


@case
def harvest_judge_maps_to_real_letters():
    """Storing the literal 对/错 made every 判断题 miss forever."""
    it = harvest.parse_block(5, JUDGE_BLOCK)
    assert it["typeName"] == "判断题", it
    assert it["letters"] == ["B"], it
    assert it["opts"][0].startswith("对"), it["opts"]


@case
def harvest_judge_letters_follow_the_page_not_convention():
    """The labels are read from the page: if the paper prints A. 错 B. 对 then an
    answer of 错 is letter A, not the conventional B."""
    swapped = JUDGE_BLOCK.replace("A. 对\nB. 错", "A. 错\nB. 对")
    it = harvest.parse_block(5, swapped)
    assert it["letters"] == ["A"], it["letters"]
    it2 = harvest.parse_block(5, swapped.replace("参考答案：错", "参考答案：对"))
    assert it2["letters"] == ["B"], it2["letters"]
    # Original order, answer 对 -> A.
    it3 = harvest.parse_block(5, JUDGE_BLOCK.replace("参考答案：错", "参考答案：对"))
    assert it3["letters"] == ["A"], it3["letters"]


@case
def harvest_single_choice():
    it = harvest.parse_block(2, CHOICE_BLOCK)
    assert it["letters"] == ["B"] and it["typeName"] == "单选题", it
    assert it["stem"].startswith("一质点做匀速圆周运动"), it["stem"]
    assert len(it["opts"]) == 4, it["opts"]


@case
def harvest_multi_select():
    it = harvest.parse_block(6, MULTI_BLOCK)
    assert it["letters"] == ["A", "C"], it
    assert it["typeName"] == "多选题"


@case
def harvest_keeps_sort():
    it = harvest.parse_block(11, CHOICE_BLOCK)
    assert it["sort"] == "11", it


@case
def harvest_rejects_block_without_answer():
    assert harvest.parse_block(1, "1、题干\nA. x\nB. y") is None


@case
def harvest_handles_e_option():
    """The old regex only knew A-D and silently dropped E answers."""
    blk = CHOICE_BLOCK.replace("参考答案：B", "参考答案：E").replace(
        "D. 合力为零", "D. 合力为零\nE. 向心加速度指向圆心")
    it = harvest.parse_block(2, blk)
    assert it["letters"] == ["E"], it


# ------------------------------------------------------------------- probe
def _qs():
    return [
        {"sort": 1, "typeName": "单选题", "stem": "q1", "opts": []},
        {"sort": 2, "typeName": "判断题", "stem": "q2", "opts": []},
        {"sort": 3, "typeName": "单选题", "stem": "q3", "opts": []},
        {"sort": 4, "typeName": "多选题", "stem": "q4",
         "opts": [{"sort": "A"}, {"sort": "B"}, {"sort": "C"}, {"sort": "D"}]},
    ]


@case
def probe_evidence_splits_by_what_the_preview_proved():
    """The whole point of the attribution: a question harvest agrees with is
    PROVED right and must never cost another paper. The old code started at
    question 1 and burned twelve papers learning that."""
    qs = _qs()
    plan = {"1": "B", "2": "A", "3": "A", "4": "AB"}
    harvested = {"1": "B", "2": "A", "3": "C"}          # q4 missing from harvest
    wrong, right, unreported = probe.evidence(qs, plan, harvested, {})
    assert wrong == ["3"], wrong
    assert sorted(right) == ["1", "2"], right
    assert unreported == ["4"], unreported


@case
def probe_evidence_treats_a_learned_answer_as_proved():
    qs = _qs()
    plan = {"1": "B", "3": "C"}
    wrong, right, unreported = probe.evidence(qs, plan, {"3": "C"}, {"3": "C"})
    assert "3" in right and "3" not in wrong, (wrong, right)


@case
def probe_evidence_sorts_multiset_letters():
    """AB and BA are the same answer; a different ORDER must not read as wrong."""
    qs = [{"sort": 1, "typeName": "多选题", "stem": "q", "opts": []}]
    wrong, right, _u = probe.evidence(qs, {"1": "AB"}, {"1": "BA"}, {})
    assert not wrong and right == ["1"], (wrong, right)


@case
def probe_ranks_judge_before_single_before_multi():
    """A 判断题 costs 2 papers, a single choice 4, a multi-select up to 15."""
    qs = _qs()
    order, by_sort = probe.rank_unknown(qs, ["4", "1", "2"], {})
    assert order == ["2", "1", "4"], order
    # by_sort is the whole paper, not just the suspects.
    assert set(by_sort) == {"1", "2", "3", "4"}, by_sort


# ----------------------------------------------------------------- fastpy
@case
def committed_reads_answer_state_not_the_old_suffix():
    """`not endswith('->2')` was dead: fast.js never emitted `->2`, so every
    fully-answered paper was reported as uncommitted."""
    import fastpy
    rep = {"1": "OK_AC/want=AC/state2", "2": "OK_B/want=B/state1", "3": "BAD_/want=/state1"}
    ok, bad = fastpy.committed(rep)
    assert ok == ["1"], ok
    assert sorted(bad) == ["2", "3"], bad


@case
def no_paper_is_its_own_class():
    """A 免考 card must not look like a timeout: the run reports it and stops."""
    import drive
    assert issubclass(drive.NoPaper, RuntimeError)
    assert isinstance(drive.NoPaper("k1"), RuntimeError)


# ------------------------------------------------------------------ verify
@case
def verify_flags_short_point():
    rows = [["k1", "点一", "100"], ["k2", "点二", "76"], ["k3", "免考", "?"]]
    summary = {"points": [{"name": "点一", "stage": "done", "final": 100.0, "hist": [94.0, 100.0]}],
               "no_paper": [{"name": "免考"}]}
    res = verify.check(summary=summary, rows=rows)
    assert res["stats"]["short"] == 1 and res["stats"]["no_paper"] == 1, res["stats"]
    assert not res["ok"]
    assert any(p["kind"] == "short" and p["name"] == "点二" for p in res["problems"]), res["problems"]


@case
def verify_rejects_false_done_and_progress_bar():
    rows = [["k1", "点一", "100"]]
    summary = {"points": [{"name": "点一", "stage": "done", "final": 83.3,
                           "hist": [94.0, 83.3]}]}
    res = verify.check(summary=summary, rows=rows)
    kinds = {p["kind"] for p in res["problems"]}
    assert "false_done" in kinds, kinds
    assert "progress_bar_read_as_mastery" in kinds, kinds


@case
def verify_accepts_a_real_finish():
    rows = [["k1", "点一", "100"], ["k2", "免考", "?"]]
    summary = {"points": [{"name": "点一", "stage": "done", "final": 100.0, "hist": [96.0, 100.0]}],
               "no_paper": [{"name": "免考"}]}
    res = verify.check(summary=summary, rows=rows)
    assert res["ok"], res["problems"]


@case
def verify_treats_no_paper_as_reported_not_failed():
    """A 免考 point can never reach 100. Counting it as `unfinished` turns a
    finished run into a red verdict - exactly what the field run hit with its
    three no-paper points."""
    rows = [["k1", "点一", "100"], ["k2", "无卷", "?"]]
    summary = {"points": [{"name": "点一", "stage": "done", "final": 100.0, "hist": [100.0]},
                          {"name": "无卷", "stage": "no_paper", "final": None, "hist": []}],
               "no_paper": [{"name": "无卷"}]}
    res = verify.check(summary=summary, rows=rows)
    assert res["ok"], res["problems"]
    assert not any(p["kind"] == "unfinished" for p in res["problems"]), res["problems"]


@case
def verify_unfinished_point_carries_a_reason():
    """`unfinished` alone makes the reader open the log. The problem entry must
    carry the probe stage translated into Chinese."""
    rows = [["k1", "点一", "76"]]
    summary = {"points": [{"name": "点一", "stage": "probe_budget", "final": 76.0,
                           "hist": [76.0, 76.0, 76.0]}]}
    res = verify.check(summary=summary, rows=rows)
    prob = [p for p in res["problems"] if p["kind"] == "unfinished"]
    assert prob and "预算" in prob[0]["why"], prob


@case
def summary_does_not_list_no_paper_as_a_problem():
    """write_summary's `problems` list feeds the audit headline; no-paper points
    belong in their own section, not in the "still broken" bucket."""
    import batchall
    results = [{"kid": "k1", "name": "点一", "stage": "done", "hist": [100.0]},
               {"kid": "k2", "name": "无卷", "stage": "no_paper", "hist": [],
                "mastery": None}]
    saved = config.SUMMARY
    config.SUMMARY = config.path("_selftest_summary.json")
    try:
        s = batchall.write_summary(results, [{"kid": "k2", "name": "无卷"}], 0.0)
    finally:
        try:
            os.remove(config.SUMMARY)
        except OSError:
            pass
        config.SUMMARY = saved
    assert s["problems"] == [], s["problems"]
    assert [p["stage"] for p in s["points"]] == ["done", "no_paper"], s["points"]


@case
def verify_calls_out_a_stalled_history():
    """Three identical rounds mean the plan is not changing, so no future round
    can either. The report must say so rather than showing a bare 76%."""
    rows = [["k1", "点一", "76"]]
    summary = {"points": [{"name": "点一", "stage": "short", "final": 76.0,
                           "hist": [76.0, 76.0, 76.0]}]}
    res = verify.check(summary=summary, rows=rows)
    assert any(p["kind"] == "not_converging" for p in res["problems"]), res["problems"]


@case
def verify_does_not_call_a_no_paper_history_stalled():
    rows = [["k1", "无卷", "?"]]
    summary = {"points": [{"name": "无卷", "stage": "no_paper", "final": None, "hist": []}],
               "no_paper": [{"name": "无卷"}]}
    res = verify.check(summary=summary, rows=rows)
    assert res["ok"], res["problems"]


@case
def verify_refuses_to_pass_without_a_scan():
    """`points=0 short=0` used to print `VERDICT ok`. No scan is not a pass."""
    res = verify.check(summary={"points": []}, rows=[])
    assert not res["ok"], res
    assert any(p["kind"] == "no_scan" for p in res["problems"]), res["problems"]


@case
def todo_list_reports_a_blank_scan_instead_of_all_done():
    """An empty course-page scan must not read as `NOTHING_TO_DO`.

    The scan is stubbed to return nothing, which is what a logged-out session or
    a still-painting grid produces - `main` then has to say NO_SCAN, not "every
    point is already at 100"."""
    import batchall
    saved_path = config.DOM_MASTERY
    saved_scan = batchall.live.scan
    config.DOM_MASTERY = config.path("_selftest_absent.json")
    batchall.live.scan = lambda *a, **k: []
    try:
        todo, free, done = batchall.todo_list(refresh=False)
    finally:
        batchall.live.scan = saved_scan
        config.DOM_MASTERY = saved_path
    assert (todo, free, done) == ([], [], []), (todo, free, done)


@case
def todo_list_sorts_the_cheapest_point_first():
    import batchall
    saved = config.DOM_MASTERY
    config.DOM_MASTERY = config.path("_selftest_dom.json")
    try:
        config.dump([["k1", "高", "94"], ["k2", "低", "45"], ["k3", "免考", "?"],
                     ["k4", "满", "100"]], config.DOM_MASTERY)
        todo, free, done = batchall.todo_list(refresh=False)
    finally:
        try:
            os.remove(config.DOM_MASTERY)
        except OSError:
            pass
        config.DOM_MASTERY = saved
    assert [r["kid"] for r in todo] == ["k2", "k1"], todo
    assert [r["kid"] for r in free] == ["k3"], free
    assert [r["kid"] for r in done] == ["k4"], done


@case
def post_run_grid_keeps_a_failed_point_visible():
    """A point that errored has no mastery of its own; it must stay in the grid as short.

    `live.classify` treats an unparseable ring as 免考. If the post-run grid passed
    `None` through, an `open_err` point would be filed as no-paper and the
    acceptance check would quietly excuse the one point that needs attention.
    The pre-run mastery is the honest value when we have it (nothing was answered),
    and a sentinel below target when we do not."""
    import batchall
    todo = [{"kid": "k1", "name": "打不开", "mastery": 76.0}]
    summary = {"points": [{"kid": "k1", "name": "打不开", "stage": "open_err", "final": None}]}
    grid = batchall.post_run_grid(todo, [], [], summary)
    assert grid == [["k1", "打不开", 76.0, "", ""]], grid
    _done, short, free = live.classify(grid)
    assert len(short) == 1 and not free, (short, free)

    # No pre-run value either: still short, never 免考.
    grid = batchall.post_run_grid([], [], [], summary)
    assert grid == [["k1", "打不开", -1.0, "", ""]], grid
    _done, short, free = live.classify(grid)
    assert len(short) == 1 and not free, (short, free)


@case
def post_run_grid_files_an_unopened_paper_as_free_not_short():
    import batchall
    summary = {"points": [{"kid": "k3", "name": "导体", "stage": "no_paper", "final": None}]}
    grid = batchall.post_run_grid([], [{"kid": "k3", "name": "导体"}], [], summary)
    assert grid == [["k3", "导体", "?", "", ""]], grid
    res = verify.check(summary=summary, rows=grid)
    assert res["ok"], res["problems"]


@case
def batchall_main_grades_itself_instead_of_printing_all_done():
    """Returning from the loop is not the same as finishing the course.

    Stub the browser for one point that stays at 76: `main` used to print
    ALL_DONE and return 0, so an unattended run that left a point short looked
    like success to whatever launched it."""
    import batchall
    saved = (config.SUMMARY, config.AUDIT, config.BANK)
    config.SUMMARY = config.path("_selftest_summary.json")
    config.AUDIT = config.path("_selftest_audit.md")
    saved_todo, saved_run = batchall.todo_list, batchall.run_point
    batchall.todo_list = lambda refresh=False: (
        [{"kid": "k1", "name": "卡住的点", "mastery": 76.0}], [], [])
    batchall.run_point = lambda kid, name, maxr=None, allow_probe=True: {
        "kid": kid, "name": name, "stage": "short", "mastery": 76.0, "hist": [76.0]}
    try:
        code = batchall.main([])
    finally:
        batchall.todo_list, batchall.run_point = saved_todo, saved_run
        for p in (config.SUMMARY, config.AUDIT, config.path("result_k1.json")):
            try:
                os.remove(p)
            except OSError:
                pass
        config.SUMMARY, config.AUDIT, config.BANK = saved
    assert code == 3, code


@case
def every_stage_the_loop_can_return_has_chinese_text():
    """A report that prints `unfinished: probe_budget` and nothing else is useless.

    The stage vocabulary is shared: `run_point` returns `probe_*`, `probe_point`
    returns bare names, and both end up in `verify`'s `why` field. Every one of
    them needs a sentence, and stripping the `probe_` prefix must NOT be needed -
    doing so silently downgraded `probe_stuck` to a vaguer explanation."""
    import batchall
    for stage in ["done", "short", "no_paper", "open_err", "run_err", "submit_failed",
                  "probe_perfect", "probe_stuck", "probe_exhausted", "probe_budget",
                  "probe_no_target", "probe_no_count", "probe_no_paper",
                  "probe_submit_failed",
                  "perfect", "stuck", "exhausted", "budget", "no_target", "no_count"]:
        text = probe.explain(stage)
        assert text != stage, "no sentence for stage %r" % stage
        assert any("\u4e00" <= ch <= "\u9fff" for ch in text), (stage, text)
    assert batchall.WHY is probe.STAGES, "the two copies drifted apart"
    assert probe.explain("probe_stuck") != probe.explain("stuck"), \
        "probe_stuck carries the multi-select hint; it must not collapse into `stuck`"


@case
def run_all_stops_before_driving_when_preflight_fails():
    """`run_all` must not start a 40-minute run on a channel doctor just failed."""
    import run_all
    saved = (run_all.doctor.main, run_all.live.scan)
    calls = {"scan": 0}

    def fake_scan(*a, **k):
        calls["scan"] += 1
        return [["k1", "点", "50"]]

    run_all.doctor.main = lambda *a, **k: 1
    run_all.live.scan = fake_scan
    try:
        code = run_all.main([])
    finally:
        run_all.doctor.main, run_all.live.scan = saved
    assert code == 1, code
    assert calls["scan"] == 0, "live.scan ran even though preflight failed"


@case
def run_all_reports_an_empty_grid_without_driving():
    import run_all
    saved = (run_all.doctor.main, run_all.live.scan, run_all.batchall.main)
    driven = {"n": 0}
    run_all.doctor.main = lambda *a, **k: 0
    run_all.live.scan = lambda *a, **k: []
    run_all.batchall.main = lambda argv=None: driven.__setitem__("n", driven["n"] + 1) or 0
    try:
        code = run_all.main([])
    finally:
        run_all.doctor.main, run_all.live.scan, run_all.batchall.main = saved
    assert code == 2, code
    assert driven["n"] == 0, "batchall ran on an empty scan"


@case
def scan_keeps_retrying_when_the_grid_shrinks():
    """A half-painted grid must not silently become the work list.

    `batchall` drives exactly the rows `live.scan()` returned, so a scan that
    comes back with 40 rows instead of 53 makes the other 13 points invisible
    while every downstream step still reports success. The previous scan is the
    floor: keep re-reading until the grid is at least that big.
    """
    import json as _json

    saved = (live.drive.require_browser, live.drive.close_targets,
             live.drive.new_tab, live.evaljs)
    saved_dom = config.DOM_MASTERY
    prev = [["k%d" % i, "点%d" % i, "100"] for i in range(30)]
    config.DOM_MASTERY = os.path.join(config.DATA, ".selftest_dom.json")
    config.dump(prev, config.DOM_MASTERY)

    # Two short reads (grid still painting) then the full 30-row grid.
    pages = [
        [["k%d" % i, "点%d" % i, "100"] for i in range(12)],
        [["k%d" % i, "点%d" % i, "100"] for i in range(20)],
        prev,
    ]
    seen = {"n": 0}

    def fake_evaljs(*a, **k):
        i = min(seen["n"], len(pages) - 1)
        seen["n"] += 1
        return _json.dumps(pages[i])

    live.drive.require_browser = lambda *a, **k: None
    live.drive.close_targets = lambda *a, **k: None
    live.drive.new_tab = lambda url, wait: ("ws", "t")
    live.evaljs = fake_evaljs
    try:
        rows = live.scan(tries=1)
    finally:
        (live.drive.require_browser, live.drive.close_targets,
         live.drive.new_tab, live.evaljs) = saved
        try:
            os.remove(config.DOM_MASTERY)
        except OSError:
            pass
        config.DOM_MASTERY = saved_dom
    assert len(rows) == 30, "scan stopped at %d rows and would have skipped 18 points" % len(rows)
    assert seen["n"] >= 3, "scan did not retry past the two short reads (%d)" % seen["n"]


# --------------------------------------------------------------------- CLI
@case
def cli_put_reports_new_then_updated_and_keeps_what_harvest_knew():
    """The manual path must be able to correct one letter without erasing context.

    Writing a bare {"letters": [...]} would drop the type and options harvest
    recorded, and then `stats` reports an entry with no type — after which nobody
    can tell a judge question from a single choice one when diagnosing.
    """
    path = os.path.join(config.DATA, ".selftest_cli.json")
    try:
        os.remove(path)
    except OSError:
        pass
    try:
        rc = bank._cli(["--bank", path, "put", "真空中 E1 &gt; E2", "C",
                        "--type", "单选题", "--opt", "E1&gt;E2"])
        assert rc == 0, "put returned %s" % rc
        d = bank.load(path)
        k = bank.norm("真空中 E1 > E2")
        assert list(d) == [k], "entity variants produced two keys: %s" % list(d)
        assert d[k]["type"] == "单选题" and d[k].get("opts")

        rc = bank._cli(["--bank", path, "put", "真空中 E1 > E2", "D"])
        assert rc == 0, "second put returned %s" % rc
        d = bank.load(path)
        assert bank.letters_of(d[k]) == "D", "letters not updated: %s" % d[k]
        assert d[k]["type"] == "单选题", "update erased the type: %s" % d[k]
        assert d[k].get("src") == "manual"
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


@case
def cli_get_tells_a_miss_apart_from_a_hit_by_exit_code():
    """A correction is only useful if `get` proves the key landed."""
    path = os.path.join(config.DATA, ".selftest_cli2.json")
    try:
        os.remove(path)
    except OSError:
        pass
    try:
        bank._cli(["--bank", path, "put", "某道题", "AC", "--type", "多选题"])
        assert bank._cli(["--bank", path, "get", "某道题"]) == 0
        assert bank._cli(["--bank", path, "get", "另一道题"]) == 1
        assert bank._cli(["--bank", path, "put", "", "C"]) == 2
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


@case
def cli_stdin_recovers_a_cp936_stem_instead_of_polluting_the_bank():
    """Stdin has to survive the console code page.

    Real failure seen while testing: a cp936 pipe decoded as UTF-8 with
    errors="replace" produced lone surrogates, `json.dump` raised
    UnicodeEncodeError, and the traceback looked like the write had failed on a
    perfectly ordinary question.
    """
    raw = "图片题 示意图 A".encode("gbk")
    import json as _json
    saved = sys.stdin
    try:
        sys.stdin = type("S", (), {"buffer": type("B", (), {"read": staticmethod(lambda: raw)})()})()
        got = bank._stdin_text()
    finally:
        sys.stdin = saved
    assert got == "图片题 示意图 A", "gbk stdin decoded as %r" % got
    assert not any("\ud800" <= c <= "\udfff" for c in got), "surrogate survived"
    # And whatever comes back must still be writable.
    _json.dumps({"k": got}, ensure_ascii=False)


# --------------------------------------------------------------------- run
def main(argv):
    verbose = "-v" in argv or "--verbose" in argv
    failed = 0
    for fn in CASES:
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print("FAIL %s\n     %s" % (fn.__name__, e))
        except Exception as e:  # noqa: BLE001 - a crash is a failure too
            failed += 1
            print("ERROR %s\n      %s: %s" % (fn.__name__, type(e).__name__, e))
        else:
            if verbose:
                print("ok   %s" % fn.__name__)
    print("%d/%d cases passed" % (len(CASES) - failed, len(CASES)))
    if failed:
        print("SELFTEST_FAILED")
        return 1
    print("SELFTEST_OK")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
