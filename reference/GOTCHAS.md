# 知到掌握率刷题 —— 踩过的坑

这里每一条都是「跑出了看起来很正常的错误数字」之后才发现的。
改脚本前读一遍；改完跑 `python selftest.py`，那 56 个用例基本都是这些坑的尸体。

## 答题机制

**答案只在用「下一题」（`.pre-next .next-topic`）离开题目时提交。**
用答题卡树（`.content-reviewS .custom-tree-answer-normal`，也就是 `goTo` 干的事）跳题，
会把未提交的选择**静默丢弃**。实测：`goTo(1)` + `pick('A')` 之后答题卡里还是
`answerState=1`；紧接着点 `next-topic` 才翻成 `2`。走一遍答题卡点选项的跑法，
最后 `proExamss` 出来是 16.7% 或 50%。
→ 永远用 `swipeAll` 从头到尾顺序作答。

**点已选中的选项会把它取消。** 选项不是幂等的。第二遍过同一题会把答案清空。
→ `pick()` 先读 `.checkIcon.checkedIcon`（单选/判断）或 `input[type=checkbox].checked`（多选），只点缺的。

**多选题必须一个一个点。** 一次连点三个 label 只有一个生效。
→ `pickMulti` 逐字母点击 + 间隔 + 3 轮复查 `selection()`。

**`v.jumpToQuestion(n)` 不能用。** 它是个混淆过的异步方法、要传对象，而且不更新
`currentQues.sort`。本技能没有任何地方调它。

**`readOne()` 可能返回上一题的题干。** 跳题后 `reviewTopicData` 落后于 `currentQues`。
比对两者的 `questionId`，不一致就当 `__LAG__`；`goTo()` 必须同时满足 `currentQues.sort == n`
和载荷已同步。

**`answerState` 停在 1 有时不是故障**——判断题卷子照样能交、照样得 94。
别为了等它变 2 烧掉重试。

**`committed()` 的匹配必须用前缀。** `fast.js` 的 `swipeAll` 生成的是
`'OK_'|'BAD_' + got + '/want=' + want + '/state' + answerState`（`fast.js:238`），
`OK_` 是**前缀**。曾经写成 `"_OK_" in s`，永远匹配不上，于是「全都答好了」被判成
「一个都没提交」，白白重试。这是更早那个 `not s.endswith("->2")` 死判定的第二世——
同样的病，换了件衣服。`selftest.py::committed_reads_answer_state_not_the_old_suffix` 守着它。

## 掌握率怎么算

- 全对第一轮给 **94–96**，再一轮全对才 **100**。
- 错一题掉约 **18 分**（94 → 76）。
- 所以对没 harvest 到的题，**猜 `A` 再学**比「自信地答一个错」稳得多。
- **从答题页读掌握率是陷阱**：`.answer-pro .pro` 显示的是**答题进度**（`83.3`），
  不是掌握率。掌握率只能从 `/point/` 结果页读。`verify.py` 的
  `SUSPECT=(83.3, 66.7, 33.3, 16.7)` 就是在抓这个。
- **全对 ≠ 完成。** probe 找到答案后如果直接 return，点会永远停在 94——
  现场跑就正是这么报成的「done」。判定完成的是掌握率数字，不是「答案对了」。

## 数据管道

- `drive.submit()` 返回 `None` 表示页面没跳到 `/point/`。**立刻返回**，绝不要回头刮当前页。
- 每次提交都留一个 `/point/` 标签页。不调 `close_targets("/point/")` 就会堆积
  （见过 43 个），然后 CDP 开始 500。`drive.reap()` 是兜底。
- `baseInfor` 不一定在答题页首屏就绪 → `KeyError: 'qc'`。轮询（`get_base`，8×1.5s），
  反复失败抛 `BASE_EMPTY`，然后整轮重开。
- 题库 key 是规范化题干。**先去标签，再 `html.unescape()`，最后删空白**——
  顺序反了的话 `&lt;b&gt;` 会先变成真标签再被删掉。而且 `E1&gt;E2` 与 `E1>E2`
  会变成两个 key，那题永远查不到。
- **选项会超过 D**（图片多的卷子里出现 `E`）。`LETTERS = "ABCDEF"`，别只认 A–D。
- 解析页必须用**刚提交那次 attempt** 的 `examPaperId`/`examTestId`。
  拿上一次的 id 会得到一个零 `.exam-item` 的白页。
- **harvest 必须保留题号（`sort`）。** 没有题号，错答就无法归因，自查和 probe 都变成瞎猜。
  旧版 `harvest.py` 只返回题干列表，这是「库里错答案永远修不掉」的根因之一。
- **判断题的 `对/错` 要映射成该卷真实的选项字母**，而且要看选项**文案**而不是假设
  「A 就是对」。有的卷子选项顺序是反的。存字面量「对」→ 所有判断题 key 永久 miss。
- 结果页的 `已答对 N/M` 是**唯一可信的判分信号**。没有它，probe 无法判分
  （`probe_no_count`），只能退回题库直答。
- **「分数不满而 harvest 没报错」有三种成因，别混成一个。** 解析页一题都没抓到
  （`NO_HARVEST`）是解析器问题；只抓到一部分（`BLIND`，日志里列出没覆盖的题号）
  说明错的那题正好被藏起来——这是 probe 的活；全都抓到且全都匹配（`AUDIT_CLEAN`）
  说明题库是对的、答案没提交上去。旧日志把后两种都说成「解析页没问题」，于是
  该跑 probe 的时候去改解析器，该查 `pending` 的时候去改题库。
- 每轮日志末尾的 `verdict=` 不是装饰：`shy` / `collapse` / `perfect` 分别对应
  「题库还错」「答案没提交」「只差平台那条连续两轮规则」，一眼就能决定下一步。
- **判断题的候选永远只有两个，即使调用方传了 4。** `probe._nopts()` 在题目没带选项
  列表时回退到 4，而真实卷面上的判断题通常就不带选项——于是 probe 会为一道两选项的题
  多烧两张卷子去试 C 和 D。真实题库 205 条里 168 条是判断题，这个白烧落在几乎每一个
  会停滞的点上。`oracle.candidates()` 因此对 `JUDGE` 类型硬性封顶 2。
- **扫描行数是地板，不是 `>= 20` 就够。** 卡片网格懒渲染，只画出 40 行（应为 53）时，
  没被扫到的 13 个点整轮都不会被驱动，而 summary / audit / verify 全部照常报成功。
  `live.scan()` 现在以 `dom_mastery.json` 的上次行数为地板重读，仍缩水就打印
  `SCAN_SHORT previous=53 now=40` —— 看到它先查 `ZHS_COURSE` 与登录态。
- `ops_write_file` 在本工作区可能被拒（`PUBLICATION_DENIED`）；用 bash heredoc 或 `write` 工具。
- **题库有三处写入方，只有一处是人。** `harvest`（`src` 缺省）、`audit` 自查（`source="audit"`）、
  `probe` 反解（`source="probe"`）、手工（`source="manual"`）。同一条 key 被后写者覆盖时
  字母会变——这是设计（后写者证据更强），所以排查「答案怎么又变了」先 `bank.py get` 看 `src`。

## 手工补题（命令行）的三个坑

补一条答案看起来是最简单的操作，但它有两个**静默**失败模式，都会让「明明补了答案却还是 miss」
这件事发生第二次。

- **题干被 shell / 编码改掉，key 就变了。** 题干里常有 `>`、`&`、`<`（`E1>E2` 这种），
  PowerShell 会把它们当重定向或运算符；中文 Windows 的管道又是 cp936 字节流。
  两者任一发生，写进去的 key 与页面上的题干不一致，`lookup` 精确匹配永远 miss，
  而你以为已经修好了。→ 题干改用 `python bank.py put - C <<'EOF' ... EOF` 从 stdin 读；
  `_stdin_text()` 按 `utf-8 → gbk → cp936` 依次试解码，`put` 还会把写入的 key 前 60 字回打出来。
- **`errors="replace"` 会写出代理对，把整个题库变成不可写。** 实测踩过：cp936 字节按
  UTF-8 + `replace` 解码产生孤立代理字符（`'\udca2'`），`json.dump` 当场抛
  `UnicodeEncodeError: surrogates not allowed` —— 而后面的 traceback 看起来像是「写文件失败」，
  实际是「题目文本本身就是坏的」。→ `_clean()` 落库前 `encode("utf-8","replace").decode(...)` 兜一层；
  `cli_stdin_recovers_a_cp936_stem_instead_of_polluting_the_bank` 守着它。
- **`put` 更新要 merge，不能整条替换。** 手工只报字母时，若直接写
  `{"letters": [...]}`，会把 harvest 记下的 `type` / `opts` 抹掉；之后 `stats`
  里那一条题型是空的，再想按题型判断候选（判断题封顶 2）就没有依据了。
  → `put()` 现在保留旧字段，只覆盖传进来的。

## 浏览器 / 会话

- Edge 在 `--user-data-dir` 指向真实默认 profile 时会静默忽略 `--remote-debugging-port`
  （Chromium 136+）。用 NTFS junction 指向同一目录既满足检查又保住 cookie。
- 知到会话 cookie 是 session 级；v20 app-bound 加密意味着 Cookies 与 Login Data
  都无法离线解密（`InvalidTag()`）。别围着它设计任何方案。
- **易盾滑块过不去**：`Input.dispatchMouseEvent` 与 `Input.dispatchTouchEvent` 两种拖法
  都失败，即使 gap 偏移算对了。登录只能用户手动做。复制 profile 也不行——
  Cookies 文件被占用（错误 32 共享冲突），而且解不开。
- 中文输入法会把地址栏里的 `javascript:` 变成 `javascript：`（全角冒号）。
  不要用 `javascript:` URL 注入。
- `cdp.page_ws()` 返回 `(ws_url, target)`；先 `WS(url)` 再调，否则
  `AttributeError: 'str' object has no attribute 'call'`。
- 新建 WebSocket 偶发 500 → `cdp.connect()` 有 4 次指数退避重连。
- Windows 上 `tasklist //FI ...` 会被 MSYS 路径改写搞坏，`cmd //c start` 起不了 Edge；
  用 `nohup ... &`。`taskkill` 一次杀掉整棵 Edge 树就会丢登录态，别这么干。

## 刷不动的点

卡片显示 **免考 / 去练习** 的知识点没有练习卷。它的按钮打开
`masteryHistory/<course>/<class>/<kid>`，里面没有 `.improve-btn`。`aria-valuenow` 缺失，
DOM 扫描记成 `?`。`drive.open_quiz` 会抛 `drive.NoPaper`，`run_point` 记 `stage=no_paper`，
`verify.py` 与 `audit.md` 都把它**排除在欠账之外**、单独一节列出。

不是自动化失败，换个题库也刷不动。向用户报告即可，**不要重试**。

## 验收：程序要能给自己判红

这一节的每一条都属于同一类错误——**跑完看起来是成功，其实没有**。

- **循环返回 ≠ 课程刷完。** 旧 `main` 打完 `ALL_DONE` 就 `return 0`，于是一个卡在 76 的点
  在退出码上等于成功。现在 `main` 结尾自己调 `verify.check`：达标 0、欠账 3，
  日志里那行 `ALL_DONE` 也改名 `RESULT`（不再宣称完成）。
- **空扫描不能算通过。** `points=0 short=0` 曾经输出 `VERDICT ok`：没扫到卡片被读成
  「全都 100 了」。`verify.check` 现在第一条就是 `no_scan`；`batchall.main` 见到
  空网格打 `NO_SCAN` 并返回 2。
- **`post_run_grid` 里失败的题必须给一个低于目标的数字。** `live.classify` 把
  「环不可解析」当作免考（这对 `?` 是对的）。所以跑完自验收时，`open_err` 这种没有
  mastery 的点如果原样传 `None`，就会被归到免考、被验收豁免——最该被看见的题反而隐身。
  有跑前掌握率就用它，没有就用 `-1` 哨兵。
- **免考不是欠账。** `summary.write_summary` 的 `problems`、`verify` 的 problem 循环、
  `audit.md` 的未达标表都显式排除 `no_paper`。混进去的后果是「全部刷完」永远显示
  「有 3 个点未达标」。
- **stage 的中文说明只能有一份。** 原先 `batchall.WHY` 和 `probe.explain` 各写一套，
  验收报表里的 `why` 和 audit 里的说明会漂成两句话。现在唯一来源是 `probe.STAGES`。
- **`verify` 的 `unfinished.why` 不要剥 `probe_` 前缀。** 剥掉之后 `probe_stuck`
  变成 `stuck`，会命中另一条（更模糊的）解释；`STAGES` 已经覆盖全名。
- **四步顺序不能省。** 跳过 `doctor.py` 就开跑 → 对着登出状态的浏览器刷一上午；
  跳过 `live.py` → 验收要读的网格根本没生成。`run_all.py` 就是这条顺序的固化版：
  前一步的退出码非 0 就停，绝不在坏通道上继续。`selftest.py` 里有两条用例守着
  「预检失败不扫页」「空网格不开刷」。

## 反解（probe）的三个反直觉点

1. **从「证据的缺失」开始搜，不要从第 1 题开始。** harvest 与我们提交的一致 ⇒ 该题
   **已证正确**，永不再试；不一致 ⇒ 直接改库，零成本；只有 harvest 完全没提到的题才是嫌疑。
   旧版从第 1 题开始试，先花一张卷确认第 1 题本来就对，什么都没变，于是又从头开始，
   12 张全废。
2. **某题所有候选都没让 `N` 上升 ⇒ 说明它本来就对**，标记 `proved_right` 换下一题。
   没有这第二层归因，probe 会在同一个错位置上转圈到预算耗尽。
3. **probe 找到答案后必须交回主循环。** 全对只有 94，还要再一轮才结算 100。
   `probe_perfect` 是一个**中间态**，不是完成态。

预算按候选数排：判断题 2 个候选 → 单选 3 个 → 多选 ≤4；多选 >4 直接返回 `[]`，不炸预算。
