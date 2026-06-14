# ADR 0011 设计深挖 — STATE（一眼恢复索引）

> **这是什么**：ADR 0011（actor 博弈：圣旨阻力网 + 离心账本）的设计深挖工作存档。承 GitHub #112 tracker。**设计累积，未写进 ADR 正文**（待批量 fold + CMR r2 修一起落）。
> **位置**：`docs/adr/0011-design-dig/`，分支 `design/0011-actor-resistance-adr`。
> **细节三文件**：[dig-1 派系功能](dig-1-faction-function.md) / [dig-2 外压整合](dig-2-external-pressure.md) / [dig-3 资源经济](dig-3-resource-economy.md)。

## ⚠️ 重验日志 2026-06-14（隔壁开发推进后，对承重 claim 重新 query 实际系统）
触发：用户问"隔壁开发推进了，你之前说的没完成的东西还靠谱不"。结果：**4 条承重判断全部仍成立，2 条过时（都不致命）**。

| claim | 重验结果 | 证据 |
|---|---|---|
| 血债/离心棘轮零实现（= 总解锁前提） | ✅ 仍成立 | `grep 血债\|ratchet\|grudge ming_sim/*.py` 命中 0 |
| B1/#9 阉党退场 leverage 不联动（决定8 根因） | ✅ 仍成立 | #9 仍 OPEN |
| 召对无 location 闸（FF-4 net-new） | ✅ 仍成立 | `summon_minister` 仍纯透传 `__summon__{name}` |
| status enum 无"称病"（FF-5） | ✅ 仍成立 | 8 态：active/offstage/candidate/dismissed/imprisoned/exiled/retired/dead |
| FF-4 依赖"0009 location 落地" | 🔄 过时·好消息 | 0009 **#106 已 MERGED**(2026-06-13)，`location`/`transit_to` 真字段+invariant；依赖已满足。但召对仍不 gate、仍无在途时间(#93)→ 要加的活不变 |
| "#70 cutover 被 deferred" | 🔄 过时·框架修正 | #70 step1(史实重标)正被另一 session 跑(PR#113 纯 doc OPEN)；那是基座精度**不是** cutover；#70 ≠ 我的加征反噬/寅吃卯粮(不撞，同片地，build-upon) |

**已 merged 的相关线**：#106(ADR 0009 实现 C1)、#110(#66 财政基座 port, 0.11.0.0)、#111(release polish)。**在跑**：#70 step1(PR#113, fiscal-70-remark 分支)。

## 三维度状态
| 维度 | 状态 | 产出 |
|---|---|---|
| 派系功能 | ✅ 收口 | 决定 8 草案（dig-1） |
| 外压整合 | ✅ 收口 | 决定 9 草案 + 决定 1/2/3/8 细化（dig-2） |
| 资源经济(具象) | ✅ **方向已挑**（HOW 未设计） | 4 recommend 认(方向)；带宽=批红积压(暂定,最虚)；亲临 defer；6 maybe/2 cut 未过（dig-3） |
| 呈现层 P4 | ⏸ PARKED | — |

## 决定清单（待 fold 进 ADR 0011）
- **决定 8（派系功能）**：每派一条承重功能（供给面），走光=失能、惹毛=反咬（同轴两 failure mode）；功能数不设配额（按实际）；接触途径分层（召对 location 闸，蹭 0009 不碰 #93）；不发明新机读态（落 factions离心/issues/裁判规则）；P4 定性。dig-1 全文。
- **决定 9（外压集成）**：外压=破局压力引擎；前半截(外压→逼旨)已大半接好(gate 机器现成)；net-new 承重=血债棘轮①/三饷传导②/power_tick③/leverage联动④/华夷轴不对称⑤；困境链(三饷绞索/攘外安内/暴君螺旋)每条留真出路；后宫/外戚/监军 defer(剧本-gated)。dig-2 全文。
- **决定 1 细化**（Q1）：确定性账本只累积、永不内嵌判负；判死分层(结局层)；确定性因果链可全做，只守"账不判死 + 出路杠杆恒可达"。
- **决定 2（血债棘轮）= 优先收口 = 总解锁**：schema 待定(逐派列vs新表/算式=基础×合法性系数+同类防备底/不变式：阻力·称病只读·不可跨派冲抵)+ parked CMR r2 修(provisional/H5/净负 钉最低契约)。
- **决定 3 细化**（Q4）：入轴判据软化"真实价值张力、不要求对称、史实不对称按史实"；华夷轴不对称(主和极 emergent 高血债杠杆)，待复核 flag 收口。

## ⚡跨线强信号
外压 workflow + 资源 workflow 各自独立都指回：**血债/离心棘轮 schema 收口 = 总解锁**（资源 menu 4 条 + 外压承重件 + 派系离心全压它上）。

## Roadmap
1. ~~挑资源 menu~~（甲）✅ **方向已挑**（4 recommend 认 + 带宽=批红积压暂定）。**但全是"方向"非"HOW"**——三维度至此都只到"方向/决定"层，机制/schema 设计是下一层。用户明确感知："都不知道怎么做"。
2. **收口血债棘轮 schema**（乙）🟢 **schema 草案 + 用户拍板收敛**（详见 [dig-4](dig-4-blooddebt-schema.md) 末「用户拍板收敛」节）：fan-out 出骨架(方案1+审计账+净负冻土/薄冰)，用户**覆盖了 5 推荐**——①粒度=**42 格逐派×轴**(喂叙事，非 scalar；决定3 矩阵从defer变现在填) ②"合法性"反了→改名**失称度**(罚配不配罪) ③中旨**按历史·钱没了就是没了**(=牙非缺陷，溶解 fork4 escrow；跟四层票拟一起做) ④**罪与罚账第一刀就建**(轻、像42为叙事存状态，非查案系统；罪罚判定回归直觉) ⑤**seed-guilt 开局预装罪**(人人有点脏阉党最多；白送悲剧弧+厂卫致盲扣) ⑥信息=大面公知/具体在相关人手(actor-mediated非搜证) ⑦血债=朝堂7派专属。**北极星**=东林查隐田90分体验([north-star-90fen.md](north-star-90fen.md))。
   - **待办**：谁有罪=**查史实**(seed 预装数据)；后期大臣再犯罪=后话；provisional/中旨闸仍 defer 第二刀。
3. fold 决定 8/9 + 细化 → ADR 0011 + 应用 parked CMR r2 修。
4. 承重落地洞 → sub-ADR。
5. 恢复 CMR 走完，再让 0011 落 main。

## ⚠️ 设计哲学更正（2026-06-14，用户纠 P3 理由）
- 拒科技树/国策树**不是**因"稀释悲剧"，是**皇帝角色保真**（皇帝面前不该有能点的科技树/进度面板）。同根=拒换兵种微操、P4 皇帝无表、actor 博弈>资源按钮。
- **不是非悲剧**：feel 参照 = 冰汽时代1（高压求生+硬取舍+**真能破局成功**）。
- **长线发展/科技不是禁区**，只要 diegetic（经旨意/朝局/奏报涌现，非面板点节点）。禁的是面板形态，非发展本身。
- **判据**：问"皇帝会不会坐这面板前点它"，不是"它给不给出路"。详见 memory [[emperor-role-fidelity-frostpunk-feel]]。
- ⏳ 待办：CLAUDE.md 的 P3 那句"稀释悲剧"理由需更正（待用户授权 + 走 main 向 worktree，当前树在 fiscal-70 别人分支）。

## 工作纪律
- 本 session = **设计为主，编码 spawn 隔壁**（用户明示，memory design-vs-coding-session-split）。
- 状态结论先 query 实际系统（本重验日志即此规矩的执行）。
