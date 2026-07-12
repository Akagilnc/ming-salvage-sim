Status: Accepted（2026-07-06：源于 #497/#498 实证与 #604；本地 kill-axis cmr + 线上 4-bot 收敛，PR #605 合入）

> **前向更正（ADR 0129，2026-07-12 owner 重申）**：三通道保留，但 runner 不再消费 worker outcome JSON，也不做 finding id/disposition、commit/head、测试或证据一致性校验。信号②直接查询 findings 状态库未决数；专业判断和材料核验留在 reviewer/fixer 之间。

# 0062: 删除 runner 侧 finding 分类，失败 escalate 与人类决策门分家（回归 0026/0050，supersede #448/#449 路线）

## 决定

runner 回归纯调度三功能——(a) worker exit 0/1 → 异常重试/正常继续，不看工作内容；(b) findings 计数 0/非 0 → 0 过、非 0 退给 coder/fixer（仅 review loop）；(c) worker 发「需人类拍板」→ 挂起 park → 决策走 durable 通道 → 答案注回原 session 原地 resume，driver 不退。据此删除按 finding 内容分类路由的整套 apparatus（`cmrClassification.ts` / `cmrFixableFindings.ts` 及 reviewer 输出中的 disposition/route 字段），任何 finding 不得由 runner 依内容终止 run；「真失败退出（escalate：infra 挂/重试耗尽）」与「人类决策门（挂起待裁后续跑）」拆为两个独立概念，不共用 escalation 一词。#448/#449 的 classify-defers 路线被 supersede——其要防的「defer 当免修后门」由「非 0 findings 必进 fix loop」这条机械规则天然堵死，不需要内容分类。

**澄清「driver 不退」（2026-07-06，随 #604 slice 5 落）**：(c) 的「driver 不退」是 **run 语义级**——run 不落终态、不被当失败关掉、上下文不丢、始终可续；**不是 OS 进程生命周期**。实现取「退出-重入 + durable ledger 挂起」：撞决策题时进程可退出、把待答状态持久化进 ledger，人 append 答案行后重入、用原 sessionId 在原 session 原地 resume，绝不从头重跑。**长活阻塞 / 进程驻留轮询模型否**。三个内证：拍板句里「决策走 durable 通道」本身排除内存阻塞（要阻塞在内存等，就不需要 durable）；「不退」的对举对象是同段「真失败退出」而非进程退出；全项目无一处靠「进程驻留」保状态（同 ADR 0008 delta ready=1、崩溃断点续跑、从不依赖进程活着）。

**信封宪法（收口，2026-07-06）**：runner 只读控制信封——exit code / `findings.length` / 决策门信号位——从不读信封里的字；finding 富内容（severity/位置/修法）经 landing file 在 worker 间直达 coder-fix，不经 runner 判断面；决策 payload 与人的答案对 runner 不透明，runner 纯搬运。任何「读 finding/decision 内容再分叉」的代码都是回归，删。**信封同时包含上轮 claimed-fix 的 id 覆盖校验（ADR 0030 保护保留，不随分类 apparatus 删除）**：fresh 复审输出必须按 id 枚举上轮每条 finding 的去向；这属 ADR 0050 outcome-guard 层的**按 id 在场核对**（形状校验——缺覆盖 = malformed outcome，走机械重试重派 reviewer），guard/runner 不读任何 disposition 内容。防的是「reviewer 截断/漏判输出 0 findings，把未修复的 blocking finding 假关闭」，且不越信封。

**澄清：typed-字段治理派生信封 vs 自由文本命运分叉（2026-07-06，用户拍，随 #604 ship-pre cmr 落）**：网关 / outcome-guard 层**可**做 typed 字段的形状与治理校验（claimed-fix id 在场核对、`dispositionKind` + `hasAcceptedSuppressionAuthority` 核验）并**由此派生信封计数**——这是 0030 / 0050 例外的同族，**intended**（accepted-suppression 治理是有意保留的规格要求，非要删的 apparatus）。红线是：**不得读 finding 自由文本（`claim_quote` / `suggested_fix` 等描述）做任何命运分叉**；**富内容不得驻留 runner 侧派发结构**（`DispatchContext` 只带 identity keys + 计数，富内容走 landing file）。把治理校验挪进被守护的 reviewer worker=被守护者自守（reviewer 自宣 accepted → 自吐 findings.length=0 → 闸空转，同 #330 verification-scope-vacuum），故 outcome-guard 必须在 worker 之外的 runner 层（0050 立法理由）——这与「删除按内容路由的 apparatus」不矛盾：杀的是读散文做分叉，留的是读 typed 信号位做形状/治理校验。

## 后果

- #445 已落地的分类代码（`124419da`，经 PR #482 进 main）按 #604 删除；验收与回放测试细节见 #604。
- 韧性 epic #440 全家 issue 正文已按此口径重切（2026-07-06）；实证触发件为 #497/#498（一条 reviewer 自标 low + defer 的 finding 被死代码判成终止 10 片 family）。
