# 0128 — Sandcastle 单一拥有 agent 执行底座

- Status: Accepted（2026-07-12，#871 grill；2026-07-14 按 #863 架构审计修订）
- Date: 2026-07-11

**决策**：Execution Plane 只指真正运行自主 agent session 的环境；当前唯一执行底座是 Sandcastle。Scene Provisioning / Recovery 复用 Sandcastle 的 worktree、sandbox 与 close 生命周期；Worker Invocation 把可执行席位直接绑定为 Sandcastle `AgentProvider`，并复用其 `run`、session resume、结构化结果与 timeout 语义。host launcher 与 monitor 只负责开工、观察、取消和重入控制，不直接运行 agent CLI，也不另建 agent 执行协议。

每次 Worker Invocation 对一个已选席位的调用只发起一次 Sandcastle run；专业 Action 有多条模型腿时，每条腿分别使用自己的 Worker Invocation/run，不在 Sandcastle 外再套第二层 Ralph 或重试执行器。需要多 iteration 的实现/修复 worker 使用 Sandcastle 自带的 `maxIterations` 与纯终止 `completionSignal`，不另交业务 outcome；后续专业 reviewer 负责判断工作结果。需要机器可读交卷的单次 reviewer 使用 `Output.object` 与 `result.output`，格式修复使用 Sandcastle 的 structured-output retry。same-seat 续跑使用 Sandcastle 原生 session resume；新席位在同一 worktree 上启动新 session。无输出卡死与已经发出完成信号但进程未退出分别由 `idleTimeoutSeconds` 与 `completionTimeoutSeconds` 处理。

本仓不得重复实现 stdout tag parser、result sidecar、session 文件搬运或 cwd 改写、结构化结果修复循环、完成信号后的自制 hang-kill、worktree/sandbox 清理或 provider 命令执行层。Sandcastle 尚未提供的业务能力才留在本仓：交付流程、专业 Action、固定选座与额度 Policy、Human Decision、外部副作用 reconciliation，以及进程重启后凭 durable locator 找回既有现场的最薄适配。若发现真实底层缺口，先形成可复现的 Sandcastle 能力差距，再决定上游补齐或保留窄适配。

**背景**：#684 R2 以 host 桥子进程实现监控句柄，属票面范围外长出（#814 调查坐实，commit 5ce70e31）；其中 host `hang-kill` 与 result sidecar 是现状迁移对象，不再是规范设计。grok-build 接通采用容器路线（镜像烤 Linux CLI + auth 副本挂载 + slug 注册，#807 原案），host 直跑变体（feat/807-pi-channel tip `4da2562b`，未进 main）不作默认架构。2026-07-14 对照 Sandcastle 公开 `RunResult`、structured output、session resume、worktree/sandbox 与 completion-timeout 能力后，明确以底层原生能力替代本仓重复包装。

**上游依据**：[Sandcastle API / Structured output](https://github.com/mattpocock/sandcastle#structured-output)、[ADR 0010：structured output 与 completion signal 正交](https://github.com/mattpocock/sandcastle/blob/main/docs/adr/0010-structured-output.md)。本仓当前依赖基线为 `@ai-hero/sandcastle ^0.10.0`。
