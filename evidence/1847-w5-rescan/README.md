# #1847 w5 frozen scan dossier（机械扫描；非 KEEP 判决）

本目录冻结全类枚举扫描脚本与原始产物，供核验复现。**不是**游戏运行时机制。

**CORRECTED CONTRACT**：自动规则只标 `PENDING_HUMAN` / `POTENTIAL_*` / `MECHANICAL_*` /
`DELETED_KNOWN`，**不产 KEEP verdict**。人工 KEEP/DELETE 见
`evidence/1847-w5-correction/human_judgment.tsv`。

## 复现命令

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1847-w5
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  evidence/1847-w5-rescan/scan_classify_n6_n13.py
```

## 产物

| 文件 | 含义 |
|---|---|
| `scan_classify_n6_n13.py` | 机械枚举+潜在标记（无 KEEP） |
| `n6_candidates_raw.tsv` | N6 机械候选原始表（保留） |
| `n6_members_classified.tsv` | N6 机械 disposition（PENDING/MECHANICAL…） |
| `n11_focus.tsv` | N11 全扫命中（含 POTENTIAL_NOISE） |
| `n11_exclusion_summary.tsv` | 机械 disposition 计数（非完整排除证明） |
| `n12_literal_hits.tsv` | N12 字面量/枚举名命中（扫描面） |
| `n12_exclusion_note.tsv` | 排除须人工；字面命中≠判决 |
| `n13_focus.tsv` | N13 全扫命中与机械标记 |
| `summary.json` | 计数摘要 |

## 修正引用（不删除本卷宗）

- `evidence/1847-w5-correction/CORRECTION.md`
- `evidence/1847-w5-correction/human_judgment.tsv`
- `evidence/1847-w5-correction/remaining_scope.md`
- `evidence/1847-w5-correction/n6_ask_emperor_pty_mutation.py`
