# delta 落库失败统一按 per-item 拒收（含 validate 层）；整份重产只在拆不出项时（#63）

Status: Accepted（2026-06-18；grill #63 warn-vs-reject 收敛。**修订 ADR 0008 决定3** 的 validate 粒度。**评审收敛**：线上 R1–R7 收敛（codex 空于 `b029773`；gemini faction/class 同点 drift 连 3 轮无新论据、无仓库根源 → 移出复评）；**本地 cmr 经用户决定本轮由线上替代（2026-06-18）**。Accepted → #63 升 ready-for-agent、进实现期。实现属编码、spawn 隔壁。file:line 指示性、以函数名为准。**线上 R1（gemini/sourcery/codex）折入：F1 非 dict 留痕包装 · F2 嵌套字段逐实体隔离 · F3 留痕对 resolve_context 崩溃安全 · F4 改 deferred-measured（#210）**。R2/R3 续折：嵌套实体保 id · 留痕同事务 · section 隔离修自相矛盾 · 跨阶段 collector 生命周期。**R4 折入：玩家可见门跨阶段聚合 + 容忍归一不触门（codex P2×2）；驳回 gemini×2（atomicity = ADR 0008 既定事务边界 / faction·class_delta 故意排除，均有实证）**。**R5 折入：gate 限定到当前 attempt（重模拟不删拒收行）+ 容忍数据源全文同步（#210 不混拒收行）（codex P2×2）；gemini faction/class 同点 drift 第 2 轮 → 定义域收口、标不再重议**。**R6 折入：gate 门窗 = 本回合所有 attempt − 用户重模拟作废的（codex P2，修 R5「只认当前 attempt」漏 settle-retry 真 validate 拒收）；gemini 同点第 3 轮无新论据 → 移出复评**。）

## 背景与第一性原则

#63「LLM 产出的 delta 落库失败死法目录」剩三片标「warn-vs-reject 设计未定」：死法 2（合法字段吐进**错模块** → `_sanitize_module_output`（simulation.py:649）静默剔）、new_issues 段逐项拒收、`validate_delta_shape` 非 dict list 项 abort-vs-逐项。

ADR 0005 / 0008 已钉死大半：代码错（KeyError/AttributeError/schema 漂移）→ 响亮上抛；LLM 脏数据（幻觉 id / 枚举非法 / 引用不存在实体）→ 逐项拒收留痕、不带走整批；三底线「不宽吞 / 不静默 / 不带走整批」。所以「warn = 静默放行」**早已出局**——系统里不存在「悄悄让一项过去」。剩下的不是 warn-vs-reject，是落在 0005 两桶**之间的缝**：「合法但放错位置 / 结构局部坏」该按什么**粒度**处理、要不要**替 LLM 猜着搭救**。

**第一性原则**：
1. **显式优于推断**（接 ADR 0003/0009）：可恢复**只能靠推断**的，拒收——系统绝不替 LLM 猜意图。
2. **per-item 隔离一路到底**（接 ADR 0005「per-item 隔离替整批崩」）：粒度是**项**，不是整份 delta。

## 决定

**delta 落库失败统一按 per-item 处理，粒度一路贯到 validate 层。**

1. **粒度 = 项。** 每条 delta 项独立校验 + 独立落库，validate 层也按项，不存在「一项坏 → 整批退」。
2. **好项永远落 + 报成功**，绝不被同批坏项牵连。
3. **坏项单独成轨**：走它自己的 per-item 处理 → 成则落；不成则**仅针对该项报错 + 留痕**（item / reason / category / source，走 ADR 0008 拒收报告管线 + source-gated 邸报），其余项仍成功。
4. **「合法但放错位置」= 拒收，不搭救**（死法 2）：错位字段的还原目标常**不唯一**（`manpower` 吐进 region 模块，不知是哪支军），搭救 = 替 LLM 猜 → 猜错比拒收更毒、且 P4「皇帝无表」下玩家看不见。**不猜。**
5. **new_issues = 拒主体坏项，但可选次要字段例外（数据门 #210）**：主体 / 必需字段非法 → 拒整条 issue（「丢坏字段、剩下照建」= 推断「这条 issue 没那字段仍成立」，出局）。**但纯可选次要字段（`ongoing_effects` / `effect_on_*` / `cancel_cost`）畸形 → 归一 `{}`、保住 issue 主体**（= 现有 `ming_sim/issues.py` 行为 + `test_new_issue_non_dict_cancel_cost_tolerated`；将脏的可选字段归零不算「猜主体意图」，主体照玩家原样）。「拒整项」是否该收紧到连可选字段都拒，取决于「主体合法 + 仅可选字段畸形」真实多罕见——**deferred-measured（#210）：先发安全默认（容忍）+ 非阻塞容忍度量通道对该 case 打标计数（不落 `rejection_reports` 行），试玩频率 < 阈值再切严格拒整项**；在容忍默认下测 = 试玩期零丢玩家 issue。**容忍归一的打标计数走非阻塞度量通道，绝不写 player_decree/hitl_decision 来源的拒收行、不触发玩家可见门（codex R4 P2）**：issue 主体成功建成、仅可选次要字段被归零时，`has_player_visible_rejection()` 不得因此报「窒碍未行」（否则成功的旨意被误呈失败）。容忍 ≠ 拒收——度量用独立 category/severity，玩家可见门显式忽略容忍类。
6. **validate 非 dict 项 = 逐项拒**：丢坏项 → **净化后再过一遍 validate → 通过才入 `resolve_context`**（进重试真源的恒是逐项过了的那批，毒 payload 进不来，ADR 0008 决定 3 怕的永久 soft-lock 由此自动免疫）+ 走拒收留痕（否则 = 死法 3「零痕迹消失」搬到 validate 楼层重演）；原始坏项留**错误包**取证。
   - **非 dict 项的留痕包装（F1）**：`RejectionCollector` 的 `RejectedItem.item` 现类型为 `dict`、落库 / 镜像直接序列化它；validate 层拒的**任何非 dict 项**（裸字符串 / 数字 / `None` / list 等，凡非 dict 一律）须**统一包装为 dict**（`{'raw_value': <原值>}`），令 `RejectedItem.item` 恒为 dict、下游序列化一致；**不**放宽类型成 `dict|str|int|None`（那会让消费方处理异构、契约脏）。**嵌套实体（F2）被拒时包装须保留实体 id**——`region_delta.shaanxi` 非 dict → `{'entity_id': 'shaanxi', 'raw_value': <原值>}`，别把 shaanxi 丢了。现 `RejectedItem.item:dict` 靠 Python 松类型放任非 dict 通过 = 违本条，实现期须显式包装。
   - **留痕对 `resolve_context` 必须崩溃安全（F3）**：validate 层的拒收**与净化版 `resolve_context` 在同一 `applier.atomic` 事务块内一起持久化**——`save_resolve_context` 与拒收记录 durable 写库要么全落要么全回滚，**原始坏项的拒收记录必须先 durable 落库，才允许 `resolve_context` 只留净化版**（写序明确、不留两解）。⚠️ **「先喂进内存拒收器」不算等价替代**：`RejectionCollector` 只是内存缓冲、`rejection_reports` 只在后半段 `settle_with_delta` 事务内 flush，而净化版 `resolve_context` 在那之前已提交 → 崩在中间仍丢审计链。否则崩在「净化版已提交、拒收未 durable」之间 = 坏项无 durable 真相，`item / reason / category / source` 审计链丢（违「不静默」）。**`RejectionCollector` 跨阶段生命周期（gemini R3）**：`pre_settle` 阶段已 flush 落库的拒收，不能被后半段 `settle_with_delta` 回滚的 `reset()` 误清（否则 DB 有记录、jsonl 镜像永远丢、两者不一致）——`pre_settle` commit 后**立即 `mirror_to_jsonl` 清 `_flushed`**，或**两阶段各用独立 `RejectionCollector` 实例**。
   - **玩家可见门须跨阶段聚合（codex R4 P2）**：`has_player_visible_rejection()`（applier.py）只检单个 collector 的 `_buffer + _flushed`，而 F3 的「`mirror_to_jsonl` 清 `_flushed`」/ 独立实例令 `pre_settle`（validate 层）拒的项不在 `settle_with_delta` 的 collector 里 → 一条**只在 validate 层被拒**的玩家旨意会 durable 落 `rejection_reports`/jsonl，却**不**在 turn_report 报「窒碍未行」（decree.py 组装报告调的是 settle 阶段 collector），静默违 source-gated 保证。修法：报告组装前**按本回合查 durable 拒收行（player_decree/hitl_decision 来源，跨 `pre_settle`+`settle` 两阶段）**，或自 `pre_settle` **携 player-visible 标志前传**——门 =「本回合任一阶段有玩家来源真拒收」，非「settle collector 内存里有」。**但 durable 查询须按 attempt 作用域过滤（codex R5/R6 P2）**：`clear_for_resimulation`（`error_pack.py:164`）走 ADR 0008 重模拟逃生口时**只降级 `resolve_context`、不删 `rejection_reports` 行**（docstring 明文「降级而非删行」）→ 若门写成「本回合任一 durable 行」，被用户重模拟作废的旧 attempt 拒收行会让重模拟后的报告仍报「窒碍未行」（幻象失败）。故门须排除**被用户重模拟作废的 attempt** 的拒收行,而非简单「只认最后一次 attempt」。⚠️ **区分两种 abort（codex R6 P2）**:① `settle` abort → ready-context **重放/重试**（`attempt = _next_attempt(before_turn)` 自增、`RejectionCollector(attempt=…)`，`decree.py:874-878`）是**同一逻辑回合的续跑**——先前 attempt 的 validate 拒收（坏项已净化出 `resolve_context`、重放不再 revalidate）**仍真、必须计入**,否则最终成功的重放会漏报该真拒收（又静默);② 唯有 `clear_for_resimulation`（用户重模拟逃生口、ready=0、LLM 重跑）才**作废**其之前 attempt 的拒收。故**门窗 =「本回合所有 attempt − 被用户重模拟作废的」,非「仅当前 attempt」**;实现可由 `clear_for_resimulation` 给该 turn 旧拒收行打作废标记（settle-retry 不打）、门只数未作废的玩家来源行。门 =「本回合未被重模拟作废的玩家来源真拒收」。
   - **驳回·gemini R4「`pre_settle` 提前 commit = 半落库，应裹同一最外层 `applier.atomic`」**：不收——`pre_settle` 自带事务、提交后保持已落是 **ADR 0008 决定的明文边界**（seed issues 等先落；断点续跑的重试真源 = `ready=1` 的 delta 重放，非靠回滚），`mirror_to_jsonl` 在 `pre_settle` commit 后清是顺这条既定边界、非新引入的半落库 bug。整段裹一个最外层 atomic 会废掉 ADR 0008 的断点续跑。按 later-doc-wins，事务边界以 ADR 0008 为准。
7. **整份 abort + 重跑 extractor 只剩一个场景**：delta 根本**拆不出 section**（顶层非 dict / JSON 截断到连 section 都分不出）——此时无任何「好项」要保，只能整份重产。**只要拆得出 section 就 per-section / per-item 处理，永不整份退**：某个 section 整体坏（如 `region_delta` 非 dict）→ 只拒该 section（留痕）、其余 section（`economy_moves` / `new_issues` 等）的好项照落、不连累（codex R2/R3：局部容器坏值不该触发整份重产）。⚠️ **跨 section 因果耦合**（如 `army_delta` 坏被拒、`economy_moves` 扣饷照落 = 「扣了钱军队没变」，gemini R3）：**仍不为它整份 abort** —— 这与 per-item 拒收是**同一个已接受的取舍**（坏项后果丢、但经拒收报告 + source-gated 邸报**响亮 surface**，玩家见「某事窒碍未行」，非静默半落库）；整份 abort 丢更多 + 重 extract 成本，违决定 1–3 的 per-item 原则。守原则、不破。
   - **嵌套字典字段也按实体逐项隔离（F2）**：`_NESTED_DICT_FIELDS`（`region_delta` / `army_delta` / `power_updates`）现状是「任一二级值非 dict → ValueError → 整份 abort」；须收窄为**逐实体**——`region_delta.shaanxi` 非 dict → 拒该实体（留痕）、保住 `region_delta.henan` 等合法实体，不整份退。「拆不出项」的判定**下沉到嵌套层**：能拆出实体就 per-实体；整个 `region_delta` 非 dict（拆不出实体）= **该 section 整体坏 → 按决定 7 拒该 section、其余 section 好项照落，不整份退**（整份退只在连 section 都拆不出，codex R3 P1：别把坏 section 升级成整份重产）。嵌套结构 = `region_delta: {<entity_id>: {<field>: <value>}}`（二级 key = 实体 id），逐个二级 key 隔离校验。**「嵌套字典字段」规则的精确边界（收口·gemini R4/R5 同一点）**：`_NESTED_DICT_FIELDS = {region_delta, army_delta, power_updates}`——规则**只适用于 schema 上二级值本身即为 dict 的字段**。`faction_delta`（二级值是**扁平 int**，`{"阉党": -10}`，prompt 允许的合法形，当 dict 校验反而错杀合法项）与 `class_delta` **结构上不属 validate 层的嵌套-dict 类，故不在该规则内——是定义域外、非例外**。二者在段适配器按各自契约处理：faction 扁平 int 合法；class 扁平 item 非法，依 #564 契约逐项 `invalid_enum` 拒收留痕，不静默跳过，也不带走同段合法项。明文见 `ming_sim/issues.py` 的 `_NESTED_DICT_FIELDS` 相邻说明。这既非「漏列」也非「与通用规则冲突」：通用规则的定义域本就是 nested-dict-shaped 字段。**此点 R4/R5/R6 三轮已定、移出复评**（gemini 连 3 轮念同一条「通用规则」、无新论据，全仓 grep 无该规则任何 config/styleguide 来源 = gemini 自带的内化规则、非本仓约定；属 memory 记的「gemini 多轮 drift 即驳回停」，后续不再 @gemini 复评此 ADR）。

**本决定修订 ADR 0008 决定 3**：`validate_delta_shape`「校验失败 → 整份重跑 extractor」收窄为「per-item 拒；**拆不出项才**整份重产」。按 later-doc-wins，validate 粒度以本 ADR 为准。

## Considered Options

- **整份 abort + re-ask（ADR 0008 原 stance）**：一个坏项重烧一次 extractor、还把同批好项一起卡。否决——per-item 隔离更省、更不丢后果（整份退只在拆不出项时）。
- **错位字段尽力路由 / 搭救**：还原目标常不唯一、要系统猜 LLM 意图；猜错把后果塞错实体，比拒收更毒，且 P4 玩家无表看不见。否决（不猜）。
- **per-item LLM 重 ask（方案 b）**：对坏项**单独再 ask 一次 LLM 重产**、成则进入，更贴 P1「后果当回合全量落库」。**但 token 开销 + 命中率（LLM 手抖→重 ask 能救 vs prompt 系统性坑→白烧）只有实跑游戏才知**（游戏吃 token，不实测不能拍）。作为 **deferred、flag-gated、自带度量（触发率/成功率/token 增量）+ kill 线、单项 capped 1 次 + 单项 soft-lock 兜底**的 spike，叠在本决定之上、失败**优雅降级回拒收**；不进地基契约（探针期不过早工程化，同 ADR 0008「不建自动回收 telemetry」）。**本决定的拒收留痕，正是日后判 b 值不值的数据源**（真跑几局看畸形项多久一次、哪类、像手抖还是系统坑）。落单独 spike issue **#207**（blocked-by #63），挂发版后「真实试玩检测环节」**#209** 下。

## Consequences

- #63 死法目录统一修法 = per-item 拒收契约（接 ADR 0005/0008 段适配器）：死法 2 = 拒收；new_issues = 拒主体坏项、容忍可选次要字段（数据门 #210）；validate 非 dict = 逐项拒 + 净化后再校验才入 `resolve_context`。
- #63 设计已定 → 评审收敛后从 ready-for-human 升 **ready-for-agent**（详设留 `/tdd`）。
- 实现期 `validate_delta_shape` / 拒收契约须做进：「净化后再校验」「逐项留痕」「非 dict 项包装（F1）」「留痕对 `resolve_context` 崩溃安全（F3）」「嵌套字段逐实体隔离（F2）」。
- **两个 deferred 数据门挂发版后 #209**：方案 b = **#207**（per-item LLM 重 ask 经济性）靠 #63 **拒收报告留痕（真拒收）** 当数据源；F4 = **#210**（new_issues 收紧到严格拒整项的频率门）靠**非阻塞容忍度量通道（不落 `rejection_reports` 行，codex R5 P2）** 当数据源——容忍归一非真拒收，两个数据源不可混（否则成功旨意被误判失败、重开 R4 洞）。
- 修订 ADR 0008 决定 3 的 validate 粒度。
- restore 无损不受影响：好项当回合全落、坏项留痕（崩溃安全），崩溃续跑读 `resolve_context`（干净那批）。
