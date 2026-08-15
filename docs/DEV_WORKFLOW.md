---
title: Matt Pocock 开发流程
description: Matt Pocock skills 整套（想法 → merge）canonical：grill-with-docs → (prototype) → to-spec → to-tickets → 逐片 implement（内联 tdd + code-review），外加 7 标签状态机 + triage 入口匝道 + agent brief 契约 + 「状态活 label、不活散文」。本项目 2026-06-17 起 Matt 纯化、严格按 Matt 试水；2026-06-18 修正三处真错（grill 在 to-spec 前 / to-spec 是完整 PRD 含两层设计 / triage 是匝道不是主线）并补「设计六层阶梯」；2026-07-02 同步 code-review / implement 新口径；2026-07-03 注：本项目〔项目加〕设计评审闸（本地 cmr + 线上 bot → ADR Accepted）位于 to-tickets 之后、逐片 implement 之前（CLAUDE.md §开发流程 步骤 5；#470/#471/#478 实践序）；2026-07-14 上游改名 to-prd→to-spec、to-issues→to-tickets（后者内建原生挂接），全文已随改，历史 ADR/log 旧名不回改。
type: concept
created: 2026-06-17
updated: 2026-08-13
sources:
  - mattpocock/skills 各 SKILL.md 原文（ask-matt 路由器 / grill-with-docs / grill-me / domain-modeling / prototype / to-spec / to-tickets / triage / implement / tdd / code-review / diagnosing-bugs / improve-codebase-architecture）
  - Ming_LLM 2026-06-17 验证 session（#174 走通全链、标签纯化、triage 36 backlog）
  - Ming_LLM 2026-06-18 校订 session（对照 skill 原文修正流程顺序 + to-spec 两层设计 + 设计阶梯）
related:
  - "[[matt-pocock-skills]]"
  - "[[tdd-autonomous-dev]]"
  - "[[pr-review-loop]]"
  - "[[cross-model-review]]"
tags: [workflow, triage, matt-pocock, agent-brief, issue-tracking, slicing]
---

## 操作规程

权威源 = Matt 的 `ask-matt` 路由器 + 各 skill SKILL.md 原文。整条主线：**想法 → grill 出 CONTEXT/ADR →（大/模糊想法先 decision-mapping 推雾）→ to-spec 综合成完整 PRD → 切薄 issue → 逐片 implement → ship。** 每步一个 skill，状态全靠 label + open/close 跟踪。

自动化交付的角色与运行时由仓外 v3 [`ak-pi-workflow-roles`](https://github.com/Akagilnc/ak-pi-workflow-roles) 维护；本页只定义 Ming 项目的开发方法和质量闸，不保存自动化接力、模型路线或运行时配置。

> [!important] grill **在 to-spec 之前**
> `to-spec` 故意**不访谈**（SKILL.md 原文："Do NOT interview the user — just synthesize what you already know"）。访谈/逼问那一步是 `grill-with-docs`，它在前；`to-spec` 只是把 grill 透的对话**笔录**成 PRD。所以顺序不可能反——to-spec 前面没 grill 就没东西可综合。

> [!important] triage 不在主线上，是**入口匝道**
> `triage` 只处理**你没创建的**外来 issue（bug 报告 / 进来的需求）。`to-tickets` 产出的子 issue 规格即 agent-ready，**不要再 triage**（原文："Issues that to-tickets produced are already agent-ready, so don't triage them"）。（本项目注：不 triage 不变；标签贴着无所谓——评审态真源 = ADR Status，owner 2026-07-14 简化、旧闸前 hold 废止。）

> [!important] `to-spec` / `to-tickets` 只在「多 session 大活」才走
> `ask-matt` 第 3 步是个分叉：**多 session 才做的大 feature** 才 `to-spec` → `to-tickets`；**单 session 能完的小活直接在同一窗口 implement、跳过这两步**。别把 to-spec/to-tickets 当所有活的必经。

> [!important] 大/模糊想法先 `decision-mapping` 推雾，再进 to-spec
> grill 完若还剩「一次 session 定不完」的开放决策（fog of war），先跑 `decision-mapping`：建 git-tracked 决策图，每个 ticket（Research / Prototype / Discuss，一票一 ~100K session）逐个 resolve、推开迷雾，直到通往终点的路清晰，才进 to-spec。grill 完就没迷雾（多数情况）= 直接往下、不必建图。这是 Matt 原生的多-session **规划** 层（区别于 to-spec/to-tickets 的多-session **实现** 层）。

```
想法
 └ grilling（核心逼问引擎）── 壳：grill-with-docs[有codebase,落CONTEXT/ADR] / grill-me[无codebase,不落]
 └ ❲迷雾?❳ grill 完还剩「一次 session 定不完」的开放决策?
      有 ─→ decision-mapping ── git-tracked 决策图（ticket=Research/Prototype/Discuss，一票一 ~100K session）
      │                          逐票 resolve（调 grilling/prototype/research）推开迷雾，直到路清
      无 ↓（grill 完就没迷雾，多数情况）
 └ ❲规模?❳
      小（单 session）─→ 直接 implement，跳过 to-spec / to-tickets
      大（多 session）↓
 └ to-spec ────────── 综合成「完整 PRD」（不访谈，只笔录），发 issue tracker 当父/epic
        Problem / Solution / 详尽 User Stories / Implementation Decisions / Testing Decisions / Out of Scope / Further Notes
 └ to-tickets ─────── PRD 切薄垂直切片子 issue（Parent + What to build + 验收 + Blocked by + AFK/HITL）
        ↑ grill →(decision-mapping)→ to-spec → to-tickets 留同一不间断窗口，别中途 compact（smart zone ~120k）
 └ 〔项目加〕设计评审闸 ── 本地 cmr + 线上 bot（审含切片布线的设计全家）→ merge → ADR Accepted（评审态真源=ADR Status；标签不管）
 └ (每个 issue 开新 session) implement ── 按 PRD/issue 实现：约定 seam 调 /tdd（never refactor while RED）→ 测试义务见下方「测试分级」
          → 手动/单 session：baseline commit → /code-review → fix commits
          → 自动化交付：由仓外 v3 独立角色接力，本仓不复制其内部流程
        ▼
     家族/批次收尾：测试义务见下方「测试分级」→ merge commit（不 squash）→ 关子 issue；全完 → 人手动关父
        （prototype 按需绕道，handoff 出/回桥接）
```

**什么地方用什么（全 skill 速查）**：

| skill | 阶段 | 干什么 |
|---|---|---|
| `grilling` | A 规划·引擎 | 核心逼问引擎：一次一问、走决策树、每问给推荐答案；下面几个壳调它 |
| `grill-with-docs` | A 规划·起点（有 codebase）| grilling + `/domain-modeling`：逼问 + 当场写 `CONTEXT.md` + `docs/adr/` |
| `grill-me` | A 规划·起点（无 codebase）| 只 grilling：同一场逼问，stateless、不落文档 |
| `domain-modeling` | A 规划 | 建/磨领域词表 + ADR（被 grill-with-docs 挂用；也可单独修词表/ADR）|
| `decision-mapping` | A 规划·大/模糊 | 一次 session 定不完时：git-tracked 决策图，ticket=Research/Prototype/Discuss 逐票推雾 |
| `prototype` | A 规划·去风险 | 扔型原型**二选一**答「逻辑/状态对不对」(终端 app) 或「长啥样」(UI 多变体)；= decision-mapping 的 Prototype ticket，handoff 桥接、答案落 durable、原型删 |
| `codebase-design` | A 规划·架构词汇 | 深模块设计共享词汇（Module/Interface/Depth/Seam…，被 tdd/improve 挂用）|
| `to-spec` | B 立项 | grill 透后**综合成完整 PRD**（不访谈），含两层设计，发 issue tracker 当父 |
| `to-tickets` | B 立项 | PRD 切薄垂直切片子 issue（tracer bullet）+ 依赖序 |
| `implement` | C 实现（逐片，各开新 session）| umbrella：按 PRD/issue 实现，约定 seam 调 `/tdd` → 测试义务见「测试分级」；手动流随后 baseline commit → 单评 → fix commits |
| `tdd` | C 实现（被 implement 调）| 红绿重构；**代码级实现在这现场长**；never refactor while RED |
| `code-review` | C 实现·收尾 | Matt 单评：固定点 diff 的 Standards + Spec 两轴 review；取代旧内置 `/review` 作为 canonical 收尾评审。它评 `fixed-point...HEAD`，所以手动/单 session implement 要在 baseline commit 后跑 |
| `diagnosing-bugs` | C 旁路（硬 bug）| 硬 bug / 性能 regression 调查（旧名 `diagnose`）|
| `improve-codebase-architecture` | 保养 | 据 CONTEXT + ADR 找深挖/重构，产出回 A 当新想法 |
| `triage` | 入口匝道（非主线）| **外来** issue（你没创建的）走五态状态机、贴标签、发 agent brief |
| `handoff` | 横切 | session 间交付（context 满 / 绕道 prototype 的桥）|

### 测试分级（#1185，owner 2026-08-13 裁定）

**本仓测试分级政策真源**（CLAUDE.md Skill routing / 开发流程步骤 6 引用此处，不另立第二份口径）：

- **切片轮次**（逐片 implement / fixer 自检；评审核 coder 回执里的聚焦测试证据，不以复跑全量 suite 为复核手段）＝ `typecheck` + **聚焦测试**（本片触及的测试）。
- **家族/批次收尾**＝在**最终待合并状态**执行一次全量 suite；若执行失败或随后产生修复 commit，必须在新的最终状态重跑。**最终状态绿灯**后，才可作为 **merge 前门槛**。无家族/批次上下文的单切片或单 session 改动，**其自身即一个批次**——merge 前同样在最终状态跑一次全量到绿。
- **CI**（`.github/workflows/ci.yml`）覆盖 **Python 全量 pytest + Web 构建/类型检查**（`tsc` + vite build），**不含 Web vitest**；本政策如实描述既有覆盖面，不改 CI 机制、不把 vitest 加进 CI。

正向口径：切片只跑聚焦；全量在最终待合并状态跑到绿（失败/修复后重跑）。同构于仓外 `ak-pi-workflow-roles` 司天家族测试策略（该仓 #215 provenance）；worker prompt / reviewer 验收面属外部编排器仓，由其维护，本仓不改。

### ship-pre DoD 全闭环点检（#911 自项目 CLAUDE.md 迁入）

进 ship-pre / CMR 评审循环前必须确认 feature 全闭环完成，不是「核心写路径接通」就进。Definition of Done = 所有闭环面都齐——**写入端 + 读取端 + 恢复端 + 真实 extractor 输出 + UI/呈现端 + 文档契约**，缺一面都不算 ship-ready。

把「核心写路径接通 + 单元测试绿 + 前几轮 CMR 收敛」误当成「全闭环完成」两头亏：(1) 在不完整目标上启动昂贵的 ship-pre 评审循环，(2) CMR 一轮轮真抓闭环缺口、滚到离谱轮数才被外人判出「功能不足」。

**判据**：进 ship-pre 前对着 plan 逐面点检 DoD，任一面（尤其读取/恢复/呈现这些最容易被「写路径接了」盖过的隐性面）未落 = 早了，先补完再进。这是 **ship-gate / DoD 判断**，不是编码能力——写路径接了、测试绿都可能为真，错在把「核心接通」当「全闭环完成」。

且即便 DoD 齐、进了 ship-pre，装起来跑的整体 cmr 仍是独立一道闸——别当走过场：per-slice cmr 各自全绿 ≠ feature 完成，整体闸基本仍会抓出 per-slice 照不到的**跨片接缝**（字段名/类型对不对、字段口径一不一致、组合后才出现的 e2e 行为），要预期它有料、按真闸认真跑。

> [!note] 本项目在 Matt 之上加的闸（非 Matt canonical）
> 本项目在 ③ 之后插一道**设计评审**（`ak-cross-m-review` 本地 cmr + 线上 bot，收敛 ADR）。手动流在 ⑥ baseline commit 后进入**代码评审**（Matt `/code-review` 单评 + per-slice cmr + ship-pre + 线上 bot）。`/code-review` 是 Matt 原装，per-slice cmr / ship-pre / 线上 bot 是本项目质量装置；自动化 coder/reviewer 分工由仓外 v3 维护。详见 [[cross-model-review]] / [[pr-review-loop]]。

### to-spec —— 完整 PRD（含两层设计，别漏）

`to-spec` 不是开个薄 issue。它按固定模板把 grill 透的对话**综合成一份完整 PRD**（SKILL.md 原文模板）：

- **Problem Statement** —— 用户视角的问题。
- **Solution** —— 用户视角的解法。
- **User Stories** —— 一长串编号 user story，要求 **"extremely extensive"**、覆盖 feature 各面。
- **Implementation Decisions（设计第一层）** —— 要建/改哪些模块、改哪些接口、技术澄清、架构决策、schema 变更、API 契约、具体交互。**明文禁止写文件路径 / 代码片段**（"They may end up being outdated very quickly"）。例外：prototype 产出的、比散文更精确编码了某决策的 snippet（状态机 / reducer / schema / type shape）可内联，并注明来自原型、只留决策相关部分。
- **Testing Decisions（设计第二层）** —— 什么算好测试（只测外部行为、不测实现）、测哪些模块、代码里的同类 test prior art。
- **Out of Scope** —— 明确不做的。
- **Further Notes** —— 其它。

产出发到 issue tracker（父/epic），贴 `ready-for-agent`，无需再单独 triage（标签贴着无所谓、不用管——评审态真源 = ADR Status；owner 2026-07-14 简化）。

### 设计落在哪（六层阶梯，解「详细设计在哪长」）

「详细设计」是个糊词。Matt 流程里设计**分布在六个台阶**，落在不同 artifact、不同时点定——别压扁成一处：

| 台阶 | 设计的哪一面 | 落在哪 | 何时定 |
|---|---|---|---|
| 1 语言 | 术语是什么意思 | `CONTEXT.md`（零实现，只 glossary）| grill |
| 2 不可逆决策 | 少数反悔贵的选择 + 为什么 | `docs/adr`（1-3 句单决策，稀有）| grill |
| 3 **架构/决策级设计** | 哪些模块/接口/契约/schema（**不写代码**）| to-spec 的 **Implementation Decisions** | to-spec |
| 3′ 测试策略 | 测什么、啥是好测试、prior art | to-spec 的 **Testing Decisions** | to-spec |
| 4 行为切片 | 端到端竖切，行为级（不写代码）| to-tickets 的 issue body | to-tickets |
| 5 接口+行为计划 | 公共接口长啥样、先测哪些行为（跟你确认）| tdd Planning | tdd 开头 |
| 6 **代码级实现设计** | 真函数 / 文件结构 / 内部实现 | **代码本身** | **tdd 红绿重构现场长** |

要点：**第 6 层（代码怎么写）是故意不提前写、留给 TDD 现场长的**——所以 to-spec 和 to-tickets 都明文禁文件路径/代码。但第 3 层（哪些模块/接口/契约）**是在 to-spec 就钉的**，不留到 TDD 现编。「详细设计在 TDD 长」只对第 6 层成立；漏掉第 3 层就会以为 to-spec 之后到代码之间什么设计都没有——那是错的。

### 标签制（Matt 纯化，全仓只剩 7 个）

**2 category**：`bug`（坏了）/ `enhancement`（新功能或改进）。
**5 state**：`needs-triage`（待评估）/ `needs-info`（等 reporter）/ `ready-for-agent`（规格全、AFK 可独立做）/ `ready-for-human`（需人：判断/设计/外部访问/手测）/ `wontfix`（不做，含已完成可关）。

> [!important] 每个工作项恰好一个 category + 一个 state
> epic/tracker（追踪别的 issue 的总台）**不进工作态、留空**。本项目 2026-06-17 删掉了原有 `priority/*` `area/*` `type/*` 一整套，只留这 7 个——见 §为什么「半套用半套空」。

### triage —— 入口匝道的状态机那只手

> [!important] triage 只对**外来** issue；`to-tickets` 的产出不 triage
> 每条 triage 发的评论/issue 都必须开头标 `> *This was generated by AI during triage.*`

**流转**：没标的 → `needs-triage` → 四态之一；`needs-info` 等 reporter 回了再回 `needs-triage`。maintainer 随时可手动覆盖。

**dashboard 模式**（看「该我管的有啥」）：按最老优先列三桶——没标的 / `needs-triage` / `needs-info` 且 reporter 有新动静的。给计数 + 一行摘要，maintainer 挑。

**triage 一条（5 步）**：
1. **Gather** —— 读全 + 读旧 triage 笔记（别重问）+ 探代码（用 glossary、尊重 ADR）+ 读 `.out-of-scope/` 看撞没撞旧驳回。
2. **Recommend** —— 给 category + state + 理由 + 一句代码现状，**等 maintainer 定**。
3. **Reproduce（只 bug）** —— grill 前先试复现：成功（带代码路径）/ 失败 / 信息不足（= 强 `needs-info` 信号）。
4. **Grill（若需细化）** → 跑 `/grilling` + `/domain-modeling`（即 grill-with-docs）。
5. **Apply**：`ready-for-agent`→ 发 agent brief；`ready-for-human`→ 同结构 + 注明为何不能甩 agent；`needs-info`→ 发 triage notes（已确立的 + 还需 @reporter 答的具体问题）；`wontfix(bug)`→ 客气解释 + 关；`wontfix(enhancement)`→ 写 `.out-of-scope/` + 链过去 + 关。

### agent brief —— ready-for-agent 的契约

> [!important] brief（存在时）是最权威契约；**可选**——无 brief 则以整个 issue（body + 讨论）为准
> issue 移到 `ready-for-agent` 时若发一条结构化 `## Agent Brief` 评论，那是 AFK agent 工作的最权威规格。但 brief **不是强制**（用户 2026-06-22 拍：`to-tickets` 切片未必带它、工具不能这么死板）。coder **读整个 issue**（body + 全部 comments）实现，brief 在则为其中最权威、durable 的那部分。

**四原则**：① **durability over precision**——不写文件路径/行号（会过时），写接口/类型/行为契约、点名 symbol；② **behavioral not procedural**——写做什么不写怎么改；③ 完整可测验收；④ 显式 out-of-scope 防镀金。

**模板**：`## Agent Brief` → Category / Summary / Current behavior / Desired behavior / Key interfaces（点名 type/函数签名）/ Acceptance criteria（`- [ ]` 可测）/ Out of scope。

### out-of-scope 知识库

驳回的 enhancement 写 `.out-of-scope/`：**一个 concept 一个文件**，松散小设计文档体，写为什么驳 + `Prior requests` 列表。用途 = institutional memory（理由不丢）+ 去重（新 issue 撞旧驳回翻出旧决定不重吵）。

### 切片 & 并行

- **垂直切片（tracer bullet）**：每片穿透所有层、独立可 demo/merge。**禁横切**（先全 schema 再全 UI = 谁也独立不了）。
- **`Blocked by` 真源 = native blocked_by**（2026-07-14 起 to-tickets 已内建挂接；GitHub 原生强制可 filter）；子 body 里的 prose `## Blocked by` 降级为可读面包屑/核验信息，不再是唯一契约（核验命令见下节）。
- **AFK / HITL**：AFK 可甩多 session 真并行；HITL（要人在环）串行在你的注意力上。
- **context hygiene**：grill → to-spec → to-tickets 留在同一上下文窗口；每个子 issue **开新 session** 走 implement（内联 `/tdd`；手动流可接 `/code-review`；自动化角色上下文由仓外 v3 隔离），别拿上一个 issue 的脏 context 接下一个。

### to-tickets 后的原生核验（2026-07-14 上游改版后：①②已内建，③仍手动）

**2026-07-14 上游改版**（to-issues → to-tickets）已把原生挂接写进 skill：按依赖序发子票，「Use the platform's native blocking / sub-issue relationship where it has one」——即下面第 1、2 步**正常情况它自己干**（旧版只写 prose `## Parent` / `## Blocked by` 的缺口已补，Matt backlog #47/#262 落地）。标签一律不管（owner 2026-07-14 简化：新版默认贴 `ready-for-agent`，贴着无所谓——评审态真源 = ADR Status，本项目无扫标开工机制；旧「撤父标 / 闸前 hold」仪式废止）。下列命令降级为**核验/手补**用（skill 输出异常时照跑，本项目实测可用）：

1. **子挂父 native sub-issue**（父页自动出子列表 + 进度条 → 解决「找子 / 导航」）：
   ```bash
   cid=$(gh api repos/O/R/issues/<子号> -q .id)        # 取 numeric .id，不是 issue 号
   gh api -X POST repos/O/R/issues/<父号>/sub_issues -F sub_issue_id=$cid
   ```
2. **子↔子 native blocked_by**（GitHub 原生依赖，可 filter 未阻塞 → 解决「先抓哪」）：
   ```bash
   bid=$(gh api repos/O/R/issues/<blocker号> -q .id)
   gh api -X POST repos/O/R/issues/<blocked号>/dependencies/blocked_by -F issue_id=$bid
   ```
3. ~~保护父：撤父工作态 label~~（**已废止 2026-07-14**：标签不管，评审态真源 = ADR Status，父标贴着无害）
4. **(可选) wave milestone**：无前置 = `wave-1`、前置都在更早波 = `waveN`（告诉 agent 先抓哪；Matt #238）。**大图才需要**——native blocked_by 已把依赖上了 tracker，小图（unblocked 没几个）可省。

### 追踪模型

> [!important] 状态活在 label + open/close，不活在散文 body
> 看「啥能抓」查 `ready-for-agent` 桶；看「还剩啥」filter open 子 issue。

> [!warning] 几个 GitHub 事实
> ① **父→子归属** = **native sub-issue**（见上「to-tickets 后的原生核验」）+ 子 body `## Parent #N` 面包屑；父页自动出子列表 + 进度条。② **依赖 = native blocked_by**（GitHub 原生、可 filter 未阻塞），不再只是 prose 约定。③ **父「完成」= 人手动关**（子全关后整体验收再关），GitHub 不自动关父；**关父即解锁 blocked_by 父的下游**。④ ⚠️ 2026-07-14 起 Matt skill（to-tickets）已内建 native sub-issue + blocked_by 挂接；「to-tickets 后核验」章节的命令降级为核验/手补用，撤父标签仍手动。⑤ ⚠️ **`Closes/Fixes/Resolves #N` 在 PR body 与默认分支 commit message 都是子串匹配**——动词后的限定词（含中文）挡不住，合并 `main` 即**自动关整条 issue**。所以「merge → 关子 issue」这步：**想引用而不关**（如设计 PR 解决了某 issue 的*设计*但*实现*未做、或引用一个 tracker 父）**绝不带关闭动词**，写「见 #N」「关联 #N」「#N 的设计」；只在该 PR 真要关整条 issue 时才 `Closes #N`；误关 → `gh issue reopen` + 复原 label + 说明。**实证**：#208 body「`Closes #63` 的设计悬置」误关了 #63（设计已定、实现未做、应留 OPEN + `ready-for-agent`）。详版见 [agents/issue-tracker.md](agents/issue-tracker.md)。

> [!warning] ADR 生命周期：「Accepted」≠「已实现」（Matt skills #299）
> `grill-with-docs` 在 grill 阶段（远早于实现）就把 ADR 写进 `docs/adr/`，而下游 skill 默认 `docs/adr/` 是**现行**架构。于是「已定、未建」的决策和「代码已反映」的决策长得一样，可能让接邻近活的 agent 围着不存在的代码写——Matt 自己仓库 issue #299（radmen 提、Matt 认、未合）正是这个。**本项目对策**：ADR 带 Status 行，但本项目 `Accepted` 语义 = 「设计经评审收敛、可去实现」**不等于**「代码已建」——所以读 ADR 必须交叉看对应 issue 的 open/close 才知道建没建（#63 = ADR 0015 已 Accepted 但实现 OPEN，就是这种「已定未建」态）。

---

## 为什么这么做

- **为什么状态活 label 不挂散文进度**：散文 checkbox（带 #N 链接但非 tracked task）GitHub 不自动滚、必过时，得人手维护 = treadmill。**实证**：本项目 release 清单 #96 全是散文状态（「设计待定/开发待接」），必然过时、靠人重写同步。改用 label + open/close（或纯 `- [ ] #N` tracked）后，关 issue 即更新、永不 stale。**body 放稳定 spec，状态交给 label/开关。**

- **为什么 brief（存在时）最权威——但可选、不替代整个 issue**：issue 在 `ready-for-agent` 可能躺几天几周，代码同时在变；body 引文件路径/行号会过时。brief 写成 durable（behavioral、点 symbol 不点路径）= agent fresh 探码也接得住的合同，所以**有 brief 时它是最权威的那部分**。但 brief **不强制**——`to-tickets` 切片未必带它；没 brief 时 agent 读**整个 issue**（body + 全部讨论）实现，工具不因缺它而死板拒收。

- **为什么薄、独立、垂直切片**：这是**并行的前提**。横切（先全层）互相依赖、并行不起来；薄独立垂直 + issue 化 → 多 session 各抓不同 issue 真并行。**实证**：本项目脊柱写着「默认全部并行」却从没并行过——根因不是机制坏，是**从没切出多个独立切片**（粗块单功能 + 自跑例外吃掉大半 + 没 issue 化跨 session 无抓手）。**切得碎不碎是设计侧的活，是「能不能并行」的总开关。**

- **为什么 grill 在 to-spec 前、to-spec 不访谈**：sharpen 在 grill（逼问 + 落 CONTEXT/ADR），to-spec 只是把已 sharpen 的对话笔录成 PRD。把访谈塞进 to-spec 会让它既访谈又成文 = 两件事混一步、还和「grill 落文档」重叠。拆开 → grill 一次访谈到位、to-spec 一次综合到位。

- **为什么设计分六层、第 6 层留给 TDD**：可逆的代码级实现（真函数/文件结构）做了才知道哪样好，提前写 = 浪费且过时——所以 to-spec/to-tickets 禁文件路径/代码、留 TDD 现场长。但架构级（模块/接口/契约，第 3 层）反悔贵、得在 to-spec 钉死；不可逆的（架构形态/契约/分类，第 2 层）进 ADR。**实证**：#174 曾在 issue 里铺逐事件代码级详设，ADR 一改即过时、成考古负担——那是把第 6 层提前写了。**ADR 颗粒度**配套：1-3 句单决策（Matt ADR-FORMAT），大 section 模板会把可逆细节吸进来 = 过度设计。

- **为什么评审强度跟反悔成本走**：spec 错比 impl 错贵（改 ADR/PRD 时上面还没盖代码）。所以设计（ADR/PRD）审狠、代码审正确性。

- **为什么 Matt 纯化（删项目原标签）**：半套用半套空——本项目原先只用了 `ready-for-*` 后半、没用 `needs-triage`/`needs-info` 入口态，triage dashboard 因此空转。要验证整套是否成立，先把杂标签清掉、全仓只跑 Matt 7 个，信号才干净。

- **为什么 handoff ≠ 交接**：同一个你驱动，fresh agent 靠**文档 + 你在场** re-seed，不是扔过墙给陌生团队。所以 session 边界画在「上下文满/脏」处、不钉死在某步；小功能一个 session 连做。

---

## 来源 / 验证

- **skills**：`mattpocock/skills`（"Skills for Real Engineers"）—— canonical 出处 + 各 skill 机制细节见 [[matt-pocock-skills]]。本页流程顺序以各 SKILL.md + `ask-matt` 路由器原文为准。
- **本项目验证（2026-06-17）**：
  - #174「历史事件触发」走通全链：`grill → ADR 0014 → to-tickets 切 9 片(#187–#195) → triage 贴态`。
  - 标签 Matt 纯化：35 → 7（删 `priority/area/type` 等 28 个）。
  - triage 36 个 backlog：fan-out 分类 → 7 ready-for-agent / 20 ready-for-human / 2 关闭 / 7 tracker 留空。
- **本页校订（2026-06-18）**：对照 skill 原文修正三处真错——① `to-spec` 实为「grill 之后」（不访谈，只综合）；② `to-spec` 产**完整 PRD**含 Implementation/Testing Decisions 两层设计（先前误写成薄 issue）；③ `triage` 是**入口匝道**、不对 `to-tickets` 产出用——并补「设计六层阶梯」消歧。
- **本页校订（2026-07-02）**：同步 Matt 新增 `code-review` 与 `implement`；手动流在 baseline commit 后用 `/code-review` 做 Standards + Spec 两轴单评，本项目 per-slice cmr 仍是额外跨模型闸，二者叠加非替代。
- **关联**：ship 后的 PR 评审循环见 [[pr-review-loop]]；自治 TDD 实现 loop 见 [[tdd-autonomous-dev]]；设计阶段 cross-model 评审见 [[cross-model-review]]。

> [!note] 状态：严格按 Matt 试水中（完全实验，非照抄）
> 本页把 Matt 整套当 canonical 写全，本项目**严格照它跑一遍**验证成不成立。**操作姿态（2026-06-18 定）**：先走走看，碰到不合理的地方就**改 / 提 issue**、慢慢理解，**不是无脑照抄**。
> **已拍决定**：**跑 Matt 的重型 `to-spec`**（含 Implementation/Testing Decisions 两层设计），不退薄 issue（2026-06-18，完全实验——既是 strict Matt 就不再逐点问「要不要照 Matt」）。
> **仍记的偏离 / 待撞的粗糙边**（数据点）：(a) 〔2026-07-03 已结算〕设计评审闸=**一道**、位于 to-tickets 之后（cmr 审含切片布线的设计全家=PRD+ADR+词表+切片，#470/#471/#478 实践序）——早期「to-spec 后、to-tickets 后各插一道」的两闸设想与「对象从 ADR 扩到 PRD+ADR」的诉求均已被此形态吸收；(b) 实践中撞到的粗糙边（如 to-tickets 前父 issue 短暂挂 `ready-for-agent`）按「走走看」原则**遇到再改 / 提 issue**，不提前拍。
> 成立后这套机制的 canonical 应回流 wiki（wiki session 的活）；本项目侧只留「采纳决定 + 指针」在 `CLAUDE.md`。
