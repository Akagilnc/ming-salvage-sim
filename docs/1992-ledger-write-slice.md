# #1992 落账、重建与按需读取施工记录

**现行状态见文末「删应用层机制」**。此前 Q4/Q5 的跨提交复用、依赖分析及只读转换已由新版票面撤回，下列各轮数字与判断仅为历史证据，不再是现行设计。第一片对应 `5effbcdfa42b48c36caeaf269bb7b33dbc7b58bc`。

## 第一片：范围与当时剩余决定

本片替换落账与重建路径，未改 `read_once` 的按提交清空策略。Q4/Q5 的跨无关提交去重尚未实现，不能据本片减少的 SQL 数宣称重复归零。

当前 `Ledger.commit` 每次有 recordings 就 `read_results.clear()`；`read_once` 同时缓存 SQL 结果和中间层派生结果，既不保存查询依赖，也不保存父子读依赖。Q4 要求无关提交不使结果失效，因而不能只删除 clear（会返回旧实体、旧权限和旧事实），也不能仅以表/kind 变更清空（同类无关实体仍会重复）。

继续需要把现有提交级复用改为跨提交、依赖相关状态的复用设计，并明确其存活期和材料增长成本。这个实质设计变更尚未在票面 Q1–Q7 中定义；依“设计修订后重新过庭”，本片不擅自加 SQL 依赖分析器、第二套依赖名单或长寿命无界缓存。待签发方取得设计裁定并重新署票后继续 Q4/Q5；本记录不是新的设计决定。

## SQL 实测

基线 HEAD：`1f2d13220c74df389c8af1d339fbfc1d36a7e169`（本工作树的起点）。票面原探针在 `b60834271`，两者不是同一状态；这里如实记录本树，不把数字冒称复现原票的 2872。

命令：

```sh
PYTHONPATH=/tmp:$PWD .venv/bin/python -m pytest -q -p probe1992 \
  'tests/test_month_steps.py::test_month_pays_affair_from_declaration_month[regular]'
# 修后加 SQL_REPORT=/tmp/1992-after-write.json
```

临时探针 `/tmp/probe1992.py` 用 SQLAlchemy `before_cursor_execute` 记录实际 SQL、参数和仓内调用栈，只统计 pytest call 段。完整数据：`/tmp/1992-before.json`、`/tmp/1992-after-write.json`。事件流为录件驱动、真实 HTTP → Game → Court → Ledger → SQLite；不调用真实模型。

| call 段动作 | 修前 | 本片后 |
| --- | ---: | ---: |
| 全部 SQL | 3207 | 1011 |
| SELECT | 1895 | 601 |
| 读实体／事实表 | 440 | 440 |
| 聚合获取读事件表 | 344 | 161 |
| 初始化、落账、跟随者读事件表 | 427 | 0 |
| 读 tracking | 684 | 0 |
| 写 tracking | 322 | 0 |
| 写事件表 | 322 | 322 |
| 写实体表（执行次数，不是行数） | 322 | 36 |
| 写事实表（执行次数，不是行数） | 322 | 36 |
| PRAGMA | 24 | 16 |

修前输出 `1 passed in 8.33s`；本片后输出 `1 passed in 4.22s`。实体／事实批量写使用 SQLAlchemy 原生 executemany，记录完整性由重开与重建比对验证，不以减少写入条数冒充删除事实。

### 读表 440 句：调用者 × 表（修前、本片后相同）

E＝实体表；E+F＝语句涉及实体与事实表（含关联子查询）。这是实际 SQL 的表参与分类，不冒称逐行语义依赖分析。

| 调用者（均在 `ming/middle/`） | 表 | 次数 |
| --- | --- | ---: |
| calendar.calendar_row | E | 37 |
| calendar.journeys_due | E | 4 |
| court.current_decrees | E+F | 2 |
| court.errands | E+F | 2 |
| court.interactions | E+F | 37 |
| court.month_petitions | E+F | 2 |
| court.nights | E+F | 37 |
| court.pending_nights | E+F | 5 |
| court.pending_petitions | E+F | 37 |
| court.pending_pushes | E+F | 2 |
| court.petition_officials | E | 16 |
| court.petition_products | E+F | 2 |
| court.products | E+F | 67 |
| court.record_catalogue | E+F | 22 |
| court.returned_petitions | E+F | 41 |
| court.unhandled_monthly | E+F | 37 |
| dispatch.dispatch | E+F | 2 |
| dispatch.landing_entities | E | 6 |
| dispatch.landing_sources | E+F | 16 |
| fiscal.Accounts.__init__ | E | 4 |
| fiscal.due_levies | E | 2 |
| fiscal.Accounts.run | E+F | 2 |
| view.entities | E / E+F | 19 / 32 |
| view.month_open | E+F | 2 |
| view.project | E+F | 5 |

事件表／tracking 的剩余修前调用者拆分可在原始 SQL 文件核对；本片后事件表 161 句为 `fiscal.Accounts.__init__` 153、`court.record_product` 7、`court.record` 1，全部为缓存未命中的聚合历史读取，不是快进。

## 重建行为与成本

真实入口 `ming read --db … --identity audit --replay`，与不加 replay 的同库输出比较：

| 历史 | 事件 | 实体 | 事实 | SELECT（含最后两张表输出） | INSERT 执行 | 耗时 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 开局 | 3433 | 3433 | 0 | 7 | 1 | 0.3703s |
| 现成八个月任免案 | 4813 | 3454 | 1359 | 8 | 3 | 0.6618s |

命令 `PYTHONPATH=$PWD .venv/bin/python /tmp/replay1992.py`，两档输出均 `equal: true`。八个月存档来自已有 `tests/test_court.py::test_common_declaration_updates_entities_and_displaces_incumbent_atomically[holders-first_night]`，不是另造业务夹具。额外固定开销均为 10 次 PRAGMA、9 次 CREATE（临时读库的表及索引）。每页至多 1000 条通知；实体累进状态的内存随实体及其状态大小增长，非总内存有界。

## 验证与变异

- CLI 既有案扩充开局、历史、连续两次、坏事实表缺行／多行比对。修前 `10776 != 3592` 红；修后绿。恢复旧 CLI 分别重建实体和事实的逻辑，真实入口再次 `7184 != 3592`，`1 failed in 3.01s`；随后恢复共享重建逻辑。
- `LedgerReplay` 复用已有生成序列与回滚案：比较实体行与聚合 snapshot；失败后新建 Ledger 验证事件、实体、事实仍为原值，再正常提交。未增平行测试函数。
- 在 `ming/middle/calendar.py` 暂加 `import ming.ledger.tables`，`lint-imports` 输出 `3 kept, 1 broken`，点名该非法导入；移除后 `4 kept, 0 broken`。
- `.venv/bin/python -m pytest -q tests/test_ledger.py tests/test_opening.py tests/test_secrets.py` → `15 passed in 33.81s`。
- 八个月案＋CLI 重建案 → `2 passed in 15.53s`。
- `.venv/bin/pyright --pythonpath .venv/bin/python` → `0 errors, 0 warnings, 0 informations`；触及文件 `ruff check` → `All checks passed!`。
- 自审将新增 `Court.records` 并入已有 `Court.read_records`，删去平行入口；CLI 用原入口的新增 replay 选项一次读取实体与事实。
- 最后聚焦调用（本腿 runId `01a180fe-a9d1-74bb-8484-61260ab2fc3f`，跑时 HEAD `1f2d13220c74df389c8af1d339fbfc1d36a7e169` 加本片工作区）：`.venv/bin/python -m pytest -q tests/test_ledger.py tests/test_opening.py tests/test_secrets.py 'tests/test_month_steps.py::test_month_pays_affair_from_declaration_month[regular]' 'tests/test_court.py::test_common_declaration_updates_entities_and_displaces_incumbent_atomically[holders-first_night]'` → `17 passed in 56.42s`。同次随后 ruff、pyright、lint-imports、diff --check 均通过。
- 未跑全量，未 push／开 PR／merge；ADR 0159、0160 与 CONTEXT 修订待评审。第一片交卷时 Q4/Q5、跨提交边界与错误常驻案仍待施工，不以已有权限测试通过替代它们。

## 续修：Q4/Q5

复用原 `read_once`，不建并行读口。SQLGlot 的作用域解析从真实查询取得表、不可变等值／IN 条件及 JSON 数据字段依赖；返回的整行数据另依赖实际返回的实体 ID。父读收集子读依赖，命中缓存也传递依赖。落账用本次 recordings 的建立、修改字段与新增事实使相交依赖失效；没有实体字段变化的 Recorded 不冒充实体建立。其他 SQL 谓词保留较宽依赖，不复制权限规则，不按业务 kind 列免检名单。

products 的月份及 month_open 截止位现统一从 calendar_row 显式绑定（前轮遗漏的另一 MONTH_OPEN 表达式由下节 F2 修正）；既有 AVAILABLE 权限条件未改。落账引用按 `(kind, key)` 成批读取；已有 owner 直接传其 snapshot；入殿名单、已知谕旨的议处／选择／暂行记录成批读。引用顺序、原录件输入、权限和材料均不改。

### 生态选择与成本

仓内已有 `read_once`、SQLAlchemy 查询键、NetworkX；没有 SQL 作用域分析器。先查官方资料，再选现成 SQLGlot 解析而不是自造 SQL 遍历器；不翻 eventsourcing 源码推断接口。

- [SQLGlot AST primer](https://github.com/tobymao/sqlglot/blob/main/posts/ast_primer.md)："Scope is a traversal module that handles more semantic context of SQL queries." 其例用 `build_scope`、`root.traverse()`、`selected_sources`；`find_all_in_scope` "doesn't traverse into subqueries"。
- [SQLAlchemy 编译器文档](https://docs.sqlalchemy.org/en/20/core/internals.html#sqlalchemy.sql.compiler.SQLCompiler.construct_expanded_state)："this method will provide for both the finalized SQL string as well as the parameters that would be used for a particular parameter set." 用原生 CacheKey、`construct_params(extracted_parameters=...)` 和 `construct_expanded_state()` 复用结构编译、绑定本次实参；不是自拼 SQL。只把 JSON object 的键用原生 `render_literal_execute()` 展开以供解析，业务值仍是参数。
- [SQLAlchemy Tuple IN](https://docs.sqlalchemy.org/en/20/core/operators.html#tuple-in-expressions) 的 `tuple_().in_()` 承接成批复合条件；[NetworkX](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.components.connected_components.html) 的 `connected_components()`（"Generate connected components."）承接 SQL 等值关联，不自写图遍历。
- [SQLGlot 安装说明](https://github.com/tobymao/sqlglot#install) 提供 `sqlglot[c]`；README 原句："It is roughly 3-5x faster than the pure Python version"。本包无自定义 dialect 子类。此前纯 Python 解析密件样本超时；改用官方编译版，并修掉重复结构编译。
- [cachetools](https://cachetools.readthedocs.io/en/stable/#cachetools.LRUCache) 的 LRUCache："This class discards the least recently used items first to make space"。跨提交复用不再自然清空，普通字典会积累历次查询、无界占用内存，且下游无容量回收；标准库 `lru_cache` 又不支持逐键删除，故直接换有界现成容器，不造淘汰器。每 Ledger 至多 10000 个结果／依赖条目；结构编译和 SQL 作用域各至多 128 项，后者用标准库 `lru_cache`。这是条目数界，不是字节界；单项仍随该需求合法读取的材料量增长，未截断材料。容量淘汰不是测试里的重复豁免。

初版依赖分析把每组参数都重新编译：真实 HTTP 月结的 cProfile 中 `query_scopes` 占 7.519s，作用域解析仅 1.076s。改为复用库编译对象后，同组月结＋密件样本由 `37.06s` 降至 `15.71s`。这是聚焦样本时间，不冒称全量或产品墙钟。

最终单案 SQL 执行点观测到结果缓存最多 297 项；编译缓存 39 项、作用域缓存 60 项，均未触及容量。一次提交对缓存依赖去重后与本次变化相交，不增加数据库读取。材料与角色返回内容不做散文指纹或措辞断言。

### 同口径 SQL 拆分

命令：`SQL_REPORT=/tmp/1992-after-q4.json PYTHONPATH=/tmp:$PWD .venv/bin/python -m pytest -q -p probe1992 -p duplicate1992 --tb=line --show-capture=no 'tests/test_month_steps.py::test_month_pays_affair_from_declaration_month[regular]'`。

结果原文：`1 passed in 4.91s`；`call statements 714`；`READ_OBSERVATION {'selects': 304, 'rows': 17906, 'repeats': 0}`。读预算的额外 DBAPI 观测不计入应用 SQL。以下调用者 × 表覆盖全部 304 次 SELECT；E/F 含该语句内的关联子查询，不把表参与冒称返回行依赖。

| 调用者 | 表 | 修前 | 第一片 | 续修 |
| --- | --- | ---: | ---: | ---: |
| calendar.calendar_row | E | 37 | 37 | 3 |
| calendar.journeys_due | E | 4 | 4 | 2 |
| court.current_decrees | E+F | 2 | 2 | 2 |
| court.errands | E+F | 2 | 2 | 0 |
| court.interactions | E+F | 37 | 37 | 5 |
| court.month_petitions | E+F | 2 | 2 | 2 |
| court.nights | E+F | 37 | 37 | 1 |
| court.pending_nights | E+F | 5 | 5 | 1 |
| court.pending_petitions | E+F | 37 | 37 | 3 |
| court.pending_pushes | E+F | 2 | 2 | 2 |
| court.petition_officials | E | 16 | 16 | 8 |
| court.petition_products | E+F | 2 | 2 | 1 |
| court.products | E+F | 67 | 67 | 35 |
| court.record_catalogue | E+F | 22 | 22 | 22 |
| court.returned_petitions | E+F | 41 | 41 | 4 |
| court.unhandled_monthly | E+F | 37 | 37 | 3 |
| dispatch.dispatch | E+F | 2 | 2 | 1 |
| dispatch.landing_entities | E | 6 | 6 | 1 |
| dispatch.landing_sources | E+F | 16 | 16 | 5 |
| fiscal.Accounts.__init__ | E | 4 | 4 | 4 |
| fiscal.due_levies | E | 2 | 2 | 1 |
| fiscal.Accounts.run | E+F | 2 | 2 | 2 |
| view.entities | E / E+F | 19 / 32 | 19 / 32 | 11 / 17 |
| view.month_open | E+F | 2 | 2 | 2 |
| view.project | E+F | 5 | 5 | 5 |
| 取聚合（修前含快进）：fiscal.Accounts.__init__ / court.record_product / court.record | 事件 | 344（合计） | 153 / 7 / 1 | 153 / 7 / 1 |
| 初始化／落账／跟随者 | 事件 | 427 | 0 | 0 |
| 进度读取 | tracking | 684 | 0 | 0 |

总 SQL `3207 → 1011 → 714`；SELECT `1895 → 601 → 304`；E/F 读取 `440 → 440 → 143`。续修仍是事件写 322、实体写 36、事实写 36、PRAGMA 16，合计 714；无 tracking，落账不回读事件。保留的 161 次聚合未命中按票面已声明的官方缓存行为统计，不冒称消除了它们。

### 常驻与变异证据

未新增测试用例函数或业务夹具；把既有 `test_read_budget` 监听器提成共享观察器，仍执行真实 SQL。比较同一 engine、SQL、参数下的行身份、实体字段变更版本和选定结构化输出；只有附加事实、没有实体字段 changes 时，不推进实体状态版本。模型正文、data 文本不哈希、不锁定。

- 正确：既有 regular 月结案断言重复列表为空；同口径旧 clear 变异检出 307 次，修后为 0，不以 SELECT 总数减少替代此证据。
- 无关／相关提交边界：既有召对连续 say、翻译、重开案，未改月历时每个 Ledger 的月历需求只读一次；推进月份后多读一次，并断言日期为 11。旧 clear 变异得 `assert {1, 19} == {1}`。重开产生不同 engine，不把新 Ledger 的首次读取算重复。
- 不同需求边界：既有 `test_translation_queries_preserve_two_table_permissions` 保留 night/month 两案及原 `declarations_1972.json` 录件；官职、保定府新城县、郭允厚等不同取阅的原结构化结果断言不变。
- 前轮已知批量错误证据（F3 判定不足，现已替换）：入殿工具案检查多个人的参数同批进入查询，且无逐个 `(person, name)` 查询；恢复旧逐人查后 `assert not True`，`1 failed in 4.41s`。新的按类判定及两种形状变异见下节。
- 依赖传递回归：把父读的依赖合并临时改成空集合，真实召对入口得 `assert {'王承恩'} == {'杨嗣昌', '王承恩', '王绍徽'}`，`1 failed in 1.92s`；不是只关失效求少读。三处变异已恢复。

clear 变异命令：`PYTHONPATH=/tmp:$PWD .venv/bin/python -m pytest -q -p duplicate1992 --tb=line --show-capture=no 'tests/test_month_steps.py::test_month_pays_affair_from_declaration_month[regular]' 'tests/test_audience.py::test_nights_are_persistent_and_translate_only_after_dismissal[first_night-approved-approved]'` → `2 failed in 7.28s`。

另两处变异均用：`.venv/bin/python -m pytest -q --tb=line --show-capture=no 'tests/test_audience.py::test_scene_tools_use_physical_location_not_office_and_project_dossiers'`。

聚焦验证（跑时 HEAD `5effbcdfa42b48c36caeaf269bb7b33dbc7b58bc` ＋续修工作区，本腿 runId 同上）：

```sh
.venv/bin/python -m pytest -q --tb=line --show-capture=no tests/test_ledger.py tests/test_opening.py tests/test_secrets.py
# 15 passed in 45.07s
.venv/bin/python -m pytest -q --tb=line --show-capture=no tests/test_read_budget.py \
  'tests/test_audience.py::test_nights_are_persistent_and_translate_only_after_dismissal' \
  'tests/test_audience.py::test_scene_tools_use_physical_location_not_office_and_project_dossiers' \
  'tests/test_court.py::test_translation_queries_preserve_two_table_permissions' \
  'tests/test_court.py::test_common_declaration_updates_entities_and_displaces_incumbent_atomically[holders-first_night]' \
  'tests/test_month_steps.py::test_interim_costs_follow_promulgation_not_backing'
# 16 passed in 36.85s
```

前述独立 regular 单案为第 32 个通过的聚焦参数案。未跑全量、未 push／开 PR／merge、未送大理寺；ADR 修订仍待评审。临时 threading/cProfile 探针曾超时，已改用 HTTP action 上的标准 cProfile；不把探针失败当测试通过或基础设施故障。

前轮自审记录：入口沿用 HTTP／模型工具／CLI，未造内部函数测试；断言移除正文比较，只保留结构化状态与真实查询参数，并纠正 JSON null 的 changes 不应推进实体字段版本。前轮对「退役已齐、实现范围无剩余」的结论不成立：遗漏 CLI 异步调用边界、tracking 测试引用及另一月份表达式，按以下封驳续修。

## F1–F3 封驳续修（基于 90a9e64c3）

### 修法与边界

- F1：`Court.read_records` 内无异步工作，改回同步调用，CLI、Web、模型工具三个调用方一并改；不加线程桥接或嵌套事件循环适配。Python [asyncio.run 官方文档](https://docs.python.org/3/library/asyncio-runner.html#asyncio.run) 明示：“This function cannot be called when another asyncio event loop is running in the same thread.” `audit` 夹具、原模型回调及业务断言不变。
- F1：`LANDING` 删除退役 tracking 查询及其等式，只观察事件和事实；保留提交前故障注入、落账有无、库银回滚及重试断言，明确检查故障前可见的事件和 landed 行均未持久化。没有恢复进度表来迁就测试。
- F2：复用 `month_open(ledger)` 作为唯一的本月截止位表达式，日期来自 `calendar_row`；实体快照和事实权限查询共同引用。`fact_sources` 从一次性全局表改为既有 `read_once` 缓存的查询构造，不重复构造同一需求；重建使用重建库的月历。删除另一内嵌 `MONTH_OPEN`，不改来件排除的基线 `AVAILABLE`。
- F3：原 `replaying` 只增加对实际发出 `ModelResponse` 的记录；原 `measure_reads` 按这份请求序列的当前位置、engine、实际 SQL 分组，记录完整实体单行结果的 `(kind, key)`。原入殿案据真实 `set_hall.add` 检查：同一请求中同一 SQL 不得逐次返回已知批量中的多个不同单体。不匹配参数元组，不预定按名字还是按 UUID 查询；先后请求不会合组。没有替换工具或数据库行为、没有新增测试函数或夹具。继续使用 [FunctionModel 官方接口](https://ai.pydantic.dev/api/models/function/#pydantic_ai.models.function.FunctionModel)：“A model controlled by a local function.”

### 红绿与变异

同一 F1 命令，在修前 `11 failed, 3 warnings in 11.91s`（2 例月份停在 10，9 例 `no such table: readmodel_tracking`）；修后 `11 passed in 25.27s`：

```sh
.venv/bin/python -m pytest -q --tb=line --show-capture=no \
  'tests/test_month_steps.py::test_two_nights_feed_world_and_arrivals_wait_for_audience' \
  'tests/test_month.py::test_month_lands_both_sides_at_source_stock_and_preserves_nominal'
```

F3 沿用前节入殿工具案命令：

1. 恢复 `for name in dict.fromkeys(add): ledger.entities(kind="person", key=name)` 的逐人查询：新类判定 `assert False`，`1 failed in 2.61s`。
2. 保留批量查人，再对每人的 UUID 调 `ledger.entities(entity_id=e["id"])`：同一类判定 `assert False`，`1 failed in 2.55s`。这一路没有旧 `(person, name)` 哨兵形状。
3. 恢复批量生产实现：`1 passed in 2.58s`；`git diff -- ming/middle/scene.py` 为空，两处变异均已还原。

### 扩大的触及面与结果

此前聚焦覆盖不足。本轮纳入全部使用 `audit` 的测试文件、整个 `test_month.py`，以及直接 CLI、工具权限和读量边界；这是入口替换的触及面，不是全量：

```sh
.venv/bin/python -m pytest -q --tb=line --show-capture=no tests/test_month.py tests/test_month_steps.py tests/test_audience.py tests/test_court.py tests/test_web.py tests/test_secrets.py tests/test_travel.py tests/test_opening.py tests/test_cli.py tests/test_read_budget.py
# 165 passed in 337.64s (0:05:37)
```

耗时为串行中型测试的实际总时间，不称小型/秒级整套测试，不以该结果冒称 CI 全量通过。另单独复核 F2 的召对月界、regular 月结、opening/replay：`10 passed in 20.22s`。

```sh
SQL_REPORT=/tmp/1992-after-fixes.json PYTHONPATH=/tmp:$PWD .venv/bin/python -m pytest -q -p probe1992 --tb=line --show-capture=no 'tests/test_month_steps.py::test_month_pays_affair_from_declaration_month[regular]'
# 1 passed in 4.75s
# SQL_REPORT /tmp/1992-after-fixes.json call statements 714
# READ_OBSERVATION {'selects': 304, 'rows': 17906, 'repeats': 0}
```

总 SQL、SELECT、E/F 查询仍为 714／304／143；Q4 月结样本仍零重复。缓存观测峰值变为 309 项，编译缓存 38 项、解析缓存 60 项，仍在原上界内。前表原 `view.month_open` 的两次实体快照事实读取现由 `view.entities` 直接发起，合计没有变化。来件所报召对 `record_catalogue` 的保守失效线索，本轮不外推为已消除。

以上跑时 HEAD 为 `90a9e64c3516ec048de884d74473cca706a45e03` 加本轮工作区，本腿 runId 同前。ruff、pyright、四条 import-linter 合约均通过。自审：无新增生产函数或测试函数；入口仍为 HTTP／CLI／模型工具；删除字面参数哨兵，只断言结构化实体归属及状态；退役 tracking 引用、内嵌 MONTH_OPEN 和无意义 async/await 调用均删除。不推送、不派发角色、不以施工代评审。

## 删应用层机制（基于 2239a891e）

新版票面 `updatedAt=2026-10-28T15:39:37Z`；给事中 `01a1832a-d16d-7fbf-a19e-932f5273bb77@countersign`、符宝郎 `01a18332-8144-7dd4-8e41-2b3a77bbf309@notary` 均署。官方例文链接与原句见 ADR 0160「官方能力依据」。本轮没有保留缓存的 A/B 设计选择，也没有新增替代机制。

### 实施与退役

- `Ledger.read` 直接经记录器事务、Session 按条件查询，返回普通 dict；`get` 仍用 `repository.get`。删除全部 `read_once`、结果缓存、锁、键、依赖分析、编译／解析缓存和提交后失效。事件与读表同事务、回滚时淘汰库聚合缓存、显式分页重建均保留。
- 删除 `deepfreeze`、`ReadData`、冻结 `ReadView`；视图直接使用 Pydantic BaseModel。删除 sqlglot、cachetools、frozendict 依赖；NetworkX 仍供既有 `opening.py` 构造开局图，不能随 SQL 分析用途一起误删。
- `presentation` 一次取月历、交互、当前夜，传给已有下游；最新夜查询所得行直接用于夜投影。`Game.start → accept` 传已算的 state；`Month.resume` 不再为同一分支重复取 pending/draft。模型工具一次确定本次身份，实体投影共享本次查询参数；未跨模型请求、await 后重新取阅或前端推送存结果。
- 月度落账材料复用判定落账模式时读出的议处／选择，当前旨意的既往 interim 和密令知情人各批读一次，删除逐旨包装；仍用原 `known_people` 权限表达式。落账补在任者时不重读手里已有的人。
- 退役旧 SQL 同文同参／版本比较观察器、跨提交零重复与日历参数哨兵。保留返回行预算、通知唯一性与入殿已知批量断言；`/state` 在单个请求内观察完整实体行 ID，不跨请求判等。密令断言移到模型实际收到的结构化材料，预期知情人不变；不再拿同一个查询 helper 的结果作预期。

### 红绿与变异证据

```sh
.venv/bin/python -m pytest -q --tb=line --show-capture=no \
  'tests/test_read_budget.py::test_http_read_work_ignores_unrelated_history[state-night]'
```

删除缓存但未合并调用时：`1 failed in 2.21s`，同次 `/state` 的当前夜／月历行被读取 4／6 次。合并后连同 regular、holders 两案：`3 passed in 7.52s`。装回 `pending_petitions()` 自取月历的旧调用：`1 failed in 1.46s`，实体读取次数为 `{1, 2}`，恢复后继续聚焦验证。

```sh
.venv/bin/python -m pytest -q --tb=line --show-capture=no \
  'tests/test_audience.py::test_scene_tools_use_physical_location_not_office_and_project_dossiers'
```

装回逐人 `ledger.entities(kind="person", key=name)`：`1 failed in 1.66s`，`assert False`。已恢复原批读，`scene.py` 无最终 diff。

### 聚焦验证与耗时边界

- 施工前 regular＋holders：`2 passed in 16.48s`；删机制并改调用后相同两案：`2 passed in 6.30s`。这是两案的实测，不推算全量 CPU 或全量占比。
- `tests/test_read_budget.py tests/test_audience.py`、官职取阅两案、全模型身份案、`tests/test_opening.py tests/test_ledger.py`：`28 passed in 31.89s`。
- `tests/test_month_steps.py tests/test_secrets.py tests/test_web.py`：初跑 `5 failed, 55 passed in 72.68s`，五个失败都是旧测试调用已退役 `Court.known_people`。改为读取真正发送的材料并保留原预期；这五案复跑 `5 passed in 11.98s`。
- `tests/test_month.py tests/test_court.py tests/test_cli.py`：`77 passed in 120.13s`。它们是中型串行行为验证，不称小型测试。
- 裸调 `.venv/bin/pyright` 未找到虚拟环境包，报 2450 个导入派生错误；改用 `.venv/bin/pyright --pythonpath .venv/bin/python`：`0 errors, 0 warnings, 0 informations`。未因此改配置或压断言。
- 最后聚焦：`tests/test_read_budget.py`、入殿工具案、`tests/test_secrets.py`、月结原子落账案，`23 passed in 45.88s`。命令前缀均为 `.venv/bin/python -m pytest -q --tb=line --show-capture=no`；同时 ruff `All checks passed!`、pyright 零错误、`PYTHONPATH=. .venv/bin/lint-imports` 四合约 kept、`git diff --check` 无输出。
- 提交前自审：逐文件 AST 对比 HEAD，无新增生产／测试函数，diffItems 为空。入口：移除了密令测试对退役 helper 的调用，改观察 HTTP 链路实际发送给模型的材料；断言：删除跨请求 SQL／参数哨兵，只保结构化行 ID、预算、材料值，未发现新增盯文；退役：缓存、分析器、冻结类型、专用依赖、逐旨包装及失效测试均在 diff 中删除。

### 同案完整 SQL 拆分

同一临时 SQLAlchemy `after_cursor_execute` 探针 `/tmp/probe1992_direct.py`，不替换应用读取。只计 regular 的 call 段；查询返回行用独立 DBAPI cursor 观察，不计入应用 SQL。前态为独立工作树 `2239a891e`，后态为本轮工作区。探针有明显观察开销，**以下探针耗时不作应用性能结论**。

```sh
SQL_REPORT=/tmp/1992-direct-after.json PYTHONPATH=/tmp:$PWD \
  .venv/bin/python -m pytest -q -s -p probe1992_direct --tb=line --show-capture=no \
  'tests/test_month_steps.py::test_month_pays_affair_from_declaration_month[regular]'
# 前态同命令，使用主工作树 venv 的绝对路径，输出 /tmp/1992-direct-before.json
```

| call 段 | 2239a891e | 本轮 |
| --- | ---: | ---: |
| 全部 SQL | 715 | 1265 |
| SELECT（含 WITH） | 305 | 855 |
| 返回行 | 17906 | 18430 |
| 实体／事实查询 | 144 | 694 |
| 聚合未命中回读 | 161 | 161 |
| tracking SQL／写后事件回读 | 0 / 0 | 0 / 0 |
| 事件 INSERT | 322 | 322 |
| 实体 INSERT 执行 | 36 | 36 |
| 事实 INSERT 执行 | 36 | 36 |
| PRAGMA | 16 | 16 |

删除跨请求缓存后 SQL 增加，如实保留；不以 SQL 相同冒称业务重复，也不以减少查询数替代提速。E＝entities，F＝facts，L＝ledger_events；按最近业务调用者拆 SELECT（未出现项为 0）：

| 调用者 | 表 | 前 | 后 |
| --- | --- | ---: | ---: |
| calendar.calendar_row | E | 3 | 197 |
| calendar.journeys_due | E | 2 | 4 |
| court.current_decrees | E+F | 2 | 2 |
| court.errands | E+F | 0 | 2 |
| court.interactions | E+F | 5 | 49 |
| court.month_petitions | E+F | 2 | 6 |
| court.nights | E+F | 1 | 47 |
| court.pending_nights | E+F | 1 | 7 |
| court.pending_petitions | E+F | 3 | 50 |
| court.pending_pushes | E+F | 2 | 2 |
| court.petition_officials | E | 8 | 16 |
| court.petition_products | E+F | 1 | 2 |
| court.products | E+F | 35 | 80 |
| court.record | L | 1 | 1 |
| court.record_catalogue | E+F | 22 | 22 |
| court.record_product | L | 7 | 7 |
| court.returned_petitions | E+F | 4 | 49 |
| court.unhandled_monthly | E+F | 3 | 45 |
| dispatch.dispatch | E+F | 1 | 2 |
| dispatch.landing_entities | E | 1 | 0 |
| dispatch.landing_sources | E+F | 5 | 16 |
| fiscal.__init__ | E / L | 4 / 153 | 4 / 153 |
| fiscal.due_levies | E | 1 | 2 |
| fiscal.run | E+F | 2 | 2 |
| view.decree_nights | E | 1 | 30 |
| view.entities | E / E+F | 11 / 19 | 19 / 34 |
| view.project | E+F | 5 | 5 |

观察文件含逐句 SQL、参数、调用链与返回行数；拆分复算在 `/tmp/1992-direct-{before,after}-counts.txt`。前态和后态探针分别 `1 passed in 15.20s`、`1 passed in 10.29s`。

**未作终验**：本轮不是最终待合并状态，未运行全量，也未推送、开 PR、合并或派审。票面要求的 `1f2d13220`／最终 HEAD 全量串行 cProfile、全量 CPU 对照与十分钟 CI 仍由最终待合并轮执行，不用上述单案替代；ADR 修订仍待评审。
