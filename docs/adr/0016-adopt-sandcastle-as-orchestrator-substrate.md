# 采用 Sandcastle 作为 epic 编排器底座；编排器收缩为叠加在其上的「质量层」

Status: Accepted（2026-06-19 提出 / 2026-06-20 Accepted；spike 实证「底座可行 + 并行编排可行 + 缺质量层」三面。**评审闭环完成**：本地 cmr 6 轮收敛（r1=14→r6=0）+ 线上 bot（PR #246：真 finding 仅 1 处 markdown 已修；G2 安全阀 / G4 reviewer 守护按用户 defer 决定记录在案）。parallel-planner 并行编排证据已补（见 Spike 证据 4）。在此之前 #217 PRD 的「整套自建」描述不作数、以本 ADR 方向为准。）

Current authority: 本 ADR 只保留“Sandcastle 是执行底座、编排器只叠项目质量层”的方向决定。现行交付拓扑只读 #869，Runner 边界只读 ADR 0131，Action / 角色所有权只读 #868；下文 #244、S0–S8 与 v1 模型/镜像细节仅为历史。

## 背景

#217 把「喂父 epic → AFK 跑到待 PR」的编排器**整套自建**（PRD + wiki [[epic-orchestration]] + 切片 #218–225 + prototype），收敛后才发现 `mattpocock/sandcastle`（6.1k⭐，MIT，TS）很可能就是被重新发明的东西（见 memory `prior-art-search-before-building-tool`）。本 ADR 记录「自建 vs 引入」分叉的 spike 实证与方向决定。

衡量标尺 = #217 北极星：谁更快把人（用户 + 主 session）从盯开发里解放出来。

## 决定（方向）

**不二选一。Sandcastle 当底座，#217 收缩为叠在它 `run()` 上的薄「质量层」。**

- **底座（直接用 Sandcastle）**：容器/podman/vercel 沙箱隔离、codex/claude 订阅 auth、worktree、分支策略（merge-to-head）、Ralph 循环（`simple-loop`）、并行（`parallel-planner`）、issue 输入（`github-issues` tracker）。这些是 #217 想自建、而 Sandcastle 已有且经 6.1k⭐ 验证的硬基建。
- **质量层（#217 的真增值，Sandcastle 没有，须自叠）**：独立专业评审、findings 在专业 worker 间流转、家族集成验证与 shared-tail 质量闸；准确接力只读 #869，不在本 ADR 保存第二份拓扑。

## Spike 证据（2026-06-19，本机 colima Docker + codex ChatGPT 订阅，端到端真跑）

1. **核心原语跑通**：`@ai-hero/sandcastle@0.10.0` install → init → build 镜像（补 `ca-certificates`）→ `run({agent:codex, sandbox:docker})` 在容器里**用订阅 auth（零 OPENAI_KEY，仅 bind-mount `~/.codex` 副本）**改文件 + 提交 + merge-to-head 合回。订阅接法 = `docker({ mounts:[{hostPath, sandboxPath:'/home/agent/.codex'}] })`，比上一场手动那套干净。
2. **真 issue 实测（#137，meaty 切片，非一行 fix）**：在 Ming_LLM 隔离 worktree 上跑（护栏：不跑测试/不 close/不 push）。codex 自己读了 `cli_backend.py / session.py / db.py / web_app.py` + 三个测试、**定位真实调用点**、新增 `extract_draft_action` **完全对齐既有抽取器写法**、接进 pending 流复用 `add_directive(status="pending")`，44 行、改在对的地方、符合项目惯例。**外人模型、零项目上下文喂入 → 产出像样且地道的改动**，底座质量出乎意料地强。
3. **同一份 diff 同时坐实「无评审闸 = 真缺陷直接 ship」**：Ralph 改完即 commit+close，而该 diff 至少 5 个真问题、Sandcastle 默认循环一个不拦：① **漏 issue 硬要求**（没实现「pending 原地更新 last-write-wins」，issue 白纸黑字「唯一新增要求」）② 草案文本 = 大臣整段回话（含闲聊前缀，未剥）③ 无测试（违项目 TDD 铁律）④ 每条无前缀对话多一次 LLM 抽取、延迟叠加无人审 ⑤ 称对齐 ADR 0006 但没真打开该 ADR。**这 5 个缺陷全落在「质量层」该拦的范围内**——即本决定要自叠的那层。
4. **parallel-planner 端到端跑通（并行编排）**：`plan → 并行 implement → merge` 三阶段、编排本体是**固定可复现的 TS 代码**（main.mts），仅每轮「选哪些 issue」是 LLM 读 issue 图产结构化 JSON（zod 校验）。真跑：plan 出 2 个独立任务 → **两个 implementer 容器真并发**（各在 `sandcastle/issue-{id}` 隔离分支、各 1 commit）→ merge agent 把两分支并回 master（git graph 真菱形、`alpha.js`+`beta.js` 落地）。**依赖感知**经「每轮只取当前未阻塞、阻塞者下轮 merge 后再取」实现 = #217 的「依赖按层 barrier」。**确定性分支名**（`sandcastle/issue-{id}`）= 重规划保留已积累进度（#217 的 git-skip 续跑）。

## Considered Options

- **整套自建（#217 原 PRD）**：重新发明容器/订阅/worktree/分支合并/Ralph 循环这些 Sandcastle 已验证的硬基建。否决——重复造轮子，违 prior-art 教训。
- **直接照搬 Sandcastle（不叠）**：开箱即用，但 spike 证据 #3 显示其默认循环**零 cross-model 评审 / 无 findings 升级 / 无家族整体闸**，会把漏需求+无测试的改动 commit+close。否决——丢掉 #217 唯一真正想要的承重质量闸（用户看不了 diff，merge 前的多模型评审是唯一可信关卡）。
- **Sandcastle 底座 + 薄质量层（本决定）**：硬基建复用、质量层自叠。最省、且保住 #217 真增值。

## Consequences

- **#218–225 切片须重定向**：S0「JS 测试基建」「决策核」、S2「单切片流水线」、S3「并行 + 串行 merge 队列」等不再「从零搭机器」，而是「在 Sandcastle `run()` 之上接质量层」。具体重切待本 ADR Accepted 后做（含可能改 #217 PRD / wiki [[epic-orchestration]] 的执行拓扑章节）。
- **spike 发现 1（RALPH prompt 假设 JS 项目）**：scaffold 的 `simple-loop` prompt 硬写 `npm run typecheck && npm run test`；Ming_LLM 是 Python（pytest）为主、`web/package.json` 还缺 test/typecheck 脚本。叠层时 verify 命令须按本项目重写（prompt 级，易）。
- **spike 发现 2（镜像须带项目工具链才能 verify）**：spike 镜像是 `node:22-bookworm`，无 python → 容器内跑不了 pytest（本次靠护栏跳过 verify）。真用于 Ming_LLM 须预设镜像带 python + 项目 deps（呼应 #217 PRD 的「预设 image 摊薄启动」）。
- **依赖**：colima Docker 在跑（~8GB RAM）；订阅 auth 经 bind-mount 进容器，凭据副本用完即删（铁律）。CI-native AFK + 订阅大概率卡（runner 无登录无 key），编排仅本机可行。
- **spike 发现 3（parallel-planner 的两处与 #217 真差异，均 prompt 级可调，非架构缺口）**：① **依赖是 LLM 推断**（planner 读 issue 文本 + 文件重叠猜 blocked-by），#217 要读 **GitHub native blocked_by**（确定性）——改 plan-prompt 用 `gh` 读原生依赖即可；② **merge 是 LLM agent 解冲突 + 跑 npm test**（merge-prompt），#217 要**确定性串行 merge 队列**（切片返 reviewed hash、编排器逐个合）——可换成脚本侧 git 合、把 LLM merge 退化为兜底。③ merge 阶段 close issue（同 simple-loop 的 close 语义冲突）。
- **质量层确认仍是净增量**：parallel-planner 的 plan/execute/merge **三阶段全程零 cross-model 评审 / 无 findings 分流 / 无独立家族整体闸**（merge agent 只跑自己的 npm test）。两个模板都证实：评审承重闸 = Sandcastle 没有、#217 要自叠的那层。
- **spike 发现 4（skill 注入缺口，叠质量/纪律层时必处理）**：Sandcastle 只 bind-mount git worktree（被加工物），agent 跑在**干净容器**——host 的 `~/.claude`（skills / 全局 CLAUDE.md / MCP）**故意不带进去**（Sandcastle 的 clean-room 取向：防 host 状态污染、保可复现）。后果:容器里的 Sonnet/codex 只有**项目级 CLAUDE.md**（在 workspace 内、被自动读）+ 纯净 CLI + prompt,**没有项目 slice-dev 那组纪律 skill**。
  - **slice 开发真正用的 skill 组**（CLAUDE.md 步骤6 + DEV_WORKFLOW 速查,全非 gstack、全在 `~/.claude/skills/<name>/`、纯 markdown 无 host 二进制依赖）:`tdd`(主) + **`codebase-design`(被 tdd/improve 挂用、是 tdd 子 skill)** + `review` + `diagnosing-bugs` + `improve-codebase-architecture`;编排器 family 合并那步还需 `resolving-merge-conflicts`。**skill 间有依赖（tdd→codebase-design）,故须整组注入、不能 cherry-pick 一两个。**
  - **gstack 与 slice 开发无关**:gstack 是 ship/存档/编排 ceremony,不进实现腿——别把它列进注入清单。
  - **cross-model 评审不靠注入 cmr skill**:`ak-cross-m-review` 是单 session 扇出工具,编排器在 **pipeline 层**用不同模型的 `run()` 实现评审(本 spike 已证:codex run() 评 Sonnet run()),不往容器里塞 cmr skill。
  - **关键 SE 原则:纪律文档化、prompt 收薄(否则可复现性破功)**。光把 skill 文件挂进去≠agent 会用——必须有**文档喊它用**;而那个「喊」不能写在编排器 prompt 里(= 我每次即兴发挥 = 退回 hermes「运行时临场建卡不可复现」,正是 #217 要弄死的)。纪律必须**进版本库**:① **仓库 CLAUDE.md 补机器可执行的「## Skill routing」段**(实现切片→`/tdd`;末尾→`/review`;硬 bug→`diagnosing-bugs`;架构清理→`improve`),in-container agent 自动读 workspace CLAUDE.md 即按它走;② 编排器 prompt **收薄**到「实现 issue #N,按本仓 CLAUDE.md dev 流程做」,不复述方法论。**现状缺口:本仓 CLAUDE.md 只有叙事 `## 开发流程`(给人读)+ `## Agent skills`(指针),无机器可执行 Skill routing 段——叠纪律层前要补。**
  - 落地三件套 = **skills 在场**(容器 bind-mount `cp -RL` 实体化那组 dev skill 到 `/home/agent/.claude/skills`)+ **CLAUDE.md 路由**(在 git、机器可执行)+ **thin prompt**;待「注入+路由 vs 不注入」A/B 实测(同一 issue #137 对照)定收益。
- **未决（剩唯一项）**：设计评审闭环（本地 cmr + 线上 bot）未跑——本 ADR Proposed → Accepted 的最后一道。并行编排证据已补齐（发现 3）；skill 注入收益待 A/B（发现 4，**下方 v1 具体化已改向「按 profile 预烤镜像」，A/B 作废**）。

## v1 具体化（2026-06-20 grill-with-docs 收敛；薄质量层落到「单个实现切片」的最小形态）

> **历史说明（#217 → #244）**：本 ADR 上半部（背景 / 决定 / Considered / Consequences）以 **#217** 为语境记录「编排器自建 vs 采 Sandcastle」的决定——那是当时的 epic 编号。**v1 实际 build 已 spin 成独立新 epic #244、与 #217 无关**（不隶属、不取代、升级链不含 #217）。上半部及别处的 #217 仅作历史 / 对照出现，v1 设计不依赖、不修改 #217。

衡量标尺仍是北极星。v1 = wiki [[tdd-autonomous-dev]] 流程的**一小段**（单切片 implement + per-slice review/fix → push）；**流程编排由 ADR 0018 的 runner-driven step 序列控**（取代「coder 一个 run 跑完整流程、自判完成」）。ship / 家族 / 线上评审全 deferred；家族 base 当前置见 ADR 0017。

以下 v1 spec（包括 #244 的 S0–S8 步骤表）只保留为历史；现行流程与角色接力只读 #869/#868。

- **v1 模型 = Sonnet 写 / Opus 4.8 评**，暂搁置 wiki per-slice「不用 Claude 省额度」规矩（claude -p credit 紧；v1 走订阅 auth 容器、Opus 担得起，代价是烧 Claude 额度）；以后换 codex 回省额度、per-slice 升多模型时再用 `ak-cross-m-review`。
- **v1 = 一个镜像、双角色**：coder/reviewer 同一常驻 sandbox（共享 worktree），靠 `run()` 级 fresh context 保上下文隔离（reviewer 看不到 coder「我刚写的」推理）。**可逆**：reviewer 真需独立再拆两镜像。
- **dev skills + 角色 soul 烤进 profile 镜像**（**取代发现 4 的 cp -RL bind-mount 注入**，later-doc-wins）。
- **输入只收单个实现切片**（「喂父报错、子不报错」，凭 **native sub-issues** 判：有子 = 父 epic、拒；无子 = 叶子切片、放行）；**调用端只传 issue 数字**，编排 + prompt 全在代码里（保可复现）。`## Agent Brief` **不是闸**（可选；用户 2026-06-22 拍——`to-issues` 切片未必带它，coder 读整个 issue；S0 闸 = rfa ∧ 无 sub-issues ∧ blocked_by 全 closed）。**本 epic 全新、与 #217 无关**。
