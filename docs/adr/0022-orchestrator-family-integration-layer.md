# 家族集成层：commander 确定性波次调度（读现成子片）+ distinct-branch fan-out + merger 薄编排器

Status: Accepted（2026-06-21；grill-with-docs 收敛 + 设计 cmr 5 轮 + 线上 bot 收敛 → PR #290 合入 main。前置：ADR 0024 仓库隔离、0016/0017/0018。）

> **前向更正（ADR 0061，2026-07-06 Accepted 起生效）**：下文「决定 4」的"线上 bot cmr + merge 复用现有 pr-review-loop 的独立自治阶段"已被 **ADR 0061 反转**——线上评审 loop 纳入编排器自身，自治边界从"止于 PR"推进到"止于 merge"（#366）。本 ADR 其余决定不受影响。

## 背景

ADR 0016/0017 把家族层（父 epic → 多子片并行 fan-out + 合回家族 base）显式 deferred。现做。

人机分工实证（本项目）：用户强参与**只到 PRD + ADR 的 cmr 评审**；之后 `to-issues` 切片（我在**外部 design session** 切、发 GitHub native sub-issues + 显式 `blocked_by`，最多征用户一句、不评审）/ implement / cmr / merge **全 agent 自治**；唯一人环 = cmr 不收敛（概率极低）；**不做 merge 前代码 review**，反馈靠 post-merge 实际游玩。

Sandcastle 原生（文档/issues 优先核过、代码验证）：
- 并发 fan-out 安全的**唯一**前提 = 每 child 一个 distinct named branch（README「fork is session-only」；`head`/`merge-to-head` 并发不安全）。
- `parallel-planner` 模板的 **Plan stage 是「读现成 open issue 列表 → 选本轮 unblocked」的调度/选择器**（`plan-prompt.md` 实读：输入 already-filtered ready issues、输出 `{id,title,branch}`），**不分解 epic、不建 sub-issue**（cmr R1 三腿 + 源码核实）。Execute=`Promise.allSettled`，Merge=纯 LLM prompt。
- **库无多分支整合原语**（`dist/index.d.ts` 无 `merge`/`integrate`）；merge 真强项 = per-run `merge-to-head` 回灌（库级、副作用保全），作用在 **slice/run 级**——单片 coder run 已在用。

## 决定

1. **commander = 确定性波次调度（runner 步，非 LLM 分解器）**：父 epic 的子片由 `to-issues` 在**编排器外**切好、发成 GitHub native sub-issues + 显式 `blocked_by`（单一真相）。父流程开工第一步读取 live GitHub 状态、标签和 sub-issue 数量：`closed` 子片退出当前调度并满足依赖（包括此前按单片模式独立完成者），但已有 family worktree 保留到父流程 terminal-success + 显式 GC，期间 reopen + ready 可复用原现场；open 但无 `ready-for-agent` 的子片不启动；open + ready 但自身仍有 sub-issues 的子片显式列为 unsupported nested family 并跳过；只有 open + ready 的叶子子片进入显式 `blocked_by` DAG → 拓扑分波（未阻塞者并发为一波、被阻塞者下波）→ fan-out。当前只支持一层 family，不递归展开孙 issue。过滤后没有可运行叶子时，本次运行报告各项跳过原因并正常空跑完成；不建新 family worktree、不派 worker、不建 PR、不 park，也不因空跑立即 GC 旧现场。**不自分解、不用原生 Plan 的 LLM 依赖推断**（我们有显式 `blocked_by`，无需 LLM 再猜，且原生 Plan 只是 selector、会重推已有的边）。切片质量由切片那一步（design session 带 PRD/ADR 上下文）保证，非编排器职责。

2. **fan-out = Sandcastle 原生 fork + 每子片 distinct branch**，跑在该 invocation 的独立 clone（ADR 0024）内故安全。每子片**复用单片 S0-S8 流程，但家族模式下 S7 的 `backend.push` 替换为本地 no-op**（子片只本地提交到自己分支、不 push 远端——共享 clone 内多个子片并发 push 会撞 `.git/refs/remotes` 引用锁；codex R3 指出「完整复用 S0-S8」含强制 S7 push、与「不 push」矛盾，故此处显式碰 S7）；只有家族 base 在末尾开 PR 时 push 一次。**家族 context（parentIssue / family ledger 引用）经 RunnerOptions 传入子片 runner**，使其 S0 走 ledger 口径（决定 6③）+ S7 走 no-op（agy R3）。base 从家族 base 切（家族模式闸适配见决定 6、base 取值见决定 7）。

3. **merger = 薄编排器（确定性骨架 + 点状 LLM）**，与原生「整段 LLM」相反，**分两层时序**：
   - **每波（fan-out barrier）**：① **cycle-check**：排波前对 `blocked_by` 图做无环校验，有环 → fail-closed 升级（不死锁）；② 把**本波**已过审子片分支**串行 `git merge --no-ff`** 落家族 base——家族整合是**已提交分支间的 branch-to-branch 合并**，库无此原语 → Backend seam 后的**确定性 `git merge`**，**不是 `merge-to-head`**（后者是 slice/run 级回灌、已在单片 coder run 用）；冲突才上 LLM（`resolving-merge-conflicts` soul），原生一上来就 LLM、本设计确定性优先；③ 每合一片即写 family ledger（决定 5）；④ **本波合完跑一次 family verify（typecheck + 单测）fail-fast**——红即中止、不再排下一波（避免白跑下游波，agy R2）。下一波从**更新后的家族 base** 切（拿到上波依赖）。
   - **全波合完一次（末尾）**：⑤ 确定性 **全量** family verify；⑥ 整合后 cross-model **cmr 承重闸**（抓跨片接缝；原生零评审）。**说明**：每波 LLM 解的冲突合并，其承重审是末尾这道 cmr（决定 4「止于 cmr 绿」）；若中途 verify 红而中止，这些 LLM 合并留在家族 base + ledger 供人 triage（不被 cmr 审但可查），符合「不静默吞」（Claude R2）。

   **family CMR module context contract**：family/child issue 可在正文中提供唯一结构化区块 `## Module Declaration` + fenced YAML，runner 只解析该区块，不从标题、散文、日志或临时 reviewer 文本推断 module 边界。issue-body YAML 允许字段仅为 `module`、`module_scope`。其中 `module_scope` 是当前 family/child 已拥有的文件/目录 surface；「刻意不在本 family base 内开发、但可作为 cross-module defer target 的目标 module」只能由 runner/run-option/route metadata 提供，不扩展 issue-body YAML。CMR 的 `cross_module` defer 只有在 target 命中 runner 声明的 undeveloped module、且该 target 不属于当前 module context 时才可放行；当前 module context 只用于归因和阻塞判定，未声明 target 一律留在本 family gate 内继续修。

4. **自治边界 = 分阶段到 PR**：family 编排器跑到「家族 base + 本地 cmr 绿 + 开好 PR」即止；线上 bot cmr + merge 复用现有 pr-review-loop 的独立自治阶段。人只在 cmr 不收敛 / cycle 时被叫（复用 ADR 0017/0018 的升级续跑：卡点 → 返回调用端 → 拍 → resumeSession 注入）。**任何父流程重入都先重抓 live GitHub metadata，再处理旧 escalation；重新读取子 issue 成员、状态、标签和依赖，不信首次启动缓存**：暂停期间新挂入的子 issue 按决定 1 的过滤规则加入后续候选集，从当前 family base 切 worktree；已 merged 子片与原有未完成现场保持不动。未回答的 child-scoped decision 只阻塞原子片、依赖它的下游与 final barrier，不能在刷新成员表前短路整个 family，也不能阻止独立的新子片运行。原先在本 family、重入时已从 native sub-issues 移除的未合子片视为 owner 明确取消该家族现场：停止调度并删除其 worktree，但保留 branch、family ledger、日志与 telemetry/统计；已 merged 子片不自动反向撤销。该规则同时覆盖 cycle 被人在 GitHub 改依赖后重入，避免旧依赖图反复升级。

5. **family ledger**（家族 base worktree 的 sibling、worktree 外）= **append-only 事件账本**，每合一片即写一条（至少 `{childIssue, childBranch, childHead, wave, familyHeadBefore, familyHeadAfter, status}`），verify/cmr 失败写 `aborted` 事件（携带当时 family head）。**幂等不变式 + 崩溃窗口 reconcile**（cmr R2 三腿一致：merge 成功但 ledger 没写就崩的窗口须有可实现契约）：merger 只在该片 merge commit **已落家族 base 之后**才写其 `merged` 条。崩溃续跑先 reconcile，比对 ledger 末条 `familyHeadAfter` 与 live HEAD：① 一致 → 信已合集合、跳过已合、续合；② **live HEAD 领先 ledger（merge 成功、ledger 未写就崩的常规窗口）→ 不 abort**：对每个未记账子片查 `git merge-base --is-ancestor childHead liveHEAD`（**若该子片 branch/childHead 尚不存在——崩在它任何提交前——跳过 merge-base、当「未合」从头跑、不报错，agy R4**；存在且其合并已落）→ 补写一条 **`status:"merged"` + `event:"reconciled"`** 的 ledger 条（**保持 `status==merged`，使决定 6 的解阻塞谓词照样计入**——codex R3：若补成 `status:"reconciled"`，谓词 `status==merged` 不计、reconciled 的 blocker 仍被判未合、死锁）、续合；真有未落 / 不一致的 → fail-closed 升级。**即家族版 reconcile 比单片 `checkBranchHeadConsistency`「mismatch 直接 abort」更宽**，才兑现「幂等续合」（agy/codex R2）。字段级 JSON 留 TDD。

6. **家族模式的闸适配（与单片 S0 闸三点差异）**：① 家族入口**接受父 epic**（单片 S0 闸「无 sub-issues 才放行」是单片规则，家族模式对 epic 反转该条）；直接输入某个子 issue 则仍可走单片流程，使用独立 worktree、独立 PR，不建立父 worktree。② **依赖满足判据 = GitHub-closed 或本 family ledger-merged**：父流程开始前已独立完成并 closed 的 blocker 已满足；本次 family 内刚合进家族 base、尚未 closed 的 blocker则由 ledger `merged` 满足。只看 closed 会让本次 family barrier 死锁，只看 ledger 会重做此前已独立完成的子片。③ **子片各自的家族 S0 依赖门使用同一联合判据**；rfa + 自己无 sub-issues 两项不变（`## Agent Brief` 可选、有则为最权威部分）。故 `to-issues` 发的待执行子片必须带 `ready-for-agent`。④ **家族外（external）`blocked_by` 在父 epic 进来时显式预检**：外部 blocker 不会进入本 family ledger，只能由 live GitHub `closed` 满足；凡仍 open 即拒整个 family run，并列出具体阻塞关系。admission 与每次 resume 都重新读取 live GitHub metadata。

7. **家族 base = dedicated clone 上的本地分支**，merger 合并累积在本地。子片**从本地家族 base 切**（非 `origin/<family-base>`）——`cutRefFor` 当前对有远端的 base 取 `origin/<base>`，对本地家族分支会切到缺上波提交的陈旧 base（agy R1）；家族 base 须走本地引用。

## Considered Options

- **commander 自分解 / 采原生 Plan 当分解器（纯 AFK 喂生 epic）**：否决——cmr R1 三腿 + 源码核实：原生 Plan 不分解 epic、是「选 unblocked」的调度器；真要自动切 = 自造 to-issues（违背 `orchestrator/CLAUDE.md` 头号规则）+ 无人闸切片质量风险。`to-issues` 留外部（design session 带上下文、质量稳），commander 只调度现成片（用户 2026-06-21 拍）。
- **commander 用原生 Plan 的 LLM 依赖推断**：否决——有 `to-issues` 写的显式 `blocked_by`，LLM 再推冗余且可能与显式边冲突；commander 直读显式 `blocked_by`、确定性拓扑。
- **merger 照搬原生「整段 LLM 解任意冲突」**：否决——用户看不了 diff、cmr 是唯一承重关卡，不让 LLM 静默吞冲突；不可重放、费额度。
- **merger 用 `merge-to-head` 做家族整合**：否决——它是 slice/run 级回灌、非 branch-to-branch 合并 API；已提交子片分支合进家族 base = 确定性 `git merge`。
- **单 run 一杆到底（含线上 bot cmr）**：否决——线上 loop 性质不同（GitHub 侧、数小时空等）且已有 pr-review-loop 工具。

## Consequences

- 家族 base 必须 clone-rooted（ADR 0024，每 invocation 独立 clone）；否则 fork 波次原样重踩 prune 跨 session/invocation 互毁。
- 新增持久件：**family ledger**（append-only + 幂等不变式见决定 5；字段级 JSON 留 TDD）。
- 家族整合 = 确定性 `git merge`（库无 branch-to-branch 原语）；`merge-to-head` 仅 slice 级回灌、在单片 coder run 内——两者不混。
- 切片在外部 design session 做（带上下文、质量较稳）；下游闸（merger 冲突 / family verify / 整合 cmr）兜的是 **conflicting + seam-broken** 错切，**coherent-but-wrong（自洽但分错）的错切仍可能漏过下游**，靠切片那步的判断 + post-merge 游玩兜（honest caveat，非下游全兜）。
- 角色 roster = coder + reviewer（沿用）+ merger（冲突 fallback soul）；**commander 是 runner 确定性调度步、无 soul**（非 LLM）。
- 删 `cleanResidueAt` 的 repo 级 prune（ADR 0024）还须更新 `Backend.cleanResidue` 的 JSDoc 契约（types.ts 现把 prune 列为 sequence 一部分），且 #255 resume 路径受影响是有意的。
- base 参数化：Backend seam 已收 base 参数（ADR 0017 §2），但 runner 现硬编码 `SLICE_BASE='main'`，须扩成从家族 base 取（非只翻常量）。
- 编排器成熟后单独立项；现 co-located 在 `orchestrator/`。
