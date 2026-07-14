Status: Accepted（2026-07-06：源于 #497/#498 实证与 #604；本地 kill-axis cmr + 线上 4-bot 收敛，PR #605 合入）

Current authority: ADR 0131 完整定义 Runner 三通道，ADR 0129 定义 findings 状态，#869 定义现行接力拓扑。本 ADR 只保留“删除 finding 内容分类”与“进程失败和 worker 主动决策门分家”两项决定。

# 0062: 删除 runner 侧 finding 分类，失败 escalate 与人类决策门分家（回归 0026/0050，supersede #448/#449 路线）

## 决定

删除按 finding 内容分类路由的整套 apparatus（`cmrClassification.ts` / `cmrFixableFindings.ts` 及 reviewer 输出中的 disposition / route 字段）。reviewer 自报 open-count：`0` 关环，`>0` 按 #869 固定拓扑派 fixer；Runner 不查询状态库、不读取 finding 内容。进程非零退出的机械重试与 worker 主动提交的人类决策门拆成两个概念；Runner 只转运后者，不得自己合成或按下决策门。#448/#449 的 classify-defers 路线被 supersede。

**澄清「driver 不退」（2026-07-06，随 #604 slice 5 落）**：worker 主动提交 decision gate 后的“不退”是 **run 语义级**——run 不落终态、不被当失败关掉、上下文不丢、始终可续；**不是 OS 进程生命周期**。实现取「退出-重入 + durable ledger 挂起」：撞决策题时进程可退出、把待答状态持久化进 ledger，人 append 答案行后重入、用原 sessionId 在原 session 原地 resume，绝不从头重跑。**长活阻塞 / 进程驻留轮询模型否**。

**现行边界（ADR 0131）**：Runner 只读进程 exit code、reviewer 自报的 open-count，或转运 worker 主动提交的 decision gate。finding 富内容在专业 worker 间直达；Runner 不接 worker outcome JSON，不查询状态库，不核 finding id / disposition、commit / HEAD、测试或证据一致性。

## 后果

- #445 已落地的分类代码（`124419da`，经 PR #482 进 main）按 #604 删除；验收与回放测试细节见 #604。
- 韧性 epic #440 全家 issue 正文已按此口径重切（2026-07-06）；实证触发件为 #497/#498（一条 reviewer 自标 low + defer 的 finding 被死代码判成终止 10 片 family）。
