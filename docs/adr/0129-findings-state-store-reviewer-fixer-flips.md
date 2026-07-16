> **修订（2026-07-15，#925 落地）**：「未决行数作关环取数」条款改为判词三态
> 取数（ADR 0131 / 0132）。毙单 `refuted` = 与 fresh 终翻并列的合法终翻。
> 写入/翻态/指针搬运机制保留。

Status: Proposed

> **限缩（ADR 0131，2026-07-13 owner 裁决；#899 typed-signal 终局；#925 判词化）**：
> findings 状态库是 reviewer-leg / fixer / 判官 之间的专业材料与状态真源，不是
> Runner 的信号来源。判官读库并自报判词三态；Runner 说判词是什么就是什么，
> 不查询、不派生、不对账 open-count。写入错误由写入 worker / Action 当场自纠；
> Action-owned structured retry 耗尽则当前 Action 非零退出。格式或写入失败不得
> 变成 decision gate；只有 worker 成功提交的真实专业、设计或范围决策请求才走
> decision gate。Runner 仍只消费三通道。

# 0129: findings 状态库——复审写行、修复翻状态、复审再验再翻；纠错在写入点

## 决定

评审循环的发现流转从「散文卷面 + runner 收账」改为 **findings 状态库**：

- 审卷腿 / 判官以**写行**交发现；
- 修复腿修复后**翻该行状态**（fixed，或 refuted + 证据——fixer 第二道闸）；
- **判官毙单**按四理由翻 `refuted`（#925：与 fresh 终翻并列的合法终翻）；
- 下一轮 fresh 审卷腿 + 判官验证后**再翻**（确认关闭 / 打回重开）并可选留言。

写入接口在**写入点**做字段与状态跳转校验，错误即时反馈给写入方自行改写；
Runner 不承担卷面审判，也不查询状态库。

**关环取数 = 判词三态**（`converged | continue | escalate`），**不是**未决行数 /
open-count。S5 只消费 `open` / live 单；死单（含毙单 `refuted`）不得进修复派发。

严重度与终态的具体口径归该 authority，不由 Runner 或状态库解释。判官完成
判断后向 Runner 自报判词，或主动提交需要人类决定（escalate → 既有 decision
gate）；不另造 worker outcome JSON。

## 定理（owner 2026-07-12）

runner 是交通警察，不是刑警：能力多大，责任才配多大——TS 代码没有判断能力，
就不得在简单调度里妄图「接住」LLM 本就不稳定的输出；校验归写入点、由有判断力
的写入方自纠。

因此 Runner 不为 review / fix 专业工作比较 commit / HEAD，不核对测试、报告或
修复证据，也不判断 coder / 判官 / fixer 的专业工作是否合格。这些材料由下一位
专业 worker 读取和判断；Runner 只根据 ADR 0131 三通道派下一棒。merge、冲突
落地或恢复所需的 Git / GitHub 外部事实由对应 Action 读取和核验，不进入 Runner。

## Supersede / 沿革

- ADR 0030「四判词由 runner 断言覆盖 / 压制预算 / 翻案上限」段：法庭拆除，
  判词沦为行状态与留言；争议行反复翻转的终止兜底 = 判官 escalate 决策门
  （#597 / #925），不设 runner 计数器。
- ADR 0050 原 family-cmr findings-return 版本的“blocking finding 返回 runner
  后再派 fixer”，沿革为判词驱动固定拓扑；角色分离不变。
- ADR 0062「typed 治理豁免」句：**收账法庭形态**的豁免对象消失；
  accepted_suppressed 的授权校验仍在专业写入点完成，错误反馈给写入方。
  三通道语义不变，信号②只读判词三态。
- 落账文件作为发现载体的机制：沿革为库；富内容仍 worker 间直达、不经 runner
  判断面。
- 2026-07-12 夜实证：收账法庭两次误杀活 run；r23 证明形式核验拦不住填表完美
  的假话——真相守卫从来是 fresh 跨模型复审 + 行为演练 + fix 测试 + 线上闸。
- **#925**：废「未决行数」作通道(b)取数；毙单 `refuted` 入合法终翻集合。

## 后果

漏答结构性不可能（阻塞行不翻恒开，无需「交代下落」）；多写行=多一条可追溯
记录，天然欢迎；非阻塞发现以其 review authority 定义的 terminal 留档，不制造
虚假 fixer 工作；驳回=一次状态翻转+证据留言，不需要词表发明；库形态选型 /
状态机定义 / 接口契约归 #861 实现票；判官工位归 #925。
