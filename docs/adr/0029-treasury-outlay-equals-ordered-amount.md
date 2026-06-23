# 库出账 = 下令额：火耗/腐败数字移出 LLM 拨款视野（interim；结构真解见 #360）

Status: Proposed（2026-06-23，grill #341；真因定位后重写——markup 是「财政盘面把火耗/腐败数字喂进了 LLM」造成的）

## 背景（真因，核代码 + 用户定位）

dogfound F11：玩家下令拨 N，库实扣 ≈ N×1.1（西学令 50 → 扣 56、清丈令 10 → 11、补饷 60 → 67）。核代码：
- **扣钱代码零 markup**：`flows.py` 解运比/实收率函数都 `return 1.0`，`_apply_economy_list` 精确扣 delta、不乘任何率；`issues.py` 也没给拨款 economy 套火耗。库扣 = extractor 给的数。
- **simulator prompt 早写对了**：`season_simulator.md:56`「出账一笔银，沿途火耗截留只影响『办成多少事』、不另立截留支出」。

**真因（用户 2026-06-23 定位）= 财政基座（ADR 0007）把火耗/腐败数字喂进了 LLM 盘面**：
- `corruption`（腐败度）喂进 simulator 盘面（`simulation.py:330`）+ extractor 盘面（`:564`）；`content/regions.json:178` 有「火耗率 0.2」；extractor prompt 把腐败度当一个轴（赈银被吞/胥吏盘剥）。
- LLM 一看见这些数字，就「懂事」地把它摊到拨款上（库出 = 下令额 ×(1+耗)）。**加财政前盘面没这些数 → LLM 没东西可摊 → 库出=下令额自然成立。** 即 markup 不是 LLM 天性，是被喂了数字诱导的。

## 决定（interim 修法）

**把火耗/腐败的具体数字移出 LLM 的拨款视野**——回归加财政前「LLM 看不见」的状态；LLM 至多**定性知道「有腐败/火耗这回事」、不见具体率/数**。
- 火耗率 / 腐败度**不作为数字**进 simulator/extractor 的拨款路径；若需 LLM 叙事腐败，给**定性档**（「吏治腐败」）、不给数。
- 火耗 100% 留引擎征收侧（ADR 0007：引擎算）；LLM 拨款路径里一个率都没有 → 没东西可摊 → **库出=下令额**。
- 这是接口层 keystone（CLAUDE.md「别让 LLM 自己数数」）：火耗是确定性引擎数学，喂率给 LLM 就是请它数数。

## 结构真解（非本 ADR）

本 ADR 是 **interim**（拿走诱因）。结构真解 = **#360（结算反转：圣旨机械后果代码先确定性落库、simulator 在 committed 盘面推演）**——那时拨款额由代码落、LLM 根本不产，库出=下令额 by construction。本 interim 先把数字从 LLM 拿走，等 #360 架构反转再根治。

## Considered Options
- **parse 下令额 + guard LLM 输出**：否决——治标（LLM 已被诱导再去拦），且 NL 解析脆。
- **靠 prompt（`season_simulator.md:56` 已写、被忽略）**：不够，prompt 拦不住（keystone）。
- **结算反转（#360）**：是真解，但大、依赖 #150，另立；本 ADR 只做 interim。

## Consequences
- 库出=下令额恢复（LLM 无率可摊）。
- 腐败度 extractor 仍可按叙事调（赈银被吞 → 腐败度 +5）——那是它**改**腐败度、非摊到拨款；但拨款路径不给它腐败/火耗的**数字**。
- 损耗（到手 < N = 中饱/拨付侧）的建模留 cutover / ADR 0007，永不表现成「库出 > N」。
- 范围：#341（interim）；真解：#360。
