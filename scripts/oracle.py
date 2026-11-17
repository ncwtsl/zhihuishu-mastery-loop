"""Oracle arithmetic: turn "已答对 N/M" into an answer, without a browser.

The result page reports `已答对/总题数`. That count is a real oracle: swap the
letter for one question, resubmit, and a question whose count goes UP was wrong
before. Everything that decides *which* question to vary and *which* letter to
keep is pure arithmetic and lives here, so it can be tested offline.

Reference for why this matters: a paper scoring 5/6 with `guessed=[]` means the
bank's stored answer is wrong for one of those six questions. Without this
module the old loop just re-submitted the same wrong answer until it ran out of
rounds (observed: 76.0 repeated eight times on 爱因斯坦光子假设).
"""
import itertools

LETTERS = "ABCDEF"

# Question types as the paper names them.
JUDGE = ("判断题", "是非题")
MULTI = ("多选题", "不定项选择题")


def is_judge(type_name):
    return any(k in (type_name or "") for k in JUDGE)


def is_multi(type_name):
    return any(k in (type_name or "") for k in MULTI)


def candidates(type_name, nopts=4):
    """Letter strings worth trying for one question.

    判断题 is A/B (`对`/`错` map to the first two options). Multi-select gets
    every non-empty subset - but only when the option count is small enough to
    stay inside a round budget: 4 options is 15 papers, 5 options is 31, and at
    ~40 s a paper that is over half an hour for one question.

    A 判断题 is capped at two candidates even when the caller passes the default
    `nopts=4`: 82% of a real physics bank is 判断题, and probing C and D on a
    two-option question costs two papers per question that can never pay off.
    """
    n = max(2, min(int(nopts or 4), len(LETTERS)))
    if is_judge(type_name):
        n = 2
    letters = LETTERS[:n]
    if is_multi(type_name):
        if n > 4:
            return []
        out = []
        for r in range(1, n + 1):
            for combo in itertools.combinations(letters, r):
                out.append("".join(combo))
        return out
    return list(letters)


def wrong_alternatives(answer, type_name, nopts=4):
    """Letters that are certainly NOT the stored answer (single-answer types)."""
    ans = "".join(sorted(answer or ""))
    if not ans or is_multi(type_name):
        return []
    pool = candidates(type_name, nopts)
    return [c for c in pool if "".join(sorted(c)) != ans]


def plan_with(answers, override):
    """Copy of `answers` ({sort: letters}) with `override` ({sort: letters}) applied."""
    out = dict(answers or {})
    out.update({str(k): v for k, v in (override or {}).items()})
    return out


def pick_best(samples, baseline=None):
    """Choose the letter from [(letters, correct), ...].

    Rules, in order:
      - a candidate must STRICTLY beat the baseline count to be considered a fix
        (a tie means "still wrong", not "already right");
      - ties between candidates are reported, not silently resolved, because a
        tie means the oracle could not see the difference (e.g. the count was
        capped by another broken question).
    Returns (letters, correct, ambiguous_letters).
    """
    best_c = -1
    best = []
    for letters, c in samples:
        if c is None:
            continue
        if c > best_c:
            best_c, best = c, [letters]
        elif c == best_c:
            best.append(letters)
    if baseline is not None and best_c <= baseline:
        return None, best_c, best
    if not best:
        return None, best_c, []
    return best[0], best_c, (best if len(best) > 1 else [])


def verdict(correct, total, expected=None):
    """Classify one submission. Keeps callers from inventing their own rules.

    - `perfect`  : every question right -> this paper is done
    - `shy`      : at least one right, and short of perfect. If no question was
                   guessed, the bank holds a wrong letter and needs an audit.
    - `collapse` : zero right, or mastery fell off a cliff -> the answering
                   mechanics were skipped (answers were never committed).
    """
    if correct is None or not total:
        return "unknown"
    if correct >= total:
        return "perfect"
    if expected is not None and correct > expected:
        return "improved"
    if correct == 0:
        return "collapse"
    return "shy"


def mismatches(plan, harvested):
    """Questions the submitted answer got wrong, attributed by paper position.

    `plan` is {sort: letters} as submitted; `harvested` is {sort: letters} from
    the attempt's own 参考答案 page. Any sort where the two disagree was answered
    wrong - no guessing about which one, because the preview page lists the
    answers in paper order and `harvest.py` keeps that order.

    Sorts missing from either side are skipped: an absent harvest means the
    preview page failed, not that the answer was right.
    """
    out = []
    for s, want in (harvested or {}).items():
        s = str(s)
        if s not in (plan or {}):
            continue
        got = "".join(sorted(str((plan or {})[s] or "")))
        want = "".join(sorted(str(want or "")))
        if not want:
            continue
        if got != want:
            out.append({"sort": s, "got": got, "want": want})
    return sorted(out, key=lambda d: int(d["sort"]) if d["sort"].isdigit() else 0)


def budget_ok(rounds_used, rounds_cap, cost_per_round=None, seconds_cap=None):
    """Can we afford ANOTHER round?

    Two independent ceilings: the round cap, and - when a per-round cost is known
    - the wall clock. The wall-clock test asks whether the *next* round fits,
    because a budget that only checks what is already spent always approves one
    more round and overshoots by exactly one paper.
    """
    if rounds_used >= rounds_cap:
        return False
    if cost_per_round and seconds_cap:
        return (rounds_used + 1) * cost_per_round <= seconds_cap
    return True
