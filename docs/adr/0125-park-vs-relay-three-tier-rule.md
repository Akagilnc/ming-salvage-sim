# 0125. 额度墙处置：park vs 换棒三段式

Date: 2026-07-10

## Status

Proposed

## Decision

worker 撞额度墙（#683 探针 429，带 `resetAt`）时三段式裁决：①同一可执行席位的 quota reset 在阈值 T 内，保留现场等待；②超 T 且 ADR 0134 固定席位顺序仍有下一候选，owning Action 交棒到下一席位；③固定候选耗尽，保留现场并走既有 decision gate，不静默 park。T 可配置，默认 30 分钟。

## Consequences

Issue #683 的 quota park 与 #686 的 relay 在同一处置点分叉：短窗口等待同一席位，长窗口沿固定顺序交棒，候选耗尽则保留现场并进入既有 decision gate；判据机械可测，不留模型自由裁量。
