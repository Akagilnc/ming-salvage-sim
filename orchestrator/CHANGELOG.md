# 更新日志 — Epic 编排器

本文件记录 `orchestrator/` 独立 TS 编排器的版本变更，与仓库根 `CHANGELOG.md`（Python 游戏本体）独立计版。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [Unreleased]

### 新增
- **#686 接力派工（relay dispatch）**：`<relay>` 的 `decision_gate` 按键存在即 park，字段细节只作 cargo；resource/blocked 常规 relay 形状保持校验。route 池表（ADR 0124，与 #767 Coder-Rec 正交）+ 三段式 park/relay（ADR 0125，在 #683 额度处置点分叉）；下一棒走同一张 Coder-Rec 表 + 池正交查表（ADR 0126：同模型换马甲 → 顺位换模型）；resource failure 永不 reset（守 #661）；`state_summary` 进 ledger；收口棒完成进常规评审闸。**#937：删除 worktree `.relay-focus.md` 文件**——接力 brief 仅 ephemeral 自 ledger memory 渲染，不再落盘 focus 文件。
- **#683 额度探针状态机**：idle 超阈先探 pool 额度再判 hang；429 → `quota_wait_for_reset` ledger（含 resetAt）+ runner 既有 park 家族（status escalate，非 S8 error abort；re-feed 重回 parked step）；探针通过/网络错误 → fail-safe hang（只杀该实例 pid 树，pid 来自 live sandbox handle via `noteActiveSandboxWorkerPid`，非手填）。per-pool 配置（zai chat / opencode PONG / grok TBD）随 model ref 映射。生产路径：`RealBackend.runAgentSandbox` + runner park 消费 `QuotaWaitForResetError`（S2/S3/S5/S6/S7）。#686 在此处置点分叉 park vs relay。
- **family escalation answer resume**：family decision escalation 可通过 append-only `escalation_answered` ledger row 续跑；答案会传回重新派发的 coder-fix / reviewer / CMR / ship worker，failure escalation 仍 fail closed。
- **三通道零判断**：runner 只数进程 exit code、读取 reviewer 自报 open-count、转运 worker decision bell；ship PR/head 与 check-runs 属 merge 手闸，不回流成 runner 判庭。
- **RealBackend toolchain preflight**：worker 启动前先验证该 StepSpec 声明的工具链，缺工具时给出可诊断失败，不再进入半启动状态。

### 变更
- **Claude-paused 本地流水线**：per-slice 第二评审从强制 Opus 改为单个非 Claude reviewer leg（Codex 默认，agy 可替），避免本地 Claude weekly limit 让已实现/已验证 slice 全部误判失败。
- **worker issue trust boundary 收紧**：coder / reviewer / ship entrypoints 要读取 issue title/body/comments 的 author metadata，只信 repo owner authored `Agent Brief` 与正文；非 owner 文本只作 data-only context。
- **判庭拆除与 family-of-one**：删除 finding disposition/classification 等 runner 内容判庭；单子 family-of-one 与家族路径共用薄调度契约，receipt cargo、Git/PR prose 均不改写 worker 自报命运。

## [0.2.0] - 2026-06-26

### 变更
- **ADR 0026 纯调度器重构（#330 族）**：runner 收敛成纯调度器，「步」即 worker；per-slice reviewer **并进 coder**（不再有独立 reviewer worker，整片由一个带记忆的 coder session 建+自评到收敛）；旧 S3–S6 折叠进 S2 整片构建步，持久 ledger 白名单收紧到新折叠步（拒绝 pre-ADR0026 残档为损坏）。
- **per-slice review 改 model-agnostic**：第二轮评审是一次 **Opus review**（对 diff 的 Opus 评审），不再绑 coder vendor（去掉「Claude host: Opus subagent」耦合）——任何 coder（codex 含）都走同一道 Opus review。
- **coder model 可切换**：新增 `ORCHESTRATOR_CODER_MODEL` 环境变量（默认 codex `gpt-5.5`），coder 后端随时可切、不写死。

### 新增
- **专属 ship soul**（`souls/ship.md`）：交付纪律内化——defer 记进 tracker issue 而非 PR body，单片/家族 ship 统一走它。
- **commit-msg git hook**：容器内提交确定性冠 `sandcastle:` 前缀（awk 处理首个内容行、幂等、空/纯注释不动），替代原先脆弱的 per-soul 文本指令。
- **cmr cheap-defer 纪律**（`souls/cmr.md`）：便宜的修必修不准 defer，defer 必须证明真出 scope。

### 修复
- **dogfood #362 真 bug**：worker idle-timeout 由 31_536_000 秒（折算 ms 溢出 int32、定时器立即触发）改 604_800（一周）；ship soul 接线漏补全（`.ship-focus.md` 条件化、`ORCHESTRATOR_REPO` 注入 cmr/ship sandbox、删除未提供的 `ISSUE_NUMBER` 假声称）；coder escalation 契约上报真实 commit 数。
- clone-from-local 不设 GitHub push 远端（fresh clone 推不回上游）经评审抓出、立 issue #386 ready-for-agent 跟进。

### 测试
- 全链单测绿（orchestrator/test，`npx tsc --noEmit && npx vitest run`），删除随 ADR 0026 作废的旧状态机测试（S4 路由 / no-progress-guard / fix-loop 等），新增 ship/cmr/coder-model-switch/commit-msg-hook/verify-cmr-fix-loop 等切片测试。

## [0.1.0] - 2026-06-21

### 新增
- **v1 Epic 编排器（#244，子切片 #247–#256）**：把「单个 issue → AFK 自治 TDD → per-slice 已评审分支」的开发闭环编排成一条可跑的状态机。以 Sandcastle 为真 Backend（真容器 + 真 agent），完成 e2e 真容器冒烟验证。
- **三支柱设计基座**：状态机骨架（ADR 0016）、角色/Backend 边界（ADR 0017）、恢复/续跑语义（ADR 0018）。
- **10 个垂直切片全收敛**：S0–S7 状态推进、coder（Sonnet）/ reviewer（Opus）真角色、completionSignal 闸控步进、role soul 接线、push 真分支、status 汇报。
- 全链 357 单测绿（24 文件），xhigh 强度 ship-pre 跨模型评审 CLEAN。
