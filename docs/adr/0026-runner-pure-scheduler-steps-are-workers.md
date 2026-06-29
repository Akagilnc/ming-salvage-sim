---
status: accepted
supersedes-part-of: ADR 0018 (step 分类); ADR 0016 (spike 发现4 的 cmr/gstack 不进容器排除)
partially-superseded-by: ADR 0030 (2026-06-29：「cmr/per-slice = 一条带记忆 worker 兼 fixer、无 runner 轮间 loop、findings 不在 worker 间传」这一条被反转，见下「前向更正」)
---

# 编排器 runner = 纯调度器；每个具体 wiki 步是 worker

> **前向更正（ADR 0030，2026-06-29）—— 读本 ADR 时注意**：下文「例外 = worker 内部的『收敛』不是分叉」整段（cmr/per-slice = 一条带记忆主 session 兼 fixer、fix-loop 在 worker 内、没有独立 fix worker、没有 runner 轮间 loop、findings 不在 worker 间传）**已被 ADR 0030 反转**。dogfood #362 证伪了「in-session 记忆能自律收敛」的赌注（#375 完整性闸被吞、#373 spec-miss 被 defer），改为「收敛 loop 由 runner 持、coder/reviewer/fix 独立 worker、findings 走 landing file、每轮 fresh reviewer 复审全 diff」。**本 ADR 的核心「runner = 纯调度器、每个具体 wiki 步是 worker」仍然有效**——0030 恰是更彻底地落实它（把埋进单 worker 的分叉点提回 runner 边界，正是本 ADR 自己定的「分叉点必须是 runner 边界」）。遇到下文 consolidate 描述与现状不符时以 ADR 0030 为准，不要据此判「实现违反设计」。**具体被反转的不止「例外 = worker 内部的『收敛』」整段，还包括 Consequences 里「fresh 只在 review 腿、worker 主 session 带记忆」那条及其「不需要也不准把 findings 当 data 在 fresh worker 间传递」——这两处在 0030 下均已翻案（review 成独立 worker、findings 经 landing file 跨 worker 传是独立性载体）。**

**决定**：runner 只做**调度**——step 之间的流程决策（input gate / route / 排序 / step ledger / 续跑）；它**不内联任何具体活**。每个产出工作的 wiki 步——写码 / 评审 / cmr / ship——是一个 **worker**（merge 非均匀 worker，见 Consequences）：跑在自己容器里、里面 agent 是该容器**顶层**（非 runner 的 sub，故能起自己的 sub + CLI），由 runner 派出去执行、收回结果、据此路由。worker **不一定用 skill**；用时 Claude = `Skill` invoke、Codex = 加载 SKILL.md 当 skill item 传入 prompt。

**真源边界**：issue 是需求真源，worker 用 `gh` live fetch body + comments；worktree 是代码真源，由 runner 挂给容器；image/soul/skill 是流程真源，封装 wiki/skill 调用和 host 差异；runner 是调度真源，只传 issue/repo/soul/auth/运行参数文件并读取终态。`.orchestrator-snapshot.json` 这类 host 侧快照可保留作审计/续跑材料，但不得作为 worker 的需求执行真源；离线先重试，auth 失败 escalate 要人登录，不 fallback 到猜测。

**为什么**：ADR 0018 让 runner 控外层序列（防 agent 跳步/合并步），但把 `push / cmr / ship` 归成「runner 动作」（纯 TS 内联）。结果 runner **自己手搓**了 cmr（三腿）和 ship（push+PR）的等价逻辑，而不是 invoke 现成的 `ak-cross-m-review` / `gstack-ship` skill —— 偏离了「忠实跑 wiki 流程」。把这些改成 worker 步后，runner **薄到没东西可偏**，具体纪律全活在 worker invoke 的 skill 里。

**步边界 = 路由/分叉点**（判据：步内无需调度）。无分叉的连续活可按 smart zoom 合成大步（省调度、但吃上下文）；**任何分叉点必须是 runner 边界、不能埋进 worker**——否则 worker 内 agent 自跑一条带分叉的流程，正是 ADR 0018 要弄死的。

**例外 = worker 内部的「收敛」不是分叉（wiki 模型）**：一个 review→修复→复审 直到收敛的 loop，**整条住在 worker session 内**，runner 看到的只是该 worker 的**终态判决**（收敛→下一步 / escalate→停）——这是路由点、不是隐藏的多步分叉。wiki line 42 明定切片 coder「一路做到 per-slice cmr concur 才 return，fix loop / drift / 升级全在 subagent 内部跑完」；integrated cmr 同构。故 **cmr = 一个 worker = 一条带记忆主 session，它本身就是 fixer**：session 内派 fresh review 腿 → grade → 自己改 → 派 fresh 腿复审 → 收敛，**fix-loop 在 worker 内、不归 runner**。runner 只派这一个 cmr worker、读它收敛/escalate 的终态判决。**没有独立 fix worker、没有 runner 轮间 loop、没有把 findings 当 data 在 fresh worker 间传递。**

**这推翻 ADR 0016 spike 发现4 的一条排除**：0016 当时判「`ak-cross-m-review` 是单 session 扇出工具、塞不进容器，cmr 在 pipeline 层用不同模型 run() 实现；gstack 不进实现腿」。该前提已被实测证伪（2026-06-22 spike，见 #333）：容器顶层 agent 能 invoke 真 skill 并起满三腿——codex（rc=0 真评审）+ claude `Task` 腿 + agy（Linux 二进制 + 文件 token），均在容器内逮到注入 bug。故 cmr/ship 改为容器 worker invoke 真 skill，runner 不再手搓近似。

## Consequences

- **supersede ADR 0018 的 step 分类**：`push / cmr / ship` 从「runner 动作」改成「worker 步」；runner 只剩纯调度决策（gate / route / 排序 / ledger / 续跑）。
- **supersede ADR 0016 的 cmr/gstack 排除**：`ak-cross-m-review` / `gstack-ship` 改为烤进镜像、由容器 worker invoke（取代 0016 的「pipeline 层 run() / 不进容器」）。三腿容器内实证可行（#333）；agy 走文件 token（`~/.gemini/antigravity-cli/antigravity-oauth-token`，runtime 挂载，同 codex/claude auth 模式）。
- **fresh 只在 review 腿、worker 主 session 带记忆**（2026-06-24 更正——旧文「评审类 cmr/reviewer 每轮 fresh」是错的，它把「cmr worker」和「review 腿」混为一谈）：**唯一每轮 fresh 的是 cmr/reviewer worker 内部派出的 3 条只读 review 腿**（codex / agy CLI + claude subagent）——fresh 保证 cross-model 独立性、不复查自己旧 finding。而 **worker 主 session（= fixer）全程一条、带记忆**：它记得上几轮报过什么、改过什么、哪些是重复假报，凭记忆 dismiss、凭记忆收敛。生产类（coder/per-slice）同理：一条带记忆 coder subagent 干到 per-slice cmr concur，fix loop 在 session 内。**「带记忆」靠的就是「同一条 `sc.run` session」本身**（正常 sc.run 自带 git-truthing：核实真提交、不信模型自报），**不需要也不准把 findings 当 data 在 fresh worker 间传递来模拟记忆**（旧 `priorFindings`/`cmrReason` 轮间传是错架构的产物，删）。**`resumeSession`（session:"resume"）仍仅 crash/escalate 续跑**——它跳过 git-truthing 且 maxIter 固定 1，**不承载正常 fix-loop**（正常 fix-loop 是 worker 主 session 内的循环，git-truth 完整）。**fresh ≠ 新 checkout**：review 腿 fresh 指「无上轮 review 记忆」，worker 容器仍挂同一条 host 常驻 slice worktree（ADR 0017：提交真源 = 常驻 worktree），提交绝不落进临时 checkout。
- **落实 ADR 0016 的 bake**：每个 worker = 从**一个预制镜像**起的容器，工具链 + 多模型 CLI + dev skills + 角色 soul **全烤进镜像**。**「不 runtime bind-mount」只指这些工具/技能/soul/资产**（故可复现）;runtime 仍挂 = 被加工的常驻 slice worktree（ADR 0017 提交真源,见上条）+ auth token —— 必要例外、非矛盾。
- **promptFile 只剩入口契约**：读 baked soul / invoke 对应 skill / 指向 `.cmr-focus.md`、`.ship-focus.md` 等运行参数 / 输出结构化 tag。promptFile 不写 wiki 方法、不塞 issue 正文、不每轮改措辞；如果 promptFile 长成 mini-wiki，就是 runner 重新手搓流程的回归。
- **scope = A（自治 implement→ship）先建,B（grill/to-prd/to-issues 带上下文+HITL）以后**；worker 清单 / worker↔runner 结果契约 / 容器粒度等实现细节见 PRD #330。
- **merge 非均匀 worker（家族层 / B 段,本 PRD A 段不做）**：family merge 的波次 / 冲突分派 / verify-fail-fast / 续跑路由仍是 **runner 调度**（ADR 0022 决定3），不是无分叉产出步;仅「无冲突单次 git merge 或冲突解决 fallback」是 worker 形——别把整段 merger 循环塞进 worker、绕过 family ledger/verify/route 这些 runner 级保证。
