# 编排器角色分离：分叉点 = runner 派的独立 worker（反转 ADR 0026 单 worker 兼 fixer）

Status: Accepted（2026-06-29；本地 cmr 8 轮[完整性 4 + 正确性 4] + 线上 bot 3 轮双闸收敛，PR #425）

Revised by: ADR 0129（findings 状态机、写入点校验与三态取数收口；角色分离决定不变）

partially-supersedes: ADR 0026（「cmr = 一条带记忆 worker 兼 fixer / 无 runner 轮间 loop / findings 不在 worker 间传」这一条被反转；ADR 0026 的 runner=纯调度其余部分仍有效）

## 决定

per-slice 与 integrated cmr 的「评审 → 修复 → 复审」收敛 loop，从「单 worker session 内部跑完」**拆回 runner 调度层**：coder / reviewer / coder-fix 是各自 runner 派的独立 worker/容器。reviewer 把 findings 写入状态库，runner 只按未决 0 / 未决 >0 / 需要人三态派下一棒；fixer 更新行状态，fresh reviewer 在**当前全 diff**上复验后确认关闭或打回重开。**通用原则：任一 must-pass-first 闸不得埋进单 worker loop，必须落成 runner 调度边界。**

跨轮发现及其裁定由 findings 状态库承接，不靠任一 worker 的 session 记忆。字段、状态跳转与 accepted suppression 授权在写入点校验；runner 不分类 finding，不管理 disposition，不比较 commit/head 或测试证据。

**integrated cmr 拆分**：step5 完整性 与 step6 正确性 是两道**有序** runner-dispatched pass —— step5 先过才派 step6、step5 fail 即停、每 pass 判决落 findings 状态库（细节见子片 #419；本 ADR 把它从纯指针升为决定）。

## 为什么

ADR 0026 押注「一条带记忆的 worker 主 session 兼 fixer，凭 in-session 记忆 dismiss 重复假报、自律收敛」，并明确把「findings 当 data 在 fresh worker 间传」判为错架构。dogfood #362 证伪这个赌注——角色揉进一个 session → 纪律靠 agent 自律 → 被侵蚀：#375（cmr step5 完整性闸被 step6 正确性 loop 吞）、#373（coder 自评把 build+review 揉一处 → 自我框架带跑 → spec-miss 被 defer #370）。结构分离让「跳过/合并闸」**结构上不可能**：runner 只在 reviewer 完了才派 fix、只在收敛了才下一步，worker 想塌也塌不了。这恰是 ADR 0026 自己的原则（「分叉点必须是 runner 边界、不能埋进 worker」）—— 0026 的 consolidate 例外违背了它自己。

## Tradeoff（如实记，不粉饰 0026）

代价 = 失去 0026 看重的 in-session 记忆（worker 记得上轮报过/改过啥、凭记忆收敛）。替代 = runner-visible findings 状态库：跨轮状态写进可审制品而非藏在一条 session 记忆里。**「findings-as-data 跨 worker 传」在 0026 被判错架构，此处明确翻案**——它不是「模拟记忆」，是 reviewer 独立性 + 可观测性的载体（每轮 fresh reviewer 冷读当前全 diff，不复查自己旧 finding）。换言之：用**可观测 + 独立**换掉**会侵蚀的自律记忆**。coder 仍可兼 fixer（同一模型接 fix worker），但 review 是独立 worker、不是 coder 自评。

## 追踪

#376（epic v2.1 角色分离）/ #369（per-slice 拆 coder/reviewer/fix）/ #376 scope#2（integrated cmr step5 完整性 与 step6 正确性 拆成独立 runner-dispatched pass）。实现保「薄 promptFile / issue live fetch / baked soul-skill / runner 只调度读终态」的反漂移约束不变。

## 传导范围（实现 #369/#419/#422 必改；本节列已知承重点，但**清单非穷尽**）

被本反转推翻的旧（0026 consolidate）设计 + **写死的 model 钉死点**散在 orchestrator souls + src 各处——它们是**当前有效的 0026 实现**，由实现切片重写。**逐轮 cmr 总能再揪出一个漏列文件（coverage drift），故本节不追求穷尽清单，而是把"扫全"定为切片的首步职责**：

> **实现职责（#422 路线/registry + #419 cmr 拆分 的首步）**：扫出**所有写死 model 钉死点**让它们消费 route+registry 输出（不再硬编码）。**`rg 'model:\s*"..."'` 只匹配对象字段、会漏裸常量** —— 必须语义扫全，含 codex R1 点名的形态：`runner.ts` coder 默认 `|| "gpt-5.5"`、`realBackend.ts` 的 slug switch case、`family/realFamilyBackend.ts` 的 `MERGER_MODEL = "claude-opus-4-8"`（**否则 merger 在 claude-tight 下仍跑 Claude**）。建议扫 `rg -n 'model:\s*"|MODEL\s*=\s*"|"(sonnet|opus|haiku|gpt-5\.5|claude-[a-z0-9-]+)"'` 再人工过 switch/默认值。再 `rg -n 'You ARE the fixer|memory-bearing|inside YOUR session|S3/S5/S6|priorFindings'` 扫 0026-consolidate 注释/契约一并翻。本节清单是已知起点、**不是完整集**。

已知承重点（起点，非全集）：
- **souls**：`coder.md`（per-slice review/fix loop 在 coder 内）、`reviewer.md`、`cmr.md`（"You ARE the fixer…loop inside YOUR session"）、`ship.md`（引 cmr defer 语义）。
- **worker spec / 钉死点（codex R3 揪出的真代码点，#422 必改）**：`orchestrator/src/dispatchWorker.ts`（`shipWorkerSpec()` 写死 `model:"sonnet"`）、`orchestrator/src/family/dispatchFamilyWorker.ts`（写 integrated cmr 是单 memory-bearing fixer session + 写死 `model:"opus"`(cmr) / `"sonnet"`(family ship)）。
- **code 注释/契约**：`route.ts`、`runner.ts`（S2-only 塌缩）、`types.ts`（StepId 序列 + `StepRole` 枚举 + Reviewer/CoderOutput schema 注释，单 session/无独立 fix worker）、`realBackend.ts`、`family/verifyCmr.ts`、`family/realFamilyBackend.ts`、`image/build.sh`。

**便利标记（非全集）**：`CLAUDE.md ## Skill routing`、`coder.md`、`reviewer.md`、`route.ts`、`runner.ts` 已就地加 `pre-0030` 指针;其余以本节 + 上面的 grep-sweep 为准。**0030 落地前这些全是当前 0026 有效设计**——不是「现在就错了」，是「实现时一并翻」。
