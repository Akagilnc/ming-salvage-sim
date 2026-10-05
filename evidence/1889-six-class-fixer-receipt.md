# #1889 六类修内司回执（全定义复扫修正）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1889-w5r`
- 施工分支：`ak-roles/1889-six-class-fixer`
- 判词真源：`…/attachments/04-1889-judge-00aff8316.json` → `outcome.payloads` **末份**
- 底座对照：`10e64fbef`；相对开工 HEAD `00aff8316`；上一提交 `684919d60`（谓词收窄已纠正）
- 约束：无 stash / amend / rewrite / push / PR；七变量 BIN=`/usr/bin/false`；只跑聚焦；不新建自动了结/框架/兼容护栏/证明性测试；不改治理/Soul

---

## 可复跑枚举（完整命令，非伪代码）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1889-w5r
python3 scripts/1889_six_class_enumerate.py --out evidence/1889-six-class-enum.tsv
python3 scripts/1889_six_class_enumerate.py --leaks-only --out /tmp/1889-leaks.tsv
# 按类：
python3 scripts/1889_six_class_enumerate.py --class 1
python3 scripts/1889_six_class_enumerate.py --class 2 --leaks-only
python3 scripts/1889_six_class_enumerate.py --class 3,4,5,6
```

脚本路径：`scripts/1889_six_class_enumerate.py`（本票最小枚举器，非生产机制）。
全量表：`evidence/1889-six-class-enum.tsv`（本轮实测写入）。

本轮实测 lane 计数（写回执时）：

| lane | count |
|---|---|
| c1_fiscal_retired | 6 |
| c2_forward | 7 |
| c2_sql_framework | 65 |
| c2_sql_in_store | 791 |
| c2_sql_leak_candidate | 9 |
| c2_sql_schema | 1 |
| c3_orphan_mech | 14 |
| c4_pop_parallel | 10 |
| c5_affair_close | 1 |
| c6_prose_lock | 5 |
| c6_struct_contract | 22 |

**不冒称「谓词命中 0 = 全清」**：下列各节给出真实候选与逐项处置（清退 / 归位 / KEEP+依据）。

---

## 类1 — 退役财政分流

### 定义边界
删除退役公式、标记及 shadow 平行路径和仅为它们存在的测试；复用现役 hub；不增加兼容或护栏。

### 枚举谓词（脚本 C1_PAT）
`calc_province_fiscal|USE_FISCAL_SUBSTRATE|fiscal_substrate_cutover|use_fiscal_substrate|_read_use_fiscal|_write_use_fiscal|__fiscal_engine|__army_pay_source_cutover|army_pay_source_cutover|fiscal_engine=|legacy.?engine|shadow.?parallel|留作测试参照|cutover.?marker|read_use_fiscal`

### 成员表与处置
| 成员 | 位置 | 处置 | 依据 |
|---|---|---|---|
| 注释「hub-only: cutover markers retired」×6 | `tests/test_mutiny_*.py` / `test_player_army_projection_321.py` | **KEEP** | 仅文档注释，无退役公式/标记/分流代码 |
| `calc_province_fiscal` / cutover 标记读写 / 无标记跳过坏省 | （上轮已删） | 已清 | 复扫生产谓词 0 命中 |

### 结果
类1：无残留退役分流实现；注释 KEEP。

---

## 类2 — 持久职责泄漏与重复实现

### 定义边界
领域编排留领域；持久读写归既有 owner；合并双份 SQL；清退纯转发；调用方直接用现有 Store。**不能**仅以「跨实体编排」保留事实 SQL。

### 枚举
- 全仓 Python AST：`execute` / `executemany` / `executescript`（含动态 SQL）
- GameDB AST：纯 `return self.<store>.…`、无领域逻辑 void/thin 包装

### 修前泄漏（相对 `684919d60` 收窄谓词漏网）→ 本轮归位
| 成员 | 原位置 | 归位 Store | 处置 |
|---|---|---|---|
| 加派人口池/省行/农民余额读 | `displaced_population.py` | `ClassStore` / `RegionStore` | 改走既有 `read_*` |
| 回流 grant 行/省存在/流水合计/流民农民 | 同上 | `DossierStore.grant_allocation_rows` / `RegionStore` / `ReignStateStore.read_apply_recovery_driven_transfers` / `ClassStore` | 改走 Store |
| 人物 seed_guilt/intrigue/ability/location/row | `covert_progress.py` | `CharacterStore.field_row` / `row` | 改走 Store |
| 主办未结差计数 | 同上 | `DossierStore.open_by_executor` | 领域计数 |
| 实况进度幂等读 | 同上 | `DossierStore.actual_progress_at`（新增原语） | 归位 |
| 毁证 list | 同上 + tests | `CharacterKnowledgeStore.list_investigation_spoiled_facts` | GameDB 纯转发删除 |
| 毁证 insert | `db.py` | `CharacterKnowledgeStore.record_investigation_spoiled_fact`（新增） | GameDB 保留校验编排 |
| 密令 body 读/写 | `db.py` | `secret_order_row` / `update_secret_order_assignments` | 归位；删 `_load_*` 纯转发 |
| pending 源轮判/作废读改 | `db.py` | `pending_source_status` / `pending_voidable_for_chat_turn` / `void_pending_if_pending` / `pending_ids_for_chat_turn` | 归位 |
| turn_directives 按 pending 回收 | `db.py` undo | `IssueStore.directive_ids_for_pending_actions` | 归位 |
| 撤令 issue 行 | `db.py` | `IssueStore.row` | 归位 |
| 知识 public/sources/人物名册 | `db.py` knowledge_items | `public_events_for_turn`(补 kind) / `sources_for_turn` / `CharacterStore.read_knowledge_items_for_turn` | 领域聚合留 GameDB |
| 闭夜档案三查询 | `db.py` | `ReignStateStore.closed_nights_archive_rows` / `ledger_archive_rows_for_nights` / `chat_turn_archive_rows_for_nights` | 呈现编排留 GameDB |
| 身份材料人物行 | `materials.py` / `month_chain.py` | `CharacterStore.row` | 归位 |
| override 行 | `pay_order.py` | `FiscalConfigStore.override_rows_for_origin` | 归位 |
| `_set_meta_flag` / `_delete_turn_scoped_*` / `_delete_shared_knowledge_*` / `set_portrait_id` | GameDB | 调用方直达 Store | **删除方法** |

### 修后 `c2_sql_leak_candidate`（9）逐项 KEEP
| 位置 | KEEP 依据 |
|---|---|
| `applier.py` RejectionCollector CRUD + sqlite_master | **RejectionCollector 即 rejection_reports owner**；无既有实体 Store；非 GameDB 旁路 |
| `applier.py` `_SuspendableConnection.executescript` | 连接包装转发，非事实写口 |
| `db.py` PRAGMA foreign_keys / `_table_exists` / `table_has_rows` | 框架/schema 探测；判词：PRAGMA/事务框架不计事实写口 |
| `web_app.py` `SELECT 1` | 运行时可恢复性探针，非领域事实 |

### 修后 `c2_forward`（7）逐项 KEEP
| 方法 | KEEP 依据 |
|---|---|
| `save_state` | GameState→reign 字段适配（领域对象解包），非同参纯转发 |
| `record_person_log` | 同上，多参适配 `person_logs.append` |
| `append_chat_message` | 召对消息写口 + 知识投轨不变式文档；非第二套 SQL |
| `save_resolve_context` | Provenance/sanitize/json 领域归一后写 Store |
| `clear_resolve_context` | 跨 Store（resolve_contexts + dossiers 判词清理）编排 |
| `clear_month_open_snapshot` | 月初快照生命周期写口（票面保留呈现投影） |
| `close` | 连接关闭框架 |

### 结果
类2：判词点名旁路与收窄漏网事实 SQL 已归既有 Store；剩余候选均有书面 KEEP 依据，**非**「谓词 0」。

---

## 类3 — 被取代的孤立机制

### 定义边界
依实际退役关系清退遗留辅助链、专用读写及测试；不能仅因未引用删除仍属票面职责的待接接口。

### 成员与处置
| 成员 | 处置 | 依据 |
|---|---|---|
| `_fail_cli_chat_turn_scene` / Army·Region·Building debug upsert / covert 旧坐实链 | 上轮已删 | 复扫无生产残留 |
| `neutralize_covert_fiscal_effects` + `_COVERT_NEUTRALIZATION_REASON` | **KEEP** | 禁摊派一次性撤销＝票面现役；`covert_levy` 消费 |
| `CharacterStore.upsert` / `record_store.upsert` | **KEEP** | 合法现役原语；判词明示勿误删 |
| 注释「满阈自动写依律的旧清算轨已退役」 | **KEEP** | 说明性注释，非机制 |

### 结果
类3：无新增孤立机制；现役职责保留。

---

## 类4 — 人口规则平行实现

### 定义边界
保留一个现役领域真源；删除复制件、旧名兼容及只维系它们的测试；保留真实世界核算。

### 成员与处置
| 成员 | 处置 | 依据 |
|---|---|---|
| `apply_levy_driven_transfers` / `apply_recovery_driven_transfers` 定义 | **KEEP** | 唯一定义在 `displaced_population.py`；月链直调 |
| `LEVY_DISPLACEMENT_RATE` 常量与引用 | **KEEP** | 核算参数真源，非双份实现 |
| `apply_issue_inertia_and_ongoing` / issues 内双份核算 | 上轮已删 | 复扫无旧名 |
| Store `read_apply_*` 名 | **KEEP** | 持久读原语命名，非第二套领域公式 |

### 结果
类4：单一领域真源；核算保留。

---

## 类5 — 撤回的事务了结机制

### 定义边界
清退显式了结、拒绝该动作的守门及专用旧测试；不借修理新建自动了结。

### 成员与处置
| 成员 | 处置 | 依据 |
|---|---|---|
| `close_from_declaration` / `declare_closed` / `ATTACH_RESULT_CLOSE` / 专用拒收文案 | 已删 | 复扫生产谓词 0 |
| `tests/test_affairs_1831.py` `attach="close"` | **KEEP** | 拒收边界：非法 attach 仍应 ValueError；非恢复了结动作 |
| `audience_nights/decree_dossiers status='closed'` | **KEEP** | 夜/案卷终态，非事务声明了结 |

### 结果
类5：显式了结未复活；未建自动了结。

---

## 类6 — 测试契约边界处置错误

### 定义边界
复用已有最短行为用例承接必要结构化结果；清理非契约叙事锁；不得靠删仍生效契约洗绿；不恢复措辞锁；不新增证明性测试。

### 成员与处置
| 成员 | 处置 | 依据 |
|---|---|---|
| `modals.test.tsx` scrollTop 600/700/100/137 | **KEEP** | 结构化行为；上轮已恢复 |
| `#1732` `aria-label="撤回召对确认"` 关闭断言 | **KEEP** | 结构化存在性 |
| `AGENDA_FROZEN` | 上轮已删 | 复扫 0 |
| `gameMenu`/`menuPage` `textContent=="关（codex/grok…）"` ×4 | **本轮删除** | 菜单措辞锁；保留 `value==="off"` / disabled 结构断言 |
| drawers/map `not.toContain(欠饷…/不满…)` | **KEEP** | 测试注入禁显字段的 P4 缺席契约（硬规13：注入值） |
| `settlementGazettePanel` `pre` 回读注入 report | **KEEP** | 测试注入圆柜；非生产自由文本锁 |

### 变异取证（真实入口）
```bash
# 临时注释 chatModal.tsx 中 scrollTop 恢复赋值后：
cd web && npx vitest run --environment jsdom --cache=false src/components/modals.test.tsx
# → 2 failed（expected 600 / 137 got 0），32 passed；还原后 34 passed
```
日志：`/tmp/1889-mutation-scroll.out`（红）、`/tmp/1889-mutation-scroll-restore.out`（绿）。生产文件已还原。

### 结果
类6：叙事菜单锁已清；结构化契约保留并经变异咬合。

---

## 聚焦测试（七变量前缀）

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false
```

| 批次 | 命令摘要 | 实测 |
|---|---|---|
| core+fiscal | pytest new_game_smoke / population_648 / surcharge_650 / affairs_1831 / supervision / covert_levy / pay_order / section_fiscal / secret_order_payoff + fiscal_bridge `-k …` | **143 passed**, 263 deselected；`real 13.98s`（`/tmp/1889-focus-core.out`） |
| more | mutiny×5 / player_army / month_translate_1840 / relation_seed / character_knowledge / audience_scroll / decree_commitment | **242 passed**；`real 5.39s`（`/tmp/1889-focus-more.out`） |
| web | `modals` + `gameMenu` + `menuPage` | **79 passed**；`/tmp/1889-focus-web-c6.out` |
| scrollTop 变异 | 见上 | 红 2 failed → 绿 34 passed |
| `git diff --check` | | clean |

未跑全量（票面：只跑聚焦）。

---

## 自查二连

1. **合法性**：未改治理/Soul；未新建自动了结；未恢复措辞锁；未新增证明性测试；禁摊派中和与 P4 缺席契约保留。
2. **引入 bug**：上轮收窄谓词导致 db/域名事实 SQL 漏网——本轮按全定义 AST 枚举归位；变异证明 scrollTop 断言仍咬合；聚焦绿。
3. **边界**：未放松上轮已清的财政分流/了结/人口双份；仅补全漏网与诚实 KEEP 表。

---

## 剩余范围 / 真实阻断

- 无本票六类未处置候选阻断（剩余均为 KEEP+依据）。
- 不宣告合并、不关票、不 push、不开 PR。
- 家族收尾复杂度对比仍归 #1812 / owner。
