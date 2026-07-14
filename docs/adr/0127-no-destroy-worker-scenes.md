# 0127. Worker 现场永不销毁（废除 fresh-restart 语义）

Date: 2026-07-10

## Status

Accepted（Owner 终审，见 issue #661 评论 2026-07-10；部分收窄 ADR 0024 决定 2）

## Decision

编排器任何 `retry` / 崩溃复用 / `resume` / `relay` 路径**不得因流程重入而销毁 worker 现场**——未提交产出与 partial commit 是劳动成果，一律接续；`reset --hard` / `clean -fd` 类清场仅允许出现在 terminal-success 后的显式 GC。ADR 0024 决定 2 中「保留 `reset --hard HEAD` + `clean -fd` 的片内残留清理」一句被本 ADR 收窄废除（0024 的独立 clone 与 prune 边界不变）。GitHub `closed` 只让该子 issue 退出当前调度，不授权立即删除已有 worktree；父流程 terminal-success + 显式 GC 前若 reopen + ready，复用原现场。唯一新增例外：owner 从父 issue 的 GitHub native sub-issues 中移除某个未合子 issue，等于明确取消**该家族子现场**：先停止未来调度；若对应 agent invocation 仍在运行，不杀进程、不删 worktree，待该实例不再运行后由 Closure/Reclamation 只删除目标 worktree；保留 branch、Lineage/ledger、日志与 telemetry/统计，不要求 success 或 normal exit，也不自动撤销已经合进父工作树的代码。该例外来自明确成员移除，不得扩张成 `close`、`retry`、`resume` 或 `relay` 清场。

## Consequences

「诚实未完成」成为合法 worker 终态（drift 保留、下一棒接续，#686 relay 承接）；#600 归档的防御式重试（archive/600-defensive-retry-preserved）按本决定不再复活。
