# #1834 修内司回执：F9 / F12 / F3

依据：fix-packet + 冻结判词 `00-1834-judge-52809cdf3.json`；现行 #1834 / #1812；ADR 0143、0155；质量法 #13。  
diagnosing-bugs：判词已定位根因，跳过探索性假设/仪表；以真实入口探针红绿 + 旧逻辑变异验证。  
未 push / PR / amend / stash；未改 Soul / 宪法 / 宿主配置。

## 三类根因

1. **F9** 案卷经 `_dossier_row` 解码后的 `payload`（含 `ongoing_effects.人物变更[].loyalty`）被整行搬进公共/世界材料，绕过 P4 人物属性输入投影。  
2. **F12** `list_world_effect_history` 新增的 `person_logs` 等整行审计转储只按行上来源字段过滤；真实人物日志常只携事务来源，密令私密 reason 仍进公共作者目录。  
3. **F3** 测试对人读材料正文做散文子串机械依赖（Python + Web），违反质量法盯文禁令。

## 修法（优先删除）

- F9：案卷材料跳过解码机器载荷 `payload` / `stigma` / `execution_signal`（`*_json` 本已跳过）。不扩字段矩阵、不擦洗输出。  
- F12：从 `list_world_effect_history` 删除 `person_logs` 及同类 `*_logs` / 审计整行转储；保留实况轨 + affair 的 issues/characters/边事件（issues 人物效果仍走既有投影）。四类文字事实接线归 #1873，本片不新增来源机制。  
- F3：删除正文成员断言；保留路径/归档字段/来源与权限负向契约；不换成非空/长度/哨兵或测试专用生产出口。

互联网核对：SQLite JSON1 官方页 `https://www.sqlite.org/json1.html`（HTTP 200）；pytest 正文断言脆性共识（Loose-Text-Oracle / pytest assert docs）。沿仓内既有 `json.loads` 与定性投影，无自造机制。

## 全仓枚举命令

```sh
# F9：案卷原始机器 payload → 材料
rg -n 'dossier\.items\(\)|endswith\("_json"\)|_DOSSIER_MATERIAL_SKIP|out\["payload"\]' ming_sim/materials.py

# F12：历史/审计整行转储 → 材料
rg -n 'person_logs|list_world_effect_history|_world_effect_materials|army_logs|building_logs|power_logs|region_logs|office_change_records|authority_records|decree_cost_events|dossier_loophole|dossier_supervision|population_transfer|investigation_spoiled' ming_sim/materials.py ming_sim/db.py

# F3：人读正文机械断言（Python 材料读口 + Web 邸报/局势正文）
# 谓词：assert/toContain 在 read_material / author_files / 材料 carrier 或邸报/局势人读面查找散文子串；
# 含字面量与命名常量（_PUBLIC_FACT / fact_body / original / _REPORT / SNAP_*）。
../Ming_LLM/.venv/bin/python - <<'PY'
# （本轮执行的 AST/正则全仓扫描脚本；结果见下表）
PY
```

复扫结果见同目录 `rescan.txt`：F9 仅剩 skip 集合 + items 过滤；F12 材料侧不再引用 person_logs 表转储；F3 材料正向散文断言已空，仅存路径成员与负向非泄漏。

## 完整成员表

### F9

| 成员 | 处置 | 理由 |
| --- | --- | --- |
| `ming_sim/materials.py` 案卷 `dossier.items()` 整行转储中的 `payload` | 删除（加入 `_DOSSIER_MATERIAL_SKIP`） | 判词样本；解码机器载荷含人物属性裸值 |
| 同上 `stigma` | 删除（skip） | 同形解码机器载荷（自 stigma_json），避免 `*_json` 漏网后的平行泄漏 |
| 同上 `execution_signal` | 删除（skip） | 同形解码自 extension_json |
| 同上 `office_archive_keys` + `*_json` | 保留既有排除 | 上轮已排除；非本轮新增 |
| `participant_roster` 等结构字段 | 保留 | 非人物六轴裸值机器载荷；事务成员需要 |
| `revoke_target_facts` 读 payload 抽结构化键 | 排除 | 非材料目录供料转储 |
| DB `create_decree_dossier` / 引擎读写 payload | 排除 | 账本真源，非玩家面输入 |

### F12

| 成员 | 处置 | 理由 |
| --- | --- | --- |
| `list_world_effect_history` → `person_logs` | 删除转储 | 判词未结支路；整行审计越过公共来源接缝 |
| 同上 `army_logs` / `building_logs` / `power_logs` / `region_logs` | 删除转储 | 同类新增整行日志/审计 |
| 同上 `population_transfer_ledger` / `investigation_spoiled_facts` | 删除转储 | 同上 |
| 同上 dossier 附属 `office_change_records` / `authority_records` / `decree_cost_events` / `dossier_loophole_exposures` / `dossier_supervision_presence` | 删除转储 | 同上「优先删除日志/审计转储」 |
| `实况轨`（economy/fiscal durable） | 保留 | 既有实况轨，非新增审计转储 |
| affair `issues`（含人物效果投影） | 保留 | 必要材料；复用既有 `_person_history_fields` |
| affair `characters`（仅 name） | 保留 | 既有成员名，非属性转储 |
| `relation_edge_events` | 保留 + 既有来源过滤 | 边事件；origin 过滤仍有效 |
| `_world_history_row_visible` 对判决/背书/进度/检举等 | 保留 | 非本类删除对象；origin 漏项修复保留 |
| 四类文字事实公共读侧补接 | 不施工 | #1873；禁止本片新增来源账 |

### F3

| 成员 | 处置 | 理由 |
| --- | --- | --- |
| `tests/test_month_chain_1847.py` `assert fact_body in carrier` | 删除 | 判词样本；材料正文盯文 |
| `tests/test_gazette_author_1862.py` `_PUBLIC_FACT/_PLAIN_DOSSIER_FACT/_PRIVATE_KEEP in author_files[...]` | 删除；改路径成员存在 | 判词样本 |
| 同上 `assert _REPORT in text`（read_material 邸报） | 删除；保留路径可读 + 归档字段相等 | 判词样本；`archive["report"] == _REPORT` 保留 |
| `tests/test_material_directory_1830.py` `assert original in read_material(...)` | 删除；保留调用读口 | 判词样本 |
| `tests/test_fiscal_levy_effect.py` 请旨材料正文子串 | 删除；保留 `presented_*` 结构化字段 + 路径可读 | 同类材料正文 |
| `tests/test_public_projection_consistency_1830.py` `original in disk/direct/api` | 删除；保留三通道相等 | 同类；通道一致≠盯文 |
| `web/.../appDurableWiring.test.tsx` 邸报标题 / MIDCOURSE / SNAP_ATTENDANT / SNAP_CLOSED / masthead 正向 toContain | 删除；保留 dialog/testid/负向非泄漏 | Web 人读正文 |
| `web/.../settlementGazettePanel.test.tsx` 报头/递话正文 toContain | 删除；保留 memorial exact + testid | 同上 |
| `web/.../modals.test.tsx` masthead 正向 toContain | 删除；保留错月负向 | 同上 |
| `web/.../situation.test.tsx` `toContain("杨嗣昌")` | 删除；保留 memorial exact + 负向 | 同上 |
| `web/.../settlementFaces.test.tsx` 「邸报」「上月抄报」caption | 排除 | UI 固定木牌文案（P7 界面话语例外），非自由正文盯文 |
| `modals.test.tsx:654` / `appDurableWiring:2782` 大臣名 toContain | 排除 | 结构化身份接线（发言人/奏疏作者），非材料散文契约 |
| 结构化 `archive["title"/"report"]`、`origin_ref` / `public_ids` / `exclude_*` 负向 | 保留 | 判词明确保留 |

## 探针与聚焦测试

七变量前缀 + `PYTHONDONTWRITEBYTECODE=1` + `../Ming_LLM/.venv/bin/python`。

```sh
PYTHONPATH="$PWD" ../Ming_LLM/.venv/bin/python /tmp/1834-f9-f12-probe.py
PYTHONPATH="$PWD" ../Ming_LLM/.venv/bin/python /tmp/1834-f9-f12-probe.py --old
PYTHONPATH="$PWD" ../Ming_LLM/.venv/bin/python /tmp/1834-f12-only-probe.py
```

| 运行 | 结果 |
| --- | --- |
| 当前逻辑 开放/关闭/恢复 × 世界+公共作者 | `ALL_GREEN`（见 `probe.txt`） |
| `--old` 恢复 payload 转储 + person_logs 转储 | `OLD_LOGIC_RED ... raw payload reason leaked` |
| F12-only 仅恢复 person_logs | `F12_OLD_LOGIC_RED leaked person_logs/private reason` |

聚焦 pytest（同上七变量；未跑全量）：

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
  -q -p no:cacheprovider --basetemp=/tmp/1834-fixer-pytest
```

结果：`455 passed, 1 skipped in 13.23s`（`focused-pytest.txt`）。  
Web vitest：本机无 `web/node_modules/.bin/vitest`，未跑；改动为删断言，CI 本就不含 vitest。

## 复杂度 / 合法性自查

- `git diff --stat`：11 files, **+31 / −62**（净删）。  
- `git diff --check`：无输出。  
- `CHANGED_PYTHON_SYNTAX_OK 7`。  
- 无新增来源账/摘要/模型调用/字符串解析/历史兼容/输出擦洗。

## 剩余范围

- #1873：四类既有文字事实公共读侧接线。  
- 邻票生产消费接线（#1861/#1840/#1843）不在本片。  
- Web vitest 需有依赖时再复核本轮删断言文件。
