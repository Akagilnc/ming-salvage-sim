# #1992 落账、重建与读复用施工记录

以下第一片记录对应 `5effbcdfa42b48c36caeaf269bb7b33dbc7b58bc`，保留当时结论；当时的续修前置已由后续用户指令解除。Q4/Q5 续修及现状见后半篇，不再把失效算法选择作为外部缺前置，未送大理寺。

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
