# 编排器角色分离：分叉点 = Runner 派出的独立 worker

Status: Proposed

Current authority: ADR 0131 定义 Runner 三通道，#869 定义现行接力拓扑，ADR 0129 定义 findings 跨 worker 流转。本 ADR 只保留 coder / reviewer / coder-fix 角色分离。

partially-supersedes: ADR 0026 中“一条带记忆 worker 兼 reviewer/fixer、findings 不在 worker 间传”的决定；ADR 0026 的 Runner 纯调度原则仍有效。

## 决定

Coder、reviewer 与 coder-fix 必须是独立 worker / agent context。Reviewer 只负责专业判断并自报 open-count，不持久修复；fixer 验真、修复或证伪并完成自查；只有 fresh reviewer 能确认关闭或重新打开 finding。准确调用顺序与各 gate 的接力只读 #869，不在本 ADR 保存第二份流程。

跨 worker 的发现与裁定由 findings 状态库承接，不依赖任一 worker 的 session 记忆。状态库字段与写入规则归 ADR 0129；Runner 不查询状态库、不分类 finding、不比较 commit/HEAD、测试或修复证据，只处理 ADR 0131 三通道。

Integrated completeness 与 integrated correctness 同样保持为两个独立 reviewer 角色，不能被同一个会话吞成“边评边修”的内部 loop。

## 为什么

Dogfood #362 证明，把评审与修复揉进同一 session 会让 must-pass-first gate 被合并、跳过或自我合理化。结构分离用 fresh context 与可观察 findings 换掉脆弱的 in-session 自律；代价是多一次 worker 接力，但判断独立、恢复边界和审计记录更可靠。

## 后果

- Reviewer 不自修，fixer 不自报评审收敛，新角色使用独立 agent context/session。
- 专业材料交给下一位专业 worker，不成为 Runner 的裁决输入。
- 旧实现文件、模型钉死点与迁移 grep 清单属于历史实施记录，不再写入 ADR；替换/删除范围由 #863 的 census 与实施票追踪。
