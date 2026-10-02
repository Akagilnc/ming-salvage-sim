# #1834 历史供料修内司回执

本轮处置 F9 / F11 / F12 / F13；只施工、提交，未 push、开 PR、合并或关票。依据为本轮冻结大理寺判词 `00-1834-judge-f3e7dc6b0.json`、GitHub #1834 现行正文与 CLAUDE.md / ADR 0143、0155。未修改 Soul、authority、设计契约或邻票生产接线。

## 扫类谓词与机械枚举

从所有材料写盘/开场入口追溯读口，不将判词点名字段当白名单：

- F9：进入材料输入的历史人物属性（包含变化量、旧值、新值，以及已知效果载荷中的人物变更）；不是扫描或擦洗自由散文。
- F11：进入材料输入的持久行中，schema / 写口声明为 JSON 的字段；不根据任意字符串的外观猜 JSON。
- F12：历史供料全部行的已落结构化来源，包括 `origin_ref`、`origin`、`source_id`、`source_chat_turn_id` 及来源/稽核/护送案卷指针，密令案卷、密令来源前缀及持久口头来源轮；不按人物身份猜密令。
- F13：材料准备结果中仅测试或无人消费的导出及其旁路证明；非仅点名三份测试。

全仓执行的命令（不是只搜点名文件）：

```sh
rg -n 'PreparedMaterials|\.index_lines|\.world_facts|world_facts\[' --glob '*.py' .
rg -n 'list_world_effect_history|_world_effect_materials|_material_facts_text\(' --glob '*.py' .
rg -n 'record_person_log\(|normalized=' ming_sim
rg -n 'person_logs|payload_summary|old_loyalty|new_loyalty' ming_sim
rg -n 'is_secret_order_origin|secret_turn_ids|exclude_dossier_ids' ming_sim
rg -n 'CREATE TABLE|normalized TEXT|ongoing_effects TEXT|participant_roster TEXT|json.loads|_json' ming_sim/db.py
rg -n '人物变更|effect|normalize_commitment_stages' ming_sim/staged_commitment.py ming_sim/person_delta_adapter.py
rg -n '_record_decree_cost\(' ming_sim/db.py
```

另通过临时真跑探针 `--census` 机械枚举 schema：AST 取 `GameDB.list_world_effect_history` 引用的全部表，补入其真实下游实况轨及案卷附属读口；逐表 `PRAGMA table_info` 枚举 JSON 默认值、`*_json` 和已声明的 `person_logs.normalized`。命令为下节七变量前缀 + `PYTHONPATH="$PWD" ../Ming_LLM/.venv/bin/python /tmp/1834-history-probe.py --census`。其 28 表输出构成以下完整读面成员表。临时探针清理后仍可直接重做这份 schema 枚举（加下节七变量前缀）：

```sh
../Ming_LLM/.venv/bin/python - <<'PY'
import ast, tempfile
from pathlib import Path
from ming_sim.content import GameContent
from ming_sim.db import GameDB
with tempfile.TemporaryDirectory(prefix='1834-census-') as tmp:
    db = GameDB(str(Path(tmp) / 'schema.db'), GameContent.load())
    tables = {r[0] for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    tree = ast.parse(Path('ming_sim/db.py').read_text())
    method = next(n for c in tree.body if isinstance(c, ast.ClassDef) and c.name == 'GameDB'
                  for n in c.body if isinstance(n, ast.FunctionDef) and n.name == 'list_world_effect_history')
    members = {n.value for n in ast.walk(method) if isinstance(n, ast.Constant)
               and isinstance(n.value, str) and n.value in tables}
    members.update(('economy_ledger', 'fiscal_config_creations', 'fiscal_config_changes',
                    'fiscal_config_tombstones', 'dossier_actual_progress', 'decree_dossiers',
                    'decree_dossier_decisions', 'decree_dossier_endorsements', 'decree_dossier_links',
                    'dossier_reported_progress', 'decree_dossier_reconciliations',
                    'faction_denunciations', 'secret_orders'))
    for table in sorted(members):
        columns = db.conn.execute(f'PRAGMA table_info({table})').fetchall()
        fields = [r['name'] for r in columns if str(r['dflt_value']).strip("'\"") in ('{}', '[]')
                  or r['name'].endswith('_json') or (table == 'person_logs' and r['name'] == 'normalized')]
        print(table, fields)
    db.close()
PY
```

| 成员 | F9 / F11 / F12 处置或保留依据 |
| --- | --- |
| `person_logs`，直挂事务与关联案卷两条路径 | `normalized` 明确 JSON 解码；六轴 `loyalty / ability / integrity / courage / identity / intrigue` 的增量供方向，旧新值复用 canonical 档位词；自由 reason、summary、性情等原样。 |
| `issues` | 全部九个明确 JSON 列解码：`tags / participants / participant_roster / target_roster / ongoing_effects / cancel_cost / effect_on_resolve / effect_on_fail / stages_json`。四种效果载荷中的 `人物变更 / person_changes / character` 共用同一六轴投影（上轮漏后两键，见下节补修）。内部数值 `stop_condition` 执行格不再转储；人读 resolve/fail condition 与阶段、结案经历保留。 |
| `characters` | 此历史读口只供事务成员姓名；属性继续走现有朝臣定性名册、人物经历，不恢复整行副本。schema 的 aliases 不进入此读口。 |
| `relation_edge_events` | 读取真实 `origin`；排除密令案卷引用、密令来源前缀及密令源轮。普通边事件保留，全知目录不排除。 |
| `army_logs / building_logs / power_logs / region_logs / population_transfer_ledger / investigation_spoiled_facts` | schema 无 JSON 存储列；非人物六轴的物理世界数值保留。全部行仍经过共同来源排除，而非只筛边事件。 |
| `office_change_records / authority_records / decree_cost_events / dossier_loophole_exposures / dossier_supervision_presence` | schema 无 JSON 列。枚举 cost 写口后确认现有种类为皇威、派系满意度、责任事件等，未发现人物六轴数值载荷；不新增推测性护栏。全部来源同筛。 |
| `economy_ledger / fiscal_config_creations / fiscal_config_changes / fiscal_config_tombstones / dossier_actual_progress` | 沿已有经济财政与实际进度合并口；schema 无 JSON 列。钱粮、数量及完整已落历史不截断，同筛已落来源。 |
| `decree_dossiers` | 既有 `_dossier_row` 解码 participant_roster；payload/stigma/extension 的原始 `*_json` 审计格及 office_archive_keys 本来不转储，保持。密令整案沿既有排除集剔除。 |
| `decree_dossier_decisions` | 既有读口解码 `primary_opponents_json / criteria_snapshot_json / affected_parties_json`，没有恢复原始列。 |
| `decree_dossier_endorsements / decree_dossier_links / dossier_reported_progress / decree_dossier_reconciliations` | schema 无 JSON 列；既有读口供必要历史，奏报与实况保持分轨。扫描另发现背书源轮、关联来源案卷及稽核/护送来源案卷指针，也走同一来源谓词，不留旁路。 |
| `faction_denunciations / secret_orders` | 检举仅供既有白名单字段，payload_json 真伪底不进材料。密令只供自由 result 陈词和既有已解码进度读口；tags/text_log_json/excluded_names/dossier_progress_json/excluded_targets 不原样转储。密令整案沿公共排除集剔除。 |

同时复扫了盘面、朝臣名册、人物/军队/地区按月事实、人物经历/可闻性、事务起因与关闭历史、公开说法、邸报、候选/终态/请旨材料。现有定性投影与公开供料排除保留；自由散文不是结构化属性字段，不新增词面守门。候选门是已判过的资格事实，不借本轮修改候选资格或选择规则；军隊 loyalty 等世界事实不按人物六轴误投影。

F13 成员与处置：

| 枚举成员 | 处置 |
| --- | --- |
| `PreparedMaterials.world_facts`、prepare 返回参数与描述 | 删除对外快照。候选、检举、终态的一次计算快照仍局部保留、用于写盘。 |
| `test_world_materials_1834` 的检举/候选标签旁路 | 删除快照断言，保留真实列目录、实际读取与结构化路径契约。 |
| `test_candidate_supply_1893._read_candidates`，合格/不合格/终态快照两案，弹劾链快照对比 | 删除旁路 helper 和两条证明性测试，不换形重造。弹劾链保留真实转译请求→声明→落账；目录只验证可取阅的路径。资格、终态、未选与恢复行为由现有入口测试负责。 |
| `test_faction_denunciation_627.test_world_materials_exclude_secret_fork_from_gazette` | 删除仅以专用快照证明作者供料的整案，不用正文哨兵替代。真实作者目录排除由本轮真跑取证。 |
| `PreparedMaterials.index_lines` | 额外同类成员：生产和测试均无消费者，仅空构造残留。删除导出和空构造参数，publish 不再返回镜像索引；根目录 INDEX.txt 的实际载体照旧。 |
| registry/session、LLM channel fixture | 保留实际消费的 root/opening；fixture 跟随删除无消费参数，没有 mock 被测供料。 |

复扫 `rg -n '\.world_facts|\.index_lines|world_facts:|index_lines:' --glob '*.py' .`：仅剩 `_write_world_tree` 的局部 `world_facts` 参数，无对外导出/消费。测试中的 `_world_facts`（P4 surface fixture helper）不是 PreparedMaterials 导出，不误删。旧 evidence 文件为历史回执，非现役 schema，保留原历史。

## 根因、修法与成本

根因：新增历史把持久整行当作可读输入。共同材料读面现负责已知存储加工、人物输入投影与来源准入，直挂事务/案卷共用；去掉 DB 中旧的仅检查 origin_ref 完全相等的窄排除。不新增账本、摘要、模型调用、任意字符串解析器或输出擦洗。

互联网核对：`curl -L -s https://www.sqlite.org/json1.html -o /tmp/1834-sqlite-json.html`；实际读到官方页标题 `JSON Functions And Operators`。仓内搜索见上表：沿 `_dossier_row`、既有决策 JSON 读口及 `ming_sim.qualitative`。语言标准库直接用 `json.loads` 处理明确字段；无新通用件、无第三方依赖，因此未造包生态已有件的副本。

## 自验与变异真跑

所有运行前缀：

```sh
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1
```

聚焦命令（上述前缀）：

```sh
../Ming_LLM/.venv/bin/python -m pytest \
  tests/test_world_materials_1834.py tests/test_candidate_supply_1893.py \
  tests/test_faction_denunciation_627.py tests/test_material_directory_1830.py \
  tests/test_event_trigger_gate.py tests/test_gazette_author_1862.py \
  tests/test_person_delta_adapter.py::test_apply_score_extraction_records_mao_appeasement_commitment_and_loyalty_delta \
  tests/test_llm_channel_config.py -q -p no:cacheprovider
```

最后一轮实测输出：`244 passed in 7.64s`（扩展附属历史来源修复后重跑）；此前为 `244 passed in 7.58s`。先前最小触面输出 `21 passed in 3.82s`。仅聚焦，未跑全量或真实模型。Python 触及面以 AST 语法核验，输出 `CHANGED_PYTHON_SYNTAX_OK 6`；不冒称静态类型检查。

真跑命令：上述前缀 + `PYTHONPATH="$PWD" ../Ming_LLM/.venv/bin/python /tmp/1834-history-probe.py`。在自建临时库经真实 `apply_score_extraction`、`insert_issue_with_affair_declaration`、`dispatch_declaration`、`create_secret_order` 及普通边事件写口落定：

- 人物评定经真实入口分别直挂事务落账 `loyalty=3, old_loyalty=68, new_loyalty=71`、经顺颁案卷落账 `loyalty=8, old_loyalty=71, new_loyalty=79`；两读面的供料结构变为变化方向与两端档位。issue 四种已知效果载荷共用该投影，探针同时观察了 ongoing 人物变更输入。
- 真实持久口头 pin 对应密令源轮；同一事务有一条密令轮边事件与一条普通边事件。正常案卷另落一条密令轮背书和一条普通批红背书，确认附属历史也不能绕过排除。
- `prepare_world_materials / prepare_gazette_author_materials → list_materials → read_material` 实际取阅；开放、关闭、关库恢复三态均输出 `PASS ... typed person/issue inputs; full=2 public=1 edges/backings; API/native equal`。全知目录逐文件用 `/bin/cat` 与 API 实取对照；不解析人读正文，不盯非空/措辞。
- 观察仅在临时进程渲染前抓结构化输入，原渲染仍调用；没有测试专用生产导出。

变异在独立临时进程装回旧逻辑，命令为同一探针附旗：

| 变异命令后缀 | 已执行的报红结论 |
| --- | --- |
| `--old` | AST 装回 HEAD 旧历史方法、旧窄排除；`AssertionError: known person JSON storage is unprocessed`。 |
| `--old-person` | 恢复人物记录原样过手；`AssertionError: person delta is raw`。 |
| `--old-json` | 恢复 issue SQLite 原始行；`AssertionError: ('tags', <class 'str'>)`。 |
| `--old-source` | 取消历史共同来源排除；`AssertionError: secret oral-pin edge leaked`。 |
| 无旗，恢复现逻辑 | 三态绿，完整目录保留两条边，公共作者只保留普通边。 |

探针早期两次失败为缺少 apply 的 content/授权事务输入，另一次为探针误用顶层 affair_id 而非 affair_declaration；均按真实写口契约纠正，没有把探针错误当作生产缺陷。

测试改动成本：净删除三个证明性测试及专用快照断言；只调整一行真实 fixture 构造参数，没有新增测试函数、正文解析或非空守门。剩余测试向结构化路径、生产转译请求、写口结果负责，不将渲染失效冒称通过供料验收。本轮渲染内容验收只以真实取阅观察呈证。

上轮“F9 无施工未结项”的声明经复核撤回：效果载荷键枚举不全。F11–F13 维持原处置；F9 补修如下。后续庭审/合并、邻票生产接线仍归各自车道。临时探针及下载文件均自建于系统临时目录，交卷前清理；未动宿主、席位表、stash 或他人工作。

## 复核补修：F9 人物效果载荷键同类漏项

事实成立。上轮只从规范键出发，未从引擎全部读口枚举；所以“四种效果载荷共用投影”并不等于“全部人物载荷形状已投影”。本次仅补该类，不重做 F11–F13。

### 全类枚举与成员

```sh
rg -n 'effect.get\(|effect\[' ming_sim/issues.py
rg -n 'person_changes|\.get\("character"|\["character"\]' ming_sim --glob '*.py'
rg -n 'effect_dict_has_work|_person_effect_has_work|_character_effect_has_work' ming_sim/models.py
rg -n 'normalize_person_changes|_copy_present|character_status_changes|character_power_changes|office_changes|appointments' ming_sim/person_delta_adapter.py
rg -n 'PERSON_EFFECT_KEYS|ongoing_effects|cancel_cost|effect_on_resolve|effect_on_fail' ming_sim/materials.py ming_sim/issues.py ming_sim/models.py ming_sim/person_delta_adapter.py
```

枚举源是 `issues._monthly_person_rating_changes`、其拒收/非月度工作判定、`_apply_issue_entities`、`models.effect_dict_has_work` 和人物 adapter 的全部 legacy 形状；不是从判词点名的两个字符串反推。

| 人物效果形状 | 引擎承载语义 | 本次处置/保留依据 |
| --- | --- | --- |
| `人物变更` | 规范人物动作，评定读 `loyalty` 增量 | 共用 `_person_history_fields`，保留字段结构 |
| `person_changes` | 月度评定别名，同规范动作正规化 | 同上，不残留裸数值 |
| `character` | 旧形状列表；name/人物、loyalty、reason/原因转评定 | 同上；不要求材料自行增添动作或正规化自由散文 |
| `character_status_changes` | 处置状态；adapter 白名单为 status/reason_code/reason/origin_ref | 不承载合法六轴数值变更；保留既有状态历史，不增防御 |
| `character_power_changes` | 易主，new_power/reason/origin_ref | 不承载六轴；保留实际归属变化 |
| `office_changes / appointments` | 任命/官职与任所；adapter 明确字段白名单 | 非这类属性增量；保留既有任命材料 |
| `action / 动作`、`name / 人物`、`reason / 原因` | 条目内部别名，不是第四个效果载荷键 | 原样保留；六轴字段共用投影 |

完整需要投影的笛卡尔成员表：

| 持久效果字段 | 人物载荷键（全部共用六轴投影） |
| --- | --- |
| `ongoing_effects` | `人物变更 / person_changes / character` |
| `cancel_cost` | `人物变更 / person_changes / character` |
| `effect_on_resolve` | `人物变更 / person_changes / character` |
| `effect_on_fail` | `人物变更 / person_changes / character` |

最小修法：将引擎已经接受的三键抽为 adapter 的 `PERSON_EFFECT_KEYS`；真实月度读口、验证/工作判定、models 工作判定和材料投影共同消费它，删除重复的键集合与单键投影边界。`character` 的既有专门正规化与拒收语义不改；不新增解析器、防御或测试专用出口。

### 真跑、变异与聚焦自验

所有运行均使用上节完整七变量前缀和 `PYTHONDONTWRITEBYTECODE=1`；探针另设 `PYTHONPATH="$PWD"`。自建临时探针通过真实 `insert_issue_with_affair_declaration` 写入四个字段，每个字段均存三个人物键，分别落正增量 `5` 与负增量 `-8`。从 `prepare_world_materials` 进入并实际 list/read 目录；仅在原渲染函数旁观察结构输入，不解析生成正文。

```sh
# 修前真实入口已报红；补修后再独立进程装回上轮单键边界
../Ming_LLM/.venv/bin/python /tmp/1834-person-effects-probe.py --old
# 不带旗，恢复生产逻辑，同一真实写入/目录入口三态复验
../Ming_LLM/.venv/bin/python /tmp/1834-person-effects-probe.py
../Ming_LLM/.venv/bin/python -m pytest tests/test_world_materials_1834.py tests/test_decree_commitment_schema_136.py tests/test_player_payload_1022.py tests/test_web_issue_condition_display.py tests/test_person_delta_adapter.py -q -p no:cacheprovider
```

可核输出摘录：旧边界中四个效果字段的 `person_changes` 均为 `int 5`、`character` 均为 `int -8`，而规范键为 `str`；报 `AssertionError: ('open', [('ongoing_effects', 'person_changes', 5), ('ongoing_effects', 'character', -8), ...])`。恢复后每个字段/键组合均观察为 `str`，开放、关闭、重新打开数据库恢复三态各报 `PASS ... all 4 payload fields x all 3 engine person keys projected; actual directory read`。

聚焦结果：`161 passed, 1 skipped in 6.79s`（保留基底盘面缺人物时的既有条件 skip）；四个变动 Python 文件 AST 解析通过，`git diff --check` 无输出。不跑全量、不冒称 typecheck，无测试改动/新增测试。复扫后上述三键和四字段无漏项；F9 本次施工无剩余。两个自建临时文件 `/tmp/1834-person-effects-probe.py`、`/tmp/1834-person-effect-readers.txt` 交卷前清理。

