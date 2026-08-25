# #642 六面 DoD 点检矩阵（P-3）

| 面 | 含义 | 证据指针 | 本片义务 |
|---|---|---|---|
| **1 写入** | 写端三口 + seed 写 | S1 `tests/test_relation_store_632.py`；S2 `tests/test_relation_capture_633.py`；S3 `tests/test_relation_judge_634.py`；S7/S8 `tests/test_relation_seed_638.py`；本片锚③ `tests/test_family_tail_642.py::test_anchor3_xuyang_collaboration_via_summon_judge` | 锚③ 实走召对写口 |
| **2 读取** | canonical 读面 + 判官机面 | S9 `tests/test_relation_read_640.py`；本片锚① `test_anchor1_seed_net_readable_via_production_import`；锚④ `load_relation_history_before` + `build_brew_input` prior_events（`tests/test_relation_read_640.py::test_load_relation_history_before_*` + `tests/test_relation_brew_636.py::test_build_brew_input_includes_full_prior_history_in_stable_order` / `test_prepare_attaches_prior_events_only_via_history_seam`） | 锚①②④ 读缝 |
| **3 恢复** | TD-5 全链 | `docs/evidence/issue-642-restore-matrix.md` | P-2 三缝矩阵 |
| **4 真实 extractor 输出** | 结算口模块真实产出形状进落库 | `tests/test_family_tail_642.py::test_dod_face4_real_extractor_section_lands_via_apply_score`；既有 `tests/test_relation_capture_633.py` | 真出口 tracer |
| **5 UI/呈现** | P4 零裸露 | S9 TD-7 `tests/test_relation_read_640.py::test_td7_*`；族级 `tests/test_presentation_p4_family_629.py`；S10 `tests/test_style_temperament_641.py` | 点检引用；五字段白名单不扩 |
| **6 文档** | 契约与实现一致 | `docs/SETTLEMENT_FLOW.md` 关系酿制腿专章；`docs/DELTA_SCHEMA.md` `relation_edge_events` 审计；`tests/test_family_tail_642.py::test_settlement_flow_*` / `test_delta_schema_*` | P-4 收口 |

## DELTA_SCHEMA 审计摘要（P-4）

对照 `ming_sim/relations.py` / `resolve_relation_edge_events_from_extraction`：

- 顶层 section `relation_edge_events` 与 modules 表 `relations` 行一致
- 项字段：施动者/受动者(单名或名单)/类目/语境/来源引用 — 与实现一致
- 类目＝大臣侧九类（荐引/恩义/结怨/站台/使绊/联名/连坐/把柄/协作）— 与 `MINISTER_EDGE_KINDS` 一致
- 语境非空、存储原样 — 与 F1 一致
- 方向展开、无对称翻倍 — 与 r2 F2 一致
- **本片无需改正文**（无错型/漏约束/分叉句）

## 闸级（活模型）

脚本：`scripts/family_tail_relation_acceptance_642.py`  
证据路径约定：`docs/evidence/issue-642-anchor-seed-*.json` / `yang-*.json` / `coda-*.json`（或汇总 `issue-642-acceptance-*.json`）  
独立选择：`--anchor seed|yang|coda`（可重复）。
