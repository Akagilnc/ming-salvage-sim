# v1 编排器 = runner 驱动的固定 step 序列（StepSpec + ledger）；agent 只在一步内执行，不推进 / 不跳 / 不改流程

Status: Proposed（2026-06-20；grill-with-docs 第二轮收敛，整合 gpt-5.5-pro stepper 方向 + Sandcastle 原生原语实证（`createSandbox` 容器保活多 run、`resumeSession`/`fork`、`createWorktree` first-class、`completionSignal`、`Output.object`）。**尚未 Accepted** —— 待设计评审闭环。**取代 ADR 0016 v1 §3「coder 一个 run 跑完整 wiki 流程、自己判完成」**。）

## 背景

实证痛点：编排出错几乎全在**外层步骤序列**（跳步 / 合并步 / 改流程 / agent 自己决定下一步），不在步内执行（`/tdd` 内层红绿很少错）。ADR 0016 v1 §3 把整条 wiki 流程交给 coder 在一个 run 里自跑、自判完成——而「agent 自跑整条」正好让它能跳 / 合并 / 变形（不可复现，正是要弄死的）。CLAUDE.md / soul / prompt 只能提高「步内行为」的概率，管不了「步有没有跳」——那必须由外层 runner 控。

## 决定

**外层 wiki 步骤由 runner（TS 代码）逐步推进；agent 只在单步内执行，永不决定下一步。**

1. **一个 wiki 外层步骤 = 一个 StepSpec = 一次 `sandbox.run()`**：固定 `promptFile` + 固定 agent/model + 固定 `completionSignal` + 固定 output schema（`Output.object`）+ 每步各设的 `maxIterations`。
2. **下一步由 runner 的 `route()` 定，不由 agent**：agent 在步内再想跳到别的步也没用——下一步是 TS 调的。
3. **`/tdd` 内层红绿留给 skill，v1 不机器验**：runner 只保证某步一定被调用、且喂的是统一 prompt；红绿重构是否忠实执行靠 Matt `/tdd` + 项目 skill（步内执行，v1 不是主要问题）。
4. **每步写 step ledger**：防跳步真源（事后看跳没跳）+ 续跑真源（下一步只读 ledger，不靠 LLM 记忆）。一条 = run_id / step / promptFile / prompt_hash / agent / model / completionSignal / commits before-after / log_file / output_json / **sessionId（resume 用）**。
5. **prompt 注入权归 runner**：`promptFile`（版本化、frontmatter 标 `source: wiki/...`）+ `promptArgs`（只填变量 issue_number / branch / findings_path）；不临场拼大 prompt、不「参考 wiki 那套做一下」。

**v1 步骤表（S0–S8）**：

| # | step | 谁 | maxIter | 干啥 |
|---|---|---|---|---|
| S0 | input_gate | shell/runner | — | rfa ∧ 有 `## Agent Brief` ∧ 自身不挂子 issue（非父/非未切 epic），否则报错打回调用者 |
| S1 | load_context | shell/gh | — | 输入快照 = body + comments + 最新 Agent Brief（权威 spec）+ native metadata |
| S2 | coder_implement | coder(Sonnet) | >1 | invoke `/tdd` + 项目 skill → commit + 顺手打包证据 → `IMPLEMENT_DONE` |
| S3 | reviewer_full_review | reviewer(Opus 4.8) | 1 | full diff + 读源码、只评不改 → `REVIEW_DONE` + findings JSON |
| S4 | route_findings | runner | — | 有 P0/P1 → S5；无 → S7 |
| S5 | coder_fix | coder | >1 | findings + `/diagnosing-bugs` → 修 + 自查二连 → commit → `FIX_DONE` |
| S6 | reviewer_rereview | reviewer | 1 | 全量复审（非点检）→ findings → 回 S4 |
| S7 | push_branch | shell | — | push 分支（不 PR、不 merge） |
| S8 | handoff | runner | — | 输出 branch / commits / 轮次 / defer 清单 / logs（读 ledger） |

**fix loop 收敛 / 升级（堵死循环，不用 diagnose 机器）**：runner 按 reviewer JSON 确定性路由（有 P0/P1 → 修、无 → push；余 P2/P3 进 defer 清单上浮、不挡）。不收敛历史上仅 1–2 次 → v1 不造自动 drift 诊断：**模型自己判 stuck 时发 escalate 信号**（不数轮数）→ runner 停、落 ledger（sessionId）→ 返回调用端（切片 ← 主 session ← 用户）→ **tester（人）判**怎么办 → `resumeSession` 续跑。

## Considered Options

- **大 prompt、agent 自跑整条**（ADR 0016 v1 §3 原样）：少接线，但 agent 能跳 / 合并 / 改流程、不可复现 → 否决（正是痛点）。
- **LangGraph**：v1 状态机线性（implement → review → fix loop → push），Sandcastle + TS while 够；LangGraph 的价值（多 issue 并行 / 父 epic 拓扑 / 长期挂起 / worker 池 / 可视化）在**家族编排阶段**才用 → v1 不上。
- **机器验 `/tdd` 内层红绿**：步内执行很少错、机器化代价高 → v1 不做，留给 skill。
- **Sandcastle Step Runner（本决定）**：薄 stepper，不是通用 orchestration framework；机器只控真出错的外层序列。

## Consequences

- **取代 ADR 0016 v1 §3** 的「coder 一个 run 跑完整流程、自判完成」；角色（coder / reviewer）不变，改的是「它们怎么被排序」= runner 逐步。
- **每步独立 `run()` = 步间 fresh context** → ADR 0016 v1 §4 要的「上下文隔离」白送（reviewer S3 看不到 coder S2 的推理）。
- **step ledger = ADR 0017「状态落盘」的具体化**，也是 resume 底（每步 persist sessionId，`resumeSession` 续跑；escalation 续跑与崩溃续跑同一套机器）。
- **promptFile 是 wiki 的版本化派生** → 流程活在两处（wiki + `.sandcastle/prompts/`），sync 风险靠 `source:` frontmatter + ledger `prompt_hash` 兜（漂了看得见），不另造同步机器。
- **maxIterations 每步各设**（S2 / S5 调 /tdd、/diagnosing = >1；单发步 = 1）——不一刀切 1（`/tdd` 内层是多 iteration 循环）。
- **每步结构化输出容错**：completionSignal 没 emit / schema 不合（实证：codex 不保证合 zod → `StructuredOutputError` 硬崩）→ retry 一次，再不行 surface 给 tester（v1 简单兜）。
- 收敛由 runner 确定性路由（看 P0/P1），但「严重度 / 何时 stuck 升级」是模型出的结构化判断——既「模型判断」又「不跳步 / 不死循环」。
