# 编排器 mainRepo 必须是独立 clone，回归 Sandcastle 原生 worktree 生命周期

Status: Proposed（2026-06-21；grill-with-docs 收敛。评审待 to-prd 之后，按 review-gate-after-to-prd 流程。）

## 背景

ADR 0017 的单片编排器把 driver 喂的 `mainRepo` 当 Sandcastle 的 `cwd` 切常驻 slice worktree。实测 driver 喂的是 `Ming_LLM-design`——主仓 `Ming_LLM` 的一条 **linked worktree**，与整个工作区共享同一个 `.git`（`git -C Ming_LLM-design rev-parse --git-common-dir` = `Ming_LLM/.git`，其下还有 hermes / sc137 / 104 / 187 等数十条活 worktree）。

Sandcastle 的隔离原语 = 在 `<cwd>/.sandcastle/worktrees/` 下 `git worktree add`，并在**每次 acquire 跑 repo 级 `pruneStale(cwd)`**（`@ai-hero/sandcastle@0.10.0` `dist/chunk-5VM5QZ26.js:25359`：先无作用域 `git worktree prune`，再对 `.sandcastle/worktrees/` 内「目录在、不在册」的条目 `rm -rf`）。它**假设独占一个仓库**。

因 `.git` 共享：Sandcastle 的 repo 级 prune（外加编排器 `realBackend.ts:1691` `cleanResidueAt` 自己重复的一条）会在「目录缺席窗口」（`/tmp/hermes-*` 这类会被 tmp 清理/容器重绑而短暂缺席的路径高发）把**别 session 的 worktree admin entry** 收割成 git-dead husk——文件留着、`git` 操作死于 `not a git repository`。跨 session、跨 owner 互毁。

上游佐证（文档/issues 优先核过）：库**无多分支 merge 原语**；#470（0.11.0 修复）= `pruneStale` 在共享/symlink `.git` 下删活树；#642（OPEN，作者承认）= 「共享 `.git` 上 repoDir 根本不可能是 branch 级隔离边界，修了也只是挪错误」。

## 决定

1. **编排器 `mainRepo` 必须是独立 clone（自有 `.git` 目录），禁止 shared-`.git` 的 linked worktree。** RealBackend 构造期 fail-closed 守卫：断言 `git rev-parse --git-common-dir` 落在 `<mainRepo>/.git`（即非 linked worktree），否则响亮报错、不启动。
2. **把 *prune* 职责交回 Sandcastle，但常驻 worktree 的存废仍归 ADR 0017、不交给 `.close()`**：① 删掉 `cleanResidueAt` 的 repo 级 `git worktree prune`（既重复 Sandcastle 自身、又危险），**保留 `reset --hard HEAD` + `clean -fd` 的片内残留清理**；② **常驻 slice / family worktree 不得用 `await using` / `.close()` 做常规清理**——Sandcastle 的 `Worktree.close()` 在 worktree 干净时 `remove()` 它（`dist/index.js` close 实现），而 ADR 0017 的常驻 worktree 是 commit 真源 + 崩溃复用真源，删了就破续跑。常驻 worktree 只在 **terminal success（不再需要 resume）** 时由显式 GC step 删除。「回归原生」仅指把 prune 交回库，**不**指把常驻 worktree 的存废交给库。
3. **闭洞靠独立 clone（决定 1），不靠版本升级。** 升 `@ai-hero/sandcastle` ≥ 0.11.0 = 一般卫生（含上游 #470「prune 删活树」修复），**非本修复关键路径**——独立 clone 让任何 prune 都够不着别 session 的 admin 命名空间，与 #470 是否修无关。#470 / #642 系 GitHub issue claim、离线不可核，标 unverified、不依赖。

## Considered Options

- **只删编排器自己的 prune**：否决——Sandcastle 的 `pruneStale` 每次 acquire 仍对 `cwd` 跑 repo 级 prune，删自己那条只降频率、不闭洞。
- **单 clone 跨 invocation 复用**：否决——多个编排器 invocation 并发（PRD A.5「同时跑多个独立 issue 的编排而互不破坏」）共享同一 clone 的 `.git` 时，对该 clone 的 repo 级 prune 仍会跨 invocation 互毁（同一个洞、降一层）。故隔离粒度 = **每个编排器 invocation 一个独立 clone**（家族 run / 单片 run 各一个），路径按 run/family id 参数化（`~/.sc-orchestrator/<repo>-iso-<runId>`）。一个 family run *内部*的所有子片 worktree 共享该 run 自己的 clone（同一 run 的活，安全）。

## Consequences

- 每 invocation 一个独立 clone（`~/.sc-orchestrator/<repo>-iso-<runId>`）即闭洞——独立 `.git` 的 prune 物理够不着别 session / 别 invocation 的 admin 命名空间（实测单 clone `main-283-iso` 对单 invocation 干净跑通；并发多 invocation 须各自 clone）。
- driver 不再能喂工作区 worktree；独立 clone 由 RealBackend 按 runId 自建并持有生命周期（实现期定）。
- 与 ADR 0017 不冲突：0017 的常驻 slice worktree 模型仍成立，只是落在独立 clone 内。本 ADR 补 0017 未写明的 `mainRepo` 拓扑前提，不修订 0017。
