# 0133. capacity 客观失败 → 下一固定席位

Date: 2026-07-11

## Status

Proposed

## Decision

Coder/CoderFix 遇到服务端 `capacity`/拥挤（非 429 `quota`）时保留现场；这是客观执行故障，由 owning Action / Policy 按 ADR 0134 选择下一固定席位。不判池死、不等 quota window，也不设同池 checkpoint 特例。

## Consequences

用现行 owner-scoped records/telemetry 记录 `capacity`，使其与 `quota` 等其他执行状态可区分；旧 ledger 不作为权威。
