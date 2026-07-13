---
status: accepted
supersedes-part-of: ADR 0018 (step 分类); ADR 0016 (spike 发现4 的 cmr/gstack 不进容器排除)
partially-superseded-by: ADR 0030; ADR 0131; issue #869
---

# 编排器 Runner = 纯调度器；专业步骤由 worker / Action 完成

## Current authority

- #869 单一拥有现行 issue→merge 交付拓扑。
- ADR 0131 单一拥有 Runner 三通道与零判断权。
- ADR 0030 单一拥有 reviewer / fixer 角色分离。

本 ADR 只保留一个架构决定：**专业工作不得内联进 Runner，必须由对应 worker / Action 完成。** 下文旧版曾规定的 S0–S8、终态 output、promptFile、单 session 收敛、ledger 路由、merge 特例与容器细节均已废止，不得作为现行实现依据。

## Decision

1. 写码、验证、评审、修复、合并、ship、线上评审、文档发布与清理，分别由拥有该专业能力和外部副作用的 worker / Action 完成。
2. Runner 只在 #869 的固定位置调用这些 Action，并且只处理 ADR 0131 的三种交通信号：进程 exit code、reviewer 自报 open-count、worker 主动提交的 decision gate。
3. Runner 不读取 worker 的终态报告、输出格式、findings、测试、commit、HEAD、diff、PR 或其他完成证据，也不内联任何 Action 的专业方法。
4. issue、worktree、image / soul / skill、Lineage 与外部服务各自由其专业所有者读取或维护；Runner 不把这些材料重新解释成第四种交通信号。
5. worker 只完成当前角色，不自行跨到下一角色；准确接力只读 #869。

## Why

ADR 0018 最初让 Runner 控制外层顺序，却同时把 push、CMR、ship 等专业行为写成 Runner 内联步骤，导致 Runner 手搓 skill 的近似实现并不断扩大判断权。实证已证明，容器内的顶层 worker 可以调用真实 skill 与模型腿；因此应让专业步骤回到 worker / Action，让 Runner 保持纯交通调度。

## Consequences

- `ak-cross-m-review`、`gstack-ship` 等方法由对应 Action / worker 调用，Runner 不复制其流程。
- reviewer 与 fixer 的分离、fresh review 纪律由 ADR 0030 保留；具体顺序只在 #869 出现。
- scene identity、locator 与 live handle 的找回/重连归 Execution Capsule / Lineage 与 Scene Provisioning / Recovery；既有 scene 内的 worker 进程、当前角色 session、重试与 relay 归 Worker Invocation；merge reconciliation 与外部效果核验归对应 Action。本 ADR 不再规定实现细节。
- 旧 prompt/output/ledger 机制只能作为 Git 历史背景，不能成为兼容目标或新实现验收依据。
