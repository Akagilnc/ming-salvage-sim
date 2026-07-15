# 编排器的 commit 真源 = 一条常驻 slice worktree;Sandcastle sandbox 只当隔离壳;家族 base 当前置

Status: Proposed

Current authority: 本 ADR 只保留“每个 slice 使用一条常驻 worktree/分支承载劳动与 commit”的决定。commit 创建归 #868 的 Change Finalization Action，接力顺序只读 #869；base/scene 与恢复、回收分别只读 ADR 0022/#871 与 ADR 0127。下文 v0.1 base、step ledger 与同镜像细节仅为历史。

## 背景

ADR 0016 采 Sandcastle 当底座，但其默认 `run()` + merge-to-head 模型是「每条 agent 腿一个 throwaway sandbox worktree、合回 head」。spike + hermes #222 实证：这让 **impl 的 commit 落在临时 sandbox 里、没落回家族分支的根**（40 个 worktree 堆积、子片改动蒸发）。worktree「在哪攒 commit」是 0016 没收口的洞，也是 #222 卡死处。

## 决定

**编排单切片时，commit 的真源是一条常驻的 slice worktree/分支；Sandcastle 的 sandbox 只当「跑 agent 的隔离壳」，不当「攒 commit 的地方」。**

1. **一 issue 一条常驻 worktree**：从 base 切出 slice 分支后起一条 worktree；Implementation / Finding Repair 的劳动留在这里，所有 baseline 与 review-fix commit 由 Change Finalization Action 创建在这里，而不是由 coder 自行提交或让每个 agent run 新开 throwaway sandbox。若该 issue 的 scene/worktree 已存在则复用，不重切。
2. **base 按 issue 类型**：独立子 issue → 从默认分支（main）派生。**v0.1 对放行的「有父」叶子也一律当独立片处理：从 main 派生（v0.1 传话筒只传 issue 号、不接 base 参数），不按有无父区分 base**（「父 = 多个子，做通一个子即做父的一部分」；家族 base 派生 + 子片合回家族 = 家族层 deferred，见 ADR 0016 v1「输入只收单个实现切片」bullet + PRD #244 输入闸）。v0.1 输入闸只挡父 issue（有子）/ 未切 PRD epic / 非 rfa / **有未关 blocked_by 依赖**，不挡「有父叶子」。
3. **家族 base = 家族层（v0.1 deferred）不变式，v0.1 单片编排不消费它**：v0.1 单片**从 main 切**（§2），此刻**不从家族 base 派生、不读它**；家族 base 的创建 / 管理 + 把子片合回 = 后面「家族集成」层（planner / merger 角色）的事，不在单片目标内（与 §2「从 main 派生」一致——不再写「单片只消费家族 base」）。
4. **sandbox = 隔离壳**：agent 跑在容器沙箱里，沙箱挂那条 host 侧常驻 worktree；沙箱可随 run 起落，worktree 上的 commit 不随沙箱蒸发。**v1 一镜像下 coder 与 reviewer 跑在同一 sandbox／同一 worktree mount，reviewer 的「只读」靠 reviewer soul 软约束（烤进镜像的 reviewer soul 里写 READ-ONLY 硬约束；不引用 cmr skill 的 `cmr-reviewer.md`——那在 ak-cross-m-review skill 里、不在编排器仓库）强制，不是 OS 级只读挂**；OS 级 coder-rw／reviewer-ro 分挂只在 reviewer 拆成独立镜像／独立 sandbox 时才成立（可逆，见 ADR 0016 v1「一个镜像、双角色」bullet）。

## Considered Options

- **照搬 Sandcastle merge-to-head（每腿一 sandbox）**：模板原样、最省接线；但 #222 实证 impl 不落回家族分支 → 否决。
- **常驻 slice worktree（本决定）**：多一点接线（host 侧 worktree + 沙箱挂载），但 commit 真源确定、不蒸发。

## Consequences

- 单片编排不碰家族 base 的创建 / 合并；那是家族层（deferred）。
- worktree 用 Sandcastle 原生 `createWorktree()`（first-class、持久跨 `run/interactive/createSandbox`）；coder/reviewer 经 `Worktree.createSandbox()` 在同一持久 worktree 上跑——常驻 worktree 模型 Sandcastle 原生支持，不用自定义接线。
- reviewer 与 coder 共享被评物（同一 worktree），各自 fresh `run()` 上下文独立（评审独立性来自上下文、非容器边界，见 ADR 0016 v1「一个镜像、双角色」bullet）；v1 reviewer 只读靠 prompt/soul（决定 4），非 OS 挂载。
- 状态、scene locator 与恢复不由本 ADR 定义；现行所有权只读 #867/#871。常驻 worktree 只承载该 slice 的工作现场与 Change Finalization 产生的 commit。
