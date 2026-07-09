# 下一步执行顺序（临时备忘 · 2026-07-08 凌晨更新）

**✅ 四片 bench 之夜全 ship(2026-07-07/08)：#593(PR #680)、#372(PR #682)、#617(PR #679)、#601(PR #681) 全部 merge 进 main**——四个真实切片由便宜 coder（GLM-5.2 / kimi-k2.7-code / grok-build / grok-composer）打穿完整评审链（双轴评审→per-slice cmr→线上 bot→threads 全 resolve），runner 全程零改码，bench 数据/缺陷人格/角色×池子矩阵全在 **#424**。#681 尾单 codex P2（无信号 ship→escalate 零重试）经 GLM 证据裁决 DEFER→**#661** 备案（用户 2026-07-08 拍板），`realBackend.ts:2825-2831` 注释 doc bug 随 kind-mapping 决定原子改。#440 epic 剩 3 open 子片：#366（#596 走闸中→#600→#602→#603）/ #367 / #592 已由 #601 交付关闭待核。

**▶ 当前动作（2026-07-08 凌晨更新）：✅ #596 已落 main（PR #707 merged 03:23，本地 6 轮+线上 4 轮全收敛，defer 台账 #600×4/#706/#709）→ 现行 = #600 composer 裸 issue 大考进行中**（bench-600 worktree，判断地形考试，主力 coder 加冕战，数据入 #424）；#600 接线时 4 条 forward-note 是硬点检（success-flag 分支 / live-path a-b-c / ADR 0061 fresh-verify 拓扑）。

**✅ #597 全 ship(2026-07-07):删 family CMR round-cap——PR #664 merge 进 main(merge commit `59d4bcfd`)。删掉 `MAX_CMR_CODER_FIX_ROUNDS=3` + `remainingCmrCoderFixRounds` 全线穿线;有 blocking 就一直派 coder-fix+fresh re-review,退出只剩收敛(→ship)或 worker-raised escalate。coder = opencode `zai/glm-5.2`(派发腿),runner=Claude(验 DoD+评审+ship)。本地双闸(completeness 3/3,含 Claude 差分执行证非空壳 + correctness 2/2)+ 线上 3 轮:Codex 把「删 cap 后无界循环」P2→P1、抓出 **#597 criterion 4 没真落地**——worker 契约只对 out-of-slice 设计 gap escalate、不覆盖「反复修不好 in-scope bug」→ 无限循环。R2 修复:往两个 CMR pass soul(`cmr_completeness.md`/`cmr_correctness.md`)加 item 5——**非收敛本身即 escalate 触发**,锚复现+worker 判断、明禁轮数计数(否则=把删掉的 cap 搬进 worker);runner 侧本就每轮接(`verifyCmr.ts:1632`)。加 `EscalateOnNonConvergenceBackend` 测试(2 轮修后 escalate → 有界停)。Codex R3 +1 approve、Gemini clean、Sourcery 处置、CodeRabbit provisional。全测 1318 passed,tsc 0,2 thread resolved。#597 CLOSED,#590 两个 sub-issue(#597/#598)均 closed。worker-escalate 落进 **#604 已建好的 `decision_gate_park`**(B-class,answerable+resumable,ADR 0062 退出-重入+durable ledger 模型、原地 resume——非长活挂起、非 terminal abort;runner.ts:131-206 / realFamilyBackend:2489)。#590 韧性三半(#597 删 cap、#598 重试、#604 A/B 分家+park-resume)均已落地,**#590 已 CLOSED(2026-07-07,7 验收逐条对交付 issue,close comment 有表)**。#440 epic 剩 4 片:#366 / #367 / #372 / #592。**

**✅ #598 全 ship(2026-07-07):关键石完成——PR #646 merge 进 main(merge commit `72e88bbd`)。通用机械重试落在共享 worker-dispatch seam(`dispatchRetry.ts`:`withMechanicalRetry`/`retryProcessCrash`);进程级失败(failed/malformed/outcome_protocol_failure/thrown)fresh 重试到 `MAX_DISPATCH_ATTEMPTS=3`,已判定 shape(completed/escalated)零重试透过,耗尽 durable abort。与两个语义层(reviewer `MAX_INVALID_REVIEWER_OUTPUT_ATTEMPTS`、CMR `OUTCOME_REWRITE_RETRY_CAP`)靠 `callerOwns` 谓词组合不双数。本地 cmr 5 轮收敛 + 线上 5 轮(R1 bots→R4 confirm)全处理:Codex 把 verifyCmr 的 family 写 worker crash-retry-on-residue 从 P2 升 P1(数据完整性)→ 改判为 #598 验收「重试前 reset 残留」缺口、直接关(写 worker crash abort 不重试,只读 reviewer 照旧重试);Gemini null-tolerance 全 sweep + ship-reset worktree 守卫;驳回 Gemini 的 stateful-repair 建议(#598 刻意无状态)。全量 1316 tests/0 fail,tsc 0,pytest 绿,19 thread 全 resolved。#598 CLOSED,#590 进度 1/2(还剩 #597),#440 直接子片仍 8/13(#590 未闭)。deferred → **#661**(family 写 worker 保 runner-param 的 reset 以安全重试 + merger 未跟踪残留清理 + coder 提交后崩溃保留,ADR 0024 张力)。**

**✅ #604 全 ship(2026-07-07):Layer 3 完成——PR #643 merge 进 main(merge commit `49ab3ac1`)。三轮线上 bot 评审全收敛(Codex +1 approve、Gemini R1-R3 findings 全处理、Sourcery 超 diff 上限出局、CodeRabbit provisional),9 thread 全 resolved,pytest+tsc 绿。#604 CLOSED,#440 epic 进度 8/13 (61%)。Layer 3 补丁:R1 `finalizeDecisionPark` ledger-merged 感知 + validator null 容忍(`ebac5194`);R2 family-level `decision_gate_park`(`5864cd56`);R3 null-tolerance 全类 sweep + 驳 Gemini 假阳性 critical(`e41067a9`)。deferred:#644(跨版本 resume 丢受保护 findings,守卫档=#643 后小尾巴 PR / 迁移档=需设计)、`task_769419f7`、`task_6c5f63bb`。**

## #440 剩余子片 · 依赖驱动执行顺序（2026-07-07 拍板）

> 五个 open 子片**全都有定稿设计**（PRD/ADR 齐、已切子切片）——不是「卡设计闸」，`ready-for-agent` 没贴 ≠ 设计没收敛（那标签评审闸后才贴）。真正定顺序的是**子切片级 native `blocked_by` 依赖**，不是标签。**#604 merge 已解锁 #596/#597/#598（三个都 blocked_by:[604]）。**

依赖图（子切片级）：
```
#604 ✅merged ── unblocks ──▶ #596, #597, #598

#590 韧性核心  ├─ #597 删 round-cap（reviewer 判断驱动续/停）      ← 现可做
             └─ #598 通用机械重试 dispatchWorker                ← 现可做 · 关键石
                        ├──▶ #600 (#366 收敛引擎 bot 轮询+verify/fixer)
                        └──▶ #601 (#592 role 回归测试)
#366 线上评审  #596 skeleton(可做) → #600 → #602 → #603
#592          #601  blocked_by #598
#367          #593  blocked_by:[]  ← 一直可做（小·独立）
#372          本体即切片（检测式子片 #594/#595/#599 已关），ready·独立
```

**执行顺序（按依赖杠杆）：**
1. ~~**#598 通用机械重试**（关键石，解锁 #600+#601）~~ ✅ **shipped(PR #646, `72e88bbd`)** → 2. **#597 删 round-cap**（#590 韧性核心另一半，`blocked_by #604` 已闭=现可做）→ 3. **#601**（#592 role 回归测试，#598 解锁后现可做）→ 4. **#596→#600→#602→#603**（#366 线上评审 loop 链）→ 独立快赢 **#593 / #372** 可随时插。

**~~当前动作：#598 已 ship（关键石）→ 下一片 = #597 删 round-cap~~（已完成，见文首）**：#597 ✅、#601（#592）✅、#593（#367）✅、#372 ✅、#617 ✅ 均已 merge；现行动作见文首「▶ 当前动作（2026-07-08）」段（#596 走闸中 → #600 composer 大考）。

（备选更高层轴：#485 线 = 大方向 #472 角色视角,见下方「顺序」段。）

---

**（历史)设计已定稿+合并(PR #605,ADR 0061/0062/0063 全 Accepted 进 main)。半手工 TDD 实现 #604 已完成。**

## #604 切片进度

- [x] **slice 1** 通用工具迁出 → `family/moduleDeclaration.ts`(commit `be53f43b`,绿)
- [x] **slice 2** 路由改「只数 findings、非 0 全进 coder-fix、永不据内容 terminate」;删 cmrFixableFindings.ts(commit `d8da731`,绿 1203,已独立验证——#497 核心 bug 已修)
- [x] **slice 3** ledger 胖字段拆成瘦信封 `blockingFindingIdentityKeys`(runner 读)+ `cmrDispositions`(gate 读)(commit `60a9afe7`,绿 1206,已独立验证)
- [x] **slice 4** reviewer 契约瘦身(5 个路由 disposition kind + 4 个路由字段全删,5 prompt + soul 归零;FindingDispositionKind 塌成 accepted_suppressed;classifier 塌缩;StopReason/治理/closure 全保)(commit `72899351`,绿 1209,已独立验证)。过程乱(subagent 丢线程+3 子 agent+过删),收尾 agent 补齐。defer 语义:新 prompt 禁 defer、validate 对 stray defer fail-closed=自洽,采纳。
- [x] **slice 5** 人类决策门(B)park-resume:family 层 child-escalation 退出-重入 park/resume(commit `4efaff9c`,绿 1212,已独立验证——含 session 跨 ADR 0063 重建存活硬闸 PASS)。ADR 0062 回注 `e8087cf2`。
- [x] **slice 6** 收口:ADR 0030 closure 完好确认 + 三出路覆盖已齐(fix-loop/decision-gate/envelope 各有测试)+ #448/#449 补 superseded 溯源注(本就 CLOSED)+ defer 拔除切成 follow-up #617(非 #604 验收面,不塞 finish line)。

## ✅ #604 代码完成 + 本地 ship-pre cmr 双闸过(2026-07-06)
**16 commits,52 files,+5427/-1972,tsc 0,1282 tests/0 failed。COMPLETENESS 5/5(4轮)+ CORRECTNESS 5/5(6轮)全 concur。含 reopen/dispute 治理 rework(修回 ADR 0030、bounded 宪法零推翻)。下一步 = Layer 3:push→PR→线上 bot 评审→merge。deferred:task_769419f7 / task_6c5f63bb。checkpoint 已存。**

分支 `fix/604-runner-envelope-constitution`,6 commit(slice1-5 + ADR 回注),34 文件 +2268/-1610,tsc 0 / 全量 1212 绿。DoD 各面齐(写/读/恢复/reviewer 契约/文档契约/测试)。**下一相 = 评审闸(ak-cross-m-review 整合 cmr + 线上 bot),未跑。**

**已拍定的设计判断**(不再问):accepted-suppression 治理**保留**、只从 runner 决策面解耦(删它=越 #604 scope,且近期 commit 正加固它)。prior-disposition 跨轮追踪走 ledger 瘦字段 `cmrDispositions`(不建 sidecar)。

---

（原始等待期计划,已推进到实现阶段）

## 顺序

1. **【等】** 设计定稿 **#440**(编排器韧性 epic)。#604(runner 纯调度反转,ADR 0026/0050)收在 #440 里,**不单独实现 #604**。
2. **【做】#440** —— 编排器韧性 / 自驱服务。走 /tdd:删 runner 侧 finding 分类(cmrClassification.ts/cmrFixableFindings.ts)、runner 收敛到三功能(exit 重试 / findings==0 门 / 人类决策门)、reviewer soul+promptFile 去 disposition、加人类决策门 → 重编 dist + 重烤镜像。
3. **【做】#485 线**(= 大方向 **#472** 角色视角与情报解释层,M11 order-1,**定义型上游**)。切片 #487-494,从 **#487(S1)** 起。
   - 为什么先它:M11 tracker(#486)排序「定义型轴优先」;#497 的见闻底座真源 **#489** 就在这条线里;#497 现靠 ADR 0034 简化兜底跑、整合闸留了尾巴,等 #489 落地才能真过。
   - **#494 是重内容活**(40+ 大臣 dossier + 7 派档料)—— cheap 编排器可能啃不动,到时换路子/换后端/手工,单独定。
4. **【做】#497**(= 大方向 **#470** 召对流程,M11 order-2)。#485 线(至少 #489)到位后回来。

## #497 续跑资产(一律不碰,换跑 #485 线不影响)

- family 分支:`family/497-base @ e21acc9d`(已含 #499 merge)
- ledger:`~/.sc-orchestrator/dogfood-497-ledger/`(只 `499 merged`)
- iso worktree:`~/.sc-orchestrator/Akagilnc_ming-salvage-sim-iso-497`
- family-base-start-head:`e3ff3b5b`
- 续跑命令:`ORCHESTRATOR_ROUTE=codex-cheap node orchestrator/launch-497.mjs`,`cutFamilyBase` 复用 family/497-base,从 #498 续跑
- #498 待做:criterion 10 收夜×在飞回话 guard(已实现)+ 生产接线(open_audience_night 接进 web_app._start_chat_turn、night_id 穿进 create_chat_turn)

## 号码对照(别再记混)

- #497 = PRD 召对流程,父 = **#470**(不是 #487)
- #487 = [485·S1] 切片,父 = #485(PRD),再上 = #472
- M11 order:1=#472(PRD #485) → 2=#470(PRD #497) → 3=#471 → 4=#478
