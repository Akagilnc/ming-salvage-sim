Status: Proposed

# 0136: Runner 控制面与公开结果 ABI 原子切换

## 决定

Runner 固定为只负责调度与 durable 记录的交通控制面；业务事实的解释与 side effects 归对应 Action、Flow 或 worker，详细契约唯一引用 live #934。

公开结果与 OS code 按 #934 ID-001 原子切换，不保留旧结果、旧终态映射或双轨兼容；实现顺序与删除约束只读 #935～#942 的 live `Blocked by` 和 #934 ID-016。

## Supersession

本 ADR Accepted 时 forward-supersede ADR 0131，并取代 closed #929 中与 #934 ID-001、ID-006 冲突的旧 completion、terminal 与退出码契约；历史 ADR 与 issue 不回改。

## 后果

#934 是实现细节的唯一真源；本 ADR 与子票不复制其定义、流程或规则。
