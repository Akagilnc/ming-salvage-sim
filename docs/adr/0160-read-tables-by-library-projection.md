# 读表由库的投影维护；读按条件查，查询数不随世界大小增长

Status: proposed（2026-10-22 owner grill 定方向：「那肯定是优先用库的做法而不是自己去写。不然还用库干什么。A」）

重写后的账本只有一张 `entities` 表，每个实体一行，`data` 和整份事件列表 `events` 都是 JSON 列；中间层的每一个小问题（今天几号、这夜什么状态、按名找人）都是全表 `SELECT` 再在 Python 里挑。一次 `presentation()` 要全表读 (8+2N) 次、重放 N 个夜（N＝夜数），而它挂在每次落账和每个流式片段上。57 个录播测试跑四分钟，一个月级测试里全表读近三千次。病在两处：**一件小事查整个世界**；**事件在事件库之外又存了一份**（`events` 列）。[0159](0159-ledger-entities-events-and-landing.md) 当初以「库在 SQLite 上维护不了查询表」为由自写内联刷新，这个前提经核不成立（见文末）。

## 决定

- **真源只有事件库**。`entities` 表上的 `events` 列删除；任何「有哪些事实」都从事实读表或事件库取。
- **读表由库的投影维护，不由落账代码直接写**。用 eventsourcing 的 `ProcessApplication`／`Follower`：一个读模型应用，只有一个策略方法，收到 `Recorded`／`Created` 事件就写读表相应行。读表的唯一写者是这个策略；库的 tracking 保证每条事件恰好处理一次，读表随时可从通知日志整表重建。单进程下用 `SingleThreadedRunner`，`save()` 一返回策略就跑完，中间层立刻读到新值。
- **读表两张**：`entities(id, kind, key, data)`，`kind` 与 `(kind, key)` 建索引；`facts` 追加式，每条落账事件一行（实体 id、kind、夜 id、日期、正文），按夜／按日期／按实体查。
- **读只按条件查**。账本对中间层开的读口是窄的：按 id、按 kind、按 (kind, key)、按夜取事实。「取全部实体」只留给审计与世界视图。
- **聚合缓存开着**（`AGGREGATE_CACHE_MAXSIZE`，库自带 LRU＋只取新事件的快进）；不开 snapshotting，事件量用不上。
- **presentation 便宜但仍按提交推送**：前端把 `state` 与 `done` 一视同仁整份接收，核账期靠逐次提交的推送显示进度，所以每次提交推一份保留；流式 `delta` 只推增量文本，不再为每个片段重算整份 presentation。
- **不变量**：同一路由的 SQL 查询数不随世界大小增长。测试造 1 夜与 5 夜两局，数每个请求的 SQL 条数，断言相等（允许常数差）。这是「一件小事不查整个世界」的机械表述，不锚墙钟。
- **示范模块**：月历与夜。这两条是最热的读路径（`calendar()`、`nights()`），一块完整的「落账 → 策略刷读表 → 按条件读 → 预算测试覆盖」，之后的人物、账户照抄。

## 考虑过、没选

- **内联同事务刷新（0159 现行）**：读表对任何拿到 session 的代码敞开，规矩靠人守，这次的全扫与 `events` 列就是从这个口子长出来的；重建路径要自己维护。库的投影把「只能经事件改读表」压进结构。
- **按 kind 拆成人物表、账户表、月历表**：kind 是开放的（声明可建任意 kind），表的集合会变成一件要维护的事；一张带索引的表加按条件查已经是「读相关行」。
- **换 recorder（SQLAlchemy → 内置 sqlite）**：两者都能同事务写自定义表、都有 Process/Tracking recorder；recorder 不是病根，换了只添迁移。
- **墙钟阈值当验收**：锚在机器速度上，会 flake，也查不出原因。
- **一次请求只算一次 presentation、删掉按提交推送**：前端核账期进度依赖逐次推送，去掉是体验倒退；让它便宜即可。
- **把一夜内多次提交合成一次事务**：改变「事实先成行」的时点，是账本语义题，不夹在本票。

## 0159 前提的更正

库源码（eventsourcing 9.5.6，同 venv）：`subscribe` 不支持只影响推式 `ProjectionRunner`；`system.py` 的 `Leader`／`Follower` 走通知日志拉取，全文没有 `subscribe`；SQLite 与 SQLAlchemy 都有现成的 `TrackingRecorder`／`ProcessRecorder`；内置 sqlite 的 `SQLiteDatastore.transaction()` 同样能在同一事务里写自定义表。「只能走 sqlalchemy recorder」与「库维护不了查询表」都不成立。
