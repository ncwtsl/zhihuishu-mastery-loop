# zhihuishu-mastery-loop

把知到（智慧树）「知识学习」每个知识点的掌握率刷到 100% 的可复用工具包。
本包由一次完整的实战跑通（大学物理Ⅱ 53 个知识点，50 个刷满、3 个平台无练习卷）总结而成。

- 用法与原理：[SKILL.md](SKILL.md)
- 踩过的坑（改代码前必读）：[reference/GOTCHAS.md](reference/GOTCHAS.md)
- 脚本：`scripts/`
- 题库种子（205 条）：`data/answers.json`

## 快速开始

```bash
./scripts/launch_edge.sh                       # 起一个带 9222 的 Edge（保留登录态）
# 浏览器里手动登录一次知到
export ZHS_COURSE=<课程id> ZHS_CLASS=<班级id>
cd scripts
PYTHONIOENCODING=utf-8 python doctor.py        # 通道自检
PYTHONIOENCODING=utf-8 python live.py          # 掌握率基线
PYTHONIOENCODING=utf-8 python batchall.py      # 开跑（挂后台，40-90 分钟）
PYTHONIOENCODING=utf-8 python live.py          # 复核，rest=0 才算完成
```

## 它做什么

每个知识点：开一张新练习卷 → 读题 → 查题库 → 未命中的先猜 `A` → 顺序作答 → 提交 →
从解析页把参考答案抓进题库 → 重复到掌握率 100。

首次全对只有 94–96 分，再全对一轮才到 100；有生题时先拿 45–78 分，入库后下一轮就全对。
答错一次掉约 18 分，所以不能硬答，靠「猜 + 学」收敛最稳。
