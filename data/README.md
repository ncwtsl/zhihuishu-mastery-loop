# data/

运行时数据。除本文件外，其余产物都不入 git（见 `../.gitignore`）。

| 文件 | 内容 |
| --- | --- |
| `answers.json` | 题库。key 是规范化题干，value 是 `{"letters":["AC"],"type":"多选题","opts":[...]}` |
| `dom_mastery.json` | 最近一次课程页扫描网格 `[kid, 名称, aria-valuenow 或 "?", 卡片文本, 按钮文本]` |
| `batchall.log` | 全量日志 |
| `result_<kid>.json` | 每个知识点的单点结果 |
| `summary.json` | 汇总；每个点跑完即重写，`--resume` 靠它 |
| `audit.md` | **给用户看的报表**：已达标表 + 未达标原因 + 免考点清单 |
| `.fake/` | `--fake` 演练的产物，与真实数据完全隔离 |

## 题库

首次运行会自动创建。空库也能跑——前一两轮会猜 `A` 拿低分，之后收敛到 100%。

题库**跨课程可复用**：key 是题干规范化后的文本，不同课程里相同的题会直接命中。
有别的机器跑出来的 `answers.json`，直接拷进这个目录即可。

写入是原子的（临时文件 + `os.replace`），中途被杀不会写出半个 JSON。

想手工补一题（比如选项全是图片、问用户问到的答案），用 `bank.py` 的命令行，不用写 Python：

```bash
cd ../scripts
python bank.py put "题干原文（可以带 HTML，norm 会处理）" C --type 单选题
python bank.py get "题干原文"      # 命中返回 0 并打印字母；未命中返回 1 并列出最接近的
python bank.py near "题干原文"     # 只诊断，不写库
python bank.py stats              # 条数 + 题型/答案分布
```

题干里有 `>`、`&` 或换行时，把题干换成 `-` 从标准输入读，避免被 shell 转义搞坏：

```bash
python bank.py put - C --type 单选题 <<'EOF'
（把题干原样粘贴在这里）
EOF
```

题干被搞坏的后果是**静默的**：key 不一致 ⇒ 下次照样 miss，看起来像「补了没用」。
所以 `put` 会把它写进去的 key 前 60 字打出来，一眼能看出是不是同一道题。

`bank.near(b, stem)`（等同 `bank.py near`）可以找出最相近的已有条目，用于排查「明明答过却 miss」。
它只用于诊断——`lookup` 是**精确匹配**，绝不做模糊兜底。
