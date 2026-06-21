# 更新日志 — Epic 编排器

本文件记录 `orchestrator/` 独立 TS 编排器的版本变更，与仓库根 `CHANGELOG.md`（Python 游戏本体）独立计版。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [0.1.0] - 2026-06-21

### 新增
- **v1 Epic 编排器（#244，子切片 #247–#256）**：把「单个 issue → AFK 自治 TDD → per-slice 已评审分支」的开发闭环编排成一条可跑的状态机。以 Sandcastle 为真 Backend（真容器 + 真 agent），完成 e2e 真容器冒烟验证。
- **三支柱设计基座**：状态机骨架（ADR 0016）、角色/Backend 边界（ADR 0017）、恢复/续跑语义（ADR 0018）。
- **10 个垂直切片全收敛**：S0–S7 状态推进、coder（Sonnet）/ reviewer（Opus）真角色、completionSignal 闸控步进、role soul 接线、push 真分支、status 汇报。
- 全链 357 单测绿（24 文件），xhigh 强度 ship-pre 跨模型评审 CLEAN。
