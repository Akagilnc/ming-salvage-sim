# 读表由库的投影维护；读按条件查，查询数与行数不随世界大小增长

Status: proposed（2026-10-22 owner grill 定方向：「那肯定是优先用库的做法而不是自己去写。不然还用库干什么。A」；中书省两轮十二题审读后落为 spec #1959 v2，本文与之同步）

重写后的账本只有一张 `entities` 表，每个实体一行，`data` 和整份事件列表 `events` 都是 JSON 列；中间层的每一个小问题（今天几号、这夜什么状态、按名找人）都是全表 `SELECT` 再在 Python 里挑。一次 `presentation()` 要全表读 (8+2N) 次、重放 N 个夜（N＝夜数），而它挂在每次落账和每个流式片段上。57 个录播测试跑四分半，一个月级测试里全表读近三千次。病在两处：**一件小事查整个世界**；**事件在事件库之外又存了一份**（`events` 列，以及聚合 `Entity` 身上的 `events` 列表）。[0159](0159-ledger-entities-events-and-landing.md) 当初以「库在 SQLite 上维护不了查询表」为由自写内联刷新，这个前提经核不成立（见文末）。

## 决定

- **真源只有事件库**。删除 `entities.events` 列与聚合 `Entity` 身上的 `events` 列表；「有哪些事实」一律从事实读表按实体取。
- **读表由库的投影维护，不由落账代码直接写**。用 eventsourcing 的 `ProcessApplication`／`Follower`，运行器 `SingleThreadedRunner`：读模型应用只有一个策略方法，收到事件就写读表相应行。读表的唯一写者是这个策略，用 import-linter 合约当闸（附负向样本）。
- **同一次提交**：一次落账的事件、读表行、tracking 在同一次提交里落——`Ledger.commit` 保留外层事务，`save()` 内同步跑跟随者，复用同一事务。这依赖 eventsourcing_sqlalchemy 事务 ContextVar 的嵌套复用语义（`datastore.py` 模块级 `transactions`）；以「同一事务先证」与「重建相等」两条验收守住。
- **「事件→状态」的规则只此一处**：在 `Entity` 的 `@event` 方法里；策略经聚合得出结果状态再写读表行，不另写一份合并规则。
- **重建与追平**：不另开重建入口。打开存档时由库按 tracking 位置追平；读表结构版本号变化即清读表与 tracking、由同一追平从通知日志重放。读表「坏了」不另设自动检测（单人存档、读表与事件同一事务，坏表概率低；手动清 tracking 即全量重放，有人兜底）。
- **读表两张**：实体读表（id、kind、key、data；索引 kind 与 (kind, key)）；事实读表（追加式：实体 id、kind、日期、正文；不设夜 id 列）。
- **读只按条件查**。账本对中间层开的读口是窄的：按 id、按 kind、按 (kind, key)、事实按实体（可加 kind、日期）与按 kind。`/state` 与动作路径只读当前状态（最近一夜、每个动作键最新一条、本月未批奏疏）。
- **合法的整类读**（按条件取各 kind，条数恒定，不算「小事查世界」）：审计与世界视图的「取全部」；转译名册与字段表（全部有名字的 kind）；`read_records` 空参；月初皇帝视图快照；`scene_material` 的皇帝可见「接不住」清单。整类读一律走一个具名读口（以 SQLAlchemy `execution_options` 之类标记），清单之外的读不得走它。模型看到的材料不变。
- **聚合缓存开着**（`AGGREGATE_CACHE_MAXSIZE`）；不开 snapshotting。
- **presentation 便宜但仍按提交推送**：前端把 `state` 与 `done` 一视同仁整份接收，核账期靠逐次提交的推送显示进度，所以每次提交推一份保留；流式 `delta` 仍是 `{text, hall}`，`hall` 每片段按夜 id 读一次，不再每片段重算整份 presentation；前端不改。
- **不变量**：`GET /state` 与 `POST /actions`（say／month／choose）的 SQL 条数与返回行数之和，在三种大小的局（夜数与月数同时变）之间严格相等，整类读口只计条数不计行数；`GET /records` 只比条数。这是「一件小事不查整个世界」的机械表述，不锚墙钟。
- **示范模块**：月历与夜。最热的两条读路径，一块完整的「落账 → 策略刷读表 → 按条件读 → 预算测试覆盖」，之后的人物、账户照抄。
- recorder 保持 eventsourcing-sqlalchemy。

## 考虑过、没选

- **内联同事务刷新（0159 现行）**：读表对任何拿到 session 的代码敞开，规矩靠人守，这次的全扫与 `events` 列就是从这个口子长出来的。库的投影把「只能经事件改读表」压进结构。
- **提交后另开事务刷读表**：库的 policy 契约只把新聚合事件与 tracking 原子落，策略自己写的行不在其中；崩在写行之后、写 tracking 之前会重复追加，要自写幂等与开档追平。同一次提交没有这个窗口。
- **只数 SQL 条数当不变量**：把 (8+2N) 次全表读合成一次全表读，条数恒定、测试照绿，病原样还在；读全部历史事实的增长也查不出。
- **按 kind 拆成人物表、账户表、月历表**：kind 是开放的（声明可建任意 kind），表的集合会变成一件要维护的事。
- **换 recorder（SQLAlchemy → 内置 sqlite）**：两者都能同事务写自定义表、都有 Process/Tracking recorder；recorder 不是病根。
- **墙钟阈值当验收**：锚在机器速度上，会 flake，也查不出原因。
- **删掉按提交推送、一次请求只算一次 presentation**：前端核账期进度依赖逐次推送，去掉是体验倒退。
- **只删表列、保留 `Entity.events`**：「事件→现状」会有聚合快照与策略两条投影路，重建相等变成两份逻辑互相对照，守不住策略本身。
- **把一夜内多次提交合成一次事务**：改变「事实先成行」的时点，是账本语义题，不夹在本票。

## 0159 前提的更正

库源码（eventsourcing 9.5.6，同 venv）：`subscribe` 不支持只影响推式 `ProjectionRunner`；`system.py` 的 `Leader`／`Follower` 走通知日志拉取，全文没有 `subscribe`；SQLite 与 SQLAlchemy 都有现成的 `TrackingRecorder`／`ProcessRecorder`；内置 sqlite 的 `SQLiteDatastore.transaction()` 同样能在同一事务里写自定义表。「只能走 sqlalchemy recorder」与「库维护不了查询表」都不成立。
