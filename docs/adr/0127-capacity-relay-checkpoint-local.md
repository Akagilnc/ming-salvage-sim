# 0127. 模型拥挤按 checkpoint 换棒

Date: 2026-07-11

## Status

Accepted

## Decision

服务端 capacity/拥挤（非 429 quota）是 relay 的第四触发：立即保留现场并重派；先在当前 live billing pool 按 Coder-Rec 顺位换 checkpoint，无同池候选才回退既有跨池 relay，不 park 等配额窗，也不把池判死。

## Consequences

ledger 的 handoff trigger 记为 `capacity`，使其与 quota_wall、hang_with_live_pool、自报 blocked 可区分。
