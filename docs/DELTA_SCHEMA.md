# DELTA_SCHEMA.md — 我产 delta JSON 的格式契约

**真相源**：`ming_sim/simulation.py`（`EMPTY_EXTRACTION` / `MODULE_FIELDS` / `_clean_*`）+ `ming_sim/issues.py`（落库守门）+ `ming_sim/constants.py`（白名单）。

用途：每回合月末，我以裁判身份产一份 delta JSON，由 driver 喂 `apply_score_extraction(db, state, extracted)` 落库。**未知顶层字段会响亮中止；已知 section 内值不合法的条目逐项拒收留痕。** 必须查表，不要凭"我以为"。
v0.8.0.0 起（ADR 0008 PR1）：**shape 级垃圾**（非 dict、损坏 JSON、未知顶层字段）过不了 `validate_delta_shape`，结算会响亮中止（SettlementAbort + 诊断错误包），不再静默吞——产出前自查顶层字段集（与 `EMPTY_EXTRACTION` 对齐），别指望守门人帮忙兜。

## ADR 0055 效果分工线与 origin 槽

- **结构化载荷类**（任免 / 定额拨帑 / 授权等 payload 可机械导出且经外廷受判者）：判决后自案卷载荷物化；同类效果 extractor **禁抽**；apply 端按 origin 回指 dedup（`origin_ref: dossier:<id>` 或生产槽 `dossier_id`）。案卷须已具备可物化资格（已颁 / 执行中 / 强颁，或豁免直落）；打回、留中、未达资格不得改世界。
- **叙事性政令**（新政 / 工程 / 改革等无结构化 payload 者）：效果经推演-extractor 链涌现；顺颁当月进推演正文，批红强颁自次月进（T+1）；打回受硬约束零效果。两路效果记录均带 origin 回指。
- **origin 槽**：各 section 的 `origin_ref` / `dossier_id` / `origin_kind` 即回指锚（见下表各字段）；`盘面自发` 仅用于非旨意自然演化。dedup 只辖结构化类，不得误杀叙事政令的合法抽取。

## 顶层字段（容器类型固定；与 EMPTY_EXTRACTION 对齐）

```jsonc
{
  // ── internal 模块（钱粮 / 民心 / 派系 / 阶级 / 地区 / 财政制度）──
  "metric_delta":     {},  // dict[国势名 -> int]
  "economy_moves":    [],  // list[一次性收支]
  "faction_delta":    {},  // dict[派系名 -> int]
  "class_delta":      {},  // dict[阶级名 或 阶级@省id -> {satisfaction/leverage: int}]
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
  "事件结局":          {},  // dict[event_id -> 闭合结局标签]
  "cancels":          [],  // 撤销 issue
  "close_issues":     [],  // 结案 issue
  "dossier_executions": [], // 执行中案卷的明确结局（S1）
  "dossier_participants": [], // 月末新出场的案卷参与人（S2，append-only）
  "secret_dossier_participants": [], // #1252 密令案卷参与人追加（personnel_secret 私字段）
  "authority_changes": [], // 授予/收回持有型特权（ADR 0071 / #611）
  "dossier_reconciliations": [], // 在途拨帑对账提案（#567 / ADR 0054）
  "faction_denunciations": [], // 政敌检举条目（#627 / ADR 0077 ID-12）

  // ── personnel_secret 模块 ──
  "人物变更":                    [],  // ADR 0009 单一人物入口：每项必带「动作」
  "secret_order_updates":       [],  // 密令副作用
  "secret_order_closes":        [],  // 密令核议结案
  "dossier_progress_reports":   [],  // 长差密令逐月密奏（#566 / ADR 0058）
  "emperor_fate":               null // "abdicate" | "suicide" | null
}
```

中英文 key 都吃（`钱粮收支`==`economy_moves`），别名表见 `simulation.py:TOP_LEVEL_ALIASES`。**未知顶层 key 按本文开头的唯一规则，经 `validate_delta_shape` 响亮中止。** item 字段同样有中英双语别名表（`ITEM_FIELD_ALIASES`）。

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
| `origin_ref` | **必填** `dossier:<id>` 或 `盘面自发` | 案卷引用必须存在且已颁；自然演化必须写精确哨兵。缺失、伪前缀及未授权案卷逐项拒收 |
| `beyond_intent` | 可选 bool/0/1（别名 `旨外` / `旨外标记` / `旨外恶果`） | #622 旨外恶果/受益标记；与 `origin_ref` 同效果行落库。到期复核机械读此标记落 `transformed`（0072）。缺省=否 |

> ⚠️ **常踩坑**：建筑日常产出 / 固定月度收支 **不要写**（已由程序 `apply_fixed_period_flows` 落账）。这里只写本回合"诏书/事件导致的一次性真金白银收支"，每笔三要素「源→目标，金额」点死。
> 「太仓岁亏三十万」是困境描述，不是本月一笔收支，**别照写成 economy_moves**。

### `faction_delta` — 派系满意度变化
- 合法派系（7 个，写一个就够，不写就不动）：`阉党` `东林` `皇党` `军队` `宗室` `中立` `西学`
- 值：int 增量，作用于 `satisfaction`。改 `leverage` 用 `power_updates`/正文叙事，不在此处。

### `class_delta` — 阶级满意度变化
- 合法 key：`<class_name>` 或 `<class_name>@<region_id>`（如 `农民@shaanxi`）
- `class_name` 在 `content/classes.json` 里：农民 / 士绅 / 官僚 / 军户 / 商人 / 匠户 / 宗藩
- value：dict，只收 `satisfaction` / `leverage` 两个字段；字段值为 int 增量
- 非 dict 的阶级 item（包括扁平 int）不合法，按 item 逐项以 `invalid_enum` 拒收留痕；同一 `class_delta` 中其它合法 item 仍照常落库

### `region_delta` — 地区变化
- 每个 region value 必填 `origin_ref`（已颁 `dossier:<id>` 或 `盘面自发`）；该字段不作为地区属性处理。
- key：region_id（如 `beizhili` / `shaanxi` / `liaodong` 等，看 `content/regions.json` id 列）
- value：dict，字段（来自 `REGION_*` 常量）：
  - score（0-100，int）：`public_support` `unrest` `gentry_resistance` `military_pressure`
  - quantity（int）：`population` `registered_land` `hidden_land` `tax_per_turn` `grain_security`
  - special quantity（int 增量）：`cannon`（城防炮，落库时按 `city_level×8` 上限 clamp 并留痕）
  - text：`natural_disaster` `human_disaster` `status`
  - `controlled_by`：必须是 `powers.id` 中存在的非空势力 id（`null`/空白/未知 id 逐项拒收留痕）
- 中文别名都吃：`动乱`→unrest、`士绅`→gentry_resistance、`粮食`→grain_security 等

### `fiscal_changes` — 改月度收支额度
| 字段 | 约束 |
|---|---|
| `key` | **必须**非空（key 在 `fiscal_config` 表里，如 `liao_xiang_rate`）|
| `delta` | int（无损整数串 `"5"` 可）；0/缺省/null = 无操作不记拒；bool/float/坏串 → 整项拒收留痕（v0.8.x PR2-S3）|
| `reason` | ≤120 字 |
| `origin_ref` | **必填** `dossier:<id>` 或 `盘面自发`；每次调整独立留存来源历史 |
| `beyond_intent` | 可选 bool/0/1（别名 `旨外` / `旨外标记` / `旨外恶果`）；#1260 旨外恶果/受益标记；与 `origin_ref` 同效果行落库。到期复核机械读此标记落 `transformed`（0072）。缺省=否 |

### `fiscal_creates` — 新立月度收支
| 字段 | 约束 |
|---|---|
| `key` | **必须**非空 |
| `account` | **必须** `国库` 或 `内库` |
| `direction` | **必须** `income` 或 `expense`（吃中文别名 `收`/`支`/`收入`/`支出`/`进账`/`出账`）|
| `init_value` | 非负 int（无损整数串 `"300"` 可）；缺省/null = 0；在场负值或非 int（bool/float/坏串）→ 整项拒收留痕（rejection_reports），不再静默 clamp（v0.8.x PR2-S3） |
| `display` | 缺省=key 去 `_base`/`_rate` 后缀（归一 stem）|
| `reason` | ≤120 字 |
| `origin_ref` | **必填** `dossier:<id>` 或 `盘面自发`；base/rate 两行共享此唯一来源 |
| `beyond_intent` | 可选 bool/0/1（别名 `旨外` / `旨外标记` / `旨外恶果`）；#1260 旨外恶果/受益标记；与 `origin_ref` 同效果行落库。到期复核机械读此标记落 `transformed`（0072）。缺省=否 |

> 用于「新设关税岁额折月二十万」「新立宗藩裁革月省禄米三十万」这类**常设新增**。一次性进账（抄没/缴获）不属此类，归 `economy_moves`。

### `fiscal_removes` — 裁撤月度收支
- `key` 非空 + `reason` ≤120
- `origin_ref` **必填**，只能是 `dossier:<id>` 或 `盘面自发`；裁撤历史永久留存
- `beyond_intent` 可选 bool/0/1（别名 `旨外` / `旨外标记` / `旨外恶果`）：#1260 旨外恶果/受益标记；与 `origin_ref` 同效果行落库。到期复核机械读此标记落 `transformed`（0072）。缺省=否
- 整项永久取消才属此类；只降税率/削禄米不算（用 `fiscal_changes`）。

### `army_delta` — 军队变化
- 每个 army value 必填 `origin_ref`（已颁 `dossier:<id>` 或 `盘面自发`）。
- key：army_id（看 `content/armies.json`，如 `guanning` `dadong` 等）
- value 字段（来自 `ARMY_*` 常量）：
  - score（0-100）：`supply` `morale` `training` `equipment` `arrears` `mobility` `loyalty`
  - quantity：`manpower`
  - text：`station` `commander` `controller` `troop_type` `status` `owner_power`
- 中文别名都吃
- `army_delta.arrears` / `欠饷` 只允许既有军**正值外生加欠**（如剧情罚欠、战役拖欠），cutover 下引擎按饷源比例拆入省/中央累加器；`欠饷` 负值拒收。真钱补饷、减欠、核销必须走 `economy_moves`（`purpose=补饷`）或显式核销路径，不能用负数 `arrears` 绕过预算流。新军初始欠饷固定为 0，`new_armies` 不写 `欠饷`。
- ⚠️ `maintenance_per_turn`（维护费）#173 **列已物理删除**：别名（维护费/军费）已移除，写它当非法字段逐项拒收留痕（`invalid_enum`）。月饷由引擎 `army_needed`（=`ceil(manpower × salary_rate / 10000)`，仅 ming）唯一承载；调月饷改 `manpower`。

### `new_armies` — 建军
每项必填 `origin_ref`（已颁 `dossier:<id>` 或 `盘面自发`），创建日志以此提供一跳反查。
⚠️ **`id` 必填**（英文 army_id，如 `tianxiong`）。缺 id 该项逐项拒收留痕（落 `rejection_reports`，不再 print WARN——v0.8.x PR2-S2）。〔崇祯二年八月实测，turn 11〕
全字段：`id`（必填）`name` `owner_power` `station` `theater` `commander` `controller` `troop_type` `manpower`（必填）`morale` `training` `loyalty` `equipment` `supply` `mobility` `status` `pay_source_region` `province_pay_share` `central_pay_share` `is_tusi` `self_funded_pay`…（参考 `ARMY_FIELD_ALIASES`）。普通明军（`owner_power="ming"` 且非土司/自养）必填 `pay_source_region`（明控省 region_id）+ `province_pay_share` + `central_pay_share`，两份额和必须为 1；土司/自养明军才可写 `is_tusi`/`self_funded_pay`，且饷源省为空、两份额为 0/0。#173：`maintenance_per_turn` 列已删，LLM 若仍塞维护费键当未知键忽略（不入库、不影响建军）；月饷由 `army_needed` 按 `manpower` 派生。

### `power_updates` — 外部势力变化
- 每个 power value 必填 `origin_ref`（已颁 `dossier:<id>` 或 `盘面自发`）。
- key：非 `ming` 的 power_id，必须来自输入盘面 `power_ids`（如 `houjin` / `mongol` / `korea` / `bandits` / `bandit_li_zicheng` / `bandit_zhang_xianzhong` 等）；禁止写 `ming`。
- value 字段只允许三项整数增量：`威望` / `leverage`、`实力` / `military_strength`、`经济` / `supply`；其余字段一律逐项拒收留痕。
- #190 流寇分股：李自成股 / 张献忠股等必须写各自 power_id（如 `bandit_li_zicheng`、`bandit_zhang_xianzhong`），不是全局 `bandits`。
- 剿股 / 被剿 / 孤儿股平定：写目标股 `power_updates.<power_id>.military_strength` 下降，这是独立 power 级军事镇压。
- 招安 / 就抚某流寇头目归明：削股不写顶层 `power_updates`，而写在同一条 `人物变更.易主.反噬` 里；同一股同一信封两边都写会拒收顶层 `power_updates` 防双减。
- 若作为战略/外敌战事同信封主账战果，`reason` / `原因` 必须带事件名或战役名；缺锚点不能单独触发战略事件。

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

`origin_kind="event_pool"` 只收当前候选池中的未终态事件。若事件已因超过显式最晚时点进入 `expired` 终态，立项会明确拒收为“事件已过期终态”，不可用后续 delta 让它晚弹或重入。

**战略/外敌战事 node/ending**（如 `jisi_lubian` / `dalingghe` / `lindan_xiqian` / `wuyin_lubian` / `songshan_battle` / `luoyang_fallen` / `kaifeng_siege` / `beijing_fallen`）不能只写 `new_issues`。同一信封必须同时由军务/人事等字段写世界状态主账：`region_delta` / `army_delta` / `power_updates` / `new_armies` / `人物变更`，并在 `reason` / `原因` 带事件名或战役名；程序会在主账落地后记 `event_triggers`，不转长期 issue。只写 event_pool id 会拒收为“缺世界状态主账结果”。

若该战略事件定义了闭合结局标签，还必须同信封写 `事件结局`。当前 `jisi_lubian` 只接受三档：`挡于边墙` / `入塞被遏` / `长驱直入`。例如：

```json
{
  "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
  "事件结局": {"jisi_lubian": "入塞被遏"},
  "region_delta": {"beizhili": {"military_pressure": 35, "reason": "己巳之变软判敌逼京畿", "origin_ref": "盘面自发"}}
}
```

`origin_kind=decree` 时字段：
| 字段 | 约束 |
|---|---|
| `origin_kind` | **必须** `"decree"` |
| `origin_ref` | 承诺 issue 必填，指回诏书 / 旨意来源 |
| `kind` | 默认 `initiative`；若用 `situation` 则按系统危机走 |
| `title` | ≤60 字 |
| `bar_value` | int，默认 25 |
| `expected_months` | int |
| `end_turn` | int，硬时限承诺到期回合；默认 0 |
| `commitment_kind` | 空或 `"until_stop"`；承诺 issue 专用标记，不能只靠 `origin_kind=decree` 区分 |
| `resolve_condition` | 文本；旧结案条件 / 兼容字段 |
| `stop_condition` | dict；落库到 `issues.stop_condition` 时以 JSON 字符串保存。条件 dict 用 `{"army.guanning.arrears":"<=0"}` 这种形态：key 带表/对象/字段，operator 写在 value 内 |
| `bar_good_meaning` / `bar_bad_meaning` | 文案 |
| `ongoing_effects` / `effect_on_resolve` / `effect_on_fail` | dict，月度持续/结案/失败效果 |
| `ongoing_effects.economy[]` | 与顶层 `economy_moves` 同形；#1260 嵌套通道直走 `_apply_economy_list`（不经 `_clean_economy_moves`），`beyond_intent` 吃全套别名 `beyond_intent` / `旨外` / `旨外标记` / `旨外恶果`（真源=simulation 别名表） |
| `cancellable` | "decree" / "never" / "by_progress" |
| `narrative` | 立项叙事 |

⚠️ **kind 白名单**：落库时 `kind` 不在 `(situation, initiative)` 内会被拒。**第二次踩的坑**：`kind="reform"` 被拒（应改 `initiative`）。

⚠️ **数量上限**：active `kind=initiative` 的 issue **总数不超过 15**，超过新立直接拒（"已有十五事在办，朝廷分身乏术"）。

「每月 X 直到补齐」这类旨意承诺必须建 `kind="initiative"` 的承诺 issue：带 `commitment_kind="until_stop"`、`ongoing_effects`、`stop_condition`，落库时会按承诺路径处理为 `inertia=0`、`cancellable="decree"`，并跳过普通国策的 resolve-effect 补全。多军合计可写 `{"army.xuan_da|jizhen.arrears.sum":"<=0"}`，人物阈值可写 `{"character.毛文龙.loyalty":">=65"}`。

「连续 N 月 / 半年为限」这类时限承诺也必须建 `kind="initiative"` 的承诺 issue：带 `commitment_kind="until_stop"`、`ongoing_effects`、`end_turn`。立项公式是 `end_turn = turn + N`，且 `end_turn` 必须严格大于当前 turn；当前回合或过去回合会被拒收，避免立项即过期的持续承诺空壳。半年按 6 个回合计。若同时要求「直到补齐」，同时写 `stop_condition`；`stop_condition` 或 `end_turn` 谁先到谁停。时限到期由结算写 `issue_advances.trigger_kind="expire"` 并标 `dropped`，不要在 delta 里伪造成 `close_issues resolved/failed`，也不要给承诺补普通 resolve/fail 效果。

开放式经常性承诺必须显式带 `commitment_kind="until_stop"` 和非空 `ongoing_effects`；可以没有 `stop_condition` 与 `end_turn`，表示皇帝主动撤销前长期挂账。缺 `commitment_kind` 的同形状会拒收，避免把承诺误落成普通 initiative。

「三月后复试 / 期满复核」这类未来一次性 form③ 承诺带 `commitment_kind="until_stop"`、`end_turn`，`ongoing_effects` 可为空。到期后程序会把它顶到待核议；皇帝/邸报明确裁决或确认已处理后，`close_issues` 可写 `reason="acknowledged"` 作 ACK 收尾，状态标 `dropped`、`issue_advances.trigger_kind="commitment_ack"`，不运行 `effect_on_resolve` / `effect_on_fail`。普通承诺不得用 `close_issues resolved/failed` 绕过专门闭环。

#### #620 / ADR 0074 分段承诺（本片扩展面，不改 #520 本体字段语义）

**存储选型（本片定）**：
- **段表**：`issues.stages_json`（JSON 数组，挂在**单一**承诺 issue 上；禁止假多 issue 接力冒充分段）
- **次回合召对待办**：表 `next_audience_todos`

**`new_issues[].stages`**（可选，仅承诺扩展面）：
```jsonc
"stages": [
  {
    "stage_idx": 0,
    "due_turn": 37,                 // 绝对回合；捕获侧亦可以 scripted「三年X五年Y」换算 origin_turn+N*12
    "criterion_text": "火器见眉目",
    "origin_context": "三年火器见眉目"  // 原诺语境，持久可查（Story 5 回声底）
  }
]
```
- 一条多段 = **一个** `commitment_kind="until_stop"` initiative；`stages` 非空时可不写单值 `end_turn`（引擎可派生 max(due_turn) 仅作兼容展示，**不得**用单值 `end_turn` 冒充多段）
- **段到期扫描独立**（与 form③ 共享「active 承诺 + 到期」谓词语义，不共用其 SQL 结果集）；**待裁载体改道** `next_audience_todos`——段派生的展示 `end_turn` **不**进 form③ `due_commitments` 待核议通道；**独立** `end_turn`（≠ max 段 due）仍可走 form③。结算**不**置 `TurnPhase.AWAITING_DECISION` / `<<DECISION>>` 停轮（0074/0076）
- 去重键：`(commitment_ref, stage_idx, entry_kind)`，不得只按 issue_id 抹段
- 段间自动续，无需玩家 ACK；消费/复命场面归 #621，本片只 own 写端
- 捕获：召对/邸报「三年X五年Y」经生产 `capture_commitment_stages`（scripted 年诺解析）落段；禁 live-LLM 作唯一验收

**`next_audience_todos` 最小字段（P2）**：
| 字段 | 约束 |
|---|---|
| `commitment_ref` | 单一承诺对象 issue id |
| `stage_idx` | int 段序号 |
| `due_turn` | int |
| `criterion_text` | 段判据 |
| `origin_context` | 原话摘句/origin 派生，持久可查 |
| `status` | `pending`（本片写端；消费态归后续片） |
| `entry_kind` | 默认 `staged_commitment`（预留 form③/挽留区分位） |
| `created_turn` | 写入时回合 |

生命周期：段到期当回合结算内确定性写入；下一召对回合 `list_next_audience_todos` 可读；未消费可滚存；restore 只读 DB 接续。


人物承诺型事项也属 `initiative`：如皇帝命臣安抚毛文龙，应立标题类似 `安抚毛文龙·进行中` 的玩家可见 issue，并同时写两件事：`stop_condition` 表达意图阈值（如 `{"character.毛文龙.loyalty":">=65"}`），`ongoing_effects` 表达每月持续动作（如 `{"人物变更":[{"name":"毛文龙","动作":"评定","loyalty":2,"reason":"奉旨持续安抚"}]}`）。只写 `stop_condition`、没有月度动作的载体会被拒收；一次性赏赐、抚恤、拨银若当回合办完，不立 issue，只走 `economy_moves` 与必要的 `人物变更`。

### `dossier_participants` — S2 案卷参与人追加
- 每项必须带 `dossier_id`、`character_id`、`tier`、`delegator_id`；`tier` 只收 `主办` / `协办` / `知情`，`role` 可选。
- 人物与委派人必须是 `characters.name`；写入只追加且精确重复项幂等，不覆盖已有名单。

### `secret_dossier_participants` — #1252 密令案卷参与人追加

personnel_secret 模块产出；与公共 `dossier_participants` **分立**（字段名即 provenance，禁止共享槽位 + union 授权）。settle 内经同一 `append_decree_dossier_participants` 写原语逐项拒收留痕（ADR 0015），不 fail-loud。

| 字段 | 约束 |
|---|---|
| `dossier_id`（别名 `案卷编号`） | **必填**正整数；须落在本批冻结授权集 `secret_dossier_ids_at_input`（由冻结 `secret_orders` 经 `get_dossier_for_secret_order` 解析；缺授权=空闭集，禁 live DB 重建） |
| `character_id` | **必填**在册人物规范名 |
| `tier` | **必填**∈｛主办/协办/知情｝ |
| `delegator_id` | **必填**同案已有主办/协办 |
| `role` | 可选职分文字 |

读缝：`secret_dossier_rosters`（personnel_secret 私轨；每项 `dossier_id`+`participant_roster`，同 `monthly_dossier_reports` 口径）。键控用 `dossier_id`，不另起 `order_id` 键空间。公共 `dossier_participants` 对密令案卷 id 仍拒（#883 隔离不变）。

### 背书条目（ADR 0070）

背书条目与参与人名单分立：担名≠办事，不入毁约追责。条目字段为 `form`∈｛会签/当面站台/御笔手敕｝、会签/当面站台的具名 `endorser_id`（在册人物），或御笔手敕的 `imperial=true`（不得具名大臣）。写入只接受已存在案卷（单向新指旧；悬空/未知案卷拒收），并绑定来源 `source_chat_turn_id`；精确重复项幂等。

捕获：普通 story/presence 每轮即时抽取（#501）；背书绑定走收夜**一次** endorsement-only 批处理（#612）——输入为最终可背书案卷 refs + surviving source turns（含已落普通账），输出只写 `decree_dossier_endorsements`（`form`/`endorser_id`/`imperial`/`source_chat_turn_id`），不重复故事正文。不按皇威二次抑制意愿（意愿调制属 #472）。精确重复项幂等；批失败不落终局、可重试。颁布判官读端投影完整 `endorsements`，并把条目 id 写入 `criteria_snapshot.endorsement_entry_ids`。restore 直接读档，判官读端行为一致。

### `授权变更` / `authority_changes` — 授权档生产槽（ADR 0071 / #611）

顶层槽中英别名：`授权变更` ↔ `authority_changes`。复用既有段适配器（`items → applied/rejected + reason`）；非法项进既有 `rejection_reports`；同批合法项仍应用。不得另造平行写入口。

每项必含判别字段 `动作`（别名 `op`），只收 `授予`（`grant`）／`收回`（`revoke`）。**每项必填正整数 `dossier_id`** 作为唯一案卷来源，且该案卷须在 ADR 0055 下已具备可物化资格（`dossier_authorizes_effects`：已颁/执行中/强颁，或豁免直落）。缺来源／案卷不存在 → `missing_dossier_source`；打回、留中、未达资格 → `dossier_not_effect_eligible`。无来源、打回、留中不得改授权档。

**授予**：必填 `holder_id`（在册人物）、`privilege`（`尚方剑密授`／`便宜行事`／`专差督办`／`新机构专办`）、非空 `scope`（须写典范键 `target_kind:target_id`；裸域／缺冒号 → `invalid_authority_scope`）、`dossier_id`；可选 `effective_turn`（缺省＝当次 turn）、`expires_turn`。应用插入 `authority_records` 行（稳定 id＝行主键）；重复判断以**当次结算的当前 `state.turn`** 查询同 `(holder_id, privilege, scope)` 在持行，不以请求的未来 `effective_turn` 查询：不同案卷命中 → `duplicate_active_authority`。同源 `dossier_id` 重放则不受当前适用性影响，始终幂等回传原 `authority_id`。不得从授权案卷 payload 平行写 `authority_records`。

**收回**：必填 `authority_id`（＝`authority_records.id`）与 `dossier_id`。生产槽不接受 holder/privilege/scope 模糊收回。未知 id → `unknown_authority_id`；首次 `revoked 0→1` 成功并写观感边；已收回 → 幂等 `applied`（`already_revoked`），不改 `revoked_turn`、不写第二笔边。收回＝正当治术：零 0056/皇威代价；观感经既有 `relation_edge_events`（`source=holder_id`, `target=皇帝`, `event_kind=结怨`, `context=收权·罢差·{privilege}·{scope}`, `origin=authority_revoke:{id}`）。

**唯一适用性投影**（颁布判官与 #613 共用）：承办对象＝案卷 `executor_id`（character）∪ `participant_roster` 中 `主办`/`协办`（不含 `知情`，不读 payload assignee）；事域**仅**典范键 `target_kind:target_id`（无裸 `target_id` 平行匹配）；再过滤在持谓词。投影结果为 `held_authorities`；`criteria_snapshot.authorization_ids` **只**含投影 id 的十进制字符串——禁止从 payload `authorization_id(s)` 拼第二真源。自然语言授予/收权捕获分别由 #528/#523 回接，本契约不作关键词推断。

### `dossier_executions` — S1 案卷执行结局
- 每项必须带 `dossier_id`、`outcome`、`note`；可选第四键 `affected_parties`。
- `dossier_id` 必须指向当前处于 `executing` 的案卷；`outcome` 只收 `fulfilled` / `degraded` / `failed` / `transformed`；`note` 不得为空。
- `affected_parties` 可选；若给出则须通过 `validate_affected_parties` 全键（kind/key/direction/intensity），且 intensity 贴合终值固定映射（failed/transformed→strong，degraded→weak，次责可降一档）；拒收不落库。该清单**不**驱动连坐额度——机械写账仍由 roster+终值映射生成。
- 每项独立校验并拒收；通过后写入执行记录并关闭该案卷。此字段只描述 S1 当前的案卷执行回注，不是其它效果族的通用回指机制。

### `faction_denunciations` — 政敌检举条目（#627 / ADR 0077 ID-12）
别名 `政敌检举` / `检举条目`。issues 模块产出；settle 内经 `accept_faction_denunciations` 承接落库。

| 字段 | 约束 |
|---|---|
| `accuser_name`（别名 `检举人`） | **必填**在朝 active 人物规范名 |
| `subject_name`（别名 `被检举人`） | 可选；缺省由引擎从所指案卷承办人解析 |
| `target_dossier_id`（别名 `所指案卷`） | **必填**正整数；须指向真实存在且非 `closed` 的案卷 |
| `memorial_text`（别名 `弹章正文`） | **必填**非空；LLM/scripted 原文，引擎零模板 |

引擎行为：真伪底由 fork 单源读端机械派生（分叉→真检举 origin mark；无分叉→私货 mark）；去重键=检举人×案卷×真伪类（**不含 turn**），案情升级可同键再落；暴露载体=检举条目自身的结构化 origin/payload，**不**写 `dossier_loophole_exposures`、**不**回注 `character_knowledge_events`、不改世界状态、不自动转案。弹章对玩家的呈现由 simulator 事件章/探子回报承担。

### `dossier_reconciliations` — 在途拨帑月度对账（#567 / ADR 0054）
别名 `拨帑对账`。issues 模块产出；settle 内经 `record_monthly_grant_reconciliations` 消费。

| 字段 | 约束 |
|---|---|
| `dossier_id`（别名 `案卷编号`） | **必填**正整数；须落在本月在途拨帑扫描面（`list_monthly_grant_reconciliation_targets`）内 |
| `arrived_amount`（别名 `实抵` / `到银`） | 与 `loss_amount` **二选一**；整数，单位两 |
| `loss_amount`（别名 `折损`） | 与 `arrived_amount` **二选一**；整数，单位两；引擎换算 `arrived = ordered - loss` |
| `note` | 可选文本 |

引擎行为：只按护行/稽核在场口径 **clamp** 实抵上下界；**不二次扣库**、不改原 `economy_move`、**不写 0058 进展**（密奏仍走 personnel_secret / #566）。无提案时对扫描面内每路按口径中位机械落账（有/无护行同一存储、逐路键控）。

> ⚠️ **与文档开头「section 内非法项逐项拒收留痕」通则相反**：本字段走 fail-loud。`record_monthly_grant_reconciliations` 对未知案卷、重复案卷、非在途拨帑、缺量字段、非列表提案一律 `raise`；落在 settle atomic 内 = **整月响亮中止**（同 #566 `dossier_progress_reports` 的 progress fail-loud 口径）。空提案（缺省/`[]`）合法——程序用中位默认。

### `dossier_progress_reports` — 长差密令逐月密奏（#566 / ADR 0058）
personnel_secret 模块产出；settle 内经 `record_monthly_dossier_progress` 消费。
- 每项必须带 `dossier_id`、`progress_band`、`memorial_text`；三者皆非空。
- 合资格集 = 精确 tag `护行`/`稽核` 且当前期限至少两月的密令案卷（读缝 `monthly_dossier_reports`）。
- **必须完整覆盖**合资格集：不得漏项、不得重复、不得指向未知案卷；无合资格却收到提案亦拒。
- 同 `dossier_reconciliations`：非法/不全 → fail-loud 整月中止，不走逐项拒收留痕。

### 颁布 verdict 契约（非 delta 字段）
打回 verdict 的 `blocked_layer` 只收 `cabinet_drafting` / `palace_rescript` / `six_offices`；`primary_opponents` 是非空 typed 派系清单，每项须且仅含 `kind="faction"` 与在册派系 `key`；`gatekeeper_id` 只可为 null 或在册人物 id。`criteria_snapshot` 须且仅含 `imperial_authority_band`、`appointment_tenure`、`authorization_ids`、`endorsement_entry_ids`。前三类字符串值不得混入数字；阻力数值字段均非法。合法 typed 数值/布尔位仅包括正整数 `dossier_id`、正整数 `endorsement_entry_ids`（拒绝 bool/float/数字串），以及 bool `midzhi_unpromulgatable`。

快照随既有判决历史原样落 JSON，仅供审计，后续盘面变化不回写、不重算。非法 verdict 整批不应用，并把原 item/原因/类别/来源写入既有 `rejection_reports`；不存在第二套 verdict schema 或审计表。

### `cancels` — 撤销 issue
- `issue_id` int + `reason` 文本
- 仅 `cancellable in (decree, by_progress)` 的 issue 可撤；预设 `never` 撤不动。

### `close_issues` — 结案 issue
- `issue_id` int + `reason`（`resolved` / `failed` / `acknowledged`）+ `narrative` 文本。
- 一般由 issue bar=100/0 自动了结；这里用于强行结案。`acknowledged` 只用于已到期 form③ 承诺被皇帝明确裁决/确认处理后的 ACK 收尾。

### `人物变更` — 人事档案单一入口
每条必须带 `name`（必须在 `characters` 名册）和 `动作`。`动作` 只收八个值：`任命` / `罢黜` / `调任` / `处置` / `易主` / `册封` / `行止` / `评定`。未知动作、查无此人、缺必填字段、非法枚举或非法状态迁移都会逐项拒收留痕。

共通字段：
| 字段 | 约束 |
|---|---|
| `name` | 必填，精确人物名 |
| `动作` | 必填，八动作之一 |
| `reason` / `status_reason` | 可选，人读叙事说明 |
| `reason_code` | 可选，机读枚举；未知值归一到 `未识别`，缺省和读不懂不能混成一个语义 |

动作 payload：
| 动作 | 必填 | 可选 | 说明 |
|---|---|---|---|
| `任命` | `office` | `office_type` / `faction` / `任别` | 身名分入职名分；若目标现持职名分，执行位可归一为 `调任` |
| `罢黜` | — | `reason_code` | 清职名分并落 `dismissed`；政治反应由裁判另产 |
| `调任` | `office` | `office_type` / `faction` / `任别` | 旧职解绑、新职绑定；若目标现无职名分，执行位可归一为 `任命` |
| `处置` | `status` | `子动作` / `reason_code` | 状态迁移：下狱、流放、致仕、放归、赐死、卒、起复、昭雪、夺情等 |
| `易主` | `new_power` / `方式` / `反噬` | `new_title` | `方式` ∈ `主动投敌` / `被俘而降` / `主动归附`；`反噬` 为内嵌派系/势力反应；legacy 翻译才可用 `不明` |
| `册封` | `office` | `office_type` | 后宫 candidate 出边；落选走 `处置(status=offstage, reason_code=落选)` |
| `行止` | `location` 或 `transit_to` | `reason_code` | 去向变更；`transit_to` 非空表示在途，迁出 active 时会被清空 |
| `评定` | `loyalty` | — | 人物忠诚软判增量（integer，非新值），用于安抚/离心等叙事裁判后的结构化数值变化 |

`任别` 只收 `真除` / `署理` / `兼署` / `加衔`；缺省按 `真除`，用于兼容旧档且不重判历史任命。非法值逐项拒收留痕。

状态白名单（DB 全集 8 态）：`active` / `candidate` / `offstage` / `dismissed` / `imprisoned` / `exiled` / `retired` / `dead`。其中 **`处置.status` 只可直迁 6 态**（去掉 `active` / `candidate`——二者经 `任命` / `册封` 级联或 applier 起复派生达成；直接 `处置(status=active/candidate)` 被拒 `invalid_transition`，见 `issues.py` `disposition_statuses`）。死人没有 status 出边；追谥、追赠等身后事不进 `人物变更`。

#190 流寇招安：`易主(new_power:"ming", 方式:"主动归附")` 的 `反噬` 若写势力削弱，只能指向该人物当前原势力股；写到其它流寇股会整条拒收，防「招张献忠却削李自成」。头目已死时不能 `易主`，其遗留孤儿股只能走 `power_updates` 剿股。

> **旧四 key（appointments / character_status_changes / character_power_changes / office_changes）不在本契约文档化**（ADR 0009 决定11「alias 保留但不写文档」）：新产出的 delta 只写 `人物变更`；旧 key 仅作历史 delta / ready=1 重试真源的内部兼容翻译层，永不获得新能力（`行止` / `方式` 仅新 key；`reason_code` 系 处置/罢黜 通用辅助字段，legacy `character_status_changes` 翻译保真带过、非新增能力），自然枯死。翻译保真（执行序、spillover 殿后、legacy_gate/legacy_partial 注记）由 `ming_sim/person_delta_adapter.py` + `tests/test_person_delta_adapter.py` 覆盖，不在用户面 schema 重复。

### `secret_order_updates` / `secret_order_closes`
- updates：`order_id` int + `sim_note`（本月推进实况）+ 可选 `impact` + 可选布尔 `disclosed`（中文键 `泄漏结论`；可省略）。`disclosed`/`泄漏结论`：密令情节已**实际公开**才为 true（被目击、闹至公堂、承办人被拿获、目标公开反击、明发上谕、科道公开参劾等）；为 true 时触发 `secret_order_disclosure:` 公开知识事件（简报升公共面的唯一闸）。风声/警觉/暴露风险仍为不填或 false。
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
| `issues` | `issue_advances` `new_issues` `事件结局` `cancels` `close_issues` `dossier_executions` `dossier_participants` `authority_changes` `dossier_reconciliations` `faction_denunciations` |
| `personnel_secret` | `人物变更` `secret_order_updates` `secret_order_closes` `dossier_progress_reports` `secret_dossier_participants` `emperor_fate` |

---

## 落库守门 - 已经踩过的坑（list of pain）

| 字段 | 我犯过的错 | 真相 |
|---|---|---|
| `new_issues[].origin_kind` | 不填 | **必填** `decree` 或 `event_pool` |
| `new_issues[].kind` | 写 `reform` | 白名单 `situation` / `initiative`；改革/试点都用 `initiative` |
| `new_issues[].title` | — | ≤60 字 |
| `new_issues` 总数 | — | active `initiative` ≤15 |
| `close_issues[].reason` | 填了 `result` 没填 `reason` | close_issues 要 **`reason`** 字段（不是 result），空则整条被跳过。注：若同时用 `issue_advances` 把 bar 推满（≥100），issue 会**自动 resolved**，不依赖 close_issues |
| `power_updates` 字段 | 写 `{"stance":...}` 或 `{"satisfaction":...}` | **实际守门只收三个字段：`威望`(leverage) / `实力`(military_strength) / `经济`(supply——英文 canonical 是 supply,别名表把 经济 映到它;写 `economy` 不被认会拒)。** 连 `satisfaction` / `cohesion` / `stance` / `leader` / `agenda` 全被拒，逐项拒收留痕落 `rejection_reports`（不再 print WARN——v0.8.x PR2-S1;supply 一直在白名单内,旧坑表把它列进被拒名单是 doc 错误）。改外势态度文用 `world_advance`（≤40字）；改归附倾向只能动 leverage/military_strength/supply。本文档上方 `power_updates` 段已按运行时守门收敛。〔崇祯二年五、六月结算实测，turn 8/9〕|

每踩一坑就补到这张表里，下次别再来一遍。

---

## 真相源对照（代码升级后跟原仓库 rebase 时务必跑一遍 diff）

| 文件 | 看什么 |
|---|---|
| `ming_sim/simulation.py` | `EMPTY_EXTRACTION` / `TOP_LEVEL_ALIASES` / `ITEM_FIELD_ALIASES` / `MODULE_FIELDS` / `_clean_*` |
| `ming_sim/issues.py` | `apply_score_extraction()` 里各 issue/new_issue 校验、`origin_kind`/`kind` 白名单 |
| `ming_sim/db.py` | `set_character_status()` 状态白名单、各 `apply_*_deltas` 字段守门 |
| `ming_sim/constants.py` | `REGION_*` / `ARMY_*` / `POWER_*` / `BUILDING_*` / `ECONOMY_ACCOUNTS` / `SCORE_METRICS` |
