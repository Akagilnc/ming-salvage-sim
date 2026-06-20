# 编排器的 commit 真源 = 一条常驻 slice worktree;Sandcastle sandbox 只当隔离壳;家族 base 当前置

Status: Proposed（2026-06-20；grill-with-docs 收敛 v1 编排器设计。**尚未 Accepted** —— 待设计评审闭环（本地 cmr + 线上 bot）。本 ADR 是 ADR 0016「薄质量层」的 worktree 维度具体化，收口 0016 当时含糊的 worktree 模型。）

## 背景

ADR 0016 采 Sandcastle 当底座，但其默认 `run()` + merge-to-head 模型是「每条 agent 腿一个 throwaway sandbox worktree、合回 head」。spike + hermes #222 实证：这让 **impl 的 commit 落在临时 sandbox 里、没落回家族分支的根**（40 个 worktree 堆积、子片改动蒸发）。worktree「在哪攒 commit」是 0016 没收口的洞，也是 #222 卡死处。

## 决定

**编排单切片时，commit 的真源是一条常驻的 slice worktree/分支；Sandcastle 的 sandbox 只当「跑 agent 的隔离壳」，不当「攒 commit 的地方」。**

1. **一 issue 一条常驻 worktree**：从 base 切出 slice 分支后起一条 worktree，coder 的 impl + 历轮 fix 全 commit 进它（不是每个 agent run 开新 throwaway sandbox）。
2. **base 按 issue 类型**：独立子 issue → 从默认分支（main）派生；家族子片 → 从家族 base 派生。
3. **家族 base 是前置条件，不由单片编排创建**：父 epic 立项时就有；单片编排只消费它（从它切、reviewed 后 push 子片分支）。创建 / 管理家族 base + 把子片合回它 = 后面「家族集成」层（planner / merger 角色）的事，不在单片目标内。
4. **sandbox = 隔离壳**：agent 跑在容器沙箱里，但沙箱挂的是那条 host 侧常驻 worktree（coder 读写 / reviewer 只读）；沙箱可随 run 起落，worktree 上的 commit 不随沙箱蒸发。

## Considered Options

- **照搬 Sandcastle merge-to-head（每腿一 sandbox）**：模板原样、最省接线；但 #222 实证 impl 不落回家族分支 → 否决。
- **常驻 slice worktree（本决定）**：多一点接线（host 侧 worktree + 沙箱挂载），但 commit 真源确定、不蒸发。

## Consequences

- 单片编排不碰家族 base 的创建 / 合并；那是家族层（deferred）。
- Sandcastle 具体怎么让沙箱挂 host 侧既有 worktree（而非它自己创建的那条），是实现期要验的接法。
- reviewer 只读挂同一条 worktree → 与 coder 共享被评物，但各自 fresh `run()` 上下文独立（评审独立性来自上下文、非容器边界，见 ADR 0016 Consequences v1 §reviewer）。
