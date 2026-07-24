# v1 编排器 = runner 驱动外层步骤序列；agent 只在步内执行，不决定下一步

Status: Proposed

Current authority: #869 单一拥有现行交付拓扑，ADR 0131 单一拥有 Runner 三通道。下文旧 `completionSignal`、output schema、reviewer JSON 内容路由与 Runner prompt 注入权均废止，不得作为实现依据。

## 背景

实证痛点：编排出错几乎全在**外层步骤序列**（跳步 / 合并步 / 改流程 / agent 自己决定下一步），不在步内执行（`/tdd` 内层红绿很少错）。把整条 wiki 流程交给 agent 在一个 run 里自跑、自判完成，正好让它能跳 / 合并 / 变形（不可复现）。CLAUDE.md / soul / prompt 只能提高「步内行为」的概率，管不了「步有没有跳」——那必须由外层 runner 控。

## 决定

**外层交付顺序由 #869 固定；worker 只完成当前角色 / Action，不自行跨角色决定下一步。**

1. 每个专业 worker 只完成一个明确 Action / 角色范围；Runner 按 #869 固定拓扑与 ADR 0131 三通道调用下一 Action，不解析 completionSignal、output schema 或 worker 内容。
2. **`/tdd` 内层红绿留给 skill，v1 不机器验**（步内执行很少错，机器化代价不划算）。
3. **step ledger 只作 Flow-owned 历史投影**：Flow 拥有 program counter 语义，Lineage 单一持久化当前 flow position 与投影；Runner 只执行 Flow 给出的 fixed position，不从 ledger 推导下一步、动作完成或 session 恢复。
4. 需要模型的专业 Action 通过共享 Worker Invocation capability 完成固定运行上下文装配；`Runtime Context Materialization` 不再是独立 Action。该 capability 不是 Flow position，Runner 不临场拼方法 prompt，也不读取其内容。
5. review loop 只读取 judge typed tri-state，并按 #869 固定拓扑继续；worker 主动提交 decision gate 时由 Runner 原样转运，进程成败由 exit code 表达。Runner 不看 reviewer prose、严重度、action 字段或 finding 内容。

> 旧 S0–S8 / StepSpec / 结构化输出路由只保留为历史背景；现行顺序见 #869，Runner 边界见 ADR 0131。

## Considered Options

- **大 prompt、agent 自跑整条**（ADR 0016 v1 §3 原样）：少接线，但 agent 能跳 / 合并 / 改流程、不可复现 → 否决（正是痛点）。
- **LangGraph**：v1 状态机线性，Sandcastle + TS while 够；LangGraph 的价值（多 issue 并行 / 拓扑 / 长挂起 / worker 池 / 可视化）在家族编排阶段才用 → v1 不上。
- **机器验 `/tdd` 内层红绿**：步内很少错、代价高 → v1 不做，留给 skill。
- **Sandcastle Step Runner（本决定）**：薄 stepper，不是通用 orchestration framework；机器只控真出错的外层序列。

## Consequences

- **取代 ADR 0016 v1 §3** 的「coder 一个 run 跑完整流程、自判完成」；角色不变，改的是「它们怎么被排序」= runner 逐步。
- **每步独立 `run()` = 步间 fresh context** → ADR 0016 v1 要的「上下文隔离」白送（reviewer 看不到 coder 的「我刚写的」推理）。
- **step ledger 是经 Lineage 持久化的审计投影**，不是独立恢复底座；scene/session locator 与 flow position 的 durable 真源只归 Lineage，准确恢复所有权见 #867。
