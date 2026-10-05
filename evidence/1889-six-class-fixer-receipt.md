# #1889 六类修内司回执（SIGTERM 续完 · 交卷闸更正）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1889-w5r`
- 施工分支：`ak-roles/1889-six-class-fixer`
- 判词真源：`…/attachments/04-1889-judge-00aff8316.json` → `outcome.payloads` **末份**
- 相对开工基线：`00aff8316`；前序实体提交：`684919d60` / `8e77a2b46` / `23a761a8a`
- 本轮：宿主 SIGTERM 后续完；**交卷闸=回执诚实性 + 测试质量自查**（不新增全绿/行数门槛）
- 约束：无 amend / rebase / stash / push / PR；七变量 BIN=`/usr/bin/false`；只跑聚焦且**不得 `-k`**；不新建证明测试/护栏/兼容；不改角色包或全局交卷工具

---

## 交卷闸更正（本轮要点）

| 更正项 | 事实 | 处置 |
|---|---|---|
| 枚举表行号过期 | `HEAD` 入库的 `evidence/1889-six-class-enum.tsv` 相对现行代码行号偏 1（如 `test_menu_lifecycle_drain_396` assert 记 609，现行 610） | **本轮重生成**并入库；`git diff --check` 对工作树 TSV = clean |
| 不以命中 0 冒称全清 | 六类 lane 仍有候选（见下表）；须语义逐项/分组处置 | 本轮对 c1–c5 全列、c6 全量 + han_only 语义审；**不**写「谓词 0=清净」 |
| 类5 close 专用拒收 | 用户明确禁「attach=close 专用拒收」换形保留 | 复扫 `close_from_declaration` / `ATTACH_RESULT_CLOSE` / `birth_close` / `attach=close` = **0** |
| 类6 自由文本锁 | 须语义审，不能只扫生产 Raise∩match | 本轮补：Raise∩raises_match=0；AGENDA/菜单措辞锁=0；han_only 1878 按组 KEEP（见类6） |
| 全绿/行数门槛 | 违法处方已撤 | **未**新增；more 批 4 红如实记，不为绿扩改 CLI 轻壳 |

过程史：曾误触 stash 已在 `23a761a` 前回执声明并立即 pop；本轮未 stash。

---

## 可复跑枚举（完整命令）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1889-w5r
python3 scripts/1889_six_class_enumerate.py --out evidence/1889-six-class-enum.tsv
# 本轮实测：real 8.15s（/tmp/1889-enum-fresh.err）；rows=19570
python3 scripts/1889_six_class_enumerate.py --leaks-only --out /tmp/1889-leaks.tsv
python3 scripts/1889_six_class_enumerate.py --class 1
python3 scripts/1889_six_class_enumerate.py --class 2 --leaks-only
python3 scripts/1889_six_class_enumerate.py --class 3,4,5,6
```

脚本：`scripts/1889_six_class_enumerate.py`（snip/行写 `.rstrip()`，防 TSV 截断尾空白）。
全量表：`evidence/1889-six-class-enum.tsv`（本轮相对 `23a761a` 重生成）。

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

### `git diff --check` 实测

```bash
git diff --check HEAD~3 HEAD   # 本轮：无输出；exit=0（用户开工条件亦同）
git diff --check               # 工作树含新 TSV：exit=0
```

历史：`HEAD~2..HEAD`（`8e77a2b..23a761a` 前）曾因旧 TSV 尾空白失败——已在 `23a761a` 回执如实记载；**不得**回写为 clean。

---

## 类1 — 退役财政分流

### 定义边界
删除退役公式、标记及 shadow 平行路径和仅为它们存在的测试；复用现役 hub；不增加兼容或护栏。

### 成员与处置（全 6 行）
| 成员 | 位置 | 处置 | 依据 |
|---|---|---|---|
| 注释「hub-only: cutover markers retired」×6 | `tests/test_mutiny_*.py` / `test_player_army_projection_321.py` | **KEEP** | 仅文档注释；生产 cutover 谓词 0 |
| `calc_province_fiscal` / 切换标记读写 / 无标记跳过坏省 | （前序已删） | 已清 | 复扫生产路径无分流选择 |

### 结果
无残留退役分流**实现**；6 条注释 KEEP。不以「命中 6」或「命中 0」单边洗白。

---

## 类2 — 持久职责泄漏与重复实现

### 定义边界
领域编排留领域；持久读写归既有 owner。合并双份 SQL，清退纯转发，调用方直接使用现有 Store。

### `c2_forward`（4）逐项
| 方法 | 处置 | 依据 |
|---|---|---|
| `save_state` | **KEEP** | GameState 字段解包→`reign.save`（领域对象适配） |
| `save_resolve_context` | **KEEP** | sanitize / `safe_json_dumps` / Provenance `.value` 归一后写 Store |
| `clear_resolve_context` | **KEEP** | 跨 Store：`resolve_contexts.delete` + `dossiers.clear_pending_promulgation_verdicts` |
| `close` | **KEEP** | 连接关闭框架 |

前序已删纯转发：`append_chat_message` / `clear_month_open_snapshot` / `record_person_log`（不得以「文档写口」保留）。

### `c2_sql_leak_candidate`（9）逐项
| 位置 | KEEP 依据 |
|---|---|
| `applier.py` RejectionCollector CRUD + sqlite_master | RejectionCollector 即 rejection_reports owner |
| `applier.py` `_SuspendableConnection.executescript` | 连接包装，非事实写口 |
| `db.py` PRAGMA / `_table_exists` / `table_has_rows` | 框架/schema 探测 |
| `web_app.py` `SELECT 1` | 可恢复性探针 |

判词样本复扫：`flows` 容器写已走 `FiscalContainerStore.replace/add`；`army_pay`/`situation_drift` 无裸事实 SQL；监督史走 `dossiers.presence_rows`。

### 结果
纯转发已删；剩余 4 forward + 9 leak_candidate 均有框架/owner/适配依据。

---

## 类3 — 被取代的孤立机制

### 定义边界
依据实际退役关系清退遗留辅助链、专用读写及测试；不能仅因未引用而删除仍属票面职责的待接接口。

### 成员与处置（21 行同依据分组）
| 组 | 代表 | 处置 | 依据 |
|---|---|---|---|
| 禁摊派中和现役 | `issues.py` `neutralize_covert_fiscal_effects`；`covert_levy.py` 调用 | **KEEP** | 票面现役一次性撤销 |
| Store `upsert` 原语 | character/record store | **KEEP** | 合法现役写原语 |
| 退役说明注释 | `covert_progress.py:801` | **KEEP** | 注释非机制 |
| 测试 `reason_code="依律"` | `test_centrifuge_ledger_690.py` | **KEEP** | 现役字段取值 |
| `_fail_cli_chat_turn_scene` / debug upsert / 旧坐实链 | — | 已清 | 复扫生产残留 0 |

### 结果
无应删孤立机制残留；现役职责保留。

---

## 类4 — 人口规则平行实现

### 定义边界
保留一个现役领域真源，删除复制件、旧名兼容路径及只维系它们的测试，保留真实世界核算。

### 枚举
definition / call / text_hit / **duplicate_defs**；本轮 **376** 行。

### 重复名表（duplicate_defs）与处置
| 同名 | 位置对 | 处置 | 依据 |
|---|---|---|---|
| `read_due_order_displacement_entries` 等 5 对 Store 读口 | army/region/social_class/reign_state | **KEEP** | 分表持久读，非第二套领域公式 |
| `_global_population` | 两测试 helper | **KEEP** | 测试夹具同名 |

领域真源：`displaced_population.apply_levy_driven_transfers` / `apply_recovery_driven_transfers` 唯一定义；`apply_issue_inertia_and_ongoing` 复扫 0。

### 结果
单一领域真源；同名 Store 读口非平行核算。

---

## 类5 — 撤回的事务了结机制

### 定义边界
清退显式了结、拒绝该动作的守门及**专用旧测试**；不借修理新建自动了结。

### 成员与处置
| 成员 | 处置 | 依据 |
|---|---|---|
| `close_from_declaration` / `declare_closed` / `ATTACH_RESULT_CLOSE` | 已删 | 生产谓词 0 |
| close 专用拒收块（原 `birth_close_is_rejected`） | 已删（`23a761a`） | 改为同名不合并且仍 open；**不**换形保留 close 拒收 |
| 合法 `attach=new` / `existing` | **KEEP** | 现役声明边界 |
| `match='attach boom'` | **KEEP** | 测试自注入（硬规13） |
| `c5_affair_close` 余 1：`materials.py:416` ADR 说明 | **KEEP** | 文档叙述，非动作/守门 |
| 夜/案卷 `status='closed'` | **KEEP** | 终态枚举，非事务声明了结 |

### 结果
显式了结与专用 close 拒收案已清；未建自动了结。

---

## 类6 — 测试契约边界处置错误

### 定义边界
复用已有最短行为用例承接必要结构化结果，清理非契约叙事锁和重复成本。不得靠删掉仍生效契约洗绿，不恢复措辞锁，不新增证明性测试。

### 枚举（本轮，未按汉字长度收窄）
- lane：`c6_string_lock` = **18295**
- 形态：assert 9119 / compare 8852 / web_expect 229 / raises_match 82 / struct_scroll_or_aria 13
- 标签聚合：machine_only 12796；han+machine 2928；han_only 1878；other 668；ui_chrome 12；struct 13

### 本轮语义审方法（补完，非「命中 0」）
1. 全表入库 `evidence/1889-six-class-enum.tsv`（位置真源）。
2. `raises_match` 字面 ∩ 生产 `Raise` 常量中文串：**0**（82 条均为测试自注入或机器记号）。
3. 残留探针：`AGENDA_FROZEN` / 菜单「关（codex|…）」/ `attach=close` / `close_from_declaration` / `birth_close` = **0**。
4. han_only 1878：按组 KEEP（完整 location 见 TSV）；长汉字候选 65 条人工抽查——注入回读、领域键/官职/人名、路径前缀、种子夹具，**无新增 DELETE**。

### 同依据分组处置

| 组 | 判据 | 处置 | 代表 |
|---|---|---|---|
| A 机器记号 | status/id/枚举/`invalid_state` 等 | **KEEP** | 大量 `assert\|machine` |
| B UI 固定 chrome | 按钮/菜单/aria（P7 界面固定话语） | **KEEP** | gameMenu/modals aria |
| C 测试自注入保真 | 同窗 raise/monkeypatch 原文再 match | **KEEP** | `test_faction_brew_637` 派系库不可写；`attach boom` |
| D P4 缺席契约 | `not.toContain` 禁显注入字段 | **KEEP** | drawers/map |
| E 结构化行为 | scrollTop / 存在性 | **KEEP** | modals scrollTop 600/700/100/137 |
| F 注入圆柜回读 | 测试自备 report/对话再读回 | **KEEP** | settlementGazettePanel；audience_continuous |
| G 上轮已删措辞锁 | 菜单关后端；AGENDA_FROZEN | 已删 | 复扫 0 |
| H 生产报错/叙事锁 | 非注入生产文案 | **本轮无新增 DELETE** | Raise∩match=0；长文抽查无生产生成措辞锁 |

**不以「谓词 0」代替逐组处置**：全表在 TSV；上表为同依据分组。

### 变异取证（真实入口）

```bash
# 临时注释 chatModal.tsx 两处 scrollTop 恢复赋值后：
npx --prefix web vitest run --environment jsdom --cache=false web/src/components/modals.test.tsx
# → 2 failed | 32 passed（expected 600/137 got 0）；/tmp/1889-mutation-scroll.out；real 1.08s
# git checkout -- web/src/components/chatModal.tsx 后：
# → 34 passed；/tmp/1889-mutation-scroll-restore.out；real 1.31s
```

### 结果
全量字符串锁候选已枚举并分组处置；结构化 scrollTop 经变异红绿咬合；本轮无新增措辞锁 DELETE（前序已清目标样本）。

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
| core | `python3 -m pytest tests/test_new_game_smoke.py tests/test_population_unit_648.py tests/test_population_transfers_649.py tests/test_surcharge_causal_chain_650.py tests/test_affairs_1831.py tests/test_supervision_625.py tests/test_covert_levy_651.py tests/test_pay_order_override_653.py tests/test_section_fiscal_rejections.py tests/test_secret_order_payoff_1504.py tests/test_fiscal_substrate_bridge.py -q --tb=line` | **419 passed**；real 17.27s（`/tmp/1889-focus-core.out`） |
| more | `python3 -m pytest tests/test_mutiny_actual_residence_659.py tests/test_mutiny_latch_315.py tests/test_mutiny_noop_whitelist_319.py tests/test_mutiny_progression_316.py tests/test_mutiny_redemption_317.py tests/test_mutiny_third_strike_318.py tests/test_player_army_projection_321.py tests/test_month_translate_1840.py tests/test_relation_seed_638.py tests/test_character_knowledge_489.py tests/test_audience_scroll_539.py tests/test_decree_commitment_settlement_229.py tests/test_cli_play_turn.py tests/test_chat_stream_failpaths_393.py tests/test_web_chat_serialization_393.py tests/test_secret_order_isolation_883.py tests/test_month_open_snapshot_1234.py tests/test_person_delta_adapter.py tests/test_enter_settlement_period_1235.py tests/test_qa_c2_settlement_display_lifecycle_1343.py tests/test_menu_lifecycle_drain_396.py tests/test_audience_restore_505.py tests/test_audience_background.py -q --tb=line` | **4 failed, 509 passed**；real 13.46s（`/tmp/1889-focus-more.out`） |
| chat | `python3 -m pytest tests/test_web_chat_serialization_393.py tests/test_menu_lifecycle_drain_396.py tests/test_chat_stream_failpaths_393.py -q --tb=line` | **42 passed**；real 2.49s |
| web | `cd web && npx vitest run --environment jsdom --cache=false src/components/modals.test.tsx src/components/gameMenu.test.tsx src/components/menuPage.test.tsx src/components/drawers.test.tsx src/components/map.test.tsx src/components/settlementGazettePanel.test.tsx` | **102 passed**；real 1.76s |
| scrollTop 变异 | 见上 | 红 2 failed → 绿 34 passed |

### more 批次 4 失败（非本票引入）
均属 `tests/test_cli_play_turn.py` 轻壳缺 `dossiers`（#42 / secret_order 报告路径）。未为洗绿扩改该轻壳；红灯记入未结范围（#1812/#1873 口径：功能红不阻架构清退收敛）。

未跑全量。

---

## 自查二连

1. **合法性**：未改治理/角色包/交卷工具；未新建自动了结/证明测试/行数或全绿门槛；类5 close 专用案未复活；类6 全量枚举 + 语义分组；TSV 行号与 `diff --check` 如实。
2. **引入 bug**：本轮仅证据/回执；变异后已还原 `chatModal.tsx`；工作树无生产代码脏写。
3. **边界**：未放松财政分流/人口双份/了结清退；结构化契约经变异仍咬合。

---

## 剩余范围 / 真实阻断

- CLI #42 dossiers 轻壳缺口仍在（非本票为绿扩面）。
- 整体复杂度对比仍归 #1812 / owner 家族收尾。
- 不宣告合并、不关票、不 push、不开 PR。
