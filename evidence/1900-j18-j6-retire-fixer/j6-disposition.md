# J6 全仓测试成员处置（冻结分析 + 逐成员语义覆核）

全集：**2886**（Python `test_*` 2602 + web `it`/`test` 284）。
开放 J6（须再删修）：**0**。

完整逐成员表（每成员 `action` / `reason` / `sha256`，覆核带 `semantic_note`）：
`j6-all-members-disposition.json`。

类定义（未收窄）：非契约内部证明、mock 替代被测行为、helper 专测、退役行为、非契约文字锁、内部 oracle、调用 mock；必要闸负向保留真实入口+实际结果；原文无损契约 ≠ 拼装材料措辞锁。

## Action / Reason 直方图

- `retain`: 2886

- `R_no_j6_signal`: 933
- `R_live_entry_result`: 552
- `R_gate_shape`: 464
- `R_gate_negative_live`: 349
- `R_external_boundary`: 280
- `R_web_ui_or_unit_no_j6`: 253
- `R_web_ui_callback_contract`: 31
- `R_ui_lifecycle_gate`: 14
- `R_persisted_projection_after_live_entry`: 10

逐成员 reason 归属以 JSON 为准（可按 `reason` 字段过滤核对）；此处不平行复制 2886 行名单。

## 本轮代码已处置样本（非白名单）

| File | Member | 处置 |
|---|---|---|
| `tests/test_faction_leverage_9.py` | `test_settle_path_triggers_reconcile_before_next_period` | spy/calls → 真结算入口+leverage |
| `tests/test_office_rank_562.py` | `test_rank_rule_offset_reanchor_preserves_existing_save_leverage_once` | 去私有权重 helper |
| `tests/test_character_knowledge_489.py` | structured person scope 案 | 去 `_office_archive_key` 断言 |
| `tests/test_cli_play_turn.py` | `test_review_issue_reaches_staged_directive_default_approval` | 去 calls 协作锁 |

## 核验命令

```sh
python3 -c "import json; d=json.load(open('evidence/1900-j18-j6-retire-fixer/j6-all-members-disposition.json')); print(d['summary']); print('open', sum(1 for m in d['members'] if m['action']!='retain'))"
```
