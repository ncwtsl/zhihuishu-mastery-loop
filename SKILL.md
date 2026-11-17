---
name: zhihuishu-mastery-loop
description: Drive 智慧树/知到 (zhihuishu) 「知识学习」knowledge-point mastery to 100% by repeatedly taking each auto-generated quiz until every answer is correct, harvesting reference answers as it goes. Use when asked to raise 掌握率/掌握度 on a zhihuishu course, to 刷题/刷掌握度/刷知到, to auto-answer 知到 知识点练习, or to audit mastery percentages per knowledge point. Ships a dependency-free CDP driver that attaches to an already-logged-in Edge.
---

# 知到（智慧树）知识学习掌握率刷满

拿一门已经登录的 Edge，通过 CDP 反复做每个知识点的自动生成练习卷，直到掌握率圆环到 100%。
每次提交后从 `examPreview` 抓参考答案入库，所以越刷越准，最终每轮全对。

动手改脚本前先读 [`reference/GOTCHAS.md`](reference/GOTCHAS.md)。那里面每一条都曾经
让程序跑出「看起来很正常的错误数字」。

## 前置条件

1. **一个已登录知到、且开了调试端口的 Edge。**
   直接用默认 profile 启动会被 Chromium 136+ 静默忽略 `--remote-debugging-port`，
   所以要用 NTFS junction 指向真实 profile。脚本已封装：

   ```bash
   ./scripts/launch_edge.sh          # 建 junction + 带 9222 启动 Edge
   ```

   等价手工命令：

   ```bash
   powershell.exe -NoProfile -Command "New-Item -ItemType Junction -Path '.\\.edge-junction' -Target 'C:\Users\<you>\AppData\Local\Microsoft\Edge\User Data'"
   "/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" \
     --remote-debugging-port=9222 \
     --user-data-dir="C:/path/to/workspace/.edge-junction" \
     --no-first-run --no-default-browser-check &
   ```

   注意：如果 Edge 已经在跑（没有调试端口），新启动的进程会**复用旧实例并忽略参数**，
   `launch_edge.sh` 会因此等待 20 秒后报错——这时必须让用户先关掉浏览器。

   然后让用户**手动登录一次**。知到的会话 cookie 是 session 级（`is_persistent=0`），
   cookie 与密码都是 v20 app-bound 加密、无法离线解密（`InvalidTag()` 是正常结果）。
   浏览器被杀掉就掉登录，重新导航回课程页通常能恢复，但不要指望。

2. **运行期间绝不能 `Stop-Process msedge`。** 重启一次就要用户手动过易盾滑块，
   而 CDP 合成事件拖不过去（`Input.dispatchMouseEvent` 与 `Input.dispatchTouchEvent` 都验过）。

3. 课程 id 取自 URL `.../knowledgeStudy/<ZHS_COURSE>/<ZHS_CLASS>`，连同端口和数据目录一起注入：

   ```bash
   export ZHS_COURSE=2092834400809041920 ZHS_CLASS=333872 ZHS_PORT=9222
   export ZHS_DATA="$PWD/data"
   ```

## 流程

命令都在 `scripts/` 下执行，并加 `PYTHONIOENCODING=utf-8`。

### 0. 先自检通道

```bash
python doctor.py
```

检查端口是否可达、有没有开着的知到标签页、当前页是不是登录页。
`FAIL` 会直接给出可执行的补救提示，比在循环里撞 `IndexError` 好排查。

### 1. 建立基线

```bash
python live.py
```

输出 `total=N done100=N rest=N free(no quiz)=N`，并把
`[knowledgeId, 名称, aria-valuenow 或 "?", 卡片文本]` 写到 `$ZHS_DATA/dom_mastery.json`。
DOM 扫描是权威进度来源——JSON 接口 `list-knowledge-theme` 需要 AES `secretStr`，
只能靠临时注入 hook 在 reload 时截获，不适合日常复现。

`?` 表示该知识点**根本没有练习卷**：卡片显示 `免考 / 去练习`，按钮跳到
`masteryHistory/...` 且页面里没有 `.improve-btn`。这类要单独向用户报告为
「平台未开练习卷」，刷再多也到不了 100%。

### 2. 跑循环

```bash
python batchall.py                # 所有未满 100 的知识点
python batchall.py <kid1>,<kid2>  # 指定知识点
python batchall.py - 5            # 剩余里取前 5 个
```

每个知识点：开一张新卷 → 读全部题 → 查题库 → 未命中的一律猜 `A` → 顺序作答 → 提交 →
解析结果页 → 抓参考答案入库 → 重复直到掌握率 100（最多 9 轮）。
日志打到 stdout 和 `$ZHS_DATA/batchall.log`，每个点落 `$ZHS_DATA/result_<kid>.json`。

**预期形态**：首次全对得 94–96，再全对一轮才到 100；有未命中题时得 45–78，
入库后下一轮就全对。所以每个点 2–3 轮、每轮约 35–40 秒。答错一题会掉约 18 分，
所以不能靠「半懂」硬答，猜完靠 harvest 学才是稳的。

35–50 个点要跑 45–90 分钟。挂后台跑、轮询日志，不要阻塞等待。

### 3. 核验与汇报

```bash
python live.py   # 重扫
```

只有 `rest=0` 才算成功。再和 `$ZHS_DATA/result_<kid>.json` 里的分数序列对一遍，
并把 `free(no quiz)` 的点单独说明原因——不要当成自动化失败，也不要悄悄略过。

## 可调项

- `ZHS_COURSE` / `ZHS_CLASS` —— URL 里的课程与学期 id。
- `ZHS_PORT` —— CDP 端口，默认 9222。
- `ZHS_DATA` —— 题库、扫描结果、日志目录，默认 `../data`。
- `$ZHS_DATA/answers.json` —— 题库，按规范化题干作 key，跨课程可复用同一题库池。

## 刷不动的点怎么办

| 症状 | 真实原因 | 修法 |
| --- | --- | --- |
| 掌握率卡在 76–78，日志每轮 `guessed=['1']` | 题库 key 失配，常见是 HTML 实体（`&gt;` vs `>`）导致同一题两个 key | `auto.norm()` 必须先去 `html.unescape()` 再压空白 |
| 日志有 `SUBMIT_FAILED`，但同时又出现掌握度数字 | 把答题页的**答题进度**（`83.3`）当成掌握度读了 | `submit_only` 在 `drive.submit` 返回 `None` 时必须直接返回 |
| 每题都点过，复查却是 `16.7%` / `50%` | 用答题卡跳题会丢弃未提交的选择，答案只在「下一题」时提交 | 用 `swipeAll` 顺序作答，别 `goTo`→`pick`→`goTo` |
| 第二遍过同一题时答案被清空 | 点击已选中的选项会**取消选中** | `pick()` 要幂等：先读 `.checkIcon.checkedIcon` |
| CDP 越来越慢、最后 500 | 每轮提交都留一个 `/point/` 标签页（见过 43 个） | `submit_only` 读完结果后调 `drive.close_targets("/point/")` |
| `KeyError: 'qc'` / `BASE_EMPTY`，批量 `open_err` | `baseInfor` 还没渲染就去读 | `get_base()` 重试 8×1.5s，失败抛 `BASE_EMPTY` 后整轮重开 |
| 某题选项全是图片 | 文字不可读，环境无 OCR | 直接问用户「题N选X」，按 `auto.norm(stem)` 手工入库 |

真刷不动时，问用户要那一道题的答案（一句话「题N选X」）并写进 `answers.json`，
比任何猜测循环都快且可靠。

## 脚本分工

| 文件 | 作用 |
| --- | --- |
| `config.py` | 读环境变量、拼所有 URL、管路径 |
| `doctor.py` | 预检：端口、标签页、登录状态 |
| `cdp.py` | 零依赖 CDP 客户端（`WS`、`page_ws`、`evaljs`） |
| `quiz.py` | 答题页读取（`read_question`、`states`、`qtype`） |
| `fast.js` | 注入页内的 `window.__F`：`goTo`、`pick`、`selection`、`swipeAll` |
| `fastpy.py` | `fast.js` 的 Python 侧：`open_read`、`answer_all`、`submit_only`、`get_base` |
| `drive.py` | 标签页生命周期：`open_quiz`、`submit`、`new_tab`、`close_targets` |
| `harvest.py` | 解析 `examPreview` 的 `.exam-item` 成 `{stem, letters}` |
| `auto.py` | 题库读写与 `norm()` 定 key |
| `live.py` | 权威掌握度 DOM 扫描 |
| `batchall.py` | 无人值守驱动器 |

`fast.js` 必须和 `fastpy.py` 放在同一目录，它在 import 时从磁盘读取。
