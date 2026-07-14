# 0134. 第一版路线直接排列可执行席位

Date: 2026-07-14

## Status

Proposed

## Decision

第一版以“接入渠道 + 模型”识别可执行席位，xAI/Grok 与 Cursor/Grok 视为两个独立候选；各角色路线直接给出固定席位顺序，显式顺序中的未知席位在任何现场副作用前报配置错误。启动只点检各角色当前首选；首选失败或运行中需要交棒时才点检下一席位，固定表走完即“当前无可用席位”。Policy 不读取 finding、不数 review/fix 轮数，也不接受 worker 对模型质量的主观判定；worker 无法继续与客观候选耗尽都复用既有 decision gate 喊人，不做跨池同模型归一、动态评分或与候选数量无关的全局换棒次数限制。

每个可执行席位直接解析为 Sandcastle `AgentProvider`；Policy 只返回席位、等待或候选耗尽，真正执行统一交给 #868 Worker Invocation，并完整遵守 ADR 0128。本文不重复定义 worktree、sandbox、result、session、timeout 或 retry 机制。

## Consequences

ADR 0124 的模型/池正交匹配、ADR 0126 的同模型优先换池与质量轮数换棒，以及 ADR 0133 的同池 checkpoint 优先均被本决定收窄；ADR 0125 的额度阈值与等待/换棒分流保留，但候选耗尽从静默 park 收窄为保留现场并走既有 decision gate。现有指标继续记录，等真实数据支持评分时再另行设计。

#870 的实现切片只补 Sandcastle 不提供的固定选座与额度业务语义；所有 agent 执行能力直接复用 ADR 0128，不在 Policy 或 Runner 旁边建立第二套包装。
