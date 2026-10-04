# #1843 修内司回执（w5 / F2-R11 apply 自查再订正）

工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1843-w5`
分支：`ak-roles/issue-1843-w5-r11-f2`
派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a10914-924d-782f-befd-de9d9e61b59b@fixer/fix-packet.md`
末判真源：附件 `03-1843-judge-fab71100c.json` **最后一份 payload**（F2-R11-1 / F2-R11-2）
未 push、未 PR、未 amend、未 stash；未声称合并或关票。

## 顾问审视（动手前）

- CLI `advisor` / `gstack-advisor` **不可用**；**未获得任何外部 advisor 意见**，不得冒称。

## 上轮谓词问题（主席实核；本局如实承认）

上轮 `evidence/1843-w5-fixer-enum_full.py.txt` **并未**按类定义全文覆盖，边界漏洞包括：

1. **无 git 历史删除 diff 消费链**：未从本地全可用历史抽退役结算/simulator 消费者定义及真实删除 diff。
2. **A1** 仅名字 `migrate|backfill|purge` 或固定 `CHASE_SEEDS`。
3. **A3** 仅零引用下划线 helpers（默认当候选，易把夹具壳当退役树）。
4. **A5/A6** 固定种子；互引扩展只在注释、未实现。
5. **资源**只靠文件名关键词；**未扫**根目录 `web_app.py` / `scripts/`。
6. **B** 用 `ENTRY_RE` 固定入口白名单、helper「只私有且无 game」、中文 literal「仅 6 字以上」等作收窄——扩大 regex **不等于**整类修净。
7. 上轮对保留的 164 项多用同一泛称理由（「私有助手+外部可观察」「结构性前缀」），**不足以**当契约证据。
8. 复杂度曾报「约 +568」——与含 evidence 的实际 diff 千余行不符；本局按下节**实际 query** 报告。
9. 上轮补跑日志实为 **1100 passed, 2 skipped, 2 failed**（`test_office_rank_562` 两条）；**不得**称整批已绿。删 reanchor 专属测 + 洗净胡廷宴 seed 后 office_rank 曾 16 passed，但 `test_named_characters_seed_484` 仍咬旧 office 串，属上轮漏测触及面。

本局纠正方法见下；**不**把再扩几个 regex 声明成全文覆盖。

## 未结两类（末判原文边界）

1. **F2-R11-1** 旧结算／simulator 独占支持树与旧档兼容路径漏退役。
2. **F2-R11-2** 非契约文字／内部结构／重复测试未清，并以弱化断言代替行为验证。

## 机械枚举（可复现；临时扫描，非生产机制）

| 用途 | 路径 |
|---|---|
| 枚举命令 | `evidence/1843-w5-fixer-enum-commands.txt` |
| 上轮谓词脚本（已证有边界漏洞，仅对照） | `evidence/1843-w5-fixer-enum_full.py.txt` |
| 本局闭包脚本（/tmp 施工，证据副本） | `evidence/1843-w5-fixer-closure_enum.py.txt` |
| 历史删除 defs | `evidence/1843-w5-fixer-deleted-defs-ae4a2a3e6-HEAD.json`（723 名自 diff；清洗后追 301） |
| 清洗退役名集 | `evidence/1843-w5-fixer-retired-cleaned.txt` |
| pre2 摘要 | `evidence/1843-w5-fixer-pre2-enum-summary.json` |
| 全仓测试完整清单（先枚举再分类） | `/tmp/1843-f2-r12/pre2-all-tests-inventory.tsv`（指针：`evidence/1843-w5-fixer-pre2-all-tests-inventory.tsv.path.txt`；4588 行含表头） |
| 全仓 defs / resources | `/tmp/1843-f2-r12/pre2-all-defs-inventory.tsv`、`evidence/1843-w5-fixer-pre2-all-resources-inventory.tsv` |
| A/B 候选与处置 | `evidence/1843-w5-fixer-pre2-class-a-candidates.tsv`；B 大表指针 `…pre2-class-b-candidates.tsv.path.txt`；处置 `…-class-a-members.tsv` / `…-class-b-members.tsv` |
| 本局删除复扫 | `evidence/1843-w5-fixer-class-b-rescan.tsv`（14 项均为 `DELETED_ABSENT`） |
| 聚焦补测 | `evidence/1843-w5-fixer-pytest-focused.txt`（`*.log` 被 gitignore） |
| 上轮大补跑（含 2 failed） | `evidence/1843-w5-fixer-pytest-missed.txt` |

施工前命令（本局）：

```bash
# git ae4a2a3e6..HEAD 抽删除 defs → retired-cleaned.txt（见 enum-commands.txt）
MING_SIM_*_BIN=/usr/bin/false \
  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python /tmp/1843-f2-r12/closure_enum.py \
  /Users/akagilnc/WorkSpace/Ming_LLM-1843-w5 /tmp/1843-f2-r12 pre2 \
  /tmp/1843-f2-r12/retired-cleaned.txt
```

pre2 摘要实核：`retired_names_input=301`；A CANDIDATE=72 + OOC_PROBE=42；**先**全仓测试清单 `all_test_functions=2865`，再信号分类 B CANDIDATE=581 / OUT_OF_SIGNAL=2284；扫描基座含 `web_app.py`+`scripts/`。

## 逐类处置摘要

### F2-R11-1

沿 `ae4a2a3e6..HEAD` 删除 diff + 前轮 r7 表 / hist-seeds 建退役名集，下行闭包后反核现役入口：

| 成员 | 处置 | 依据 |
|---|---|---|
| 上轮已删 migrate/backfill/purge/旧夹具等 | 维持 | 现行 `ming_sim/db.py` 无 `_migrate_|_backfill_|_purge_` 定义 |
| `_backfill_healed_participant_refs` | RETAIN | cli_backend 现役纠错消费 |
| `save_rescript_drafts` / `_insert_rescript_draft_rows` / `normalize_rescript_layer_a_option` / `decision_has_rescript_capability` / `settle_province_tick` | RETAIN | 末判 LIVE_SEAM / 现役写口 |
| `run_month_end_relation_brew` | RETAIN | Leg 直调便利；mechanical_tail 持 Leg；非旧 simulator |
| `complete_rescript_summon_scaffold_turn` | **OOC_F3** | 零调用，但 `evidence/1843-f2-retirement.md` 已标 F3 邻接；超出 F2 不上删 |
| `ORPHAN_REF::{ARMY_SALARY_PRIORITY,rescript_*,simulator_payload}` | FALSE_POSITIVE | 与现役同名模块/字段碰撞 |
| 零引用下划线 helpers（42） | OOC_PROBE | 默认类外夹具壳；不以零引用当删除充分条件 |
| `content/distance_scale.md` / `maps.txt` | OOC | 非结算独占支持 |
| `characters.json` 胡廷宴 office + `test_named_characters_seed_484` | **FIXED** | seed 已是 `三边总督`+dismissed；测试改咬洗净事实（上轮漏测） |

**不声称** F2-R11-1 已 externally 结清：闭包仍会因同名符号/测试便利入口产生候选噪声；未触达项以消费者理由标类外，不用名字阈值。

### F2-R11-2

在**完整**测试清单上分类后，删除上轮用泛称误保的纯 helper／内部案 14 项（复扫全 `DELETED_ABSENT`）：

- `test_faction_leverage_9`：7 个 `_member_office_weight` / `_office_rank_multiplier` / 权重表锁（保留 `test_weizhongxian_ouster…` 真退场入口）
- `test_non_finite_salary_rate_anchored_not_crash`（纯 coerce/army_needed）
- `test_gate_passed_tolerates_*`、`test_character_numeric_gate_supports_comparison`（直测 `_gate_passed`；保留 gather 入口案）
- `test_is_non_person_covers_generics_and_collectives`（保留 capture / night_archive 入口案）
- `test_provenance_from_stored_recovers_all_forms`
- `test_web_runtime_cli_no_saved_timeout_uses_cli_default`（`_llm_config_from_runtime` 私有）

其余信号命中项按契约逐名 RETAIN（见 `class-b-members.tsv` 的 `final_reason`，不再同一句搪塞）。#1471 HUD 负向维持末判 G1。

**未结承认**：post 复扫 B 信号候选仍约 569（含大量 `unused_game_fixture` / `helper_internal_signal` / 中文结构化断言）；本局只清已核实纯 helper 误保，**不**宣称 B 类 externally 结清。未新增证明性测试或生产扫描机制。

## 复杂度（实际 query，非约数）

相对 `fab71100c`（含未提交工作树）：

```text
git diff --numstat fab71100c | awk '{a+=$1;d+=$2;n++} END{print n,a,d}'
→ paths 67  +2160  -2193
git diff --numstat fab71100c -- . ':(exclude)evidence'
→ paths 55  +146   -2193
```

本轮相对 HEAD 仅触及测试删行约 `+3 / -253`（8 paths）。evidence 变长是枚举诚实化成本；**复杂度下降看生产闭包与误保测试变短**。上轮回执「约 +568」与当时/现在 evidence 千余行不一致，以本 query 为准。

## 聚焦测试

### 上轮大补跑（完整命令；结果含失败——不得称整批绿）

命令见前次回执所列 34 文件批次；实测 `evidence/1843-w5-fixer-pytest-missed.txt`：

```text
2 failed, 1100 passed, 2 skipped in 43.28s
FAILED tests/test_office_rank_562.py::test_rank_rule_offset_reanchor_preserves_existing_save_leverage_once
FAILED tests/test_office_rank_562.py::test_seed_archives_clean_historical_office_for_dismissed_ministers
```

其后同日志尾：`tests/test_office_rank_562.py` → `16 passed in 2.24s`（删 reanchor 测 + 洗净 seed 后）。**其余未改文件不重跑全量**；仅记录该批其余当时通过。

### 本局补测（失败面 + 本轮新触及）

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/test_office_rank_562.py \
  tests/test_named_characters_seed_484.py \
  tests/test_faction_leverage_9.py \
  tests/test_army_salary_44.py \
  tests/test_event_trigger_gate.py \
  tests/test_qa_d1_decree_normalize_1274.py \
  tests/test_rejection_wiring.py \
  tests/test_llm_channel_config.py \
  tests/test_opening_gazette_delete_1356.py
```

实测（`evidence/1843-w5-fixer-pytest-focused.txt`）：**294 passed in 3.50s**（`/usr/bin/time -p` → real 3.94s）。非全量。

## 变异证据

沿用 `evidence/1843-w5-fixer-mutation.json`（上轮装回旧 severity 映射 / startswith 弱断言对照）。本局未再改生产源码装回；本局删除的是已核实纯 helper 测试，变异对照仍指向末判 independentVerification 的同值传递案。

## 进程信号（「杀掉脚本」）

- 本席本轮**未**向任何脚本或 worker 发送信号；**未使用 SIGKILL**；**未杀 worker**。
- 枚举与 pytest 均正常退出（exit 0）。
- 若编排器 stdout 出现「杀掉脚本」，**非本席发出**；本工作树内自建扫描在 `/tmp/1843-f2-r12`，自行跑完，无中断杀除。

## 自查二连

- 同类型：承认上轮谓词边界漏洞；改用历史删除 diff + 全仓清单 + 消费者理由；补删泛称误保的纯 helper；补胡廷宴 seed 测试与洗净 seed 一致。
- 引入 bug：未误删 LIVE_SEAM / F3 邻接 `complete_rescript_summon_scaffold_turn`；未对 OUT_OF_SIGNAL 测试盲删。

## 未结范围（交卷时仍未 externally 结清）

- F2-R11-1：历史同名碰撞与测试便利入口仍产生候选；F3 零调用 scaffold 上呈不删。
- F2-R11-2：完整清单上仍有数百信号候选待逐案契约核；本局只清 14 项已核实误保。
- 不声称大理寺收敛 / 合并 / 关票。

## 最终 commit

- 分支：`ak-roles/issue-1843-w5-r11-f2`
- hash：`4536f4db8d541937b447613353228b8a086bf115`
- 未 push；未合并；未关票。
