Status: Accepted（2026-07-06：源于 #497/#498 实证与 #604；本地 kill-axis cmr + 线上 4-bot 收敛，PR #605 合入）

# 0062: 删除 runner 侧 finding 分类，失败 escalate 与人类决策门分家（回归 0026/0050，supersede #448/#449 路线）

## 决定

runner 回归纯调度三功能——(a) worker exit 0/1 → 异常重试/正常继续，不看工作内容；(b) 查询 findings 状态库未决数：0 过、非 0 退给 coder/fixer（仅 review loop）；(c) worker 发「需人类拍板」→ 挂起 park → 决策走 durable 通道 → 答案注回原 session 原地 resume，driver 不退。据此删除按 finding 内容分类路由的整套 apparatus（`cmrClassification.ts` / `cmrFixableFindings.ts` 及 reviewer 输出中的 disposition/route 字段），任何 finding 不得由 runner 依内容终止 run；「真失败退出（escalate：infra 挂/重试耗尽）」与「人类决策门（挂起待裁后续跑）」拆为两个独立概念，不共用 escalation 一词。#448/#449 的 classify-defers 路线被 supersede——其要防的「defer 当免修后门」由「非 0 findings 必进 fix loop」这条机械规则天然堵死，不需要内容分类。

**澄清「driver 不退」（2026-07-06，随 #604 slice 5 落）**：(c) 的「driver 不退」是 **run 语义级**——run 不落终态、不被当失败关掉、上下文不丢、始终可续；**不是 OS 进程生命周期**。实现取「退出-重入 + durable ledger 挂起」：撞决策题时进程可退出、把待答状态持久化进 ledger，人 append 答案行后重入、用原 sessionId 在原 session 原地 resume，绝不从头重跑。**长活阻塞 / 进程驻留轮询模型否**。三个内证：拍板句里「决策走 durable 通道」本身排除内存阻塞（要阻塞在内存等，就不需要 durable）；「不退」的对举对象是同段「真失败退出」而非进程退出；全项目无一处靠「进程驻留」保状态（同 ADR 0008 delta ready=1、崩溃断点续跑、从不依赖进程活着）。

**三态宪法（ADR 0129 收口）**：runner 只看未决 findings 为 0、未决 findings 大于 0、需要人类决定。finding 富内容在专业 worker 间直达；状态合法性由状态库写入点校验。runner 不接 worker outcome JSON，不核 finding id/disposition、commit/head、测试或证据一致性。

## 后果

- #445 已落地的分类代码（`124419da`，经 PR #482 进 main）按 #604 删除；验收与回放测试细节见 #604。
- 韧性 epic #440 全家 issue 正文已按此口径重切（2026-07-06）；实证触发件为 #497/#498（一条 reviewer 自标 low + defer 的 finding 被死代码判成终止 10 片 family）。
