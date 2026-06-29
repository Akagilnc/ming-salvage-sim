# 编排器角色分离：分叉点 = runner 派的独立 worker（反转 ADR 0026 单 worker 兼 fixer）

Status: Proposed（2026-06-29，grill #376/#369 结晶；评审闸在 to-prd 之后，本 ADR 尚未评审）

partially-supersedes: ADR 0026（「cmr = 一条带记忆 worker 兼 fixer / 无 runner 轮间 loop / findings 不在 worker 间传」这一条被反转；ADR 0026 的 runner=纯调度其余部分仍有效）

## 决定

per-slice 与 integrated cmr 的「评审 → 修复 → 复审」收敛 loop，从「单 worker session 内部跑完」**拆回 runner 调度层**：coder / reviewer / coder-fix 是各自 runner 派的独立 worker/容器，runner 持那条可见的 loop（派 reviewer → 分类 findings → 派 fix → 派 fresh reviewer 复审 → 收敛/escalate）。findings 经 landing file 跨 worker 边界传，每轮复审针对**当前全 diff**。**通用原则：任一 must-pass-first 闸不得埋进单 worker loop，必须落成 runner 调度边界。**

**终止/收敛判定**：loop 的收敛/escalate **复用 cmr skill 的现成模型**（drift 三检收敛、**非轮数计数**；缺腿按 cmr skill 降级容忍——**不强制三腿齐全**），不另立判据；integrated cmr 的最低线 = ADR 0032 的 ≥1 撑底线强腿。**fix-loop 的每步走 fresh `runStep`（保 git-truthing 真提交核验 + 单步 maxIter），不走 `resumeSession`**——`resumeSession`（跳 git-truthing、maxIter 固定 1）**严格只用于 crash/escalate 恢复**（沿 ADR 0026 既有不变式）；让正常 fix 步绕过 git-truthing 会使「假修」逃过真提交核验。这天然抗 LLM 抖动（drift 看 finding count 趋势/类，不是精确 hash，换措辞不重置）。**landing file = 结构化 findings 记录，存受保护的 ledger sibling 目录**（ADR 0026 既有「worktree 外」模式）、对非 reviewer worker 只读，防 coder worker 篡改绕闸。

**裁定状态补「无记忆」缺**（拆 worker 后丢了 0026 的 in-session 记忆）：landing file 不只记 findings，还记**跨轮裁定**，由 **runner 持**（runner 持可见 loop，裁定是它的账、不是某条 reviewer 腿私改）。**关键区分「自报」与「已验证」**——fix worker 说修好了只是 `claimed-fixed`（**未验证的自报，绝不当既成"已修"**）；只有**下一轮 fresh reviewer 在当前全 diff 里复验确认关闭**后，runner 才标 `verified-closed`。**这正是 cmr「每轮全量复审 + 上轮 finding 仅尾挂确认」**：假修（claimed 但没真修）会被下一轮 fresh 冷读重新 flag，不被噤声。**关闭判据 = 显式 disposition + 覆盖断言（不是"缺席"）**：fresh reviewer 必须把**每一条上轮 `claimed-fixed`** 明确归入三桶之一——`still-active`（仍在）/ `verified-closed`（已验证关闭）/ `unable-to-assess`（本轮判不了）；runner **断言每条 claimed-fixed 都被 disposition 覆盖**，漏判、或 reviewer 崩/截断/吐坏输出 = **无效输出 → 重跑 / escalate**，**绝不当 verified-closed**（同 cmr skill「降级 ≠ approve」——缺席不是关闭证据，因为 reviewer 失败也会造成缺席）。`unable-to-assess` **保持 open**。「不在 active 列表」只作佐证、**不是关闭唯一真源**（否则 reviewer 一崩、列表一空，所有未修 bug 被假关闭放行）。

**suppression 只用于「故意不修」、不用于「自报已修」**：fresh reviewer 不重提的，**仅限已接受的 `wont-fix` / `已驳`**（runner/人对某 finding 的明确判断「这条不修」）——否则 fresh 每轮重提一条**已决定不修**的 finding，drift 永不收敛、误触 escalate。`claimed-fixed` **不在 suppression 之列**（必须复验，见上）。

**裁定不得噤声独立性、且必须终止**（双约束）：① 对 `wont-fix/已驳`，fresh reviewer（尤其换了模型）独立判定**更严重** → **可升 severity**（单调、有界 `low→medium→high→critical`，封顶 ≤4 次）；判定**前轮裁错**要**同 severity 翻案/争议** → runner 记**一次性**（同一 finding 同 severity 的争议至多一次，之后该 severity 原样重提才压）。**降级不 reopen**：一条已被压制的 finding 若以 **≤ 已压制最高 severity** 再报，自动压制——**只有严格升 severity 才走 reopen 逃生阀**，降级报不消耗 reopen 预算、不刷回。两条都保证 reopen 有限 → loop 必终止，又不把"另一双眼睛发现它其实是真 P1"噤声。`landing file 是 fresh-worker 拓扑下"记忆"的落点`，正是 0030「runner 可见、不靠 session 记忆」的应有之义。

**integrated cmr 拆分**：step5 完整性 与 step6 正确性 是两道**有序** runner-dispatched pass —— step5 先过才派 step6、step5 fail 即停、每 pass 判决落 ledger/landing file（细节见子片 #419；本 ADR 把它从纯指针升为决定）。

## 为什么

ADR 0026 押注「一条带记忆的 worker 主 session 兼 fixer，凭 in-session 记忆 dismiss 重复假报、自律收敛」，并明确把「findings 当 data 在 fresh worker 间传」判为错架构。dogfood #362 证伪这个赌注——角色揉进一个 session → 纪律靠 agent 自律 → 被侵蚀：#375（cmr step5 完整性闸被 step6 正确性 loop 吞）、#373（coder 自评把 build+review 揉一处 → 自我框架带跑 → spec-miss 被 defer #370）。结构分离让「跳过/合并闸」**结构上不可能**：runner 只在 reviewer 完了才派 fix、只在收敛了才下一步，worker 想塌也塌不了。这恰是 ADR 0026 自己的原则（「分叉点必须是 runner 边界、不能埋进 worker」）—— 0026 的 consolidate 例外违背了它自己。

## Tradeoff（如实记，不粉饰 0026）

代价 = 失去 0026 看重的 in-session 记忆（worker 记得上轮报过/改过啥、凭记忆收敛）。替代 = runner-visible ledger + landing file：跨轮状态写进可审制品而非藏在一条 session 记忆里。**「findings-as-data 跨 worker 传」在 0026 被判错架构，此处明确翻案**——它不是「模拟记忆」，是 reviewer 独立性 + 可观测性的载体（每轮 fresh reviewer 冷读当前全 diff，不复查自己旧 finding）。换言之：用**可观测 + 独立**换掉**会侵蚀的自律记忆**。coder 仍可兼 fixer（同一模型接 fix worker），但 review 是独立 worker、不是 coder 自评。

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
