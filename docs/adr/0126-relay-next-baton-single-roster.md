# 0126. Coder/CoderFix 换棒 = 同一张 Coder-Rec 表

Date: 2026-07-10

## Status

Proposed

## Decision

编排器不维护第二张 coder relay 候选表；候选与顺序只读取 ADR 0134 的固定席位。资源或 `capacity` 触发时，由 owning Action 请求下一固定席位；质量不收敛不触发换座。

## Consequences

候选与顺序只有 ADR 0134 一份真源，不另造 relay 机制或质量换座规则。
