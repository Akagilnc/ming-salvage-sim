# 编排器角色分离：分叉点 = runner 派的独立 worker（反转 ADR 0026 单 worker 兼 fixer）

Status: Proposed（2026-06-29，grill #376/#369 结晶；评审闸在 to-prd 之后，本 ADR 尚未评审）

partially-supersedes: ADR 0026（「cmr = 一条带记忆 worker 兼 fixer / 无 runner 轮间 loop / findings 不在 worker 间传」这一条被反转；ADR 0026 的 runner=纯调度其余部分仍有效）

## 决定

per-slice 与 integrated cmr 的「评审 → 修复 → 复审」收敛 loop，从「单 worker session 内部跑完」**拆回 runner 调度层**：coder / reviewer / coder-fix 是各自 runner 派的独立 worker/容器，runner 持那条可见的 loop（派 reviewer → 分类 findings → 派 fix → 派 fresh reviewer 复审 → 收敛/escalate）。findings 经 landing file 跨 worker 边界传，每轮复审针对**当前全 diff**。**通用原则：任一 must-pass-first 闸不得埋进单 worker loop，必须落成 runner 调度边界。**

## 为什么

ADR 0026 押注「一条带记忆的 worker 主 session 兼 fixer，凭 in-session 记忆 dismiss 重复假报、自律收敛」，并明确把「findings 当 data 在 fresh worker 间传」判为错架构。dogfood #362 证伪这个赌注——角色揉进一个 session → 纪律靠 agent 自律 → 被侵蚀：#375（cmr step5 完整性闸被 step6 正确性 loop 吞）、#373（coder 自评把 build+review 揉一处 → 自我框架带跑 → spec-miss 被 defer #370）。结构分离让「跳过/合并闸」**结构上不可能**：runner 只在 reviewer 完了才派 fix、只在收敛了才下一步，worker 想塌也塌不了。这恰是 ADR 0026 自己的原则（「分叉点必须是 runner 边界、不能埋进 worker」）—— 0026 的 consolidate 例外违背了它自己。

## Tradeoff（如实记，不粉饰 0026）

代价 = 失去 0026 看重的 in-session 记忆（worker 记得上轮报过/改过啥、凭记忆收敛）。替代 = runner-visible ledger + landing file：跨轮状态写进可审制品而非藏在一条 session 记忆里。**「findings-as-data 跨 worker 传」在 0026 被判错架构，此处明确翻案**——它不是「模拟记忆」，是 reviewer 独立性 + 可观测性的载体（每轮 fresh reviewer 冷读当前全 diff，不复查自己旧 finding）。换言之：用**可观测 + 独立**换掉**会侵蚀的自律记忆**。coder 仍可兼 fixer（同一模型接 fix worker），但 review 是独立 worker、不是 coder 自评。

## 追踪

#376（epic v2.1 角色分离）/ #369（per-slice 拆 coder/reviewer/fix）/ #376 scope#2（integrated cmr step5 完整性 与 step6 正确性 拆成独立 runner-dispatched pass）。实现保「薄 promptFile / issue live fetch / baked soul-skill / runner 只调度读终态」的反漂移约束不变。
