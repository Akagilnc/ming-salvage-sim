---
status: proposed
supersedes-part-of: ADR 0018 (step 分类 + 生产类步「步间 fresh context」改 resumeSession); ADR 0016 (spike 发现4 的 cmr/gstack 不进容器排除)
---

# 编排器 runner = 纯调度器；每个具体 wiki 步是 worker

**决定**：runner 只做**调度**——step 之间的流程决策（input gate / route / 排序 / step ledger / 续跑）；它**不内联任何具体活**。每个产出工作的 wiki 步——写码 / 评审 / cmr / ship / merge——是一个 **worker**：跑在自己容器里、里面 agent 是该容器**顶层**（非 runner 的 sub，故能起自己的 sub + CLI），由 runner 派出去执行、收回结果、据此路由。worker **不一定用 skill**；用时 Claude = `Skill` invoke、Codex = 加载 SKILL.md 当 skill item 传入 prompt。

**为什么**：ADR 0018 让 runner 控外层序列（防 agent 跳步/合并步），但把 `push / cmr / ship` 归成「runner 动作」（纯 TS 内联）。结果 runner **自己手搓**了 cmr（三腿）和 ship（push+PR）的等价逻辑，而不是 invoke 现成的 `ak-cross-m-review` / `gstack-ship` skill —— 偏离了「忠实跑 wiki 流程」。把这些改成 worker 步后，runner **薄到没东西可偏**，具体纪律全活在 worker invoke 的 skill 里。

**步边界 = 路由/分叉点**（判据：步内无需调度）。无分叉的连续活可按 smart zoom 合成大步（省调度、但吃上下文）；**任何分叉点必须是 runner 边界、不能埋进 worker**——否则 worker 内 agent 自跑一条带分叉的流程，正是 ADR 0018 要弄死的。cmr 出 findings → fix-or-proceed 是分叉，故 cmr 必然是独立 worker、fix-loop 归 runner。

**这推翻 ADR 0016 spike 发现4 的一条排除**：0016 当时判「`ak-cross-m-review` 是单 session 扇出工具、塞不进容器，cmr 在 pipeline 层用不同模型 run() 实现；gstack 不进实现腿」。该前提已被实测证伪（2026-06-22 spike，见 #333）：容器顶层 agent 能 invoke 真 skill 并起满三腿——codex（rc=0 真评审）+ claude `Task` 腿 + agy（Linux 二进制 + 文件 token），均在容器内逮到注入 bug。故 cmr/ship 改为容器 worker invoke 真 skill，runner 不再手搓近似。

## Consequences

- **supersede ADR 0018 的 step 分类**：`push / cmr / ship` 从「runner 动作」改成「worker 步」；runner 只剩纯调度决策（gate / route / 排序 / ledger / 续跑）。
- **supersede ADR 0016 的 cmr/gstack 排除**：`ak-cross-m-review` / `gstack-ship` 改为烤进镜像、由容器 worker invoke（取代 0016 的「pipeline 层 run() / 不进容器」）。三腿容器内实证可行（#333）；agy 走文件 token（`~/.gemini/antigravity-cli/antigravity-oauth-token`，runtime 挂载，同 codex/claude auth 模式）。
- **fresh vs resume 按活类型**：生产类（coder/fix）`resumeSession`（留上下文）；评审类（cmr）每轮 fresh（cross-model 独立性，不复查自己旧 finding）。沙堡原生 resume 撑住 fix-loop。**这 narrows ADR 0018「步间 fresh context」对生产类步,并把 ADR 0017 的 `resumeSession` 从「仅崩溃/escalate 续跑」扩到 fix-loop 上下文保留**（reviewer/cmr 步仍 fresh）。**fresh ≠ 新 checkout**：fresh worker 容器仍挂同一条 host 常驻 slice worktree（ADR 0017：提交真源 = 常驻 worktree），fresh 只是 run()/上下文 fresh，提交绝不落进临时 checkout。
- **落实 ADR 0016 的 bake**：每个 worker = 从**一个预制镜像**起的容器，工具链 + 多模型 CLI + dev skills + 角色 soul **全烤进镜像**。**「不 runtime bind-mount」只指这些工具/技能/soul/资产**（故可复现）;runtime 仍挂 = 被加工的常驻 slice worktree（ADR 0017 提交真源,见上条）+ auth token —— 必要例外、非矛盾。
- **scope = A（自治 implement→ship）先建,B（grill/to-prd/to-issues 带上下文+HITL）以后**；worker 清单 / worker↔runner 结果契约 / 容器粒度等实现细节见 PRD #330。
