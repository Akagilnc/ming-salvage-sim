# J6 处置说明（宽谓词续轮）

## 类定义（未收窄）

非契约内部证明、mock 替代被测行为、helper 专测、退役行为、非契约文字锁、内部 oracle、调用 mock；必要闸负向保留真实入口+实际结果；原文无损契约 ≠ 拼装材料措辞锁。

## 证据分层

| 文件 | 含义 |
|---|---|
| `j6_enumerate_universe.py` + `j6-universe.jsonl` | 全仓测试声明全集（机械） |
| `j6_flag_structural_candidates.py` + `j6-structural-candidates.jsonl` | **宽谓词**结构候选（已去自限） |
| `j6-wide-candidate-disposition.jsonl` | 宽候选全量语义处置（含 disposition_basis） |
| `j6-semantic-members.jsonl` | 确认类成员（delete/migrate 史） |
| `j6-class-members-wide-round.jsonl` / `j6-clear-residuals.jsonl` | 本轮落地删改 |

禁止把 structural-candidates 或「无高置信规则」当作 retain/免责结论。

## 复扫计数

见 `j6-wide-disposition-summary.json`（universe / wide candidates / outstanding_high_confidence_in_tree）。

## 核验

```sh
python3 evidence/1900-j18-j6-retire-fixer/j6_enumerate_universe.py
python3 evidence/1900-j18-j6-retire-fixer/j6_flag_structural_candidates.py
python3 -c "import json; print(json.load(open('evidence/1900-j18-j6-retire-fixer/j6-wide-disposition-summary.json')))"
```
