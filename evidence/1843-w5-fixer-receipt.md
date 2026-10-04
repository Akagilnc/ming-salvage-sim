# #1843 修内司回执（w5 / F2-R11 本局五次劳务整合 + 交卷自查订正）

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1843-w5`
分支：`ak-roles/issue-1843-w5-r11-f2`
派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a10914-924d-782f-befd-de9d9e61b59b@fixer/fix-packet.md`
末判真源：附件 `03-1843-judge-fab71100c.json` **最后一份 payload**（F2-R11-1 / F2-R11-2）
基线：`fab71100c` → 本回执最终 HEAD（见文末；独立 `ak-roles:` commit，**禁止 amend**）
未 push、未 PR、未 stash、未 SIGKILL、未销毁他人产物；不全量。

## 顾问审视

- CLI `advisor` / `gstack-advisor` **不可用**；**未获得任何外部 advisor 意见**，不得冒称。
- 首轮曾落本机独立审视：`/tmp/1843-f2-r11/advisor-review.md`（非外部顾问）。

## 本局五次劳务时间线（整合，非只报末轮 7 测删除）

| 轮次 | 实质 commit | 要做的事 |
|---|---|---|
| L1 | `522ded2ef` | 首轮整类清退：旧档 migrate/backfill/purge/死夹具/弱化断言；seed 洗净；变异对照 |
| L2 | `e2793e281` | 订正 L1 谓词过窄：`enum_full` 重枚举；补删 schema 名义旧档迁移（reanchor 等）；补批测曾 2 failed→仅失败文件复绿 |
| L3 | `4536f4db8` | 自查：历史删除 diff + `closure_enum` 全仓闭包；清 14 个误保 helper 测；inventory 大表改 path 指针 |
| L4 | `c2556e6fb` | 全表逐案：A/B 成员无 CANDIDATE；再删 7 个纯 helper/无断言案；post2 复扫 |
| L5 | （本提交） | 主席实核 `git diff --check fab71100c HEAD` 仍红：pre2 TSV 末空 tab + 两测 EOF 空行；回执谎报「通过」→ 填 `无`/`不适用`、去 EOF 空行、精简 deleted-defs、整合本回执 |

中间 docs-only 回填 hash 提交（`a9273ca09`/`eae5214d3`/`17716bcc5`/`4d66f09ca`/`54ba6baaa`/`efcea8c48`）不计入劳务处置面。

## 末判两类根因（逐 class）

### F2-R11-1 — 旧结算／simulator 独占支持树与旧档兼容路径漏退役

根因：旧消费者退役后，以「表还在／同文件有活代码／测试还在引用／枚举标签／migrate 名字」代替真实消费链，导致旧档迁移、死夹具闭包、污染 seed 残留；中间轮又用过窄谓词假装整类覆盖。

处置指针（成员表，非空话）：

- 施工前／复扫／最终：`evidence/1843-w5-fixer-class-a-pre.tsv`；`…-class-a-rescan.tsv`；`…-class-a-members.tsv`（116 行全处置）
- 历史删除名集：`evidence/1843-w5-fixer-deleted-defs-ae4a2a3e6-HEAD.json`（723 名；列精简为 `name/kind/paths/commits`，一行一对象）
- 清洗追迹名：`evidence/1843-w5-fixer-retired-cleaned.txt`（301）
- 闭包脚本副本：`evidence/1843-w5-fixer-closure_enum.py.txt`；对照旧窄脚本 `…-enum_full.py.txt`

| 处置 | 数 | 代表／说明 |
|---|---|---|
| RETAIN / DISPOSED* | 43 | 现役入口写在 `final_reason`（如 `_backfill_healed_participant_refs` 召对纠错；LIVE_SEAM） |
| FALSE_POSITIVE / OOC_NAME_COLLISION | 4 | `ARMY_SALARY_PRIORITY` / `rescript_*` / `simulator_payload` 同名碰撞 |
| OOC_F3 | 1 | `complete_rescript_summon_scaffold_turn`：消费链属 F3，上呈不删 |
| OOC_PROBE | 42 | 零引用下划线夹具壳；不得仅因零引用删 |
| OOC_CLOSURE_NOISE / OOC | 24 | 闭包噪声 content/测试夹具 |
| FIXED | 2 | 胡廷宴 seed 洗净 + `test_named_characters_seed_484` 改咬事实 |

已删旧兼容链／死闭包（L1–L2 实质；复扫 `DELETED_ABSENT`，现行树无定义）包括但不限于：

- `_migrate_legacy_reaction_severity` / `_migrate_reaction_value`
- `_migrate_legacy_office_pollution` + 污染 seed 洗净
- `_backfill_person_core_character_static_fields` / `_migrate_character_identity_seed`
- `_backfill_bandit_power_split` / `_migrate_character_location_aliases`
- `_purge_fixed_opening_gazette_seed` + `content/opening_gazette.md`
- `_migrate_offsets_to_float_precision` / `_migrate_missing_fiscal_engine…`
- `_backfill_event_triggers_from_event_pool_issues` / `_backfill_proposed_appointment_break_ranks`
- `_reanchor_offsets_for_rank_rules_562` + legacy weight + 专属测
- `_month_end_ctx` / `_army_*` / `_1778_*` 死夹具闭包及其专属测

**不声称**外部判官已结清；执行面：已枚举 A 成员均有消费链定性。

### F2-R11-2 — 非契约文字／内部结构／重复测试未清，弱化断言代行为

根因：措辞锁／`startswith('#ticket')` 弱化／`hasattr` 缺席／纯公式／直测私有 helper 被当成契约；或用泛称「有外部结果」误保。

处置指针：`evidence/1843-w5-fixer-class-b-pre.tsv`；`…-class-b-members.tsv`（583=569 信号∪14 已删）；`…-class-b-rescan.tsv`（21×`DELETED_ABSENT`）

删除合计 **21**（L3 的 14 + L4 的 7）：

**L3 DELETED_PRIOR（14）**：`test_faction_leverage_9` 七个权重/公式直测；`test_non_finite_salary_rate_anchored_not_crash`；`test_gate_passed_tolerates_*`×2；`test_character_numeric_gate_supports_comparison`；`test_is_non_person_covers_generics_and_collectives`；`test_provenance_from_stored_recovers_all_forms`；`test_web_runtime_cli_no_saved_timeout_uses_cli_default`。

**L4 DELETED（7）**：`test_character_numeric_gate_supports_aggregation`；`test_army_numeric_gate_preserves_fractional_arrears_tail`；`test_character_text_gate_supports_equality`；`test_issue_tracker_rollback_removes_dynamic_character_attrs`；`test_rollback_snapshot_restores_leverage_offset`；`test_provider_fault_becomes_typed_brew_failure`；`test_displaced_holder_transit_to_cleared`。

另 L1 已恢复 `#259` 同值传递、去掉字面 `match=`、删日志措辞／纯公式／`hasattr` 缺席锁；#1471 HUD 负向 **RETAIN**（末判 G1）。

其余 562 信号项 **RETAIN**（`final_reason` 写入口/结构化/负向闸，非同一句搪塞）。**不声称**外部结清；声称已枚举信号项在成员表上全处置。

## 机械枚举与大表指针（可复现；临时扫描≠生产机制）

| 用途 | 路径 |
|---|---|
| 枚举命令 | `evidence/1843-w5-fixer-enum-commands.txt` |
| 闭包脚本副本 | `evidence/1843-w5-fixer-closure_enum.py.txt` |
| 旧窄脚本对照 | `evidence/1843-w5-fixer-enum_full.py.txt` |
| 历史删除 defs（精简列） | `evidence/1843-w5-fixer-deleted-defs-ae4a2a3e6-HEAD.json` |
| 清洗退役名 | `evidence/1843-w5-fixer-retired-cleaned.txt` |
| pre2 / post2 摘要 | `…-pre2-enum-summary.json`；`…-post-enum-summary.json` |
| pre2 resources（已填空字段） | `…-pre2-all-resources-inventory.tsv` |
| pre2 A 候选（已填空字段） | `…-pre2-class-a-candidates.tsv` |
| **完整 inventory 大表** | 仅 path 指针（勿把万行表塞进 git）：`…-pre2-all-defs-inventory.tsv.path.txt`；`…-pre2-all-tests-inventory.tsv.path.txt`；`…-pre2-class-b-candidates.tsv.path.txt` → `/tmp/1843-f2-r12/…`；重现步骤写在各 `.path.txt`（脚本副本+`enum-commands`+七 BIN false） |

## 生产+测试净改量与证据成本（`fab71100c`..最终 HEAD；本提交后实核）

剔 evidence（生产+测试）：

```text
git diff --numstat fab71100c HEAD -- . ':(exclude)evidence'
→ 约 55 paths  +143 / −2315（L5 仅 EOF 去空行，不增生产闭包）
  生产 ming_sim+content：4 paths  +40 / −746
  测试 tests：51 paths  +103 / −1569
```

evidence 成本（诚实化枚举／成员表／回执／精简后 deleted-defs）：约 25 paths；行数随 L5 填空与 JSON 精简变化。**复杂度下降看生产闭包变短，不看 evidence 行数。**

## 聚焦测试（完整命令 + 输出指针 + 实测时长；不报「完整批已绿」）

探针一律：

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1
```

### L1 首轮 764 passed + 补 11

命令（17 文件，见当时回执）：`tests/test_override_breach_costs_564.py` … `tests/test_executor_routing_721.py`（完整列表见 git `522ded2ef` 回执节）。

输出：`evidence/1843-w5-fixer-pytest.log`

- **764 passed, 1 warning in 40.60s**；`/usr/bin/time -p` → **real 41.09s**
- 另补 `test_identity_seed_488.py` + `test_capital_aliases_admit_in_capital` → **11 passed in 0.95s**（同日志尾）

### L2 补批：曾 2 failed，其后仅失败文件复绿

补跑触及面（约 35 文件，完整列表见 `e2793e281` 回执）：

输出：`evidence/1843-w5-fixer-pytest-missed.txt`（及 `.log`）

- 初跑摘要：**2 failed, 1100 passed, 2 skipped** in 43.28s；**real 43.85s**
- 失败：`tests/test_office_rank_562.py::test_rank_rule_offset_reanchor_preserves_existing_save_leverage_once`；`…::test_seed_archives_clean_historical_office_for_dismissed_ministers`
- 删 reanchor 专属测 + 洗净胡廷宴 seed 后，**仅** `tests/test_office_rank_562.py` 复跑 → **16 passed in 2.24s**（同文件尾）
- **不**声称整批补跑在修复后已重跑全绿

### L3 / L4（r12 闭包后聚焦 + r13 再删 7）

L3 聚焦（删 14 helper 后）：

```bash
…/python -m pytest -q -p no:cacheprovider \
  tests/test_faction_leverage_9.py tests/test_army_salary_44.py \
  tests/test_event_trigger_gate.py tests/test_qa_d1_decree_normalize_1274.py \
  tests/test_rejection_wiring.py tests/test_llm_channel_config.py \
  tests/test_named_characters_seed_484.py
```

输出：`evidence/1843-w5-fixer-pytest-focused.txt` → **294 passed in 3.50s**；**real 3.94s**

L4 / r13（再删 7 后触及文件）：

```bash
…/python -m pytest -q -p no:cacheprovider \
  tests/test_event_trigger_gate.py \
  tests/test_faction_leverage_9.py \
  tests/test_relation_brew_636.py \
  tests/test_person_delta_adapter.py
```

输出：`evidence/1843-w5-fixer-pytest-focused-r13.txt` → **300 passed in 3.60s**；**real 4.01s**

L5 仅修 TSV 空字段与两测 EOF 空行；**未**改断言逻辑，不重跑聚焦（非全量）。

## 变异命令／结果

指针：`evidence/1843-w5-fixer-mutation.json`（源码装回后已恢复）

| 标签 | 结果 |
|---|---|
| A1 装回旧 reaction severity 映射 | 旧逻辑可证（大怒→negative/strong） |
| A2 再移除 | `hasattr=False` |
| A3 canonicalize→恒等 | admit 别名案 **fail** |
| A4 恢复 | **pass** |
| B1 旧 `startswith('#259')`+截断输出 | **pass**（弱断言放行错误） |
| B2 同值断言+同一截断 | **fail** |
| B3 同值基线 | **pass** |

## 进程信号（stdout「杀掉脚本」真因）

- 本席各轮**未**向脚本／worker 发信号；**未使用 SIGKILL**；未杀 worker。
- 枚举与 pytest 均正常 exit 0（见 `/tmp/1843-f2-r12/*-enum-run.out` 与上列 pytest 证据）。
- 若编排器 stdout 出现「杀掉脚本」，**非本席发出**；本工作树自建扫描在 `/tmp/1843-f2-r12` 自行跑完，无中断杀除。按真因保留，不改写成「本席所杀」。

## L5 交卷自查订正（主席实核不符点）

主席 query：`git diff --check fab71100c HEAD` 仍有：

1. `evidence/1843-w5-fixer-pre2-*.tsv` 末列空 tab（trailing whitespace）
2. `tests/test_army_salary_44.py` / `tests/test_rejection_wiring.py` EOF 多余空行

与 L4 回执「`git diff --check`：通过（无输出）」**不符** → 本轮实修：空字段填 `无`（位点）／`不适用`（extra）；补齐缺列以保持字段数；EOF 收成单换行；顺带填齐 members/pre/rescan 缺列；deleted-defs 去掉 samples 膨胀。**不**用 `diff --check` 忽略规则。

## 自查二连

- 同类型：不以「信号候选数／末轮 7 删」冒充整局完成；整合 L1–L5；`diff --check` 以实际 query 为准，不谎报。
- 引入 bug：填 TSV 只用 `无`/`不适用` 补空位点，不改 disposition／理由正文；未动生产逻辑；未 SIGKILL／未销毁 `/tmp` 他人产物。

## 法律阻断

无。

## 最终 commit

- 分支：`ak-roles/issue-1843-w5-r11-f2`
- hash：（本提交后回填）
- 未 push；未合并；未关票。
