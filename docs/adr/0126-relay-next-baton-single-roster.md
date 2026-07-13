# 0126. Coder/CoderFix 换棒 = 同一张 Coder-Rec 表

Date: 2026-07-10

## Status

Accepted

## Decision

Coder/CoderFix 的资源触发（额度墙/池死/hang-with-live-pool）与专业评审 Action 声明的质量不收敛触发，共用 #767 的 `Coder-Rec: X → Y → Z` 一张表、同一顺序；编排器不设第二张 coder relay 专用 fallback 表。资源触发时多走一步 ADR 0124 的正交查池：当前模型先换活池（同模型换马甲），全池死才顺位下一模型。Reviewer / Verification 的 seat 与 relay 继续受各自 Action 的角色能力和 route 约束，不读取 Coder-Rec。

## Consequences

设计者只维护一份 coder 换人序；「平档换马甲」由池正交内建，免去 coder 的「资源换棒 vs 质量换棒」第二张表，同时不把 coder 候选误派到评审角色。
