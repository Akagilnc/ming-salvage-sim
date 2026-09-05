# #1745 诊断举证（r3 诚实记录）

**状态：A 验收仍 open（A1/A2/A3 均未证）。本文件只记账，不闭合验收，不自动选 B1。**

票面 A 要求：以 QA 存档 / error pack / 真实回路判定属
- **A1** 数据侧坏引用（提案引用的拨帑从未在途）
- **A2** 账本时序（提案合法但在途拨帑已在同月结清/撤回）
- **A3** 代码异常（状态机/相位）

下列分两栏：**已有结算标识/产物/抛点** vs **完整生成输入与目标史（缺）**。

---

## 1. 已有（结算标识 · 产物 · 抛点）

来源（可独立核对）：

| 材料 | 真源 |
| --- | --- |
| git `414207be` `qa-evidence/w11-20260905-8010/` | QA 分支 `origin/qa/w11-20260905-8010-screenshots` |
| 本 run 冻结附件 | `02`–`06`（delta / manifest / traceback / pending / REPORT） |

### 1.1 manifest（时间 / digest / 抛点标识）

- `turn=2` · `year=1627` · `period=11` · `attempt=2`
- `timestamp=2026-09-05T07:21:14.468605+00:00`
- `ready_payload_digest=ec384e8cdac5594e32b7553ce8b51e06b61e939108598a4104547604482e49e6`
- `exception_type=ValueError` · `exception_message=无在途拨帑却收到对账提案`
- `db_path=/Users/akagilnc/WorkSpace/Ming_LLM/data/ming_sim_1788591381068174000.db`
- `version=0.53.0.0`

**范围**：结算失败时刻的标识与 digest。**不是** extractor/simulator 生成输入。

### 1.2 delta（结算输出 / 提案原件）

`dossier_reconciliations` 唯一项：

```json
{"dossier_id": 20, "arrived_amount": 82}
```

同批相关输出（非完整输入）：

- `dossier_executions`：dossier 1 degraded；16 fulfilled（毕自严清核）；**20 fulfilled**（「内帑三十万两已足额拨付关宁军」）
- `issue_advances`：issue 2 叙述「国库拨关宁军八十七万两，实到宁锦约八十二万两」

**范围**：extractor 产出的 delta 产物。**不能**单独证明提案时点 targets 是否为空、dossier 20 是否曾在途、是否同月已结清。

### 1.3 traceback（旧抛点）

```
decree.settle_with_delta
 → _settle_after_extract_body
 → db.record_monthly_grant_reconciliations
 → ValueError: 无在途拨帑却收到对账提案
```

证旧路径在「无目标 + 非空 generated」时整月 abort。与现修 B1 条件行为相关，**不**代替 A 分类。

### 1.4 pending.json（原局待批 · turn1）

两条 turn=1、status=pending 的 `directive/拟旨`（毕自严）：

| id | dossier_action_type | target_kind | 摘要 |
| --- | --- | --- | --- |
| 1 | policy | policy | 清核太仓出纳、暂缓非急工役、**优先拨发辽东边饷** |
| 2 | assignment | issue | 户部亏空…清核太仓… |

**能分清的**：

- 待批清单是 **turn1 拟旨**，不是 turn2 结算前的在途拨帑账本快照。
- 两条均 **policy/assignment 拟旨**，payload **无** `grant_allocation` / `amount` / `execution_surface=in_transit` 结构化拨帑成案字段。
- 因此 pending **不能**证明 turn2 时 dossier 20 是否已颁布为在途拨帑；也 **不能**证明 20 是否「从未在途」。

**分不清的**：拟旨经批红/颁布后是否在 turn1→turn2 间生成过 grant 案卷 20；若生成过，结算前是否仍 executing / 已 close / 已撤。

### 1.5 REPORT.md（QA 叙述）

- 确认 Nov turn2 对账 ValueError 可复现；error packs `turn2_attempt2` / `turn2_attempt3`
- UI 入空 `awaiting_decision`；「续跑结算」可进十二月（非根治）
- 关联：双 pending 拟旨、批红 draft 缺字段等——**旁证，非 A 分类充分条件**

### 1.6 路径存在性（本工作树）

- 本分支 HEAD **不含** `qa-evidence/w11-20260905-8010/` 树（证据在 QA 分支 / 附件）
- manifest 所记 `db_path` 在派单方核对时 `test -e` 返回 1：**只证该精确路径现不存在**，不证一切副本不存在（本局不扫工作树外目录）

---

## 2. 缺（完整生成输入 · 目标史 · 可恢复存档）

下列任一可支撑 A 分类；**当前皆缺**：

1. manifest 指向的存档 `.db`（1627-11 结算失败时刻或之前的可恢复副本）
2. dossier 20 状态/执行史（建案 → 拨帑颁布 → 在途/结清/撤回各步）
3. turn2 结算前 `list_monthly_grant_reconciliation_targets`（或等价）目标快照
4. 原局 turn1/turn2 simulator / extractor **生成输入**（邸报正文、盘面 TSV、shared context、喂给 extractor 的完整材料）

无以上材料时：

- **不能**裁 A1（无法证「从未在途」）
- **不能**裁 A2（无法证「曾在途且同月已结清/撤回」）
- **不能**裁 A3（无法证状态机/相位代码错；现有栈只显示域级 ValueError 抛点）

故 **A1/A2/A3 = 均未证**（不是「三者被排除」）。

---

## 3. pending × delta 交叉（能分清多少写多少）

| 观察 | 结论边界 |
| --- | --- |
| delta 提案 `dossier_id=20, arrived_amount=82` | 有对账提案原件 |
| 同批 execution 称 20 fulfilled「内帑三十万两已足额拨付」 | 模型**叙事**上把 20 当已拨付案；是否曾为账本在途目标**未证** |
| issue 叙述 87 万拨 / 82 万到 | 与 arrived_amount=82 同量级叙述，仍是产出侧 |
| pending 仅 turn1 拟旨、无 in_transit grant 结构 | 不能桥接「20 的账本生命周期」 |
| 抛点「无在途拨帑」 | 失败**当时** targets 为空或等价；**为何**为空（从未有 / 已结清 / 其它）未证 |

**禁止推断**：不得因「pending 无 grant 结构」或「execution 已 fulfilled」在缺 DB 史时预钉 A1 或 A2。

---

## 4. 缺前置与索取对象

- **缺前置**：上§2 材料（存档 DB / dossier 20 史 / 目标快照 / 完整生成输入）任一可恢复件
- **索取对象**：QA 持卷者
- **索取通道**：票 #1745 评论（派单方 2026-09-06 已留言三点清单）
- **本局不做**：虚补历史状态、手设诊断族、把条件性 missing_ref（B1 行为面）写成 A 已裁；不把本文件或修理 `completed` 写成验收 A 闭合

B 支验收：A 未裁前，B1/B2/B3 **无一生效为验收闭合条件**。现有逐项拒收等为实现层条件行为，**不得**顶替票面 A 分类。

---

## 5. 修订

| 轮次 | 记要 |
| --- | --- |
| r3 | 附件 02–06 + git 414207be 对读；分栏记录；A1/A2/A3 未证；缺前置→QA 持卷者 |
