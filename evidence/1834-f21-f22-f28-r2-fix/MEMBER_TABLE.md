#1834 F21-R2 / F22-R2 / F28-R2 成员表

## F21
| 成员 | 处置 |
|---|---|
| `db.trigger_commitment_backlashes` title_c strip→insert_issue | FIX 保原文 |
| issues identity title strip→PERSON_IDENTITY_TITLES | KEEP 闭集 |
| settlement_payload title strip 匹配键 | KEEP 局部匹配 |
| purpose 补饷 closed vocab | KEEP |
| `_narrative_context` | KEEP 上轮已修 |

## F22
| 成员 | 处置 |
|---|---|
| `credit_event_to_edge` / `credit_events_as_edges` | DELETE |
| `test_credit_contract_fixture_reads_as_semantic_directed_edges` | DELETE |
| `format_metric_delta` + report/db 悬空 import | DELETE |
| `invoke_stream` | KEEP 动态绑定 |
| 现役 credit write / relation query / restore 测试 | KEEP |

## F28
| 成员 | 处置 |
|---|---|
| economy purpose 词表捷径 | DELETE |
| fiscal_changes reason 词表捷径 | DELETE |
| 非零 delta / 增值结构化 | KEEP |
| fiscal_creates 落格 | KEEP |
| issue_advances / cancels | KEEP |
