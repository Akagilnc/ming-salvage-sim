# 家族集成层：commander 确定性调度 + distinct-branch 波次 fan-out + merger 薄编排器

Status: Proposed（2026-06-21；grill-with-docs 收敛。评审待 to-prd 之后，按 review-gate-after-to-prd 流程。前置：ADR 0021 仓库隔离、0016/0017/0018。）

## 背景

ADR 0016/0017 把家族层（父 issue → 多子片并行 fan-out + 合回家族 base）显式 deferred。现做。

人机分工实证（本项目）：用户强参与**只到 PRD + ADR 的 cmr 评审**；之后 `to-issues`（我在 design session 切、并发优先）/ implement / cmr / merge **全 agent 自治**；唯一人环 = cmr 不收敛（概率极低）；**不做 merge 前代码 review**，反馈靠 post-merge 实际游玩。

Sandcastle 原生（文档/issues 优先核过、代码验证）：
- 并发 fan-out 安全的**唯一**前提 = 每 child 一个 distinct named branch（README「fork is session-only」；`head`/`merge-to-head` 并发不安全）。有 `parallel-planner` 模板（Plan=LLM 分解 / Execute=`Promise.allSettled` / Merge=纯 LLM prompt）。
- **库无多分支整合原语**（`dist/index.d.ts:966` 无 `merge`/`integrate`）；模板的多分支整合 = 一段 `merge-prompt.md` 整段委托 sonnet。
- merge 真强项 = per-run `merge-to-head` 回灌（库级、确定性、副作用保全：`preservedWorktreePath` / `sync-base` ref），作用在 **slice/run 级**——单片路径已在用。

## 决定

1. **commander = 确定性调度代码，非 LLM soul**：读父 issue 的现成 native sub-issues + blocked_by DAG（`to-issues` 在编排器外、design session 切，单一真相在 GitHub），按波次调度（未阻塞者并发为一波、被阻塞者下波）。**不自分解**（切片质量决定 merge 难度，且不与 to-issues 抢权威）。
2. **fan-out = Sandcastle 原生 fork + 每子片 distinct branch**，跑在独立 clone（ADR 0021）内故安全。每子片**完整复用单片 S0-S8**，仅把 base 从硬编码 main 改为家族 base 参数（ADR 0017 §2 已预留接 base 参数）。
3. **merger = 薄编排器（确定性骨架 + 点状 LLM）**，与原生「整段 LLM」相反：
   - [0] 读 blocked_by 拓扑排波次；
   - [1] 串行把子片分支落家族 base——**slice 级回灌沿用原生 run / merge-to-head，不手搓 git plumbing**；
   - [2] **仅冲突时**上 LLM（`resolving-merge-conflicts` skill），原生是一上来就 LLM，本设计确定性优先；
   - [3] 确定性 family verify（typecheck + 单测 + 全量，不塞进 LLM prompt）；
   - [4] 整合后 cross-model **cmr 承重闸**（抓跨片接缝；原生零评审）；
   - [5] family ledger 落账。
4. **自治边界 = 分阶段到 merge**：family 编排器跑到「家族 base + 本地 cmr 绿 + 开好 PR」即止；线上 bot cmr + merge 复用现有 pr-review-loop 的独立自治阶段。人只在 cmr 不收敛时被叫（复用 ADR 0017/0018 的升级续跑：卡点 → 返回调用端 → 拍 → resumeSession 注入）。
5. **family ledger**（家族 base worktree 的 sibling、worktree 外）记 `{已合子片 hash、当前 wave、家族 base HEAD}`；merger 每合一片即 append，崩溃重启幂等跳过已合。

## Considered Options

- **commander 自分解（LLM planner，照搬 parallel-planner Plan）**：否决——重复 `to-issues` 权威成两套真相；且 context-poor 容器切片质量差→merge 冲突地狱。
- **merger 照搬原生「整段 LLM 解任意冲突」**：否决——用户看不了 diff、cmr 是唯一承重关卡，不让 LLM 静默吞冲突；且不可重放、费额度。
- **单 run 一杆到底（含线上 bot cmr）**：否决——线上 loop 性质不同（GitHub 侧、数小时空等）且已有 pr-review-loop 工具，硬塞成脆的多小时单体。

## Consequences

- 家族 base 必须 clone-rooted（ADR 0021）；否则 fork 波次会原样重踩 prune 跨 session 互毁。
- 新增持久件：family ledger（schema 实现期定）。
- merger [1] 具体走 plain `git merge` 还是借 merge-to-head 机器 = 实现期（to-prd/TDD）定；并发 fork 安全要求子片先 distinct branch、再串行整合，故整合大概率 branch-to-branch。
- 角色 roster = coder + reviewer（沿用）+ merger（冲突 fallback soul）；commander 是 runner 代码、无 soul。
- 编排器成熟后单独立项（独立 repo）；现阶段 co-located 在 `orchestrator/`。
