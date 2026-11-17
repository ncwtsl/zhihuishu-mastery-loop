# Zhihuishu mastery loop — hard-won gotchas

Every item here was found by watching a run produce plausible-looking but wrong numbers.
Read this before editing the scripts.

## Answering mechanics

**Answers commit only when you leave a question via 下一题 (`.pre-next .next-topic`).**
Jumping between questions with the answer-card tree (`.content-reviewS .custom-tree-answer-normal`,
what `goTo` does) silently discards the pending selection. Verified: after `goTo(1)` + `pick('A')`
the sheet still reports `answerState=1`; clicking `next-topic` immediately flips it to `2`. A run
that visits every question via the card and picks options ends with `proExamss` at 16.7% or 50%.
→ Always answer front-to-back with `swipeAll`.

**Clicking an already-selected option toggles it OFF.** The options are not idempotent. A second
pass over the same question wipes the answer. → `pick()` reads `.checkIcon.checkedIcon` (single
choice / true-false) or `input[type=checkbox].checked` (multiple choice) and only clicks what is
missing.

**Multiple choice needs individual clicks, verified one at a time.** Clicking three labels in one
batch registers only one. `pick()` clicks each missing letter, sleeps, and re-reads `selection()`.

**`v.jumpToQuestion(n)` does not work.** It is an obfuscated async method taking an object, and it
leaves `currentQues.sort` unchanged. Nothing in this skill calls it.

**`readOne()` can return the previous question's stem.** After a jump, `reviewTopicData` lags
`currentQues`. Compare `reviewTopicData.questionId` against `currentQues.questionId` and treat a
mismatch as `__LAG__`; `goTo()` must require both `currentQues.sort == n` and a synced payload.

**`answerState` staying at 1 is not fatal** on true/false papers — such a paper still submits and
scores 94. Do not burn retries waiting for it to become 2.

## Mastery scoring

- All-correct round scores **94–96** the first time; a further all-correct round reaches **100**.
- A round with one wrong answer drops mastery by ~18 points (94 → 76).
- Therefore the loop must never answer from partial knowledge on a question it has not harvested —
  guessing all-`A` and learning from the result is safer than a confident wrong answer.
- Reading mastery off the answering page is a **trap**: `.answer-pro .pro` shows answering
  progress (`83.3`), not mastery. Mastery must come from the `/point/` result page.

## Data plumbing

- `drive.submit()` returning `None` means the page never navigated to `/point/`. Return early;
  never fall back to scraping the current page.
- Every submission leaves a `/point/` tab open. Without `close_targets("/point/")` they pile up
  (43 tabs observed) and CDP starts returning 500s.
- `baseInfor` is not always rendered when a quiz page first loads → `KeyError: 'qc'`. Poll for it
  (`get_base`, 8×1.5 s) and treat repeated failure as `BASE_EMPTY`, retrying the whole open.
- Bank keys are the normalised question text. **`html.unescape()` before stripping whitespace**,
  or `E1&gt;E2` and `E1>E2` become two keys for one question and the lookup misses forever.
- Options can go past `D` (`E` appears on image-heavy papers). Harvest `A`–`E`, not `A`–`D`.
- The preview page needs the `examPaperId`/`examTestId` of the attempt you just submitted. Reusing
  a previous attempt's ids yields a blank page with zero `.exam-item` blocks.
- `ops_write_file` may be denied (`PUBLICATION_DENIED`) in this workspace; a bash heredoc works.

## Browser / session

- Edge silently ignores `--remote-debugging-port` when `--user-data-dir` is the real default
  profile (Chromium 136+). An NTFS junction to that profile satisfies the check and keeps cookies.
- zhihuishu session cookies are session-scoped; app-bound v20 encryption means Cookies and Login
  Data cannot be decrypted offline (`InvalidTag()`). Do not plan around it.
- The Yidun slider cannot be passed with synthesized events — both
  `Input.dispatchMouseEvent` and `Input.dispatchTouchEvent` drags fail even with the correct gap
  offset. Only the user can log in.
- Chinese IME turns `javascript:` in the address bar into a search for `javascript：`. Do not use
  javascript: URL injection.
- `cdp.page_ws()` returns `(ws_url, target)`; call `WS(url)` first or you get
  `AttributeError: 'str' object has no attribute 'call'`.
- On Windows, `tasklist //FI ...` breaks under MSYS path mangling, and `cmd //c start` does not
  launch Edge; use `nohup ... &`.

## Points that cannot be driven

A card showing **免考 / 去练习** has no practice paper. Its button opens
`masteryHistory/<course>/<class>/<kid>`, which contains no `.improve-btn`. `aria-valuenow` is
absent, so the DOM scan records `?`. Report these to the user; do not retry them.
