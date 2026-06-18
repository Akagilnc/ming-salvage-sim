# delta 落库失败统一按 per-item 拒收（含 validate 层）；整份重产只在拆不出项时（#63）

Status: Proposed（设计草案，2026-06-18；grill #63 warn-vs-reject 收敛。**修订 ADR 0008 决定3** 的 validate 粒度。待评审：本地 cmr + 线上三 bot 收敛后进实现期，#63 随之升 ready-for-agent。实现属编码、spawn 隔壁。file:line 指示性、以函数名为准。）

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
5. **new_issues 多字段 = 拒整项，不做字段级搭救**：一字段非法 → 拒整条 issue（「丢坏字段、剩下照建」= 推断「这条 issue 没那字段仍成立」，出局）。
6. **validate 非 dict 项 = 逐项拒**：丢坏项 → **净化后再过一遍 validate → 通过才入 `resolve_context`**（进重试真源的恒是逐项过了的那批，毒 payload 进不来，ADR 0008 决定 3 怕的永久 soft-lock 由此自动免疫）+ 走拒收留痕（否则 = 死法 3「零痕迹消失」搬到 validate 楼层重演）；原始坏项留**错误包**取证。
7. **整份 abort + 重跑 extractor 只剩一个场景**：delta 根本**拆不出项**（顶层非 dict / JSON 截断 / 整段非 list）——此时无「好项」要保，只能整份重产。**只要拆得出 N 项就走 per-item，永不整份退。**

**本决定修订 ADR 0008 决定 3**：`validate_delta_shape`「校验失败 → 整份重跑 extractor」收窄为「per-item 拒；**拆不出项才**整份重产」。按 later-doc-wins，validate 粒度以本 ADR 为准。

## Considered Options

- **整份 abort + re-ask（ADR 0008 原 stance）**：一个坏项重烧一次 extractor、还把同批好项一起卡。否决——per-item 隔离更省、更不丢后果（整份退只在拆不出项时）。
- **错位字段尽力路由 / 搭救**：还原目标常不唯一、要系统猜 LLM 意图；猜错把后果塞错实体，比拒收更毒，且 P4 玩家无表看不见。否决（不猜）。
- **per-item LLM 重 ask（方案 b）**：对坏项**单独再 ask 一次 LLM 重产**、成则进入，更贴 P1「后果当回合全量落库」。**但 token 开销 + 命中率（LLM 手抖→重 ask 能救 vs prompt 系统性坑→白烧）只有实跑游戏才知**（游戏吃 token，不实测不能拍）。作为 **deferred、flag-gated、自带度量（触发率/成功率/token 增量）+ kill 线、单项 capped 1 次 + 单项 soft-lock 兜底**的 spike，叠在本决定之上、失败**优雅降级回拒收**；不进地基契约（探针期不过早工程化，同 ADR 0008「不建自动回收 telemetry」）。**本决定的拒收留痕，正是日后判 b 值不值的数据源**（真跑几局看畸形项多久一次、哪类、像手抖还是系统坑）。落单独 spike issue，blocked-by #63。

## Consequences

- #63 死法目录统一修法 = per-item 拒收契约（接 ADR 0005/0008 段适配器）：死法 2 = 拒收；new_issues = 拒整项；validate 非 dict = 逐项拒 + 净化后再校验才入 `resolve_context`。
- #63 设计已定 → 评审收敛后从 ready-for-human 升 **ready-for-agent**（详设留 `/tdd`）。
- 方案 b 记成单独 spike issue、blocked-by #63；等真实拒收数据再开 go/no-go。
- 修订 ADR 0008 决定 3 的 validate 粒度；实现期 `validate_delta_shape` 须把「净化后再校验」「逐项留痕」做进契约。
- restore 无损不受影响：好项当回合全落、坏项留痕，崩溃续跑读 `resolve_context`（干净那批）。
