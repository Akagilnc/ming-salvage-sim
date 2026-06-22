---
status: proposed
supersedes-part-of: ADR 0018 (step 分类)
---

# 编排器 runner = 纯调度器；每个具体 wiki 步是 worker

**决定**：runner 只做**调度**——step 之间的流程决策（input gate / route / 排序 / step ledger / 续跑）；它**不内联任何具体活**。每个产出工作的 wiki 步——写码 / 评审 / cmr / ship / merge——是一个 **worker**：跑在自己容器里、里面 agent 是该容器**顶层**（非 runner 的 sub，故能起自己的 sub + CLI），由 runner 派出去执行、收回结果、据此路由。worker **不一定用 skill**；用时 Claude = `Skill` invoke、Codex = 加载 SKILL.md 当 skill item 传入 prompt。

**为什么**：ADR 0018 让 runner 控外层序列（防 agent 跳步/合并步），但把 `push / cmr / ship` 归成「runner 动作」（纯 TS 内联）。结果 runner **自己手搓**了 cmr（三腿）和 ship（push+PR）的等价逻辑，而不是 invoke 现成的 `ak-cross-m-review` / `gstack-ship` skill —— 偏离了「忠实跑 wiki 流程」。把这些改成 worker 步后，runner **薄到没东西可偏**，具体纪律全活在 worker invoke 的 skill 里。

**步边界 = 路由/分叉点**（判据：步内无需调度）。无分叉的连续活可按 smart zoom 合成大步（省调度、但吃上下文）；**任何分叉点必须是 runner 边界、不能埋进 worker**——否则 worker 内 agent 自跑一条带分叉的流程，正是 ADR 0018 要弄死的。cmr 出 findings → fix-or-proceed 是分叉，故 cmr 必然是独立 worker、fix-loop 归 runner。

## Consequences

- **supersede ADR 0018 的 step 分类**：`push / cmr / ship` 从「runner 动作」改成「worker 步」；runner 只剩纯调度决策（gate / route / 排序 / ledger / 续跑）。
- **fresh vs resume 按活类型**：生产类（coder/fix）`resumeSession`（留上下文）；评审类（cmr）每轮 fresh（cross-model 独立性，不复查自己旧 finding）。沙堡原生 resume 撑住 fix-loop。
- **落实 ADR 0016 的 bake**：每个 worker = 从**一个预制镜像**起的容器，工具链 + 多模型 CLI + dev skills + 角色 soul **全烤进镜像**（不 runtime bind-mount，可复现）。
- **scope = A（自治 implement→ship）先建**；grill / to-prd / to-issues（带上下文 + HITL 的 worker）= B，模型已通用装得下、以后再做、不为它现在特殊化。
- **留 to-prd / 实现**：A 段切成哪几个 worker（对到现 S0–S8）、worker↔runner 结果契约、容器启动成本 vs 步粒度。
