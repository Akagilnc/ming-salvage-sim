# 四层票拟 resolve + 中旨 + 执行层 schema（ADR 0011 决定4/5 子 ADR · 0011-5）

Status: Proposed（草案；承母 ADR `0011-edict-resistance-and-centrifuge-ledger.md` 决定4（两阶段五结局 + 四层票拟全幕后）+ 决定5（中旨 / 密令代价曲线），由 design-dig `dig-8` fold 而成。**待评审**——按 CLAUDE.md 设计文档铁律走本地 cmr 收敛 + 线上三 bot 收敛，未收敛前不进实现期。实现属编码活、spawn 隔壁。）

承 GitHub #112 tracker。本 ADR 是**圣旨颁布阻力网的心脏** + **排最后**：`resolve_directive` 是全部 substrate（血债 0011-2 / 矩阵 0011-3 / ceiling+seed 0011-4 / identity）的汇流口，把「圣旨未必颁得出、颁了未必有效、actor 各有算盘」做成一次幕后纯函数。**硬序铁律：substrate 先落、本 ADR 后做**（零 substrate 则 resolve 读空值退化纸面、破局无料可读，别先搭四层框架）。

## 为什么排最后 + 为什么是纯函数

母 ADR 决定4 把四层票拟的精确契约留给本子 ADR。grep 实证四层逻辑（票拟 / 批红 / 封驳 / 六科 / 中旨）**当前零存在** = 纯 net-new、最重。它读 substrate 判离心 / 命门 / 失称度 / 认同度，**若 substrate 未落则读空值** → resolve 退化成纸面、破局曲线无数可算。故排在 0011-2/3/4 之后。

设计取**镜像省级 `settle_tick` 范式**：程序算账（确定性、可 golden 测试），LLM 只叙事。质量标尺仍是北极星——resolve 要让「硬抄宗室撞 91 高墙 vs 查实坐实塌到 35」这条 **8.7 倍破局曲线**从确定性算出，LLM 只把它叙事成邸报，而不是 LLM 即兴判圣旨过不过。

## 核心：`resolve_directive(action, substrate, mode)` 一次幕后纯函数

- **读全 substrate**（0011-3 矩阵 / 0011-2 血债 + 失称度 / 0011-4 ceiling + seed / identity）→ 短路输出 `ResolveResult{ outcome, blocked_layer, exec_fidelity, per_layer 诊断串, 反咬列表, 机械后果包 }`。**LLM 只叙事、零算账**（镜像 settle_tick：程序定胜负、LLM 描花样）。
- **召对侦察 = 同函数 `dry_run=True`**（单一真源：侦察口径 ≡ 实际 resolve 口径，玩家能信；严守只读、不落库、不推回合，见 D5-3）。
- **彻底替换 `estimate_resistance`**（tools.py:148 的拍平 `AVG(leverage)` 启发式）；插在 `propose_directive`（tools.py:254）之后、落 `directives` 表之前。
- **build-upon**：ADR 0004 `pre_settle`/`settle_with_delta` 同核 / 0008 `applier.atomic` / 0009 `reason_code`（见 D5-10）。

---

## 决定点（D5-1 ~ D5-10）

> 每点给：**决定 / 弃案 / 残留诚实标**。带「⚠️ CMR」的须本轮评审复核。

### D5-1 resolve_directive = 一次幕后纯函数（LLM 零算账）

**决定**：四层票拟**一次 resolve、全幕后、零新面板**（母 ADR 决定4 的「轻交互」契约）。程序算出胜负 + blocked_layer + 后果包，LLM 只把结果叙事成邸报（六科封还、阉党阳奉阴违、某老臣称病）。玩家接口三件不变（母 ADR 决定4）：事前召对定性谏言、决策三选、事后邸报复盘。

**弃案**：逐层交互点击（点击疲劳、违轻交互 / 「不是 CK3」）；裸阻力数值面板（违 P4）；LLM 自由判圣旨过不过（违 settle_tick 范式、不可 golden、不可复现破局曲线）。

### D5-2 四层（各读不同 substrate，故「同一道旨撞的层不同」）

**决定**：

1. **内阁票拟**（软否决：封还 / 拟温和版 / 辞职逼宫）——东林 + 中立把着，读 0011-3 东林礼法 / 祖制轴立场 + 0011-2 血债 floor。**中旨绕此层**（D5-6）。
2. **司礼监批红**（阉党承重功能 = 母 ADR 决定8）——阉党核心把着，读阉党 satisfaction/leverage + identity。**清了阉党 → 从「顺」翻「失能阻力」= 自我致盲**（北极星；根因 B1/#9 退场 leverage 联动未做，决定8/0011-2 D2-9）。
3. **六科封驳**（硬否决，最关键，中旨天敌）——六科 + 御史，读 ① ceiling（0011-4）② 是否中旨 ③ 失称度（0011-2 D2-4）。**破局核心层**。
4. **部院执行**（阶段二：忠实 / 打折 / 阳奉阴违 / 反噬）——承办派把着，读 0011-3 立场 + 0011-2 血债 + identity。FF-5 承重功能负片在此（阉党瞒报 / 军队哗变 / 中立怠政 / 东林清议 / 宗室串联 / 西学撂挑子）。后果落 issues 停滞 + factions 离心，**不扩 status enum**（合 0009）。

**弃案**：四层读同一 substrate（则「同一道旨撞的层不同」表达不出）；执行层后果扩 status enum（违 0009「不为风味态扩 enum」）。

### D5-3 召对侦察 = 同函数 `dry_run=True`（单一真源）

**决定**：召对大臣给的定性谏言（母 ADR 决定4 接口①）= `resolve_directive(..., dry_run=True)`——**与实际 resolve 同一函数同一口径**，只是不落库、不推回合、输出转成大臣 in-character 的话（「六科那边怕要争」「此事撞了清议」）。

- **单一真源**：侦察 ≡ 实际 = 玩家能信谏言（不是另算一套估算）。
- **只读铁律**：`dry_run=True` 物理不写任何表、不调 applier、不 `next_period`（守 P1 / 事务边界）。
- 谏言**不暴露价值轴这个系统概念**（P4，轴永不呈现）——信号是大臣的话与态度、不是 axis 标签。

**弃案**：召对另起一套估算公式（侦察 ≠ 实际 = 谏言不可信，回到 `estimate_resistance` 拍平启发式的老病）。

### D5-4 per_layer_resistance 公式 + 短路 blocked_layer

**决定**（消费 substrate，不另定义；逐层短路）：

```
per_layer_resistance = max( min(cap, α×血债)[0011-2 D2-7] , 命门合法性floor[0011-4 D4-3] , min(ceiling[0011-4], dynamic_term) )
```

- **dynamic_term** = 该层把关派系的当下激烈度（读 satisfaction/leverage/identity）。**含议和外压 dynamic 臂**（0011-3 D3-4）：华夷议和题，外压够大 → 务实派 dynamic_term 降 → 该层 resistance 降（议和可颁的第二出路，非翻轴）。
- **逐层短路出 `blocked_layer`**（✅ 用户拍④）：四层依次算，第一层 resistance 超阈即短路、记 `blocked_layer`（实现取定，邸报复盘 + 破局都要「卡哪层」）。
- 公式三臂的真源在别处（血债 floor=0011-2、命门 floor + ceiling=0011-4），**本 ADR 只组装 + 短路、不重定义**（避双真源）。

**弃案**：把三臂在本 ADR 重新定义（双真源漂移）；不出 blocked_layer 只给 pass/fail（邸报复盘 + 破局教学无「卡哪层」可讲）。

### D5-5 破局机理（走程序坐实 → 翻轴 → 符号翻 → 顺颁）

**决定**（今晚所有 substrate 汇成一回路）：抄既得权贵（命门，ceiling 高被挡）——

- **硬推** → 血债 +69（罗织、失称度饱和 0011-2 D2-4、六科顶封）。
- **聪明解** = 先走 actor 取证坐实真罪（厂卫 / 政敌 / 苦主）→ `reason_code = 依律` → **旨意轴翻转**（0011-4 D4-4(a)）：「任性夺权（撞礼法）」→「依律惩贪（合礼法）」→ **矩阵符号翻**（0011-3）：东林从封还变背书、六科无从科参 → 顺颁 + 血债 +7。
- **同道旨走程序 vs 硬推差 8.7 倍**（0011-2 D2-4 数值）。**不是绕 ceiling，是把动作从命门题变非命门题**。
- 串起：失称度（0011-2）+ 矩阵符号（0011-3）+ seed-guilt 真靶子（0011-4 B）+ actor 取证（信息 actor-mediated）+ 认同度（善待边缘人 → 反正 → 当取证的刀）。史实锚 = 定逆案 262 人走程序清阉党 vs 国本之争硬撞祖制 15 年完败。

**弃案**：破局 = 绕过 ceiling 的特例 / 后门（gamey、违 organic）；破局 = 数值堆够就过（抹平「攒合法性」的教学）。

### D5-6 中旨（绕内阁、六科照封、三代价落库；provisional defer 第二刀）

**决定**（母 ADR 决定5 / ✅ 用户拍③）：

- **绕内阁**（L1 置 0）= 中旨唯一买到的；**六科照样封驳且陡升**（`MIDZHI_PENALTY`）→ 行政旨几乎无伤、**命门题照样打回**（白绕、还多担「非正途」污名）。代价曲线 = 命门陡 / 行政平。
- **三代价落库**（P1）：`STIGMA` reason_code（0011-2 D2-5）→ 血债陡 + `edict_overdraw`（0011-2）+ 污名。
- **第一刀映射「一意孤行 = 必碰壁打回」**（✅③ 埋伏笔）：第一刀给「中旨」选项但**映射成「硬推 = 必碰壁打回」**，真中旨闸（provisional 等）随第二刀接。
- **provisional / 未生效标记 = defer 第二刀**（H6；最低契约已由 0011-2 D2-8 钉死：钱拨了被封驳 = 没了〔史实〕、status 类压窗 W=1 当回合作废、转 final 放 settle 后半段 atomic 对 before_turn 幂等、绝不放 pre_settle 避软死锁）。本 ADR **不重复 0011-2 D2-8 的 provisional 契约**，只声明四层侧的消费点。

**弃案**：第一刀就做真中旨闸（必撞软死锁 / 套利，0011-2 D2-8 实测）；中旨能稳过命门题（违代价曲线、变拐杖不是工具）。

### D5-7 执行层（阶段二：忠实 / 打折 / 阳奉阴违 / 反噬）

**决定**（母 ADR 决定4 阶段二 + 决定8 FF-5 承重功能负片）：旨意过了四层颁出后，执行层按承办派的 satisfaction/血债/identity 软判执行保真度——忠实 / 打折扭曲 / 阳奉阴违 / 反噬。FF-5 反咬（阉党瞒报掺水 / 军队拥兵不前 / 中立怠政 / 东林辞官 / 宗室串联 / 西学撂挑子）= 各派承重功能负片。

- **后果落已有槽位**：issues 停滞 + factions 离心，**不扩 status enum**（装病 = 叙事风味，consequence 落「issue 不进 / 不动」）。
- **第一刀 defer 四态细分**（✅②）：第一刀只做颁布关；执行层四态**第二刀**做（可选先粗做忠实 / 打折两档）。

**弃案**：执行层第一刀就做四态（超第一刀 scope）；反咬后果扩 status enum（违 0009）。

### D5-8 第一刀 scope（严格只颁布关 顺颁 / 打回两档）

**决定**（✅ 用户拍②，严格收口第一刀）：

- **第一刀 = `resolve_directive` 确定性骨架，只做阶段一颁布的「顺颁 / 打回」两档**，替换 `estimate_resistance`；召对 dry-run 只读；邸报复盘；**打回 → 触发二次决策点**（重新想缝在哪，母 ADR 决定4）。
- **defer 第二刀**：中旨闸整套（provisional / edict_overdraw 螺旋）；执行层四态细分；provisional 生命周期；召对 location 闸（FF-4，决定8）。

**弃案**：第一刀就铺四层全套 + 中旨 + 执行层（过度工程、违硬序「别先搭四层框架」）。

### D5-9 硬序铁律（substrate 先落、resolve 后做）

**决定**：硬前置 = 血债 schema（0011-2）+ 矩阵 42 值（0011-3）+ identity 列 + seed-guilt（0011-4 B）+ ceiling 表（0011-4 A）**先落**；`resolve_directive`（本 ADR）**后做**（读上述 substrate，零实现则读空值退化纸面、破局无 substrate 可读）。**别先搭四层框架。**

**弃案**：先搭四层框架占位、substrate 后补（resolve 读空值、第一刀就是纸面 demo）。

### D5-10 build-upon ADR 0004 / 0008 / 0009

**决定**（明确依赖，非无成本复用）：

- **0004**：颁旨链复用 `pre_settle`/`settle_with_delta` 同核（ADR 0004），resolve 插在 propose 后、落 directives 表前。
- **0008**：中旨 provisional 转 final（第二刀）走 `applier.atomic`、对 `before_turn` 幂等（0011-2 D2-8）。
- **0009**：`reason_code`（依律集 / STIGMA）= 扩 0009 enum + 协调静态围栏（与 0011-2 D2-5/D2-9、0011-4 D4-8 同一扩展批次，避免各扩各的撞车）；召对 location 闸（FF-4）依赖 0009 `location`（第二刀）。

---

## 自检（10 条，dig-8 全过）

1. **轻交互真没堆成 CK3**：一次 resolve、blocked_layer 只进邸报复盘，零新面板。
2. **读 substrate 对**：逐条核 0011-2/3/4 的值与字段。
3. **破局非灭亡**：ceiling 硬墙但走程序压成顺颁（D5-5）、dig-2 红线守死不内嵌判负（母 ADR 决定1）。
4. **中旨第一刀自洽**：映射「硬推必碰壁打回」、真中旨闸 defer（残留诚实标）。
5. **gaming 扫洞**：① 中旨绕四层 → 六科照封 + 透支账（0011-2）；② 话术诱导降敏感度 → 结构化查表（0011-4 D4-5 / 堵 H5）；③ 召对侦察套利 → dry_run 只读。
6. **build-upon 0004/0008/0009**（D5-10）。
7. **召对 dry_run 单一真源**（D5-3）。
8. **逐层短路出 blocked_layer**（D5-4，✅④）。
9. **执行层后果不扩 status enum**（D5-7，合 0009）。
10. **硬序铁律**（D5-9）。

## 依赖 substrate（本 ADR 读它们、不在本 ADR 定稿）

- **矩阵**（0011-3）：四层读派系立场判离心方向 / 封驳倾向 / 执行折扣。
- **血债 + 失称度**（0011-2）：per_layer_resistance 的血债 floor 臂 + 六科读失称度 + 破局走程序坐实压失称度。
- **ceiling + 命门合法性 floor**（0011-4）：六科层读 ceiling 判命门、floor 臂；破局翻轴（D4-4a）+ 议和外压杠杆（D4-4b）。
- **seed-guilt + identity**（0011-4 B / dig-6）：破局「真有可坐实的罪」（seed）+ 执行层 / 反咬读 identity；善待边缘人反正当取证刀。
- **中旨 provisional 契约**（0011-2 D2-8）：第二刀消费点。

## defer 清单（明确不在第一刀 / 不在本 ADR）

- **中旨闸整套**（provisional 生命周期 / edict_overdraw 螺旋）= 第二刀（最低契约在 0011-2 D2-8）。
- **执行层四态细分** = 第二刀（先粗做忠实 / 打折两档可选）。
- **召对 location 闸**（FF-4，决定8）= 单独切片（依赖 0009 location）。
- **密令核议结构化输入**（母 ADR 决定5 抄家拿人）= 与中旨第二刀同批 or 单列。

---

## 后果

### 北极星验证（喂得出 8.7 倍破局曲线吗）

硬抄福王（命门，ceiling≈91）→ resolve 短路 blocked_layer = 六科封驳（ceiling + 命门 floor 顶满）+ 血债 +69（0011-2 失称度饱和）→ 邸报「六科封还、清议汹汹」+ 二次决策点。聪明解：先 actor 取证坐实通寇 → reason_code = 依律 → 翻轴（0011-4 D4-4a）→ 矩阵符号翻（东林背书）→ resolve 顺颁 + 血债 +7。**resolve 把这条 8.7 倍曲线确定性算出、LLM 只叙事**——破局教学从「撞运气」变「稳定可复现」。这套四层 resolve 喂得出。

### 落地顺序（硬序铁律）

substrate（0011-2/3/4）**全先落** → `resolve_directive` 确定性骨架（本 ADR 第一刀，只颁布关 顺颁 / 打回）→ 替换 estimate_resistance → 召对 dry-run → 邸报复盘。第二刀（中旨闸 / 执行层四态 / location 闸）后接。

### 调参 / playtest

per_layer_resistance 的阈值 + MIDZHI_PENALTY + dynamic_term 权重 = **首版**，随 substrate α/β playtest 调参（镜像 spike G1-G22：独立 oracle + 末态硬期望 + mutation 自验）。**逐层短路语义 / dry_run 单一真源 / 硬序 = 设计与不变式、不是调参旋钮。**

### 评审

本 ADR 是设计文档，按 CLAUDE.md 铁律产出后必跑完整评审闭环（本地 cmr 收敛 + 线上三 bot 收敛），不因「只是文档」跳步。**本轮评审重点盯**：① resolve 纯函数「LLM 零算账」与现有 simulator 裁判规则（season_simulator.md）的边界——四层确定性算账后 LLM 还叙事什么、会不会偷偷重算；② per_layer_resistance 组装公式与三臂真源（0011-2/0011-4）是否真单一真源、无重定义；③ 议和外压 dynamic 臂在 dynamic_term 里的落点是否与 0011-3 D3-4 / 0011-4 D4-4(b) 一致；④ 第一刀 scope（只顺颁 / 打回）是否真自洽——中旨映射「必碰壁打回」会不会让第一刀的中旨选项变成纯装饰；⑤ 召对 dry_run 只读铁律的事务边界（不写表 / 不推回合）与 ADR 0004/0008 是否相容。实现属编码活、交隔壁 session。

### 出处

由 design-dig `dig-8` fold：5-agent（ground 颁旨链 + 四层史实 + 3 路设计 + 合成）。用户 2026-06-14 设计 session 拍板 5 问（① ceiling 跟矩阵一起拍 + 出路恒可达先锁 / ② 第一刀只颁布 顺颁/打回、执行层 defer / ③ 中旨第一刀给但映射必碰壁 / ④ 逐层短路出 blocked_layer / ⑤ kinship 改动血债 sub-ADR 带、四层另起 sub-ADR）→「四层票拟定稿」。承母 ADR 决定4 / 决定5。读全 substrate（0011-2/3/4）。**草稿后待内部对抗预检 + 正式 cmr。**
