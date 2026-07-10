# 0124. 池 = 配额/账单边界，与模型花名册正交

Date: 2026-07-10

## Status

Accepted

## Decision

编排器的「池」定义为**配额/账单边界**（grok-build 订阅、Cursor 订阅、zai key、codex 5h 窗各为一池），模型是池内商品——同一模型可住多个池（实证：grok-4.5 在 grok-build 402 后经 Cursor 池接续）。route 池表按池记状态（额度/`resetAt`），#767 花名册按模型记能力序，两表正交：选人先按 Coder-Rec 序选模型，再查该模型在哪个池有活额度。

## Consequences

池死不等于模型不可用（先换马甲再顺位换人）；池表与花名册各自演化互不耦合。
