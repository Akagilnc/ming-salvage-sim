# 结算落库统一拒收契约与事务边界

Status: accepted（实现分波次,见末节;#73 产出问题 1/4 的答案;r1 跨模型评审修订:重跑契约显式化/provenance/错误包/commit 暂停实现指正）

落库唯一入口 `apply_score_extraction` 名义统一,实现是 17 个 section × 5 种互相矛盾的错误处理风格(整段吞 issues.py:1209/1382、逐项静默 continue、裸奔无防 :1191/:1249/:1310/:1395、逐项记拒、前置抛)。最毒单点 `decree.py:406`:extractor 抛错 → `extracted={}` 整月 delta 蒸发,而 pre_settle 财政已落账=半落库,违「决策即落库」P1 铁律。事务边界稀碎:落库核自己不 commit,管线中段却散着独立 commit(且 GameDB 几乎每个方法内部 `conn.commit()`,实测 79 处),崩在中间无法回滚。本 ADR 把 ADR 0005 的 fail-loud 分流落成可执行契约。

## 决定

1. **段适配器契约**:每个落库 section 统一为 `apply(items, ctx) → {applied[], rejected[](item, 原因, 类别, source)}` 的适配器。LLM 脏数据(幻觉 id/枚举非法/引用不存在实体)= 逐项拒收留痕,坏项不带走整批(#63);代码异常(KeyError/AttributeError/schema 漂移)= **上抛,绝不吞**(ADR 0005)。`apply_score_extraction` 退化为「按白名单顺序跑适配器 + 聚合拒收报告」的薄编排。

2. **事务原子单元 = pre_settle 之后所有推进回合的写路径**:不只正常路(「extractor 产出 apply + 章节记忆 + next_period」),**simulator 失败的 fallback 分支(decree.py:296-319,跳过结算仍写 record_log/save_turn_report/惯性清理/next_period)与退朝无诏的 `advance_without_edict` 同样必须走同一事务包裹**——任何一条推进回合的写序列都全有或全无,不许 ad-hoc 散写;`pre_settle`(固定财政 + 暂存动作 commit)维持先行提交(ADR 0006 要求推演前盘面已定)。**不变式(收窄):后半段半落库在结构上不可达**——pre_settle 的效果(已确认暂存动作+固定财政)在中止/重试时保持已落,这是设计而非缺陷。实现要点:commit 暂停不可 monkeypatch `conn.commit`(`sqlite3.Connection` 属性只读,运行时必崩),用 `sqlite3.connect(..., factory=自定义Connection)` 或 GameDB 持代理对象拦截。

   〔2026-08-30 #1700/P7 后出注记：simulator 失败的固定邸报 fallback 已退役。失败须保留 `settling` 并响亮上抛，不进入 extractor 或推进回合；并行 companion 已成功时仅保留 ready=0 checkpoint 供原月重试。上段对该旧分支的事务约束仅为历史实现记录。〕

3. **重跑契约(三件缺一不可,r1/r2 评审并发指出,全部列入 PR1 验收)**:
   - **resolve_context 无条件持久化**:现状只有 HITL 回合才 `save_resolve_context`(decree.py:324)——改为每回合进入后半段前必存(extractor delta + 叙事);**持久化前先过 `validate_delta_shape`——畸形 delta 绝不入 resolve_context**(否则毒 payload 钉进重试真源:apply 永崩、而「重跑 extractor」被「context 已存在」挡死=永久 soft-lock),校验失败响亮报错、重跑 extractor 重新生成;**清理在后半段事务内作最后一笔**(commit 后再清会留「已提交但 context 残留」的崩溃窗口)。重跑保证收窄为:**不重跑 simulator/extractor(贵的两步)**——同进程重试用内存产出,跨进程恢复从 resolve_context 重灌;章节记忆/结局总评产出**不入** resolve_context,崩在其后重试会重调这两个便宜调用(可接受)。
   - **pre_settle 自成事务 + 完成相位**:pre_settle(暂存动作 commit + 固定财政 + auto_trigger,**连同推演前的其余确定性写如 `auto_submit_due_secret_orders`,decree.py:240——一并纳入,不留事务外散写**)整体包成**自己的单事务**,完成时**同事务内**落中间相位(如 `settling`)——崩在内部=回滚=相位未变=重进时**干净重跑前半段**。**`settling` 只意味着「前半段已完成,不再重跑 pre_settle」,不意味着后半段就绪**:恢复入口先查 resolve_context——有(extractor 已产出)→ 直入 apply 重试;无(崩在推演/抽取期间)→ **重跑 simulator/extractor**(此窗口的 LLM 产出本就没持久化,重跑是唯一选择,与决定 3 第一条的「不重跑」承诺不冲突——那条只覆盖 resolve_context 已存在的情形)。⚠️ `settling` 必须加进 `begin_turn` 的相位保活白名单(session.py:432-436,白名单外的相位重载即被重置回 summoning,守门失效——`awaiting_decision` 当年就为此补过)。验收测试=崩溃重载于 settling 不二次财政 tick、崩于 pre_settle 内部财政不缺账、崩于推演期间恢复后能重新推演并结算。
   - **内存态与 DB 同源恢复**:DB 回滚**不会**还原内存副作用(`state.metrics` 直加 flows.py:192、`content.characters`/registry 注册、`state.next_period()`)。事务期内**正常写内存**(后续逻辑要读,不搞选择性推迟——那会让事务内读到新旧混杂);回滚后重跑前把 state/content/registry 统一从 DB 重载(与 restore 同路径)。

4. **事务内 LLM 调用边界**:后半段含章节记忆/结局总评两个 LLM 调用,其失败**沿用现行降级保底、不触发回滚**(memories.py「不抛断游戏」铁律)——只有代码异常触发回滚。持锁横跨分钟级 LLM 在 CLI 串行下可接受(探针走 CLI);实现**可自由**先收集 LLM 产出、再开短事务集中写入以减持锁时长,只要「章节记忆在结局判定前」等顺序不变式保持——本 ADR 只约束写入的原子性,不约束持锁方案。

5. **拒收报告,分析优先**:拒收记录落库为结构化行(turn/section/原 item/原因/类别/**source**),**DB 为分析真源**,支撑「哪个 section 最常被喂脏」聚合;镜像到可回收 jsonl 须**内存缓冲、事务 commit 成功后才 append**(事务内写文件回滚不掉=回滚后留脏行);行带 turn+attempt 标记,attempt 计数**不从 DB 取**(随回滚重置),从错误目录已有文件推导。**provenance 进契约**:适配器入参带 `source: player_decree|hitl_decision|secret_order|system_simulation|unknown`(由 extractor/driver 灌注;现 schema 无通用来源字段,仅 issue 有 origin_kind——PR1 扩展)。**玩家可见性按 source 字段 gate**:仅 `player_decree`/`hitl_decision` 来源的拒收,邸报给一句 in-world 提示(如「有司奏:某事窒碍未行」);系统推演来源对玩家安静。

6. **中止与错误包**:代码异常中止时,玩家见「本月结算失败,进度已保存,可重试」;同时自动落错误包到**用户可写目录**(走 paths.py 的 user-data helper——frozen 打包下 `data/` 相对路径不可写),内容=traceback + 当回合 delta JSON + resolve context + **存档副本(SQLite,仅用 `conn.backup()` API——WAL 模式直接 copy 文件得坏/旧快照;`wal_checkpoint` 后拷贝在 checkpoint→拷贝窗口仍可能混入并发写,不采用)** + manifest(db 路径/turn/版本号/attempt)。重试仍炸(同一 apply 异常反复)→ 先提供**「重新推演」**逃生口(清 resolve_context、重跑 simulator/extractor 重产 delta;原 delta 已在错误包留档不丢证据)→ 仍不行才引导发错误包 + 冻结该局存档、换开新局;**不提供「跳过本月结算」**(=自愿半落库,污染盘面与试玩反馈)。

7. **不建自动回收 telemetry**(探针期过早工程化)。试玩形态=**试玩者本地跑**(不考虑作者托管 web),回收唯一路径=手动发错误目录——中止提示必须自带指引(写明完整路径+「请把它发给作者」),拒收 jsonl 与错误包集中同一目录,一次打包全带走。

8. **契约住 `ming_sim/applier.py`**(契约类型 + 拒收收集器 + 事务包裹);各 section **原地**迁入契约,不大搬家(免与财政线 #66/#78 撞文件)。〔2026-08-27 后出为准:**本决定被 ADR 0150 supersede**——段物理迁入实体适配器目录 `ming_sim/entities/<entity>/`、契约承重化(SectionResult/RejectedItem canonical)、`apply_score_extraction` 退役为 `settle_delta`;当年「免撞财政线」的理由已随财政线落地过期。0008 其余决定(事务边界/重跑契约/错误包/拒收报告)全部继续有效。〕

## Considered Options

- 整回合单事务(含 pre_settle):跨 HITL 暂停挂不住事务;且回滚会吞掉玩家已确认的暂存动作。否决——代价是「回合没发生」不成立,收窄为「后半段不半落」。
- validate-all-then-mutate 不上事务:挡格式错,挡不住写到一半真异常,仍半落库。否决(#73 产出问题 4 的回答=事务包裹)。
- 代码异常「响亮隔离该项、批次继续」:游戏不被卡死,但该项后果永久丢=换皮半落库,P1 破口。否决——中止+重试代价低(不重跑 simulator/extractor,见决定 3),真相无损。
- 拒收报告进邸报全量展示:试玩者(非技术)看了无能为力,开发者要的是可聚合数据非游戏内文本。改为分析优先+按 provenance 最小 diegetic 提示。

## 实施波次(每 PR 可 review,295 测试护航)

- **PR1**:applier.py 契约类型 + 拒收收集器(落库+commit 后 jsonl)+ 事务包裹(factory/代理式 commit 暂停;**当时覆盖三条推进路:正常 apply / simulator-fallback / advance_without_edict；其中 simulator-fallback 已由 #1700 退役**)+ **重跑契约三件套**(resolve_context 无条件持久化+事务内清 / pre_settle 自事务+完成相位+begin_turn 白名单 / 内存态重载)+ `decree.py:406` 改响亮中止 + 错误包(backup API 存档副本,user-data 路径)。
- **PR2**:两个整段吞(power×2)+ 四个裸奔段迁入契约 + provenance 字段灌注。
- **后续**:其余 section 分批;邸报 in-world 提示;与财政线对齐后 flows 侧(候选 4)。

## Consequences

- **后半段**半落库在结构上不可达:apply 全落或回合停在可重试态;pre_settle 效果保持已落(设计使然)。
- 重试不重跑 simulator/extractor(resolve_context 为真源);章节记忆/结局总评便宜调用可能重调(决定 3/4 接受);崩在推演期间的恢复须重新推演(该窗口产出未持久化)。
- 新实体类型落库 = 写一个适配器,错误语义免费继承——M3 财政 port(#66)的 settle_tick 直接做成适配器。
- #14(静默吞)从 127 个 except 逐个修,变成 17 个 section 迁一个契约;#63 的拒收目录由结构化报告自动产出。
- 邸报一句话提示与「瘦裁判」(CONTEXT.md)分工一致:裁判拦一致性错误并留痕,不算历史判断。
- driver(ADR 0004)走同一结算核,自动获得事务+重跑语义;driver 无聊天/LLM 路径,provenance 由其 delta 信封灌注。
