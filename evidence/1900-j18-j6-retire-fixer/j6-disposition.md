# J6 处置说明（源头语义审阅闭环）

## 类定义（未收窄）

非契约内部证明、mock 替代被测行为、helper 专测、退役行为、非契约文字锁、内部 oracle、调用 mock；必要闸负向保留真实入口+实际结果；原文无损契约 ≠ 拼装材料措辞锁。

## 唯一权威成员表

| 文件 | 含义 |
|---|---|
| `j6_enumerate_universe.py` + `j6-universe.jsonl` | 全仓测试声明全集（机械） |
| `j6_flag_structural_candidates.py` + `j6-structural-candidates.jsonl` | 宽谓词结构候选 |
| **`j6-wide-candidate-disposition.jsonl`** | **唯一当前权威完整处置表**（每项含 entry / result / mock_boundary / text_oracle_helper_necessity / reason / disposition_basis） |
| `j6-wide-disposition-summary.json` | 计数摘要 |
| `j6-semantic-members.jsonl` / `j6-class-members-wide-round.jsonl` / `j6-clear-residuals.jsonl` | 历史落地删改记录（不替代权威表） |
| `semantic-review-queue/advisor-shards/advisor-*-disposition.jsonl` | 顾问源头审阅产出（已并入权威表） |

已删简误导表：`j6-wide-disposition-batch{1,2,3,prio}.*`、`j6-disposition-private-helper.*`、以及以 `wide_flag_no_high_confidence_member_rule` 充当 retain 的旧权威副本。历史提交不 rewrite。

## 处置规则

- 确认类成员：`delete` / `migrate`（代码侧删简修净）
- 必要负向：真实入口 + 实际结果 → `retain`
- 禁止：机器低置信 retain、一句「公开入口+可观察结果」、新增测试钩子/平行夹具

## 复扫

```sh
python3 evidence/1900-j18-j6-retire-fixer/j6_enumerate_universe.py
python3 evidence/1900-j18-j6-retire-fixer/j6_flag_structural_candidates.py
python3 -c "import json; print(json.load(open('evidence/1900-j18-j6-retire-fixer/j6-wide-disposition-summary.json')))"
```

不自行宣布 J6 converged / 类净。本轮：结构复扫 2477 全处置、`migrate_outstanding_in_tree=0`、`wide_flag=0`；J18 与家族缺口仍归 #1873。
