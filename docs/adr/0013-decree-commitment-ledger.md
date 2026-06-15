# 圣旨承诺载体契约：经常性/时限/未来触发的承诺有始有终（#136）

Status: Proposed（设计草案，2026-06-15。地基机制经 4-agent 实证调查（带 file:line）锚定。**待评审**：按 CLAUDE.md 设计文档铁律走本地 cmr + 线上三 bot 收敛后才进实现期。实现属编码活、spawn 隔壁。）

## 背景与第一性原则

实玩实证（`#136`，昨晚存档 `data/ming_sim.db`）：玩家下旨「**今后边军月饷每月一律列支五十万两**」（recurring）、孙承宗起复诏「**三月后复试**」（未来触发）——两者的「未来才发生的后果」都**只活在邸报叙事 / office 文本备注里、无结构化载体、到期不触发**。turn2 extractor `fiscal_creates=[]`、turn3–6 无 50 万扣账；孙承宗 turn4（三月期）复试未触发、turn6 仍「暂听候政」。

**第一性原则（P1 铁律的延伸）**：CLAUDE.md P1「决策当回合全量落库」对**未来后果**同样成立——承诺=「未来后果的**当回合落库凭证**」。凡圣旨/密令的后果不是一次性的（每月 X、连续 N 月、直到补齐、X 月后复试），当回合就必须把**承诺本身结构化落进 DB**（动作 + 终止维度 + 来源），让 restore 只读 DB 能无损接续到期 firing，不靠「我记得」。

承诺有三形态：① **经常性**（每月 X，直到某条件）② **时限**（连续 N 月 / 半年为限）③ **未来一次性触发**（X 月后复试/复核）。

## 调查结论：零件仓内全有，唯一缺口是「日历维度」

4-agent 实证（下列 file:line 为**指示性锚、个别随版本漂移，以函数名为准**，修 R1-low）：「每月动作」「条件判停」「来源溯源」三块零件现仓内**全有**，承诺载体**不另造表**、复用现有机制：

- **`issue.ongoing_effects`**（`issues.py:2707` `apply_issue_inertia_and_ongoing` 每回合无条件落账 + `issue_advances` 留痕 + `close_issues` 收尾；实证户部亏空 国库 −10/月）= 主载体（财政+非财政通吃、自带进度/留痕/收尾/`origin_ref`）。
- **`new_issues` 创建路**（`issues.py:1055-1116`，`origin_kind=decree`、kind 白名单、active initiative≤10）= 创建端入口。
- **`secret_orders.due_turn`**（`db.py:601` + `auto_submit_due_secret_orders` `db.py:6304-6334`，`decree.py:880` 接入）= 全库唯一「回合到点→代码自动 firing」范式。
- **`legacies.duration_months` + `clear_gate`**（`db.py:729-741` + `expire_legacies` + `clear_gated_legacies`）= 同行「时长到期」+「条件满足」双结束语义范本。
- **`_gate_passed`**（`issues.py:292-328`，支持 >=/<=/==/!= 寻址 region/army/building/power/class/faction）= 「直到补齐 X」条件判停的现成机判器。⚠️ 实证：`resolve_condition`/`fail_condition` 当前**纯展示字符串、全库零求值**（grep 证）。
- **ADR 0008 Provenance**（`source` + `origin_kind`/`origin_ref`）= 溯源 + 可见性。

**唯一普遍缺口**：除 `secret_orders.due_turn`/`legacies.duration_months` 外，主载体（issue/fiscal_config）**无「到第 N 回合自动 firing」的列 + 钩子**（issues 仅 `origin_turn`/`last_advance_turn`；`expected_months` 只折成 inertia 软漂移、日期信息即丢）。

## 决定

### D1 主载体 = `issue.ongoing_effects`（复用，不新建表）
承诺一律落成一条 `kind=initiative`、`origin_kind=decree`、`origin_ref` 指回诏书的 issue，承诺的「每月动作」放 `ongoing_effects`（economy/metrics/…）。判据：它已具「每月动作 + 进度留痕 + 收尾 + 溯源」四面，避免造平行第二套。**纯无限期常设义务**（如永久新增一档月饷、无终止）仍可走 `fiscal_config`（经常性月流水，大臣查账认账）——但带「直到/N 月/复试」终止维度的承诺走 issue（要有始有终追踪）。

### D2 schema 扩展（不污染 gate 语法、不新表）
`issues` 表 `ensure_column`：
- **`end_turn INTEGER DEFAULT 0`**（0 = 无硬期限；立项时 `end_turn = turn + N`，算法仿 `secret_orders.due_turn` 的 `turn + deadline`，**无 clamp**，修 R1-low）——「时限/到期」的日历维度。
- **`stop_condition TEXT DEFAULT ''`**（空 = 无条件；复用 `_gate_passed` 的 `{key: "比较式"}` 语法，同 `legacies.clear_gate`）——「直到补齐 X」的条件维度。
- **`firing_kind TEXT DEFAULT '' + firing_payload TEXT DEFAULT ''`**（**仅形态③用**；空 = 非未来触发承诺）——「X 月后复试/复核」到期要触发什么的**可机读凭证**（kind=recheck/audit/… + JSON payload 带 target/context）。**没有它，restore 后一条只有 `end_turn` 的 issue 分不清是孙承宗复试还是别的、也不知该 emit 什么决策**（修 codex R2-high）。

不新增 turn/month gate key（保持 `_gate_passed` 寻址表纯净）；时间条件一律用 `end_turn` 显式列表达。

### D3 三形态 → 载体落点
| 形态 | 载体 | 终止 |
|---|---|---|
| ① 经常性（每月 X 直到条件） | issue.ongoing_effects（每月扣 X）**·bar-exempt** | `stop_condition`（条件达成→收尾） |
| ② 时限（连续 N 月 / 半年为限） | issue.ongoing_effects**·bar-exempt** | `end_turn`（到期→停账收尾） |
| ③ 未来一次性（X 月后复试/复核） | issue（**无 ongoing**）+ `end_turn` + `firing_kind`/`firing_payload`**·bar-exempt** | `end_turn` 到点 firing 一次后收尾 |

- **bar-exempt（修 Claude R1-high）**：承诺 issue **必须 `inertia=0`（不给 `expected_months`）且豁免 bar-based 自动结案**（`advance_issue` 的 to_value≥100→resolved / ≤0→failed 对承诺不适用）。否则 bar 漂到 100 会在 `stop_condition`/`end_turn` 触发前把承诺静默 resolved，两套终止逻辑赛跑。承诺**唯一终结路径 = `stop_condition` 达成 或 `end_turn` 到期**。
- ①②可叠（先到者停）。**形态①「`stop_condition` 永不达成 + `end_turn=0`」= 有意的开放式承诺**（如永久新增月饷、皇帝可主动撤），永久挂账可见，非死锁——与 D1「纯无条件永久流水走 `fiscal_config`」的分界：**要逐月有始有终追踪/带条件 → issue；纯无条件永久月流水 → `fiscal_config`**。
- **形态③ 是「预约未来一次决策」，不是 recurring 承诺**：不落每月账，到期注入一个**当月 simulator 二次决策块**（复试/复核，皇帝拍）。注入时序与槽见 D5（必须 pre-simulator + 独立注入槽）。

### D4 创建端（extractor）：新增承诺路由规则
现状缺口（实证 #136）：边军月饷被当固定流不重写（`score_extractor_internal.md:64`）+ 非新科目不触发 fiscal_create + `new_issue` 门只收工程/改革/案（`score_extractor_issues.md:46`）→ 经常性拨款承诺被三重挡在外。
新增 prompt 规则：玩家旨意含「今后每月 X / 连续 N 月 / 直到补齐 / X 月后复试」等**未来/时限/周期**语义 → 路由为带 `ongoing_effects` + `end_turn` + `stop_condition`（③再加 `firing_kind`/`firing_payload`）+ `origin_ref` 的 `new_issue`。`new_issues` 落库需接受并落这些列。注：`resolve_condition` 现**仅 extractor LLM 软判结案消费、无 code 侧 `_gate_passed` 求值**（修 R1-medium 措辞，非「纯展示」）——承诺的条件判停改用新 `stop_condition`（code 硬判、权威，见 D5），`resolve_condition` 可留作 LLM 软判兜底但 code 判优先。

### D5 检查端（结算）：条件求值 + 两类到期扫描（**时序是关键**）
- **条件判停（①②，后半段事务内）**：每回合对 active 承诺 issue 的 `stop_condition` 跑 `_gate_passed`，达标即收尾（D6）。这补上 `resolve_condition` 当前仅 LLM 软判、无 code 求值的洞——`stop_condition` 是 **code 侧 `_gate_passed` 硬判、为权威**；与 LLM 软判同回合都触发时靠 `close_issue` 的 `status!='active'` 守门**幂等去重**（先到先收尾，后者 no-op）。
- **①② 到期停账（后半段 `applier.atomic`）**：扫 `end_turn>0 AND end_turn<=turn` 的 ①② → 停账收尾（D6），与 `apply_issue_inertia_and_ongoing` 同段（随结算原子、崩溃回滚一致）。
- **③ 到期 firing（必须 pre_settle、simulator 之前）**：扫到期形态③ → 按 `firing_kind`/`firing_payload` **注入二次决策块到 simulator payload**。**时序硬约束（修 codex R1-high）**：simulator 在 pre_settle 之后跑，故③的到期扫描**必须放 pre_settle 段**（仿 `auto_submit_due_secret_orders` 在推演前置触发）；放后半段则 simulator 已跑完、注不进当月决策块、firing 落空。
- **注入槽（修 Claude+codex 的「接 0011-5」洞）**：0011-5 的二次决策块入口按「被打回旨意/`blocked_layer`」键控、**无到期承诺槽**。故**新增独立注入槽**：simulator payload 加 `due_commitments:[{title,origin_ref,firing_kind,context}]` + `season_simulator.md` HITL `<<DECISION>>` 章补口径「凡 `input.due_commitments` 须为各条生成一个复试/复核二次决策块」。即**复用 0011-5 的 `<<DECISION>>` 块形态、走独立到期承诺注入槽**，不挂 0011-5 被打回入口。

**事务边界（ADR 0008）**：①② 求值/停账在后半段 `applier.atomic`；③ 到期扫描在 `pre_settle`（自带事务、提交后保持已落）。两者均不破 `assert turn==before+1`。承诺创建（D4）+ 两类到期标记全当回合落库（含 `firing_payload`），restore 只读 DB 无损接续到期 firing。

### D6 有始有终（收尾语义 + 留痕 + 呈现）
**收尾复用既有 status，不新引 `expired` 枚举（修 Claude+codex R1-high）**：`issues.status` 域现仅 `active/resolved/failed/dropped`（`close_issue` 只产 resolved/failed、`list_closed_issues_at` 只认 resolved/failed/dropped）。承诺收尾两条：
- **条件达成（兑现完成，如欠饷补齐）→ `resolved`**。
- **到期停账（`end_turn` 到、未达成）→ `dropped` + `close_reason='承诺到期'`**——`dropped` 既有收尾语义、既有读者已认，不引新枚举。须新增一条 `expire_commitment` 收尾路（标 `dropped`+reason、写 `issue_advances`、**不跑 resolve/fail effects**），**不能复用会触发效果的 `close_issue('resolved')`**（否则到期被误判成兑现、还放 resolve 效果）。
每月兑现写 `issue_advances`（`trigger_kind=commitment`）。`origin_kind=decree` → 玩家可见（议题面板：「边军月饷·每月 50 万·已第 3 月·直到欠饷补齐」）。承诺=皇帝看得见始终的活账，不再「嘴上答应后面全忘」。

### D7 Provenance（避免孙承宗坑）
承诺带 `source=player_decree` + `origin_ref` 指回诏书（ADR 0008 决定 5）。**溯源用 `origin_ref`、不用 `source` 做硬 reject**——#136 实证孙承宗起复 person_changes `source=system_simulation`（虽源于玩家诏书经 simulator→extractor），硬按 source 问责会误杀合法承诺（同 #158 close 的教训）。

### D8 对齐已有设计（不造平行第二套）
- **#45/#46**（国策结案强制配对，现 `_emit_pairing_warnings` warn-only、查同回合 delta、看不见顶层 fiscal_creates）：承诺载体落地后**成为该守门的检查对象**，把 #45/#46 升级为「凭承诺载体强制」；**改写其「后果当回合一次性配齐」假设**——承诺后果是未来逐月/到期发生，配对检查改为「按承诺期表核本月兑现」。
- **#67 / 财政基座**（`FISCAL_PROVINCE_SUBSTRATE.md:33/96` recurring obligation + k=0 两类分流）：财政类承诺的未兑现处置**对齐 substrate 成熟语义**（军事俸禄→转 Due 成债「停饷即叛」/ 工程营建→挂起进度 0 不积债），`cost_type=recurring`、`arrears_allowed` 复用，不造平行 recurring 模型。⚠️ substrate 现 shadow 未 cutover（待 M0 #73）→ 承诺现落全局 `fiscal_config`/issue 与省级 Due **暂并存**；cutover 后财政类承诺**归约到 substrate Due**，非财政类（复试/营建进度）自带 firing 超出 substrate 范围。冲突按 later-doc-wins。

## Considered Options
- **新建 `commitments` 表**：否决——issue.ongoing_effects 已具四面，新表=平行第二套 + 重复落账/留痕/收尾机制。
- **给 `_gate_passed` 加 turn/month gate key 表达时限**：否决——污染 gate 寻址语法；`end_turn` 显式列更干净、且对齐 secret_orders/legacies 既有范式。
- **承诺只落 `fiscal_config`**：否决——fiscal_config 无 turn/start/end 列、无「有始有终」追踪、非财政承诺（复试/营建）无家；仅「永久无限期常设义务」适合它。
- **firing 时序一刀切放后半段**：否决（R1 codex 修正）——③未来触发的 firing 要注入当月 simulator 二次决策块，而 simulator 在 pre_settle 之后跑，放后半段就注不进、firing 落空。故按「要不要注入当月 simulator」**分段**：③ firing 必须 pre_settle（simulator 之前，仿 secret_order due），①②的条件求值/到期停账放后半段 atomic（与落库同源）。

## Consequences
- #136 解决：recurring/时限/未来触发承诺有结构化载体 + 到期 firing + 有始有终；「每月 50 万补饷」「三月后复试」不再丢。
- #45/#46 从 warn-only 升级为凭承诺载体强制（需改写其当回合假设）。
- 新增面：四列（`end_turn`/`stop_condition` 通用 + `firing_kind`/`firing_payload` 仅③）+ 结算三扫描（条件求值 / ①②后半段到期 / ③ pre_settle 到期注入）+ simulator `due_commitments` 注入槽 + extractor 路由规则 + new_issues 落库扩展；主机制（issue.ongoing_effects）全复用、**不新表**。
- 与 substrate 关系明确（暂并存→cutover 后财政类归约 Due）。
- restore 无损：承诺当回合全量落库（end_turn/stop_condition/firing_payload/origin_ref），崩溃续跑不靠记忆（P1）。
- 实现属编码（spawn 隔壁）：schema 迁移（四列）+ extractor prompt 路由 + 结算三扫描（①②后半段 / ③ pre_settle）+ simulator `due_commitments` 注入槽 + bar-exempt 守门 + `expire_commitment` 收尾路 + new_issues 落库扩展 + 呈现。
