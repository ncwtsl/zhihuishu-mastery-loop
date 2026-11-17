---
name: zhihuishu-mastery-loop
description: Drive 智慧树/知到 (zhihuishu) 「知识学习」knowledge-point mastery to 100% by repeatedly taking each auto-generated quiz until every answer is correct, self-auditing the bank after every submit and reverse-engineering the remaining answers from the result page's 已答对 count. Use when asked to raise 掌握率/掌握度 on a zhihuishu course, to 刷题/刷掌握度/刷知到, to auto-answer 知到 知识点练习, or to audit mastery percentages per knowledge point. Dependency-free CDP driver; attaches to an already-logged-in Edge, and can rehearse the whole loop offline with `--fake`.
---

# 知到（智慧树）知识学习掌握率刷满

拿一个**已经登录**的 Edge，通过 CDP 反复做每个知识点的自动生成练习卷，直到掌握率圆环到 100%。

它不是「背题库然后祈祷」：每提交一次，程序都会拿解析页的参考答案跟**自己刚提交的答案**对一遍，
不一致的当场改库；三轮分数不动就换 `probe` 用结果页的 `已答对 N/M` 当神谕，反推出那一道错的题。
所以「库里有错答案」这种最容易把一轮 40 分钟跑成白跑的坑，是**有闭环**的。

改脚本前先读 [`reference/GOTCHAS.md`](reference/GOTCHAS.md)。里面每一条都曾经让程序吐出
「看起来很正常的错误数字」。

## 一分钟先摸清它长什么样（不需要浏览器）

```bash
cd scripts
python selftest.py     # 56 个离线用例：题库定键、判断题字母、反解归因、验收判定、自验收退出码
python batchall.py --fake
```

`--fake` 会拿内置夹具（1 个「库里存了错答案且解析页不给答案」的点、1 个混合题型、1 个免考点）
把**真实的 `run_point` 全流程**跑一遍，产出 summary/audit，并用 `verify` 给自己打验收：

```
爱因斯坦光子假设 hist=[79.7, 79.7, 79.7, 100.0] done     # 三轮不动 → probe 反解 → 续跑刷到 100
光电效应 [39.0, 94.0, 100.0] done                        # 空库先猜 → 学 → 94 → 100
导体表面电荷密度与尖端放电 no_paper
points=3 at_target=2 short=0 no_paper=1 bank=8
VERDICT ok
```

改完任何逻辑先跑这两条，再碰真浏览器。离线跑不通的流程，线上只会更慢地失败。

## 前置条件

### 1. 一个已登录知到、且开了调试端口的 Edge

直接用默认 profile 启动会被 Chromium 136+ 静默忽略 `--remote-debugging-port`，
所以要用 NTFS junction 指向真实 profile（cookie 仍在，只是路径变了）：

```bash
./scripts/launch_edge.sh            # 建 junction + 带 9222 启动 Edge，等到端口真起来
```

等价手工命令：

```bash
powershell.exe -NoProfile -Command "New-Item -ItemType Junction -Path '.\\.edge-junction' -Target 'C:\Users\<you>\AppData\Local\Microsoft\Edge\User Data'"
"/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" \
  --remote-debugging-port=9222 \
  --user-data-dir="C:/path/to/workspace/.edge-junction" \
  --no-first-run --no-default-browser-check &
```

如果 Edge 已经在跑（没有调试端口），新进程会**复用旧实例并忽略参数**，`launch_edge.sh`
因此等 20 秒后报错——这时必须让用户先关掉浏览器。

然后让用户**手动登录一次**。知到会话是 session 级 cookie，v20 app-bound 加密，
离线解密只会得到 `InvalidTag()`；`javascript:` URL 注入会被中文输入法把 `:` 变成全角。
不要在这些方向上花时间。

### 2. 运行期间不要重启浏览器

重启一次就要用户手动过易盾滑块，而 CDP 合成事件拖不过去
（`Input.dispatchMouseEvent` 与 `Input.dispatchTouchEvent` 都验过）。

### 3. 注入课程 id

课程 id 来自 URL `.../knowledgeStudy/<ZHS_COURSE>/<ZHS_CLASS>`：

```bash
export ZHS_COURSE=2092834400809041920 ZHS_CLASS=333872 ZHS_PORT=9222
export ZHS_DATA="$PWD/data"
```

## 流程

命令都在 `scripts/` 下执行，并加 `PYTHONIOENCODING=utf-8`。

### 一条命令跑完（推荐）

```bash
python run_all.py                    # 预检 → 基线 → 刷题 → 自验收
python run_all.py --dry              # 只做预检与基线
python run_all.py --resume           # 跳过已达标
python run_all.py --fake             # 离线演练，完全不碰浏览器
```

`run_all.py` 只是把下面 0–3 步按顺序调一遍并**在失败处停下**，退出码即结论：
`0` 全部达标 / `1` 预检没过 / `2` 课程页没解析到卡片 / `3` 跑完但仍有点欠账。
手工排查时仍可按下面四步单独执行。

### 0. 自检通道

```bash
python doctor.py
```

五项检查 + 一个结论：数据目录可写 → 题库能否解析 → 端口可达 → 知到标签页（是否登录 / 自己的标签页
有没有堆起来）→ 学习页三个关键选择器（`.item-content[knowledgeid]` / `.el-progress` /
`.simplified-mastery__action`）。`FAIL` 直接给可执行的补救提示，比在循环里撞 `IndexError` 好排查。
退出码非 0 就不要开跑；`VERDICT ready_with_warnings` 可以跑，但看一遍告警。

### 1. 建立基线

```bash
python live.py
```

输出 `total=N done100=N rest=N free(no quiz)=N`，并把
`[knowledgeId, 名称, aria-valuenow 或 "?", 卡片文本, 按钮文本]` 写进 `$ZHS_DATA/dom_mastery.json`。

DOM 扫描是权威进度来源——JSON 接口 `list-knowledge-theme` 需要 AES `secretStr`，
只能靠临时注入 hook 在 reload 时截获，不适合日常复现。

`?` 表示该知识点**根本没有练习卷**：卡片显示「免考 / 去练习」，按钮跳
`masteryHistory/...`，页面里没有 `.improve-btn`。刷再多也到不了 100，
必须单独向用户报告为「平台未开练习卷」，不要当成自动化失败。

扫描会拿**上一次的行数当地板**：卡片网格是懒渲染的，只画出一半时如果直接采信，
没被扫到的点整轮都不会被驱动，而 summary / audit / verify 照样报成功——这是另一种
「假完成」。所以行数不足时会继续重读；仍然缩水就打印 `SCAN_SHORT previous=53 now=40`。
看到这行别继续跑，先确认 `ZHS_COURSE` 和登录态，否则那 13 个点等于没做。

### 2. 跑循环

```bash
python batchall.py                    # 所有未满 100 的点
python batchall.py <kid1>,<kid2>      # 指定知识点
python batchall.py - 5                # 剩余里取前 5 个（先小批量试水）
python batchall.py --resume           # 跳过 summary.json 里已到目标的点
python batchall.py --no-probe         # 只直答不反解（题库已很全时更快）
```

每个点：开一张新卷 → 读全部题 → 查题库 → 未命中的猜 `ZHS_GUESS`（默认 `A`）→ 顺序作答 →
核对每题 `answerState` → 提交 → 解析结果页 → **自查并修库** → 重复到目标掌握率。

每轮日志行末尾的 `verdict=` 是四个数字的一句话结论：`shy` 说明题库还有错答案，
`collapse` 说明答案根本没提交上去（机制问题，不是内容问题），`perfect` 说明只剩平台
「连续两轮全对」那条规则挡着。看到 `shy` 连续三轮不变，就该让 probe 上场了。

**预期形态**：首次全对得 94–96，再全对一轮才到 100；有未命中题时得 45–78，入库后下一轮就全对。
所以每个点 2–3 轮、每轮约 35–40 秒。答错一题掉约 18 分，因此「猜 + 学」永远比「半懂硬答」稳。

35–50 个点要 45–90 分钟。挂后台跑、轮询日志，不要阻塞等待。
每个点跑完都会重写一次 `summary.json`，所以中途被杀也不会丢进度，`--resume` 接着跑。

### 3. 验收与汇报

`batchall.py` 跑完会**自己调一次 `verify.py`**，把 `points=… at_target=… short=…` 和
`VERDICT ok|not_ok` 打进日志，并以此决定退出码（达标 0、欠账 3）。所以「循环返回了」
和「课程刷完了」不再是同一件事——旧版打印 `ALL_DONE` 就返回 0，一个卡在 76 的点也会被当成成功。

想看独立结论（或重扫课程页拿最新数字）：

```bash
python verify.py --refresh      # 重扫课程页并验收，非 0 退出即未达标
python verify.py --json         # 机器可读
```

`verify.py` 判四件事，任一不成立就红：

0. **有证据** —— 扫描网格为空直接判 `no_scan`。`points=0 short=0` 曾输出 `VERDICT ok`，
   把「没扫到」报成了「全做完」。
1. **没有点欠账** —— 每个有圆环的卡片都到目标；`?`（免考）排除，不算 0。
2. **历史是诚实的** —— `done` 的点最后一轮必须 ≥ 目标；序列里出现 `83.3 / 66.7 / 33.3 / 16.7`
   判 `progress_bar_read_as_mastery`（那是答题进度被当成了掌握率）；末位 `None` 判 `no_point_page`。
3. **在收敛** —— 未完成的点若最近三轮分数一模一样，判 `not_converging`：
   plan 没变，再跑一轮也不会变，该上 `probe` 或修库。

不达标时它会直接点出「哪个点、什么阶段、中文原因」，不用回头翻日志。
最后把 `$ZHS_DATA/audit.md` 交给用户：已达标表格 + 未达标原因 + 免考点清单 + 一句结论。

## 为什么能到 100：三个机制

### 题库 + harvest（每轮都在变准）

`$ZHS_DATA/answers.json`，key 是**规范化题干**（`bank.norm`：先去标签 → `html.unescape()` →
删所有空白），value 是 `{"letters":["AC"],"type":"多选题","opts":[...]}`。
每次提交后 `harvest.py` 打开本次 attempt 的 `examPreview`，按题号把参考答案抓进来。

两个细节是 load-bearing 的：

- **`sort`（题号）必须保留**。没有题号，错答无法归因到具体题，自查就是瞎猜。
- **判断题的 `对/错` 必须翻译成该卷的真实选项字母**。存字面量「对」会让所有判断题 key 永远 miss。

### 自查修库（错答案当场改）

提交完拿解析页的参考答案和**自己刚发出去的 plan** 逐题比，不一致就立刻 `bank.put(..., source="audit")`。
旧版只「新增没见过的题」，所以库里一个错字母能活过所有轮次，点永远卡在 76。

### probe 反解（结果页就是神谕）

三轮分数一模一样 ⇒ plan 也一模一样 ⇒ 再跑一轮不可能变。这时 `probe.py` 接管：

- 结果页的 `已答对 N/M` 是真 oracle：改一道题的字母重新提交，`N` 上升就证明找到了那道错的。
- **先免费修**：harvest 与我们一致 ⇒ 该题**已证正确，永不再试**；不一致 ⇒ 直接改库，零成本。
  只有「harvest 完全没提到」的题才是嫌疑——所以搜索从**证据的缺失**开始，不是从第 1 题开始。
- 成本顺序：判断题（2 个候选）→ 单选（3 个）→ 多选 ≤4 选项；多选 >4 直接放弃，别炸预算。
- 某题所有候选都没让 `N` 上升 ⇒ 判定「该题本来就对」，标记 `proved_right` 换下一题。
- 一旦找到，写库（`source="probe"`）后**交回主循环**继续跑——因为全对只给 94，
  还要一轮才结算 100。`probe` 找到答案 ≠ 完成，这是旧版最大的语义错误。

预算 `ZHS_PROBE`（默认 12 张卷）。真实案例：一个点 8 轮卡在 76.0 放弃；
修好归因后 **2 张卷**就锁定答案（`try q3=B -> 5/6`、`try q3=C -> 6/6`）。

## 状态码

`summary.json` 里每个点都有 `stage`，`audit.md` 会翻成中文：

| stage | 含义 | 下一步 |
| --- | --- | --- |
| `done` | 到目标掌握率 | — |
| `no_paper` | 平台未开练习卷（免考卡片） | 报告用户，别重试 |
| `short` | 轮次用尽仍未达标 | `--maxr` 调大或先 `probe.py <kid>` 单独反解 |
| `probe_perfect` | 答案已找全，但还差一轮全对才结算 100 | 再跑一次这个点即可 |
| `probe_stuck` | 候选字母都没让已答对数上升 | 大概率解析页数据本身有问题，人工看一题 |
| `probe_exhausted` | 没有可试的候选了 | 同上 |
| `probe_budget` | 反解预算用完 | `--probe` 调大 |
| `probe_no_target` / `probe_no_count` | 结果页没给 `已答对/总题数` | 反解无法判分，只能靠题库 |
| `open_err` | 练习卷打不开 | 多为登录失效或 `BASE_EMPTY`，重跑 `doctor.py` |
| `submit_failed` | 提交后没跳到 `/point/` | 看日志里的 `.reviewDone` 是否点到 |
| `run_err` | 作答过程报错 | 看日志 |

## 刷不动时怎么查

| 症状 | 真实原因 | 修法 |
| --- | --- | --- |
| 掌握率卡在 76–78，每轮 `guessed=['1']` | 题库里那题存了错字母，旧版只新增不修正 | 现在会自动 probe；也手动 `python probe.py <kid>` |
| 日志有 `SUBMIT_FAILED`，却又出现掌握度数字 | 把答题页的**答题进度**（`83.3`）当成掌握度读了 | `submit_only` 在 `drive.submit` 返回 `None` 时必须直接返回 |
| `NO_HARVEST` 且 `correct=5/6`，连续几轮一样 | 解析页一题答案都没给，本轮无从归因 | 正常，下一轮会重新抓；连续出现就走 `probe.py <kid>` 逐字母试 |
| `BLIND correct=5/6`，每轮都指同一题号 | 解析页只给了部分题目的答案，错的那题正好被藏起来（题库里能查到的都对） | 正常，这就是 probe 的活；`BLIND` 后面那串题号就是搜索起点 |
| `AUDIT_CLEAN correct=5/6` 且全部匹配 | 题库是对的，差异来自作答/提交（某题 `answerState` 没跟上） | 查同一行的 `pending=`，别改题库 |
| 每题都点过，复查却是 `16.7%` / `50%` | 用答题卡跳题会丢弃未提交的选择，答案只在「下一题」时提交 | 用 `swipeAll` 顺序作答，别 `goTo`→`pick`→`goTo` |
| 第二遍过同一题时答案被清空 | 点已选中的选项会**取消选中** | `pick()` 幂等：先读 `.checkIcon.checkedIcon` |
| 日志说 `PENDING` 一堆但页面明明全选了 | `committed()` 拿 `"_OK_" in s` 匹配 `OK_AC/...` 这种前缀串，永不命中 | 用 `s.startswith("OK_")`；`selftest.py` 有对应用例 |
| CDP 越来越慢、最后 500 | 每轮提交都留一个 `/point/` 标签页（见过 43 个） | `submit_only` 读完结果调 `drive.close_targets("/point/")` + `drive.reap()` |
| `KeyError: 'qc'` / `BASE_EMPTY`，批量 `open_err` | `baseInfor` 还没渲染就去读 | `get_base()` 重试 8×1.5s，失败抛 `BASE_EMPTY` 后整轮重开 |
| 掌握率一到位却验收说 `short` | 只在课程页卡片上取数，卡片渲染滞后 | `verify.py --refresh` 重扫；`live.scan()` 拿上次行数当地板，缩水会打 `SCAN_SHORT` |
| 某题选项全是图片 | 文字不可读，环境无 OCR | 直接问用户「题N选X」，`python bank.py put "<题干>" C --type 单选题` |
| 手工补了答案却还是 miss | 题干被 shell 转义（`>` `&`）或编码搞坏，key 变了 | 题干改用 `python bank.py put - C <<'EOF'` 从 stdin 读；`bank.py put` 会回打它写的 key 前 60 字 |

真刷不动时，问用户要那一道题的答案（一句话「题N选X」）并写进题库，
比任何猜测循环都快。**问一句比跑一小时便宜。**

```bash
cd scripts
python bank.py put "题干原文（可以带 HTML）" C --type 单选题   # NEW / UPDATED 都会回打 key
python bank.py get "题干原文"                                 # 0=命中 1=miss（并列出最接近的）
python bank.py near "题干原文"                                # 只诊断
python bank.py stats                                          # 条数 + 题型/答案分布
```

补完立刻 `get` 一次确认命中，别等到下一轮跑完才发现 key 不一致。

## 脚本分工

| 文件 | 作用 | 依赖浏览器 |
| --- | --- | --- |
| `config.py` | 环境变量、URL 模板、路径、带抖动的 `sleep()`、原子写 | 否 |
| `bank.py` | 题库内核：`norm`/`lookup`/`put`/`save`/`near`/`parse_point`/`stalled`；命令行 `put`/`get`/`near`/`stats` | 否 |
| `oracle.py` | 题型判定、候选字母、`pick_best`、`verdict`、`mismatches`、预算 | 否 |
| `harvest.py` | 解析 `examPreview` 的 `.exam-item`，带题号与判断题字母映射 | 是 |
| `verify.py` | 验收判定：无扫描 / 欠账 / 假完成 / 答题进度当掌握率 / 是否在收敛 | 否 |
| `selftest.py` | 56 个离线用例，改逻辑后先跑它 | 否 |
| `fake.py` | 夹具平台，`--fake` 用它把真 `run_point` 全流程演练一遍 | 否 |
| `run_all.py` | 一条命令串起 预检 → 基线 → 刷题 → 自验收，退出码即结论 | 是 |
| `cdp.py` | 零依赖 CDP 客户端（手写 WebSocket）、带退避的连接 | 是 |
| `drive.py` | 标签页生命周期：`open_quiz`/`submit`/`new_tab`/`close_targets`/`reap` | 是 |
| `quiz.py` | 答题页读取：`get_base`/`read_question`/`states`/`pending` | 是 |
| `fast.js` | 页内 `window.__F`：`goTo`/`pick`/`pickMulti`/`swipeAll`/`stateOf` | 是 |
| `fastpy.py` | `fast.js` 的 Python 侧：`open_read`/`answer_all`/`committed`/`submit_only` | 是 |
| `live.py` | 权威掌握度 DOM 扫描（`?` = 免考；缩水会 `SCAN_SHORT`） | 是 |
| `probe.py` | 反解环：归因、候选择序、预算、写库 | 是（可被 `fake.Sim` 替身） |
| `batchall.py` | 无人值守驱动器、报表、`--resume`、`--fake` 入口 | 是 |
| `doctor.py` | 五项预检 + `ready/ready_with_warnings/not_ready` 结论 | 部分 |
| `launch_edge.sh` | 建 junction 并带 9222 启动 Edge | — |

`fast.js` 必须和 `fastpy.py` 放在同一目录，它在 import 时从磁盘读取。
`batchall.py` 与 `probe.py` 都通过 `_Live` 这个窄接口调浏览器，所以 `fake.Sim` 能整替进去——
这条注入缝是这套技能能被离线测试的原因，改签名时两边一起改。
stage 的中文说明只有一份：`probe.STAGES`，`batchall.WHY` 与 `verify` 的 `why` 字段都指向它，
所以报表、日志、验收说的永远是同一句话。

## 产物

| 路径 | 内容 |
| --- | --- |
| `$ZHS_DATA/answers.json` | 题库，跨课程可复用（不入 git） |
| `$ZHS_DATA/dom_mastery.json` | 最近一次课程页扫描网格 |
| `$ZHS_DATA/batchall.log` | 全量日志 |
| `$ZHS_DATA/result_<kid>.json` | 每个点的单点结果 |
| `$ZHS_DATA/summary.json` | 汇总（每点跑完即重写，供 `--resume`） |
| `$ZHS_DATA/audit.md` | **给用户看的报表** |

## 可调项

- `ZHS_COURSE` / `ZHS_CLASS` —— URL 里的课程与学期 id。
- `ZHS_PORT` —— CDP 端口，默认 9222。
- `ZHS_DATA` —— 题库、扫描结果、日志目录，默认 `../data`。
- `ZHS_TARGET` —— 算达标的掌握率，默认 100。
- `ZHS_MAXR` —— 每个点最多几张卷（不含反解），默认 9。
- `ZHS_PROBE` —— 每个点的反解预算，默认 12。
- `ZHS_JITTER` —— 每个动作额外随机化的秒数，默认 0.4；固定节奏是最容易被识别的自动化指纹。
- `ZHS_GUESS` —— 生题兜底字母，默认 `A`。
