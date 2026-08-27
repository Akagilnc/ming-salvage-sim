# issue #1572 施工证据：测试逐函数处置表

- 票：issue #1572 / ADR 0150（实体适配器目录 + `settle_delta` 落库编排器，替代 `apply_score_extraction`）
- 判词要求（大理寺外部评审）：精确文件清单 + 逐 test-function 处置表（保留原入口 / 迁 adapter / 并入参数化公共主干 / 删除），每行写所证行为及最终外部断言；公共主干只吸收真实 driver/adapter 入口下完全同构的「坏项拒收＋同批好项落库＋rejection_reports」；rollback/jsonl、source A/B、恢复、动态财政、clamp、战略整封、issue 路严格度、event_pool、玩家可见 extraction、消费者/formatter 等独立契约不得因同文件被吞；`test_applier_contract.py` 明列死类型绿卡删除项与 collector 生命周期迁移项。
- HEAD：`3ef603c68bb7b7276b4948a55ff0ecbfee63da71`（工作树仅有 CONTEXT.md、ADR 0008/0010 三处未提交改动，本表所引 13 个测试文件均为 HEAD 原样；行号以当前实读为准）
- 复核方法：`glob tests/test_*section_rejections.py` + 逐文件 `grep -nE '^\s*(async )?def test_'` + 逐函数实读函数体归纳。

## 0. 文件清单复核（与判词实测一致）

| 来源 | 文件 | test 函数数 |
|---|---|---|
| glob `test_*section_rejections.py`（7） | tests/test_secret_order_section_rejections.py | 7 |
| 〃 | tests/test_power_section_rejections.py | 12 |
| 〃 | tests/test_faction_class_section_rejections.py | 11 |
| 〃 | tests/test_economy_section_rejections.py | 11 |
| 〃 | tests/test_new_issues_section_rejections.py | 25 |
| 〃 | tests/test_close_issues_section_rejections.py | 12 |
| 〃 | tests/test_advances_section_rejections.py | 10 |
| 判词补列（2） | tests/test_section4_rejections.py | 31 |
| 〃 | tests/test_section_fiscal_rejections.py | 35 |
| 判词补列（2） | tests/test_adr0015_per_item_rejection.py | 8 |
| 〃 | tests/test_rejection_wiring.py | 24 |
| 判词另列 | tests/test_applier_contract.py | 23 |

合计 11 个拒收测试文件 186 函数 + `test_applier_contract.py` 23 函数 = **209 函数**。

## 1. 处置口径（四类的判定规则）

- **并入参数化主干**：经真实 driver 入口（`driver.run_prepare`→`run_settle`，即 `tests/section_rejection_helpers.prepare_then_settle`）或段 adapter 入口（`apply_issue_tracker_output` 直调，迁后=局势实体段适配器 `apply(items, ctx)`），布置仅为「信封内坏项 ± 同批好项」，断言仅为 `rejection_reports` 行（section/category + **reason 只断非空、不锁措辞**——生产生成 reason 是自由文本，ADR 0008 决定 5 只要求「有原因」，措辞锁违盯文法）± 好项落库/坏项不落——无其它独立语义。分两臂：**主干·driver**（入口不变，仅参数化塌缩）与**主干·adapter**（入口随段适配器迁移后参数化塌缩）。
- **保留原入口**：driver / db 方法 / 纯函数单测入口在 0150 后不变（`settle_with_delta` 外层核保留、GameDB 实体方法不动、formatter/cleaner/消费者不动），且测试承载独立契约（clamp、no-op、动态财政、成对损耗、controlled_by、P4 玩家可见、rollback/jsonl、provenance A/B、恢复、fail-loud、别名/no-op 语义等），不得被主干吞。
- **迁 adapter 入口**：直调 `issues.apply_score_extraction` / `apply_issue_tracker_output` / `apply_issue_inertia_and_ongoing` / `_apply_issue_entities` / `create_armies_from_extraction` 且承载独立契约（事件池、clamp、保真、容忍、issue 路严格度、metric 不泄漏、fail-loud 等），整体迁到对应实体段适配器 / `settle_delta` 入口，断言不变。
- **删除**：给死类型或将被删桥接发绿卡的测试，行为由主干/落库编排器测试接管。
- **波次归属**（四审后补，五审补 23 改径账）：**迁 adapter 入口（45）与删除（6）随 PR-1 fixed point 同 PR**——它们直调 `apply_score_extraction` 等旧入口，旧入口退役即红，与 fixed point 不可分；**主干·adapter 臂 23 个函数（§2.5 新立 12 + §2.6 结案 6 + §2.7 推进 5）随 PR-1 做 import 机械改径**（`apply_issue_tracker_output` 沉 entities/issue 后调用方改径，零行为差，与 PR-0 系列同款）；**并入参数化主干的塌缩本身（72 = 49 driver 臂 + 23 adapter 臂）为 PR-2**——入口在 PR-1 已就位，塌缩前后均绿，是不阻塞合并的质量整合。
- **文案断言口径**（六审后补，完整五项）：源码对「窒碍未行」的机械断言共 5 处（`test_adr0015_per_item_rejection.py:72,154`、`test_rejection_wiring.py:672,716,801`），对应本表 5 行（adr0015 §2.10 的 :53/:119 函数、wiring §2.11 的 :647/:675/:741 函数）已全部改为结构化断言（source gate / 送入 LLM 的事实字段 / system 来源不触发玩家文案生成通道），各行的 rollback/jsonl、恢复 source 等主契约保留——合 CLAUDE.md P6/P7 与 ADR 0150 决定 5 文案纪律（决策键 0150-D5-b，owner 原话在 ADR 在卷）；生产模板 `ming_sim/decree.py:2517` 本身随 ADR 0150 决定 5 施工时改 LLM 生成通道，本表不代施工。

## 2. 逐文件逐函数处置表

### 2.1 tests/test_secret_order_section_rejections.py（7）

| 行 | 函数 | 所证行为 | 最终外部断言 | 处置 |
|---|---|---|---|---|
| 22 | test_close_retired_source_rejected | #1504：closes 段一律 retired_source 拒收、不结案（退役真源语义） | rejection_reports 全 retired_source + `secret_orders.status` 仍 pending_review | 保留原入口（retired_source 独立契约） |
| 48 | test_update_nonint_order_id_invalid_enum | updates order_id 非整数逐项拒收 | rejection_reports 1 行 invalid_enum | 主干·driver |
| 64 | test_update_unknown_order_id_missing_ref | 引用不存在 order_id → missing_ref，不留「已应用」假象 | rejection_reports 1 行 missing_ref | 主干·driver |
| 81 | test_update_valid_active_order_applies_no_reject | 合法 active 密令 update 不被新 gate 误拒（正向守门） | 零拒收行 + `secret_orders.sim_note` 真写入 | 主干·driver（好项臂） |
| 103 | test_apply_score_extraction_secret_order_update_respects_outer_transaction_rollback | 段写不得绕过外层事务硬提交 | 外层 BEGIN/rollback 后 sim_note 无残留 | 迁 adapter 入口（→ `settle_delta`，事务边界归编排器） |
| 127 | test_apply_score_extraction_secret_order_close_retired_no_write | closes 退役后 apply 不写库、无事务副作用 | 事务内/回滚后 status、result、turn_closed 均不变 | 迁 adapter 入口 |
| 155 | test_oversized_order_id_rejected_not_crash | 超 SQLite 64-bit order_id 两段逐项拒收、不崩整月 | updates 1 行 invalid_enum + closes 1 行 retired_source | 主干·driver |

### 2.2 tests/test_power_section_rejections.py（12）

| 行 | 函数 | 所证行为 | 最终外部断言 | 处置 |
|---|---|---|---|---|
| 35 | test_unknown_power_id_rejected_good_item_lands | 未知势力逐项拒收 hallucinated_id、同信封好势力照落 | rejection_reports 1 行 + `powers.leverage` 变 | 主干·driver |
| 62 | test_illegal_power_field_rejected | 白名单外字段 invalid_enum、合法字段照落 | rejection_reports 1 行 invalid_enum | 主干·driver |
| 79 | test_power_deltas_code_exception_aborts_settlement | apply_power_deltas 代码异常 → SettlementAbort 回滚整批不吞 | `pytest.raises(SettlementAbort)` | 保留原入口（fail-loud 契约） |
| 99 | test_unknown_person_power_change_rejected_good_lands | 9b 易主查无此人 missing_ref、合法易主照落（saved_game 基线） | rejection_reports 1 行 missing_ref + `characters.power_id` 变 | 主干·driver |
| 127 | test_canonical_person_power_writer_code_exception_is_fail_loud | canonical 人物 writer 代码异常上抛、legacy aliases 无第二写路 | KeyError 原样上抛 | 迁 adapter 入口（直调 apply_score_extraction → 人物段适配器） |
| 149 | test_power_change_formatter_skips_rejected_items | formatter 遇拒收项不 KeyError、全拒收回落「未见变化」 | `format_power_changes` 输出串 | 保留原入口（消费者/formatter 独立契约） |
| 165 | test_dirty_power_value_rejected_sibling_field_lands | null 脏值逐项拒收、兄弟好字段照落 | rejection_reports 1 行 invalid_enum + `military_strength` 变 | 主干·driver |
| 191 | test_dirty_power_value_string_rejected | 字符串脏值（"三成"）同路拒收、不 SettlementAbort | rejection_reports 1 行 invalid_enum | 主干·driver |
| 206 | test_ming_power_update_rejected_with_trace | 写 ming（prompt 明文禁止）逐项拒收留痕 | rejection_reports 1 行 category==invalid_enum、reason 非空（源码对 ming/大明 字样的措辞锁删除；目标势力经 item_json 原值断） | 主干·driver |
| 222 | test_float_and_bool_power_values_rejected | float/bool 叶两条拒收、不静默截断落库 | rejection_reports 2 行 invalid_enum + `leverage` 不变 | 主干·driver |
| 243 | test_reason_carrier_aliases_not_recorded_as_rejection | last_action/近动 为 reason 载体键，不记假阳拒收 | 零拒收行 | 保留原入口（段别名语义） |
| 258 | test_all_reason_aliases_consumed_as_reason | 别名键被消费成应用变更的 reason、不回落默认 | `power_logs.reason` == 联姻蒙古（**sentinel round-trip 保留**：「联姻蒙古」为测试自传入的别名值，证消费不回落，非生产生成措辞锁） | 保留原入口（段别名语义） |

### 2.3 tests/test_faction_class_section_rejections.py（11）

| 行 | 函数 | 所证行为 | 最终外部断言 | 处置 |
|---|---|---|---|---|
| 39 | test_unknown_faction_rejected_good_item_lands | 未知派系 missing_ref、好派系照落 | rejection_reports 1 行 + `factions.satisfaction` 变 | 主干·driver |
| 68 | test_unknown_class_rejected_good_item_lands | 未知阶级 missing_ref、好阶级按 clamp 精确落 | rejection_reports 1 行 + `classes.satisfaction` 精确值 | 主干·driver |
| 90 | test_illegal_faction_value_rejected | 合法派系脏值 invalid_enum | rejection_reports 1 行 invalid_enum | 主干·driver |
| 106 | test_illegal_class_value_rejected | 合法阶级脏值 invalid_enum、行不变 | rejection_reports 1 行 + `classes` 行不变 | 主干·driver |
| 124 | test_float_and_bool_class_values_rejected | class float/bool 两条拒收不落库 | rejection_reports 2 行 + 行不变 | 主干·driver |
| 142 | test_float_and_bool_faction_values_rejected | faction float/bool 两条拒收不截断 | rejection_reports 2 行 + 行不变 | 主干·driver |
| 164 | test_web_panel_faction_delta_stays_applied_dict | 玩家可见 extraction 的 faction_delta 仍是已落 dict、拒收段不进可见（P4） | `get_turn_extraction().extractor_output` 形状与键集 | 保留原入口（玩家可见 extraction 独立契约） |
| 188 | test_valid_flat_int_faction_not_rejected | faction 扁平 int 合法形状不误拒、照常落库 | 零拒收行 + `satisfaction` clamp 落 | 保留原入口（段输入形状契约） |
| 206 | test_flat_class_delta_rejected_while_nested_sibling_lands | class 扁平项拒 + 同信封嵌套好项落（形状不对称） | rejection_reports 1 行 invalid_enum + 好项落 | 保留原入口（形状不对称契约） |
| 229 | test_zero_delta_faction_not_rejected | 0 增量为合法 no-op、不误拒 | 零拒收行 | 保留原入口（no-op 语义） |
| 242 | test_issue_effect_faction_rejection_reaches_reports | 局势结案 effect 派系拒收经 entity_rejections 达 reports 不蒸发 | `issue_summary.entity_rejections` 1 行 missing_ref | 保留原入口（issue 路契约） |

### 2.4 tests/test_economy_section_rejections.py（11）

| 行 | 函数 | 所证行为 | 最终外部断言 | 处置 |
|---|---|---|---|---|
| 33 | test_top_level_bad_account_rejected_good_lands | 非法 account invalid_enum、合法项照落（applier 拒收） | rejection_reports 1 行 invalid_enum | 主干·driver |
| 51 | test_top_level_nonint_delta_rejected | 非整数 delta invalid_enum | rejection_reports 1 行 | 主干·driver |
| 64 | test_valid_economy_still_applies_no_reject | 合法 economy 照常落账零拒收（saved_game 基线） | 零拒收行 + 国库 ledger 实扣 | 主干·driver（好项臂） |
| 79 | test_zero_delta_economy_no_reject_no_apply | delta==0 为 no-op、不拒收不落账 | 零拒收行 | 保留原入口（no-op 语义） |
| 91 | test_issue_effect_bad_account_economy_reaches_reports | 结案 effect economy 拒收经 entity_rejections 达 reports | `issue_summary.entity_rejections` 1 行 invalid_enum | 保留原入口（issue 路契约） |
| 116 | test_float_and_bool_delta_rejected | float/bool delta 两条拒收不静默落账 | rejection_reports 2 行 invalid_enum | 主干·driver |
| 133 | test_noop_bad_account_skipped_not_rejected | no-op 占位行（delta==0/缺额）即便 account 非法也静默跳 | 零拒收行 | 保留原入口（no-op 语义） |
| 149 | test_issue_effect_cancel_economy_reaches_reports | 撤局势 applied_cost economy 拒收同 sink 达 reports | `issue_summary.entity_rejections` 1 行 invalid_enum | 保留原入口（issue cancel 路契约） |
| 174 | test_economy_rejections_not_in_player_visible | 拒收项与拒收段不进玩家可见 extractor_output（P4） | `extractor_output` 无 rejected 项、无 rejections 段 | 保留原入口（玩家可见 extraction 独立契约） |
| 193 | test_clean_economy_moves_passes_bad_through | cleaner 不静默丢/coerce 坏项、透传给 applier 拒收 | `_clean_economy_moves` 返回列表内容 | 保留原入口（cleaner 透传独立契约） |
| 216 | test_clean_economy_moves_non_list_returns_empty | cleaner 非列表输入归空 | `_clean_economy_moves` 返回 [] | 保留原入口（cleaner 契约） |

### 2.5 tests/test_new_issues_section_rejections.py（25）

入口均为 `apply_issue_tracker_output` 直调（read_game/game），迁后=局势实体段适配器；主干臂断言为返回 SectionResult 的 rejected 列表（category + reason 非空，措辞不锁；坏项标识经 item_json 原值断言）。

| 行 | 函数 | 所证行为 | 最终外部断言 | 处置 |
|---|---|---|---|---|
| 113 | test_temp_events_replaces_same_id_and_restores_original | 测试基建 `_TempEvents` 同 id 替换/复原自证 | content.events / event_by_id 复原 | 保留原入口（基建自测，不落主干） |
| 137 | test_new_issue_non_dict_item_rejected_not_crash（×3 参数） | 非 dict 新立项逐项拒收不崩 | rejected 1 项 category==invalid_enum、reason 非空（「非对象」措辞锁删除） | 主干·adapter |
| 153 | test_new_issue_dirty_coercion_field_rejected（×3） | bar_value/severity/tags 强转脏值拒整项 | rejected 1 项 category==invalid_enum、reason 非空 + item_json 含原脏字段（「强转失败」措辞锁删除，字段标识经 item 断） | 主干·adapter |
| 164 | test_new_issue_bad_kind_rejected（×3） | 白名单外 kind 预检拒收、不逃逸 abort | rejected 1 项 category==invalid_enum + item_json 含原 kind 值（「含 kind」措辞锁删除） | 主干·adapter |
| 176 | test_new_issue_dirty_inertia_rejected | 脏 inertia 在预校验内拒整项 | rejected 1 项 category==invalid_enum、reason 非空（源码 :185「强转失败」措辞锁删除） | 主干·adapter |
| 188 | test_new_issue_oversized_severity_clamped_not_abort | severity 超界 clamp 到 100 照常落库（clamp 非拒收） | `issues.severity`==100、立项成功 | 迁 adapter 入口（clamp 独立契约） |
| 204 | test_new_issue_whitespace_resolve_condition_falls_back_to_stop_condition | 空白 resolve_condition 回落 stop_condition 并可正常推进结案 | issues 行双条件一致 + advance 到 resolved | 迁 adapter 入口（fallback 语义） |
| 233 | test_new_issue_infinity_field_rejected_not_abort | bar_value=inf（OverflowError 类）拒整项不逃逸 | rejected 1 项 category==invalid_enum、reason 非空（源码 :242「强转失败」措辞锁删除） | 主干·adapter |
| 245 | test_new_issue_infinity_expected_months_rejected_not_abort | expected_months=inf 经严格化拒整项 | rejected 1 项 invalid_enum | 主干·adapter |
| 256 | test_new_issue_severity_zero_preserved | 合法 severity=0 不被 `or 50` 吞（数据保真） | `issues.severity`==0 | 迁 adapter 入口（保真契约） |
| 269 | test_new_issue_garbage_severity_rejected | severity=[] 脏值拒整项、不静默默认 50 | rejected 1 项 invalid_enum | 主干·adapter |
| 287 | test_new_issue_bool_float_int_field_rejected（×5） | 整数字段 _strict_int 拒 bool/float | rejected 1 项 invalid_enum | 主干·adapter |
| 299 | test_new_issue_falsy_nonstring_kind_rejected（×3） | falsy 非串 kind 不静默默认、走白名单拒收 | rejected 1 项 category==invalid_enum + item_json 含原 kind 值（「含 kind」措辞锁删除） | 主干·adapter |
| 311 | test_new_issue_insert_code_exception_propagates | insert_issue 代码/DB 异常上抛不 WARN 吞 | RuntimeError 原样上抛 | 迁 adapter 入口（fail-loud） |
| 324 | test_new_issue_valid_decree_still_creates | 合法新立局势照常立项（好路 pin） | `issues` 行 title/status==active | 主干·adapter（好项臂） |
| 350 | test_event_to_issue_insert_exception_propagates | event_pool 第二 insert 路真异常上抛、不吞成 None | RuntimeError 原样上抛 | 迁 adapter 入口（event_pool fail-loud） |
| 364 | test_new_issue_event_pool_insert_exception_propagates | 同上，经 apply 的 event_pool 分支 call-site 驱动 | RuntimeError 一路上抛 | 迁 adapter 入口（event_pool fail-loud） |
| 385 | test_event_to_issue_duplicate_returns_none_not_raise | 同源事件重复触发幂等返回 None、不抛不重立 | 首次立项、二次 None、`find_any_issue_by_origin` 唯一 | 迁 adapter 入口（event_pool 幂等） |
| 397 | test_new_issue_event_pool_rejects_expired_event | 已过期事件逐项拒收、不立项 | rejected 1 项（category + reason 非空）+ 无 origin 行（「过期/终态」措辞锁删除） | 迁 adapter 入口（event_pool 契约） |
| 413 | test_authoritative_event_pool_rejects_same_batch_obsolete_event | authoritative 快照下同批上游触发致下游作废拒收 | 仅上游立项、下游 rejected 1 项（category + reason 非空；「终态/作废」措辞锁删除） | 迁 adapter 入口（event_pool 契约） |
| 456 | test_new_issue_scalar_string_tags_rejected（×2） | 标量串 tags 拒收（防拆字 bypass 配对守门） | rejected 1 项 category==invalid_enum + item_json 含原 tags 值（「含 tags」措辞锁删除） | 主干·adapter |
| 466 | test_new_issue_non_string_tag_element_rejected | tags 非串元素拒收 | rejected 1 项 category==invalid_enum + item_json 含原 tags 值（「含 tags」措辞锁删除） | 主干·adapter |
| 476 | test_new_issue_valid_list_tags_preserved | 正常 list[str] tags 整词保全不拆字 | `issues.tags` JSON 原词 | 迁 adapter 入口（保真契约） |
| 495 | test_new_issue_non_dict_cancel_cost_tolerated（×5） | 非 dict cancel_cost 容忍归 {}、不 garble 不拒整项（P1 次要字段） | 立项成功 + `cancel_cost`=={} | 迁 adapter 入口（容忍语义） |
| 506 | test_new_issue_valid_cancel_cost_preserved | 正常 dict cancel_cost 原样保全 | `cancel_cost` JSON 原值 | 迁 adapter 入口（保真契约） |

### 2.6 tests/test_close_issues_section_rejections.py（12）

| 行 | 函数 | 所证行为 | 最终外部断言 | 处置 |
|---|---|---|---|---|
| 30 | test_close_bad_issue_id_rejected（×5） | 坏 issue_id（非整数/bool/float/超界）逐项拒收 | rejected 1 项 category==invalid_enum + item_json 含原 issue_id 值（「含 issue_id」措辞锁删除，item 保真断） | 主干·adapter |
| 43 | test_close_non_dict_item_rejected_not_crash（×4） | 非 dict close 项逐项拒收不崩 | rejected 1 项 category==invalid_enum、reason 非空（「非对象」措辞锁删除） | 主干·adapter |
| 54 | test_close_bad_reason_rejected | 非法 reason 先验拒收 | rejected 1 项 category==invalid_enum + item_json 含原 reason 字段（「含 reason」措辞锁删除） | 主干·adapter |
| 66 | test_close_unknown_issue_rejected_missing_ref | 不存在 issue → missing_ref、不静默 continue | rejected 1 项 missing_ref | 主干·adapter |
| 77 | test_close_overflow_issue_id_rejected | 10**100 解析期拒收、OverflowError 不崩月 | rejected 1 项 invalid_enum | 主干·adapter |
| 89 | test_close_already_inactive_rejected_missing_ref | 已结案再结 → missing_ref 陈旧引用（需两次顺序 apply） | rejected 1 项 category==missing_ref、reason 非空 + `issues.status` 保持非 active（「含 active」措辞锁删除，状态面经 DB 断） | 迁 adapter 入口（状态序列，非同构单次坏项） |
| 103 | test_close_failed_on_uncollapsible_rejected_invalid_enum | 不可崩坏局势 failed → invalid_enum 三分（非 missing_ref）且保持 active | rejected 1 项 category==invalid_enum + `issues.status`==active（源码对「不可崩坏」reason 字样的措辞锁删除，行为面经 category + DB 状态断） | 迁 adapter 入口（语义误判分类契约） |
| 118 | test_close_rejection_reaches_rejection_reports | 旧桥 `_collect_inline_rejections` 下探 closes 落 reports 的绿卡 | rejection_reports 行（桥接产出） | **删除**——桥随 0150 决定 2 fixed point 删除；行为由主干·driver + 编排器集中落库测试接管 |
| 141 | test_effect_brief_ignores_rejected_closes | 效果摘要消费者跳过拒收项、不污染章节摘要 | `effect_brief` 输出串 | 保留原入口（消费者独立契约） |
| 157 | test_scalar_item_rejection_preserves_original_in_reports | 旧桥按 'item' 键解包、标量原件保真的绿卡 | rejection_reports.item_json（桥接产出） | **删除**——桥随删；item_json=原始坏项行为由 wiring L275 组 + RejectedItem 单点形状接管 |
| 179 | test_close_issue_code_exception_propagates | close_issue 代码/DB 异常上抛不 WARN 吞 | RuntimeError 原样上抛 | 迁 adapter 入口（fail-loud） |
| 191 | test_close_valid_issue_still_succeeds | 合法结案照常、touched_ids 含项（好路 pin） | closes 成功项 + `touched_ids` | 主干·adapter（好项臂） |

### 2.7 tests/test_advances_section_rejections.py（10）

| 行 | 函数 | 所证行为 | 最终外部断言 | 处置 |
|---|---|---|---|---|
| 32 | test_advance_non_dict_item_rejected_not_crash（×4） | 非 dict advance 项逐项拒收不崩 | rejected 1 项 category==invalid_enum、reason 非空（「非对象」措辞锁删除） | 主干·adapter |
| 43 | test_advance_bad_issue_id_rejected（×5） | 坏 issue_id 逐项拒收留痕不裸丢 | rejected 1 项 category==invalid_enum + item_json 含原 issue_id 值（「含 issue_id」措辞锁删除，item 保真断） | 主干·adapter |
| 61 | test_advance_dirty_int_field_rejected（×6） | delta_bar/inertia_delta 脏值 _strict_int 拒收 | rejected 1 项 invalid_enum | 主干·adapter |
| 72 | test_advance_missing_issue_rejected | 不存在 issue → missing_ref 不裸 continue | rejected 1 项 missing_ref | 主干·adapter |
| 81 | test_advance_non_active_issue_rejected | 已结案 issue 推进 → missing_ref（需先结案序列） | rejected 1 项 missing_ref | 迁 adapter 入口（状态序列） |
| 92 | test_advance_valid_still_advances | 合法推进不被误拒（好路 pin） | advances 成功项含 issue_id | 主干·adapter（好项臂） |
| 103 | test_advance_code_exception_propagates | advance_issue 代码/DB 异常上抛不吞 | RuntimeError 原样上抛 | 迁 adapter 入口（fail-loud） |
| 120 | test_advance_missing_issue_no_metric_leak | 拒收路径不得先落 metric 副作用（内存态不泄漏） | `state.metrics` 前后不变 | 迁 adapter 入口（内存态副作用契约） |
| 131 | test_advance_non_active_issue_no_metric_leak | 同上（已非 active 分支） | `state.metrics` 前后不变 | 迁 adapter 入口（内存态副作用契约） |
| 145 | test_advance_non_dict_metric_delta_tolerated（×3） | 非 dict metric_delta sanitize 为 {}、正常推进不崩 | 推进成功 + `state.metrics` 不变 | 迁 adapter 入口（容忍语义） |

### 2.8 tests/test_section4_rejections.py（31）

| 行 | 函数 | 所证行为 | 最终外部断言 | 处置 |
|---|---|---|---|---|
| 56 | test_unknown_region_rejected_good_item_lands | 未知地区 missing_ref、好地区照落 | rejection_reports 1 行 + `regions.public_support` 变 | 主干·driver |
| 82 | test_illegal_region_field_rejected_sibling_lands | 白名单外字段 invalid_enum、兄弟好字段照落 | rejection_reports 1 行 + 好字段落 | 主干·driver |
| 105 | test_dirty_region_value_rejected_sibling_lands（×4） | null/串/float/bool 脏叶逐项拒收、兄弟照落 | rejection_reports 1 行 + `unrest` 变 | 主干·driver |
| 130 | test_region_controlled_by_rejects_non_power_id_and_preserves_region（×6） | controlled_by 须真实非空 power id，否则拒且不改控制权 | rejection_reports 1 行 category==invalid_enum、reason 非空 + `controlled_by` 不变（源码 :148 的 `controlled_by in reason` 措辞锁删除；身份契约经 category + DB 控制权断） | 保留原入口（controlled_by 身份字段契约） |
| 155 | test_region_controlled_by_accepts_existing_power_ids_and_restore_hook | 合法控制权变更落库且 ming 收复 on_restore 覆盖仍触发 | `controlled_by`==ming + `public_support` 覆盖 + region_logs 双字段 | 保留原入口（restore hook 契约） |
| 185 | test_region_controlled_by_mixed_invalid_and_valid_siblings_apply | 坏 controlled_by 只拒该字段、不阻断同地区好字段与别地区合法变更 | rejection_reports 1 行 + 两地区各行其是 | 保留原入口（controlled_by 组契约） |
| 219 | test_unknown_army_rejected_good_item_lands | 未知军队 missing_ref、好军队照落 | rejection_reports 1 行 + `armies.morale` 变 | 主干·driver |
| 245 | test_illegal_army_field_rejected_sibling_lands | 非法字段 invalid_enum、同军好字段照落 | rejection_reports 1 行 + 好字段落 | 主干·driver |
| 268 | test_dirty_army_value_rejected_sibling_lands（×4） | 脏叶逐项拒收、兄弟好字段照落 | rejection_reports 1 行 + `training` 变 | 主干·driver |
| 299 | test_unknown_owner_power_army_rejected_good_builds | owner_power 未入库 hallucinated_id、好军照建坏军不落 | rejection_reports 1 行 + armies 表有好无坏 | 主干·driver |
| 329 | test_army_missing_manpower_rejected_good_builds | 非法/缺 manpower invalid_enum、好军照建 | rejection_reports 1 行 + armies 表有好无坏 | 主干·driver |
| 355 | test_duplicate_army_without_manpower_rejected | 命中已有 id 且无 manpower 增量 invalid_enum | rejection_reports 1 行 | 主干·driver |
| 375 | test_region_deltas_code_exception_aborts_settlement | apply_region_deltas 代码异常 → SettlementAbort 回滚整批 | `pytest.raises(SettlementAbort)` | 保留原入口（fail-loud 契约） |
| 392 | test_army_deltas_code_exception_aborts_settlement | apply_army_deltas 代码异常同上 | `pytest.raises(SettlementAbort)` | 保留原入口（fail-loud 契约） |
| 408 | test_create_armies_code_exception_aborts_settlement | create_armies_from_extraction 代码异常同上 | `pytest.raises(SettlementAbort)` | 保留原入口（fail-loud 契约） |
| 427 | test_army_cannon_over_cap_clamps_not_rejected | 军 cannon 超 cap 12 clamp 后照落、不算拒收（P2） | 零拒收行 + `cannon_equipment`==12 | 保留原入口（clamp 独立契约） |
| 447 | test_region_cannon_over_cap_clamps_not_rejected | 地区 cannon 超 city_level×8 clamp 后照落 | 零拒收行 + `cannon`==cap | 保留原入口（clamp 独立契约） |
| 469 | test_army_firearm_over_100_clamps_not_rejected | firearm 超 100 clamp 后照落 | 零拒收行 + `firearm_equipment`==100 | 保留原入口（clamp 独立契约） |
| 488 | test_region_army_formatters_skip_rejected_items | region/army formatter 遇拒收项不 KeyError、全拒收回落「未见变化」 | `format_region_changes`/`format_army_changes` 输出串 | 保留原入口（消费者/formatter 独立契约） |
| 518 | test_duplicate_army_noninteger_manpower_rejected | 重复 id + manpower 非整数 invalid_enum | rejection_reports 1 行 | 主干·driver |
| 540 | test_dirty_region_cannon_value_rejected_not_abort（×4） | cannon 分支脏值守门前置、逐项拒收不崩 | rejection_reports 1 行 + `region_logs` 好字段 1 行 | 主干·driver |
| 561 | test_dirty_optional_army_field_rejects_item | 可选数值字段在场即须合法、脏值拒整项 | armies 无此行 + rejection_reports 1 行 | 保留原入口（在场/缺省语义，与 L579 成对） |
| 579 | test_absent_optional_army_fields_use_defaults | 缺省可选字段走默认 50/0（pin） | armies 行 morale==50、cannon==0 | 保留原入口（缺省默认 pin） |
| 594 | test_issue_path_tolerates_previously_skipped_cases | 国策结案路对历史 print-skip 案容忍不升级崩月、好字段照落 | `morale` 按 min(100,+2) 落、不抛 | 迁 adapter 入口（issue 路严格度，直调 `_apply_issue_entities`） |
| 614 | test_issue_path_still_strict_for_historically_fatal | 历史致命类（查无此军）在 issue 路保持严格 raise | `pytest.raises(ValueError)` | 迁 adapter 入口（issue 路严格度） |
| 625 | test_nondict_new_army_item_recorded_not_silent | new_armies 非 dict 项留拒收记录不静默 | 返回列表 1 项 rejected invalid_enum | 迁 adapter 入口（直调 `create_armies_from_extraction`） |
| 636 | test_all_score_fields_guarded_on_creation（×3） | 守门集从 ARMY_SCORE_FIELDS 派生、equipment/mobility/loyalty 脏值拒 | armies 无此行 + rejection_reports 1 行 | 主干·driver |
| 655 | test_issue_path_tolerated_rejections_reach_reports | issue 结案路容忍拒收经 entity_rejections 落 reports 不蒸发 | `issue_summary.entity_rejections` 1 行 | 保留原入口（issue 路留痕，driver 入口） |
| 683 | test_inertia_natural_resolution_tolerated_rejection_no_crash | inertia 自然结案含容忍脏项不崩、好字段照落 | issue resolved + `morale` 落、不抛 | 迁 adapter 入口（直调 `apply_issue_inertia_and_ongoing`） |
| 710 | test_float_bool_army_delta_tolerated_on_issue_path | issue 路 float/bool 容忍、None/串保持严格 | 不抛 + `pytest.raises(ValueError)` 双断言 | 迁 adapter 入口（issue 路严格度） |
| 731 | test_required_field_historical_strictness_on_issue_path | 建军必填谓词只看 manpower：float 容忍、串/缺键严格、合法缺 maintenance 容忍 | 不抛/raises(ValueError) 分组断言 | 迁 adapter 入口（issue 路严格度） |

### 2.9 tests/test_section_fiscal_rejections.py（35）

| 行 | 函数 | 所证行为 | 最终外部断言 | 处置 |
|---|---|---|---|---|
| 41 | test_remove_unknown_fiscal_key_rejected_good_removal_lands | 裁撤未知 key missing_ref、好 key 照裁 | rejection_reports 1 行 + `fiscal_config` 好 key 行删 | 主干·driver |
| 65 | test_remove_dynamic_tax_still_zeroes_region_field | 裁撤 dynamic 税（辽饷）base/rate 行删 + 各省实收归零 | `fiscal_config` 无行 + regions.fiscal.liao_xiang==0 | 保留原入口（动态财政独立契约） |
| 88 | test_remove_structural_sink_loss_rate_rejected | 中央自然损耗率结构地板不可裁撤 | rejection_reports 1 行 invalid_enum + 值不变 | 保留原入口（成对损耗/地板契约） |
| 105 | test_remove_central_human_loss_rate_rejected_as_loss_pair | 人为损耗率属成对配置不可裁撤 | 同上 | 保留原入口（成对损耗契约） |
| 122 | test_remove_central_human_loss_rate_stem_rejected_as_loss_pair | stem 写法不可绕过成对保护 | 同上 | 保留原入口（成对损耗契约） |
| 142 | test_direct_remove_central_human_loss_rate_stem_refuses_loss_pair | `db.remove_fiscal_item` 自身也拒 stem 形态 | 返回 None + 值不变 | 保留原入口（GameDB 方法层不动） |
| 156 | test_create_duplicate_key_rejected_good_create_lands | 重复 key 拒收、好新立照建 | rejection_reports 1 行 + 新 base key 建成 | 主干·driver |
| 181 | test_create_illegal_account_rejected_sibling_lands（×3） | 非法 account invalid_enum、好新立照建 | rejection_reports 1 行 + 好建行有/坏建行无 | 主干·driver |
| 207 | test_create_dirty_init_value_rejected_not_silent_zero（×3） | 脏 init_value 显式拒不静默归 0、好项照落 | rejection_reports 1 行 + 脏项无行/好项值正确 | 主干·driver |
| 234 | test_create_absent_init_value_defaults_zero | init_value 缺省走默认 0（「缺省走默认」pin） | 新行 value==0 | 保留原入口（缺省默认 pin） |
| 251 | test_change_unknown_key_rejected_good_change_lands | 未知 key missing_ref、好 key 调率照落 | rejection_reports 1 行 + `fiscal_config` 值变 | 主干·driver |
| 276 | test_change_dirty_delta_rejected_sibling_lands（×3） | 脏 delta invalid_enum、同信封好项照落 | rejection_reports 1 行 + 值按好项落 | 主干·driver |
| 299 | test_change_zero_delta_no_op_not_rejected | delta=0 无操作不记拒（pin） | 零拒收行 | 保留原入口（no-op 语义） |
| 312 | test_change_empty_key_rejected | 空 key 脏项记拒（与 no-op 不同类） | rejection_reports 1 行 invalid_enum | 主干·driver |
| 328 | test_change_dynamic_tax_rate_scales_region_field | 调 dynamic 税系数 → 各省实收按比例缩放 | rate 新值 + regions.fiscal 缩放后实收 | 保留原入口（动态财政独立契约） |
| 352 | test_change_structural_sink_loss_rate_below_floor_rejected | 自然损耗率可调不可清零、低于地板拒 | rejection_reports 1 行 + 值不变 | 保留原入口（结构地板契约） |
| 369 | test_change_central_loss_rate_pair_above_100_rejected | 人为+自然损耗合计 ≤100%、写入即拒 | rejection_reports 1 行 + 两值均不变 | 保留原入口（成对损耗契约） |
| 393 | test_change_central_loss_rate_rebalance_uses_batch_final_total | 同批重分配只看批次终态、不受行序影响 | 零拒收行 + 两值 85/15 | 保留原入口（批次终态语义） |
| 427 | test_falsy_dirty_delta_still_rejected（×2） | False/0.0 脏值判定先于 no-op 短路 | rejection_reports 1 行 invalid_enum | 主干·driver（保判定顺序） |
| 445 | test_cleaner_passes_dirty_delta_through | `_clean_fiscal_changes` 不 coerce/不丢脏、透传 applier | cleaner 返回映射逐键断言 | 保留原入口（cleaner 透传独立契约） |
| 468 | test_cleaner_passes_dirty_create_fields_through | `_clean_fiscal_creates` 脏字段透传、同义词规范化、缺省归 0 | cleaner 返回映射逐键断言 | 保留原入口（cleaner 透传独立契约） |
| 490 | test_create_rate_only_sibling_collision_rejected_not_abort | 存在性检查覆盖 base+rate 双键、撞 rate 键 PK 不崩 | rejection_reports 1 行 | 主干·driver |
| 507 | test_empty_key_rejected_even_with_noop_delta（×2） | 空 key + 0/null delta 仍记拒、短路不吞留痕 | rejection_reports 1 行 | 主干·driver（保判定顺序） |
| 521 | test_remove_missing_key_rejected | removes 缺 key 记拒 | rejection_reports 1 行 invalid_enum | 主干·driver |
| 535 | test_create_with_rate_suffix_key_rejected | stem 归一剥双后缀、`田赋_rate` 不建冒牌科目 | rejection_reports 1 行 + 零冒牌行 | 主干·driver（带无副作用断言） |
| 554 | test_negative_init_value_rejected_not_clamped | 负 init_value 按脏值拒不 clamp 0 | rejection_reports 1 行 + 未建行 | 主干·driver |
| 572 | test_double_suffix_key_rejected_no_phantom（×2） | 双后缀垃圾 key 拒收、不建幻影科目 | rejection_reports 1 行 + 零幻影行 | 主干·driver（带无副作用断言） |
| 591 | test_double_suffix_remove_rejected_not_destructive | remove 路双后缀垃圾 key 拒收、真科目毫发无损 | rejection_reports 1 行 + 辽饷行数不变 | 主干·driver（带不破坏性断言） |
| 612 | test_sanitizer_passes_empty_key_items_through | 引擎 sanitizer 路空 key 项不透过滤、两路同判 | 三个 cleaner 返回非空 | 保留原入口（cleaner/同输入两判契约） |
| 627 | test_chinese_direction_alias_accepted_on_driver_path | direction 中文别名「收」在 driver 路同判落库（归一在唯一守门人） | 新行建成 + 零拒收 | 保留原入口（同输入两判独立契约） |
| 645 | test_whitespace_only_key_rejected_on_driver_path | 空白 key 守门处统一 strip、按空 key 拒 | rejection_reports 1 行 invalid_enum | 主干·driver |
| 662 | test_lossless_int_string_same_verdict_both_paths | 无损整数串在 applier 归一接受、两路同判 | 零拒收 + change 值 +5 / create 值 300 | 保留原入口（同输入两判独立契约） |
| 682 | test_driver_path_display_defaults_from_key | display 缺省=key 去 _base 后缀、默认归 applier | 新行 display==「显名测试」 | 保留原入口（默认值归一契约） |
| 697 | test_garbage_key_category_consistent_across_sections | 同形垃圾 key 在 create/remove/change 三段同口径 invalid_enum | 三段 category 全 invalid_enum | 保留原入口（跨段一致性契约） |
| 716 | test_fiscal_change_reopens_with_value_origin_history_and_scaled_rows | 独立财政变更重开后 live 值/provenance/历史/缩放四件齐备 | 重开 DB 后 fiscal_config 值+origin_ref、fiscal_config_changes 历史、regions 缩放 | 保留原入口（持久化+provenance 独立契约） |

### 2.10 tests/test_adr0015_per_item_rejection.py（8）

| 行 | 函数 | 所证行为 | 最终外部断言 | 处置 |
|---|---|---|---|---|
| 12 | test_persist_resolve_context_rejects_bad_items_and_saves_sanitized_delta | persist_resolve_context 拒坏项并存消毒后 delta 进 ctx | `get_resolve_context` extracted 净形 + rejection_reports 两行 player_decree | 保留原入口（decree 层入口不动） |
| 53 | test_driver_validate_rejection_mirrors_jsonl_after_outer_atomic | driver 外层事务提交后 validate 层拒收镜像 jsonl | rejection_reports 行 + rejections.jsonl 镜像行一致（rollback/jsonl 主契约保留）；源码 :72 另有「窒碍未行」固定文案正断言——**删除**，改断结构化 source gate 与送入 LLM 的 item/category/reason 事实输入（ADR 0150 决定 5 文案纪律 / CLAUDE.md P6/P7） | 保留原入口（rollback/jsonl 独立契约） |
| 87 | test_validate_and_module_rejections_do_not_leak_into_player_visible_extraction | shape/module 拒收桶不写进玩家可见 extraction（P4） | extractor_output 无两个拒收键 | 保留原入口（玩家可见独立契约） |
| 119 | test_player_visible_rejection_aggregates_durable_rows_across_attempts_and_resimulation | 玩家可见拒收聚合跨 attempt 与重模拟、审计行不删但失效标记 | 聚合行 source gate（player 来源入玩家可见聚合）+ `resimulation_invalidated`==1；措辞由 LLM 据实编织，不断言固定文案（ADR 0150 决定 5 文案纪律 / CLAUDE.md P6/P7） | 保留原入口（恢复/重跑独立契约） |
| 168 | test_utf8_safe_serialization_preserves_chinese_and_escapes_lone_surrogate | RejectedItem 序列化中文保全、孤 surrogate 转义 | rejection_reports.item_json 内容 | 迁移保留（随 collector 生命周期组迁置，见 §3 同类） |
| 184 | test_misrouted_module_field_becomes_rejection_not_only_trace | `_sanitize_module_output` 错路由字段产出拒收非仅 trace | cleaned `_module_rejections` 形状 | 保留原入口（sanitizer 单测） |
| 194 | test_sqlite_text_sanitization_covers_resolve_report_and_extraction_rows | resolve ctx/turn_report/turn_extraction 文本消毒覆盖 | 各表行 `中文`+`\ud800` 并存 | 保留原入口（DB 消毒契约） |
| 231 | test_sqlite_text_sanitization_covers_issue_rows_and_advances | issues/issue_advances 行文本消毒覆盖（含 close narrative） | 各列 `中文`+`\ud800` 并存 | 保留原入口（DB 消毒契约） |

### 2.11 tests/test_rejection_wiring.py（24）

| 行 | 函数 | 所证行为 | 最终外部断言 | 处置 |
|---|---|---|---|---|
| 29 | test_rejected_item_lands_in_reports_and_jsonl | 拒收项落 reports + commit 后镜像 jsonl、attempt=1 | rejection_reports 行 + jsonl 行一致 | 保留原入口（rollback/jsonl 契约） |
| 54 | test_rollback_leaves_no_rows_and_no_jsonl | flush 后崩 → 回滚无行无镜像（镜像只在 commit 成功后） | 表空 + jsonl 不存在 | 保留原入口（rollback/jsonl 契约） |
| 79 | test_attempt_derived_from_error_pack_dirs | attempt 从错误包目录推导、与错误包同号 | rejection_reports.attempt==2 | 保留原入口（attempt 推导契约） |
| 96 | test_engine_extractor_path_stamps_player_decree | 皇帝下旨触发的 extractor 整批标 player_decree（#146 A 面） | rejection_reports.source==player_decree | 保留原入口（source A/B 契约） |
| 125 | test_issue_summary_nested_rejections_are_collected | issue_summary 嵌套段拒收被收集（桥下探 new_issues） | `issue_summary.new_issues` 行 + category + reason 非空（源码 :143 对生产生成 reason 的 `"decree/event_pool" in …` substring 锁删除；嵌套下探行为经 section 名 + 计数断） | 保留原入口（driver 行为契约；实现由旧桥改为框架集中收集，断言不变） |
| 143 | test_nested_atomic_success_path_does_not_orphan_jsonl | 嵌套 atomic 成功路 mirror 等最外层 commit、不孤立 jsonl | 外层回滚后表空 + jsonl 不存在 | 保留原入口（rollback/jsonl 契约） |
| 164 | test_attempt_derivation_failure_does_not_abort_settlement | attempt 推导故障不拖垮结算、回落 1 | 结算完成 + attempt==1 | 保留原入口（副信道容错契约） |
| 187 | test_noncancellable_cancel_rejection_carries_reason | 不可撤国策转强推的拒收带人读 reason | `issue_summary.cancels` 行 reason 非空 | 保留原入口（嵌套段 reason 契约） |
| 210 | test_rejected_appointment_carries_rejection_cause | 后宫任命拒收 reason=拒收原因、非任命理由回显 | `appointments` 行 reason 非空且 ≠「椒房之选」（**sentinel 负向回环保留**：「椒房之选」为测试自传入的任命理由，≠ 断言证非回显，非生产措辞锁）+ category==appointment_rejected | 保留原入口（producer reason 契约） |
| 229 | test_bridge_synthesizes_reason_when_producer_omits | 「拒收行必带原因」不变式的集中兜底（现挂在旧桥） | rejection_reports.reason 非空兜底 | 迁（旧桥随删；不变式上移到 RejectedItem 单点/编排器落库层重写，行为不丢） |
| 249 | test_inertia_tolerated_rejections_reach_reports | inertia 自然结案容忍拒收进 reports、与 tracker-close 路同判 | `issue_inertia.entity_rejections` 1 行 | 保留原入口（inertia 路留痕契约） |
| 275 | test_item_json_is_original_delta_item_when_producer_carries_it | item_json=原始 delta 项、非嵌套 wrapper（决定 5） | item_json 解包==原件、无 rejected 键 | 保留原入口（item 保真契约） |
| 298 | test_person_change_rejection_item_json_keeps_original_delta_item | 人物行止拒收 item_json 存原始条目 | item_json==raw_item | 保留原入口（item 保真契约） |
| 326 | test_power_move_rejection_item_json_keeps_original_person_delta_item | 易主委托 power helper 后拒收仍存 ADR0009 原始条目 | item_json==raw_item | 保留原入口（item 保真契约） |
| 362 | test_office_change_rejection_item_json_keeps_original_person_delta_item | 任命漏官职拒收存原始条目 + category==missing_field | item_json==raw_item | 保留原入口（item 保真契约） |
| 393 | test_non_ming_appointment_rejection_keeps_original_person_delta_item | 非明人物任明官拒收存原始条目 + category==invalid_transition | item_json==raw_item | 保留原入口（item 保真契约） |
| 435 | test_power_move_backlash_rejection_lands_in_reports | 易主可落库时嵌套反噬拒收也落 reports、不藏成功项内部 | `applied_person_changes.backlash_results` 行：section/category==hallucinated_id/item_json 原值 + 计数（源码 :483 对生产 reason `power_updates 引用未入库势力…` 的等值锁删除，reason 只断非空） | 保留原入口（嵌套反噬拒收契约） |
| 495 | test_issue_close_power_move_backlash_rejection_is_not_duplicated | 结案人物变更嵌套拒收只入库一次（close 详情与 issue_summary 聚合去重） | 全表恰 1 行 `issue_summary.applied_person_changes.backlash_results`（去重计数契约；源码 :547 的 reason 等值锁删除，category/item_json 断行为） | 保留原入口（去重契约） |
| 559 | test_inertia_power_move_backlash_rejection_lands_in_reports | 自然结案易主反噬拒收落 reports | `issue_summary.applied_person_changes.backlash_results` 行（源码 :604 的 reason 等值锁删除，section/category + 计数断） | 保留原入口（嵌套反噬拒收契约） |
| 612 | test_resimulation_inherits_player_source_from_ctx | HITL 续跑/崩溃重抽从 ctx['source'] 继承 player_decree、不退化 system | rejection_reports.source==player_decree | 保留原入口（恢复/source 契约） |
| 647 | test_player_decree_rejection_surfaces_prompt_in_turn_report | player 来源拒收 → 触发邸报文案生成通道并落 turn_reports（A 面闭环） | source gate 通过 + 送入 LLM 的事实字段（item/category/reason）齐全 + turn_reports 落行；不断言固定措辞（ADR 0150 决定 5：代码只供事实、不写话） | 保留原入口（source A/B 契约） |
| 675 | test_system_rejection_stays_silent_and_keeps_system_provenance | system 来源拒收记 system_simulation 且邸报静默（B 面对照） | source==system_simulation + system 来源不触发玩家文案生成通道（结构性静默，非文案比对） | 保留原入口（source A/B 契约） |
| 719 | test_provenance_from_stored_recovers_all_forms | `_provenance_from_stored` 三层兼容还原（枚举/纯值/脏串），非法回落 system | 纯函数 9 断言 | 保留原入口（provenance 还原单测） |
| 741 | test_settling_recovery_fallthrough_preserves_system_source | SETTLING 非 ready 崩溃恢复 fallthrough 穿透 ctx['source']、provenance 按构造保真 | source==system_simulation + 恢复穿透（主契约保留）；源码 :801 另有「窒碍未行」固定文案负断言——**改为** system 来源不触发玩家文案生成通道（结构性静默，非文案比对） | 保留原入口（恢复独立契约） |

## 3. tests/test_applier_contract.py 两类明列（23 函数）

### 3.1 死类型构造绿卡——删除（4）

0150 背景：`ApplyContext`/`SectionResult` 在 0008 半落地形态下生产侧零引用（死类型），以下测试仅构造死类型断言字段/拼接，是绿卡。注意 0150 决定 2 会把 `SectionResult`/ctx 复活为 canonical 段契约——但那是新形状的契约，由地基 PR 重新发契约测试；旧骨架断言（applied 任意列表、merge 拼接、ctx 持四字段）不沿用。

| 行 | 函数 | 绿卡内容 | 处置 |
|---|---|---|---|
| 66 | test_section_result_holds_applied_and_rejected | 死类型 SectionResult 持 applied/rejected 两列表 | 删除（地基 PR 按新 canonical SectionResult 重发契约测试） |
| 73 | test_section_result_merge | 死类型 SectionResult.merge 拼接 | 删除（同上） |
| 82 | test_section_result_merge_empty | 空 SectionResult 合并 | 删除（同上） |
| 106 | test_apply_context_holds_all_fields | 死类型 ApplyContext 持 db/state/content/registry/source | 删除（同上） |

### 3.2 RejectionCollector 事务/镜像生命周期——迁移保留（13+1）

0150 结论「collector 事务/镜像生命周期行为迁移复用」：迁入落库编排器/collector 契约测试文件，断言不变。

| 行 | 函数 | 所证行为 | 处置 |
|---|---|---|---|
| 121 | test_rejection_collector_flush_before_record_leaves_db_empty | 空缓冲 flush 不写行 | 迁移保留 |
| 130 | test_rejection_collector_flush_writes_rows | record×2 → flush 落 2 行、四字段正确 | 迁移保留 |
| 163 | test_rejection_collector_flush_clears_buffer | flush 清缓冲、二次 flush 不写新行 | 迁移保留 |
| 175 | test_rejection_collector_flush_stores_item_as_json | 原 item dict 以 JSON 落库可反解 | 迁移保留 |
| 194 | test_mirror_to_jsonl_writes_lines | flush 后 mirror append jsonl 行、字段齐 | 迁移保留 |
| 216 | test_mirror_to_jsonl_appends_on_multiple_calls | 多批 flush→mirror 追加不覆盖 | 迁移保留 |
| 231 | test_mirror_to_jsonl_empty_buffer_writes_nothing | 空缓冲 mirror 不建文件 | 迁移保留 |
| 245 | test_flush_then_mirror_writes_jsonl | 规定调用序 record→flush(事务内)→commit→mirror 有行（cmr F1 回归） | 迁移保留 |
| 270 | test_mirror_idempotent_after_flush | 同批行 mirror 两次只写一次 | 迁移保留 |
| 286 | test_unflushed_rows_never_mirrored | 未 flush 行不进 jsonl（防孤立镜像） | 迁移保留 |
| 299 | test_reset_discards_pending_and_flushed | 回滚路 reset() 丢弃缓冲与已 flush 快照 | 迁移保留 |
| 320 | test_record_accepts_plain_string_source | source 传普通字符串落库归一为枚举值 | 迁移保留 |
| 334 | test_record_rejects_unknown_source_string | 非法 source 字符串 fail-loud ValueError | 迁移保留 |
| 346 | test_collector_counts_deterministic_on_polluted_save | 活存档已带拒收行时清场后计数确定（测试基建 pin） | 迁移保留（随 collector 组） |

### 3.3 既非死类型绿卡、又非 collector 生命周期——保留（5）

RejectedItem 唯一 typed 契约（三审裁定）：**四字段（item/reason/category/source）为项级固有；turn/section 是框架在拒收报告（rejection_reports/jsonl）投影时补的，不进 RejectedItem**。钉四字段的测试恰是对的，予以保留（可改名/迁至 canonical 类型守门），非按六字段改。

| 行 | 函数 | 所证行为 | 处置理由 |
|---|---|---|---|
| 16 | test_provenance_enum_values | Provenance 五值与字符串一致 | 保留——0150 决定 7 五值来源分类仍 canonical |
| 25 | test_provenance_from_string | 按字符串反查成员 | 保留（同上） |
| 35 | test_rejected_item_fields | RejectedItem 四字段（item/reason/category/source） | 保留（可改名/迁至 canonical 类型守门测试）——0150 决定 2 RejectedItem 为全系统唯一拒收形状；四字段属项级固有，turn/section 由框架在拒收报告投影时补、不进 RejectedItem，钉四字段恰与唯一 typed 契约一致 |
| 50 | test_rejected_item_constructs_with_fields | 四字段按名构造可读 | 保留（同上；四字段项 + 框架补 turn/section 的契约守门，非按六字段改） |
| 367 | test_ddl_in_open_transaction_rolls_back | sqlite DDL 在打开事务内不隐式 commit、随 rollback 撤销 | 保留——环境不变式 pin；0150 决定 3 事务边界归编排器独占后此前提仍成立 |

## 4. 人物/财政/战略三域：既有真 SQLite 行为测试与迁移目标

0150 结论：三域**迁移既有真 SQLite 行为测试到新 adapter 入口，不新增第二套平行 fixture**。迁移目标入口 = `ming_sim/entities/<entity>/` 实体段适配器 `apply(items, ctx) → SectionResult`，由 `settle_delta(state, db, delta, ctx)` 编排（0150 决定 1/2/6）。

| 域 | 文件（函数数） | 现入口 | 迁移目标 adapter 入口 |
|---|---|---|---|
| 人物 | tests/test_person_delta_adapter.py（114） | 直调 `issues.apply_score_extraction` / `apply_person_changes` / `normalize_person_changes`（归一化单测） | 人物实体段适配器（entities/person 段模块）；落库断言经 `settle_delta` 编排后查 DB，归一化单测随 `person_delta_adapter` 模块共置迁移 |
| 人物 | tests/test_person_transit_write_667.py（9） | 直调 `apply_score_extraction`（在途写入缝） | 人物段适配器入口（同上） |
| 人物 | tests/test_appointment_tenure_607.py（6） | 直调 `apply_score_extraction`（任期/任别） | 人物段适配器入口（同上） |
| 财政 | tests/test_surcharge_causal_chain_650.py（28） | `apply_score_extraction` / `settle_with_delta` / `apply_historical_fiscal_rates`（明渠加派 e2e 因果链） | 财政三段适配器（entities/fiscal，段序 removes→creates→changes 为登记表一行）；`settle_with_delta` 外层核调用点不动 |
| 财政 | tests/test_pay_order_override_653.py（69） | `fiscal_tick.settle_tick` / `pay_order.materialize_pay_order_decree` / 直调 `apply_score_extraction`（偿还序 override 票面 golden） | settle_tick/pay_order 入口不动；涉及落库段的部分迁财政段适配器入口 |
| 财政 | tests/test_fiscal_tick.py、test_fiscal_levy_effect.py、test_fiscal_substrate_bridge.py、test_fiscal_beyond_intent_1260.py、test_covert_levy_651.py | fiscal_tick/征收效应直调，部分经 `apply_score_extraction` | 同上，按实际调用点逐个迁财政段适配器 |
| 战略 | tests/test_event_trigger_gate.py（199；其中 ADR0014 战略战果整封组见行 1019/1052/1098/1258/1284/1333/1370/2668/2866） | 事件门闩求值 + 战略信封整封预检（`_preflight` 拒整封、不得半落兄弟战果） | 战略战果落库迁军事/地区/军队段适配器；事件门闩求值引擎留 issues 内（0150 决定 8：求值器非落库段），整封原子断言逐份保留 |
| 战略 | tests/test_mutiny_noop_whitelist_319.py（16） | latched 军字段 deny-by-default 白名单 + `apply_score_extraction` 集成对照 | 写缝白名单随军队段适配器迁移；集成对照改调 `settle_delta` |
| 战略 | tests/test_event_outcome_retry.py、test_military_order_materialize_521.py | 结局标签重试 / 军令状物化（`apply_score_extraction` 路） | 军令状段适配器入口；标签重试属 extractor 层不动 |

## 5. 汇总

- HEAD：`3ef603c68bb7b7276b4948a55ff0ecbfee63da71`
- 209 个 test 函数处置合计：**72 并入参数化公共主干**（driver 臂 49 + adapter 臂 23）/ **86 保留原入口**（11 文件 81 + applier_contract canonical/环境 pin 5）/ **45 迁移**（迁 adapter 入口 29 + 迁移保留 15 + 桥迁移 1）/ **6 删除**（close 段旧桥绿卡 2 + applier_contract 死类型绿卡 4）。
- 主干不收的独立契约分布（全部标「保留原入口」或「迁 adapter 入口」，逐行可查）：rollback/jsonl（wiring L29/54/143、adr0015 L53）、source A/B（wiring L96/647/675）、恢复（wiring L612/741、adr0015 L119）、动态财政（fiscal L65/328）、clamp（section4 L427/447/469、new_issues L188）、战略整封（§4 test_event_trigger_gate.py 组）、issue 路严格度（section4 L594/614/710/731）、event_pool（new_issues L350/364/385/397/413）、玩家可见 extraction（faction L164、economy L174、adr0015 L87）、消费者/formatter（power L149、section4 L488、close L141）。
- 勘正说明（大理寺三审后）：① §3.3 的 RejectedItem 两行按「四字段（item/reason/category/source）项级固有 + 框架在拒收报告投影时补 turn/section」唯一 typed 契约改写处置理由——保留（可改名/迁至 canonical 类型守门），非按六字段改；② 迁移子账由误记的「迁 adapter 31 + collector 生命周期 13 + 基建 pin 1」勘正为逐行实数「迁 adapter 入口 29（secret_order L103/127 + power L127 + new_issues 12 + close_issues L89/103/179 + advances 5 + section4 6）+ 迁移保留 15（§3.2 collector 组 14 + adr0015 L168）+ 桥迁移 1（wiring L229）」。总数 209 与四大类闭合（72/86/45/6）不变。
- 勘正说明（大理寺九审后，reason 措辞锁专项）：209 函数范围内对**生产生成 reason 自由文本**的 substring/等值断言全面清除，改断 category / item_json 原值 / 拒收计数 / DB·状态外部结果，reason 一律只断非空（ADR 0008 决定 5 只要求「有原因」）。**完整审计命中清单（23 个函数行）**：test_power_section_rejections L206（ming/大明）；test_new_issues_section_rejections L137/153/164/176/233/299（「非对象」「强转失败」×3（L153/176/233）含 kind ×2）、L397/413（「过期/终态」「终态/作废」）、L456/466（含 tags ×2）；test_close_issues_section_rejections L30/43/54（含 issue_id/「非对象」/含 reason）、L89（含 active）、L103（「不可崩坏」字样）；test_advances_section_rejections L32/43（「非对象」/含 issue_id）；test_section4_rejections L130（`controlled_by in reason`，源码 :148）；test_rejection_wiring L125（"decree/event_pool" substring）、L435/495/559（`power_updates 引用未入库势力 '查无此势力'` 等值锁三处）。**经审计保留**：reason 非空类（wiring L187/L229、adr0015 L53/L119/L647/L675/L741 已按六审口径结构化）与 sentinel round-trip 两类（power L258「联姻蒙古」测试自传入别名值、wiring L210 ≠「椒房之选」负向回环）——后者断言对象均为测试自有输入而非生产生成文案。不新增 typed 字段替代措辞锁；72/86/45/6 总账与 PR 波次不变。
