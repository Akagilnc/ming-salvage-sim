# #1889 七类修内司回执（K5 整类实际清退 · forward shells）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1889-w5r`
- 施工分支：`ak-roles/1889-seven-class-fixer`
- 本轮相对开工：`043a93940`
- 约束：无 amend / rebase / stash / push / PR；七变量 BIN=`/usr/bin/false`；只跑聚焦；不新建证明测试/护栏/兼容/功能补齐；不改治理/Soul/宿主/SDK/席位；不碰既存存档；不改 batch/事务边界

---

## 授权未结类（末判原文类名）

K4 / K1 / K5 / K8 / K9 / K3 / K7

本轮主施工面：**K5 纯 Store 转发壳实际清退**（禁止「票面待接 / pending ownership review / 现役调用入口」作 KEEP 依据）。

---

## K5 逐成员语义判据（本轮真源）

### DELETE — 同形持久转发（消费者直连既有 Store，合法所有权点 commit）

| 成员 | 原形状 | 消费者改法 |
|---|---|---|
| `GameDB.class_rows` | `ClassStore.read_class_rows` | `class_report` 直调 `ClassStore` |
| `GameDB.get_directive` | `IssueStore.directive` | `session` / 测试 → `IssueStore(...).directive` |
| `GameDB.list_closed_issues_at` | `IssueStore.read_list_closed_issues_at` | `web_app` → Store |
| `GameDB.find_active_issue_by_origin` | `IssueStore.read_find_active_issue_by_origin` | `issues` / 测试 → Store |
| `GameDB.find_any_issue_by_origin` | `IssueStore.read_find_any_issue_by_origin` | `db`/`issues`/测试 → `self.issues` 或 Store |
| `GameDB.reject_directive` | `set_directive_status(...,'rejected', expected='pending')` + commit | 测试在所有权点 `IssueStore` + `conn.commit` |
| `flows._set_fiscal_container` / `_add_fiscal_container` | `FiscalContainerStore.replace/add` | 调用点直调 Store |
| `breach_plea._issue_row` / `list_active_commitments` | `IssueStore.row` / `read_list_active_commitments` | 调用点直调 Store |
| `issues.character_row`（嵌套 Store one-liner） | `CharacterStore.read_character_row` | 调用点直调 Store |

活调用 / 「职责待接」**不是**保留纯转发壳的依据：职责由既有真源 Store 承担。

### KEEP — 逐方法读完整体后的真实职责（禁止同一泛化标签批量 KEEP）

| 方法 | 为何不可等价直调 Store |
|---|---|
| `GameDB.save_state` | **GameState→ReignStateStore.save 字段解包**（year/period/turn/turn_phase/ended/ending_status/metrics）；不是裸 `reign.save` |
| `GameDB.save_ending_summary` | **GameState + timeline `json.dumps` 打包**进 `write_save_ending_summary`，并在 GameDB 所有权点 commit |
| `GameDB.save_resolve_context` | **`sanitize_sqlite_text` + `safe_json_dumps` + Provenance.value 归一**后再 `resolve_contexts.upsert` + commit；同形转发无法保留该读缝适配 |
| `GameDB.clear_resolve_context` | **多事实编排**：`resolve_contexts.delete` + `dossiers.clear_pending_promulgation_verdicts` **同一 commit**；不是单 Store delete |

### NON_MEMBER — 内部 alias（不以类名蒙混）

| 方法 | 依据 |
|---|---|
| `create_decree_dossier` → `_create_decree_dossier_row` | 公有 API / 私有实现拆分，非 Store 双权威 |
| `stage_directive_candidate` → `stage_pending_action` | 同对象域绑定（kind=directive / action=拟旨），非 Store 转发壳 |
| `read_directive_dossier_payload` → `_decode_...` | 行字段抽取 + 严格解码缝，非 Store 双入口 |
| `get_active_secret_orders_for_minister` → `list_secret_orders` | 同对象命名过滤绑定，非 Store 双权威 |
| session_write_queue / materials / CliChat aliases | 非持久化 method alias |

---

## 枚举脚本整改

`evidence/1889-seven-class-enumerate.py`：

- 废止 `gamedb_facade_pending` / `module_store_forward` 的 pending-review KEEP。
- 新 kind：`gamedb_pure_forward`（DELETE）、`gamedb_domain_adapter`（KEEP，方法级 BASIS）。
- AST：`_call_has_domain_adaptation`（sanitize/json/state 字段/多 Store ops）。
- baseline 扫描补本轮已删纯壳（含 `list_active_commitments` / nested `character_row`）。
- orphan 候选：禁止「待接」KEEP；无名噪声 → NON_MEMBER。

可复跑：

```bash
python3 evidence/1889-seven-class-enumerate.py
```

### 修后复扫摘要

| 处置 | 条数 |
|---|---|
| NON_MEMBER | 4673 |
| KEEP（33 distinct basis） | 279 |
| DELETE_DONE | 40 |
| DELETE_REVOKED_K3 | 2 |
| LIVE 生产 DELETE 残差 | **0** |

K5 成员车道 52；forward_shell：DELETE_DONE（含本轮纯壳）+ domain_adapter KEEP×4（上表）+ internal/non_persist NON_MEMBER；**无 pending-review 假 KEEP**。

---

## 聚焦测试

环境前缀：七个 `MING_SIM_*_BIN=/usr/bin/false`。

```bash
../Ming_LLM/.venv/bin/python -B -m pytest -q -p no:cacheprovider --tb=line \
  tests/test_section_fiscal_rejections.py \
  tests/test_audience_restore_505.py \
  tests/test_chat_stream_failpaths_393.py \
  tests/test_event_trigger_gate.py::test_load_event_requires_latest_or_open_window \
  tests/test_event_trigger_gate.py::test_load_event_rejects_non_boolean_open_window \
  tests/test_character_knowledge_489.py \
  tests/test_affairs_1831.py \
  tests/test_rescript_draft_656.py::test_clear_pending_decisions_keeps_rescript_drafts \
  tests/test_promulgation_seam_560.py \
  tests/test_new_game_smoke.py \
  tests/test_breach_plea_623.py \
  tests/test_decree_dossiers_571.py::test_pending_directive_only_enters_settlement_after_final_approval \
  tests/test_commitment_backlash_626.py::test_ac1_breach_verdict_triggers_commitment_backlash \
  tests/test_commitment_backlash_626.py::test_ac1_deformation_exposure_triggers_commitment_backlash \
  tests/test_supervision_625.py::test_ac2_paired_observation_slots_and_countermeasure_hard_gate \
  tests/test_fiscal_substrate_bridge.py::test_fixed_flows_substrate_hub_books_split_treasury_income_and_central_losses \
  tests/test_new_issues_section_rejections.py \
  tests/test_draft_admission_resubmit_1769.py \
  tests/test_structured_decree_contract_1624.py::test_http_manual_directive_lands_beyond_fifteen_initiatives_1790
```

**实测**：`231 passed in 11.71s`。完整输出：`/tmp/1889-k5-focused.out`。

未纳入：`test_rescript_follow_draft_nails_drafted_roster`（既有 `GameDB.save_rescript_drafts` 缺失，与本轮删壳无关，未顺手补兼容）。

无新增证明性用例；未改 batch/事务边界。

---

## Advisor 自查（修改前 + 最终）· 自查二连 done

**修改前**：
- disposition 以「票面待接 / 现役调用」KEEP 纯 Store 转发壳 → 违 K5。
- `reject_directive` 与读口同形转发未分判。

**最终**：
- 所列纯壳 + 同类 module one-liner 已删；消费者直连 Store；所有权点 commit 未并入新层。
- 四方法 KEEP 各带不可等价直调依据；无泛化批量 KEEP；无 pending-review 假 KEEP。
- 枚举谓词与处置表已按实际现状重扫；LIVE DELETE=0。
- 未改治理宪法 / Soul / 宿主 / SDK / 席位 / 既存存档。
- 未 amend / stash / push / 开 PR。

---

## 证据路径

| 文件 | 用途 |
|---|---|
| `evidence/1889-seven-class-enumerate.py` | 完整可复跑枚举+处置谓词 |
| `evidence/1889-seven-class-member-disposition.tsv` | 全员处置 |
| `evidence/1889-seven-class-enum.tsv` | 成员车道 |
| `evidence/1889-seven-class-enum-raw.tsv` | 宽谓词原始扫 |
| `evidence/1889-seven-class-fixer-receipt.md` | 本回执 |
| `/tmp/1889-k5-focused.out` | 聚焦测完整输出 |
| `/tmp/1889-seven-enum-k5.out` | 本轮枚举复跑输出 |
