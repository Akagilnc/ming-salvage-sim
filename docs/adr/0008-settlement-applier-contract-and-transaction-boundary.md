# 结算落库统一拒收契约与事务边界

Status: accepted（实现分波次,见末节;#73 产出问题 1/4 的答案;r1 跨模型评审修订:重跑契约显式化/provenance/错误包/commit 暂停实现指正）

落库唯一入口 `apply_score_extraction` 名义统一,实现是 17 个 section × 5 种互相矛盾的错误处理风格(整段吞 issues.py:1209/1382、逐项静默 continue、裸奔无防 :1191/:1249/:1310/:1395、逐项记拒、前置抛)。最毒单点 `decree.py:406`:extractor 抛错 → `extracted={}` 整月 delta 蒸发,而 pre_settle 财政已落账=半落库,违「决策即落库」P1 铁律。事务边界稀碎:落库核自己不 commit,管线中段却散着独立 commit(且 GameDB 几乎每个方法内部 `conn.commit()`,实测 79 处),崩在中间无法回滚。本 ADR 把 ADR 0005 的 fail-loud 分流落成可执行契约。

## 决定

### 1. **段适配器契约**:每个落库 section 统一为 `apply(items, ctx) → {applied[], rejected[](item, 原因, 类别, source)}` 的适配器。LLM 脏数据(幻觉 id/枚举非法/引用不存在实体)= 逐项拒收留痕,坏项不带走整批(#63);代码异常(KeyError/AttributeError/schema 漂移)= **上抛,绝不吞**(ADR 0005)。`apply_score_extraction` 退化为「按白名单顺序跑适配器 + 聚合拒收报告」的薄编排。

### 2. **分段提交**：过月落账边界见 [0157](0157-v2-month-waits-for-exhausted-model-call-recovery.md)、#1843、#1845；旧整月后半段事务及失败 fallback 不再适用。

### 3. **前半段事务与重载**：`pre_settle` 的确定性写与 `turn_phase` 完成标记在同一事务提交；失败回滚后从 DB 重载 state/content/registry。重入已完成的前半段不重复财政结算。本月上下文继续持久化，供史册与收尾读取。恢复契约只引用 [#1846 现行正文](https://github.com/Akagilnc/ming-salvage-sim/issues/1846)。

### 4. **收尾调用边界**：见 #1843、#1845。旧章节记忆与结局总评的整月事务条款删除。

### 5. **拒收报告,分析优先**:拒收记录落库为结构化行(turn/section/原 item/原因/类别/**source**),**DB 为分析真源**,支撑「哪个 section 最常被喂脏」聚合;镜像到可回收 jsonl 须**内存缓冲、事务 commit 成功后才 append**(事务内写文件回滚不掉=回滚后留脏行);行带 turn+attempt 标记,attempt 计数**不从 DB 取**(随回滚重置),从错误目录已有文件推导。**provenance 进契约**:适配器入参带 `source: player_decree|hitl_decision|secret_order|system_simulation|unknown`(由 extractor/driver 灌注;现 schema 无通用来源字段,仅 issue 有 origin_kind：PR1 扩展)。**玩家可见性按 source 字段 gate**:仅 `player_decree`/`hitl_decision` 来源的拒收,邸报给一句 in-world 提示(如「有司奏:某事窒碍未行」);系统推演来源对玩家安静。〔2026-09-09 后出注记（proposed，随重构设计待评审）：[0153](0153-v2-world-record-and-two-way-mediation.md) 末段 / 决策票 #1820：拒收当事实回给同一场推演者自行处置，邸报提示句由推演者据实编话、代码不另加；拒收留痕与 DB 分析真源不变。〕

### 6. **中止与错误包**：停住与续跑见 [#1846](https://github.com/Akagilnc/ming-salvage-sim/issues/1846)，呈现见 [0158](0158-v2-frontend-receives-audience-month-and-recovery.md)。诊断包写入用户可写目录，保留 traceback、月度上下文、存档副本与 manifest；存档副本只用 SQLite `conn.backup()`。删除整月 delta 诊断字段、重放与清上下文重演条款。

### 7. **不建自动回收 telemetry**(探针期过早工程化)。试玩形态=**试玩者本地跑**(不考虑作者托管 web),回收唯一路径=手动发错误目录：中止提示必须自带指引(写明完整路径+「请把它发给作者」),拒收 jsonl 与错误包集中同一目录,一次打包全带走。

### 8. **契约住 `ming_sim/applier.py`**(契约类型 + 拒收收集器 + 事务包裹);各 section **原地**迁入契约,不大搬家(免与财政线 #66/#78 撞文件)。〔2026-08-27 后出为准:**本决定被 ADR 0150 supersede**：段物理迁入实体适配器目录 `ming_sim/entities/<entity>/`、契约承重化(SectionResult/RejectedItem canonical)、`apply_score_extraction` 退役为 `settle_delta`;当年「免撞财政线」的理由已随财政线落地过期。0008 其余决定(事务边界/重跑契约/错误包/拒收报告)全部继续有效。〕

## Considered Options

- 整回合单事务(含 pre_settle):跨 HITL 暂停挂不住事务;且回滚会吞掉玩家已确认的暂存动作。否决：代价是「回合没发生」不成立,收窄为「后半段不半落」。
- validate-all-then-mutate 不上事务:挡格式错,挡不住写到一半真异常,仍半落库。否决(#73 产出问题 4 的回答=事务包裹)。
- 代码异常「响亮隔离该项、批次继续」:游戏不被卡死,但该项后果永久丢=换皮半落库,P1 破口。否决：应中止并沿现行恢复入口重试。
- 拒收报告进邸报全量展示:试玩者(非技术)看了无能为力,开发者要的是可聚合数据非游戏内文本。改为分析优先+按 provenance 最小 diegetic 提示。

## 实施波次(每 PR 可 review,295 测试护航)

- **PR1**:applier.py 契约类型 + 拒收收集器(落库+commit 后 jsonl)+ 事务包裹(factory/代理式 commit 暂停;**当时覆盖三条推进路:正常 apply / simulator-fallback / advance_without_edict；其中 simulator-fallback 已由 #1700 退役**)+ **前半段事务与重载**(pre_settle 自事务+完成相位+begin_turn 白名单 / 内存态重载)+ `decree.py:406` 改响亮中止 + 错误包(backup API 存档副本,user-data 路径)。
- **PR2**:两个整段吞(power×2)+ 四个裸奔段迁入契约 + provenance 字段灌注。
- **后续**:其余 section 分批;邸报 in-world 提示;与财政线对齐后 flows 侧(候选 4)。

## Consequences

- **后半段**半落库在结构上不可达:apply 全落或回合停在可重试态;pre_settle 效果保持已落(设计使然)。
- 新实体类型落库 = 写一个适配器,错误语义免费继承：M3 财政 port(#66)的 settle_tick 直接做成适配器。
- #14(静默吞)从 127 个 except 逐个修,变成 17 个 section 迁一个契约;#63 的拒收目录由结构化报告自动产出。
- 邸报一句话提示与「瘦裁判」(CONTEXT.md)分工一致:裁判拦一致性错误并留痕,不算历史判断。

〔2026-09-10 后出注记：#1820 拍的「拒收当事实回给同一场推演者、改口重交」随核算反馈驱动的同场续演循环取消：拒收项留痕、本月不重交，作为实况进入邸报作者供料与下月材料（密令来源的只走密报）；落账及拒收承接见 #1843，邸报供料见 #1862；决策缘由见 [0157](0157-v2-month-waits-for-exhausted-model-call-recovery.md) 与 [0153](0153-v2-world-record-and-two-way-mediation.md) 后出注记二。本条其余拒收留痕规则不变。〕


## 后出注记（#1843 reopen，2026-09-28）

`driver.py` 与 `settle_with_delta` 已删除（owner 裁定 uuid `1c439239-e748-417a-ac37-79603374583a`）。「driver(ADR 0004)走同一结算核」不再适用。`pre_settle` 自事务、settling 相位与内存态重载保留。恢复条款见 #1846 现行正文。