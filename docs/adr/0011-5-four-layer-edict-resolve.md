# 四层票拟 resolve + 中旨 + 执行层 schema（ADR 0011 决定4/5 子 ADR · 0011-5）

Status: Accepted（承母 ADR `0011-edict-resistance-and-centrifuge-ledger.md` 决定4（两阶段五结局 + 四层票拟全幕后）+ 决定5（中旨 / 密令代价曲线），由 design-dig `dig-8` fold 而成。**评审收敛**——本地 ship-pre cmr R1–R8 4/4 concur（2026-06-15）+ 线上 PR #123 R1–R3 评审收敛；PR #123 已 merge（`847dc3da5`，2026-06-15）转 Accepted。实现属编码活、spawn 隔壁。）

承 GitHub #112 tracker。本 ADR 是**圣旨颁布阻力网的心脏** + **排最后**：`resolve_directive` 是全部 substrate（血债 0011-2 / 矩阵 0011-3 / ceiling+seed 0011-4 / identity）的汇流口，把「圣旨未必颁得出、颁了未必有效、actor 各有算盘」做成一次幕后纯函数。**硬序铁律：substrate 先落、本 ADR 后做**（零 substrate 则 resolve 读空值退化纸面、破局无料可读，别先搭四层框架）。

## 为什么排最后 + 为什么是纯函数

母 ADR 决定4 把四层票拟的精确契约留给本子 ADR。grep 实证四层逻辑（票拟 / 批红 / 封驳 / 六科 / 中旨）**当前零存在** = 纯 net-new、最重。它读 substrate 判离心 / 命门 / 失称度 / 认同度，**若 substrate 未落则读空值** → resolve 退化成纸面、破局曲线无数可算。故排在 0011-2/3/4 之后。

设计取**镜像省级 `settle_tick` 范式**：程序算账（确定性、可 golden 测试），LLM 只叙事。质量标尺仍是北极星——resolve 要让「硬推罗织阉党重罪 + 血债 +69 vs 走程序坐实真重罪 + 血债 +7」这条破局曲线（**血债 ≈10 倍、ceiling ≈2 倍**，0011-2 D2-4 真源）从确定性算出，LLM 只把它叙事成邸报，而不是 LLM 即兴判圣旨过不过。

## 核心：`resolve_directive(action, substrate, mode)` 一次幕后纯函数

- **读全 substrate**（0011-3 矩阵 / 0011-2 血债 + 失称度 / 0011-4 ceiling + seed / identity）→ 输出 `ResolveResult{ outcome, blocked_layer, per_layer 全诊断串, 反咬列表, 机械后果包；exec_fidelity（第一刀 = None / 未算、仅第二刀执行层填，D5-7/D5-11） }`。**LLM 只叙事、零算账**（镜像 settle_tick：程序定胜负、LLM 描花样；硬约束见 D5-11）。
- **召对侦察 = 同纯算核 `dry_run=True`**（单一真源：侦察口径 ≡ 实际 resolve 口径，玩家能信；物理只读护栏见 D5-3）。
- **替换 `estimate_resistance`**（`tools.py:136` def、拍平 `AVG(leverage)` 启发式在 `:147`）；落库时序与 `add_directive` 的关系见 D5-3 / D5-10（**非简单「propose 后落表前」**，须校正）。
- **build-upon**：ADR 0004 `pre_settle`/`settle_with_delta` 同核 / 0008 `applier.atomic` / 0009 `reason_code`（见 D5-10）。

---

## 决定点（D5-1 ~ D5-11）

> 每点给：**决定 / 弃案 / 残留诚实标**。带「⚠️ CMR」的须本轮评审复核。

### D5-1 resolve_directive = 一次幕后纯函数（LLM 零算账）

**决定**：四层票拟**一次 resolve、全幕后、零新面板**（母 ADR 决定4 的「轻交互」契约）。程序算出胜负 + blocked_layer + 后果包，LLM 只把结果叙事成邸报（六科封还、阉党阳奉阴违、某老臣称病）。玩家接口三件不变（母 ADR 决定4）：事前召对定性谏言、决策三选、事后邸报复盘。**LLM 如何吃判决（硬约束、禁重算）= D5-11。**

**弃案**：逐层交互点击（点击疲劳、违轻交互 / 「不是 CK3」）；裸阻力数值面板（违 P4）；LLM 自由判圣旨过不过（违 settle_tick 范式、不可 golden、不可复现破局曲线）。

### D5-2 四层（各读不同 substrate，故「同一道旨撞的层不同」）

**决定**（阶段一三层产 `blocked_layer`，阶段二部院产 `exec_fidelity`，两类不混入同一短路序列——P1-6）：

**阶段一·颁布（产 blocked_layer，前三层）**：

1. **内阁票拟**（软否决：封还 / 拟温和版 / 辞职逼宫）——东林 + 中立把着，读 0011-3 东林礼法 / 祖制轴立场 + 0011-2 血债 floor。**中旨绕此层**（D5-6）。
2. **司礼监批红**（阉党承重功能 = 母 ADR 决定8）——阉党核心把着，读阉党 **leverage（+ 血债 floor）**（**不读 satisfaction 入阻力**——阻力 / 称病只读血债〔非失望〕，0011-2 D2-6 不变式2 / H2 堵好回合洗白；satisfaction 是失望 / 召对层、走净负不入阻力。**亦不读 identity 入阻力**——只缩 kinship，0011-2 D2 限定）。**清了阉党 → 从「顺」翻「失能阻力」= 自我致盲**（北极星；根因 B1/#9 退场 leverage 联动未做，决定8/0011-2 D2-9）。
3. **六科封驳**（硬否决，最关键，中旨天敌）——六科 + 御史 = **制度性命门把关、非朝堂 7 派之一**，故 L3 阻力**不读某派血债 / leverage / dynamic_term**，而读 ① ceiling（0011-4）② 是否中旨（MIDZHI 污名项，D5-6）③ 失称度（0011-2 D2-4）④ 命门合法性 floor（0011-4 D4-3）= **纯制度命门项**。这正是「命门题即便各派 dynamic 低也被合法性 floor 托到 ceiling」（国本之争原型）的落点 = **命门必由六科挡**不变式（D5-4）的结构来源。**破局核心层、命门题真墙**。（dynamic_term〔派系当下阻挡力〕只用于 L1 内阁 / L2 批红 / L4 部院这些 7 派把关层，L3 六科无单一把关派系。）

**阶段二·执行（产 exec_fidelity，第一刀 defer 见 D5-7/D5-8）**：

4. **部院执行**（忠实 / 打折 / 阳奉阴违 / 反噬）——承办派把着，读 0011-3 立场 + 0011-2 血债；**identity 仅经 kinship 旁及反咬强度**（不入 resistance）。FF-5 承重功能负片在此（阉党瞒报 / 军队哗变 / 中立怠政 / 东林清议 / 宗室串联 / 西学撂挑子）。后果落 issues 停滞 + factions 离心，**不扩 status enum**（合 0009）。

**弃案**：四层读同一 substrate（则「同一道旨撞的层不同」表达不出）；把 L4 执行层塞进阶段一 blocked_layer 短路序列（范畴错配，P1-6）；identity 入阻力（违 0011-2「只缩 kinship」，P2）。

### D5-3 召对侦察 = 同纯算核 `dry_run=True`（单一真源 + 物理只读护栏）

**决定**：召对大臣给的定性谏言 = `resolve` 的 `dry_run=True`——**与实际 resolve 同一纯算核同一口径**，输出转成大臣 in-character 的话。

- **⚠️ 物理只读护栏（P1-2，不靠「函数体记得别写」）**：拆 **`resolve_core(action, substrate_snapshot, mode) → ResolveResult`（零 db 写、零内存可观察态写、纯算）** + **`apply_resolve(ResolveResult) → 落库`（薄落库层）**。`dry_run` 只调 `resolve_core`；live 调 `resolve_core` + `apply_resolve`。**单一真源落在共享纯算核**（而非含写副作用的整函数）。`resolve_core` 签名只接 **substrate 只读快照 / 视图**、不接可变 `state`——从签名层堵死 db / 内存副作用（防 0008 内存态污染，0008 决定3：DB 回滚不还原内存、召对期不触发 atomic_and_reload）。
- **⚠️ dry_run 不偷写 directive（P1-3）**：实流程 directive 在召对/chat 期即时落库（`session.py:635 self.db.add_directive`、不在 atomic 内、远早于 settle）。`dry_run` 侦察复用 propose 后路径**须显式短路 `session.py:635` 那条 `add_directive`**；测试断言「召对侦察 N 次后 `turn_directives` 行数不变 + state 内存指纹不变」。
- **⚠️ 等价性强制点（P2，单一真源可证伪）**：`dry_run` 是 **wrapper / use-site 层概念、不进 `resolve_core` 签名**（`resolve_core(action, substrate_snapshot, mode)`，无 dry_run 形参）。golden/mutation 断言**侦察路径拿到的 ResolveResult ≡ live 路径在 `apply_resolve` 之前的 ResolveResult**（同一 substrate 快照、`resolve_core` 唯一产出、live 仅追加落库不重算判定值）；mutation 把 live 分支某判定改算法立即咬。列入第一刀 DoD。
- **⚠️ dry_run 须 mode-aware（P2，埋伏笔的事前信号）**：`dry_run` 接 `mode`（顺颁 / 中旨），对命门题产**可区分的两套谏言**（顺颁路「六科必争」vs 中旨路「纵下中旨、六科仍可封还，且落非正途之讥」）——玩家三选前就能从大臣的话读出中旨在此题白绕。
- 谏言**不暴露价值轴 / blocked_layer 标签 / 数值**（P4，见 D5-11）——信号是大臣的话与态度。

**⚠️ 覆盖母 ADR 决定4 line78（P2）**：母 ADR 决定4 接口① 原写「召对谏言**复用 estimate_resistance**」；本条改为谏言走 **dry-run wrapper / use-site 路径**（调纯算核 `resolve_core(action, substrate_snapshot, mode)`；`dry_run` 不进核签名，见 D5-3），`estimate_resistance` 整体废弃（D5-8）。**later-doc-wins、本条覆盖之**，并回标母 ADR line78 指向此处。

**弃案**：靠 atomic 包裹再丢弃事务实现 dry_run（仍走写路径、违物理不写，0008 atomic 只暂停 commit 不阻止写入）；召对另起一套估算公式（侦察 ≠ 实际）。

### D5-4 per_layer_resistance 公式 + blocked_layer（全算、非短路）

**决定**（组装 substrate；blocked_layer 全算取真墙）：

```
per_layer_resistance = max( min(cap, α×血债)[真源 0011-2 D2-7] , 命门合法性floor[真源 0011-4 D4-3] , min(ceiling[0011-4], dynamic_term) )
```

- **dynamic_term** = 该层把关派系的当下阻挡力，读 **leverage + 外压 substrate（powers/classes，母 ADR 决定9）**（**不读 satisfaction**——阻力 / 称病只读血债〔非失望〕，0011-2 D2-6 不变式2 / H2 堵好回合洗白：好回合涨 satisfaction 只动失望 / 召对 + 净负、永不松阻力；阻力的可变部分 = leverage〔多能挡〕+ 外压，持久部分 = 血债 floor。**不含 identity**——只缩 kinship，0011-2 D2 限定）。**dynamic_term 的 base 语义由本 ADR 首次定义**（上游只用它占位 + 定义外压臂降它，无别处真源可撞）；三臂的**值真源**在别处（血债 floor=0011-2、命门 floor + ceiling=0011-4、议和外压调制=0011-4 D4-3），本 ADR 只组装、不重定义那三项。
- **⚠️ 议和外压臂如何击穿命门 floor（P1-4，与 0011-4 D4-3 对齐）**：议和是华夷命门题，命门 floor 把阻力托到 ceiling 85、不受 dynamic_term 影响——故**外压臂不能只降 dynamic_term（会被 max() 短路）**。真机制：**华夷命门 floor 本身吃外压调制**（`华夷命门floor = f(外压 substrate, 代价明白度)`，真源 0011-4 D4-3：华夷 floor 软、祖制硬核 floor 不松）——`外压够大 + 代价够明白`（两合取项，对齐 0011-3 D3-4 / 0011-4 D4-4b）→ 华夷命门 floor 真下调 → 议和 resistance 随之降 → 可颁。议和真正 blocked 在 **L3 六科**；外压经「朝堂主战共识松动 → 六科失清议背书」传导到六科的命门 floor（floor 调制即此传导的落点），非降 L1 务实派 dynamic（那救不了 L3）。
- **⚠️ blocked_layer = 全算三层、命门优先 / 否则顺序第一超阈（P1-6 弃 first-over-threshold-as-truth；Gemini 线上修 argmax 打地鼠）**：阶段一三层**全算**（轻量纯函数），`blocked_layer = ① 若有命门 floor 顶满（≥ceiling）层 → 取最高 tier 命门真墙（通常 L3 六科，战略警示）；② 否则（普通行政旨、无命门真墙）→ 顺序 L1→L2→L3 第一个超阈层`。ResolveResult 带**全三层诊断串**（不短路、防后层无值）。**不变式**：命门 floor 顶满层**必判超阈**（命门题必由六科挡、不因全局阈调高而漏）。
  - **为何不用 raw argmax（Gemini 线上）**：普通旨多层超阈时 argmax 报最高阻层，玩家降了它、下回合又被更前层挡 =「上回合明明过了这层、这回合怎么又卡」的打地鼠困惑；**顺序-第一超阈**保「递进通关」直觉。
  - **为何命门优先压在顺序之上**：命门题某**前层**（如 L2 批红 leverage 高）可能先超阈，纯顺序会误报 L2、漏 L3 六科命门真墙；故 ① 命门真墙优先（战略警示「这是命门、得走程序坐实/外压」），② 仅普通旨走顺序。
- **⚠️ 阈值（P2）**：`resistance 超阈` 的阈**逐层（per-layer）**，与 max() 三臂量纲挂钩；至少钉死「命门 floor 顶满该层必超阈」不变式，与可调的普通层阈区分。首版随 playtest，但此不变式非调参旋钮。

**弃案**：把三臂值在本 ADR 重定义（双真源漂移）；外压臂只降 dynamic_term（被命门 floor 短路、议和悬空，P1-4）；dynamic_term 读 identity（违 0011-2）；first-over-threshold 定 blocked_layer（误报真墙）。

### D5-5 破局机理（走程序坐实 → 翻轴 → 符号翻 → 顺颁）

**决定**（substrate 汇成一回路）：抄阉党核心（命门，ceiling 被挡）——

- **硬推罗织** → 血债 +69（罗织 STIGMA cw=1、失称度饱和 0011-2 D2-4、六科顶封）。
- **聪明解** = 先走 actor 取证坐实**真重罪** → `reason_code ∈ 依律集`（依律 / 谋逆坐实 / 贪墨坐实，0011-2 D2-5 单一真源；崔呈秀真重罪 → cw=70 → 血债低）→ **旨意轴翻转**（0011-4 D4-4a）：命门轴重路由到非命门「依律处置」行 → ceiling 塌 + 血债 +7（罪罚相称）。
- **同道旨走程序 vs 硬推：血债 ≈10 倍（+69→+7）、ceiling ≈2 倍（如崔呈秀 72→35）**（0011-2 D2-4 真源；勿把两根轴混标同一倍数）。**不是绕 ceiling，是把动作从命门题变非命门题**。
- **⚠️ 「矩阵符号翻」的机制桥（P3）**：翻轴后东林态度变化走的**不是 42 格矩阵符号**（「依律处置」是 0011-4 ceiling 表的合成行、非 0011-3 六轴之一，东林对它无 stance）——而是**翻轴使动作不再撞东林护的礼法名节轴 → 东林反对格停 fire → 从「封还」转「无怒 / 不科参」**（注意「无怒」≠「悦 / 背书」；「背书」须该派受益、走 0011-3 D3-8 符号路由，非翻轴必然结果）。
- 串起：失称度（0011-2）+ 矩阵符号（0011-3）+ seed-guilt 真靶子（**重罪全压阉党 = 真有可坐实的罪**，0011-4 B；**宗室如福王仅轻贪吝、无重罪可相称 = 更难的破局靶**）。**⚠️ 两环 #89 诚实标（P3）**：「actor 取证」（厂卫 / 政敌 / 苦主如何产出可坐实证据）= 信息模型设计意图、**机制未设计**（单独切片或 #89）；「认同度当刀（善待边缘人 → 反正 → 取证）」依赖 identity 动态漂移 / 叛变 = **#89**。第一刀 resolve（只读静态 substrate）的破局只到「翻轴需要的 `reason_code = 依律集`」为止——**「谁帮你坐实」这半截无引擎、显式后置**。史实锚 = 定逆案 262 人走程序清阉党 vs 国本之争硬撞祖制 15 年完败。

**弃案**：破局 = 绕过 ceiling 的特例 / 后门（gamey）；数值堆够就过（抹平「攒合法性」教学）；用无重罪的目标（福王）演 +7 聪明解（产不出，P1-8）。

### D5-6 中旨（绕内阁、六科照封、代价落库；provisional defer；正式离心 → M12）

**决定**（母 ADR 决定5 / ✅ 用户拍③；中旨频度／逐派离心 later-wins → #657 contract **§C.8**）：

- **绕内阁**（L1 置 0）= 中旨唯一买到的；**六科照样封驳且陡升**（`MIDZHI_PENALTY`）→ 行政旨几乎无伤、**命门题照样打回**（白绕、还多担「非正途」污名）。代价曲线 = 命门陡 / 行政平。
- **⚠️ MIDZHI_PENALTY = 这道旨的全局污名项、不依赖短路跑到 L3（P1-6）**：挂在 ResolveResult 的中旨 flag 上、**当回合无条件落库**（即便 L2 批红先超阈也照落），不靠循环评估到六科才 fire。
- **⚠️ 第一刀中旨打回仍落可观察代价（P1-7，消除 D5-6/D5-8 矛盾）**：第一刀中旨打回时**仍落不依赖选派的 `STIGMA` 污名**（独立常量表、非 0009 reason_code，D5-10）与 `mode=midzhi` 案卷事实；**不**在当回合写「该派血债」或中旨侧 `edict_overdraw`／向派系扇出累加（旧义 later-wins 废止）。**正式逐派血债／离心／频度反噬落派 → M12**（#657 D+／contract §C.8；0011-2 D2-4 罗织失称度数值例仍作血债**公式**说明，正式撞派落账属 M12）。provisional 生命周期仍 defer（H6；0011-2 D2-8）。`edict_overdraw` **廷杖侧**累加第一刀已建（0011-2 H1），与中旨当下施工脱钩。命门题下中旨可观察代价＝STIGMA（+案卷 midzhi 事实），不是纯装饰。一句锚：**第一刀中旨 = 落 STIGMA + 案卷 midzhi 事实（P1）；正式血债／离心 → M12；provisional defer**。
- **⚠️ 行政旨端代价曲线（P2）**：第一刀「中旨 = 必碰壁打回」**限定命门题**；低敏感行政旨中旨**照过 + 落非正途污名**（与「行政平」曲线一致），不是一律打回（否则行政旨用中旨反比顺颁差、与曲线矛盾）。
- **provisional / 未生效标记 = defer 第二刀**（H6；最低契约已由 0011-2 D2-8 钉死：钱拨了被封驳 = 没了、status 类压窗 W=1 当回合作废、转 final 放 settle 后半段 atomic 对 before_turn 幂等、绝不放 pre_settle 早退守门避软死锁）。本 ADR **不重复 0011-2 D2-8**，只声明四层侧消费点。`MIDZHI_PENALTY` 的真闸（陡升量级）= 第二刀调参（D5-8 调参节，**不与第一刀公式阈值并列**）。

**弃案**：第一刀就做真中旨闸（必撞软死锁 / 套利，0011-2 D2-8 实测）；中旨能稳过命门题；第一刀中旨连 STIGMA／案卷事实都不落（则确为纯装饰）；当回合猜派写 blood_debt／中旨侧 `edict_overdraw`（违 #657 D+）。

### D5-7 执行层（阶段二：忠实 / 打折 / 阳奉阴违 / 反噬）

**决定**（母 ADR 决定4 阶段二 + 决定8 FF-5 承重功能负片）：旨意过四层颁出后，执行层按承办派 satisfaction/血债 + kinship(identity) 软判执行保真度 `exec_fidelity`——忠实 / 打折扭曲 / 阳奉阴违 / 反噬。后果落 issues 停滞 + factions 离心，**不扩 status enum**。

**⚠️ 与现存密令核议的边界（P2，防平行造第二套）**：`season_simulator.md:84-90`「密旨动向」章已实装**密令核议** LLM 软判（核议五项在 :88——可行性 / 能力忠诚 / 目标反制 / 暴露 / 陈词真伪；本行原引 :79-82、后因文件插章漂移，2026-07-08 M12 闸勘正；〔#883 勘正（密令源头隔离，2026-07-17）：密令核议已迁至 `score_extractor_personnel_secret.md` 密令节（核议五项随迁）；`season_simulator` 公共产出依 #883 硬约束不再预读密令〕），母 ADR line91 明说密令「复用密令核议」。执行层四态软判（第二刀）**与密令核议是同一套执行软判、吃 resolve 算出的账本约束，不另起平行核议**（P2 本义保留——「不另起平行核议」现指向 extractor 侧唯一核议）。**第一刀诚实标 = 分裂裁判态**：edict 走 resolve 确定性（LLM 零算账）、密令仍走 LLM 自判 done/failed（写作时锚 simulator；〔#883 后架构：核议主体=personnel_secret extractor〕；密令结构化裁判 = 第二刀收口）；**第一刀公共 simulator prompt 不因 edict 改 resolve 而另造平行密令核议**（隔离两条裁判路径防渗漏；#883 后密令核议只活在 personnel_secret extractor）。

**弃案**：执行层第一刀就做四态（超 scope）；执行层另起一套平行于密令核议的软判（违 dont-overbuild）；反咬后果扩 status enum。

### D5-8 第一刀 scope（严格只颁布关 顺颁 / 打回两档）

**决定**（✅ 用户拍②）：

- **第一刀 = `resolve_core` 确定性骨架，只做阶段一颁布「顺颁 / 打回」两档**，替换 `estimate_resistance`；召对 dry-run 只读；邸报复盘；**打回 → 触发二次决策点**（载体 = HITL `<<DECISION>>` 块，接线见 D5-11）。第一刀中旨：命门题映射「必碰壁打回」+ 落 STIGMA／案卷 midzhi 事实（D5-6；**正式血债／离心 → M12**），行政旨照过 + 污名。
- **⚠️ estimate_resistance 替换面（P2，含 skills.json）**：`estimate_resistance` 是面向大臣的注册工具，`content/skills.json` 三处（`common_skills:8` / `skill_catalog:38` / 描述 `:174`）须同步——召对侦察口径（dry_run resolve）接到玩家暴露的技能名上，或保留技能名内部改派；避免 dangling 注册。列入第一刀写入端 DoD。
- **defer 第二刀**：中旨闸整套（provisional / MIDZHI 真闸量级；旧「edict_overdraw 中旨螺旋」施工义 later-wins → #657 contract §C.8 → M12）；执行层四态细分 + 密令结构化裁判；provisional 生命周期；召对 location 闸（FF-4，决定8）。〔**取代注（2026-07-08 M12 闸回标）**：本行系写作时快照——其中「召对 location 闸（FF-4）」一项已由 **ADR 0096** 兑现、不再是第二刀待办；其余 defer 项不受影响。defer 清单取代注同源。〕

**弃案**：第一刀就铺四层全套 + 中旨闸 + 执行层（过度工程、违硬序）。

### D5-9 硬序铁律（substrate 先落、resolve 后做）

**决定**：硬前置 = 血债 schema（0011-2）+ 矩阵 42 值（0011-3）+ identity 列 + seed-guilt（0011-4 B）+ ceiling 表（0011-4 A）**先落**；`resolve_core`（本 ADR）**后做**（读上述 substrate，零实现则读空值退化纸面）。**别先搭四层框架。**

**弃案**：先搭四层框架占位、substrate 后补（resolve 读空值、第一刀纸面 demo）。

### D5-10 build-upon ADR 0004 / 0008 / 0009 + 码集二分

**决定**（明确依赖）：

- **0004**：颁旨链复用 `pre_settle`/`settle_with_delta` 同核；resolve 落库时序须与现有 `add_directive` 即时写对齐（D5-3，**非简单「propose 后落表前」**）。
- **0008**：`apply_resolve` 落库走 `applier.atomic`；中旨 provisional 转 final（第二刀）对 `before_turn` 幂等（0011-2 D2-8）。`resolve_core` 只读路径**不进 atomic**、live 落库路径才进（D5-3）。
- **0009 + 码集二分（真源 0011-2 D2-5）**：**依律集 {依律 / 谋逆坐实 / 贪墨坐实}（3 码）= 扩 0009 reason_code enum、走程序坐实 flag**（触发 0011-4 D4-4 翻轴；crime_weight 取被坐实罪真实 gravity、**与依律集正交、不固定 cw=70**，见 D2-4/D2-5；`获罪削籍` = 既存定罪状态码、不在翻轴白名单）；**STIGMA {中旨除授 / 非正途 / 罗织} = 独立常量表、不进 0009 enum**（cw=1）。三 sub-ADR（本 ADR / 0011-2 / 0011-4）**引用 0011-2 D2-5 的二分、不各定各的**（破局动作两端读同一集、曲线算得出，P1-10）。`estimate_resistance` 在 `tools.py:136`（def）；召对 location 闸（FF-4）依赖 0009 `location`（第二刀）。〔**取代注（2026-07-08 M12 闸回标）**：末句系写作时快照——FF-4 已由 **ADR 0096** 兑现，不再是第二刀待办；defer 清单取代注同源。〕

### D5-11 resolve ↔ simulator 裁判分界（LLM 吃判决、禁重算）

**决定**（补母 ADR 决定1 承重缝：确定性账本不被 LLM 软判即兴重算成装饰，P1-1）：

- **resolve 的 `outcome` + `blocked_layer` 是 simulator 诏书核销（`season_simulator.md:106-113`）的硬约束输入**（第一刀；**`exec_fidelity` 是阶段二执行层产物、第一刀不入 payload**——D5-7/D5-8 defer、第二刀随执行层四态 + 密令核议侧加）：旨被 resolve 判 `打回` → simulator **只能叙事「搁置不行 / 受阻折损」并写卡在 `blocked_layer`、禁写「已办成」**。第一刀须改 `season_simulator.md` 加正向吃判决指令（「依 `resolve_result.outcome/blocked_layer` 复盘旨意下落」），列入本切片 prompt 文档端 DoD。
- **打回 → 二次决策点接线（P2）**：resolve 判「打回」须把 `blocked_layer` + 反咬列表**注入 simulator payload**；`season_simulator.md` HITL `<<DECISION>>` 章（`:125-141`）补口径「凡 `input.resolve_result` 含被打回旨意，必为其生成一个二次决策块（以卡哪层为 context），不另凭自判造」——使「打回 → 二次决策点」闭环、非悬空。
- **P4 呈现禁令枚举扩（P2）**：`blocked_layer` / `exec_fidelity` / `per_layer_resistance` / `ceiling` / `命门` / `失称度` 等系统词与数值**永不裸呈现**；邸报只把 `blocked_layer` 翻成 in-character 叙事（「六科封还」而非标签 / 数值）。散文禁令枚举**与 0011-2 P4 同批扩 `season_simulator.md`**，哨兵 / 概念泄漏断言纳入本切片呈现端 DoD。

**弃案**：resolve 算完不约束 simulator（LLM 可把打回写成办成 = 母 ADR 决定1 点名的承重缝、确定性账本变装饰）。

---

## 自检（11 条）

1. **轻交互真没堆成 CK3**：一次 resolve、blocked_layer 只进邸报复盘，零新面板。
2. **读 substrate 对**：逐条核 0011-2/3/4 值与字段；**阻力只读 血债 floor / leverage / ceiling / 外压**，**不读 satisfaction**（失望层、走召对 + 净负）、**不读 identity**（只缩 kinship）——0011-2 D2-6 不变式2 / H2 堵好回合洗白。执行层 `exec_fidelity`（非阻力）才读 satisfaction / kinship。
3. **破局非灭亡**：ceiling 硬墙但走程序压成顺颁（D5-5）、dig-2 红线守死不内嵌判负。
4. **中旨第一刀自洽 + 非装饰**：命门题打回仍落 STIGMA + 案卷 midzhi 事实（可观察，D5-6）；正式血债／离心 → M12；真中旨闸 defer。
5. **gaming 扫洞**：① 中旨绕四层 → 六科照封 + MIDZHI 全局污名；正式逐派离心／频度反噬 → M12（#657 §C.8）；② 话术诱导降敏感度 → 结构化查表（0011-4 D4-5）；③ 召对侦察套利 → dry_run 物理只读护栏（D5-3）；④ LLM 把打回写成办成 → D5-11 硬约束。
6. **build-upon 0004/0008/0009 + 码集二分单源**（D5-10）。
7. **召对 dry_run 单一真源 + 等价性强制点 + mode-aware**（D5-3）。
8. **blocked_layer 全算取真墙（非短路误报）+ 命门必由六科挡不变式**（D5-4）。
9. **执行层不扩 status enum + 不另起平行密令核议**（D5-7）。
10. **硬序铁律**（D5-9）。
11. **resolve↔simulator 硬约束、LLM 禁重算 + 打回→HITL 闭环 + P4 禁令扩**（D5-11）。

## 依赖 substrate（本 ADR 读它们、不在本 ADR 定稿）

- **矩阵**（0011-3）：四层读派系立场判离心方向 / 封驳倾向 / 执行折扣。
- **血债 + 失称度 + 码集二分**（0011-2 D2-4/D2-5/D2-7）：per_layer_resistance 血债 floor 臂 + 六科读失称度 + 破局走程序坐实 + 依律集/STIGMA 二分真源。
- **ceiling + 命门合法性 floor（含华夷 floor 外压调制）**（0011-4 D4-3/D4-4）：六科层读 ceiling 判命门、floor 臂 + 议和外压击穿点。
- **seed-guilt + identity**（0011-4 B / dig-6）：破局「真有可坐实的罪」（重罪全阉党）；identity 仅经 kinship 旁及执行层反咬（**不入阻力**）。
- **中旨 provisional 契约**（0011-2 D2-8）：第二刀消费点。

## defer 清单（明确不在第一刀 / 不在本 ADR）

- **中旨闸整套**（provisional 生命周期 / MIDZHI 真闸量级）= 第二刀（最低契约在 0011-2 D2-8）。旧「edict_overdraw 中旨螺旋」当回合／第二刀施工义 later-wins → #657 contract **§C.8** → **M12**。
- **执行层四态细分 + 密令结构化裁判**（与现存密令核议合一）= 第二刀。
- **召对 location 闸**（FF-4，决定8）= 单独切片（依赖 0009 location）。〔**取代注（2026-07-08 M12 闸回标）**：本行系写作时快照——FF-4 已由 **ADR 0096**（召对 travel-gating＋候见制）兑现，不再单独立片；母 ADR line125/133 取代注同源。〕
- **actor 取证引擎 + 认同度叛变（破局回路后半截）= #89 / 单独切片**（D5-5 诚实标）。

---

## 后果

### 北极星验证（喂得出破局曲线吗）

硬推罗织抄崔呈秀（阉党核心、seed 重罪）→ resolve 全算三层、`blocked_layer = 六科封驳`（ceiling + 命门 floor 顶满）+ 血债 +69（罗织 cw=1、0011-2 D2-4）→ 邸报「六科封还、清议汹汹」+ 二次决策点（D5-11）。聪明解：先 actor 取证坐实其真重罪 → `reason_code = 贪墨坐实（依律集）` → 翻轴（0011-4 D4-4a）→ 东林反对格停 fire（D5-5 桥）→ resolve 顺颁 + 血债 +7。**resolve 把「血债 ≈10 倍、ceiling ≈2 倍」确定性算出、LLM 只叙事（D5-11 硬约束禁重算）**——破局从「撞运气」变「稳定可复现」。宗室如福王（无重罪）= 更难的破局靶，正撑「清完阉党即缺正当靶」的悲剧弧。这套 resolve 喂得出。

### 落地顺序（硬序铁律）

substrate（0011-2/3/4）**全先落** → `resolve_core` 确定性骨架（第一刀，只颁布关 顺颁 / 打回 + 命门题中旨落 STIGMA／案卷 midzhi 事实；正式血债／离心 → M12）→ 替换 `estimate_resistance`（含 skills.json 三处）→ 召对 dry-run 物理只读 → season_simulator 加吃判决 + HITL 接线 + P4 禁令（D5-11）→ 邸报复盘。第二刀（中旨闸／执行层四态／location 闸／密令结构化）后接。〔**取代注（2026-07-08 M12 闸回标）**：第二刀括注系写作时快照——其中「location 闸」已由 **ADR 0096** 兑现、不再后接；其余项仍属第二刀。defer 清单取代注同源。〕

### 调参 / playtest

per_layer_resistance **逐层阈值** + dynamic_term 权重 + 外压 floor 调制曲线 = **首版**，随 substrate α/β playtest 调参（镜像 spike G1-G22）。`MIDZHI_PENALTY` 真闸量级 = **第二刀**调参（不与第一刀公式阈值并列）。**blocked_layer 全算 / dry_run 单一真源 + 物理护栏 / 命门必由六科挡 / 硬序 / D5-11 硬约束 = 设计与不变式、不是调参旋钮。**

### 评审

本 ADR 是设计文档，按 CLAUDE.md 铁律产出后必跑完整评审闭环（本地 cmr 收敛 + 线上三 bot 收敛）。**草稿后经内部对抗预检**（15-agent：6 fold 保真核 + 8 承重 claim 红队 + 合成，2026-06-15）——修 **10 P1**（resolve↔simulator 裁判分界〔D5-11〕/ dry_run 只读 vs 0008 atomic 错配〔拆 resolve_core+apply_resolve〕/ resolve 落 directives 时序 vs add_directive 即时写 / 议和外压臂被 max() 短路〔华夷 floor 吃外压调制，回标 0011-4 D4-3〕/ dynamic_term 漏外压 substrate + 层错位 / first-over-threshold 误报 blocked_layer〔改全算 argmax〕/ 第一刀中旨装饰 + D5-6↔D5-8 矛盾〔命门题中旨落 STIGMA+血债〕/ 福王 seed 无重罪却当 +7 范例〔改崔呈秀〕/ 倍数绑错〔血债≈10 倍、ceiling≈2 倍〕/ 依律集 vs CRIME_BY_CODE 脱钩〔码集二分单源 0011-2 D2-5〕）+ **14 P2**（执行层 vs 密令核议边界 / 打回→HITL 接线 / 外压臂补「代价够明白」/ dry_run mode-aware / 行政旨中旨可观察 / estimate_resistance 替换 skills.json / 召对谏言覆盖母 ADR 决定4 / 单一真源等价性强制点 / dry_run 内存态 / identity 不入阻力 / MIDZHI 切片归属 / per-layer 阈值 / P4 禁令枚举扩 / 等）+ **7 P3**（estimate_resistance 行号 tools.py:136 / pre_settle 锚点〔0011-2〕/ 依律处置非矩阵轴桥 / dynamic_term 首次定义 / STIGMA 码归属 / actor 取证+认同度两环 #89 诚实标 / 等）。多数 P1 跨 0011-2/0011-4/0011-5 同步改（已同改）。**resolve 纯函数范式 + 中旨 fold + 三臂指针 + 议和非翻轴定性框架 + 破局机理方向 = 5 条承重 claim 攻不破**。**本轮 cmr 复裁重点**：① 拆 resolve_core/apply_resolve 物理只读护栏是否真堵死 dry_run 副作用；② 华夷 floor 外压调制（0011-4 D4-3）+ 经六科传导链是否自洽；③ blocked_layer 全算 + 命门必由六科挡不变式；④ D5-11 resolve↔simulator 硬约束 + season_simulator 改动面是否覆盖诏书核销 / 密令核议 / HITL 三处。实现属编码活、交隔壁 session。

### 出处

由 design-dig `dig-8` fold：5-agent（ground 颁旨链 + 四层史实 + 3 路设计 + 合成）。用户 2026-06-14 设计 session 拍板 5 问（① ceiling 跟矩阵一起拍 + 出路恒可达先锁 / ② 第一刀只颁布 顺颁/打回、执行层 defer / ③ 中旨第一刀给但映射必碰壁 / ④ 逐层短路出 blocked_layer〔本轮改全算 argmax〕/ ⑤ kinship 改动血债 sub-ADR 带、四层另起 sub-ADR）→「四层票拟定稿」。承母 ADR 决定4 / 决定5、读全 substrate（0011-2/3/4）。**草稿后经内部对抗预检 15-agent（2026-06-15）修 10 P1 + 14 P2 + 7 P3、跨 0011-2/0011-4 同步，再进正式 cmr。**
