# 读表与事件同事务写；索引找 id，实体交库恢复

Status: #1992 修订待独立评审（此前版本 accepted）

按 [#1992 现行票面](https://github.com/Akagilnc/ming-salvage-sim/issues/1992) 修订。授权源卷：`~/.claude/projects/-Users-akagilnc-WorkSpace-Ming-LLM/a45c2e6b-8c9a-4f56-85fb-73324ee40299.jsonl`；写入 owner `d6d57ab8-c784-4131-af02-0415e54cb9bc`，读取 owner `3fb62093-b642-4b99-bcef-4bf8cdf7b3eb`（对应 runner 选项 `6c7e2400-ac6b-4e82-a314-6669b2a492fc`）。原话及给事中、符宝郎结论见票面与本票起居录。

原问题是小问题全表读、重复存事件，以及随后引入的跟随者进度、写后回读、读结果缓存、依赖分析、冻结与合批传料机制。目标是实际提速，不是减少 SQL 句数。

## 决定

- **事件是真源**。聚合不另存事件列表，实体读表不存 `events`。状态演进只有 `Entity` 的 `@event` 方法；恢复交 `repository.get`，应用不自行 `mutate`。
- **唯一落账入口**。`Ledger.commit` 在 eventsourcing-sqlalchemy 的 `recorder.transaction()` 内调用 `events.save()`，用手里的聚合写实体行、返回的 recordings 写 Recorded 事实行。事件与读表同成同败，不回读刚写事件。回滚时移除库缓存中的未提交聚合，重试仍从已提交事件恢复。`ming.ledger.tables` 的 import-linter 合约守住写表入口。不设 recorder 子类、跟随者、tracking 或进度追平。
- **两张读表**。实体表存 id、kind、key、source、data，供条件与权限索引；事实表按通知 ID 追加实体 id、kind、日期、原话与 detail。事实正文直接按条件查询。
- **正常实体读取**。先按 id、类、名称或身份条件筛出 id，再逐个向源存档应用的 `repository.get` 取实体。名册、完整材料、夜与呈现均据取得的聚合构造；SQL 中的状态条件只用于筛选，不把读表整行当权威状态返回。人物关联的任职、本人私档等仍完整提供。已记入事实的历史材料（月初皇帝视图等）保持当时记录，不换成当前聚合。
- **库缓存，不自建读机制**。`AGGREGATE_CACHE_MAXSIZE=10000`，`AGGREGATE_CACHE_FASTFORWARD=n`，保留默认 `deepcopy_from_cache=True`；不开 snapshotting。单个应用实例写入；Game/Court/Ledger 生命周期、后台重入复用与回收不变。不另设结果缓存、锁、失效、SQL 依赖分析、冻结、合批实体读取或跨调用共享材料。
- **显式重建**。正常开档不追平、不自动修坏表。`ming read --replay` 在空临时读表上重建：源通知日志每页最多 1000 条，mapper 解码；每个 `Entity.Created` 的 id 交源存档同一个 repository 取最终聚合；实体和 Recorded 事实共用正常落账的写行函数。每页源通知和聚合读取完成后，才进入目标库写事务，避免线程级事务串到空事件库。无事件复制，无全体实体状态集合，无自管重放算法。
- **重建输出与生命周期**。同一 CLI 命令只建一份临时读表，实体和事实输出共用。临时表负责筛 id 和查事实；实体仍向源 repository 取。结束只关闭临时读侧自己的应用与数据库，源 repository 归源存档生命周期。原存档事件及读表均不改写。
- **材料与提交时点不变**。小问题不取无关历史；审计、世界视图、完整名册、月初视图、人物履历、本夜轮次等按原契约取齐，不裁材料。模型仍用 [0162](0162-every-model-reads-one-way-and-speaks-as-a-person.md) 的身份读账工具，前端 `/records` 仍取皇帝材料。逐提交 presentation 推送保留；流式片段只取对应夜的 hall，不重算整份 presentation。过月并行、恢复与 [0163](0163-one-month-timeline-forks-at-once-travel-by-day.md) 的时间线不变。

## 成本与验证

- 按条件取 k 个实体就逐个 get k 个；事实取匹配的 f 行。全量名册、审计与世界视图最大取 N 个实体、F 行事实；实体、历史和正文随游戏增长，没有固定大小上限。
- 冷 get 恢复该实体的历史，热 get 复制当前状态。一次操作取同一未变实体 r 次，初冷且未淘汰时恢复一次、取回复制 r 份；初热时不恢复、复制 r 份。淘汰后再取会重新恢复。库缓存不是免复制，也不是跨请求永久命中保证。
- 重建扫描 E 条通知、调用源 repository N 次、写 N 行实体和 F 行事实。全冷时还读取各实体历史，合计再恢复 E 条事件；不能承诺源事件只处理一次。输出继续逐个 get，仍有复制和可能的冷恢复。写入材料按通知页周转；临时表、库容量内的聚合和单实体历史/状态均计入内存，页大小不是总内存上限。
- 用已有 Ledger 状态机验证读表与事件一致、提交前失败和同实例重试；用已有 CLI 案验证重复重建、缺失/多余事实、错误实体读表状态、原存档不变、一次命令只重建一次。计量沿用 SQLAlchemy 监听，不替换生产读入口或回溯调用栈。
- 正常逐实体 get、独立请求取数、库恢复与深拷贝不按相同 SQL 或已知列表判错。仍禁止同一命令重复做完整重建。保留真实 HTTP 无关历史 1/2/4 组的查询数、返回行数和行为不变量；相关历史增长不判错，不裁相关材料凑计数。
- 最终验收：单案 SQL 分类用于解释工作；`1f2d13220` 与最终 HEAD 的全量串行 cProfile/CPU 才是完整速度证据。重建另量开局及现成最长历史。最终待合并状态按 CI 步骤全量通过既有十分钟限制，不改 timeout，不以局部计时推算全量。

## 官方依据

- [eventsourcing-sqlalchemy：Managing transactions outside the application](https://github.com/pyeventsourcing/eventsourcing-sqlalchemy#managing-transactions-outside-the-application)："Just call the application recorder's `transaction()` method"；"Everything will commit atomically when the `Transaction` context manager exits."；"This effectively implements thread-scoped transactions." 使用库外层事务，不造适配层。
- [Application 5：Full-text search](https://eventsourcing.readthedocs.io/en/stable/topics/examples/fts-content-management.html)："for page_id in recorder.search_pages(query):"，随后 "page = self.get_page_by_id(page_id)"。[Application 3：Content management](https://eventsourcing.readthedocs.io/en/stable/topics/examples/content-management.html)："return self.repository.get(page_id)"。采用索引找 id 后取聚合，不声称库只允许这一种读法，不引入示例的 snapshotting。
- [Application：Configuring aggregate caching](https://eventsourcing.readthedocs.io/en/stable/topics/application.html#configuring-aggregate-caching)："When getting an aggregate that is not found in the cache, the aggregate will be reconstructed from stored events, and then placed in the cache."；"When getting an aggregate that is found in the cache, it will be “deep copied”"。关快进的前提是 "Only do this when only one instance of the application is being used to evolve the state of the aggregates"。
- [Application：Selecting notifications from the log](https://eventsourcing.readthedocs.io/en/stable/topics/application.html#selecting-notifications-from-the-log)："The selection will contain no more than the specified limit."；"A domain event can be reconstructed from an event notification by calling the application’s mapper method to_domain_event()." 续页从最后通知 id 之后开始；解码不代替 repository 的聚合恢复。

## 未采用

- 跟随者/tracking、提交后再刷表、换 recorder：本仓已有 SQLAlchemy 外层事务，不另建并行机制。
- 整行 SQL 状态加应用缓存、冻结、依赖分析、合批传料：#1992 已撤销，不留下兼容支路。
- 重建自行逐事件 mutate 并保存全体最终状态：改用源 repository；接受通知与冷聚合恢复各有工作量。
- 只数 SQL、锁零重复或用局部计时推算全量：不能证明实际提速。
- 合并原有提交、裁模型材料、停止逐提交推送：改变游戏行为，不属于本票。
