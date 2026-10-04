# #1834 修内司回执：F9 / F12 / F3（全仓枚举补齐）

依据：fix-packet + 冻结判词 `00-1834-judge-52809cdf3.json`；现行 #1834 / #1812；ADR 0143、0155；质量法 #13。
本轮针对自验缺口：旧报告 F3 枚举为空 Python 占位、F9/F12 只扫点名文件——已换成可执行全仓脚本 + 结构探针。
未 push / PR / amend / stash；未改 Soul / 宪法 / 宿主配置。**未合并，不声称关票。**

## 三类根因（判词）

1. **F9** 案卷 `_dossier_row` 解码后的 `payload`（含 `ongoing_effects.人物变更[].loyalty`）整行进公共/世界材料。
2. **F12** `list_world_effect_history` 新增 `person_logs` 等整行审计转储，仅按行上来源过滤，密令私密 reason 仍进公共作者目录。
3. **F3** 测试对人读自由正文做机械依赖（`in` / `==` / `len` / 非空 / `toContain`）。

## 修法

- F9：`_DOSSIER_MATERIAL_SKIP = {office_archive_keys, payload, stigma, execution_signal}`（生产已在 `fc08d7713`；本轮复核）。
- F12：`list_world_effect_history` 删除 audit/`*_logs` 整行转储；保留实况轨 + affair issues/characters/边事件。
- F3：删材料读口正文成员断言；本轮补漏 `test_on_scene_immediate_write_1839` / `test_audience_translate_1837_reopen`；`assert petition_paths` **保留**（见下，非正文非空）。

## 可执行全仓枚举（真源脚本）

七变量前缀 + `PYTHONDONTWRITEBYTECODE=1` + `PYTHONPATH=$PWD` + `../Ming_LLM/.venv/bin/python`。

```sh
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD"

../Ming_LLM/.venv/bin/python evidence/1834-fixer-f9-f12-f3/scripts/enum_f9_material_payload.py \
  | tee evidence/1834-fixer-f9-f12-f3/enum_f9.txt
../Ming_LLM/.venv/bin/python evidence/1834-fixer-f9-f12-f3/scripts/enum_f12_history_dump.py \
  | tee evidence/1834-fixer-f9-f12-f3/enum_f12.txt
../Ming_LLM/.venv/bin/python evidence/1834-fixer-f9-f12-f3/scripts/enum_f3_free_text_asserts.py \
  | tee evidence/1834-fixer-f9-f12-f3/enum_f3.txt
```

复扫摘要：`evidence/1834-fixer-f9-f12-f3/rescan.txt`
原始全量命中：`enum_f9.txt` / `enum_f12.txt` / `enum_f3.txt`（人工分类，**禁止粗正则批删**）。

| 轴 | STRUCT / 计数 |
| --- | --- |
| F9 | `dossier.items_dump=PRESENT`；`_DOSSIER_MATERIAL_SKIP_has_payload_stigma_signal=YES`；HIT=70 |
| F12 | `list_world_effect_history_audit_dump_loop=ABSENT`；keeps=`实况轨,issues,characters,relation_edge_events`；HIT=142 |
| F3 | `MATERIAL_BODY_POSITIVE_COUNT=0`（材料读口正文正向 `in` 已空）；全仓 HIT=1178（宽枚举待分类库存） |

## 完整成员表

### F9（材料供料边界）

| 成员 | 处置 | 证据 |
| --- | --- | --- |
| `materials.py` `dossier.items()` → `payload` | 删除（skip） | 判词样本；STRUCT skip 含 payload |
| 同上 `stigma` / `execution_signal` | 删除（skip） | 同形解码机器载荷 |
| `office_archive_keys` + `*_json` | 保留既有排除 | 上轮已有 |
| `participant_roster` 等结构字段 | 保留 | 非六轴裸值机器载荷 |
| `revoke_target_facts` 读 payload 抽键 | 排除 | 非材料目录供料转储（enum 可见但非 `_write_world_tree`） |
| DB `create_decree_dossier` / 引擎读写 payload | 排除 | 账本真源 |
| 其它 `action_materialize`/`covert_*` payload | 排除 | 落账/候选，非玩家面材料投影 |

### F12（历史转储边界）

| 成员 | 处置 | 证据 |
| --- | --- | --- |
| `list_world_effect_history` → `person_logs` | 删除转储 | STRUCT dump_loop=ABSENT；探针 `--old-f12` 红 |
| 同上 `army/building/power/region_logs` 等 | 删除转储 | 同提交删除 |
| dossier 附属 office/authority/cost/loophole/supervision | 删除转储 | 同上 |
| `实况轨` + affair `issues`/`characters`/`relation_edge_events` | 保留 | STRUCT keeps=… |
| DB 表本身 / INSERT / CREATE | 排除 | 账本留痕≠材料供料 |
| 四类文字事实公共读侧 | 不施工 | #1873 |

### F3（人读自由正文机械依赖）

**已删（材料读口正文成员 / 判词同类）**

| 成员 | 处置 |
| --- | --- |
| `test_month_chain_1847` `fact_body in carrier` | 删；留路径 + `read_material` 可达 |
| `test_gazette_author_1862` 正文 `in author_files[...]` / `_REPORT in text` | 删；改路径成员；`archive[title/report]==` 保留 |
| `test_material_directory_1830` `original in read_material` | 删；留读口调用 |
| `test_public_projection_consistency_1830` 散文子串三通道 | 删；改 `disk==direct==api` |
| `test_fiscal_levy_effect` 请旨正文子串 | 删正文 `in`；**保留** `assert petition_paths`（见下） |
| Web 邸报/局势判词样本正向 toContain | 上轮已删 |
| `test_on_scene_immediate_write_1839` `arm_injury/death_rumour in read_material` | **本轮删**；留路径成员 + 读口；DB `facts[0].body ==` / saying body 保留（结构化字段搬运） |
| `test_audience_translate_1837_reopen` `query in read_material` | **本轮删**；留路径 + 读口；知识事件 `body == query` 保留（结构化字段） |

**`assert petition_paths` 说明（非「换成非空正文」）**

`tests/test_fiscal_levy_effect.py` 在删「边饷急迫…」「姑候户部再核」正文子串后，改为：

- `petition_paths = [请旨目录下非 INDEX 的 *.txt]`
- `assert petition_paths` = **路径列表非空**（目录结构契约）
- 随后 `path.read_text(...)` 只证明可读，**不**断言正文内容 / `len(text)` / 哨兵

结构化 `presented["presented_context"]` / `emperor_note` 字段相等仍保留。报告**不**声称「全文断言已全删」——只声称材料读口正文正向成员已清（`MATERIAL_BODY_POSITIVE_COUNT=0`）。

**宽枚举后排除（需证据；未批删）**

| 类 | 例 | 理由 |
| --- | --- | --- |
| 结构化字段精确搬运 | `archive["report"] == _REPORT`；`presented_*`；`facts[0].body ==`；`progress_band == "顺利"` | 字段相等≠材料散文子串 |
| 路径成员 | `fact_rel in author_files`；`rel in list_materials` | 结构路径 |
| 权限/非泄漏负向 | `not toContain(MIDCOURSE…)`；`seed_status not in blob` | 负向契约 |
| UI 固定木牌 | `settlementFaces`「邸报」「上月抄报」 | P7 界面话语例外 |
| 结构化身份接线 | `modals`/`appDurableWiring` `toContain("杨嗣昌")` 发言人 | 身份点名≠邸报正文契约 |

**宽枚举剩余库存（不声称本片清零）**

`enum_f3.txt` 仍有大量 `assert_in_prose` / `assert_eq_prose` / `vitest_pos_prose*`（召对对话夹具、CLI 输出、错误串、投影定性句等）。按「禁止粗正则批删」只建档分类；**不**在本片一次性铲除。材料读口正向正文成员已空；其余属质量法长尾，另跟踪。

## 结构探针（非自动测试）

脚本（已入库，可复核）：`evidence/1834-fixer-f9-f12-f3/scripts/probe_f9_f12_structural.py`
核的是**结构边界**（材料字段头 `payload：`/`stigma：`/`execution_signal：`；`list_world_effect_history` 有无 `person_logs`；开放/关闭/恢复三态目录），**不**盯自由文本 reason 哨兵。

```sh
../Ming_LLM/.venv/bin/python evidence/1834-fixer-f9-f12-f3/scripts/probe_f9_f12_structural.py
../Ming_LLM/.venv/bin/python evidence/1834-fixer-f9-f12-f3/scripts/probe_f9_f12_structural.py --old
../Ming_LLM/.venv/bin/python evidence/1834-fixer-f9-f12-f3/scripts/probe_f9_f12_structural.py --old-f12
```

| 运行 | 结果（见 `probe.txt`） |
| --- | --- |
| current 开放/关闭/恢复 × 世界+公共作者 | `ALL_GREEN`（各态 279 files） |
| `--old` 恢复 payload 进材料 | `OLD_LOGIC_RED … machine field header 'payload：'` |
| `--old-f12` 恢复 person_logs 转储 | `F12_OLD_LOGIC_RED … dumps ['person_logs']` |

## 聚焦测试

```sh
../Ming_LLM/.venv/bin/python -m pytest \
  tests/test_world_materials_1834.py tests/test_candidate_supply_1893.py \
  tests/test_faction_denunciation_627.py tests/test_material_directory_1830.py \
  tests/test_event_trigger_gate.py tests/test_gazette_author_1862.py \
  tests/test_decree_commitment_schema_136.py tests/test_player_payload_1022.py \
  tests/test_web_issue_condition_display.py tests/test_person_delta_adapter.py \
  tests/test_llm_channel_config.py \
  tests/test_month_chain_1843.py::test_world_segment_reads_material_directory \
  tests/test_month_chain_1847.py::test_step_4a_rescript_continuation_feeds_supply_run_input \
  tests/test_month_chain_1847.py::test_build_secret_orders_supply_feed_uses_fact_materials_not_assembled_effects \
  tests/test_month_chain_1847.py::test_decree_continuation_keeps_forecast_and_lands_affair_effect \
  tests/test_secret_order_payoff_1504.py::test_supply_call_writes_identity_materials_into_its_own_tree \
  tests/test_character_knowledge_489.py::test_household_secret_ledger_keeps_amount_but_hides_case_semantics \
  tests/test_mechanical_tail_1845.py::test_chapter_memory_retired_from_three_readers \
  tests/test_fiscal_levy_effect.py tests/test_public_projection_consistency_1830.py \
  tests/test_on_scene_immediate_write_1839.py \
  tests/test_audience_translate_1837_reopen.py \
  -q -p no:cacheprovider --basetemp=/tmp/1834-fixer-pytest2
```

结果：`472 passed, 1 skipped`（`focused-pytest.txt`）。未跑全量；Web vitest 本机无依赖，未跑。

## 复杂度 / 合法性

- 生产 F9/F12 净删已在 `fc08d7713`；本轮补枚举脚本/探针/F3 漏项 + 报告。
- 无新增来源账/摘要/模型调用/输出擦洗。
- 自查二连 done。

## 剩余范围（不关票）

- #1873：四类文字事实公共读侧接线。
- F3 宽枚举长尾（`enum_f3.txt` 非材料读口类）未批删。
- 邻票生产消费接线不在本片。
- 分支未合并 → **不声称 #1834 关闭**。
