Status: Proposed

Current authority: 线上评审仍属于编排器 shared tail；准确顺序只读 #869，Runner 边界只读 ADR 0131。PR / checks / threads 的读取与外部效果核验分别属于 Online Review、Ship / PR Publication 与 Merge / Delivery 等具名 Action，不属于 Runner。

# 0061: 编排器纳入线上 PR 评审 loop（反转 ADR 0022 旧版“自治止于 PR”条款）

历史文件名中的 `d4` 只记录 ADR 0022 旧版条款编号，不指现行 ADR 0022 的决定 4。

## 背景

ADR 0022 旧版“自治止于 PR”条款规定：family 编排器跑到“家族 base + 本地 CMR 绿 + 开好 PR”即止，线上 bot CMR + merge 复用现有 pr-review-loop 的独立自治阶段。该“独立自治阶段”至今靠人或不稳定的 subagent 手动驱动——dogfood 曾出现无 cap 强制下滚到 7 轮、把干净小修啃成自伤大改写的事故；本项目一次真实 PR（#589）的线上评审 loop 也是全程人工手动执行（轮询 4 bot、判 finding、修、resolve 线程、3 轮上限、查 ruleset 合并）。这段本身是确定性流程，恰是编排器（Runner = 纯调度器）的本职，不该继续外包给人/漂移的 subagent。

## 决定

反转 ADR 0022 旧版“自治止于 PR”条款：**线上评审 loop 纳入编排器自身**，成为 ship 开出 PR 后由单切片与 family 共用的 shared-tail segment；该 segment 由相互独立的具名 Action / worker 接力，不按来源分叉。编排器的自治边界从“止于 PR”推进到“止于 merge”。

**决策要点**（详见 #366 PRD，编码细节归 to-issues 切片）：

1. Online Review Action 读取 reactions / reviews / checks / threads 并完成专业判断；Ship / PR Publication 与 Merge / Delivery 分别核验自己拥有的 push、PR 与最终 merge 副作用。修复、Verification、finalization 与 fresh review 的准确接力只读 #869。Runner 不读取 PR 状态或 finding 内容，只按 ADR 0131 三通道与 #869 固定拓扑调度。
2. 单切片 PR 与 family PR 共用同一 shared-tail segment 与 Action implementations，不按来源分叉设计；这不表示多个角色合并成同一 worker。
3. 不设"强证据/弱证据分级→人工升级"机制；verify-worker（强模型）自主判定，fresh review loop 可自纠错，真卡住走既有通用升级通道，不另建专用 defer 机制。
4. Merge / Delivery Action 核验 ruleset、线程与 CI 等客观条件后自动合并，不额外加人工确认闸；这些外部事实不进入 Runner。

## Considered Options

- **维持现状（线上 loop 留在编排器外，人/subagent 手动驱动）**：否决——确定性流程交给会漂的 agent/人手动执行，已出过无 cap 失控的事故，且编排器本职就是这类确定性调度。
- **verify 和 fix 合并成一个 worker（省一次派发）**：否决——违反项目已守护的 reviewer/coder 角色边界（`cmrReviewerHeadMovedStopSummary`），且判断与动手改混在一起会有自我合理化偏差，出问题也难排查是判断错还是改错。
- **给 verify-worker 的拒绝加"强证据/弱证据"分级、弱证据必须升级人工**：否决——过度设计，defer 之后照样要重跑；fresh review loop、强模型与既有升级通道已经够用。
- **合并前插一道人工确认**：否决——ruleset/线程/CI 这些客观条件本身就是闸；真出问题分支保护 + revert 还兜得住，符合"止于 merge"的本意。

## Consequences

- 反转 ADR 0022 旧版“线上 loop 是独立自治阶段”的表述；`wiki/concepts/pr-review-loop.md` 只保留 bot 操作方法与人工流程参考，编排器的调用顺序、修复重入、fresh review 与收敛条件只读 #869。
- 新增 worker 角色边界要求：verify（判断，只读）与 fixer（改代码+自查二连）必须是两个**分离的 worker 派发**——runner 只负责调度派发，「修/拒/延」判断全部发生在 verify worker 内（runner 不做判断，见 ADR 0062 / 0129 三态宪法）；不可合一，verify-worker 复核同样要求 fresh（不带上一轮 session）。Family merge 后的构建/测试同样由 Verification / Objective Gate Action 执行并交卷；Runner 只按 #869 调用该 Action、读取其自报 open-count，不执行或解释测试。
- 编码细节（worker contract 形状、promptFile 内容、轮询间隔/give-up 策略、跟 #440/#590/#592 的关系）留给 to-issues 切片定，本 ADR 只定边界与角色分工要求。
