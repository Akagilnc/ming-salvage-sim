> **修订（2026-07-15，#925 落地）**：S4 机械分类站措辞更新——S4 溶解为判官
> 判词三态（ADR 0132）；有序双闸（completeness→correctness）保留、各庭各判、
> 关环判词化（family 第二台数数机删除随 #930）。

# 编排器角色分离：分叉点 = Runner 派出的独立 worker

Status: Proposed

Current authority: ADR 0131 定义 Runner 三通道（含判词三态），#869 定义现行
接力拓扑，ADR 0129 定义 findings 跨 worker 流转，ADR 0132 定义判官化。本 ADR
只保留 coder / judge(verify) / coder-fix 角色分离与 fresh 审卷腿纪律。

partially-supersedes: ADR 0026 中“一条带记忆 worker 兼 reviewer/fixer、findings
不在 worker 间传”的决定；ADR 0026 的 Runner 纯调度原则仍有效。

## 决定

Coder、判官（verify 工位）与 coder-fix 必须是独立 worker / agent context。

- **判官**（S3 建庭、S6 resume 同一 session）派 **fresh** 审卷 subagent 腿
  （reviewer soul 全文拼腿 prompt 头）；按四理由毙单后仅活单送修；以判词三态
  `converged | continue | escalate` 裁决收敛。
- **S4 机械分类站已溶解**：不再存在 runner 侧 open-count / 轮数阈值分类站；
  收敛判断权在判官判词。
- **coder-fix** 验真、修复或证伪并完成自查；只有 fresh 审卷腿 + 判官终翻
  能确认关闭或重新打开 finding。
- 准确调用顺序与各 gate 的接力只读 #869，不在本 ADR 保存第二份流程。

跨 worker 的发现与裁定由 findings 状态库承接，不依赖任一 worker 的 session
记忆（判官自身的跨轮记忆除外，见 ADR 0132）。状态库字段与写入规则归
ADR 0129；Runner 不查询状态库、不分类 finding、不比较 commit/HEAD、测试或
修复证据，只处理 ADR 0131 三通道。

Integrated completeness 与 integrated correctness 同样保持为两个独立开庭
（共用同一判官机），不能被同一个会话吞成“边评边修”的内部 loop；各自
`converged` 方进下一闸。

## 为什么

Dogfood #362 证明，把评审与修复揉进同一 session 会让 must-pass-first gate
被合并、跳过或自我合理化。结构分离用 fresh context 与可观察 findings 换掉
脆弱的 in-session 自律；代价是多一次 worker 接力，但判断独立、恢复边界和
审计记录更可靠。#899 连死五圈进一步证明：open-count 机械关环无法替代有
记忆的判官。

## 后果

- 判官不自修代码；fixer 不自报评审收敛；审卷腿每轮 fresh。
- 专业材料交给下一位专业 worker，不成为 Runner 的裁决输入。
- 旧「S4 classify by findingsCount」实现与措辞删除；替换范围由 #925 实施票
  追踪。
