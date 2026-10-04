# #1889 修内司回执：K3（非契约文案 / 材料标题 / 内部标签 / 删简残段）

派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a10858-3646-7193-a4b4-8f1007247730@fixer/fix-packet.md`  
判词附件（**末份 payload 为准**）：`attachments/02-1889-judge-cf79a8d0e.json`  
工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1889-w5r`；分支 `ak-roles/1889-k3-text-contracts`  
基线 HEAD（施工前 tip）：`cf79a8d0e891b22bd3a98bb03a7202d7e524e90c`  
本文件是施工证据，不另立 authority。

**提交**：劳务只负责编辑与验证；修内司核验后建立独立 `ak-roles:` 提交，不 amend、不 push。提交 SHA 见终局工具回执。

未结类（末份原文）：
1. **K3**「测试仍机械依赖非契约文案」— 成立。disposition：上一判全审遗漏、本轮新立的测试质量类。

处方方向（末份 `fix.classes[0]`）：优先删除 / 合并无必要行为价值的断言及删简残段；复用已有真实入口与结构化结果断言。保留现役公私可见边界、拒收及失败负向契约；用户输入文本的存读保真 ≠ 锁生成文案。不得恢复退役包装、为证明删除换形新增测试，或增加生产机制。

类边界（核对时分清，不得混谈）：
- **固定菜单定位**（短标题 / 菜单 / 对话框 `aria-label` 找控件）≠ K3
- **输入保真**（同案注入原文再负向/回读）≠ 锁生成叙事
- **生成叙事 / 材料标题 / 内部标签 / 生产 chrome 措辞锁** = K3

---

## 枚举命令（宽候选 → 系统临时目录；非分类引擎）

```sh
python3 scripts/1889_k3_enumerate.py
```

复用标准 AST：Python `ast`（全部 `Assert` / `Compare`含变量与多行、`pytest.raises(match=)`、字符串方法、bare `pass`）+ TypeScript compiler AST（全部 `expect*`、DOM/string selection）。候选只写系统临时目录；**不在脚本内做处置/分类**。扫描失败直接抛出，不洗白。

本轮实测：

```text
files_scanned=255  py=26396  js=3913  total=30309
CANDIDATES=/var/folders/nb/ml2z6k013psg7rdtt0t6g91m0000gn/T/1889-k3-enum-1mhkp2yi/candidates.jsonl
```

`by_kind` 摘要：`Compare=13283` `Assert=12512` `pass=44` `raises_match=90`；其余为 `strmethod_*` / `expect_*` / `selection_*`。

**已删本轮自建膨胀物**（授权清理）：`docs/1889-k3-members.tsv`、`docs/1889-k3-disposition-overrides.tsv`、旧 `scripts/_1889_k3_ts_scan.mjs`、旧分类引擎。  
候选全量在临时目录，回执不落巨量表。KEEP 证据只写在「保留类别」节。

### 复扫结论（按类定义读候选）

扩扫后对新增候选源（变量/多行 `Compare`、全仓测试入口、TS expect/DOM/string）逐项按类定义核对：
- **判词点名样本**（precondition 人话、`兵籍在册`/`任免簿`、`postures` 内部标签、删简 bare `pass`）均已落入下表删除/修改成员。
- **补扫（本轮纠偏）**：上轮误把「UI 固定话语单元测」整类当 KEEP，并以 P7「界面固定话语不禁」缩窄 K3——**撤销**。P7 只豁免生产侧界面固定话语本身，**不豁免**测试锁非契约完整文案。同扫描复核对全部原「UI 固定话语」保留项：菜单/标题纯控件定位与形式语言/机器 ID 可留；锁完整 aria / 报错 / 状态标题全文断言不能留。补删/改成员见下表末行（`yearMonthLabel` 年月全文加「核账/待批」、`settleStream`「推演流意外中断。」）。
- 其余扩扫中文断言仍多为：注入保真、实体/官职/科目键、材料路径契约、短菜单定位——归保留类别，不与生成叙事混谈。
- 判词既有「措辞替换探针」（内存改 precondition 人话即红）只证明该类成立，**不充本轮行为修复或变异真跑证据**。本票 K3 = 删/改无效测试断言；**未为删除新造测试**。

---

## K3 全部成员（修前行号 + 函数名；删除/修改单表）

行号相对基线 tip `cf79a8d0e`。成员 = 本轮实际删除或改写的非契约文案锁 / 材料标题 / 内部标签 / 删简残段。保留断言不进本表。

| 处置 | 修前位置（文件:行 / 函数） | 原断言/残段 → 处置 |
|---|---|---|
| 删 | `tests/test_audience_continuous_507.py:52` / `test_scene_recap_quotes_public_dialogue_within_presence_interval` | `assert "此人跋扈" not in recap` → 改注入变量负向（见下一行） |
| 改 | 同上:52–53 | 先 `private_body = "此人跋扈"` 注入 ledger，再 `assert private_body not in recap` |
| 改 | `tests/test_audience_draft_grant_once_1777.py:95` / `test_http_audience_one_matter_grant_with_deadline_1783` | 删 `if "【本轮皇帝】准" in text`；改 pending-directive 结构分支 |
| 删 | `tests/test_breach_plea_623.py:430` / `test_persist_foundation_tiers` | bare `pass` |
| 删 | `tests/test_character_knowledge_489.py:61–63` / `test_current_state_facts_are_selected_by_content_domain_not_role_label` | bare `pass` ×3 |
| 删 | `tests/test_character_knowledge_489.py:354` / `test_secret_office_exclusion_does_not_hide_unrelated_world_bucket` | `assert view["world"]["public"] == "登基伊始…"` |
| 删 | `tests/test_character_knowledge_489.py:1309` / `test_central_ledgers_and_unbounded_household_history_reach_final_materials` | `兵籍在册` + `军心`/`欠饷` 标题负向 |
| 改 | 同上（原:1309） | 军名存在于 war 材料（结构化名册，不锁标题） |
| 删 | 同上:1313 | `任免簿` 材料标题 |
| 改 | 同上（原:1313） | 朝臣名册成员存在性 |
| 删 | `tests/test_decree_dossiers_571.py:2045` / `test_inner_treasury_admission_uses_actual_once_and_preserves_surface` | bare `pass` |
| 删 | `tests/test_due_review_621.py:247` / `test_due_review_scene_tops_live_open_night_even_with_body` | `当前待裁场面` 模板锁 |
| 改 | 同上:247–248 | facts 原文进 opening（输入保真） |
| 改 | `tests/test_event_trigger_gate.py:483–486` / `test_gate_key_form_error_rejects_typo_metric_table_structure` | 删 `未知 metric`/`未知表` 措辞锁；改非空 fail-loud |
| 删 | `tests/test_event_trigger_gate.py:1419–1431` / `test_wuyin_lubian_content_treats_lu_death_as_soft_battle_outcome` | 整用例（precondition 人话及 resolve/fail 措辞锁） |
| 删 | `tests/test_event_trigger_gate.py:2125–2126` / `test_huangtaiji_chengdi_auto_triggers_and_renames_houjin` | `称帝` in status；`last_action == "皇太极称帝改国号大清"` |
| 删 | `tests/test_fiscal_substrate_bridge.py:400` / `test_region_loader_expands_shared_settle_meta_defaults` | `postures == ["江南财赋核心"]` |
| 删 | `tests/test_fiscal_substrate_bridge.py:3383–3384` / `test_shanxi_seed_stacks_frontier_pay_and_jin_vassal_dues` | `边镇军饷`/`晋藩宗禄` in postures |
| 删 | `tests/test_fiscal_substrate_bridge.py:3697` / `test_jiangnan_core_seeds_have_positive_remittance_golden` | `江南财赋核心` in postures |
| 删 | `tests/test_fiscal_substrate_bridge.py:3720` / `test_huguang_seed_stacks_jiangnan_surplus_with_chu_princely_due` | `楚藩重宗禄` in postures |
| 删 | `tests/test_menu_lifecycle_drain_396.py:607` / `test_drain_waits_for_queued_chat_stream_not_just_gate_holder` | `仍在进行` |
| 删 | `tests/test_month_chain_1843.py:720,733` / `test_world_segment_reads_material_directory` | `盘面：` 开场模板 |
| 删 | `tests/test_on_scene_immediate_write_1839.py:97,102` / `test_kill_lands_status_and_next_materials_include_roster` | bare `pass` ×2 |
| 改 | 同上:97 | `victim not in` 名册材料 |
| 删 | `tests/test_power_section_rejections.py:159` / `test_power_change_formatter_skips_rejected_items` | `未见明确势力盘面变化` |
| 改 | 同上:159–160 | 拒收 reason `字段非法` 不回显（NEG） |
| 删 | `tests/test_qa_b3_409_ux.py:75` / `test_serialized_web_write_settling_keeps_settlement_in_progress_copy` | `月末结算进行中` |
| 删 | `tests/test_qa_b3_409_ux.py:89,91` / `test_serialized_web_write_rejects_front_half_done_phases` | bare `pass` ×2 |
| 改 | `tests/test_rejection_wiring.py:240` / `test_inertia_tolerated_rejections_reach_reports` | 只保留注入字段名 `士气大振` |
| 删 | `tests/test_secret_order_monthly_progress_566.py:338,340` / `test_real_no_edict_entries_roll_back_every_external_state_after_fiscal_write` | bare `pass` ×2 |
| 删 | `tests/test_secret_order_update.py:22` / `test_upsert_creates_then_updates` | bare `pass` |
| 删 | `tests/test_section4_rejections.py:507,510` / `test_region_army_formatters_skip_rejected_items` | `未见明确地区/军队盘面变化` |
| 改 | 同上:507,510 | `字段非法` 不回显（NEG） |
| 改 | `tests/test_section4_rejections.py:675` / `test_issue_path_tolerated_rejections_reach_reports` | 只保留注入 `士气大振` |
| 删 | `tests/test_web_chat_serialization_393.py:390` / `test_nonstream_chat_rejects_when_session_draining` | `正在关闭` |
| 删 | `web/src/appDurableWiring.test.tsx:2684,2705` | aria 全文 `奏疏：1 件待览` |
| 改 | 同上:2685,2706 | badge 数字 `1`（结构化未读） |
| 删 | `web/src/components/modals.test.tsx:1101` | aria 含「递话」 |
| 改 | 同上 | dialog 存在（不锁 aria 叙事） |
| 删 | `web/src/components/settlementFaces.test.tsx:128` | aria `/0\s*件待览/` |
| 删 | `web/src/components/settlementFaces.test.tsx:274` | title 不含「核账」 |
| 删 | `web/src/decisionRouting.test.tsx:142` | error 不含「重新拉取」 |
| 删 | `web/src/mindreadingDelivery.test.tsx:293,298` | `busy === "大臣思索中"` |
| 改 | 同上 | busy 非空（流占用结构；不锁 chrome 措辞） |
| 删 | `web/src/settlementPresentation.test.ts:27–31` / `#1234 year-month label…` | `yearMonthLabel` 锁「1627 年 10 月」/「· 核账」全文；整用例删 |
| 删 | `web/src/settlementPresentation.test.ts:33–45` / `#1323 …年月标 ·待批…` | `yearMonthLabel` 锁「· 待批」/「· 核账」；附带 `wangSettlementSlipVisible` 与下段矩阵重复，随删不换形 |
| 改 | 同上 import | 清 unused `yearMonthLabel` |
| 改 | `web/src/settleStream.test.ts:45` / `still returns interrupted…` | 删锁「推演流意外中断。」；改 `kind===error` + 非空 string（结构；不锁 chrome） |
| 删 | `web/src/components/decisionModal.test.tsx:624–625` / `#657 midzhi projects…` | 注入 label「加衔恩赏」/hint「荣誉」已 `toBe` 保真后，再 `not.toBe("另旨·中旨")`/`not.toBe("中旨直发")` 锁生产钮文且重复结论 → 删两行；保留 label/hint 保真 + grant 结构化字段 |
| 删 | `tests/test_pihong_dossier_1490.py:1869` / `test_657_midzhi_persists_decision_key_and_llm_label` | 同构：`decree_text == llm_label` 保真后仍 `assert '另旨·中旨' not in …` → 删；保留 decision_key / llm_label 正向 |

**成员计数**：上表全部为删除或修改的真 K3 处置位。不含「保留」行。

**纠偏（开卷后）**：上表末两行 = 「注入原文相等后仍锁生产替代文案负向」同构漏项。全仓 AST 复扫候选中仅此两处含「另旨·中旨」/「中旨直发」负向；不得假称保密负向（NEG）。其它负向契约（拒收不回显、秘密排除、注入原文不外泄等）不动。

---

## 保留类别（非修复成员；可核来源）

| 码 | 含义 | 本轮触及可核例 |
|---|---|---|
| INPUT_FIDELITY | 同案注入原文再负向/回读 | `private_body`→recap 负向；due_review `facts`→opening；`test_error_pack` 注入 SettlementAbort 原文进 detail；midzhi `label`/`hint`/`decree_text==llm_label` 正向保真（**不含**再锁生产钮文负向） |
| INJECTED_FAILURE | 测试注入失败字段/原文 | `士气大振` 非法字段名；error_pack 注入文案 |
| ENTITY_ID | 实体改名/存在性 | `huangtaiji`→`大清`+aliases；军名/朝臣名在材料中 |
| NEGATIVE_CONTRACT | 拒收/保密负向 | reason 不回显；secret_order 排除；victim 不在名册 |
| MACHINE_ID | 结构化键/路径 | `转译声明的当场实况`；`朝臣名册.txt` 等材料路径；财政科目键 |
| LOCATOR_SEAM | 短标题/菜单定位 | `奏疏`/`邸报`/`朝堂·召见大臣` 等找控件；**不含**完整 aria 叙事或动态「N 件待览」 |
| STRUCTURAL_PASS | 合法 except/空体 | 本轮只删无作用删简残段 pass |
| ERROR_SENTINEL | 常量哨兵通道（非锁措辞字面） | `decisionRouting` `toBe(PAUSED_DECISION_MSG)`——比的是导出哨兵身份，不另锁中文子串 |

**撤销**：上轮「`yearMonthLabel`「· 核账/· 待批」= UI 固定话语 → KEEP」**作废**；该两例已入成员表删除。P7 界面固定话语豁免≠测试可锁非契约 chrome。  
**仍属 INPUT_FIDELITY（非 UI 固定话语 KEEP）**：fixture 回读 `奴婢呈上月邸报` / `密令未能正式落库`；staleGuard fixture 自拼 `甲：已离开实时回话`。  
补扫后同口径下未见其它「纯锁完整 aria/报错/状态标题」漏项需再删。

---

## 测试（七个 false BIN）— 实测

环境前缀（七个均设置）：

```sh
export MING_SIM_AGY_BIN=/usr/bin/false \
  MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false \
  MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false \
  MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false
PY=/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python
```

### CMD1 — 触及 pytest nodeid（含本轮改动节点）

```sh
/usr/bin/time -p "$PY" -m pytest -q --tb=line \
  tests/test_audience_continuous_507.py::test_scene_recap_quotes_public_dialogue_within_presence_interval \
  tests/test_audience_draft_grant_once_1777.py::test_http_audience_one_matter_grant_with_deadline_1783 \
  tests/test_breach_plea_623.py::test_persist_foundation_tiers \
  tests/test_character_knowledge_489.py::test_central_ledgers_and_unbounded_household_history_reach_final_materials \
  tests/test_character_knowledge_489.py::test_current_state_facts_are_selected_by_content_domain_not_role_label \
  tests/test_character_knowledge_489.py::test_secret_office_exclusion_does_not_hide_unrelated_world_bucket \
  tests/test_decree_dossiers_571.py::test_inner_treasury_admission_uses_actual_once_and_preserves_surface \
  tests/test_due_review_621.py::test_due_review_scene_tops_live_open_night_even_with_body \
  tests/test_error_pack.py::test_web_issue_endpoint_returns_structured_abort \
  tests/test_event_trigger_gate.py::test_gate_key_form_error_rejects_typo_metric_table_structure \
  tests/test_event_trigger_gate.py::test_huangtaiji_chengdi_auto_triggers_and_renames_houjin \
  tests/test_fiscal_substrate_bridge.py::test_huguang_seed_stacks_jiangnan_surplus_with_chu_princely_due \
  tests/test_fiscal_substrate_bridge.py::test_jiangnan_core_seeds_have_positive_remittance_golden \
  tests/test_fiscal_substrate_bridge.py::test_region_loader_expands_shared_settle_meta_defaults \
  tests/test_fiscal_substrate_bridge.py::test_shanxi_seed_stacks_frontier_pay_and_jin_vassal_dues \
  tests/test_menu_lifecycle_drain_396.py::test_drain_waits_for_queued_chat_stream_not_just_gate_holder \
  tests/test_month_chain_1843.py::test_world_segment_reads_material_directory \
  tests/test_on_scene_immediate_write_1839.py::test_kill_lands_status_and_next_materials_include_roster \
  tests/test_power_section_rejections.py::test_power_change_formatter_skips_rejected_items \
  tests/test_qa_b3_409_ux.py::test_serialized_web_write_rejects_front_half_done_phases \
  tests/test_qa_b3_409_ux.py::test_serialized_web_write_settling_keeps_settlement_in_progress_copy \
  tests/test_rejection_wiring.py::test_inertia_tolerated_rejections_reach_reports \
  tests/test_secret_order_monthly_progress_566.py::test_real_no_edict_entries_roll_back_every_external_state_after_fiscal_write \
  tests/test_secret_order_update.py::test_upsert_creates_then_updates \
  tests/test_section4_rejections.py::test_issue_path_tolerated_rejections_reach_reports \
  tests/test_section4_rejections.py::test_region_army_formatters_skip_rejected_items \
  tests/test_web_chat_serialization_393.py::test_nonstream_chat_rejects_when_session_draining
```

```text
4 failed, 29 passed, 1 warning in 5.32s
real 6.29
user 4.47
sys 1.19
PY_EXIT:1
```

失败（如实；**非本轮未修完的 K3 文案锁**）：

| nodeid | 原因 |
|---|---|
| `…draft_grant_once_1777…1783` | issue/stream → `stage=gazette` SettlementAbort（见下节基线复验：基线同红） |
| `…due_review…with_body` | `GameDB.list_supervision_history` AttributeError（#1873）；失败在取 facts，早于文案断言 |
| `…menu_lifecycle_drain…gate_holder` | `_GapBDB` 缺 `reign`（测试桩缺口）；失败在 chat_stream 启动 |
| `…rejection_wiring…inertia…` | `GameDB.knowledge_items_for_turn` AttributeError（#1873） |

### CMD2 — web 触及 vitest（含补扫新触及）

```sh
cd web && /usr/bin/time -p npm test -- --run \
  src/mindreadingDelivery.test.tsx \
  src/appDurableWiring.test.tsx \
  src/decisionRouting.test.tsx \
  src/components/modals.test.tsx \
  src/components/settlementFaces.test.tsx \
  src/settlementPresentation.test.ts \
  src/settleStream.test.ts
```

（实测结果见下节「补扫实测」；首轮五文件曾 134 passed。）

未跑全量。未 stash / amend / push / PR。未代提交。未为删除新造测试。

---

## 补扫实测（yearMonthLabel / settleStream 纠偏后）

环境前缀同七个 false BIN。新触及 + 既有 web 触及一并复跑：

```sh
cd web && /usr/bin/time -p npm test -- --run \
  src/settlementPresentation.test.ts \
  src/settleStream.test.ts \
  src/mindreadingDelivery.test.tsx \
  src/appDurableWiring.test.tsx \
  src/decisionRouting.test.tsx \
  src/components/modals.test.tsx \
  src/components/settlementFaces.test.tsx
```

```text
Test Files  7 passed (7)
Tests  145 passed (145)
Duration  5.27s
real 5.84
user 9.65
sys 1.88
VITEST_EXIT:0
```

（相对首轮五文件 134：+`settlementPresentation`/`settleStream`；删 2 个 yearMonthLabel 文案用例后总数 145。）

---

## 基线复验：`draft_grant_once_1777` SettlementAbort

同真实入口 nodeid：`tests/test_audience_draft_grant_once_1777.py::test_http_audience_one_matter_grant_with_deadline_1783`  
方法：工作树文件先跑；再以 tip `HEAD` 版同文件临时替换后同入口复跑；最后恢复工作树版。证据目录：

`/tmp/1889-k3-baseline-recheck-zq3KDD/`
（含 `working.out`、`baseline.out`、`working_test_audience_draft_grant_once_1777.py`）

| 版本 | EXIT | 失败形态 |
|---|---|---|
| 工作树（K3 改 pending 结构分支后） | 1 | `stage: gazette` SettlementAbort（「本月结算失败…可重试」） |
| 基线 tip 文件（含原 `【本轮皇帝】准` 分支） | 1 | **同** `stage: gazette` SettlementAbort |

结论：**基线同红**，不能把该红灯归因为本轮 K3 翻译分支改动，也**没有证据**单独写成「stub 缺口」；属既有 issue/stream→gazette 失败面（可与 #1873 并存登记，本切片不修功能）。

---

## 纠偏实测（decisionModal / pihong midzhi 同构）

环境前缀同七个 false BIN。

### CMD3 — midzhi 注入保真后删生产钮文负向

```sh
/usr/bin/time -p "$PY" -m pytest -q --tb=line \
  tests/test_pihong_dossier_1490.py::test_657_midzhi_persists_decision_key_and_llm_label
```

```text
1 passed in 7.62s
real 8.14
user 1.35
sys 2.63
PY_EXIT:0
```

```sh
cd web && /usr/bin/time -p npm test -- --run src/components/decisionModal.test.tsx
```

```text
Test Files  1 passed (1)
Tests  18 passed (18)
Duration  3.00s
real 4.01
user 1.15
sys 0.18
VITEST_EXIT:0
```

复扫：`python3 scripts/1889_k3_enumerate.py` → 候选中「另旨·中旨」/「中旨直发」负向仅上述两处（已删）；无其它同构漏项。

---

## 结论

**K3 文案/标签/残段成员已按修前行号全部删除或改写；上轮误留的 `yearMonthLabel` KEEP 已撤销并删净，同口径补改 `settleStream` 报错字面锁；开卷后再删 midzhi「注入保真后锁生产钮文」同构两处。**  
不得以 P7「界面固定话语」豁免缩窄 K3；菜单/标题定位与机器 ID 仍可留。  
注入原文相等 ≠ 再锁生产替代文案负向；不得假称保密负向。  
枚举复用标准 AST，候选在系统临时目录，回执只列真成员（删/改）与保留类别指针。  
聚焦实测：pytest 首轮 `29 passed / 4 failed`（含基线同红的 gazette abort + #1873/桩缺口）；补扫 vitest `145 passed`（7 files）；纠偏 midzhi pytest `1 passed` + decisionModal vitest `18 passed`。  
判词措辞替换探针不充本轮行为修复证据。未代提交。
