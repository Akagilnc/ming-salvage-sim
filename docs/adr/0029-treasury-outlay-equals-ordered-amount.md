# 库出账 = 下令额：拨款支出不套任何率，损耗全在下游

Status: Proposed（2026-06-23，grill #341 结晶；评审闸在 to-prd 之后，本 ADR 尚未评审）

## 背景

dogfound F11：玩家下令拨 N，库实扣 ≈ N×1.1（西学令 50 → 扣 56、清丈令 10 → 扣 11、补饷令 60 → 出 67）。

核代码（不信 F11 的「LLM 加的」结论、核真）：
- **扣钱代码零 markup**：`flows.py` 的解运比/实收率函数都 `return 1.0`（拨款侧无火耗代码），`_apply_economy_list` 精确扣 extractor 产的 delta、不乘任何率；`issues.py` 也没给拨款 economy 套火耗。库扣 = extractor 给的数。
- **simulator prompt 早写对了**：`season_simulator.md:56`「出账一笔银，沿途火耗截留只影响『办成多少事』、不另立截留支出」+ `:57`「换库等额、不产损耗」。
- ⇒ 56 是 **LLM（叙事或抽取）无视 prompt、自己给拨款套了 ~火耗率**。又一例 keystone：prompt 写对了也拦不住 LLM。

## 决定

**库出账 = 玩家下令额（令 N 扣 N），确定性认死。任何环节（LLM / 代码）不准对拨款支出套火耗、差役、解送或任何率。** 圣旨说出 100，库就出 100，绝不出 110。

- **损耗全在下游**：拨款的损耗是「收款方到手 < N」（拨付侧中饱），表现为「办成的事打折」，**绝不表现为「库出 > N」**。损耗建模 = cutover / ADR 0007（火耗=征收侧、中饱=拨付侧），不在本票；本票只把「库多出」这个错堵死。
- **enforcement = 确定性**：拨款额以**玩家下令额为权威**，承诺 / economy 载体认它，LLM 不得 re-inflate。靠 prompt（line 56 已写、被忽略）不够。补饷那条已有 ADR 0023 D7④（economy_moves clamp 到实际欠额）。
- **一个 issue、不拆**：库出=下令额是单条铁律，不分「补饷 / 承诺 / 火耗侧」多 issue。

## Considered Options
- **靠 prompt（season_simulator.md:56）**：否决——已写、LLM 仍套率，prompt 不可靠（keystone）。
- **拆成多 issue（补饷 / 承诺拨款 / 火耗建模分开）**：否决——库出=下令额是一条规则；下游损耗建模另属 cutover，但「库不多出」不可拆。
- **把损耗算成单独一笔库出支出**：否决——违背「换库/拨款不产额外库出」（`season_simulator.md:57`），且火耗是征收侧、不属拨款支出。

## Consequences
- 库账可信：玩家下令 N，库账永远扣 N，不再「令 N、扣 N×1.1」。
- 损耗（到手 < N）的实际建模留 cutover / ADR 0007（拨付侧中饱）；补饷归 ADR 0023。
- 范围：#341。
