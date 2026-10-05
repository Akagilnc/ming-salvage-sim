# #1889 六类修内司回执（核查纠偏）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1889-w5r`
- 施工分支：`ak-roles/1889-six-class-fixer`
- 判词真源：`evidence`/attachments 末份 judge payload（六类 sealed）
- 相对开工基线：`00aff8316`；纠偏前误报提交：`8e77a2b46` / `684919d60`
- 约束：无 amend / rewrite / push / PR；七变量 BIN=`/usr/bin/false`；只跑聚焦且**不得 `-k`**；不新建证明测试/护栏/兼容；不改治理
- 过程例外（如实）：曾误触一次 `git stash`，**立即 `stash pop` 恢复**，工作树未丢；此后未再 stash

---

## 可复跑枚举（完整命令）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1889-w5r
python3 scripts/1889_six_class_enumerate.py --out evidence/1889-six-class-enum.tsv
# real ~8.56s（本轮实测）
python3 scripts/1889_six_class_enumerate.py --leaks-only --out /tmp/1889-leaks.tsv
python3 scripts/1889_six_class_enumerate.py --class 1
python3 scripts/1889_six_class_enumerate.py --class 2 --leaks-only
python3 scripts/1889_six_class_enumerate.py --class 3,4,5,6
```

脚本：`scripts/1889_six_class_enumerate.py`（最小证据工具：snip/行写均 `.rstrip()`，防 TSV 截断尾空白）。
全量表：`evidence/1889-six-class-enum.tsv`（本轮重生成）。

### 本轮 lane 计数（实测）

| lane | count |
|---|---|
| c1_fiscal_retired | 6 |
| c2_forward | 4 |
| c2_sql_framework | 65 |
| c2_sql_in_store | 792 |
| c2_sql_leak_candidate | 9 |
| c2_sql_schema | 1 |
| c3_orphan_mech | 21 |
| c4_pop_parallel | 376 |
| c5_affair_close | 1 |
| c6_string_lock | 18295 |

### `git diff --check` 实测（不得洗白）

```bash
# 历史提交间（纠偏前已入库的 TSV 仍含截断尾空白）——本轮实测非 clean：
git diff --check HEAD~2 HEAD
# exit=2；50 行，全部指向 evidence/1889-six-class-enum.tsv trailing whitespace
# 日志：/tmp/1889-diff-check-head2.out

# 本轮重生成后工作树（含新 TSV）——实测 clean：
git diff --check
# exit=0；0 行；日志：/tmp/1889-diff-check-wt.out
```

**结论**：不得报告「HEAD~2..HEAD diff --check clean」。生成器已修 rstrip；本提交入库的新 TSV 为 clean；历史两提交间仍失败属既成事实。

---

## 类1 — 退役财政分流

### 定义边界
删除退役公式、标记及 shadow 平行路径和仅为它们存在的测试；复用现役 hub；不增加兼容或护栏。

### 成员与处置
| 成员 | 位置 | 处置 | 依据 |
|---|---|---|---|
| 注释「hub-only: cutover markers retired」×6 | `tests/test_mutiny_*.py` / `test_player_army_projection_321.py` | **KEEP** | 仅文档注释；生产 cutover 谓词 0 |
| `FiscalConfigStore.override` | `ming_sim/entities/fiscal_container/config.py` | **KEEP/恢复** | 现役写口；误删会导致 pay_order 批次崩，已从历史恢复 |

### 结果
类1：无残留退役分流实现。

---

## 类2 — 持久职责泄漏与重复实现

### 定义边界
领域编排留领域；持久读写归既有 owner；**纯 Store 转发不得以「文档写口/生命周期」保留**——调用方直达 Store 后删除方法。`record_person_log` 等**以是否含领域逻辑认**，不以「参数转传=适配」洗白。

### 本轮清退（相对误报 KEEP）
| 成员 | 处置 | 依据 |
|---|---|---|
| `GameDB.append_chat_message` | **删除** | 纯 `chat_messages.insert` + commit；调用方（`web_app`/`cli/terminal`/测试）改 Store |
| `GameDB.clear_month_open_snapshot` | **删除** | 纯 `month_open_snapshots.delete` + commit；`month_open_snapshot.py`/`month_chain.py`/测试直达 |
| `GameDB.record_person_log` | **删除** | 无额外领域逻辑；调用点已内联 `person_logs.append(...)` |

### 修后 `c2_forward`（4）逐项
| 方法 | 处置 | 依据 |
|---|---|---|
| `save_state` | **KEEP** | GameState 字段解包→`reign.save`（领域对象适配，非同参纯转发） |
| `save_resolve_context` | **KEEP** | sanitize / `safe_json_dumps` / Provenance `.value` 归一后写 Store |
| `clear_resolve_context` | **KEEP** | 跨 Store：`resolve_contexts.delete` + `dossiers.clear_pending_promulgation_verdicts` |
| `close` | **KEEP** | 连接关闭框架 |

### 修后 `c2_sql_leak_candidate`（9）
| 位置 | KEEP 依据 |
|---|---|
| `applier.py` RejectionCollector CRUD + sqlite_master | RejectionCollector 即 rejection_reports owner |
| `applier.py` `_SuspendableConnection.executescript` | 连接包装，非事实写口 |
| `db.py` PRAGMA / `_table_exists` / `table_has_rows` | 框架/schema 探测 |
| `web_app.py` `SELECT 1` | 可恢复性探针 |

### 调用方适配（非新机制）
- 生产：`chat_messages.insert` 后仅当 `conn` 为真实连接（`callable(commit) and not callable(conn)`）才 commit——避开轻壳 `__getattr__` stub。
- 轻壳测试：补 `chat_messages.insert` 适配；`reign` 自指以接 `db.reign.agno_runs_length`（Store 迁位后生产读法）。

### 结果
类2：纯转发已删；剩余 4 条有真实领域/框架依据。

---

## 类3 — 被取代的孤立机制

### 定义边界
全仓枚举定义及调用/引用与实际退役关系，不只命中特定符号。

### 枚举
`enum_c3_defs_and_refs`：AST FunctionDef/Assign 名 + Name/Attribute 引用 + 宽文本退役信号；本轮 **21** 行。

### 成员与处置（同依据分组 + 引用）
| 组 | 代表引用 | 处置 | 依据 |
|---|---|---|---|
| 禁摊派中和现役 | `ming_sim/issues.py:7100/7124` defs；`ming_sim/covert_levy.py:109-110` refs | **KEEP** | 票面现役一次性撤销，非孤立遗留 |
| Store `upsert` 原语 | `entities/character/store.py:211`；`record_store.py:177/264` | **KEEP** | 合法现役写原语 |
| 退役说明注释 | `covert_progress.py:801`「满阈自动写依律的旧清算轨已退役」 | **KEEP** | 注释非机制 |
| 测试 `reason_code="依律"` | `tests/test_centrifuge_ledger_690.py:245/501/513` | **KEEP** | 现役字段取值，非复活旧清算轨 |
| 上轮已删符号 | `_fail_cli_chat_turn_scene` / 旧坐实链 / debug upsert | 已清 | 复扫无生产残留 |

### 结果
类3：无应删孤立机制残留；现役职责保留。

---

## 类4 — 人口规则平行实现

### 定义边界
枚举全人口相关函数/常量/计算并查重复，不只二函数。

### 枚举
`enum_c4_population`：定义 + 调用 + 文本 + **duplicate_defs**；本轮 **376** 行（definition 56 / call 12 / duplicate_defs 12 / text_hit 296）。

### 重复名表（duplicate_defs:2）与处置
| 同名 | 位置对 | 处置 | 依据 |
|---|---|---|---|
| `read_due_order_displacement_entries` | army/store.py:171 ↔ region/store.py:155 | **KEEP** | 不同实体 Store 读原语，非第二套领域公式 |
| `read_arrears_order_displacement_entries` | army:174 ↔ region:158 | **KEEP** | 同上 |
| `read_apply_levy_driven_transfers` | region:116 ↔ social_class:92 | **KEEP** | 分表持久读 |
| `read_apply_population_transfers` | region:170 ↔ social_class:111 | **KEEP** | 分表持久读 |
| `read_apply_recovery_driven_transfers` | reign_state:196 ↔ social_class:86 | **KEEP** | 分表持久读 |
| `_global_population` | 两测试 helper | **KEEP** | 测试夹具同名，非生产双份 |

### 领域真源
| 成员 | 处置 | 依据 |
|---|---|---|
| `apply_levy_driven_transfers` / `apply_recovery_driven_transfers` | **KEEP** | 唯一定义在 `displaced_population.py`；月链直调 |
| `LEVY_DISPLACEMENT_RATE` 等 | **KEEP** | 核算参数真源 |
| `apply_issue_inertia_and_ongoing` 等旧双份 | 上轮已删 | 复扫无旧名 |

### 结果
类4：单一领域真源；同名 Store 读口非平行核算。

---

## 类5 — 撤回的事务了结机制

### 定义边界
清退显式了结、拒绝该动作的守门及**专用旧测试**；用户明确：不能保留 attach=close 专用拒收测试并称「普通边界」。已有合法 new/existing 及通用非法输入边界保留，不新增。

### 成员与处置
| 成员 | 处置 | 依据 |
|---|---|---|
| `close_from_declaration` / `declare_closed` / `ATTACH_RESULT_CLOSE` | 已删 | 生产谓词 0 |
| `test_same_name_affairs_are_not_merged_and_birth_close_is_rejected` 中 close 专用拒收块 | **本轮删除** | 改为 `test_same_name_affairs_are_not_merged`；只断言同名不合并且两案仍 open |
| 合法 `attach=new` / `existing` 路径 | **KEEP** | 现役声明边界 |
| `test_new_issue_affair_attach_failure...` `match='attach boom'` | **KEEP** | 测试自注入失败保真（硬规13） |
| `c5_affair_close` 余 1 行 | `ming_sim/materials.py:416` ADR 0154 说明注释 | **KEEP** | 文档叙述，非动作/守门 |
| 夜/案卷 `status='closed'` | **KEEP** | 终态枚举，非事务声明了结 |

### 结果
类5：显式了结与专用 close 拒收案已清；未建自动了结。

---

## 类6 — 测试契约边界处置错误

### 定义边界
AST 枚举**全部** Python 测试 `assert` / `raises(match=)` / 字符串 `Compare`（Eq/NotEq/In/NotIn）及 Web `expect`/`toMatch`/`getByText` 等含字符串者；**不靠汉字≥12 或字段名收窄候选集**。机器记号、测试自注入原文保真、UI 固定按钮/标题可 KEEP（宪法 P7 + 硬规13）；生产叙事/材料标题/报错文案不得锁。

### 枚举（本轮）
- lane：`c6_string_lock` = **18295**（旧 `c6_prose_lock` 谓词过窄已废）
- 形态：assert 9119 / compare 8852 / web_expect 229 / raises_match 82 / struct_scroll_or_aria 13
- 标签（detail 后缀，仅助分拣）：machine 12250；han 1856；han+machine 2815；other/混合其余

### 同依据分组处置（完整引用在 TSV；此处按组）

| 组 | 判据 | 处置 | 代表引用 |
|---|---|---|---|
| A 机器记号 | `status`/`id`/枚举码/`invalid_state`/`off`/`high` 等 | **KEEP** | 大量 `assert|machine` / `web_expect|machine`（见 TSV） |
| B UI 固定 chrome | 按钮/菜单标题（保存并应用、请求头名、撤回召对确认…） | **KEEP** | `gameMenu.test.tsx` aria-label/按钮；`modals` aria；detail `ui_chrome`×11+ |
| C 测试自注入保真 | 同窗 raise/monkeypatch 原文再 match/assert | **KEEP** | `test_faction_brew_637.py:292`；`test_applier_contract.py:127→146`；`raises_match` 注入族 |
| D P4 缺席契约 | `not.toContain` 禁显注入字段 | **KEEP** | `drawers.test.tsx:166-168,193-194,222-224`；`map.test.tsx:144` |
| E 结构化行为 | scrollTop / 存在性 | **KEEP** | `modals.test.tsx` scrollTop 600/700/100/137（struct×13） |
| F 注入圆柜回读 | 测试自备 report/文本再读回 | **KEEP** | `settlementGazettePanel` 注入 report；`staleGuard` fixture「甲的回话」 |
| G 上轮已删措辞锁 | 菜单「关（codex/grok…）」×4；`AGENDA_FROZEN` | 已删 | 复扫 0 |
| H 生产报错/叙事锁 | 非注入的生产 raise 文案 / 材料标题自由文本 | **DELETE 目标** | 本轮对生产 `Raise` 中文串 ∩ 测试 lock 复扫：**非注入命中 0**；无新增 DELETE 行。若后续发现须继续清 |

**不以「谓词 0」代替逐组处置**：全表在 `evidence/1889-six-class-enum.tsv`；上表为同依据分组，组内成员完整位置见该 TSV `class=6`。

### 变异取证（真实入口）

```bash
# 临时注释 chatModal.tsx 中 scrollTop 恢复赋值后：
cd web && npx vitest run --environment jsdom --cache=false src/components/modals.test.tsx
# → 2 failed | 32 passed（expected 600/137 got 0）；日志 /tmp/1889-mutation-scroll.out
# 还原后：34 passed；/tmp/1889-mutation-scroll-restore.out
```

### 结果
类6：全量字符串锁候选已枚举；按宪法/硬规分组处置；结构性 scrollTop 经变异红绿咬合；无收窄扫描洗白。

---

## 聚焦测试（七变量前缀，完整文件列表，无 `-k`）

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false
```

| 批次 | 完整命令 | 实测 |
|---|---|---|
| core | `python3 -m pytest tests/test_new_game_smoke.py tests/test_population_unit_648.py tests/test_population_transfers_649.py tests/test_surcharge_causal_chain_650.py tests/test_affairs_1831.py tests/test_supervision_625.py tests/test_covert_levy_651.py tests/test_pay_order_override_653.py tests/test_section_fiscal_rejections.py tests/test_secret_order_payoff_1504.py tests/test_fiscal_substrate_bridge.py -q --tb=line` | **419 passed**；`real 13.70s`（`/tmp/1889-focus-core.out` + `.time`） |
| more | `python3 -m pytest tests/test_mutiny_actual_residence_659.py tests/test_mutiny_latch_315.py tests/test_mutiny_noop_whitelist_319.py tests/test_mutiny_progression_316.py tests/test_mutiny_redemption_317.py tests/test_mutiny_third_strike_318.py tests/test_player_army_projection_321.py tests/test_month_translate_1840.py tests/test_relation_seed_638.py tests/test_character_knowledge_489.py tests/test_audience_scroll_539.py tests/test_decree_commitment_settlement_229.py tests/test_cli_play_turn.py tests/test_chat_stream_failpaths_393.py tests/test_web_chat_serialization_393.py tests/test_secret_order_isolation_883.py tests/test_month_open_snapshot_1234.py tests/test_person_delta_adapter.py tests/test_enter_settlement_period_1235.py tests/test_qa_c2_settlement_display_lifecycle_1343.py tests/test_menu_lifecycle_drain_396.py tests/test_audience_restore_505.py tests/test_audience_background.py -q --tb=line` | **4 failed, 509 passed**；`real 10.20s`（`/tmp/1889-focus-more.out`） |
| chat | `python3 -m pytest tests/test_web_chat_serialization_393.py tests/test_menu_lifecycle_drain_396.py tests/test_chat_stream_failpaths_393.py -q --tb=line` | **42 passed**；`real 1.88s` |
| web | `cd web && npx vitest run --environment jsdom --cache=false src/components/modals.test.tsx src/components/gameMenu.test.tsx src/components/menuPage.test.tsx src/components/drawers.test.tsx src/components/map.test.tsx src/components/settlementGazettePanel.test.tsx` | **102 passed**；`real 1.25s` |
| scrollTop 变异 | 见上 | 红 2 failed → 绿 34 passed |

### more 批次 4 失败（非本票引入）
均属 `tests/test_cli_play_turn.py` 轻壳缺 `dossiers`（#42 / secret_order 报告路径），例如：
`test_review_issue_reaches_staged_directive_default_approval` → `AttributeError: 'Db' object has no attribute 'dossiers'`。
与本票 Store 转发删除无因果关系；未为洗绿扩改该轻壳。

未跑全量（票面：只跑聚焦）。

---

## 自查二连

1. **合法性**：未改治理；未新建自动了结/证明测试；类2 纯转发已按核查删除；类5 close 专用案已删；类6 全量枚举非 12 字收窄；`diff --check HEAD~2 HEAD` 如实记失败。
2. **引入 bug**：轻壳 `__getattr__` stub 曾使 `conn.commit` 误触——已以「commit 可调用且 conn 不可调用」收紧；`reign`/`insert` 轻壳补齐后 chat/menu 绿；误触 stash 已立即 pop。
3. **边界**：未放松财政分流/人口双份/了结清退；变异证明结构化契约仍咬合。

---

## 剩余范围 / 真实阻断

- 历史 `HEAD~2..HEAD` 的 TSV trailing whitespace 由本提交新 TSV 覆盖修复；旧提交对象本身不改写。
- CLI #42 dossiers 轻壳缺口仍在（非本票范围）。
- 不宣告合并、不关票、不 push、不开 PR。
