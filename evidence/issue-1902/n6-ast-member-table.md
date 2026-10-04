# #1902 N6 AST 全量测试成员表

枚举：Python 标准库 `ast` 枚举全部 `tests/test_*.py` 的 `test_*`（assert / `pytest.raises` / mock `assert_*`）；Web 枚举全部 `it(`/`test(` 及体内 `expect(`。**不做词面白名单结清**；完整候选见 TSV。

- 候选总数：3292（含 1 条已删函数记录；现存 py=2982，web=309）
- 完整表：[`n6-ast-member-table.tsv`](n6-ast-member-table.tsv)
- 枚举 JSONL（临时，可重放）：`/tmp/ming1902-n1n7-selfverify/n6_ast_enum.jsonl`

## 处置×桶计数

| disposition | bucket | count |
|---|---|---|
| 保留 | 出 N6 三类 | 3170 |
| 保留 | 出 N6 弱结构类（已审） | 2 |
| 保留 | 外部结构契约/UI chrome | 2 |
| 保留 | 外部结构契约/公开默认 | 1 |
| 保留 | 外部结构契约/账本键名 | 1 |
| 保留 | 来源/透传/外部结构契约 | 42 |
| 保留 | 自身构造输入原文透传 | 1 |
| 保留 | 行为 identity（非内部常量证明） | 62 |
| 修 | 内部及无依据证明 | 1 |
| 修 | 必要结构及来源契约弱化 | 6 |
| 修 | 非契约诊断措辞约束 | 1 |
| 删 | 内部及无依据证明 | 1 |
| 删 | 非契约诊断措辞约束 | 2 |

## 非「保留」成员（全列）

| file | name | lineno | disposition | bucket | reason |
|---|---|---|---|---|---|
| `tests/test_chat_stream_failpaths_393.py` | `test_chat_stream_run_error_event_sse_system_layer_no_retry` | 629 | **修** | 必要结构及来源契约弱化 | 钉横幅进 provider_message、不进 message |
| `tests/test_decree_dossiers_571.py` | `test_in_transit_allocation_requires_execution_verdict` | 1916 | **修** | 非契约诊断措辞约束 | 删除应拨/实拨词面与非空 note 弱断言；失败只钉 status/outcome/金额 |
| `tests/test_decree_dossiers_571.py` | `test_malformed_dossier_origin_is_rejected_fail_closed` | 1705 | **修** | 必要结构及来源契约弱化 | 钉 economy_moves_rejections[0]["category"]，禁 json.dumps 全串搜索（判词样本） |
| `tests/test_decree_dossiers_571.py` | `test_underfunded_immediate_allocation_is_not_recorded_as_fulfilled` | 1531 | **删** | 非契约诊断措辞约束 | 删除「不足额」词面锁；保留结构化终态 |
| `tests/test_decree_dossiers_571.py` | `test_underfunded_in_transit_allocation_closes_from_execution_state` | 1505 | **删** | 非契约诊断措辞约束 | 删除 execution_note「不足额」词面锁；保留 status/outcome/金额（判词样本） |
| `tests/test_due_review_621.py` | `test_due_review_scene_tops_live_open_night_even_with_body` | 232 | **修** | 必要结构及来源契约弱化 | 待裁场面结构化事实原样供给，禁 or 二选一 |
| `tests/test_due_review_621.py` | `test_due_review_scene_tops_next_audience_with_origin_context` | 212 | **修** | 必要结构及来源契约弱化 | origin_context 与 criterion_text 均须在 opening（ADR0155） |
| `tests/test_error_pack.py` | `test_web_issue_endpoint_returns_structured_abort` | 110 | **修** | 必要结构及来源契约弱化 | 恢复 stage/error_pack_path/turn；!=500 与结构并存 |
| `tests/test_llm_channel_config.py` | `test_cli_default_constants_identity (deleted)` | 0 | **删** | 内部及无依据证明 | 常量对象 identity / 内部默认值证明整函已删（破坏共享投影仍绿＝假绿；判词样本） |
| `web/src/components/modals.test.tsx` | `空对话区呈等候/引导 chrome，带稳定 chat-stage 标记` | 431 | **修** | 内部及无依据证明 | 清退「不代笔叙事」负向锁与题名；保留 P7 UI chrome 正向匹配 |
| `web/src/useSettlementFlow.test.tsx` | `throttles inflight reloads and converges to the visible phase returned after waiting` | 167 | **修** | 必要结构及来源契约弱化 | 恢复 console.warn 带原 pollError 对象留痕 |

## 裁定口径

- **保留**：来源/透传/公共拒收/闸负向/外部结构；自身构造输入原文透传；行为 identity；P7 UI chrome。
- **修**：必要结构或来源契约曾弱化→收紧到真实字段/对象。
- **删**：非契约诊断措辞；内部常量 identity；不代笔/字数下界等呈现非法证明。
- 结清依据=本表语义裁定+代码/契约，**不以「扫了 N 个文件」代替类覆盖**。
