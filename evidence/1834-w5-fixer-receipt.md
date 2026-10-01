# #1834 W5 修内司回执

本轮施工基点：`3608a7a8dba52397ddfe12d6b755a1a702d29548`。只处置本庭 F1–F4；未改 Soul、宪法、席位、宿主安装或配置；未接旧推演链、选事件或写世界结果。交付为工作树修复及 forward commit，不宣称已合并、关票或庭审收敛。

## 法源与范围

已读本机两份全局规则、仓级 CLAUDE.md / AGENTS.md、CONTEXT、ADR 0155 / 0156、派单和冻结 judge 附件。现行票面通过 `gh issue view 1834 --repo Akagilnc/ming-salvage-sim --json body,title` 核对：交付完整世界材料目录 API 和真实读取验收，不接旧链。采用判词四类的完整定义；点名文件不是扫描白名单。正文约束类覆盖材料目录、开场及它们的真实调用测试，包括人物材料、作者和月链邻接用例，不仅本票测试文件。

## 机械枚举与复扫

下列命令从仓根执行，覆盖全部 tracked 源码／测试／文档；先枚举候选，再按输入与消费用途区分人读生成物、结构化字段、独立原文搬运及冻结历史卷宗。不是只找判词符号或 `.txt` 后缀：F1 沿全部写口追源；F2 沿所有世界备料和盘面调用追至默认开场；F3 枚举所有测试断言并追 read/opening 的变量、字典槽和捕获别名；F4 沿全部文字事实读口追到载体与对象枚举。复扫重用相同类别与命令。

```sh
git grep -n -E 'json\.dumps|json\.loads|_write_text|write_text|read_material|world_facts' -- ming_sim/materials.py tests docs README.md
git grep -n -E 'prepare_world_materials|_world_board_text|_world_roster_text|_world_opening_text|current_court_roster_rows|limit=' -- ming_sim tests
git grep -n -E 'assert|read_material|opening|materials|SENTINEL' -- tests
git grep -n -E 'textual_facts|readable_materials|按月实况|事实/|_textual_facts_text|_world_subject_ids|_world_roster_names' -- ming_sim tests docs README.md
```

复扫候选行数分别为 782 / 100 / 14221 / 183。另以 Python AST 对变更测试逐函数枚举基点与当前的 Assert，核对删除项（嵌套函数同一节点按文件＋行号去重）；以下成员位置均用施工基点行号，便于核对判词。

### F1 人读材料目录被当作 JSON 出口 — 已处置

根因：目录呈现和内部结构化消费混作一个出口，测试还从人读正文反序列化。

| 全部错误成员 | 处置 |
| --- | --- |
| materials._write_world_tree：盘面/派系检举事实.txt、盘面/候选事件与弹劾潮.txt、盘面/事件终态.txt | 改为人读分层字段清单；目录不提供反序列化契约 |
| materials._write_candidate_event_files：逐件候选的 trigger_gate 字段 | 同用字段清单，不在正文嵌 JSON |
| prepare_world_materials docstring：宣称终态文件是 JSON 对象及结构化候选文件 | 纠正为人读目录＋内部快照读口 |
| test_world_materials_1834：检举事实及人物候选读取；test_candidate_supply_1893：候选、终态、刷新、旧快照及弹劾候选读取；test_faction_denunciation_627：作者检举事实读取 | 真实读取仍执行，结构化断言落在本次 PreparedMaterials.world_facts，不解析目录文字 |

候选、检举和终态仍各从既有真源取一次；world_facts 仅引用本次已用于写目录的内存对象，不重查、不持久化、不另立账或缓存。内部资格读口不变，终态仍按 event_id 给出 terminal_state / terminal_reason，空集仍是空结构。

保留：materials 中剩余两个 json.dumps 均为 `_scene_pending_audience_facts` 的结构化开场输入，不写人读目录文件；月链／转译请求的 JSON 属结构化调用协议，不是目录出口。冻结 evidence 中的旧命令／结论不篡改。

### F2 默认开场盘面不完整 — 已处置

根因：朝臣投影只写名册文件，默认开场使用的共同盘面没有它。

| 盘面／入口枚举成员 | 处置或依据 |
| --- | --- |
| _world_roster_text → _write_world_tree，原只写人物/朝臣名册.txt | 每次 prepare 只取一次名册，同份全文也纳入 _world_board_text |
| _world_board_text → _world_opening_text → prepare_world_materials | 默认开场现含全量朝臣；直接调用共同盘面的 4a feed 也沿同一实现取得朝臣，不留平行缺口 |
| 国库、军队、地区 | 已为 limit=None，保留无截断读口 |
| 营建、边防、阶级 | 沿既有全量账本投影，非奏报替代实况 |
| 开放事务及当前情况、在途案卷 | 保留已定默认开场；显式公共作者筛选仍按原职责生效 |
| month_chain、decree_forecast、公共作者的世界备料调用 | 共用上述入口，无独立盘面白名单或第二开场实现 |

名册文件仍可自主取阅，但不再用“文件可读”替代默认在场。真实开局 57 条朝臣；毕自严／南京户部尚书修前均不在 opening，修后均在。此为特征化观察，不设正文匹配测试。

### F3 测试机械约束人读生成文本回潮 — 已处置

根因：把“真实入口可读”误写成正文 truthy、strip 后非空或标题片段包含；传播到相邻调用测试。整类删除 27 个断言位置，不换长度、哨兵、模板或放宽阈值。需要实际读取的原入口调用保留，正常返回即可；结构化路径、来源、权限、刷新和失败路径不删。

| 全部错误成员（tests/，基点行号） | 数量与处置 |
| --- | --- |
| test_world_materials_1834.py:58,60,158,159,283,285,319,328 | 8；正文非空／标题片段删除 |
| test_material_directory_1830.py:55,71,72,255 | 4；同类删除 |
| test_gazette_author_1862.py:440,446,457,459 | 4；标题片段与经历／盘面非空删除 |
| test_month_chain_1843.py:743,744,747,753 | 4；API／CLI index、board、opening 非空删除 |
| test_month_chain_1847.py:707,1314,2070 | 3；续推 opening 及 4a board 非空删除 |
| test_secret_order_payoff_1504.py:994,1017 | 2；身份目录与 INDEX 正文非空删除，并删仅服务该证明的 bodies 捕获 |
| test_character_knowledge_489.py:1411 | 1；公事档案正文非空删除 |
| test_mechanical_tail_1845.py:497 | 1；历月邸报 body 非空删除，只留结构化键存在 |

保留依据：list_materials 的路径集合和空／非空候选集合是结构化结果；直接自建文件读取、独立写入的原文完整搬运、API 与 native 同份内容属于读取／零篡改契约，不以生成物措辞推断事实身份。已落记录的 title 字段相等不等于在生成 INDEX 中找标题片段。场景 JSON 事实及 prepare.opening 向 instructions 的整份搬运只核传输，不规定人读正文内容。结构化错误标签／边界与失败传播仍保留。其他冻结史料、静态 seed、路径和业务数值断言不是本类人读生成正文约束。

### F4 世界文字事实存在平行供料投影 — 已处置

根因：一条 character / army / region 事实同时供入顶层事实文件和对象按月实况，两套查询／拼装且前者丢月份。不能只删除第二载体而以现存实体白名单误丢历史对象。

| 全部成员 | 处置 |
| --- | --- |
| _write_world_textual_fact_files：character、army、region 查询、拼正文和事实/* 三类载体；_write_world_tree 的调用 | 删除整套重复实现及载体 |
| _write_world_tree：人物、军队、地区按月实况三个分支 | 保留既有 _textual_facts_text，月份＋原文按序全部提供，include_fact 沿原规则生效 |
| _world_roster_names、_world_subject_ids：仅枚举现存实体 | SQL UNION 文字事实中的对象 ID；实体已不在当前表的历史材料仍可达，不另建对象账或缓存 |
| test_world_materials_1834 的旧事实/* 载体断言；test_gazette_author_1862 和 test_month_chain_1847 的消费路径 | 同步到唯一对象载体；已有单一载体用例排除世界事实/* 副本 |

事务事实仍只有事务/当前情况一份载体，沿 `_world_affair_lines` 提供全部月份、开场给当前一句。人物私有目录 `_write_textual_fact_files` 属不同的职位／身份可读范围，不是世界目录的第二载体；不把世界全知材料并入人物目录。场景目录也按本场身份提供材料，复用 _textual_facts_text；不同调用树不是同一世界调用的双载体。未误改其权限边界。

## 简单实现与生态调查

先查仓内现成文字／事实投影和序列化用法：`rg -n 'yaml|pprint|format.*fact|fact.*text|format.*material' requirements* ming_sim`，无适用于分层事实材料且保原文换行的现成呈现器。官方资料读取用 `curl -L -s https://docs.python.org/3/library/pprint.html`，另核 `https://pyyaml.org/wiki/PyYAMLDocumentation`；三处搜索：仓内如上，标准库 json / pprint 是可解析对象表示，会转义正文或输出 Python repr；生态 PyYAML 是另一种对象序列化，且仓内未直接声明依赖，不为这四处呈现添加依赖／新格式协议。

新增仅一个本模块的 `_material_facts_text` 展示函数：字段、列表分层，字符串原样搬运，无解析、回读、护栏或持久层；四处呈现复用它，避免维护四份字段格式。世界事实合并复用既有按月投影，删除 45 行重复写手。未新增测试函数或通用解析／重试／锁／缓存机制。

## 验证证据

所有测试和探针均前缀七个禁真模型变量：

```sh
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false MING_SIM_PI_BIN=/usr/bin/false ../Ming_LLM/.venv/bin/python -m pytest tests/test_candidate_supply_1893.py tests/test_world_materials_1834.py tests/test_material_directory_1830.py tests/test_faction_denunciation_627.py tests/test_gazette_author_1862.py tests/test_month_chain_1843.py::test_world_segment_reads_material_directory tests/test_month_chain_1847.py::test_step_4a_rescript_continuation_feeds_supply_run_input tests/test_month_chain_1847.py::test_build_secret_orders_supply_feed_uses_fact_materials_not_assembled_effects tests/test_secret_order_payoff_1504.py::test_supply_call_writes_identity_materials_into_its_own_tree tests/test_character_knowledge_489.py::test_household_secret_ledger_keeps_amount_but_hides_case_semantics tests/test_mechanical_tail_1845.py::test_chapter_memory_retired_from_three_readers -q -p no:cacheprovider
```

结果：**41 passed in 9.45s**。补跑相同前缀的 `-m pytest tests/test_month_chain_1847.py::test_decree_continuation_keeps_forecast_and_lands_affair_effect -q -p no:cacheprovider`：**1 passed in 7.34s**。随后删除仅服务正文断言的捕获变量，再以同前缀聚焦重跑 `test_month_chain_1843.py::test_world_segment_reads_material_directory`、`test_month_chain_1847.py::test_decree_continuation_keeps_forecast_and_lands_affair_effect`、`test_secret_order_payoff_1504.py::test_supply_call_writes_identity_materials_into_its_own_tree`：**3 passed in 2.67s**。只跑触及面的聚焦测试，不跑全量；新增测试数量为零，测试改动最小必要成本是去掉违规正文约束并将结构化消费移到同次快照、同步唯一载体路径，不另建平行证明测试。

变异真跑命令：上述七变量前缀加 `PYTHONPATH=. MUTATION=old ../Ming_LLM/.venv/bin/python /tmp/1834-probe.py`；恢复为同命令去掉 `MUTATION=old`。临时探针从真实 GameContent.load / GameDB.seed_static_data / load_state / prepare_world_materials / list_materials / API 工具及 `/bin/cat` 进入。old 模式从 `git show HEAD:ming_sim/materials.py` 装入施工基点完整原模块的函数，不 mock 备料行为，不改工作树或历史；三种历史对象各落一条含 CRLF 的事实，真实事件 korea_envoy 落避过终态。

摘抄结果：

- 旧逻辑：三份盘面事实为 `JSON object`；毕自严、南京户部尚书 opening 观察均 False；历史对象只在事实/*，STRUCTURED CONTRACT 的 character / army / region 均 False，**真实入口 AssertionError 报红**。
- 新逻辑：三份为 `human text`；opening 两项观察均 True；三类历史对象均只有对象按月实况；月份为天启七年十月，原文 CRLF 和尾空白仍在；STRUCTURED CONTRACT 三项 True，正常退出。
- 新逻辑：**API_NATIVE_SAME 281 files**（旧为 280），每个列目录路径经 API 与 `/bin/cat` 逐字同份内容。该比较只核两个读取通道一致，不锁任何生成正文。
- 终态材料观察：`korea_envoy：… terminal_state：… avoided … terminal_reason：… 原结局说明\r\n续行`，不转义成 JSON 字符串。
- 探针第一次扩充终态夹具时误用未定义事件 probe-terminal，真实写口 ValueError；改用已有 korea_envoy 后才重跑。此夹具错误不算旧逻辑报红证据。

F1/F2 的文字现象只作特征化人工观察，不把 JSON 解析失败、正文包含或长度变成回归约束。F3 的证明是删项枚举及复扫；F4 的秒级红绿只断结构化载体路径。diagnosing-bugs 的猜因／加仪表／新建正文回归测试步骤不适用：判词已真实复现并定位确定原因，本轮由旧模块变异复现核对；不为其重建已被禁止的正文证明。

复扫：`git grep -n -E 'json.loads\(read_material|_write_world_textual_fact_files|事实/character-|事实/army-|事实/region-' -- '*.py'` 无命中；`git grep -n 'json.dumps' -- ming_sim/materials.py` 仅上述两处结构化场景开场输入。触及 Python 文件以 compile(source, path, 'exec') 全部通过：`TOUCHED_PYTHON_COMPILE_OK`；仓内未配置 Python typechecker，CI 的类型检查只管 Web，本轮未触 Web，不冒称 Python typecheck。`git diff --check` 无输出。

临时探针及枚举输出仅在系统临时目录创建；探针每次 TemporaryDirectory 自清理。终局前只清理本轮自建脚本／下载／枚举文件，不动他人的临时物或任何配置。剩余：四类无未结施工项；待庭审复核、合并及调用者真宿主验收，不由本轮冒称。
