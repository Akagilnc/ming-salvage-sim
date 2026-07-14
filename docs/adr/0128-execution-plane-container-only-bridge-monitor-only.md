# 0128 — Sandcastle 单一拥有 agent 执行底座

- Status: Accepted（2026-07-12，#871 grill；2026-07-14 按 #863 架构审计修订）
- Date: 2026-07-11

**决策**：Execution Plane 只指真正运行自主 agent session 的环境；当前唯一执行底座是 Sandcastle。Scene Provisioning / Recovery 复用 Sandcastle 的 worktree 获取与 sandbox 生命周期，但 worker 结束时只关闭 sandbox/container；常驻 slice/family worktree 的删除不得交给 `Worktree.close()`，只走 ADR 0024 与 #868 授权的 Closure and Reclamation 入口。Worker Invocation 把可执行席位直接绑定为 Sandcastle `AgentProvider`，并复用其 `run`、session resume、结构化结果与 timeout 语义。host launcher 与 monitor 只负责开工、观察、取消和重入控制，不直接运行 agent CLI，也不另建 agent 执行协议。

每次 Worker Invocation 对一个已选席位只发起一次、single-iteration Sandcastle run；一次 agent invocation 仍在自己的 session 内完成完整 skill，专业 Action 有多条模型腿时每条腿各用自己的 run，不在 Sandcastle 外再套第二层 Ralph 或通用重试执行器。Sandcastle 原生结构化结果只承载 ADR 0131 的交通信号：reviewer 自报 open-count 或主动 decision gate，其他 worker 只在主动按门时携带 decision payload；普通成功仍由 exit code 表达。Human Decision Lifecycle 消费该 payload，Runner 只转运门、不读内容；普通报告与 findings 作为 opaque cargo/指针交给下一 Action。provider 确有已捕获、可恢复 session 时，same-seat 续跑才使用原 session；否则保留同一 worktree 并由 #868/#870 进入新的 invocation/relay。结构化结果失败的 same-session `maxRetries`（仅 resumable provider）、信号前 `idleTimeoutSeconds`、信号后 `completionTimeoutSeconds` 与取消均复用 Sandcastle 原生能力。

本仓不得重复实现 stdout tag parser、result sidecar、session 文件搬运或 cwd 改写、结构化结果修复循环、完成信号后的自制 hang-kill、sandbox/container 清理或 provider 命令执行层；也不得恢复普通 worker close 时的通用 worktree 清场。Sandcastle 尚未提供的业务能力才留在本仓：交付流程、专业 Action、固定选座与额度 Policy、Human Decision、ADR 0024/#868 授权的常驻 worktree 回收、外部副作用 reconciliation，以及进程重启后凭 durable locator 找回既有现场的最薄适配。若发现真实底层缺口，先形成可复现的 Sandcastle 能力差距，再决定上游补齐或保留窄适配。

**背景**：#684 R2 以 host 桥子进程实现监控句柄，属票面范围外长出（#814 调查坐实，commit 5ce70e31）；其中 host `hang-kill` 与 result sidecar 是现状迁移对象，不再是规范设计。grok-build 接通采用容器路线（镜像烤 Linux CLI + auth 副本挂载 + slug 注册，#807 原案），host 直跑变体（feat/807-pi-channel tip `4da2562b`，未进 main）不作默认架构。2026-07-14 对照 Sandcastle 公开 `RunResult`、structured output、session resume、worktree/sandbox 与 completion-timeout 能力后，明确以底层原生能力替代本仓重复包装。

**上游依据**：[Sandcastle API / Structured output](https://github.com/mattpocock/sandcastle#structured-output)、[Worktree lifecycle](https://github.com/mattpocock/sandcastle#createworktree--independent-worktree-lifecycle)、[ADR 0019：completion timeout](https://github.com/mattpocock/sandcastle/blob/main/docs/adr/0019-completion-timeout-for-hanging-process.md)。本仓当前主线依赖基线为 `@ai-hero/sandcastle ^0.12.0`。
