# #1835-w5 S1/S2/S3 成员表（全仓机械枚举）

脚本：`evidence/issue-1835/w5-s1s3-enum.py`
现行 JSON：`evidence/issue-1835/w5-s1s3-enum-current.json`
基线 356 JSON：`evidence/issue-1835/w5-s1s3-enum-baseline-356.json`

现行 counts = `{'S1': 9, 'S2': 1, 'S3': 23}`

## 本轮及前提交已处置（相对类定义全文，非点名白名单）

| 成员 | 位置 | 处置 | 依据 |
|---|---|---|---|
| S1-dual / dict echo | `ming_sim/covert_progress.py` | 已删（66f7） | 查案无效只返回 RejectedItem |
| S1-dual-cons | `ming_sim/month_chain.py` | 已删（66f7） | 只认 RejectedItem.category==invalid_enum 停续 |
| S1-cons get_rejected | `tests/test_secret_order_payoff_1504.py / test_month_translate_1840.py` | 本轮删简 | 去掉 applied dict 拒收过滤/断言 |
| S1-prod rejected:True fixtures | `tests/test_person_delta_adapter.py expected` | 本轮删简 | 去掉未断言的旧 dict 附属键 |
| S2 admission helpers | `preflight 字段白名单/整数/势力/炮转移早拒` | 已删（66f7） | 复用写核拒收 |
| S3 module_rejections exempt | `preflight sanitize_delta_shape` | 已删（66f7） | 与未知顶层同形拒收 |
| S3 doc campaign reason positive | `docs/DELTA_SCHEMA.md` | 已对齐（66f7） | 改显式 event_id |
| S3 helper-only normalize×2 + retired normalize | `tests/test_person_delta_adapter.py` | 本轮删 / 前轮删 | action 别名迁入既有入口易主案 |
| S3 credit_events 错约 | `ming_sim/credit_events.py` | 本轮对齐 | apply_score_extraction→settle_delta |

## 现行残留 S1

| kind | 位置 | 处置 | 依据 |
|---|---|---|---|
| `S1-cons-standalone-idx_rejected` | `ming_sim/decree_vocabulary.py:312` | **保留** | 词表查找，非拒收通道 |
| `S1-cons-standalone-get_invalid` | `ming_sim/covert_progress.py:1905` | **保留** | 读声明输入 invalid 字段 |
| `S1-prod-standalone-dict_rejected_true` | `ming_sim/due_review.py:438` | **保留** | 召对待办本地结果；非结算 RejectedItem 双形 |
| `S1-prod-standalone-dict_rejected_true` | `ming_sim/due_review.py:453` | **保留** | 同上 |
| `S1-prod-standalone-dict_rejected_true` | `ming_sim/due_review.py:522` | **保留** | 同上 |
| `S1-prod-standalone-dict_rejected_true` | `tests/test_covert_levy_651.py:116` | **保留** | 声明夹具，非结算双形生产 |
| `S1-prod-standalone-dict_rejected_true` | `tests/test_covert_levy_651.py:117` | **保留** | 同上 |
| `S1-cons-standalone-get_rejected` | `tests/test_due_review_621.py:494` | **保留** | 消费 due_review 本地协议 |
| `S1-cons-standalone-get_rejected` | `tests/test_urge_lever_624.py:429` | **保留** | 消费 due_review 本地协议 |

<details><summary>原始枚举行</summary>

```
{"kind": "S1-cons-standalone-idx_rejected", "file": "ming_sim/decree_vocabulary.py", "lineno": 312, "line": "return DOSSIER_DECISION_CN[\"rejected\"]", "scope": "prod"}
{"kind": "S1-cons-standalone-get_invalid", "file": "ming_sim/covert_progress.py", "lineno": 1905, "line": "invalid = str(declaration.get(\"invalid\") or \"\").strip()", "scope": "prod"}
{"kind": "S1-prod-standalone-dict_rejected_true", "file": "ming_sim/due_review.py", "lineno": 438, "line": "return {\"rejected\": True, \"reason\": \"案卷不存在\"}", "scope": "prod"}
{"kind": "S1-prod-standalone-dict_rejected_true", "file": "ming_sim/due_review.py", "lineno": 453, "line": "\"rejected\": True,", "scope": "prod"}
{"kind": "S1-prod-standalone-dict_rejected_true", "file": "ming_sim/due_review.py", "lineno": 522, "line": "\"rejected\": True,", "scope": "prod"}
{"kind": "S1-prod-standalone-dict_rejected_true", "file": "tests/test_covert_levy_651.py", "lineno": 116, "line": "\"dossier_executions\": [{\"rejected\": True, \"item\": {\"dossier_id\": did, \"outcome\": \"failed\"}}],", "scope": "test"}
{"kind": "S1-prod-standalone-dict_rejected_true", "file": "tests/test_covert_levy_651.py", "lineno": 117, "line": "\"population_transfers\": [{\"rejected\": True, \"origin_ref\": f\"dossier:{did}\", \"reason\": \"摊派\"}],", "scope": "test"}
{"kind": "S1-cons-standalone-get_rejected", "file": "tests/test_due_review_621.py", "lineno": 494, "line": "assert (second[0].get(\"execution\") or {}).get(\"rejected\") is not True, second", "scope": "test"}
{"kind": "S1-cons-standalone-get_rejected", "file": "tests/test_urge_lever_624.py", "lineno": 429, "line": "assert one.get(\"rejected\") is True", "scope": "test"}
```

</details>

## 现行残留 S2

| kind | 位置 | 处置 | 依据 |
|---|---|---|---|
| `S2-envelope-owner-fn` | `ming_sim/settlement/preflight.py:_strategic_event_result_preflight_error` | **保留** | 事件整封归属：调用写核并消费 RejectedItem；has_field_whitelist_return=false、has_int_delta_helper=false、has_cannon_prejudge_msg=false |

<details><summary>原始枚举行</summary>

```
{"kind": "S2-envelope-owner-fn", "file": "ming_sim/settlement/preflight.py", "func": "_strategic_event_result_preflight_error", "lineno": 360, "end": 770, "calls_write_kernel": true, "has_field_whitelist_return": false, "has_int_delta_helper": false, "has_cannon_prejudge_msg": false}
```

</details>

## 现行残留 S3

| kind | 位置 | 处置 | 依据 |
|---|---|---|---|
| `S3-retired-empty_extraction` | `ming_sim/simulation.py / declaration_dispatch.py` | **保留** | 退役史注，非现役特免 |
| `S3-retired-apply_score_extraction_prod` | `ming_sim/settlement/run.py / __init__.py` | **保留** | 标明旧入口已退役 |
| `S3-retired-module_rejections_ref` | `ming_sim/settlement/preflight.py:940` | **保留** | 注释：特免已删 |
| `S3-doc-reason_campaign_anchor` | `docs/DELTA_SCHEMA.md:214` | **保留** | 负向对齐：不得靠 reason 战役名 |
| `S3-name-residue-apply_score_extraction_prod` | `tests/* 多处注释/旧测试名` | **保留** | 历史入口名残留；非生产特免/错约教法 |
| `S3-name-residue-empty_extraction` | `tests/test_declaration_dispatch_1835.py` | **保留** | 负向说明：不再预置空壳 |
| `S3-mig-missing-file` | `tests/test_settlement_fixed_point_1835.py` | **观察** | 文件已不存在（前轮已退）；非本局新增 |

<details><summary>原始枚举行</summary>

```
{"kind": "S3-retired-empty_extraction", "file": "ming_sim/simulation.py", "lineno": 148, "line": "# 旧五模块 ``EMPTY_EXTRACTION`` 曾被声明接缝 deepcopy 成整份空提取再逐字段填"}
{"kind": "S3-retired-empty_extraction", "file": "ming_sim/declaration_dispatch.py", "lineno": 342, "line": "旧五模块包装时代这里先 deepcopy 一整份 ``EMPTY_EXTRACTION`` 空壳再逐字段填，"}
{"kind": "S3-name-residue-apply_score_extraction_prod", "file": "tests/test_person_archive_contract_index.py", "lineno": 4, "line": "surface as apply_score_extraction outcomes (reason_code aliases, title-kind"}
{"kind": "S3-name-residue-apply_score_extraction_prod", "file": "tests/test_person_archive_contract_index.py", "lineno": 27, "line": "\"\"\"reason_code aliases + missing≠unknown land through apply_score_extraction.\"\"\""}
{"kind": "S3-name-residue-apply_score_extraction_prod", "file": "tests/test_transit_aging_346.py", "lineno": 51, "line": "\"\"\"apply_score_extraction 处理 行止 时，写入 transit_to 同时记录 transit_start_turn=当前回合。\"\"\""}
{"kind": "S3-name-residue-empty_extraction", "file": "tests/test_declaration_dispatch_1835.py", "lineno": 1180, "line": "**自己带的字段**送到既有核算口，不再预置一整份 ``EMPTY_EXTRACTION`` 空壳"}
{"kind": "S3-name-residue-apply_score_extraction_prod", "file": "tests/test_style_temperament_641.py", "lineno": 4, "line": "1. apply_score_extraction 后 DB / content / person_logs 一致"}
{"kind": "S3-name-residue-apply_score_extraction_prod", "file": "tests/test_faction_leverage_9.py", "lineno": 696, "line": "玩家月链（pre_settle → 世界段转译 → apply_score_extraction → adjust_factions 注 offset"}
{"kind": "S3-name-residue-apply_score_extraction_prod", "file": "tests/test_faction_leverage_9.py", "lineno": 708, "line": "# 经玩家世界段转译 → apply_score_extraction(faction_delta) → _apply_faction_dict"}
{"kind": "S3-name-residue-apply_score_extraction_prod", "file": "tests/test_population_transfers_649.py", "lineno": 9, "line": "主测缝：apply_score_extraction 落账及恢复后的 DB 状态。"}
{"kind": "S3-name-residue-apply_score_extraction_prod", "file": "tests/test_population_transfers_649.py", "lineno": 86, "line": "\"\"\"入池五因（加派/摊派/灾害/兵灾/逃亡）各 ≥1 正例经 apply_score_extraction 落账。"}
{"kind": "S3-name-residue-apply_score_extraction_prod", "file": "tests/test_surcharge_causal_chain_650.py", "lineno": 8, "line": "主测缝：apply_score_extraction / 玩家过月 /"}
{"kind": "S3-name-residue-apply_score_extraction_prod", "file": "tests/test_section_fiscal_rejections.py", "lineno": 1, "line": "\"\"\"PR2-S3(ADR 0008 决定 1,#91)——apply_score_extraction 的 fiscal 三段迁拒收契约。"}
{"kind": "S3-name-residue-apply_score_extraction_prod", "file": "tests/test_refugee_loop_652.py", "lineno": 3, "line": "主测缝：apply_score_extraction /"}
{"kind": "S3-name-residue-apply_score_extraction_prod", "file": "tests/test_mutiny_noop_whitelist_319.py", "lineno": 5, "line": "+ apply_score_extraction 集成对照（证明无需第二门）。"}
{"kind": "S3-name-residue-apply_score_extraction_prod", "file": "tests/test_relation_capture_633.py", "lineno": 4, "line": "- 邸报大臣互动经 extractor delta → apply_score_extraction → relation_edge_events 落库，"}
{"kind": "S3-name-residue-apply_score_extraction_prod", "file": "tests/test_relation_capture_633.py", "lineno": 541, "line": "（apply_score_extraction 批内 post=live，故该构造只能经直调缝验证。）\"\"\""}
{"kind": "S3-name-residue-apply_score_extraction_prod", "file": "tests/test_population_transfers_662.py", "lineno": 8, "line": "主测缝＝apply_score_extraction 的人口守恒落账。"}
{"kind": "S3-retired-apply_score_extraction_prod", "file": "ming_sim/settlement/run.py", "lineno": 529, "line": "这是内层落库子核的**唯一**入口，取代已退役的 ``apply_score_extraction``"}
{"kind": "S3-retired-apply_score_extraction_prod", "file": "ming_sim/settlement/__init__.py", "lineno": 4, "line": ":class:`SettlementOutcome`。旧单体入口 ``apply_score_extraction`` 已整体退役，"}
{"kind": "S3-retired-module_rejections_ref", "file": "ming_sim/settlement/preflight.py", "lineno": 940, "line": "# #1835 S3：退役 `_module_rejections` 不再特免，与普通未知字段同形拒收。"}
{"kind": "S3-doc-reason_campaign_anchor", "file": "docs/DELTA_SCHEMA.md", "lineno": 214, "line": "- 若作为战略/外敌战事同信封主账战果，须在同一 effects 项顶层写显式 `event_id`（与 `new_issues`/`事件结局` 同属）；不得靠 `reason` 战役名散文反推归属。", "negative_guidance": true}
{"kind": "S3-mig-missing-file", "file": "tests/test_settlement_fixed_point_1835.py"}
```

</details>
