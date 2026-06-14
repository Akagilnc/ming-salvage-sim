# 血债棘轮 schema（ADR 0011 决定2 子 ADR · 0011-2）

Status: Proposed（草案；承母 ADR `0011-edict-resistance-and-centrifuge-ledger.md` 决定2，由 design-dig `dig-4`/`dig-5`/`dig-6`/`dig-7`/`dig-9` fold 而成。**待评审**——按 CLAUDE.md 设计文档铁律走本地 cmr 收敛 + 线上三 bot 收敛，未收敛前不进实现期。实现属编码活、spawn 隔壁。）

承 GitHub #112 tracker。本 ADR 收口母 ADR 留给子机制的「血债精确 schema」，并应用母 ADR CMR r2 parked 的三项最低契约（provisional / H5 / 净负）。

## 为什么这是「总解锁」

母 ADR 决定2 把离心账本的**精确 schema 留给本子 ADR**；design-dig 的外压线（dig-2）与资源经济线（dig-3）各自独立推导都指回同一结论——**血债/离心棘轮 schema 收口 = 总解锁**：资源 menu 4 条、外压承重件、派系离心全压在这张表上，它不落则四层票拟（dig-8）resolve 读空值退化纸面、破局无 substrate 可读。

质量标尺是北极星（`0011-design-dig/north-star-90fen.md`）：让「东林查隐田割到自己人、黄道周犹豫、公正处置反挣敬重」这种 90 分时刻**从撞运气变成稳定可复现 + 持久**。本 schema 的存在理由就是把那场戏**留得住、能累积**，而不是下一回合 LLM 失忆翻案。任何决定点都拿北极星问一句：「喂不喂得出那种时刻？」

## 选型来源（攻击驱动，非自夸）

**方案1（极简逐派结构化列）为骨架** + 嫁接方案2 的 append-only 审计账。9 攻击向量中 7 个没破，唯一破的 H5（话术诱导）= 母 ADR 留子 ADR 收口（本文 H5 节）。落选致命洞（实测）：

- 方案2 critical：透支账寄生 `GameState.metrics` 自由 dict，被 `clamp[0,100]` + 白名单**双杀**。
- 方案3 4×high：罪档无结构化真源 + 一上来就 42 格过度工程。
- 方案4 high：provisional 转 final 托付不存在的「月初 tick」，撞 `pre_settle:190` 早退软死锁。

---

## 决定点（D2-1 ~ D2-9）

> 每点给：**决定 / 弃案 / 攻击残留诚实标**。带「⚠️ CMR」标记的是 fold 时新做的 reconcile 或动了已收敛语义、必须本轮评审复核、不当已收敛。

### D2-1 粒度 = 逐派 × 轴（42 格）

**决定**：血债逐 `(faction, axis)` 累积，7 派 × 6 轴 = 42 格（轴 = 母 ADR 决定3 / dig-5 的礼法名节 / 既得利益 / 实务事功 / 皇权依附 / 华夷战和 / 民本恤民）。

**用户 2026-06-14 拍板覆盖 fan-out 原推荐（scalar）**。理由 = **喂叙事**：LLM 能说「太监因你夺其利（既得利益轴）心灰意冷，未必尽心」；笼统一个 scalar 喂不出这种定性。

**成本澄清**（纠 fan-out 误判）：42 格**不预填 42 个血债值**——仇恨从 0 累积。真正要手填的是**各派价值画像矩阵**（dig-5，42 格立场值 −2…+2），那张表本来就要填（决定3），所以「决定3 矩阵从『以后填』变『现在就填』」，42 格血债的额外代价仅「调参旋钮多」、不是 42 倍 seed 工作量。

**弃案**：逐派 scalar——喂不出按轴定性的叙事（北极星的「夺其利」说不出）。

**⚠️ CMR 残留**：D2-1 的 42 格覆盖了 dig-4 原 DDL 的「scalar 单列」，连带把 **D2-3 的答案从『列』翻成『新表』**（见 D2-3）。须复核。

### D2-2 真源 vs 缓存 = log 真源、表缓存

**决定**：`centrifuge_log`（append-only）是**审计真源**；`faction_axis_debt` 的血债/防备数是 **O(1) 缓存**，可由 `SUM(amount) GROUP BY (faction, axis, kind)` 重建（恢复端对账不变式：缓存 ≡ log 重算）。

**弃案**：纯缓存无真源——恢复端对不上账、无 append-only 审计链，且与 P1「restore 只读 DB 无损接续」冲突。

**残留**：缓存与 log 的一致性靠唯一写函数维持（见 D2-6 不变式1），双写漂移风险收窄到单函数。

### D2-3 列 vs 新表 = ⚠️ 42 格缓存改新表、edict_overdraw 仍列

**决定**（fold 时 reconcile）：

- 血债/同类防备底（per-轴）→ **新表 `faction_axis_debt`（42 行）**，不是 factions 上加 42 列。
- `edict_overdraw`（皇权透支账，逐派 scalar、非逐轴）→ **仍 factions 单列**。

**为什么新表不违反 dig-4 原「列，避 metrics 双杀」**：那个「双杀」（`clamp[0,100]` + 白名单）专打的是 **`GameState.metrics` 自由 dict**（data-drift 病源，审计过要灭的）。母 ADR 决定2 明文认可的替代是「**逐派列或新表**，非全局 metrics dict」——结构化关系表 `faction_axis_debt` 正是这个「新表」选项，带显式列、FK、CHECK 约束，**不经过 metrics dict 的 clamp/白名单管道**，双杀规避论证对它依然成立。

**弃案**：factions 加 42 列（不可维护、加轴即改表结构）；塞 metrics dict（双杀 + data-drift）。

**⚠️ CMR**：这是 D2-1 42 格 override 倒逼的 schema 翻案（dig-4 写「列」）。须复核：① 新表是否真的绕开了 metrics 双杀的所有面；② 缓存表 + log 真源的双写一致性强制点是否足。

### D2-4 失称度算法（避除零）

**决定**（用户 2026-06-14 改名修正）：血债 = **罚的力度 × 失称度**。原 fan-out 叫「合法性系数」是**反的**（值越高=越不正当=血债越多），用户抓出已纠。「失称度」= 罚配不配得上罪。

```
severity      = SEVERITY_BASE{申饬:3, 罢黜:10, 廷杖:40, 抄家:70, 诛:100}   ← 结构化处置类型，非措辞
crime_weight  = CRIME_BY_CODE{获罪削籍:70, 陷虏:50, 无:10}；STIGMA{中旨除授, 非正途, 罗织} → crime_weight=1
mismatch      = max(0, severity − crime_weight)                          ← 失称度版避除零
legitimacy_pct= clamp(10 + 90 × mismatch / severity, 10, 100)
Δblood_debt(direct) = round(severity × legitimacy_pct / 100)
```

**数值例（同抄阉党，severity 70）**：

| 路径 | crime_weight | legitimacy_pct | Δblood_debt |
|---|---|---|---|
| 走程序抄真贪 | 70（坐实） | 10% | **+7** |
| 小罪重罚 | 10 | 87% | +61 |
| 中旨罗织 | 1（STIGMA） | 99% | **+69** + 透支账 |

**血债差 8.7 倍 = 母 ADR 决定5「攒合法性别硬来」的教学曲线落进数值。**

**弃案**：比值版（severity/crime_weight）——要新建罪档表、且 crime_weight=0 时除零。

**残留**：`SEVERITY_BASE` / `CRIME_BY_CODE` 精确值 = 首版，随 α/β playtest 调参（镜像 spike G1-G22 方法学），非现在拍死。

### D2-5 crime 载体 = reason_code + STIGMA 常量；罪与罚账第一刀就建（轻）

**决定**：crime_weight 由 `reason_code`（扩 ADR 0009 enum）派生；污名 STIGMA（中旨除授 / 非正途 / 罗织）= 独立常量码。

**罪与罚的账第一刀就建（轻）**（用户纠：不是「查案/办案玩法系统」，那才牵扯 #89）——它就是**像 42 格一样为叙事多存状态**：办谁时记一笔（什么罪 / 查实没 / 判什么），从当时叙事记，不是搜证小游戏。顺手让「罪罚相称」判定回归直觉（有真罪号就能直接拿罚比罪，失称度公式内部定）。

- 罪的大小由**裁判在办他时判定**（铁证 vs 罗织），记进 `reason_code`/STIGMA。
- 皇帝硬说罪大 → **要过裁判关**（设计时盯，H5）。

**弃案**：把罪罚做成查案玩法系统（牵扯 #89、过度工程、违轻交互）。

### D2-6 四不变式 + 代码层强制点

**决定**（每条配物理强制点，mutation 自验立即咬）：

1. **单调棘轮**：唯一写函数 `accrue_blood_debt`（只 `+=`、`assert amount >= 0`）+ 列 `CHECK >= 0` + `idem_key UNIQUE` + 静态围栏（扩 0009 allowlist）。mutation 把 `+=` 改 `=` 立即咬。
2. **阻力 / 称病只读血债（非失望）**：函数签名物理不接 `satisfaction` 参数、SQL 不 `SELECT satisfaction`；`adjust_factions` 只动 sat/lev、碰不到 blood_debt。→ 一个好回合压不掉结构性负面（堵 H2 洗白）。
3. **不可跨派冲抵**：`accrue` 按 faction PK 单派 UPDATE，全库无「A 转 B」签名；安抚东林改东林 sat 列，与阉党 blood_debt **不同行不同列、物理无法相消**。→ 偷 Tyranny「favor ≠ wrath」，是涌现尽头能成立的命根。
4. **血债 ≠ leverage**：两列两写路径（blood_debt 走 `accrue` / 严重度派生；leverage 走 `adjust` / 局势派生），不共享写函数。→ 血债 = 该派多恨你、leverage = 该派多能挡你，双轴解耦。

### D2-7 净负公式（薄冰冻土）—— parked CMR r2 项③

**决定**：

```
per_layer_resistance = max( floor=α×血债 , 命门合法性floor[dig-9] , min(ceiling, dynamic_term) )
net_centrifuge       = Σ( Δsatisfaction项 + Δleverage项 )    ← 签名物理不接 blood_debt
```

- **血债 = 冻土**（单调 floor，压不动，进 `resistance` 的 floor 臂）；**失望 / leverage = 薄冰**（可动，烧 `net_centrifuge`）。
- 破局 = **移动薄冰、烧不掉冻土**。降 leverage / 招回退场 actor 解锁回流前置来移动盘面，不是抵消「阻力只读」的血债。
- **命门合法性 floor**（dig-9 ground 洞）：命门题即便各派 dynamic 低（没人激烈反对），合法性 floor 仍把阻力托到 ceiling（国本之争原型）。故 floor 臂含 `命门合法性floor`。

**硬下界不变式（堵纸面净负实操死锁）**：floor 不得碾平至**少一条可执行净负动作**；净负路收窄判据 = 「≥1 派未触底（sat>0 ∨ lev>0）则净负窄路恒存」。全派打穿 = 母 ADR 决定6 允许的**涌现尽头**、非钦定灭亡。

**残留**：α/β/γ/δ 是 playtest 调参（留 sub-spec），但**下界本身是硬不变式、不是可调参数**——这条是与决定2 单调棘轮的最硬张力的解，CMR 须确认下界与 ceiling 出路恒可达（dig-9 axis-tag 翻轴）不打架。

### D2-8 provisional 归属 = defer 第二刀（钉最低契约）—— parked CMR r2 项①

**决定**：provisional（中旨当回合落库 + 六科异步封驳的「未生效」标记，母 ADR 决定5 / H6）= **第一刀不做、随中旨闸一起 defer 第二刀**（与「四层票拟整套 defer」一致，反过度工程；提前做必撞软死锁 / 套利）。

**但本 ADR 钉死它的最低契约**（避 fan-out 方案4 实测的 3 坑，让第二刀有据可依、不留设计空洞）：

1. **转 final 扫表放 settle 后半段 `atomic` 内、对 `before_turn` 幂等**（不放 `pre_settle`，避 `pre_settle:190` 早退软死锁）。
2. **`expires_turn` 到必转 final**（避 ADR 0008 毒 payload 永挂）。
3. **fungible（钱）照落 live 国库 + 封驳窗 `W=1` 压窗 + 当回合正反账冲销**；status 类后果（家产已没 / 将就位）H6 真闭，**涉钱只压窗不全闭**——P1（当回合全量落库）× H6（既成事实套利）是固有张力，**不假装两全、不做 escrow**（见下「中旨按历史」）。
4. **⚠️ 坑④（内部红队补，本轮必修）：fungible 中旨正反账须留 append-only 双笔痕、禁净额对冲。** 坑③ 的「正反账冲销」若只做 +amount 后 −amount 净额归 0，长得就跟金手指铁律里「直接改国库余额被大臣审计成『虚存』」一样——审计大臣 LLM 会把「中旨拨款 +100 万 → 同月封驳冲销 −100 万、净 0」读成空头虚账，正撞 D2-8「钱实拨了、被驳没了（真实代价）」的设计意图；且 restore 只读净 0 分不清「拨了又驳（钱真没了）」vs「压根没拨」。**契约**：拨款与封驳冲销各落一笔结构化月度流水行（append-only、各带 `reason_code`=中旨拨款 / 六科封驳作废 + `idem_key`，进 `compute_budget_lines` 明细），净额仍 0 但审计可读「真拨真驳」；双笔进 0008 atomic + before_turn 幂等、restore 可复原「拨过且被驳」；`season_simulator`/审计大臣 prompt 侧补正向口径（成对 reason_code 同月流水 = 「钱已实拨、被六科封还作废」、不判虚账）。

**中旨按历史（用户拍，溶解原 fork-4 escrow）**：中旨绕内阁、六科可封驳、带「非正途」污名、**钱拨了被封驳就是没了**（史实）。用户：「钱没了就是没了」是**牙不是缺陷**，逼「别乱来、攒合法性慢办」。故不做暂存账 / 退款。中旨 / 封驳跟「四层票拟改革」（dig-8）一起做，**血债先、它后**（顺序可再议）。**⚠️ 覆盖母 ADR 决定5 line 82**：母 ADR 原把「钱入库」列进封驳作废集（=钱要被反转），与此处「钱没了就是没了」相反；用户 2026-06-14 拍板（钱不退）时间在后、为最终权威，本条覆盖之，并已回标母 ADR（见母 ADR line 82 注）。

### D2-9 build-upon ADR 0008 / 0009

**决定**（明确依赖，非无成本复用）：

- **0008**：`accrue` 走 `applier.atomic` 落库链；`idem_key UNIQUE` 防 0008 重跑 / 断点续跑二次累加。
- **0009**：crime `reason_code` = **扩 0009 的 reason_code enum** + 协调 0009 静态围栏 / 契约；污名 STIGMA 新增码同理。
- **faction-UPDATE 写路径缺口**（dig-6 叛变需要）：`db.py` 现无 `UPDATE characters SET faction=?`（faction 仅 INSERT 时写）；叛变落库须补此口径。设计先钉，实现按 DoD 点检。

---

## DDL（第一刀，走 `ensure_column` 幂等 ALTER，老档补默认）

```sql
-- 逐派 scalar（皇权透支账，非逐轴）
ALTER factions ADD COLUMN edict_overdraw INTEGER DEFAULT 0;   -- 中旨/廷杖频度，单调（H1/H4）

-- 42 格缓存（逐派 × 轴；O(1) 读，由 centrifuge_log SUM 重建）
CREATE TABLE faction_axis_debt (
  faction     TEXT    NOT NULL REFERENCES factions(name),
  axis        TEXT    NOT NULL,                       -- 6 轴枚举（dig-5）
  blood_debt  INTEGER NOT NULL DEFAULT 0 CHECK (blood_debt  >= 0),   -- 单调不减 floor
  wariness    INTEGER NOT NULL DEFAULT 0 CHECK (wariness    >= 0),   -- 同类防备底（kinship 臂）
  PRIMARY KEY (faction, axis)
);

-- 审计真源（append-only；缓存可由它 SUM(amount) GROUP BY (faction,axis,kind) 重建）
CREATE TABLE centrifuge_log (
  id            INTEGER PRIMARY KEY,
  turn          INTEGER NOT NULL,
  faction       TEXT    NOT NULL REFERENCES factions(name),
  axis          TEXT    NOT NULL,
  kind          TEXT    NOT NULL,                     -- direct | kinship | overdraw
  base          INTEGER NOT NULL,                     -- severity
  legitimacy_pct INTEGER NOT NULL,
  amount        INTEGER NOT NULL CHECK (amount >= 0), -- 实际累加量（单调）
  source_name   TEXT,                                 -- 目标人名（H5 残留入口，见下）
  reason_code   TEXT,                                 -- 0009 列
  source        TEXT,                                 -- 0008 来源
  idem_key      TEXT    NOT NULL UNIQUE,              -- 防 0008 重跑二次累加
  created_at    TEXT    NOT NULL
);
```

- **失望层**：复用 `factions.satisfaction`（不双真源）。
- **leverage**：复用 `factions.leverage`（与血债双轴解耦）。
- **seed-guilt / identity**：落 `characters` 表（`seed_guilt` / `identity`，走 `content.py int_field` 链 + `ensure_column` 老档补 `identity DEFAULT 50`），是失称度（crime_weight）与 kinship（k_id）的真源——见下「依赖 substrate」。

## 同类防备底（kinship 臂）+ 认同度修正 —— ⚠️ 动了已收敛语义、本轮必复核

**决定**（fold dig-6 认同度层中与血债耦合的部分；其余认同度动态 / 叛变细节留 dig-6 / #89）：

```
Δwariness(同派旁观, kinship) = round( severity × legitimacy_pct / 100 × 0.3 × k_id )
k_id = clamp(identity / 100, 0, 1)        ← 用户 2026-06-14 拍：去掉原 max(1,…) 下界
```

- `identity` = 第五个 per-人值 [0,100]（与 faction / seed-guilt / #89 loyalty 全正交），答「此人多真是其挂名 faction 的核心」，**只缩 kinship 乘数**；**direct 血债臂签名物理不接 identity**。
- 两旋钮分离：**失称度**（罪罚相称，来自 seed-guilt）→ direct 血债（对被办者派、不可逆 floor）；**认同度**（identity，来自定逆案六等）→ kinship 强度（**可归零**）。
- 四象限（认同度值依 dig-7 定稿；「建祠知县」为讲解用假想边缘原型、非名册条目）：①核心死党（高罪高认同，崔呈秀 认同度 98）→ direct 低（法办）但全党炸（kinship≈2）；②边缘投机（低罪低认同，假想建祠知县 认同度≈15）→ direct≈0 + kinship=0 = **全党无感 / 乐见顶包**（北极星复现）；③低认同高罪 → direct 足 kinship 低；④高认同低罪 → direct 小 kinship 高。

**⚠️ CMR 必复核**：去掉 `max(1,…)` 下界让 kinship 可**真归零**——这**动了 dig-4 原「同类防备底单调不减」语义**（归零 vs 至少 +1）。须确认：`centrifuge_log.amount CHECK >= 0` 与单调棘轮语义在 **0-vs-1 边界**上自洽（amount=0 的 kinship 行是否要落 log / 还是不写、单调性是否仍指「已写行只增不减」而非「每动作必 ≥1」）。**别当已收敛**（dig-6 用户已拍方向，但与 dig-4 单调语义的边界交互须本轮评审钉死）。

---

## parked CMR r2 三项最低契约（本 ADR 的 r2 fix 落点）

母 ADR CMR r1 已 fix（8 组 findings，commit `dfe8482`）；r2 浮出但**钉不住在母 ADR 层、须本子 ADR 落最低契约**的三项，集中收口于此：

| r2 项 | 落点 | 状态 |
|---|---|---|
| **provisional** | D2-8 | defer 第二刀，但最低契约（3 坑 + 中旨按历史）已钉死 |
| **H5** | 下「H5 闭合」 | 三入参结构化 + `source_name`→faction 解析契约（红队补：跨派别名钉 PK 精确 + 歧义 abort）；彻底归零留母 ADR 决定5 |
| **净负** | D2-7 | 硬下界不变式钉死、α/β/γ/δ 留 sub-spec |

### H1/H2/H5/H6 闭合

- **H1（中旨频度反噬无载体）**：`edict_overdraw` 落 factions 列（不落 metrics，规避双杀），applier 撞派 `+=1` 单调。残留：归派精度依赖轴矩阵（defer），第一刀粗粒度按 target faction。
- **H2（离心可被好回合洗白）**：不变式1 + 2（唯一写只 `+=`、读侧不 SELECT satisfaction）。攻击判「真正的棘轮牙、攻不破」。
- **H5（软判可被话术诱导降敏感度）**：受害派 faction（`SQL 查 characters.faction`）+ crime_weight（`reason_code` 枚举）+ severity（查不中落最低档保守）**三入参全结构化**。**⚠️ 残留比原想的大（内部红队攻破，本轮必修）**：`source_name`→faction 解析不仅过 extractor，且本仓库 name→row 是**模糊子串/别名匹配、非 PK 精确**（`session.py:_find_candidate_by_name` 做 `key in name or name in key`），而 seed 存**跨派同名别名**——实证 `袁巡抚` 同时是袁可立（东林）与袁崇焕（军队）的别名。攻击路径：皇帝以官衔「袁巡抚」重办袁崇焕（军队），extractor 产 `source_name="袁巡抚"`，上游别名解析撞两派、无 tie-break、worst-case 静默选错 → 高 severity 血债落到东林而非军队；因不变式1（单调）+ 不变式3（不可跨派冲抵）**永久不可撤**，静默腐蚀悲剧引擎。**解析契约钉死**：① `source_name` 只接名册原始全名（extractor 朝臣 name 补「须用原始全名」纪律，对齐妃嫔已有约束），禁 alias/官衔进 source_name；② accrue 前 name→faction **PK 精确查**，命中 0 或 >1（歧义）一律 SettlementAbort + 报错包、绝不静默任选首行；③ 治本：seed 跨派别名去歧义 + startup 断言「无任何 alias/name 跨 faction 多映射」当不变式守门；④ 诚实标：H5「收窄非归零」对存在跨派同名官衔的人物当前**实为可诱导跨派**，须上述精确化后才成立。彻底归零（任意自由文本→实体）仍留**母 ADR 决定5**。
- **H6（中旨当回合落库 + 封驳异步套利）**：第一刀不做、随中旨闸 defer 第二刀（D2-8）。提前做必撞软死锁 / 套利。

---

## 依赖 substrate（本 ADR 读它们的料、不在本 ADR 定稿）

- **价值画像矩阵**（dig-5，决定3）：7 派 × 6 轴立场值 −2…+2，**两路独立推导 42/42 逐格一致**，已定稿（用户拍）。⚠️ 但**华夷战和轴带母 ADR 决定3 未决 caveat**：「主和/议和」极恐无常驻派系占位，矩阵 sub-spec 入轴前须复核「两极都有人占」是否真满足，不满足则标主和极临时占位派或按弃案折叠（本子 ADR 不消解此 caveat、原样传递给矩阵 sub-spec）。血债按 `动作轴方向 × 派系立场` 决定累到哪些 (faction, axis) 格、符号可相反（悲剧引擎）。轴值 **P4 永不呈现玩家**（呈现契约见下「P4 呈现契约」节）。
- **seed-guilt 名单**（dig-7）：开局朝堂 74 人，罪稀疏（15 人带罪、重+中 9 人全阉党、非阉党仅 2 人轻 + 福王 1 轻）：**80% 无罪、带罪者集中、重罪全压阉党**（不是「人人有点脏」——是「绝大多数干净、脏集中阉党」，这才撑起「清完阉党即缺正当靶」的悲剧弧）。这是失称度的真源——无预装则查办全是罗织、失称度饿死。白送两涌现：①不写剧本的悲剧弧（正当靶子清完 → 后期被诱向罗织 / 中旨）；②与决定8 咬合（清阉党正当又爽，但失去厂卫耳目 = 自我致盲）。名单已定稿（用户拍 5 争议）。
- **认同度 identity**（dig-6 / dig-7）：从《钦定逆案》六等映射（首逆 90-100 … 投机墙头草 5-15）；供 kinship 的 k_id。低认同可叛变（复用 faction 字段，落库须补 faction-UPDATE 写路径）。
- **ceiling 敏感度天花板**（dig-9）：供 D2-7 的 `命门合法性floor` 与 `min(ceiling, dynamic)` 臂；命门度挂 axis-tag（私意 vs 坐实）、不挂目标身份 → **出路恒可达**（走程序坐实 → reason_code=依律 → 轴翻转到非命门「依律处置」行 → ceiling 塌）已证明。
- **信息模型**（用户拍）：大面「阉党贪」= 公共常识 / 写脸上；**具体坐实证据握在少数相关人手里**（厂卫 / 政敌 / 苦主 / 知情者），皇帝正当办人得经过那些人——actor-mediated、非搜证小游戏，天然带迷雾 = P4「读人看不清」。

## 边界（朝堂 7 派专属）

血债 = **朝堂 7 派专属**（用户认）：外压派（后金 / 流寇）走外压系统、后宫 defer，**不进血债账**。

## P4 呈现契约（新增字段逐条钉死 —— 内部红队补，本轮必修）

⚠️ 本 ADR 新增的所有数值字段都是 **player-invisible**：`faction_axis_debt.blood_debt/wariness`、`centrifuge_log.legitimacy_pct/amount/base`、`factions.edict_overdraw`、`characters.seed_guilt/identity`——**永不呈现玩家，连定性标签都不播报**（对齐母 ADR 决定3「轴值连定性标签都不播报」）。

风险实证：42 格的设计目的就是「喂叙事」（D2-1），即新值天然要被 simulator LLM 读到；而现存数据通道已实证 raw int 直灌（`db.faction_report()` 产「东林满意75」→ `build_simulator_context` `json.dumps` 原样进 simulator system instructions）。`legitimacy_pct=99` 这种字段名本身读着就是「合法性百分比」，是 LLM 最易顺嘴播报的指标。故两条强制点：

1. **接口层定性翻译**：这些字段**不裸进 simulator-narration payload**。需叙事时只喂**定性档**（新增 `memories` 侧翻译，把 blood_debt/legitimacy_pct 转「阉党记恨已深 / 此罚名实相称」式定性串），或显式声明只进 extractor-side、不进 narration payload。落 prompt 用正向表述（「以奏对口吻定性描述派系态度」），不写「不要显示数值」式负向句。
2. **哨兵测试 = DoD 硬项（非悬空 claim）**：既测原始整数不回显（sentinel int），也加 **paraphrase / 概念泄漏断言**（narration 不得含「合法性%」「失称度」「血债」等系统词面）；同步扩 `season_simulator.md` 散文禁令枚举，点名血债 / 失称度 / 合法性百分比。

**若本 ADR 第一刀不接 simulator-narration（只落库、叙事接口后续做）**：在 defer 清单显式写「血债字段 P4 呈现层 = defer」，**别留「哨兵测试防泄漏」这种已承诺却不存在的兜底**。

---

## 后果

### 北极星验证（喂得出 90 分吗）

查隐田 → seed-guilt 不止阉党（东林钱谦益带轻污、认同度 58；非阉党带罪仅 2 人轻 + 福王）→ 刀有机割到自己人；负责者犹豫 = LLM 在账本约束内软判；玩家早先埋的「自首补税」软线 = 过去布局决定此刻余地；公正处置（查实真隐田 no 罗织 + 给相称出路 = 失称度低 → **血债≈0**，敬重落 `satisfaction` 可逆层）→ 下一回合 LLM **读到这个持久状态、接着公正地演**，不失忆翻案。**这套 schema 喂得出。**

### 落地顺序（硬序铁律）

血债 schema（本 ADR）+ 矩阵 42 立场值（dig-5）+ identity 列（dig-6）+ seed-guilt（dig-7）+ ceiling 表（dig-9）**先落**；四层票拟（dig-8）resolve **后做**（它读上述 substrate，零实现则读空值退化纸面、破局无 substrate 可读）。别先搭四层框架。

### 调参 / playtest

`SEVERITY_BASE` / `CRIME_BY_CODE` / α/β/γ/δ / ceiling 精确值 = **首版**，随矩阵 playtest 调参（镜像 spike G1-G22 方法学：独立 oracle + 末态硬期望 + ~20 mutation 自验）。**硬下界不变式（D2-7）不是调参旋钮。**

### defer 清单（明确不在第一刀）

provisional / 中旨闸第二刀（D2-8）；H5 彻底归零（独立结构化实体抽取层，母 ADR 决定5）；后期大臣再犯新罪（emergent，第一刀只做预装历史欠账）；per-轴 identity（矩阵的活）；#89 大臣系统（loyalty/ability/integrity/courage 接机制、identity 动态漂移、叛变硬概率 / 关系图）。越此即停手归 #89。

### 评审

本 ADR 是设计文档，按 CLAUDE.md 铁律产出后必跑完整评审闭环（本地 cmr 收敛 + 线上三 bot 收敛），不因「只是文档」跳步。**本轮评审重点盯六处 ⚠️**（①–③=fold 期 reconcile，④–⑥=内部红队攻破已修、须复裁）：① D2-1/D2-3 的 42 格 → 新表 schema 翻案；② kinship 去 max(1) 下界对 dig-4 单调语义的 0-vs-1 边界冲击；③ D2-7 净负硬下界与 dig-9 出路恒可达的相容性；④ H5 `source_name`→faction 解析契约（跨派同名别名 `袁巡抚` 实证可诱导）；⑤ P4 新增字段呈现契约（接口层定性翻译 + 哨兵 DoD）；⑥ 中旨钱-封驳 append-only 双笔 vs 金手指虚存审计。实现属编码活、按工作流分工交隔壁 session。

### 出处

由 design-dig fan-out 合成：dig-4（9-agent 4 方案 → 对抗攻击 → 合成）、dig-5（14-agent 两路 42/42 一致）、dig-6（4-agent 认同度层）、dig-7（9-agent seed 六等）、dig-9（ceiling-sensitivity workflow）。用户 2026-06-14 设计 session 逐点拍板。承母 ADR 决定2 + CMR r1（commit `dfe8482`）+ parked r2。**草稿后经内部对抗预检**（15-agent：7 fold 保真核 + 8 承重 claim 红队，2026-06-14）——修 5 处 P1（人人有点脏 / 母 ADR 钱归宿矛盾 / H5 跨派别名 / provisional 第4坑 / P4 字段泄漏）+ 2 处 P2，5 处承重 claim 攻不破（42格→新表 / kinship 0-边界 / 净负 vs 出路恒可达 / build-upon / H2 棘轮），再进正式 CMR。
