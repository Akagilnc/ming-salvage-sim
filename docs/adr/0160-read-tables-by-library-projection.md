# 读表与事件同事务写；按可见状态转换推送

Status: #1992 修订待独立评审（此前版本 accepted）

依据 [#1992 现行票面](https://github.com/Akagilnc/ming-salvage-sim/issues/1992)，给事中 `01a18640-5e58-7e33-9db7-8943ae912a9c`、符宝郎 `01a18646-b3be-706d-b69c-4b07ed276ac3` 署。
授权源卷：`~/.claude/projects/-Users-akagilnc-WorkSpace-Ming-LLM/a45c2e6b-8c9a-4f56-85fb-73324ee40299.jsonl`；写入 owner `d6d57ab8-c784-4131-af02-0415e54cb9bc`，读取与重复工作 owner `6131a9d6-e9b2-4359-adce-e33b4725193b`、`1f13f0e4-562b-49e3-bf2b-914a779e716f`，合理性而非死数字 owner `d4e9c88a-b95d-4f53-990f-7d00b031fa2f`。原话及替代关系见票面。

## 决定

- **事件是真源**。聚合不另存事件列表，实体读表不存 `events`。状态演进只有 `Entity` 的 `@event` 方法，不另写状态合并规则。
- **唯一落账入口**。`Ledger.commit` 在 eventsourcing-sqlalchemy 的 `recorder.transaction()` 内调用 `events.save()`，用手里的聚合写实体行、返回的 recordings 写 Recorded 事实行。事件与读表同成同败，不回读刚写事件。回滚时移除库缓存中的未提交聚合。`ming.ledger.tables` 的 import-linter 合约守住写表入口。不设 recorder 子类、跟随者、tracking 或进度追平。原有落账内容、提交时点不变。
- **两张读表**。实体表存 id、kind、key、source、data；事实表按通知 ID 追加实体 id、kind、日期、原话与 detail。按条件和身份直接取需要的行；目录只取 kind、key、计数，不逐行恢复聚合。人物关联的任职、本人私档等仍完整提供。已记入事实的历史材料（月初皇帝视图等）保持当时记录。
- **聚合只在需要时恢复**。修改实体及显式重建才用 `repository.get`。`AGGREGATE_CACHE_MAXSIZE=10000`，`AGGREGATE_CACHE_FASTFORWARD=n`，保留默认深拷贝，不开 snapshotting。单个应用实例写入；实例复用与后台回收沿 #1985。不另设应用结果缓存、锁、失效、依赖分析、冻结或合批层。
- **显式重建**。正常开档不追平、不自动修坏表。`ming read --replay` 在空临时读表上重建：源通知每页最多 1000 条，mapper 解码；每个 `Entity.Created` 的 id 交源应用 repository 取最终聚合；实体和 Recorded 事实共用正常落账的写行函数。每页源通知和聚合读取完成后才进入目标库事务，避免线程级事务串库。无事件复制、全体实体状态集合或自管 mutate。
- **重建输出与生命周期**。同一命令只建一份临时读表，实体和事实输出共用，按正常读法读取临时行。结束只关闭临时应用和数据库；源应用仍归原存档生命周期，原存档事件及读表不改写。正常读表损坏会影响正常结果，由显式重建恢复，不增加静默修复。
- **推送属于可见转换，不属于提交**。复用 #1985 的共享 `state` 流及前端监听；离场解绑该局的发送回调，重入接回，不另设来源局过滤。Game 在动作接受后、成功或失败结束后各发一次；结束兼后续动作启动，在登记完后续之后一次发送。开档续跑先登记，再随导航发送。开档、菜单、设置沿既有导航发送。删除逐提交 observe/on_commit；不做事后比较或去重缓存。state 也驱动前端刷新 `/records`：旧夜完成时，名册、起居录和待改票状态仍须更新，不能仅凭当前夜的 snapshot 相同而省掉完成发送。正文仍走 delta/gazette 及 snapshot.live。
- **本次操作只取一次同份材料**。presentation 内日历、夜、互动状态、失败及各展示项局部复用；声明校验取得一次官职名单供本份任免使用。独立操作仍现查，不建立跨调用材料缓存。每次读取和推送均须有实际理由，不以 SQL 同文或固定数字代替合理性判断。
- **材料不裁减**。小问题不取无关历史；完整名册、审计、世界视图、月初视图、人物履历、本夜轮次等按原契约取齐。模型沿 [0162](0162-every-model-reads-one-way-and-speaks-as-a-person.md) 的身份读账工具，前端 `/records` 仍取皇帝材料；过月并行、恢复及 [0163](0163-one-month-timeline-forks-at-once-travel-by-day.md) 的时间线不变。

## 成本与验证

- 按条件取 k 个实体直接返回 k 行，不做 k 次聚合恢复和深拷贝；事实取匹配的 f 行。完整材料最大取 N 个实体、F 行事实，历史和正文随游戏增长，无固定大小上限。
- 画面内同份材料只读一次，推送随可见转换而非提交次数增长；末道批红结束兼过月开始只发送一次。流式正文不以整画面重算实现。
- 重建扫描 E 条通知、恢复 N 个聚合、写 N 行实体和 F 行事实。全冷时还读取实体历史合计 E 条事件，不承诺源事件只处理一次。页大小不是总内存上限：临时表、库缓存、单实体历史及状态均须计入。
- 复用 LedgerReplay 与 CLI 验证原子性、回滚重试、跨页重建、坏表缺行/多行恢复及源库不变。只锁坏读表不影响正常读取的断言退役。
- 从 HTTP、模型读账和 SSE 验证权限、完整材料、开始/待批/失败/接续/完成及导航交接。保留无关历史 1/2/4 的行为与读量不变量，不裁相关材料。常驻计量不替换生产入口、不回溯调用栈。
- 按票面同案比较 `1f2d13220`、`f5d8932bc` 和修后：逐条 SQL 归因、推送及 get 次数、交替墙钟，重复工作须删除或说明必要性。全量 CPU 与最终 CI 只在最终待合并状态验证；十分钟上限不改，不用局部结果推算全量提速。

## 官方依据

- [eventsourcing-sqlalchemy 外层事务](https://github.com/pyeventsourcing/eventsourcing-sqlalchemy#managing-transactions-outside-the-application)："Just call the application recorder's `transaction()` method"；"Everything will commit atomically when the `Transaction` context manager exits."；"This effectively implements thread-scoped transactions." 本仓使用该外层事务，不造 recorder 或适配层。
- [Application 5：Full-text search](https://eventsourcing.readthedocs.io/en/stable/topics/examples/fts-content-management.html)：`search_pages`："Returns IDs for pages that match query."；`select_page`："Returns slug, title and body for given ID."；"The _insert_events() methods of the PostgreSQL and SQLite recorders are extended, so that rows are inserted and updated"。附加表与事件同事务写，附加表可读完整状态；本仓按条件一次取所需行，不照搬逐 id 查询或 snapshotting。
- [聚合缓存](https://eventsourcing.readthedocs.io/en/stable/topics/application.html#configuring-aggregate-caching)："When getting an aggregate that is found in the cache, it will be “deep copied”"；关快进前提："Only do this when only one instance of the application is being used to evolve the state of the aggregates"。
- [通知分页](https://eventsourcing.readthedocs.io/en/stable/topics/application.html#selecting-notifications-from-the-log)："The selection will contain no more than the specified limit."；"A domain event can be reconstructed from an event notification by calling the application’s mapper method to_domain_event()." 续页从最后通知 id 之后开始，解码不代替聚合恢复。
