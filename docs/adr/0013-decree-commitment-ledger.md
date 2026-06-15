# 圣旨承诺载体契约：经常性/时限/未来触发的承诺有始有终（#136）

Status: Proposed（设计草案，2026-06-15；**务实版**——用户拍板：复用 issue 不另造、补饷喂现有 arrears 还款池且含损耗、未来复试最小化。地基机制经实证调查（file:line）锚定。待评审：本地 cmr + 线上三 bot 收敛后进实现期。实现属编码、spawn 隔壁。file:line 为指示性、以函数名为准。）

## 背景与第一性原则

实玩实证（`#136`，`data/ming_sim.db`）：玩家下旨「**今后边军月饷每月一律列支五十万两**」（recurring）、孙承宗起复诏「**三月后复试**」（未来触发）——两者的「未来才发生的后果」都**只活在邸报叙事/office 备注里、无结构化载体、到期不触发**。turn2 extractor `fiscal_creates=[]`、turn3–6 无 50 万扣账；孙承宗 turn4（三月期）复试未触发、turn6 仍「暂听候政」。

**第一性原则（P1 铁律的延伸）**：P1「决策当回合全量落库」对**未来后果**同样成立——承诺=「未来后果的**当回合落库凭证**」。后果不是一次性的（每月 X、连续 N 月、直到补齐、X 月后复试），当回合就把**承诺本身结构化落进 DB**，让 restore 只读 DB 无损接续，不靠「我记得」。

承诺三形态：① **直到补齐**（每月 X，直到条件）② **时限**（连续 N 月/半年为限）③ **未来一次性**（X 月后复试/复核）。

## 调查结论：零件仓内全有，复用不另造表

- **`issue.ongoing_effects`**（`apply_issue_inertia_and_ongoing` 每回合落账 + `issue_advances` 留痕 + 收尾 + 报告「待办未解」已列 + `origin_ref` 溯源；实证户部亏空 国库 −10/月）= **主载体**（财政+非财政通吃）。
- **`new_issues` 创建路**（`origin_kind=decree`、kind 白名单、active initiative≤10）= 创建端入口。
- **`armies.arrears`**（`models.py:247`）+ **`_auto_pay_arrears_by_priority`**（`flows.py:227` 每月按优先级用预算还各军欠饷）= 现成「欠饷结构化量 + 还款池」——「补饷」承诺喂它。
- **`_gate_passed`**（支持寻址 region/army/building/power/class/faction）= 「直到补齐」条件判停的现成机判器（可寻址 `armies.arrears`）。⚠️ `resolve_condition`/`fail_condition` 当前仅 LLM 软判消费、**无 code 侧 `_gate_passed` 求值**。
- **issue bar / issue_advances** = 履行进度显示。**ADR 0008 Provenance**（`origin_kind`/`origin_ref`）= 溯源。

## 决定

### D1 主载体 = issue（复用全套，不另造、不新 kind、不 bypass）
承诺 = 一条 `kind=initiative`、`origin_kind=decree`、`origin_ref` 指回诏书的 issue，完全复用 issue 既有机制：bar=履行/补齐进度、`ongoing_effects`=每月动作、status、报告「待办未解」已会列。**判据（用户务实拍板）**：圣旨跟踪理想该独立成线，但那改动太大；issue 已具进度/留痕/收尾/呈现/溯源，**先务实塞进 issue**。不新 kind、不新表。

### D2 最小 schema/参数改动
- **cap 10→15**（`issues.py` `initiative_active >= 10` 那处）——承诺与国策共用名额，放宽免得承诺被名额挤掉（小改，不另设承诺专属池）。
- **`end_turn INTEGER DEFAULT 0`**（仅「连续 N 月/半年为限」硬时限用；立项 `end_turn = turn + N`，到期停账）。
- **`stop_condition TEXT DEFAULT ''`**（「直到补齐」用；复用 `_gate_passed` 的 `{key: "比较式"}` 语法，同 `legacies.clear_gate`）。⚠️ **必须用可求值的带表前缀 key**——裸 `arrears` 会被 `_eval_gate_key` 判 None→恒不通过→承诺永不停（R3-high）；正确形 `army.<id>.arrears<=0`，多军补饷用 `_gate_passed` 的多 id 聚合 `army.关宁军|蓟镇.arrears.sum<=0`（`issues.py` `_eval_gate_key` 支持 id 列表 + sum/max/min/avg）。创建端须把诏书「边军」映射到具体 army.id 集合。
- **收尾区分不另加列**：用既有 `resolution_summary`（叙事）+ `issue_advances.trigger_kind`（`expire` vs `cancel`）区分「到期收尾」与「玩家撤销」（R3-medium：避免与 `resolution_summary` 重叠造冗余列）。〔撤回上一版加的 `close_reason` 列。〕
- **bar = 履行/补齐进度**，立项 **`inertia=0`（显式；`expected_months` 省略即回落 inertia=0）**，bar 由 `stop_condition`/真进度推、不靠 random inertia 自漂——免得假性了结。漂到 100（补齐）=真了结，与 `stop_condition` 一致。〔取代 R1 误加的「bar-exempt」：bar 不剥离、当进度用。〕**注：`ongoing_effects` 的 bar 折扣只折 metrics、不折 economy（`issues.py:2820` `_apply_economy_list` 传原始 economy，已三次核实）→ 补饷（economy）额恒定、无「越补越少」（codex R2/Claude R3 该处过度声明，纠）。**
- **承诺 issue 须 `cancellable='decree'`**（皇帝可无损撤自己的承诺）——否则落 `_normalize_cancellable` 默认 `by_progress`、撤回走「此事非诏可消」+皇威 −2，语义荒谬（R3-high）。创建端写死，不靠 LLM 默认。

### D3 三形态 → 载体落点
| 形态 | 载体 | 终止 |
|---|---|---|
| ① 直到补齐（每月 X 直到条件） | issue + `ongoing_effects`（每月 X） | `stop_condition`（如 `arrears==0`，code 判）→ resolved |
| ② 时限（连续 N 月/半年） | issue + `ongoing_effects` | `end_turn` 到期 → 停账收尾 |
| ③ 未来一次性（X 月后复试/复核） | issue + `end_turn`（**无 ongoing、无 firing 机制**） | `end_turn` 到期：issue 仍 active → simulator/核销自然 surface 一句话，**至多结算弹一个现有事件选项**（复用 candidate_events/HITL 决策块，不建专门 firing） |

- ①②可叠（先到者停）。开放式承诺（`stop_condition` 永不达成 + `end_turn=0`）= 有意永久挂账、皇帝可主动撤。
- **形态③刻意最小化（用户拍）**：不存 firing payload、不建注入槽、不挂 0011-5。但 ⚠️ **光靠「issue 到期 active → LLM 核销自觉提」会被 `season_simulator.md:9`「active_issues 仅背景、不可触发新动作」压住、复现 #136 到期没人提**（R3-medium 实证）。故 form③ 唯一**必需的最小机制** = 结算扫到 `end_turn<=turn` 的 form③ → 把它**从背景 active_issues 提升为「本回合到期待裁」显式项喂 simulator/核销**（仿密令到期送核议 `decree.py:350` 的程序注入模式）。这一个轻信号即可（不是 R1 那套 firing payload 重机制）；之后「至多结算弹一个现有事件选项」让皇帝拍。〔撤回 R1 的 firing_kind/firing_payload 列 + due_commitments 注入槽，只留这一个到期顶出信号。〕

### D4 钱类承诺 → 喂现有 arrears 还款池（损耗为意图、v1 待 #44/#67）
「补饷」类承诺的每月 X **喂进现有 `_auto_pay_arrears_by_priority`（flows.py:227）的还款预算**——真按优先级还各军 `armies.arrears`，不是单走一笔扣账（用户拍：要真减欠饷）。**设计意图**：补饷该有损耗——截流、贪污使实际到账 < 名义拨款，「直到补齐」才是真挣扎（钱一直拨、层层克扣、降得慢，合明末味）。⚠️ **但 v1 给不了**：现 `_auto_pay_arrears_by_priority`（`flows.py:252` `pay=min(arrears,budget)`）**全额到账、零损耗** → **本 ADR v1 补饷无损耗、arrears 准时即按额减；「真挣扎」须待 #44/#67 损耗建模（代码损耗率/吏治调制/密令查贪可减损）落地、本契约不交付**（别误读为本 ADR 即给挣扎感，R3-high）。本契约只负责「每月 X 喂进还款池 + 直到 `arrears==0` 停」；「直到补齐」依赖 **#44** 先修好 arrears 累计（否则数不准、停不对）。

### D5 创建端（extractor）：承诺路由规则（#136 主修）
玩家旨意含「今后每月 X / 连续 N 月 / 直到补齐 / X 月后复试」等**未来/时限/周期**语义 → 路由为带 `ongoing_effects`（+视情 `end_turn`/`stop_condition`）+ `origin_ref` 的 `new_issue`。这是 #136 真洞（实证 extractor 当时啥 issue 都没产、只一次性 economy_move）。现状三重门（边军月饷当固定流不重写 / 非新科目不触发 fiscal_create / `new_issue` 门只收工程改革案）需放行承诺类。

### D6 检查端（结算事务内）+ 诏书核销读结构化
- 每回合对 active 承诺 issue：跑 `stop_condition`（`_gate_passed` code 判，如 `arrears==0`）达标→收尾；扫 `end_turn>0 AND end_turn<=turn` 到期→停账收尾。均在结算后半段 `applier.atomic` 内（随原子、不破 `assert turn==before+1`）。
- **诏书核销改读结构化承诺状态**：现「诏书核销」是 LLM 每回合现编（`season_simulator.md` 诏书核销章），context 压缩即丢。改为**读 active 承诺-issue 的履行进度/状态**，核销基于结构化事实、不凭记忆——这才让「连续3月补饷」不会一月后没人记得。**数据通路**：用既有 `db.find_active_issue_by_origin(origin_kind,origin_ref)` / `list_active_issues` 取 active 承诺-issue → 经 `build_simulator_context` 把履行进度注入 simulator → 诏书核销章口径改「对带 `origin_kind=decree` 的 active issue 逐条报进度」（正向表述）。

### D7 有始有终（收尾 + 呈现）
- 收尾复用既有 status：补齐→`resolved`；到期未达成→`dropped`，**到期 vs 玩家撤销靠 `issue_advances.trigger_kind`（`expire` vs `cancel`）+ `resolution_summary` 叙事区分，不加 `close_reason` 列**（复用既有、避免冗余，R3-medium）。新增 `expire_commitment` 收尾路（标 `dropped`、写 `issue_advances(trigger_kind='expire')`、**不跑 resolve/fail 效果**），不复用会放效果的 `close_issue('resolved')`。
- 每月兑现写 `issue_advances`；报告「待办未解」已会列承诺（`origin_kind=decree` 玩家可见：「边军月饷·已第 3 月·直到欠饷补齐」）。承诺=皇帝看得见始终的活账。

### D8 Provenance + 对齐已有（不造平行第二套）
- `source=player_decree` + `origin_ref` 溯源；**用 `origin_ref` 不用 `source` 硬 reject**（避孙承宗 `system_simulation` 坑，同 #158 教训）。
- **#45/#46**（结案强制配对，现 warn-only）：承诺载体成为其检查对象、升级为「凭承诺载体强制」；改写其「后果当回合一次性配齐」假设（承诺后果未来逐月发生）。
- **#67/substrate**：财政类承诺未兑现对齐 substrate 语义（停饷成债 等）；cutover（待 M0 #73）后财政类承诺归约 substrate Due，现暂落全局。冲突按 later-doc-wins。

## Considered Options
- **新建 `commitments` 表 / dedicated `kind`**：否决——issue 已具进度/留痕/收尾/呈现/溯源全套，新表/新 kind = 平行第二套 + 重建这些；用户务实选 reuse。
- **形态③建完整 firing 机制**（pre_settle 注入槽 + firing payload + 接 0011-5）：否决（用户拍）——v1 过重；最小化到「issue + end_turn + 至多结算事件选项」，robust firing 留后。
- **bar-exempt（剥离 bar）**：否决——bar 正好当履行/补齐进度用（用户点破「欠饷还差多少补齐就是进度条」），改为按真进度驱动、不给 random inertia。
- **补饷单走一笔扣账（不喂 arrears 池）**：否决（用户拍）——不真减各军 arrears、「补齐」无意义、且抹掉截流/贪污损耗的明末味。
- **给 `_gate_passed` 加 turn gate key**：否决——`end_turn` 显式列更干净。

## Consequences
- #136 解决：承诺有结构化载体 + 直到补齐/到期收尾 + 诏书核销读结构化 + 有始有终；「每月 50 万补饷」「三月后复试」不再丢。
- **真改动小**：cap 一行 + `end_turn`/`stop_condition` 两列 + extractor 路由 + 补饷喂 arrears 池 + 核销读结构化 + 形态③一个到期顶出信号；issue 全套复用、**不新表、无重 firing 机制**。
- 依赖 **#44**（arrears 累计）才能让「直到补齐」准；损耗（真挣扎）亦待 #44/#67；财政类承诺与 substrate cutover 后归约 Due。
- restore 无损：承诺当回合全量落库（`ongoing_effects`/`end_turn`/`stop_condition`/`origin_ref`），崩溃续跑不靠记忆（P1）。
- 实现属编码（spawn 隔壁）：cap 放宽 + 两列迁移（`end_turn`/`stop_condition`）+ 承诺 issue 建 `inertia=0`/`cancellable='decree'` + extractor 路由 + 补饷接 `_auto_pay_arrears` + 结算两扫描（`stop_condition` 求值 + `end_turn` 到期）+ 形态③到期顶出信号（仿密令送核议）+ 核销读结构化 + `expire_commitment` 收尾路 + 呈现。
