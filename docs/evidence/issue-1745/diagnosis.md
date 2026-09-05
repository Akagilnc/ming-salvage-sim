# #1745 诊断举证（r5 同步 · A 已裁）

**状态：A1 成立 · A2 不成立 · 原整月 ValueError 属 B1 拒收粒度缺陷 · B1 生效 · B2/B3 不适用 · 不启用独立 B3 分支。**

票面 A 分类（本庭 r5 已裁）：
- **A1** 数据侧坏引用（提案引用的拨帑从未在途）— **成立**
- **A2** 账本时序（提案合法但在途拨帑已在同月结清/撤回）— **不成立**
- **A3** 代码异常（状态机/相位）— 原整月 abort 是拒收**粒度**缺陷，按 A1→B1 修复；**不**证明另有状态机/时序异常，**不启用 B3**

本文件 r3 曾因缺原局 DB/生成输入诚实记「A1/A2/A3 均未证」；r5 派单方已补原件，本庭只读查证后结清。旧「未证」结论仅作下方修订表历史，**不得**继续声明当前缺前置。

---

## 1. 已有（结算标识 · 产物 · 抛点 · 原件）

### 1.0 r5 冻结原件（A 分类真源）

| 材料 | 指针 |
| --- | --- |
| 派单方 runner 举证包（冻结附件） | runId `01a07260-880a-7850-b545-ed6bfa384c2f@fixer` · 角色 修内司 · 附件 `01-1745-runner-evidence-A.md` |
| 原件目录 | 仓内相对 `data/error_packs/turn2_attempt2/`（原件包名 `turn2_attempt2`） |
| 原件工作副本 | 同包名临时工作副本（与上列原件同内容；不保留机器临时目录拓扑） |
| `save_backup.db` | 上列原件目录内；失败时刻存档备份（2,187,264 B） |
| `resolve_context.json` | 上列原件目录内；含 `simulator_payload` / `narrative` / `extracted` / `decree_text` |

只读 SQL（`save_backup.db`，game_state turn=2 / 1627-11）核得：

- `decree_dossiers` id **20**：`action_type=grant_allocation` · target=army/guanning · 内库 30 万 · `execution_surface=immediate` · status=**closed** · outcome=**fulfilled** · note=成案时足额拨付 · created_turn=2 · closed_turn=2 · closed_at=2026-09-05 07:20:30
- `decree_dossier_decisions` id **18**：dossier 20 · turn 2 · promulgated · 07:20:30（建案/关闭同秒）
- `decree_dossier_reconciliations`：**0 行**（全表空）
- `economy_ledger` turn 2：
  - 行 **125**：内库 −30 · origin_ref=`dossier:20` · 成案即落账，无在途
  - 行 **66**：国库 −87 · 边饷 hub · dossier_id 空 · 引擎固定财政 tick，非案卷拨帑

`resolve_context.simulator_payload`：

- `reconciliation_inputs: []`（引擎明确：本月无在途拨帑待对账）
- `treasury_brief` 片段：「边饷结算：国库实拨87万两，实际到达82万两，途中损耗5万两。」→ hub 行 66 呈现，**不是** dossier 20
- 产出：`narrative` 述 87/82；`extracted.dossier_reconciliations=[{"dossier_id":20,"arrived_amount":82}]`

**A1 成立要点**：82「实到」来自边饷 hub（行 66，无 dossier）；dossier 20 是内库 30 一次性即付、成案已 closed；提案把 hub 到达额挂到唯一拨帑案卷上。
**A2 不成立要点**：`reconciliation_inputs=[]`，引擎未提供任何对账输入；无「合法在途提案 + 随后结清/撤回」史。
**事实边界**：82 与 hub 输入/叙事**对应**可观察；**不**把模型内部因果当已证。`treasury_brief`「实拨/实际到达/途中损耗」与拨帑对账口径同形，记为可观察的混淆关联，**不开 prompt 处方**。

### 1.1 manifest（时间 / digest / 抛点标识）

来源：git `414207be` `qa-evidence/w11-20260905-8010/`（QA 分支）及既有冻结附件 delta/manifest/traceback。

- `turn=2` · `year=1627` · `period=11` · `attempt=2`
- `timestamp=2026-09-05T07:21:14.468605+00:00`
- `ready_payload_digest=ec384e8cdac5594e32b7553ce8b51e06b61e939108598a4104547604482e49e6`
- `exception_type=ValueError` · `exception_message=无在途拨帑却收到对账提案`
- `db_path` 原件名 `ming_sim_1788591381068174000.db`（原运行时路径已被游戏归档/覆盖；**可恢复件**见 §1.0 `save_backup.db`）
- `version=0.53.0.0`

### 1.2 delta（结算输出 / 提案原件）

`dossier_reconciliations` 唯一项：

```json
{"dossier_id": 20, "arrived_amount": 82}
```

同批相关输出：

- `dossier_executions`：dossier 1 degraded；16 fulfilled；**20 fulfilled**（「内帑三十万两已足额拨付关宁军」）
- `issue_advances`：issue 2 叙述「国库拨关宁军八十七万两，实到宁锦约八十二万两」

与 §1.0 对读：execution/issue 叙事与 hub 87/82 同形；提案 82 挂 dossier 20——即 A1 错引的产出面。

### 1.3 traceback（旧抛点）

```text
decree.settle_with_delta
 → _settle_after_extract_body
 → db.record_monthly_grant_reconciliations
 → ValueError: 无在途拨帑却收到对账提案
```

`record_monthly_grant_reconciliations` 对错引的 **ValueError 拒收本身正确**；错在拒收粒度（整月 abort）——即 **B1** 处置面，不是独立状态机/相位 A3/B3。

### 1.4 pending.json（原局待批 · turn1）

两条 turn=1、status=pending 的 `directive/拟旨`（毕自严）：

| id | dossier_action_type | target_kind | 摘要 |
| --- | --- | --- | --- |
| 1 | policy | policy | 清核太仓出纳、暂缓非急工役、**优先拨发辽东边饷** |
| 2 | assignment | issue | 户部亏空…清核太仓… |

待批是 turn1 拟旨，**不是** turn2 在途拨帑快照；无 grant 结构。A 分类真源已改由 §1.0 DB/生成输入承担；pending 仅作旁证，不单独定 A。

### 1.5 REPORT.md（QA 叙述）

- 确认 Nov turn2 对账 ValueError 可复现；error packs `turn2_attempt2` / `turn2_attempt3`
- UI 入空 `awaiting_decision`；「续跑结算」可进十二月（非根治）
- 关联旁证（双 pending、批红 draft 缺字段等）——**非** A 分类充分条件；分类以 §1.0 为准

---

## 2. 缺卷栏（r5：A 分类前置已结清）

| 项 | r3 时 | r5 时 |
| --- | --- | --- |
| 存档 `.db`（失败时刻可恢复副本） | 缺（manifest 路径不在） | **已到卷**：§1.0 `save_backup.db` |
| dossier 20 状态/执行史 | 缺 | **已核**：immediate / closed / fulfilled / 同秒建闭 / ledger 125 |
| 结算前对账目标 | 缺 | **已核**：`reconciliation_inputs=[]`；reconciliations 表 0 行；无在途 |
| simulator/extractor 生成输入 | 缺 | **已到卷**：`resolve_context.json` |

**当前不声明缺 A 分类前置。** r3「均未证 / 材料当前皆缺」已过时，见 §5。

仍保留的**非缺卷**边界（不是索取项）：

- 不把模型内部「为何选 20」的因果当已证
- 输入措辞（treasury_brief 同形口径）只作观察，不开 prompt 处方
- 本票解决坏对账引用拖垮整月并形成空待批假状态；**不是**提升模型生成质量

---

## 3. 交叉结论（A 已裁）

| 观察 | 结论 |
| --- | --- |
| delta 提案 `dossier_id=20, arrived_amount=82` | 对账提案原件；82 对应 hub 叙事/brief，**非** dossier 20 拨额（30） |
| DB：20 = 内库 30 immediate 成案即付已 closed | **从未在途** → 支撑 A1 |
| `reconciliation_inputs=[]`；reconciliations 0 行 | 引擎未给对账输入；**无**合法在途后结清史 → A2 不成立 |
| ledger 66 hub 87 无 dossier；ledger 125 绑 20 | hub 与案卷拨帑两条线；错引把前者挂到后者 |
| 抛点「无在途拨帑却收到对账提案」 | 对 A1 错引的正确域级拒收；整月 abort = **B1 粒度**问题 |

---

## 4. 索取栏与 B 支

- **索取**：A 分类所需原件已由派单方补齐（§1.0）；**无现行缺前置索取**
- **B1 生效**：坏对账引用不得拖垮整月；经 canonical RejectedItem / collector 留痕，不写假对账；合法 supplied 继续 clamp。实现与验收属结算接缝/测试 owner（既有 grant / rejection_wiring / full_chain / web_state 等案），本文件不扩生产或测试
- **B2 不适用**（非漏验收）
- **B3 不适用**；不启用独立 B3 分支（原 ValueError 整月中止按 A1→B1，不另证状态机/时序异常）
- **本文件边界**：仅诊断产物同步；不虚补、不改 prompt、不改治理法

---

## 5. 修订

| 轮次 | 记要 |
| --- | --- |
| r3 | 附件 02–06 + git 414207be 对读；当时缺 DB/生成输入，**诚实**记 A1/A2/A3 未证、材料缺、B 支无一生效为验收闭合条件；缺前置→QA 持卷者。该「未证」为**当时**状态，不是现行结论 |
| r4 | 取证归派单方；禁止修内司虚补 |
| r5 | 派单方补 `save_backup.db` + `resolve_context.json`（指针见 §1.0 与冻结附件 `01-1745-runner-evidence-A.md`）。本庭裁 **A1 成立、A2 不成立、整月异常→B1、B2/B3 不适用**。本文件同步现行状态；旧未证仅留本表 |
