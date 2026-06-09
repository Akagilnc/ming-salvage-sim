# DELTA_SCHEMA.md — 我产 delta JSON 的格式契约

**真相源**：`ming_sim/simulation.py`（`EMPTY_EXTRACTION` / `MODULE_FIELDS` / `_clean_*`）+ `ming_sim/issues.py`（落库守门）+ `ming_sim/constants.py`（白名单）。

用途：每回合月末，我以裁判身份产一份 delta JSON，由 driver 喂 `apply_score_extraction(db, state, extracted)` 落库。**没在白名单里的字段会被沉默裁掉、值不合法的整条丢弃。** 必须查表，不要凭"我以为"。

## 顶层 23 字段（容器类型固定）

```jsonc
{
  // ── internal 模块（钱粮 / 民心 / 派系 / 阶级 / 地区 / 财政制度）──
  "metric_delta":     {},  // dict[国势名 -> int]
  "economy_moves":    [],  // list[一次性收支]
  "faction_delta":    {},  // dict[派系名 -> int]
  "class_delta":      {},  // dict[阶级名 或 阶级@省id -> int]
  "region_delta":     {},  // dict[region_id -> {字段:数值}]
  "fiscal_changes":   [],  // 改某项月度收支额度
  "fiscal_creates":   [],  // 新立月度收支（新税/新俸）
  "fiscal_removes":   [],  // 裁撤月度收支（永久取消）

  // ── military_external 模块 ──
  "army_delta":       {},  // dict[army_id -> {字段:数值}]
  "new_armies":       [],  // 建军
  "power_updates":    {},  // dict[power_id -> {字段}]
  "world_advance":    {},  // dict[势力名 -> "stance/态度文 ≤40字"]

  // ── issues 模块 ──
  "issue_advances":   [],  // 推进既有 issue
  "new_issues":       [],  // 新立 issue（origin_kind 必填）
  "cancels":          [],  // 撤销 issue
  "close_issues":     [],  // 结案 issue

  // ── personnel_secret 模块 ──
  "office_changes":             [],  // 人事除目（任官 / 调任）
  "appointments":               [],  // 后宫册封
  "character_status_changes":   [],  // 人物状态（罢黜/下狱/流放/致仕/死）
  "character_power_changes":    [],  // 人物易主
  "secret_order_updates":       [],  // 密令副作用
  "secret_order_closes":        [],  // 密令核议结案
  "emperor_fate":               null // "abdicate" | "suicide" | null
}
```

中英文 key 都吃（`钱粮收支`==`economy_moves`），别名表见 `simulation.py:TOP_LEVEL_ALIASES`。**未列出的 key 会被裁掉。** item 字段同样有中英双语别名表（`ITEM_FIELD_ALIASES`）。

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
| `target_kind` | 可选 `army` | 配合 target_id 用 |
| `target_id` | 可选 | 当 purpose=补饷 时定向 |

> ⚠️ **常踩坑**：建筑日常产出 / 固定月度收支 **不要写**（已由程序 `apply_fixed_period_flows` 落账）。这里只写本回合"诏书/事件导致的一次性真金白银收支"，每笔三要素「源→目标，金额」点死。
> 「太仓岁亏三十万」是困境描述，不是本月一笔收支，**别照写成 economy_moves**。

### `faction_delta` — 派系满意度变化
- 合法派系（7 个，写一个就够，不写就不动）：`阉党` `东林` `皇党` `军队` `宗室` `中立` `西学`
- 值：int 增量，作用于 `satisfaction`。改 `leverage` 用 `power_updates`/正文叙事，不在此处。

### `class_delta` — 阶级满意度变化
- 合法 key：`<class_name>` 或 `<class_name>@<region_id>`（如 `农民@shaanxi`）
- `class_name` 在 `content/classes.json` 里：农民 / 士绅 / 官僚 / 军户 / 商人 / 匠户 / 宗藩
- 值：int 增量

### `region_delta` — 地区变化
- key：region_id（如 `beizhili` / `shaanxi` / `liaodong` 等，看 `content/regions.json` id 列）
- value：dict，字段（来自 `REGION_*` 常量）：
  - score（0-100，int）：`public_support` `unrest` `gentry_resistance` `military_pressure`
  - quantity（int）：`population` `registered_land` `hidden_land` `tax_per_turn` `grain_security`
  - text：`natural_disaster` `human_disaster` `status` `controlled_by`
- 中文别名都吃：`动乱`→unrest、`士绅`→gentry_resistance、`粮食`→grain_security 等

### `fiscal_changes` — 改月度收支额度
| 字段 | 约束 |
|---|---|
| `key` | **必须**非空（key 在 `fiscal_config` 表里，如 `liao_xiang_rate`）|
| `delta` | **必须** int 且 **非零** |
| `reason` | ≤120 字 |

### `fiscal_creates` — 新立月度收支
| 字段 | 约束 |
|---|---|
| `key` | **必须**非空 |
| `account` | **必须** `国库` 或 `内库` |
| `direction` | **必须** `income` 或 `expense`（吃中文别名 `收`/`支`/`收入`/`支出`/`进账`/`出账`）|
| `init_value` | int，`max(0, ·)` |
| `display` | 缺省=key 去 `_base` 后缀 |
| `reason` | ≤120 字 |

> 用于「新设关税岁额折月二十万」「新立宗藩裁革月省禄米三十万」这类**常设新增**。一次性进账（抄没/缴获）不属此类，归 `economy_moves`。

### `fiscal_removes` — 裁撤月度收支
- `key` 非空 + `reason` ≤120
- 整项永久取消才属此类；只降税率/削禄米不算（用 `fiscal_changes`）。

### `army_delta` — 军队变化
- key：army_id（看 `content/armies.json`，如 `guanning` `dadong` 等）
- value 字段（来自 `ARMY_*` 常量）：
  - score（0-100）：`supply` `morale` `training` `equipment` `arrears` `mobility` `loyalty`
  - quantity：`manpower` `maintenance_per_turn`
  - text：`station` `commander` `controller` `troop_type` `status` `owner_power`
- 中文别名都吃

### `new_armies` — 建军
⚠️ **`id` 必填**（英文 army_id，如 `tianxiong`）。缺 id 整条被跳过并印 `[WARN] new_armies 缺 id → 跳过`。〔崇祯二年八月实测，turn 11〕
全字段：`id`（必填）`name` `owner_power` `station` `theater` `commander` `controller` `troop_type` `manpower` `morale` `training` `loyalty` `equipment` `supply` `mobility` `maintenance_per_turn` `status`…（参考 `ARMY_FIELD_ALIASES`）

### `power_updates` — 外部势力变化
- key：power_id（`houjin` / `mongol` / `korea` / `dutch` / `japan` / `liukou` / `tibet` / `annam` / `ming`）
- value 字段（`POWER_*` 常量）：
  - score：`leverage` `satisfaction` `military_strength` `cohesion` `supply`
  - text：`leader` `stance` `agenda` `status` `last_action`

### `world_advance` — 四方动向
- key：势力名（`后金` `蒙古` `朝鲜` `流寇` 等）
- value：stance/态度文，**≤40 字**，紧凑一句话；丢"无新动"。

### `issue_advances` — 推进既有 issue
| 字段 | 约束 |
|---|---|
| `issue_id` | int，必须是 `issues` 表里已有的 id |
| `delta_bar` | int 进度增量（正=推向 bar=100，负=回退） |
| `narrative` | ≤120 字，本月这条 issue 的实况 |
| `stage_text` | 可选，覆盖 issue 阶段文案 |
| `inertia_delta` | 可选 int |
| `origin_kind` | 可选 |

### `new_issues` — 新立 issue ⚠️ **最容易踩的字段**
**两种来源（必选其一）**：
1. `origin_kind: "decree"` — 玩家诏书强推的新政/工程/改革
2. `origin_kind: "event_pool"` + `id: "<候选事件 id>"` — 触发预设候选事件

**其它来源一律拒**（这是我第一次踩的坑：`origin_kind=''` 直接被丢）。

`origin_kind=decree` 时字段：
| 字段 | 约束 |
|---|---|
| `origin_kind` | **必须** `"decree"` |
| `kind` | 默认 `initiative`；若用 `situation` 则按系统危机走 |
| `title` | ≤60 字 |
| `bar_value` | int，默认 25 |
| `expected_months` | int |
| `bar_good_meaning` / `bar_bad_meaning` | 文案 |
| `ongoing_effects` / `effect_on_resolve` / `effect_on_fail` | dict，月度持续/结案/失败效果 |
| `cancellable` | "decree" / "never" / "by_progress" |
| `narrative` | 立项叙事 |

⚠️ **kind 白名单**：落库时 `kind` 不在 `(situation, initiative)` 内会被拒。**第二次踩的坑**：`kind="reform"` 被拒（应改 `initiative`）。

⚠️ **数量上限**：active `kind=initiative` 的 issue **总数不超过 10**，超过新立直接拒（"已有十事在办，朝廷分身乏术"）。

### `cancels` — 撤销 issue
- `issue_id` int + `reason` 文本
- 仅 `cancellable in (decree, by_progress)` 的 issue 可撤；预设 `never` 撤不动。

### `close_issues` — 结案 issue
- `issue_id` int + `result` 文本（描述 done/failed 的实况）
- 一般由 issue bar=100/0 自动了结；这里用于强行结案。

### `office_changes` — 人事除目
- 必填：`name`（必须在 `characters` 名册）+ `new_office`
- 可选：`new_office_type`（内阁/六部/督抚/边将/锦衣卫/司礼监…）、`faction`
- ⚠️ 用于**任命/调任/升迁/改授**；罢黜/下狱用 `character_status_changes`。

### `character_status_changes` — 人物状态
- 必填：`name` + `status`
- ⚠️ **status 白名单**：`active` / `offstage` / `dismissed` / `imprisoned` / `exiled` / `retired` / `dead`
- 不在表内会抛 `ValueError("character status 非法")`
- 同一人本月 active→imprisoned 等迁移要符合状态机（不能死人复活）

### `character_power_changes` — 人物易主
- 必填：`name` + `new_power`（power_id）
- 用于"降清""归附""投流寇"等

### `appointments` — 后宫册封
- 字段：`name`（候选秀女或宫人）+ `office`（如"贵人""嫔""妃""贵妃"）

### `secret_order_updates` / `secret_order_closes`
- updates：`order_id` int + `sim_note`（本月推进实况）+ 可选 `impact`
- closes：`order_id` + `result`（核议结论）+ `approved` bool（done=approved true）

### `emperor_fate`
- 顶层标量，不是 list/dict
- 三选一：`"abdicate"` / `"suicide"` / `null`

---

## 模块归属（仅参考，driver 现在合并产出，不分模块）

| 模块 | 顶层字段 |
|---|---|
| `internal` | `metric_delta` `economy_moves` `faction_delta` `class_delta` `region_delta` `fiscal_changes` `fiscal_creates` `fiscal_removes` |
| `military_external` | `army_delta` `new_armies` `power_updates` `world_advance` |
| `issues` | `issue_advances` `new_issues` `cancels` `close_issues` |
| `personnel_secret` | `office_changes` `appointments` `character_status_changes` `character_power_changes` `secret_order_updates` `secret_order_closes` `emperor_fate` |

---

## 落库守门 - 已经踩过的坑（list of pain）

| 字段 | 我犯过的错 | 真相 |
|---|---|---|
| `new_issues[].origin_kind` | 不填 | **必填** `decree` 或 `event_pool` |
| `new_issues[].kind` | 写 `reform` | 白名单 `situation` / `initiative`；改革/试点都用 `initiative` |
| `new_issues[].title` | — | ≤60 字 |
| `new_issues` 总数 | — | active `initiative` ≤10 |
| `close_issues[].reason` | 填了 `result` 没填 `reason` | close_issues 要 **`reason`** 字段（不是 result），空则整条被跳过。注：若同时用 `issue_advances` 把 bar 推满（≥100），issue 会**自动 resolved**，不依赖 close_issues |
| `power_updates` 字段 | 写 `{"stance":...}` 或 `{"satisfaction":...}` | **实际守门只收三个字段：`威望`(leverage) / `实力`(military_strength) / `经济`(economy)。** 连 `satisfaction` / `cohesion` / `supply` / `stance` / `leader` / `agenda` 全被拒，印 `[WARN] power_updates 只允许 威望/实力/经济，'X' → 跳过`。改外势态度文用 `world_advance`（≤40字）；改归附倾向只能动 leverage/military_strength/economy。本文档上方 `power_updates` 段（列了 satisfaction/cohesion/stance/leader…）是 doc 与守门的漂移，**以本坑为准**。〔崇祯二年五、六月结算实测，turn 8/9〕|

每踩一坑就补到这张表里，下次别再来一遍。

---

## 真相源对照（代码升级后跟原仓库 rebase 时务必跑一遍 diff）

| 文件 | 看什么 |
|---|---|
| `ming_sim/simulation.py` | `EMPTY_EXTRACTION` / `TOP_LEVEL_ALIASES` / `ITEM_FIELD_ALIASES` / `MODULE_FIELDS` / `_clean_*` |
| `ming_sim/issues.py` | `apply_score_extraction()` 里各 issue/new_issue 校验、`origin_kind`/`kind` 白名单 |
| `ming_sim/db.py` | `set_character_status()` 状态白名单、各 `apply_*_deltas` 字段守门 |
| `ming_sim/constants.py` | `REGION_*` / `ARMY_*` / `POWER_*` / `BUILDING_*` / `ECONOMY_ACCOUNTS` / `SCORE_METRICS` |
