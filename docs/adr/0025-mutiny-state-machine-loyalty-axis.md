---
status: proposed
---

# 哗变状态机：以军心(loyalty)为轴的确定性升降级 + 三振递进伤痕 + LLM 软判恢复

## Context

#299（军事线第一片）= 给「欠饷 → 军心崩 → 哗变 → 补饷滞回解除」一条**最小粗暴**的确定性状态机闭环，不等完整军事系统。设计依据 = [ADR 0023](0023-frontier-pay-source-ratio-and-arrears-reconciliation.md) D11（#287 morale substrate，明文「状态机本体=#299」）+ [ADR 0007](0007-province-fiscal-substrate-ai-judged.md) P2（判战永远 LLM 软判、代码只 clamp 不算胜负）。**只定设计决策与状态机契约，确切阈值数字 / schema 列名 / 管线落点留 `/tdd`。**

本 ADR 经 `grill-with-docs` 结晶，跑了三道支撑研究：① 晚明兵变史实（≥8 例）；② 代码地基（morale/loyalty 双列实态、现有 trigger_gate、判战软判、结算管线）；③ 中间态台阶数 + 现成机制复用。

**史实结论**：哗变根因 = **持续重欠饷（~4-6 月）侵蚀军心**，非战败（宁远1628 四月欠饷缚帅勒饷却招抚平定未叛、吴桥1631 缺饷哗变据城降金、西北边军半年欠投流寇、己巳勤王军欠饷杀将、1644 京营积欠不战而溃）。战败 → 溃散 / 降敌，非哗变；哗变兵往往能打（**军心崩 ≠ 士气崩**）；客军 / 边军高发；同一欠饷根因按「欠多久 + 有无外部去处 + 主帅威信」分流成 鼓噪(可招抚) / 哗变 / 降敌 三出口。

**关键地基裂缝（grill 实测，附 file:line）**：代码里 `morale`=士气(战斗)、`loyalty`=军心(向背)两独立列；现有哗变门 key 在 loyalty（孔有德 `events.json:83` `loyalty≤42 ∧ denglai.arrears≥6`、李自成 `:351` `morale≤40 ∧ loyalty≤45`）；但 #287 欠饷公式（`flows.py:509-517`）只扣 `morale`、不碰 `loyalty`，且无任何确定性代码动 army loyalty——**「欠饷→哗变」因果链当前是断的**（欠饷动士气、哗变看军心、军心不被欠饷推 → 哗变门是死门）。且 `constants.py:199` 把中文「军心」别名错指进 `morale` 列。

## 决定

单一架构决定：**哗变 = 以军心(loyalty)为轴的确定性状态机，欠饷经新增「军心 tick」驱动，恢复与倒戈交 LLM 软判**。展开为：

1. **（D1）哗变主轴 = 军心(loyalty)，非士气(morale)；本 ADR 修订 ADR 0023 D11 的状态机轴。** #299 新增一条确定性「军心月度 tick」由欠饷驱动 loyalty（与现有哗变门 key 一致）；#287 的 morale tick（欠饷扣士气）不变（欠饷之军确也打得差）。**ADR 0023 D11 把触发地板/滞回写成 morale 轴（`morale≤阈值` 触发、单 morale 滞回解除）——本 ADR 据 grill 实测（哗变门 key 在 loyalty、欠饷只动 morale）正式改为 loyalty 轴**：触发 `loyalty<20 ∧ 欠饷>4月`、滞回 = `is_mutinied` latch + `loyalty≥40 ∧ 欠饷退档` 解闩；**#287 侧 provision 字段为 `is_mutinied(0/1)` 等专用列、不再 provision morale-触发态**（later-doc-wins，仿 0023 修订 0021）。**附带必修**：`constants.py:199` 中文「军心」别名从 morale 改指 loyalty（单独 commit、先落）。

2. **（D2）军心 tick = 按欠饷月数分档的确定性月度增量。** 欠饷月数 = `arrears ÷ army_needed(月应发)`（**不是 ÷10**，`db.py:3848` 双证）；欠饷 0 月 → loyalty +5、1-2 月 → 0(dead-band)、≥3 月 → -5；钳到 `[0, 军心上限]`。仅 `owner_power=='ming'` 且非土司（自养军排除，共用 #287 的 is_tusi 守卫）。补饷 / 安抚由 LLM 软判调 loyalty，**单事件 `|Δ|≤15` 且调整后亦 clamp `[0, 军心上限]`**（动态上限是所有 loyalty 写入的唯一硬顶，软判不能突破伤痕 cap）。阈值示意，精确值 = seed/`/tdd`。

3. **（D3）状态 = 三档 loyalty 实时派生 + 哗变 latch 覆盖。** **派生三档**（未锁存时按 loyalty 现算）：正常（≥60，含死忠 / 优秀 / 一般 战力梯度）/ 不满（40-60，软战力 debuff·涣散·行动缓慢，仍听调遣，无事件）/ 鼓噪（20-40，可出事件、仍占军需、勉强听调遣）。**哗变不是 loyalty<20 的自动派生带**——`loyalty<20 ∧ is_mutinied=0`（欠饷未达入闩）仍归鼓噪低端展示；只有 D4 双条件入闩（`is_mutinied=1`）才是哗变。档名即玩家定性呈现词表。

4. **（D4）哗变 = 确定性 latch，唯一持久态。** 进：`loyalty<20 ∧ 欠饷>4月`（`is_mutinied` 0→1）；**锁存**：`loyalty∈[0,40)` 仍判哗变（不弹回鼓噪、不出事件——滞回，防「安抚到一半又触发缚帅事件」）；出：`loyalty≥40 ∧ 欠饷退到入闩档以下（示意 ≤4月，/tdd）` 解闩落「不满」——**LLM 软判 ±15 可抬 loyalty，但欠饷未退档则 latch 续、单独不解闩**（守「清欠才是恢复路、一次砸钱不能秒解」，宁远式补饷+安抚+撑一阵）。后果三条：① **拒绝任何命令**（针对它的任何旨令效果 no-op）② 对明 **0 战力**③ **仍占军需**（继续累欠饷、不补则军心继续 -5）。哗变期间清欠 → 军心仍 +5/月（唯一恢复路）。

5. **（D5）三振递进伤痕，由 `mutiny_count` 驱动。** `mutiny_count` **仅在 `is_mutinied` 0→1 进闩边沿 +1**（每次重新入哗变记一次，持续哗变期不重复计）。1 振：标记 + 军心上限 -20（→80）；2 振：上限再 -20（→60）+ **probation**（`mutiny_probation` 存剩余月数，**解闩 loyalty≥40 起算、每满饷月 -1、归 0 才可回正常**；probation 期内再哗变 = 直接计第 3 振、probation 作废）；3 振：进哗变即**确定性变流寇**（`owner_power`→流寇、不可救）。

6. **（D6）救赎：满饷连续 12 月 → 军心上限 +10（≤100），`redemption_count` 持久计数。** 与伤痕对称。`mutiny_count` 与 `redemption_count` 均**终身累计、不因新事件重置**（救赎抵消旧伤痕）；军心上限 = `clamp(100 − 20×mutiny_count + 10×redemption_count, 下限示意, 100)`，下限留 /tdd。

7. **（D7）倒戈只在第 3 振 = 确定性变流寇；1/2 振哗变不倒戈。** 同一支军第三次哗变即叛出去改换门庭、不可救。**1/2 振的哗变不倒戈**——军队赖在原处、不听任何指挥、无战斗力、仍吃军饷，可补饷安抚救回。既有**具名历史事件（孔有德式）可在事件层叙事降敌**（其 trigger_gate + effect_on_trigger，现成 extractor 路径），但那是**剧本路、非 #299 确定性后果**；#299 确定性层只第 3 振倒戈。若剧本事件令一支 latched 军降敌，须**同步清 `is_mutinied`**（owner 已转出 ming，走 0023 D6 核销路径），防 latch 与非明军并存。

8. **（D8）一切后果喂 LLM 软判（ADR 0007 P2），玩家见定性不见裸值（P4）。** 战力影响是给 simulator 的定性输入（TSV 带状态 flag + prompt 正向指引「鼓噪之军战力打折、哗变之军不堪驱使按非战斗裁」），代码只标态、绝不算胜负、不硬改装备数。flag 进 simulator TSV 给 LLM（机器读、不违 P4）；玩家邸报按定性档名呈现、不示 loyalty 裸值。

## Consequences

- **接缝 → #287（`blocked_by`）**：#287 须交付 (a) 哗变状态列 provision、(b) `is_tusi` 字段及 morale 公式守卫；本 ADR 把「军心 tick + 状态机本体」划归 **#299 owns**（住 `flows.py`、紧邻 #287 morale tick、同一原子事务）。#287 的 per-source 记欠迁移对本切片透明（触发读欠饷合计），可后于本切片落、不阻塞。
- **月末顺序（钉死，落 ADR 0023 D4 相位图）**：`财政 settle(③④) → morale tick → 军心 tick → 状态判定/latch/count/probation → 事件 gating →（pre_settle commit 后）LLM season_simulator delta（clamp 到动态上限）`。故 **LLM 当月调 loyalty 不影响同月哗变判定**（最早下月起作用）；同月哗变态由确定性 tick + 阈值决定，simulator 据已定状态叙事。
- **存储**：新增 armies 列 `is_mutinied(0/1)` latch · `mutiny_count(int)` · `mutiny_probation`（2 振剩余缓冲月） · `full_pay_streak`（满饷连续月） · `redemption_count(int)`（救赎次数）——均**确定性引擎独占写、不入 extractor 别名表、不塞 `status` TEXT**（status 是 LLM 可写自由文本、会被 delta 污染）。军心上限由 `mutiny_count / redemption_count` 派生（见 D6）。**`SELECT *` 自动带回新列仅对 restore / simulator(TSV) 路径成立（满足 P1）；`flows.py` 军饷 tick 是 projected `SELECT`、不自动带新列**——#299 须把上述新列 + #287 的 `is_tusi` **显式加进 tick 的 SELECT 列表**。
- **现有事件映射**：孔有德 `loyalty≤42 ∧ denglai.arrears≥6` = 鼓噪带入口（降金是越线升级 / 剧本降敌后续、非触发即演）；李自成京营 `morale≤40 ∧ loyalty≤45` = 哗变带 / 终局；纯 morale 门（关宁 / 宣大 / 蓟镇）= 士气轴、不映射；蒙古 host（owner≠明）排除。鼓噪事件取**混合**：通用军给邸报警报、具名军走缚帅剧情。
- **滞回 / latch 必要性**：`loyalty=30` 时，「从哗变恢复中（锁存）」与「从上掉进鼓噪」是两个不同状态、同一 loyalty 值——只能靠持久 `is_mutinied` 闩消歧。故状态不可纯从 loyalty 派生（见 D3），哗变态必须落库。
- **半补饷 chatter（设计明示，意图内）**：哗变军若只半补饷（欠饷未退档），解闩需 `loyalty≥40 ∧ 欠饷退档` 双条件，单靠 LLM ±15 抬 loyalty 不解闩 → 不会出现「解闩→-5/月→4 月内又入闩」的抖动；要真稳定必须清欠到退档。这是设计意图（不清欠则不脱困），非 bug。
- **留 /tdd 的数值**：20 / 40 / 60 / 80 档界、>4月入 / ≤4月出 / ≥3月扣、±15 / -20 / +10、12 月、probation 3 月、上限下限——全 seed 可调；**架构（军心轴 / 专用确定性列 / 三派生档 + 哗变 latch / 三振 + probation + 救赎计数器语义 / 月末顺序 / status 不可 extractor 写）= 本 ADR 钉死。**
- **流程**：本 ADR `status=proposed`；按项目规则设计文档须走完整评审闭环（本地 cmr + 线上 bot），**评审在 `to-prd` 之后**、本 grill 不评审。
