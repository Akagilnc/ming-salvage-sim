Status: Accepted（2026-07-06：源于 #497/#498 实证与 #604；本地 kill-axis cmr + 线上 4-bot 收敛，PR #605 合入）

Current authority: ADR 0131 完整定义 Runner 三通道，ADR 0129 定义 findings 状态，#869 定义现行接力拓扑。本 ADR 只保留“删除 finding 内容分类”与“进程失败和 worker 主动决策门分家”两项决定。

# 0062: 删除 runner 侧 finding 分类，失败 escalate 与人类决策门分家（回归 0026/0050，supersede #448/#449 路线）

## 决定

删除按 finding 内容分类路由的整套 apparatus（`cmrClassification.ts` / `cmrFixableFindings.ts` 及 reviewer 输出中的 disposition / route 字段）。reviewer 自报 open-count，Runner 只把它当作 ADR 0131 的交通信号；现行接力只读 live #869。Runner 不查询状态库、不读取 finding 内容。进程非零退出的机械重试与 worker 主动提交的人类决策门拆成两个概念；Runner 只转运后者，不得自己合成或按下决策门。#448/#449 的 classify-defers 路线被 supersede。

**澄清「driver 不退」（2026-07-06，随 #604 slice 5 落）**：worker 主动提交 decision gate 后，run / scene / fixed position 保持可续，且不依赖 OS 进程驻留。回答后，当前席位确有已捕获、可恢复 session 时才 ordinary resume；否则保留同一 scene 并进入新的 invocation / relay。恢复与选座契约只读 #868 / #902、ADR 0128 / 0134。

**现行边界（ADR 0131）**：Runner 只读进程 exit code、reviewer 自报的 open-count，或转运 worker 主动提交的 decision gate。finding 富内容在专业 worker 间直达；Runner 不接 worker outcome JSON，不查询状态库，不核 finding id / disposition、commit / HEAD、测试或证据一致性。

## 后果

- #445 已落地的分类代码（`124419da`，经 PR #482 进 main）按 #604 删除；验收与回放测试细节见 #604。
- 韧性 epic #440 全家 issue 正文已按此口径重切（2026-07-06）；实证触发件为 #497/#498（一条 reviewer 自标 low + defer 的 finding 被死代码判成终止 10 片 family）。
