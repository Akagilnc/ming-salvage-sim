# 财政基座 cutover 范围 = 全明直辖省一起翻；单省仅作 shadow 验证；seed 与 hub 分离

Status: Accepted（2026-06-20 grill-with-docs（#70）决策结晶 → to-prd 后跨模型设计评审 R1/R2 收敛 Accepted；三腿（codex gpt-5.5 / Opus 4.8 / gemini）两轮零降级。R1/R2 修订点（scope 17 省 / 失地冻结 / 起运 cap 对齐等）见 FISCAL §#70 + PRD #70。）

## 背景

ADR 0007 + [FISCAL_PROVINCE_SUBSTRATE.md](../FISCAL_PROVINCE_SUBSTRATE.md) 把省级财政基座锁成「单省 spine（陕西），跨省 hub deferred」。#70 grill 揭示两件事推翻这个范围框定：

1. **单省 cutover 不可玩**：若只把陕西接上新基座、其余省仍走旧 `calc_province_fiscal`，皇帝看到的是 split-brain 世界（陕西有火耗/起运/逋赋/死亡螺旋，其余省 flat 系数）。
2. **单省是排序选择、非引擎/设计上限**：引擎本就 province-agnostic（`settle_province_tick(region_id)` 读任意省 `regions.fiscal['settle']`），限定陕西的只是 `flows.py` 一行 `_FISCAL_SUBSTRATE_SPINE = ("shaanxi",)`；设计本就 per-province（ADR 0007「支出侧 per-province 存留/起运」）。

## 决定

1. **cutover 目标 = 全 17 个明直辖省（15 布政司/两京 + 辽东 + 皮岛）一起翻**，不存在单省 cutover。**成员按显式 canonical id 清单、不拿 `controlled_by=ming` 谓词判**（实测 ming 区有 17 个，谓词与早先「16 名单」自相矛盾，评审 R2 抓出）。
2. **单省（陕西）仅作 shadow 验证**：各省 shadow 独立 tick、不汇国库，用来看数值量级对不对；不作可玩 cutover 形态。
3. **seed 与 hub 分离**——两种不同的活、两道切片：
   - **seed（全省，#70）= 数据/校准**：给 17 省各建 `settle` 块（查史料填，详见 FISCAL doc §#70）。shadow 里各省独立 tick 即可验收，不需要 hub。
   - **hub（单独项）= 机制/单向门**：Σ各省起运到京 → 国库 + 京运补中央分配 + 退役整个 `calc_province_fiscal` + cutover flip。碰核心月末结算，高风险。
4. **外域/藩属/后金（`controlled_by ≠ ming`）不入 seed**：它们不交明朝国库；将来收复走 `on_restore` 才有 fiscal。
5. **失地冻结（评审 R2）**：spine 推进与 `settle_province_tick` 前查 `controlled_by`，省份被他势力（后金等）夺走后 ≠ming 即跳过/冻结该省 tick，不再往明朝账写死亡螺旋。v0.x 简化：理论上财政在任何控制者手下都跑，但当前 substrate 是明朝口径（宗禄/三饷/京运补），建模不了后金财政；他势力财政建模 deferred。

## Considered Options

- **永远单省 spine**：最小，但 split-brain 不可玩 → 否决。
- **全省 seed + hub 一刀齐做**：直奔目标，但 16 省未验证校准 + 高风险核心结算替换一口吞 → 否决（拆两刀，seed 先在 shadow 验数、hub 再翻）。
- **全省 seed（#70）/ hub 分离（本决定）**：seed 在 shadow 可独立验收、是数据活；hub 是机制单向门、单列。

## Consequences

- **取代 ADR 0007 / FISCAL doc 的「仅锁单省 spine」措辞**：单省 = shadow 验证态、非终点；全省 = cutover 必需。并**对齐 ADR 0007「余额起运」措辞 = 引擎 cap 模型**（实测 `起运池=min(实征,起运定额)` 是收入侧 cap、非付完出血的余额，评审 R2 抓出；起运量由起运定额定，故 #70 按 posture 构造起运定额，详见 FISCAL §#70）。
- **#70 scope 从陕西扩到 17 省 seed**（查史料填、量级定稿，详见 FISCAL doc §#70）。
- **跨省 hub 从「deferred 不需要」升为 cutover 必需件、紧随 #70**（独立项 #261，待 to-prd/to-issues）。
- 引擎 `_FISCAL_SUBSTRATE_SPINE` 元组从 `("shaanxi",)` 扩到 17 省显式清单；脊柱推进加 `controlled_by` gate（失地冻结，决定 §5）（代码级，留 #70 实现期）。
- 单省脊柱的「跨省 hub deferred」不再是终态约束，但 hub 本身的拆法（动态京运补 / 退役旧路径的并轨口径）仍是独立设计，本 ADR 不展开。
