Status: Proposed（2026-07-06，源于 #497/#498 实证与 #604，待 cmr + 线上评审）

# 0062: 删除 runner 侧 finding 分类，失败 escalate 与人类决策门分家（回归 0026/0050，supersede #448/#449 路线）

## 决定

runner 回归纯调度三功能——(a) worker exit 0/1 → 异常重试/正常继续，不看工作内容；(b) findings 计数 0/非 0 → 0 过、非 0 退给 coder/fixer（仅 review loop）；(c) worker 发「需人类拍板」→ 挂起 park → 决策走 durable 通道 → 答案注回原 session 原地 resume，driver 不退。据此删除按 finding 内容分类路由的整套 apparatus（`cmrClassification.ts` / `cmrFixableFindings.ts` 及 reviewer 输出中的 disposition/route 字段），任何 finding 不得由 runner 依内容终止 run；「真失败退出（escalate：infra 挂/重试耗尽）」与「人类决策门（挂起待裁后续跑）」拆为两个独立概念，不共用 escalation 一词。#448/#449 的 classify-defers 路线被 supersede——其要防的「defer 当免修后门」由「非 0 findings 必进 fix loop」这条机械规则天然堵死，不需要内容分类。

**信封宪法（收口，2026-07-06）**：runner 只读控制信封——exit code / `findings.length` / 决策门信号位——从不读信封里的字；finding 富内容（severity/位置/修法）经 landing file 在 worker 间直达 coder-fix，不经 runner 判断面；决策 payload 与人的答案对 runner 不透明，runner 纯搬运。任何「读 finding/decision 内容再分叉」的代码都是回归，删。**信封同时包含上轮 claimed-fix 的 id 覆盖校验（ADR 0030 保护保留，不随分类 apparatus 删除）**：fresh 复审输出必须按 id 枚举上轮每条 finding 的去向；这属 ADR 0050 outcome-guard 层的**按 id 在场核对**（形状校验——缺覆盖 = malformed outcome，走机械重试重派 reviewer），guard/runner 不读任何 disposition 内容。防的是「reviewer 截断/漏判输出 0 findings，把未修复的 blocking finding 假关闭」，且不越信封。

## 后果

- #445 已落地的分类代码（`124419da`，经 PR #482 进 main）按 #604 删除；验收与回放测试细节见 #604。
- 韧性 epic #440 全家 issue 正文已按此口径重切（2026-07-06）；实证触发件为 #497/#498（一条 reviewer 自标 low + defer 的 finding 被死代码判成终止 10 片 family）。
