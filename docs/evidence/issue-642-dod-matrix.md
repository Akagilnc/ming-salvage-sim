# #642 六面 DoD 点检矩阵（P-3）

| 面 | 含义 | 证据指针 | 本片义务 |
|---|---|---|---|
| **1 写入** | 写端三口 + seed 写 | S1 `tests/test_relation_store_632.py`；S2 `tests/test_relation_capture_633.py`；S3 `tests/test_relation_judge_634.py`；S7/S8 `tests/test_relation_seed_638.py`；本片锚③ `tests/test_family_tail_642.py::test_anchor3_xuyang_collaboration_via_summon_judge` | 锚③ 实走召对写口 |
| **2 读取** | canonical 读面 + 判官机面 | S9 `tests/test_relation_read_640.py`；锚① `tests/test_relation_seed_638.py`（新开档+`project_relation_ledger`+魏忠贤场）；锚② `test_family_tail_642.py::test_anchor2_*`；锚④ `test_relation_read_640.py::test_load_relation_history_before_*` + `test_relation_brew_636.py::test_build_brew_input_includes_full_prior_history_in_stable_order` / `test_prepare_attaches_prior_events_only_via_history_seam` | 锚①指针既有；②④本片 |
| **3 恢复** | TD-5 全链 | `docs/evidence/issue-642-restore-matrix.md` | P-2 三缝矩阵 |
| **4 真实 extractor 输出** | 结算口模块真实产出形状进落库 | **既有** `tests/test_relation_capture_633.py::test_settlement_interaction_lands_directed_edge_with_origin_round` + `test_relation_edge_events_slot_owned_by_relations_module`（本片不平行重测） | 点检引用 |
| **5 UI/呈现** | P4 零裸露 | S9 TD-7 `tests/test_relation_read_640.py::test_td7_*`；族级 `tests/test_presentation_p4_family_629.py`；S10 `tests/test_style_temperament_641.py` | 点检引用；五字段白名单不扩 |
| **6 文档** | 契约与实现一致 | `docs/SETTLEMENT_FLOW.md` 关系酿制腿专章（符号：`MonthEndRelationBrewLeg` / `settle_with_delta` / `build_brew_input` / `load_relation_history_before`）；`docs/DELTA_SCHEMA.md` `relation_edge_events` 与 `MINISTER_EDGE_KINDS` 九类一致（审计无正文分叉）。**不入 CI 锁 markdown 措辞** | P-4 收口 |

## DELTA_SCHEMA 审计摘要（P-4）

对照 `ming_sim/relations.py` / `resolve_relation_edge_events_from_extraction`：

- 顶层 section `relation_edge_events` 与 modules 表 `relations` 行一致
- 项字段：施动者/受动者(单名或名单)/类目/语境/来源引用 — 与实现一致
- 类目＝大臣侧九类 — 与 `MINISTER_EDGE_KINDS` 一致
- 语境非空、存储原样 — 与 F1 一致
- **本片无需改正文**

## 闸级（活模型）

脚本：`scripts/family_tail_relation_acceptance_642.py`  
与 #570 颁布/中旨闸**域不同**（关系 seed/三拍/coda），不可并入 `family_tail_acceptance_570.py`；形制复用 `add_gate_llm_args` / evidence JSON 契约。  
独立选择：`--anchor seed|yang|coda`。
