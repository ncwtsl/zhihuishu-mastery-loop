# zhihuishu-mastery-loop

把知到（智慧树）「知识学习」每个知识点的掌握率刷到 100% 的可复用工具包。
由一次完整实战跑通总结而成（大学物理Ⅱ，53 个知识点：50 个刷满，3 个平台无练习卷）。

- 用法与原理：[SKILL.md](SKILL.md)
- 踩过的坑（改代码前必读）：[reference/GOTCHAS.md](reference/GOTCHAS.md)
- 脚本：`scripts/` · 题库：`data/answers.json`（运行期累积，不入库，见 [data/README.md](data/README.md)）

## 它快在哪

不是「查题库然后祈祷」。三个闭环：

1. **harvest** —— 每次提交后从解析页抓参考答案，按题号入库。
2. **自查修库** —— 拿参考答案和**自己刚提交的答案**逐题比，不一致当场改库。
   旧版只新增没见过的题，所以库里一个错字母能活过所有轮次，点永远卡 76。
3. **probe 反解** —— 三轮分数不动时，用结果页的 `已答对 N/M` 当 oracle，
   逐字母试出那道错的题。判断依据是「harvest 没提到它」，不是「从第 1 题开始试」。

## 快速开始

```bash
./scripts/launch_edge.sh                        # 起带 9222 的 Edge（保留登录态）
# 浏览器里手动登录一次知到
export ZHS_COURSE=<课程id> ZHS_CLASS=<班级id>
cd scripts
PYTHONIOENCODING=utf-8 python run_all.py        # 预检 → 基线 → 刷题 → 自验收
```

退出码即结论：`0` 全部达标 / `1` 预检没过 / `2` 课程页没解析到卡片 / `3` 跑完仍有点欠账。
想分步看，等价于依次跑：

```bash
python doctor.py         # 五项预检，非 0 退出就别跑
python live.py           # 掌握率基线
python batchall.py       # 开跑（挂后台，40–90 分钟）
python verify.py --refresh
```

补答案不用写 Python，题库自带命令行（题干含 `>` `&` 或换行时用 `-` 从 stdin 读）：

```bash
python bank.py put "题干原文" C --type 单选题   # 回打写入的 key，便于确认没被转义搞坏
python bank.py get "题干原文"                   # 0=命中 1=miss（并列出最接近的）
python bank.py stats                            # 条数与题型/答案分布
```

报表落在 `data/audit.md`，直接交给用户。

## 不用浏览器也能验一遍

```bash
cd scripts
python selftest.py          # 56 个离线用例（题库定键、判断题字母、反解归因、验收判定、退出码）
python run_all.py --fake    # 用夹具把真 run_point 全流程跑通，含 probe 反解与自验收
```

`--fake` 会复现两种真实行为：库里存了错答案且解析页不给答案（必须靠 probe 反解），
以及「首次全对只有 94，再一轮才 100」。改任何逻辑先跑这两条。

## 三个数字

- 全对第一轮 **94–96**，再一轮全对才 **100**。
- 错一题掉约 **18 分**（94 → 76）。
- 所以未命中的题先猜 `A` 再学，比「半懂硬答」稳。

现场案例：一个点 8 轮卡在 76.0 全靠重试；修好归因后 **2 张卷**就锁定答案。

## 它不会假装成功

这套东西最容易犯的错不是「刷不上去」，而是「刷失败却报告完成」。所以：

- 每轮记录 `verdict=`（`shy` 库还错 / `collapse` 没提交上 / `perfect` 只差平台规则）。
- 跑完自己调 `verify.py`，退出码 3 就是还有欠账，不叫 `ALL_DONE`。
- 扫描行数拿上次当地板，缩水打 `SCAN_SHORT`，不静默丢掉知识点。
- 判断题只试两个候选，不为一道是非题烧掉四张卷。

