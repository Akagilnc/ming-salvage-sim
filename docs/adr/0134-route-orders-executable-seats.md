# 0134. 第一版路线直接排列可执行席位

Date: 2026-07-14

## Status

Accepted（2026-07-14；#870 本地 CMR R7/R8 + PR #908 R1/R2；架构复盘补清 preflight / resume 边界）

## Decision

第一版以“接入渠道 + 模型”识别可执行席位；各角色路线直接给出固定席位顺序，显式顺序中的未知席位在任何现场副作用前报配置错误。席位身份仍可包含接入渠道与模型，但 current candidate 必须服从 #905 / PR #912：`agy` 是真实 agy CLI，所有 `grok-4.5` 只经 grok-build / SuperGrok provider；OpenCode、Cursor/Grok 与 glm-via-OpenCode 不得进入 registry、route 或 onboarding。启动只点检各角色当前首选；首选失败或运行中需要交棒时才点检下一席位，固定表走完即“当前无可用席位”。Policy 不读取 finding、不数 review/fix 轮数，也不接受 worker 对模型质量的主观判定；成功工作的 worker 确有专业、设计或范围决策时，以及客观候选耗尽时，复用既有 decision gate 喊人。不做跨池同模型归一、动态评分或与候选数量无关的全局换棒次数限制。

每个可执行席位直接解析为 Sandcastle `AgentProvider`。Policy 同时拥有无副作用的路线配置预检与运行期机械选座：Ignition 在任何新 scene / worker 副作用前调用前者，需要模型的专业 Action 通过 #868 Worker Invocation capability 调用后者；Runner 不消费两者。重入时，正在进行的 invocation 固定其已选席位；只有该席位确有已捕获、可恢复 session 时才恢复原 session，不因配置变化被强制换座。没有 resumable session 时，现场仍保留，但后续必须作为新的 invocation/relay 按最新已验证候选顺序选座，不能伪称 ordinary resume；尚未开始的 invocation 与真实 relay 同样使用最新顺序。真正执行统一通过该 capability 完成并完整遵守 ADR 0128；本文不重复定义 worktree、sandbox、result、session、timeout 或 retry 机制。

typed open-count / decision-gate signal 的 Action-owned structured retry 与写入纠错若耗尽，当前 Action 必须非零退出；格式错误、写入失败或无法形成 typed signal 不得升级为 decision gate。Runner 仍只消费 ADR 0131 三通道，具体 typed retry 契约只读 #899。

## Consequences

ADR 0124 的模型/池正交匹配、ADR 0126 的同模型优先换池与质量轮数换棒，以及 ADR 0133 的同池 checkpoint 优先均被本决定收窄；ADR 0125 的额度阈值与等待/换棒分流保留，但候选耗尽从静默 park 收窄为保留现场并走既有 decision gate。现有指标继续记录，等真实数据支持评分时再另行设计。

#870 的实现切片只补 Sandcastle 不提供的固定选座与额度业务语义；所有 agent 执行能力直接复用 ADR 0128，不在 Policy 或 Runner 旁边建立第二套包装。
