Status: Proposed

# 0132: 先收敛唯一交付主流程，再考虑流程语言

## 背景

现有编排器已经基本拥有一条交付路线，当前问题是重复实现与 runner 越权，而不是真实存在多条流程需要抽象。

## 决定

#863 第一阶段只重构唯一的 issue→merge 交付主流程，并以 ADR 0131 约束 runner；通用 Role Workflow Definition、DSL 与运行时 admission validator 延后到真实第二条流程出现后再设计。

## 后果

本 ADR 只确定架构方向，不复制完整流程细节；拓扑与流程验收留在 #869，动作边界留在 #868，实现验收留在各实施票。
