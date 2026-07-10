# 0126. 换棒下一棒 = 同一张 Coder-Rec 表

Date: 2026-07-10

## Status

Accepted

## Decision

资源触发（额度墙/池死/hang-with-live-pool）与质量触发（2-3 轮不收敛）的「下一棒」共用 #767 的 `Coder-Rec: X → Y → Z` 一张表、同一顺序；编排器不设第二张 relay 专用 fallback 表。资源触发时多走一步 ADR 0124 的正交查池：当前模型先换活池（同模型换马甲），全池死才顺位下一模型。

## Consequences

设计者只维护一份换人序；「平档换马甲」由池正交内建，免去「资源换棒 vs 质量换棒最佳下一棒不同」的第二张表。
