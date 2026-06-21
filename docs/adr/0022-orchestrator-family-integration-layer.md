# 家族集成层：commander 确定性波次调度（读现成子片）+ distinct-branch fan-out + merger 薄编排器

Status: Proposed（2026-06-21；grill-with-docs 收敛 + 设计 cmr R1 修订。评审待 to-prd 之后，按 review-gate-after-to-prd 流程。前置：ADR 0021 仓库隔离、0016/0017/0018。）

## 背景

ADR 0016/0017 把家族层（父 epic → 多子片并行 fan-out + 合回家族 base）显式 deferred。现做。

人机分工实证（本项目）：用户强参与**只到 PRD + ADR 的 cmr 评审**；之后 `to-issues` 切片（我在**外部 design session** 切、发 GitHub native sub-issues + 显式 `blocked_by`，最多征用户一句、不评审）/ implement / cmr / merge **全 agent 自治**；唯一人环 = cmr 不收敛（概率极低）；**不做 merge 前代码 review**，反馈靠 post-merge 实际游玩。

Sandcastle 原生（文档/issues 优先核过、代码验证）：
- 并发 fan-out 安全的**唯一**前提 = 每 child 一个 distinct named branch（README「fork is session-only」；`head`/`merge-to-head` 并发不安全）。
- `parallel-planner` 模板的 **Plan stage 是「读现成 open issue 列表 → 选本轮 unblocked」的调度/选择器**（`plan-prompt.md` 实读：输入 already-filtered ready issues、输出 `{id,title,branch}`），**不分解 epic、不建 sub-issue**（cmr R1 三腿 + 源码核实）。Execute=`Promise.allSettled`，Merge=纯 LLM prompt。
- **库无多分支整合原语**（`dist/index.d.ts` 无 `merge`/`integrate`）；merge 真强项 = per-run `merge-to-head` 回灌（库级、副作用保全），作用在 **slice/run 级**——单片 coder run 已在用。

## 决定

1. **commander = 确定性波次调度（runner 步，非 LLM 分解器）**：父 epic 的子片由 `to-issues` 在**编排器外**切好、发成 GitHub native sub-issues + 显式 `blocked_by`（单一真相）。commander 读这些现成子片 + 显式 `blocked_by` DAG → 拓扑分波（未阻塞者并发为一波、被阻塞者下波）→ fan-out。**不自分解、不用原生 Plan 的 LLM 依赖推断**（我们有显式 `blocked_by`，无需 LLM 再猜，且原生 Plan 只是 selector、会重推已有的边）。切片质量由切片那一步（design session 带 PRD/ADR 上下文）保证，非编排器职责。

2. **fan-out = Sandcastle 原生 fork + 每子片 distinct branch**，跑在该 invocation 的独立 clone（ADR 0021）内故安全。每子片**完整复用单片 S0-S8**（coder→reviewer），base 从家族 base 切（家族模式闸适配见决定 6、base 取值见决定 7）。

3. **merger = 薄编排器（确定性骨架 + 点状 LLM）**，与原生「整段 LLM」相反，**分两层时序**：
   - **每波（fan-out barrier）**：① **cycle-check**：排波前对 `blocked_by` 图做无环校验，有环 → fail-closed 升级（不死锁）；② 把**本波**已过审子片分支**串行 `git merge --no-ff`** 落家族 base——家族整合是**已提交分支间的 branch-to-branch 合并**，库无此原语 → Backend seam 后的**确定性 `git merge`**，**不是 `merge-to-head`**（后者是 slice/run 级回灌、已在单片 coder run 用）；冲突才上 LLM（`resolving-merge-conflicts` soul），原生一上来就 LLM、本设计确定性优先；③ 每合一片即写 family ledger（决定 5）。下一波从**更新后的家族 base** 切（拿到上波依赖）。
   - **全波合完一次（末尾）**：④ 确定性 family verify（typecheck + 单测 + 全量，不塞 LLM prompt），红 → 中止 + 错误包 + ledger 记 abort；⑤ 整合后 cross-model **cmr 承重闸**（抓跨片接缝；原生零评审）。

4. **自治边界 = 分阶段到 PR**：family 编排器跑到「家族 base + 本地 cmr 绿 + 开好 PR」即止；线上 bot cmr + merge 复用现有 pr-review-loop 的独立自治阶段。人只在 cmr 不收敛时被叫（复用 ADR 0017/0018 的升级续跑：卡点 → 返回调用端 → 拍 → resumeSession 注入）。

5. **family ledger**（家族 base worktree 的 sibling、worktree 外）= **append-only 事件账本**，每合一片即写一条（至少 `{childIssue, childBranch, childHead, wave, familyHeadBefore, familyHeadAfter, status}`），verify/cmr 失败写 `aborted` 事件。**幂等不变式**：merger 只在该片的 merge commit **已落家族 base 之后**才写其 `merged` 条；崩溃续跑先 **reconcile**——比对 ledger 记的「家族 base HEAD」与 live HEAD，一致才信「已合集合」、跳过已合（单片 `checkBranchHeadConsistency` 的家族版）。字段级 JSON 留 TDD。

6. **家族模式的闸适配（与单片 S0 闸两点差异）**：① 家族入口**接受父 epic**（单片 S0 闸「无 sub-issues 才放行」是单片规则，家族模式对 epic 反转该条），每个子片仍各自过单片 S0 闸（rfa 标签 + `## Agent Brief` + 自己无 sub-issues + 依赖满足）——故 `to-issues` 发的子片必须带 `ready-for-agent` + `## Agent Brief`，否则各自被 S0 拒。② **波次解阻塞看「依赖已合进家族 base」（family ledger），不看 GitHub issue `closed`**：单片 S0 用「`blocked_by` 全 closed」判依赖满足，但家族里 blocker 只是合进家族 base、其 issue 未必 closed；按 closed 判会 barrier 死锁（codex R1）或 closed≠merged 误放（agy R1）。故家族模式依赖满足判据 = `blocked_by` 子片均已 merged 进家族 base（查 ledger），替代 closed 判据。

7. **家族 base = dedicated clone 上的本地分支**，merger 合并累积在本地。子片**从本地家族 base 切**（非 `origin/<family-base>`）——`cutRefFor` 当前对有远端的 base 取 `origin/<base>`，对本地家族分支会切到缺上波提交的陈旧 base（agy R1）；家族 base 须走本地引用。

## Considered Options

- **commander 自分解 / 采原生 Plan 当分解器（纯 AFK 喂生 epic）**：否决——cmr R1 三腿 + 源码核实：原生 Plan 不分解 epic、是「选 unblocked」的调度器；真要自动切 = 自造 to-issues（违背 `orchestrator/CLAUDE.md` 头号规则）+ 无人闸切片质量风险。`to-issues` 留外部（design session 带上下文、质量稳），commander 只调度现成片（用户 2026-06-21 拍）。
- **commander 用原生 Plan 的 LLM 依赖推断**：否决——有 `to-issues` 写的显式 `blocked_by`，LLM 再推冗余且可能与显式边冲突；commander 直读显式 `blocked_by`、确定性拓扑。
- **merger 照搬原生「整段 LLM 解任意冲突」**：否决——用户看不了 diff、cmr 是唯一承重关卡，不让 LLM 静默吞冲突；不可重放、费额度。
- **merger 用 `merge-to-head` 做家族整合**：否决——它是 slice/run 级回灌、非 branch-to-branch 合并 API；已提交子片分支合进家族 base = 确定性 `git merge`。
- **单 run 一杆到底（含线上 bot cmr）**：否决——线上 loop 性质不同（GitHub 侧、数小时空等）且已有 pr-review-loop 工具。

## Consequences

- 家族 base 必须 clone-rooted（ADR 0021，每 invocation 独立 clone）；否则 fork 波次原样重踩 prune 跨 session/invocation 互毁。
- 新增持久件：**family ledger**（append-only + 幂等不变式见决定 5；字段级 JSON 留 TDD）。
- 家族整合 = 确定性 `git merge`（库无 branch-to-branch 原语）；`merge-to-head` 仅 slice 级回灌、在单片 coder run 内——两者不混。
- 切片在外部 design session 做（带上下文、质量较稳）；下游闸（merger 冲突 / family verify / 整合 cmr）兜的是 **conflicting + seam-broken** 错切，**coherent-but-wrong（自洽但分错）的错切仍可能漏过下游**，靠切片那步的判断 + post-merge 游玩兜（honest caveat，非下游全兜）。
- 角色 roster = coder + reviewer（沿用）+ merger（冲突 fallback soul）；**commander 是 runner 确定性调度步、无 soul**（非 LLM）。
- 删 `cleanResidueAt` 的 repo 级 prune（ADR 0021）还须更新 `Backend.cleanResidue` 的 JSDoc 契约（types.ts 现把 prune 列为 sequence 一部分），且 #255 resume 路径受影响是有意的。
- base 参数化：Backend seam 已收 base 参数（ADR 0017 §2），但 runner 现硬编码 `SLICE_BASE='main'`，须扩成从家族 base 取（非只翻常量）。
- 编排器成熟后单独立项；现 co-located 在 `orchestrator/`。
