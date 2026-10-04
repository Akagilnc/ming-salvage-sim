# #1847 w5 frozen scan dossier（一次性卷宗，非永久运行机制）

本目录冻结本轮全类枚举扫描脚本与原始产物，供核验复现。**不是**游戏运行时机制。

## 复现命令

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1847-w5
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  evidence/1847-w5-rescan/scan_classify_n6_n13.py
```

脚本会重写本目录下 `n6_*` / `n11_*` / `n12_*` / `n13_*` / `summary.json`，并同步 LF 规范表到：

- `evidence/1847-w5-n6-members.tsv`
- `evidence/1847-w5-n11-members.tsv`
- `evidence/1847-w5-n12-members.tsv`
- `evidence/1847-w5-n13-members.tsv`
- `evidence/1847-w5-exempt-files.tsv`

## 产物

| 文件 | 含义 |
|---|---|
| `scan_classify_n6_n13.py` | 枚举+逐项分类真源脚本 |
| `n6_candidates_raw.tsv` | N6 机械候选 |
| `n6_members_classified.tsv` | N6 已验证去留（含具体 source→dest） |
| `n11_focus.tsv` | N11 全扫命中（含 EXCLUDED_noise） |
| `n11_exclusion_summary.tsv` | N11 噪音排除口径计数 |
| `n12_literal_hits.tsv` | N12 字面量/枚举名命中 |
| `n12_exclusion_note.tsv` | N12 未入成员表的排除规则 |
| `n13_focus.tsv` | N13 全扫命中与去留 |
| `summary.json` | 计数摘要 |

## 说明

- 上轮 `/tmp/1847-w5-rescan/` 临时目录已不可核；本卷宗取代之。
- 先前 N6/N10 真实入口变异证据仍在 `evidence/1847-n6-n10-mutation.txt` / `evidence/1847-selfcheck-mutation.txt`（勿覆盖）。
