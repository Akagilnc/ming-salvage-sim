# J6 处置说明（纠正轮：证据可核，不宣称 0 开放）

## 类定义（未收窄）

非契约内部证明、mock 替代被测行为、helper 专测、退役行为、非契约文字锁、内部 oracle、调用 mock；必要闸负向保留真实入口+实际结果；原文无损契约 ≠ 拼装材料措辞锁。

## 证据分层（勿混）

| 文件 | 含义 |
|---|---|
| `j6_enumerate_universe.py` + `j6-universe.jsonl` | 全仓测试声明全集（机械） |
| `j6_flag_structural_candidates.py` + `j6-structural-candidates.jsonl` | 结构信号**候选**（有信号≠属类；无信号≠不属类） |
| `j6-class-members.jsonl` | **语义**类成员处置（含可核 entry/result/mock_boundary） |

已移除历史误产物 `j6-all-members-disposition.json`（2886 条机器 stamp retain）。不以「无信号→retain」再生成平行大体量表。

## 测试路径核实

本工作树 find（排除 `.git/.baseline/node_modules/evidence`）：

- roots：`tests`、`web`（`web/src`、`web/src/components`）
- **无** `web/tests/`、`scripts/*test*`、根目录 `test_*.py`、`ming_sim/tests`

全集见 `j6-universe-summary.json`（本轮跑后约 2885 成员 / 234 源文件）。

## 本轮语义处置摘要

见 `j6-class-members.jsonl`（migrate/delete/retain 均带入口与结果）。

结构候选计数（跑完脚本后的快照，**不是**开放类成员数）：见 `j6-structural-candidates-summary.json`。候选须继续读源语义处置；**本回执不宣称 J6 结清 / 开放=0**。

## 核验命令

```sh
python3 evidence/1900-j18-j6-retire-fixer/j6_enumerate_universe.py
python3 evidence/1900-j18-j6-retire-fixer/j6_flag_structural_candidates.py
python3 -c "import json; print(sum(1 for _ in open('evidence/1900-j18-j6-retire-fixer/j6-class-members.jsonl')))"
```
