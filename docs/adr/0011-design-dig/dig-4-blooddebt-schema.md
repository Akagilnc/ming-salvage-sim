# 血债棘轮 schema 收口 — 深挖 ledger（2026-06-14，承 #112，ADR 0011 决定2 sub-ADR 0011-2）

> 全量在 task 输出：`/private/tmp/claude-501/.../tasks/w66wpeyio.output`（9-agent design panel：4 方案 → 对抗攻击 → 合成）。**设计累积，未写 ADR/未实现。** 实现属编码活、spawn 隔壁。

## 选型（攻击驱动，非自夸）
**方案1（极简逐派列）为骨架**（9 攻击向量 7 没破，唯一破 H5=母 ADR 留 sub-ADR、四方案同源）+ 嫁接方案2 append-only 审计账。
落选致命洞（实测）：方案2 critical=透支账寄生 metrics 表被 clamp[0,100]+白名单双杀；方案3 4×high=罪档无结构化真源+42格过度工程；方案4 high=provisional 转 final 托付不存在的"月初 tick"，撞 pre_settle:190 早退软死锁。

## 第一刀 DDL（走 ensure_column 幂等 ALTER，老档补0）
```sql
factions: +blood_debt INTEGER DEFAULT 0   -- 血债棘轮，逐派单调不减 floor
          +wariness   INTEGER DEFAULT 0   -- 同类防备底，单调
          +edict_overdraw INTEGER DEFAULT 0 -- 皇权透支账(中旨/廷杖频度，H1/H4)
centrifuge_log(append-only): id,turn,faction(FK),kind(direct|kinship|overdraw),base,
  legitimacy_pct,amount(CHECK>=0),source_name,reason_code(0009列),source(0008),
  idem_key(UNIQUE,防0008重跑二次累加),created_at
  -- 审计真源；4 列是 O(1) 缓存可由 SUM 重建(恢复端对账不变式)
-- 失望=factions.satisfaction(复用,避双真源)；leverage=factions.leverage(双轴解耦)
```

## 算式
- severity = SEVERITY_BASE{申饬3,罢黜10,廷杖40,抄家70,诛100}（结构化处置类型，非措辞）
- crime_weight = CRIME_BY_CODE{获罪削籍70,陷虏50,''=10}；STIGMA{中旨除授,非正途,罗织}→crime=1
- legitimacy_pct = clamp(10 + 90×mismatch/severity, 10,100)；mismatch=max(0,severity−crime_weight)（失称度版避除零）
- Δblood_debt(目标派,direct)=round(severity×legitimacy/100)
- Δwariness(同派旁观,kinship)=max(1,round(severity×legitimacy/100×0.3))（吃折扣不到0）
- **数值例**：同抄阉党(sev70)：走程序抄真贪(crime70,leg10%)→+7；小罪重罚(crime10,leg87%)→+61；中旨罗织(crime1,leg99%)→+69+透支账。**血债差 8.7倍=决定5"攒合法性别硬来"教学曲线落数。**

## 4 不变式代码层强制点
1. 单调棘轮：唯一写函数 accrue_blood_debt(只+=,assert>=0)+CHECK+idem UNIQUE+静态围栏(扩0009 allowlist)；mutation 把+=改=立即咬。
2. 阻力/称病只读血债：函数签名物理不接 satisfaction 参数、SQL 不 SELECT satisfaction；adjust_factions 只动 sat/lev 碰不到 blood_debt。
3. 不可跨派冲抵：accrue 按 faction PK 单派 UPDATE，全库无"A转B"签名；安抚东林改东林 sat 列，与阉党 blood_debt 不同行不同列物理无法相消。
4. 血债≠leverage：两列两写路径(blood_debt 走 accrue/严重度派生；leverage 走 adjust/局势派生)，不共享写函数。

## 净负 vs 棘轮（最硬张力的解）
```
resistance = max( floor=α×血债 , min(ceiling, dynamic_term) )   ← 血债进 floor 臂(冻土)
net_centrifuge = Σ(Δsat项 + Δlev项)  显式不含血债(签名不接)        ← 净负烧薄冰
```
血债=冻土(单调floor,压不动)，失望/leverage=薄冰(可动)。破局移动薄冰、烧不掉冻土。
+ 硬下界不变式：floor 不得碾平至少一条可执行净负动作（防纸面净负实操死锁）。
+ 净负路收窄："≥1派未触底(sat>0或lev>0)则恒存"；全派打穿=决定6允许的涌现尽头非钦定。α/β/γ/δ playtest 调参(sub-spec)，但下界是硬不变式。

## H1/H2/H5/H6 闭合
- H1：edict_overdraw 落 factions 列(不落 metrics,规避双杀)，applier 内撞派+=1单调。残留：归派精度依赖轴矩阵(defer)，第一刀粗粒度按 target faction。
- H2：不变式1+2(唯一写只+=、读侧不SELECT satisfaction)。攻击判"真正的棘轮牙、攻不破"。
- H5：受害派faction(SQL查characters.faction)+crime_weight(reason_code枚举)+severity(查不中落最低档保守)三入参全结构化；**残留**=target_name 抽取这跳过extractor(收窄非归零，name须命中既有行+faction由DB锚骗不出跨派)。彻底归零需独立结构化实体抽取层，留母ADR决定5。
- **H6：第一刀不做、随中旨闸 defer 第二刀**（反过度工程；提前做必撞软死锁/套利）。

## provisional（第二刀设计，避3坑）
①转final扫表放 settle 后半段 atomic 内、对 before_turn 幂等（不放 pre_settle，避早退软死锁）；②expires_turn 到必转 final（避0008毒payload永挂）；③fungible 钱照落 live 国库+封驳窗 W=1 压窗+当回合正反账冲销（status类后果H6真闭、涉钱只压窗不全闭——P1×H6 固有张力，不假装两全）。

## sub-ADR 0011-2 决定点骨架
D2-1 粒度(scalar vs 轴) / D2-2 真源vs缓存(log真源,列缓存) / D2-3 列vs新表(列,避metrics双杀) / D2-4 合法性算法(失称度) / D2-5 crime载体(reason_code+STIGMA独立常量) / D2-6 4不变式强制点 / D2-7 净负公式 / D2-8 provisional归属(defer) / D2-9 0008/0009 build-upon点。每点配弃案+攻击残留诚实标，按铁律跑 cmr 收敛再进实现。

## 5 个待用户拍（我的推荐）
1. **【最关键】粒度**：逐派 scalar(推荐,第一刀)vs 逐派×轴(42格,defer)。提案=先scalar、log预留axis列、按需升。
2. **provisional/中旨闸 defer 第二刀**：认可（第一刀H6暂不闭，与"四层票拟整套defer"一致）。
3. **合法性算法**：失称度版(推荐)vs比值版(要新建罪档表)。
4. **fungible H6**：接受 status闭/涉钱W=1压窗不全闭（escrow违P1审计）。
5. **7派外faction血债语义**：推荐"血债=朝堂7派专属"，外压派(后金/流寇)走外压系统、后宫defer，不进血债账。
