# Delta Schema

**真相源**：`ming_sim/simulation.py`（`EMPTY_EXTRACTION`、`ITEM_FIELD_ALIASES`、`_canonical_item_fields`、`read_beyond_intent_raw`）+ `ming_sim/issues.py`（落库守门）+ `ming_sim/constants.py`（白名单）。

用途：过月逐段声明由 `declaration_dispatch` 交 `apply_score_extraction` 落库；下文记录效果字段约束。**分层校验（ADR 0015 r4 终态）**：顶层非 dict（连 section 都拆不出）才整份重产；未知顶层 key＝可拆 section → 按段拒收留痕，其余 section 照落，**不整份退**；已知 section 内值/项不合法逐项拒收留痕。必须查表，不要凭"我以为"。
产出前自查顶层字段集（与 `EMPTY_EXTRACTION` 对齐）：未知 key 不再响亮中止，但会被整段拒收留痕、白产一段——别指望守门人帮忙猜拼写。

## ADR 0055 效果分工线与 origin 槽

- **结构化载荷类**（任免 / 定额拨帑 / 授权等 payload 可机械导出且经外廷受判者）：判决后自案卷载荷物化；同类效果不得由声明段平行重复物化；apply 端按 origin 回指 dedup（`origin_ref: dossier:<id>` 或生产槽 `dossier_id`）。案卷须已具备可物化资格（已颁 / 执行中 / 强颁，或豁免直落）；打回、留中、未达资格不得改世界。
- **叙事性政令**（新政 / 工程 / 改革等无结构化 payload 者）：效果经月链声明 / 世界段转译涌现；顺颁当月进正文，批红强颁自次月进（T+1）；打回受硬约束零效果。两路效果记录均带 origin 回指。
- **origin 槽**：各 section 的 `origin_ref` / `dossier_id` / `origin_kind` 即回指锚（见下表各字段）；`盘面自发` 仅用于非旨意自然演化。dedup 只辖结构化类，不得误杀叙事政令的合法声明。

## 顶层字段（容器类型固定；与 EMPTY_EXTRACTION 对齐）

```jsonc
{
  // ── 钱粮 / 民心 / 派系 / 阶级 / 地区 / 财政制度 ──
  "metric_delta":     {},  // dict[国势名 -> int]
  "economy_moves":    [],  // list[一次性收支]
  "faction_delta":    {},  // dict[派系名 -> int]
  "class_delta":      {},  // dict[阶级名 或 阶级@省id -> {satisfaction/leverage: int}]
  "population_transfers": [],  // list[人口守恒转移记录]（#649/0087：单记录双写，源阶级减 N、目标阶级增 N）
  "surcharge_decrees": [],  // list[加派旨]（#650/0089 明渠：逐省累积账当回合落库，月额万两、负=停征/蠲免）
  "region_delta":     {},  // dict[region_id -> {字段:数值}]
  "fiscal_changes":   [],  // 改某项月度收支额度
  "fiscal_creates":   [],  // 新立月度收支（新税/新俸）
  "fiscal_removes":   [],  // 裁撤月度收支（永久取消）

  // ── 军务 / 外部势力 ──
  "army_delta":       {},  // dict[army_id -> {字段:数值}]
  "new_armies":       [],  // 建军
  "power_updates":    {},  // dict[power_id -> {字段}]
  "bandit_absorptions": [], // #652 流民投贼吸收请求（吃池顶）
  "world_advance":    {},  // dict[势力名 -> "stance/态度文 ≤40字"]

  // ── 局势 / 案卷 ──
  "issue_advances":   [],  // 推进既有 issue
  "new_issues":       [],  // 新立 issue（origin_kind 必填）
  "事件结局":          {},  // dict[event_id -> 闭合结局标签]
  "cancels":          [],  // 撤销 issue
  "close_issues":     [],  // 结案 issue
  "dossier_executions": [], // 执行中案卷的明确结局（S1）
  "dossier_participants": [], // 月末新出场的案卷参与人（S2，append-only）
  "secret_dossier_participants": [], // #1252 密令案卷参与人追加（密令私字段，与公共参与人分立）
  "authority_changes": [], // 授予/收回持有型特权（ADR 0071 / #611）
  // #1900：dossier_reconciliations 已退役（沿途损耗归引擎），不再列入本形状。
  "faction_denunciations": [], // 政敌检举条目（#627 / ADR 0077 ID-12）

  // ── 人物 / 密令 ──
  "人物变更":                    [],  // ADR 0009 单一人物入口：每项必带「动作」
  "secret_order_updates":       [],  // 密令副作用
  "covert_exec_selections":     [],  // #1504 密令带内选态
  "dossier_progress_reports":   [],  // 长差密令逐月密奏（#566 / ADR 0058）
  "emperor_fate":               null, // null 不终局；abdicate/suicide 保留原状态号；其它非空声明（被废、暴毙等）同样终局

  // ── 关系边（#633 / ADR 0082 结算口）──
  "relation_edge_events": [],  // 大臣互动边事件；每项 {施动者, 受动者(单名或名单), 类目, 语境, 来源引用}
}
```

C0 效果字段须用 `EMPTY_EXTRACTION` 中的键；条目字段别名由 `ITEM_FIELD_ALIASES` 规范化。未知字段按段拒收留痕，其余照落。

---

## 各字段约束详表（落库守门会拒的硬规则）

### `metric_delta` — 国势变化
- 合法 key：`国库` `内库` `民心` `皇威`
- 值：int 增量（民心/皇威范围 0-100，国库/内库 ≥0；引擎会 `clamp()`）

### `economy_moves` — 一次性钱粮收支
每条必须：
| 字段 | 约束 | 说明 |
|---|---|---|
| `account` | **必须** `国库` 或 `内库` | 不在表内整条丢 |
| `delta` | **必须** int 且 **非零** | 0 直接丢 |
| `category` | ≤40 字 | 自由文本 |
| `reason` | ≤80 字 | 自由文本 |
| `purpose` | 可选 `补饷` / `其它` | 补饷会跟 army arrears 联动 |
| `target_kind` | `purpose=补饷` 时必填 `army` | 配合 target_id 用 |
| `target_id` | `purpose=补饷` 时必填合法 army_id | 缺失或不存在则整条拒收不扣账 |
| `transfer_to` | 可选，另一钱库账户 | 国库↔内库互拨只写来源负数这一项；引擎按来源实扣数在目标入同额，不再另写正数项。独立收入不填 |
| `origin_ref` | **必填** `dossier:<id>` 或 `盘面自发` | 案卷引用必须存在且已颁；自然演化必须写精确哨兵。缺失、伪前缀及未授权案卷逐项拒收 |
| `beyond_intent` | 可选 bool/0/1（别名 `旨外` / `旨外标记` / `旨外恶果`） | #622 旨外恶果/受益标记；与 `origin_ref` 同效果行落库。到期复核机械读此标记落 `transformed`（0072）。缺省=否 |

> ⚠️ **常踩坑**：建筑日常产出 / 固定月度收支 **不要写**（已由程序 `apply_fixed_period_flows` 落账）。这里只写本回合"诏书/事件导致的一次性真金白银收支"，每笔三要素「源→目标，金额」点死。
> 「太仓岁亏三十万」是困境描述，不是本月一笔收支，**别照写成 economy_moves**。

### `faction_delta` — 派系满意度变化
- 合法派系（7 个，写一个就够，不写就不动）：`阉党` `东林` `皇党` `军队` `宗室` `中立` `西学`
- 值：int 增量，作用于 `satisfaction`。改 `leverage` 用 `power_updates`/正文叙事，不在此处。

### `class_delta` — 阶级满意度变化
- 合法 key：`<class_name>` 或 `<class_name>@<region_id>`（如 `农民@shaanxi`；含第八阶级 `流民@<region_id>`，#648）
- `class_name` 在 `content/classes.json` 里：农民 / 士绅 / 官僚 / 军户 / 商人 / 匠户 / 宗藩 / 流民
- value：dict，只收 `satisfaction` / `leverage` 两个字段；字段值为 int 增量。**无 population 更新面**：写 `population` 键 → 该 item 以 `invalid_enum` **整项拒收**（#649 §1.4 升格，非静默忽略）；一切人口变化只走下方 `population_transfers` 守恒转移原语
- 非 dict 的阶级 item（包括扁平 int）不合法，按 item 逐项以 `invalid_enum` 拒收留痕；同一 `class_delta` 中其它合法 item 仍照常落库

### `population_transfers` — 人口守恒转移（#649/ADR 0087）

canonical 段形＝list，每条记录**同时表达两条腿**：applier 读一条合法记录后在同一事务内源阶级减 N、目标阶级增 N（单记录双写；LLM 禁提交双腿 delta，系统不建配平器）。中英别名：`人口转移` / `流民转移`。

| 字段 | 约束 |
|---|---|
| `source` | `<class_name>@<region_id>` 省级行（如 `农民@shaanxi`）；全国行（region_id 空）不合法 |
| `target` | 同上；须与 source **同 region_id**（跨省在途归 #475 预留，本契约不做） |
| `amount` | 拟转正整数（严格 int，拒数字串/float/bool）；单位为「人」，与 armies `manpower` 同刻度 |
| `reason` | 枚举×方向矩阵：`加派`/`摊派`/`灾害`＝农民→流民；`兵灾`＝农民→流民、军户→流民；`逃亡`＝军户→流民；`回流`＝流民→农民（**仅引擎 recovery 单核可写**，声明段申报整项拒收，#652）。方向出阵即拒 |
| `origin_ref` | **必填** `dossier:<id>`（须存在且已颁）或精确哨兵 `盘面自发`——来源追溯契约与 `reason` 机制枚举两槽并存、职责互斥 |

- applier 将拟转数额封顶为当时 source 省级行实有余额，并在同一事务中 source 减、target 增同一实数额；已应用记录的 `amount` 是实际转移量。
- 逐项拒收面（坏项留痕、同批合法项照落，ADR 0015/0008）：方向出阵、reason 枚举外、amount 非严格 int/≤0、region 未知或两侧不同省、source/target 触全国行、origin_ref 缺失/伪前缀/未颁案卷、白名单外字段（任何形式的绝对值覆写均不合法——人口只经本原语守恒变动，禁凭空造人/单侧写）。
- 灾害／兵灾入口（#662/S14）：转译依据盘面事实判断具体量级；无事实支撑不得申报。代码校验物理不变量并守恒记账，不自动触发人口迁移；各原因合流同一 classes 行池账。
- 条目字段规范化以 `ITEM_FIELD_ALIASES` 为准；人口余额与单位由月链材料供给，不将引擎数表当玩家呈现。

### `bandit_absorptions` — 流民投贼吸收（#652/ADR 0087）

canonical 段形＝list；中英别名：`流民投贼` / `投贼吸收`。LLM 软判产 typed 请求，单一原子 applier：`actual=min(requested, 该省流民余额)` → 扣池（单侧出池，无农民对端）→ 仅 `actual>0` 允许该股 `military_strength` 正增（δ=`actual//BANDIT_ABSORPTION_PERSONS_PER_STRENGTH`，再 0–100 clamp）。

| 字段 | 约束 |
|---|---|
| `region_id` | 须有 `流民@region_id` 省级行 |
| `power_id` | 流寇股：`bandits` 或 `bandit_*`，须已入库 |
| `requested_count` | 正整数（严格 int）；单位为「人」 |
| `origin_ref` | 必填 `dossier:<id>` 或 `盘面自发` |

- 流寇 `power_updates.military_strength` **正增量**整项拒收（必须走本段）；负增量（剿股）仍走 `power_updates`。
- 人口单位口径为「人」。
- item 字段中英别名：`地区编号`→region_id、`势力编号`→power_id、`请求口数`/`请求人数`/`拟吸口数`→requested_count。

### `surcharge_decrees` — 下旨加派（#650/ADR 0089 明渠）

canonical 段形＝list，每项落一道加派旨：逐省累积账当回合落库（P1），钱面由饷率通道折入三饷应征（真征收），民面由结算按账机械驱动农民→流民入池（确定性口径、clamp，非 LLM 报数——**禁再为同一道加派另报 `population_transfers`**，环后半段只认账不认来源）。

| 字段 | 约束 |
|---|---|
| `region_id` | 明省且已有 settle 财政基座，并同时物化 `农民@region_id`、`流民@region_id` 两条省级人口行（未知省/非明省/无基座或人口池逐项拒收留痕） |
| `monthly_amount` | **必填**数值（万两/月增量）：正＝加派累加；负＝停征/蠲免减账；账面钳 ≥0；显式 0＝静默无操作不落；缺失＝`invalid_enum` 逐项拒收 |
| `reason` | 可选 ≤120 字 |
| `origin_ref` | **必填且仅接受**具有效果资格的 `dossier:<正整数>`（案卷须存在且已颁或强颁）；不得使用 `盘面自发` |

- item 字段中英别名：`地区编号`→region_id、`月增额`/`月额`→monthly_amount。
- 同批 `(origin_ref, region_id)` 仅首项成功，重复项逐项拒收。
- 须已物化人口池（`农民@region_id` / `流民@region_id`）且走 substrate hub 财政的档可写入、消费。历史正账若农民/流民两行皆无则安全出列，仅缺一行视为损坏并 fail-loud。
- 无旨不入账：段空＝累积账不动；停征后入池止（出口回流归 S5 #652）。

### `region_delta` — 地区变化
- 每个 region value 必填 `origin_ref`（已颁 `dossier:<id>` 或 `盘面自发`）；该字段不作为地区属性处理。
- key：region_id（如 `beizhili` / `shaanxi` / `liaodong` 等，看 `content/regions.json` id 列）
- value：dict，字段（来自 `REGION_*` 常量）：
  - score（0-100，int）：`public_support` `unrest` `gentry_resistance` `military_pressure`
  - quantity（int）：`population` `registered_land` `hidden_land` `tax_per_turn` `grain_security`；**单位契约（ADR 0088/#648）**：`population` 以「人」计，与 armies `manpower` 同刻度
