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
- **`stop_condition TEXT DEFAULT ''`**（「直到补齐」用；复用 `_gate_passed` 的 `{key: "比较式"}` 语法，同 `legacies.clear_gate`；可寻址 `armies.arrears` 等）。
- **bar = 履行/补齐进度**（由实际进度/arrears 派生，或 LLM 按真进度给），**不给 random `expected_months` inertia 漂移**——免得 bar 自漂到 100 假性了结。漂到 100（补齐）=真了结，与 `stop_condition` 一致。〔这取代 R1 误加的「bar-exempt」：bar 不是要剥离，是要当进度用、由真进度驱动。〕

### D3 三形态 → 载体落点
| 形态 | 载体 | 终止 |
|---|---|---|
| ① 直到补齐（每月 X 直到条件） | issue + `ongoing_effects`（每月 X） | `stop_condition`（如 `arrears==0`，code 判）→ resolved |
| ② 时限（连续 N 月/半年） | issue + `ongoing_effects` | `end_turn` 到期 → 停账收尾 |
| ③ 未来一次性（X 月后复试/复核） | issue + `end_turn`（**无 ongoing、无 firing 机制**） | `end_turn` 到期：issue 仍 active → simulator/核销自然 surface 一句话，**至多结算弹一个现有事件选项**（复用 candidate_events/HITL 决策块，不建专门 firing） |

- ①②可叠（先到者停）。开放式承诺（`stop_condition` 永不达成 + `end_turn=0`）= 有意永久挂账、皇帝可主动撤。
- **形态③刻意最小化（用户拍）**：不存 firing payload、不建 pre_settle 注入槽、不挂 0011-5；「X 月后复试」就是 issue 到期还 active → LLM 在核销/邸报提一句，需要时复用现有结算事件选项让皇帝拍。重 firing 机制留作日后（实测不够再说）。〔撤回 R1 加的 firing_kind/firing_payload 列 + due_commitments 注入槽。〕

### D4 钱类承诺 → 喂现有 arrears 还款池（含损耗，补齐不易）
「补饷」类承诺的每月 X **喂进现有 `_auto_pay_arrears_by_priority`（flows.py:227）的还款预算**——真按优先级还各军 `armies.arrears`，不是单走一笔扣账（用户拍：要真减欠饷）。**补饷有损耗**：截流、贪污使实际到账 < 名义拨款，故「直到补齐」是真挣扎（钱一直拨、层层克扣、arrears 降得慢，合明末味）。损耗的具体建模（代码损耗率 / 吏治调制 / 密令查贪可减损）归 **arrears/财政线（#44/#67）**——本契约只负责「每月 X 喂进还款池 + 直到 `arrears==0` 停」。⚠️ 「直到补齐」依赖 **#44** 先修好 arrears 累计（否则数不准、停不对）。

### D5 创建端（extractor）：承诺路由规则（#136 主修）
玩家旨意含「今后每月 X / 连续 N 月 / 直到补齐 / X 月后复试」等**未来/时限/周期**语义 → 路由为带 `ongoing_effects`（+视情 `end_turn`/`stop_condition`）+ `origin_ref` 的 `new_issue`。这是 #136 真洞（实证 extractor 当时啥 issue 都没产、只一次性 economy_move）。现状三重门（边军月饷当固定流不重写 / 非新科目不触发 fiscal_create / `new_issue` 门只收工程改革案）需放行承诺类。

### D6 检查端（结算事务内）+ 诏书核销读结构化
- 每回合对 active 承诺 issue：跑 `stop_condition`（`_gate_passed` code 判，如 `arrears==0`）达标→收尾；扫 `end_turn>0 AND end_turn<=turn` 到期→停账收尾。均在结算后半段 `applier.atomic` 内（随原子、不破 `assert turn==before+1`）。
- **诏书核销改读结构化承诺状态**：现「诏书核销」是 LLM 每回合现编（`season_simulator.md` 诏书核销章），context 压缩即丢。改为**读 active 承诺-issue 的履行进度/状态**，核销基于结构化事实、不凭记忆——这才让「连续3月补饷」不会一月后没人记得。

### D7 有始有终（收尾 + 呈现）
- 收尾复用既有 status：补齐→`resolved`；到期未达成→`dropped` + `close_reason='承诺到期'`（不引新 `expired` 枚举、不跑 resolve/fail 效果；新增 `expire_commitment` 收尾路、不复用会放效果的 `close_issue('resolved')`）。
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
- **真改动小**：cap 一行 + `end_turn`/`stop_condition` 两列 + extractor 路由 + 补饷喂 arrears 池 + 核销读结构化；issue 全套复用、**不新表、形态③零新机制**。
- 依赖 **#44**（arrears 累计）才能让「直到补齐」准；财政类承诺与 substrate cutover 后归约 Due。
- restore 无损：承诺当回合全量落库（`ongoing_effects`/`end_turn`/`stop_condition`/`origin_ref`），崩溃续跑不靠记忆（P1）。
- 实现属编码（spawn 隔壁）：cap 放宽 + 两列迁移 + extractor 路由 + 补饷接 `_auto_pay_arrears` + 结算两扫描 + 核销读结构化 + `expire_commitment` 收尾路 + 呈现。
