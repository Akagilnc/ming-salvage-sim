# 0127. Worker 现场永不销毁（废除 fresh-restart 语义）

Date: 2026-07-10

## Status

Accepted（Owner 终审，见 issue #661 评论 2026-07-10；部分收窄 ADR 0024 决定 2）

## Decision

编排器任何路径（mechanical retry / 崩溃复用 prepareWorktree / resume / relay）**不得销毁 worker 现场**——未提交产出与 partial commit 是劳动成果，一律接续；`reset --hard` / `clean -fd` 类清场仅允许出现在 terminal-success 后的显式 GC。ADR 0024 决定 2 中「保留 reset --hard HEAD + clean -fd 的片内残留清理」一句被本 ADR 收窄废除（0024 的独立 clone 与 prune 边界不变）。读取/比对 HEAD 合法且必要（resume 检测、fix 追踪）；差异处置 = 报告并交下一步判断，永不销毁。

## Consequences

「诚实未完成」成为合法 worker 终态（drift 保留、下一棒接续，#686 relay 承接）；#600 归档的防御式重试（archive/600-defensive-retry-preserved）按本决定不再复活。
