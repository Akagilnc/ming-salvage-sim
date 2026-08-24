# #668 r1 增补快照：transit_arrivals × pending_resolve_context 恢复合同

- **source**: https://github.com/Akagilnc/ming-salvage-sim/issues/668
- **captured_at**: 2026-08-24T03:00:13Z
- **authority**: fixer apply（票面补钉 only；不施工业务代码、不新增缓存）
- **class**: `transit-arrivals-pre-settle-recovery-gap`
- **durable 真源**: 既有 `pending_resolve_context.simulator_payload.transit_arrivals`（零平行缓存）

以下摘录为 GitHub #668 后出修正案 r1 中与本缺口相关的 F4/F6/F7/F8 与 AC 对齐条文（全文以 issue 为准）。

---

### F4 结算链位置与当月叙事事实

- **调用点**：替换 `pre_settle` 内现 `force_transit_arrivals(...)` 调用——新 tick **仍在** `apply_event_terminal_states` / `auto_trigger_seed_issues` **之前**（门控读 location 前，在途者须先完成本月抵达；decree.py 既有教训）。
- **事务**：`commit=False` 由外层 `pre_settle` 原子提交（ADR 0008）；不得内层提前 commit。
- **叙事跟随（本票交付）**：删除 `_build_transit_nudge` / payload 键 `transit_nudge` / 其 data_note 旧措辞。改为向当月 simulator 输入投喂**本 tick 刚抵达**的事实集合（建议长期键名 `transit_arrivals`，shape 最小 `List[{"name", "location"}]`，按 name 稳定序）；语义＝「这些人本月已抵 `location`，请演出来」。
  - 只含**本 tick 抵达者**，不含仍在途者（仍在途语义量归 **#669** 的 `transit_semantics`，本票不建、不预留平行在途投影）。
  - 不喂剩余距离/系数/ETA 裸数（P4）。
  - **durable 承载（复用既有 `pending_resolve_context`，零平行缓存）**：`transit_arrivals` 须在 `pre_settle` 与 ready=0 `pending_resolve_context` 的**同一外层 atomic** 写入 `simulator_payload.transit_arrivals`；生命周期随该 ctx（完整 payload upsert 保留同键；`clear_resolve_context` 清除）。settling 重入组 simulator 时**只读该键**，不重跑 tick、不从 characters 抵达终态反推。fallthrough 再写 ready=0 占位时须合并保留该键，不得以 `{}` 整键覆写清空。
- **结算推进不变式**：`turn == before + 1` 类既有推进断言不破。

### F5 中断型

- 在途者 **status 迁出 active**（卒/下狱/流放/罢黜等既有 ousted 落点）当月起：**不再进入 tick 倒数、不产生抵达、不进 `transit_arrivals`**。
- 清账沿用 #667 已落地的迁出连带清四量（`transit_to`/remaining/factor/start_turn）；本票不另开清账写口。
- 验收：启程后、抵达前迁出 → 目的地 location 不变、ledger 全空、后续 tick 无该人抵达事实。

### F6 恢复（P1）

- **只读 DB** 即可无损重建：在途态（四量+location）与抵达后态（location=目的、四量空）。
- 断言：tick 中途 save → 关库重开 → 再 tick，与不中断连续 tick 的 location/ledger/抵达月一致。
- **「本 tick 刚抵达者」集合恢复（复用既有 `pending_resolve_context.simulator_payload.transit_arrivals`）**：崩溃窗口为 `pre_settle` 已提交（`turn_phase=settling`、抵达终态已写库）→ 至完整 `simulator_payload` / 推演输入持久化之前。此时 characters 仅剩抵达终态、局部 `forced_arrivals`/tick 返回值已不可见；settling 重入不得二次 tick。恢复路径：关库重开 → fallthrough 重跑推演时，从 `get_resolve_context(turn)["simulator_payload"].transit_arrivals` 读出集合，与连续路径**完全一致且只投喂一次**；财政/`pre_settle` tick 不二次执行。禁止新表/新列/进程内旁路缓存/从 location 终态反推/恢复时重跑 tick。
- **旧档不支持**（#667 r4 / owner 多次裁定）：不为缺两量的老 `transit_to` 行写迁移、特判或拒绝闸；验收只走新档路径。无 ctx 键则 `transit_arrivals=[]`（该窗无抵达或未写占位），不写迁移/特判闸。

### F7 拆除清单与拆测边界

**本票同批必须删除（生产）**

- `ming_sim/decree.py::force_transit_arrivals` 及其 `pre_settle` 调用
- `ming_sim/simulation.py::_build_transit_nudge`、payload/`build_simulator_context` 的 `transit_nudge` 键与旧 data_note
- `ming_sim/tools.py`（及同类 prompt/说明）中指向旧到达器的指示

**本票同批必须拆除或改绑（测试）**

- `tests/test_transit_aging_346.py`、`tests/test_yuan_arrival_185.py` 中编码「≥2 月/`transit_start_turn=0` 强制到任」「nudge months≥1 应到」的旧机制用例 → **删除或改绑到 F2/F3 oracle**；可复用的镜像同步/推进不变式断言可留，但不得再 import 已删符号。
- 全仓符号级验收：生产+测试 **零残留** `force_transit_arrivals`、`_build_transit_nudge`、`transit_nudge` 作为活机制（注释里历史点名须改为「已删除」或一并删）。

**本票聚焦测试最小集（#1185 分级：本片 focused，不借全量冒充）**

1. 河南常速黄金：重烘后 `r0≤1` → `N=1` 下月到；location/四量清零；DB=content。
2. 非常速差异路线：同一 `r0` 下 1.0/1.5/2.0 的抵达 turn 各与 F2 oracle 一致。
3. 未到期不抵达：`N>1` 路线在 `T0+N-1` 仍在途、remaining 按公式。
4. 顺序：在途赴门控地者，抵达月 event terminal/seed 门读到**新** location（tick 先于门）。
5. 中断型：F5。
6. restore：F6。
7. 拆除：F7 符号零残留；无第二套在途时间账。
8. 矩阵特批：`henan↔beizhili ≤1.0` 对称；0094 性质测试不红。
9. **pre_settle 已提交 → simulator 前崩溃恢复**（钉 F4/F6 抵达集合）：新档在途者构造本 tick 必抵达（F2 oracle）→ 跑完 `pre_settle` + ready=0 占位（与生产同缝）、**不**调用 simulator → 断言 DB 抵达终态正确且 `get_resolve_context(turn)["simulator_payload"]["transit_arrivals"]` == 期望列表 → 关连接/重开库/重载 state（相位仍 settling）→ 再入 settling 恢复 fallthrough（无 ready extracted）→ 断言：不二次财政 tick、characters 抵达账不被改写第二次；组出的 `transit_arrivals` 与占位写入**完全一致**且完整 simulator 输入含且仅含该集合一次；对照无在途抵达月键为 `[]` 或无幻影人名。不改松既有 F6 四量/location restore 断言。

**明确不在本票**

- #669 在途语义串 / `transit_semantics` projector
- #670 travel-gating / 候见前传召
- #671 候见账与宣入
- #675 三锚家族 e2e 与全面调参
- 途中改道、军队走图、旧档兼容

### F8 复杂度上限

- 新增长期机制 ≤ 1 个 tick 核（挂原 `force_transit_arrivals` 调用点）+ 1 个当月 `transit_arrivals` 事实投喂（替原 nudge 键）。
- **`transit_arrivals` 的跨崩溃 durable 承载复用既有 `pending_resolve_context`（`simulator_payload.transit_arrivals`）**，挂上 ADR 0008 已有恢复载荷；**不计入**新增长期机制，不新表/新列/旁路缓存。护栏三问：①非第二到达器（仍单一 tick 写口）；②非并行 ETA/在途缓存（只存本 tick 已抵达事实，无 remaining/factor）；③非旧档迁移/特判闸（随 #667 r4，只走新档；无 ctx 键则 `[]`）。
- **禁止**：第二到达器、并行 ETA 缓存、运行时寻路、为旧档写的迁移/拒绝闸、改全局阈值/舍入、「距 0 即到」ε 护栏、在途语义投影（#669）、候见写口（#671）、为 `transit_arrivals` 另造平行持久机制。
- 内容侧仅最小图源拧动 + 重烘；校准叙事归 #675。

### Acceptance criteria（取代原五条，机械可验）

- [ ] **河南黄金**：常速 `henan→beizhili` 次月首 tick 抵达；baked `matrix.henan.beizhili ≤ 1.0` 且对称；0094 矩阵性质测试绿。
- [ ] **oracle 抵达月**：常速/1.5/2.0 在所选路线上的抵达 turn 均满足 F2 公式；未到期月不抵达。
- [ ] **抵达写口**：抵达者 `location=原 transit_to`，`transit_to=''`，remaining/factor=`NULL`，`start_turn=0`；DB 与 content 镜像一致；经唯一 `set_character_transit` 缝。
- [ ] **链顺序**：tick 先于 event terminal/seed；抵达月门控读新 location；`pre_settle` 原子性与 turn 推进不变式不破。
- [ ] **叙事事实**：无 `transit_nudge`；当月 simulator 输入含本 tick `transit_arrivals`（仅抵达者；无裸 remaining/factor/ETA）；仍在途者不在此键；该集合在 `pre_settle` 与 ready=0 占位的同一外层 atomic 写入 `pending_resolve_context.simulator_payload.transit_arrivals`，完整 payload upsert 保留同键。
- [ ] **中断**：迁出 active 后无继续倒数、无抵达事实、ledger 空。
- [ ] **restore**：只读 DB 重建在途/抵达后态；中断重开后继续 tick 与连续跑一致。另含 pre_settle 已提交、simulator 前崩溃窗：关库重开 fallthrough 后 `transit_arrivals` 与连续路径一致且只投喂一次；不二次 tick；真源为既有 `pending_resolve_context.simulator_payload.transit_arrivals`（非平行缓存、非终态反推）。
- [ ] **拆除**：`force_transit_arrivals` / `_build_transit_nudge` / `transit_nudge` 生产与测试零活残留；旧 #346/#185 机制用例已删或改绑；无第二套在途时间账。
- [ ] **旧档**：无迁移/无特判/无拒绝闸代码；验收只走新档。
- [ ] **边界**：未交付 #669/#670/#671/#675 范围；未改 0095 公式；未借特批重校准非河南锚。


