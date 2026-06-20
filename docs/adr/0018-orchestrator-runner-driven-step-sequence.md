# v1 编排器 = runner 驱动外层步骤序列；agent 只在步内执行，不决定下一步

Status: Accepted（2026-06-20；grill-with-docs 第二轮收敛，整合 gpt-5.5-pro stepper 方向 + Sandcastle 原生原语实证（`createSandbox` 容器保活多 run、`resumeSession`/`fork`、`createWorktree`、`completionSignal`、`Output.object`）。**评审闭环完成**：本地 cmr 6 轮收敛 + 线上 bot（PR #246）。**取代 ADR 0016 v1 §3「coder 一个 run 跑完整 wiki 流程、自己判完成」**。）

## 背景

实证痛点：编排出错几乎全在**外层步骤序列**（跳步 / 合并步 / 改流程 / agent 自己决定下一步），不在步内执行（`/tdd` 内层红绿很少错）。把整条 wiki 流程交给 agent 在一个 run 里自跑、自判完成，正好让它能跳 / 合并 / 变形（不可复现）。CLAUDE.md / soul / prompt 只能提高「步内行为」的概率，管不了「步有没有跳」——那必须由外层 runner 控。

## 决定

**外层 wiki 步骤由 runner（TS 代码）逐步推进；agent 只在单步内执行，永不决定下一步。**

1. **一个 agent 步 = 一次 `sandbox.run()`**（固定 promptFile + agent + completionSignal + output schema）；runner 动作步（input_gate / load_context / route / push / handoff）是纯 TS、不跑 agent；**下一步由 runner 的 `route()` 定、不由 agent**——agent 在步内再想跳别处也没用。
2. **`/tdd` 内层红绿留给 skill，v1 不机器验**（步内执行很少错，机器化代价不划算）。
3. **每步写 step ledger** = 防跳步真源（事后看跳没跳）+ 续跑真源（下一步只读 ledger，不靠 LLM 记忆）。
4. **prompt 注入权归 runner**（版本化 promptFile + promptArgs 只填变量），不临场拼大 prompt、不「参考 wiki 那套做一下」。
5. **fix loop 收敛 = runner 确定性路由**（看 reviewer JSON：有 P0/P1 **或 `action:'fix_now'` 的 P2/P3** → 修；否则 → push，与 PRD #244 S4 路由表一致）；不收敛靠**模型发 escalate 信号**（不数轮数）→ 人判 → `resumeSession` 续跑——不造自动 drift 诊断机器。

> 具体步骤表（S0–S8）/ StepSpec 字段 / ledger schema / 路由细节 / maxIter 分配 / 结构化输出容错 = **实现 spec，见 PRD #244 Implementation Decisions**（ADR 只记决定、不记 spec）。

## Considered Options

- **大 prompt、agent 自跑整条**（ADR 0016 v1 §3 原样）：少接线，但 agent 能跳 / 合并 / 改流程、不可复现 → 否决（正是痛点）。
- **LangGraph**：v1 状态机线性，Sandcastle + TS while 够；LangGraph 的价值（多 issue 并行 / 拓扑 / 长挂起 / worker 池 / 可视化）在家族编排阶段才用 → v1 不上。
- **机器验 `/tdd` 内层红绿**：步内很少错、代价高 → v1 不做，留给 skill。
- **Sandcastle Step Runner（本决定）**：薄 stepper，不是通用 orchestration framework；机器只控真出错的外层序列。

## Consequences

- **取代 ADR 0016 v1 §3** 的「coder 一个 run 跑完整流程、自判完成」；角色不变，改的是「它们怎么被排序」= runner 逐步。
- **每步独立 `run()` = 步间 fresh context** → ADR 0016 v1 要的「上下文隔离」白送（reviewer 看不到 coder 的「我刚写的」推理）。
- **step ledger = ADR 0017「状态落盘」同一份**，也是 `resumeSession` 续跑底（升级续跑与崩溃续跑同一套机器）。
