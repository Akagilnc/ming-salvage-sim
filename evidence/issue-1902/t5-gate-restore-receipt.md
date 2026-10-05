# #1902 修内司 T5 闸类负向误删恢复回执

- 分支：`ak-roles/1902-t1t6-fixer-092109acf`
- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5`
- 判词真源：PI session `01a10a10-a917-76cc-966b-7ef94176ba78@fixer` run-state instruction（T1 已结；T2/3/4/6 不重开；仅 T5 删错闸类负向）
- **不宣称已合并 / 总票完成**；未 stash/push/PR/amend；未改治理文件

七 BIN 前缀（本轮全部测试显式展开）：

```bash
env \
  MING_SIM_AGY_BIN=/usr/bin/false \
  MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false \
  MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false \
  MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=. \
  python3 -m pytest ...
```

---

## 判词要点（落实）

1. 不恢复 helper 直测。
2. 复用原测试文件，改走真实入口最短案。
3. 样本：`test_coerce_new_salary_rate_blocks_freeload` / `test_non_finite_salary_rate_anchored_not_crash` → 一条 `create_armies_from_extraction` 多项非法 `salary_rate` 落库断言锚点 1.5。
4. 全部 72 删除成员（63+9）逐项复核；闸类无继任才改走入口；pairing / is_real_api_key / promulgation 抽查已有继任不重造。
5. 不虚构 successor、不批量同句。

---

## 本轮恢复（入口案，非 helper）

| 原删除 | 生产入口 | 恢复节点 |
|---|---|---|
| `test_coerce_new_salary_rate_blocks_freeload` | `GameDB.create_armies_from_extraction` → `_coerce_new_salary_rate`（`ming_sim/db.py` ~8625） | `tests/test_army_salary_44.py::test_create_army_illegal_salary_rate_anchors_to_1_5` |
| `test_non_finite_salary_rate_anchored_not_crash` | 同上 | 同上（一条覆盖） |
| `test_parse_highlight_judge_bad_output_is_empty` | `run_highlight_judge` → `parse_highlight_judge_output` | `tests/test_highlight_judge_544.py::test_run_highlight_judge_bad_output_degrades_to_empty` |

其余 69 条：非闸 / 已有真实入口继任 → **不重造**。逐项表见 `evidence/issue-1902/t5-gate-72-member-table.json`（72 条互异 reason）。

---

## 72 成员处置摘要

| action | count |
|---|---|
| `restored_entry` | 3（对应 2 个新入口案：salary 合并 2、highlight 1） |
| `delete_kept` | 69 |

闸类且已有继任（抽查不重造）：initiative pairing（`test_resolve_surfaces_pairing_warning_in_result` / `test_resolve_with_new_armies_no_warning_in_result`）、`is_real_api_key`（web llm runtime config）、promulgation（`test_gate_extracts_actual_cli_judge_payload_and_rejects_ambiguous_capture`）、office 副职档（`test_office_rank_562::test_leverage_multiplier_uses_canonical_office_rank_table_only`）。

非闸空继任（oracle/字面/算法，12 条）如实标 `（非闸/无必要继任）`，不虚构。

---

## 变异真跑

| 变异 | 结果 | 证据 |
|---|---|---|
| `_coerce_new_salary_rate` 改回漏负的 `v or default` | **红**：`sr_neg … 得 -1.0` | `t5-gate-mut-salary-red.txt` |
| `git checkout -- ming_sim/db.py` 后同案 | **绿** | focus |
| `parse_highlight_judge_output` 恒返 `["假亮"]` | **红**：`['假亮'] == []` | `t5-gate-mut-highlight-red.txt` |
| `git checkout -- ming_sim/highlight_judge.py` 后同案 | **绿** | focus |

---

## 聚焦测试

```
36 passed in 1.30s
```

命令与输出：`evidence/issue-1902/t5-gate-focus-pytest.txt`

覆盖：`test_army_salary_44` 全文件、`test_highlight_judge_544` 全文件、pairing 入口 2 案、office_rank leverage、web llm key 入口 2 案。

**未**新增红→绿证明测；本轮两条为判词授权的误删闸类契约恢复（入口形态）。

---

## 可核命令

```bash
# 删除宇宙
python3 - <<'PY'
import json
d=json.load(open('evidence/issue-1902/t5-t1t5-reclassified.json'))
assert len(d['deleted_members'])==72
t=json.load(open('evidence/issue-1902/t5-gate-72-member-table.json'))
assert t['unique_reasons']==72==len(t['members'])
assert t['restored_entry_count']==3
print('72 ok; restored', t['restored_entry_cases'])
PY

# 建军入口仍调 coerce
rg -n '_coerce_new_salary_rate' ming_sim/db.py

# 聚焦（七 BIN）
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. \
  python3 -m pytest tests/test_army_salary_44.py::test_create_army_illegal_salary_rate_anchors_to_1_5 \
    tests/test_highlight_judge_544.py::test_run_highlight_judge_bad_output_degrades_to_empty -q
```

---

## 质量 / 合法性

- 未改 `CLAUDE.md` / `AGENTS.md` / `CONTEXT.md` / ADR。
- 未新增永久扫描器；成员表为 evidence 一次性产物。
- 自查二连 done：同类型（闸类误删≠一切 helper 都恢复；入口案≠helper 直测）+ 引入（建军需 pay_source；坏 JSON 走 `run_highlight_judge` 而非直调 parse）。

## 剩余 / 阻断

- T1：已结（本轮不重开）。
- T5 闸类误删：salary + highlight 坏输出已入口恢复；72 表可核。
- T2/T3/T4/T6：本轮不重开。
- 家族收尾 / 合并 / 关票不在授权内。
