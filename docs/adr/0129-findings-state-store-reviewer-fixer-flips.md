Status: Accepted（2026-07-13；证据：#871 doc-mode CMR R15/R16 consecutive clear）

> **限缩（ADR 0131，2026-07-13 owner 裁决）**：findings 状态库是 reviewer / fixer 之间的专业材料与状态真源，不是 Runner 的信号来源。reviewer 自己读取库并自报 open-count；Runner 说几条就是几条，不查询、不派生、不对账。写入错误由写入 worker / Action 当场自纠；无法完成交卷时由该 worker 自按 decision gate 或让 invocation 非零退出，不新增 Runner 第四通道。fresh 终翻规则不变。

# 0129: findings 状态库——复审写行、修复翻状态、复审再验再翻；纠错在写入点

## 决定

评审循环的发现流转从「散文卷面 + runner 收账」改为 **findings 状态库**：复审员以**写行**交发现；修复腿修复后**翻该行状态**（fixed，或 refuted + 证据）；下一轮复审员验证后**再翻**（确认关闭 / 打回重开）并可选留言。写入接口在**写入点**做字段与状态跳转校验，错误即时反馈给写入方自行改写；Runner 不承担卷面审判，也不查询状态库。**阻塞项只有下一轮 fresh 复审员的终翻才解除未决态；fixer 自翻的 fixed / refuted 仍计入未决数**。P4 也必须入库，但由 reviewer 直接写为 `deferred` / non-blocking 终态，不进 fixer 循环、不计入 open-count；延后需满足 CMR 契约的严格条件，不是普通缓办筐。reviewer 完成判断后向 Runner 自报阻塞未决数 `0` 或 `>0`，或主动提交需要人类决定；不另造 worker outcome JSON。

## 定理（owner 2026-07-12）

runner 是交通警察，不是刑警：能力多大，责任才配多大——TS 代码没有判断能力，就不得在简单调度里妄图「接住」LLM 本就不稳定的输出；校验归写入点、由有判断力的写入方自纠。

因此 Runner 不为 review / fix 专业工作比较 commit / HEAD，不核对测试、报告或修复证据，也不判断 coder / reviewer / fixer 的专业工作是否合格。这些材料由下一位 reviewer / fixer 读取和判断；Runner 只根据 ADR 0131 三通道派下一棒。merge、冲突落地或恢复所需的 Git / GitHub 外部事实由对应 Action 读取和核验，不进入 Runner。

## Supersede / 沿革

- ADR 0030「四判词由 runner 断言覆盖 / 压制预算 / 翻案上限」段：法庭拆除，判词沦为行状态与留言；争议行反复翻转的终止兜底 = 复审员自升级决策门（#597），不设 runner 计数器。
- ADR 0050 原 family-cmr findings-return 版本的“blocking finding 返回 runner 后再派 fixer”，沿革为 reviewer 自报 open-count 驱动固定拓扑；reviewer / fixer / fresh reviewer 的角色分离不变。
- ADR 0062「typed 治理豁免」句：**收账法庭形态**的豁免对象消失；accepted_suppressed 的授权校验仍在专业写入点完成，错误反馈给写入方。三通道语义不变，信号②只读 reviewer 自报数。
- 落账文件作为发现载体的机制：沿革为库；富内容仍 worker 间直达、不经 runner 判断面。
- 2026-07-12 夜实证：收账法庭两次误杀活 run（多报真修复被判死）；r23 证明形式核验拦不住填表完美的假话——真相守卫从来是 fresh 跨模型复审 + 行为演练 + verify 测试 + 线上闸，法庭只提供假安全感。

## 后果

漏答结构性不可能（阻塞行不翻恒开，无需「交代下落」）；多写行=多一条可追溯记录，天然欢迎；P4 以明确 non-blocking 终态留档，不制造虚假 fixer 工作；驳回=一次状态翻转+证据留言，不需要词表发明；库形态选型 / 状态机定义 / 接口契约归 #861 实现票。
