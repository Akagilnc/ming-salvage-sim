# 读表与事件同事务写；读按条件查，读量不随无关历史增长

Status: accepted（2026-10-22 owner grill 定方向：「那肯定是优先用库的做法而不是自己去写。不然还用库干什么。A」；spec #1959 v3 经中书省、给事中、符宝郎三席署过；符宝郎五题 owner `aac1e468`「1A 2A 3B 4A 5A 可以」）

#1992 修订待评审：按 [现行票面](https://github.com/Akagilnc/ming-salvage-sim/issues/1992) 替代跟随者、tracking 与旧重建实现，并撤销应用层读缓存、依赖分析及只读转换。现行票面顶部修订覆盖旧 Q4/Q5；施工原话及完整源卷 UUID 见票面，分轮 SQL 拆分与变异证据见 [施工记录](../1992-ledger-write-slice.md)。

原问题：重写后的账本只有一张 `entities` 表，每个实体一行，`data` 和整份事件列表 `events` 都是 JSON 列；中间层的每一个小问题（今天几号、这夜什么状态、按名找人）都是全表 `SELECT` 再在 Python 里挑。一次 `presentation()` 要全表读 (8+2N) 次、重放 N 个夜（N＝夜数），而它挂在每次落账和每个流式片段上。57 个录播测试跑四分半，一个月级测试里全表读近三千次。病在两处：**一件小事查整个世界**；**事件在事件库之外又存了一份**（`events` 列，以及聚合 `Entity` 身上的 `events` 列表）。[0159](0159-ledger-entities-events-and-landing.md) 当初以「库在 SQLite 上维护不了查询表」为由自写内联刷新，这个前提经核不成立（见文末）。

## 决定

- **真源只有事件库**。删除 `entities.events` 列与聚合 `Entity` 身上的 `events` 列表；「有哪些事实」一律从事实读表按实体取。
- **落账直接写读表**：`Ledger.commit` 在 eventsourcing-sqlalchemy 的 `recorder.transaction()` 内调用 `events.save()`，再用手里的聚合写实体最终态、用返回的 recordings 写 Recorded 事实。删除 `ProcessApplication`、`Follower`、运行器、tracking 与写后回读；不继承记录器。`events.save()` 只在 `Ledger.commit` 调用，`ming.ledger.tables` 的 import-linter 合约守住写表入口；负向样本是在中间层导入该模块。
- **同一事务原子提交**：一次落账的事件与读表行全落或全不落；在实际写行后、提交前中断，重开后两者都没有。依据 [eventsourcing-sqlalchemy 官方外层事务示例](https://github.com/pyeventsourcing/eventsourcing-sqlalchemy#managing-transactions-outside-the-application)：“Everything will commit atomically when the `Transaction` context manager exits.” 不自写事务适配层。
- **「事件→状态」的规则只此一处**：在 `Entity` 的 `@event` 方法里；正常落账使用已经演进的聚合，重建使用库的 `mutate()`，不另写一份合并规则。实体行在一次提交里各写一次，事实行保留对应通知 ID。
- **显式重建，开档不追平**：同事务读表不会落后，正常开档不读进度、不重建。`ming read --replay` 保留：在空的临时读表上重建，不改源存档。一次命令的实体和事实共用一次结果；通过 `LocalNotificationLog.select(start, limit)` 每页 1000 条顺序读全部事件，每条只处理一次。临时保存每个实体的累进状态，事实随页写、实体最终态扫描完后各写一次；两种路径共用落账的写行函数。通知页有界，但全部实体状态的临时工作集随实体数和状态大小增长，无固定上界；只活在本次操作内。源页读取在目标库事务之外，避免库的线程级事务复用到另一个库。不做自动迁移或坏表自动修复。
- **读表两张**：实体读表（id、kind、key、data；索引 kind 与 (kind, key)）；事实读表（追加式：实体 id、kind、日期、正文；不设夜 id 列）。
- **合理查询**：每个问题只读回答它真正需要的材料，不读与它无关的历史。账本对中间层开窄读口：按 id、按 kind、按 (kind, key)；事实按实体（可加 kind、日期）、按 kind；替换中间层现有的全部全表读调用。`/state` 只读当前画面需要的材料（如最近一夜、本月未批奏疏），不读已结的历史。凡材料契约本身就要求整类、整份的读（审计与世界视图的「取全部」、转译名册与字段表、月初皇帝视图快照、`scene_material` 的接不住清单、人物履历、本夜轮次、模型自主取阅）照原契约读；不建豁免清单，不开具名通道，模型与前端看到的材料都不变。模型用 `read_records` 的读法现由 [#1970](https://github.com/Akagilnc/ming-salvage-sim/issues/1970) 取代：目录进输入，只给类或日期列名单，点正名才给全文，空参正常提示；权限不变，前端 `/records` 仍按皇帝身份整份读。射程已扩到所有模型调用并加官职三态，见 [0162](0162-every-model-reads-one-way-and-speaks-as-a-person.md)。
- **聚合缓存开着**（`AGGREGATE_CACHE_MAXSIZE=10000`），单个应用实例写入，关闭快进（`AGGREGATE_CACHE_FASTFORWARD=n`）；不开 snapshotting。未命中仍由库读该实体的历史重建，重入复用原实例时保留缓存。依据 [官方缓存文档](https://eventsourcing.readthedocs.io/en/stable/topics/application.html#configuring-aggregate-caching)：“Only do this when only one instance of the application is being used to evolve the state of the aggregates”。
- **读表按条件现查**：照官方示例，不维护应用层结果缓存、提交失效、SQL 依赖分析或只读转换。一次调用已经取得的材料直接传给下游，已知成批需求按条件批读；不同请求各自现查，不以同 SQL 同参数或提交间隔判重复。本票的 `products` 月份过滤和 `month_open` 截止位仍由 `calendar_row` 显式给定，既有权限与模型材料不变。
- **presentation 便宜但仍按提交推送**：前端把 `state` 与 `done` 一视同仁整份接收，核账期靠逐次提交的推送显示进度，所以每次提交推一份保留；流式 `delta` 仍是 `{text, hall}`，`hall` 每片段按夜 id 读一次，不再每片段重算整份 presentation；前端不改。
- **不变量**：同一请求、相关材料相同、只有无关的已结历史多少不同的至少三局，`GET /state` 与 `POST /actions`（say／month／choose）的 SQL 读量（条数与返回行数）相等；另加未召对的新开局测 `/state`。相关材料增长不判违规，不得为凑等量裁材料；现状必须红、修后转绿。这是「一件小事不查整个世界」的机械表述，不锚墙钟；哪些历史对哪个请求无关按各请求的材料契约定，计量接法留施工。
- **示范模块**：月历与夜。最热的两条读路径，一块完整的「落账与读表同事务写 → 按条件读 → 预算测试覆盖」，之后的人物、账户照抄。
- recorder 保持 eventsourcing-sqlalchemy。

## 考虑过、没选

- **跟随者维护同事务读表（#1959 旧选）**：#1992 撤回。它为跨应用处理通知保留的进度与回读，在这里都是额外工作。改用库官方外层事务能力；唯一写者以账本入口和 import-linter 合约约束，窄读口与不存重复事件的决定照旧。
- **提交后另开事务刷读表**：会打开事件与读表不一致的窗口，需要额外幂等与追平；官方外层事务已经能原子写两者，不选。
- **只数 SQL 条数当不变量**：把 (8+2N) 次全表读合成一次全表读，条数恒定、测试照绿，病原样还在。
- **所有请求条数与行数无条件恒定＋封闭的整类读豁免清单**：相关材料（履历、本夜轮次、模型自主取阅）本就随请求增长，硬比会逼着裁材料；豁免清单要持续维护且会遮住清单内的读放大（给事中封驳、owner `f5b66688` 第 1、2 题）。
- **结构版本变化时开档自动清表重建**：未经裁定的自动迁移机制，本票不加（owner `f5b66688` 第 3 题）。
- **按 kind 拆成人物表、账户表、月历表**：kind 是开放的（声明可建任意 kind），表的集合会变成一件要维护的事。
- **换 recorder（SQLAlchemy → 内置 sqlite）**：两者都能同事务写自定义表、都有 Process/Tracking recorder；recorder 不是病根。
- **墙钟阈值当验收**：锚在机器速度上，会 flake，也查不出原因。
- **删掉按提交推送、一次请求只算一次 presentation**：前端核账期进度依赖逐次推送，去掉是体验倒退。
- **只删表列、保留 `Entity.events`**：「事件→现状」会有聚合快照与策略两条投影路，重建相等变成两份逻辑互相对照，守不住策略本身。
- **把一夜内多次提交合成一次事务**：改变「事实先成行」的时点，是账本语义题，不夹在本票。

## 官方能力依据（#1992 替代源码推断）

- [Application 3：Content management](https://eventsourcing.readthedocs.io/en/stable/topics/examples/content-management.html)：`return self.repository.get(page_id)`；`_details_from_page` 直接 `return { ... }`。本仓保留库聚合缓存，删除额外结果缓存和冻结层，不照搬示例中本票未授权的 snapshotting。
- [Application 4：Searchable timestamps](https://eventsourcing.readthedocs.io/en/stable/topics/examples/searchable-timestamps.html)：`version = recorder.get_version_at_timestamp(tracking_id, timestamp)`，再 `self.repository.get(tracking_id, version=version)`。预先写好索引、请求时现查；本仓使用已定 SQLAlchemy 外层事务及 Session 查询，不换 recorder。
- [Application 7：Vertical slices](https://eventsourcing.readthedocs.io/en/stable/topics/examples/shop-vertical.html)：`tuple(_Globals.app.events.get(originator_id))`。每次读切片现取；不移植其全事件扫描到本仓正常读表路径。

- [eventsourcing-sqlalchemy 官方 README](https://github.com/pyeventsourcing/eventsourcing-sqlalchemy#managing-transactions-outside-the-application)：“Sometimes you might need to update an SQLAlchemy ORM model atomically with updates to your event-sourced application.” 这就是本仓需要的能力，不需要另加跟随者或记录器子类。
- [Application 文档](https://eventsourcing.readthedocs.io/en/stable/topics/application.html)：`save()` 返回 recordings，通知日志可以顺序分页；“The selection will contain no more than the specified limit.” `LocalNotificationLog` 的 section_size 与每次 select 的 limit 均显式设为 1000。
- [Domain 文档](https://eventsourcing.readthedocs.io/en/stable/topics/domain.html)：“The object returned by calling the mutate() method on one aggregate event object can be passed in when calling the same method on another aggregate event object.” 重建只用这一套库规则恢复状态。
- [Persistence 文档](https://eventsourcing.readthedocs.io/en/stable/topics/persistence.html)：通过 Mapper 的 `to_domain_event()` 将存储事件还原为领域事件。
