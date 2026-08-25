# #642 六面 DoD 点检矩阵（P-3）

| 面 | 含义 | 证据指针 | 本片义务 |
|---|---|---|---|
| **1 写入** | 写端三口 + seed 写 | S1 store_632；S2 capture_633；S3 judge_634；S7/S8 seed_638；本片锚③ `tests/test_family_tail_642.py::test_anchor3_xuyang_collaboration_via_summon_judge` | 锚③ 召对写口 |
| **2 读取** | canonical 读面 + 判官机面 | S9 read_640；锚① seed_638；锚② 闸级 `--anchor yang`；锚④ read_640 history 缝 + brew_636 `test_build_brew_input_projects_prior_event_fields` / `test_prepare_attaches_prior_events_only_via_history_seam` | ②不入 CI 重言 |
| **3 恢复** | TD-5 全链 | `docs/evidence/issue-642-restore-matrix.md` | P-2 |
| **4 真实 extractor 输出** | 结算口真出口 | capture_633 `test_settlement_interaction_lands_directed_edge_with_origin_round` + `test_relation_edge_events_slot_owned_by_relations_module` | 点检引用 |
| **5 UI/呈现** | P4 | read_640 TD-7；presentation_p4_family_629；style_temperament_641 | 点检引用 |
| **6 文档** | 契约一致 | SETTLEMENT_FLOW 酿制腿专章；DELTA_SCHEMA 审计无分叉。**不入 CI 锁 markdown** | P-4 |

## 闸级

`scripts/family_tail_relation_acceptance_642.py`：与 #570 颁布闸域不同（关系 seed/yang/coda），不可并入；形制复用 gate_llm_args。`--anchor seed|yang|coda`。
