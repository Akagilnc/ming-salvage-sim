Status: Accepted（2026-07-06：grill 收敛 #366 → 16-issue 重切 → 本地 kill-axis cmr 2 轮收敛 → 线上 4-bot 3 轮收敛，PR #605 合入）

# 0061: 编排器纳入线上 PR 评审 loop（反转 ADR 0022 decision 4）

## 背景

ADR 0022 decision 4 定「自治边界 = 分阶段到 PR：family 编排器跑到『家族 base + 本地 cmr 绿 + 开好 PR』即止；线上 bot cmr + merge 复用现有 pr-review-loop 的独立自治阶段」。该"独立自治阶段"至今靠人或不稳定的 subagent 手动驱动——dogfood 曾出现无 cap 强制下滚到 7 轮、把干净小修啃成自伤大改写的事故；本项目一次真实 PR（#589）的线上评审 loop 也是全程人工手动执行（轮询 4 bot、判 finding、修、resolve 线程、3 轮上限、查 ruleset 合并）。这段本身是确定性流程，恰是编排器（runner=纯调度器）的本职，不该继续外包给人/漂移的 subagent。

## 决定

反转 ADR 0022 decision 4：**线上评审 loop 纳入编排器自身**，成为 ship worker 开出 PR 之后统一接管的一个 worker 阶段（单切片 PR 与 family PR 共用同一套逻辑，不分叉）。编排器的自治边界从「止于 PR」推进到「止于 merge」。

**决策要点**（详见 #366 PRD，编码细节归 to-issues 切片）：

1. 轮询 bot 状态（reactions/reviews/checks/threads）是 host 侧确定性调度（runner 职责）；但"这条 finding 该修/该拒/该延"必须由 worker 读实际代码判断，runner 不猜。延续 ADR 0030 已立的收敛 loop 模型：**fresh verify-worker 核实 → fixer-worker 改+自查二连 → fresh verify-worker 复核**，不塞进一个 worker 兼两职（镜像 `cmrReviewerHeadMovedStopSummary` 已守护的 reviewer/coder 角色边界）。
2. 单切片 PR 与 family PR 共用同一套 worker/skill，不按来源分叉设计。
3. 不设"强证据/弱证据分级→人工升级"机制；verify-worker（强模型）自主判定，判错是可接受的小概率成本（线上评审本身 3 轮、可自纠错），真卡住走既有通用升级通道，不另建专用 defer 机制。
4. ruleset/线程 resolved/CI 等客观条件满足即自动合并，不额外加人工确认闸。

## Considered Options

- **维持现状（线上 loop 留在编排器外，人/subagent 手动驱动）**：否决——确定性流程交给会漂的 agent/人手动执行，已出过无 cap 失控的事故，且编排器本职就是这类确定性调度。
- **verify 和 fix 合并成一个 worker（省一次派发）**：否决——违反项目已守护的 reviewer/coder 角色边界（`cmrReviewerHeadMovedStopSummary`），且判断与动手改混在一起会有自我合理化偏差，出问题也难排查是判断错还是改错。
- **给 verify-worker 的拒绝加"强证据/弱证据"分级、弱证据必须升级人工**：否决——过度设计，defer 之后照样要重跑；线上评审本身 3 轮就有自纠错能力，强模型+既有升级通道已经够用。
- **合并前插一道人工确认**：否决——ruleset/线程/CI 这些客观条件本身就是闸；真出问题分支保护 + revert 还兜得住，符合"止于 merge"的本意。

## Consequences

- 反转 ADR 0022 decision 4"线上 loop 是独立自治阶段"的表述；线上 pr-review-loop 的 wiki 流程本身不变（wiki/concepts/pr-review-loop.md 仍是权威），只是执行者从人/subagent 变成编排器 worker。
- 新增 worker 角色边界要求：verify（判断，只读）与 fixer（改代码+自查二连）必须是两个**分离的 worker 派发**——runner 只负责调度派发，「修/拒/延」判断全部发生在 verify worker 内（runner 不做判断，见 ADR 0062 信封宪法）；不可合一，verify-worker 复核同样要求 fresh（不带上一轮 session）。此处的 verify worker 与 ADR 0026「merge 非均匀 worker」段的 verify-fail-fast（family merge 队列的构建/测试校验，属 runner 调度职责）是两个不同概念，勿混。
- 编码细节（worker contract 形状、promptFile 内容、轮询间隔/give-up 策略、跟 #440/#590/#592 的关系）留给 to-issues 切片定，本 ADR 只定边界与角色分工要求。
