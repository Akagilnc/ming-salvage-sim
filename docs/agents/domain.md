# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root — the project's domain language and glossary.
- **`docs/adr/`** — read ADRs that touch the area you're about to work in.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The producer skill (`/grill-with-docs`) creates them lazily when terms or decisions actually get resolved.

## File structure

This is a single-context repo:

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-keep-api-and-cli-llm-channels-parallel.md
│   ├── ...
│   └── 0008-settlement-applier-contract-and-transaction-boundary.md
└── ming_sim/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal — either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/grill-with-docs`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0004 (probe driver reuses engine settle core) — but worth reopening because…_

## 文档三层 + ADR 颗粒度（采 Matt Pocock grill-with-docs DDD）

**文档三层（采 Matt Pocock grill-with-docs DDD）**：① `CONTEXT.md`=领域词表（是什么、零实现）；② `docs/adr/`=非显然决策的为什么（**ADR-FORMAT：1-3 句、单决策、稀有**，hard-to-reverse / surprising / real-tradeoff 才建，不是 spec；大模板会把可逆细节吸进来＝过度设计，避开）；③ 详设/代码任务 → issue；④ 实现 → 代码。给 AI 最薄一层。

**评审强度跟反悔成本走**：设计审狠（反悔贵）、代码审正确性。

## ADR 生命周期：「Accepted」≠「已实现」（Matt skills #299）

> [!warning] ADR 生命周期：「Accepted」≠「已实现」（Matt skills #299）
> `grill-with-docs` 在 grill 阶段（远早于实现）就把 ADR 写进 `docs/adr/`，而下游 skill 默认 `docs/adr/` 是**现行**架构。于是「已定、未建」的决策和「代码已反映」的决策长得一样，可能让接邻近活的 agent 围着不存在的代码写——Matt 自己仓库 issue #299（radmen 提、Matt 认、未合）正是这个。**本项目对策**：ADR 带 Status 行，但本项目 `Accepted` 语义 = 「设计经评审收敛、可去实现」**不等于**「代码已建」——所以读 ADR 必须交叉看对应 issue 的 open/close 才知道建没建（#63 = ADR 0015 已 Accepted 但实现 OPEN，就是这种「已定未建」态）。

## 真 user story（2026-06-18 立，实证栽过）

**真 user story（2026-06-18 立，实证栽过）**：user story 必须**从真实用户的需求**写——「谁真在用这东西、要达成什么价值」，不是把 Implementation Decision 套成「作为 X，我希望〔那条决定〕」凑数。**actor = 被造之物的真实用户**：游戏 → 皇帝/玩家（+ 试玩者/我：抓 bug、要错误包、读拒收数据找规律）；**开发者只在「开发者本就是产品真实用户」时才当 actor**（dev 工具/SDK——实证 Matt 的 `sandcastle` PRD 全「As a developer」、`course-video-manager` PRD 全「As a course creator」，actor 跟产品真实用户走）。**判据**：剥掉「作为 X 我希望…以便…」的壳，剩的是「用户可感知的价值」还是「内部怎么实现」？后者＝假 story，挪 Implementation Decisions。别为凑「extensive」机械批量造、被质疑再事后补说辞——extensive 是把真实用户各面写全，非换壳堆量。
