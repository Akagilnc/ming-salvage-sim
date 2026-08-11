# DELTA_SCHEMA.md — 我产 delta JSON 的格式契约

**真相源**：`ming_sim/simulation.py`（`EMPTY_EXTRACTION` / `MODULE_FIELDS` / `_clean_*`）+ `ming_sim/issues.py`（落库守门）+ `ming_sim/constants.py`（白名单）。

用途：每回合月末，我以裁判身份产一份 delta JSON，由 driver 喂 `apply_score_extraction(db, state, extracted)` 落库。**未知顶层字段会响亮中止；已知 section 内值不合法的条目逐项拒收留痕。** 必须查表，不要凭"我以为"。
v0.8.0.0 起（ADR 0008 PR1）：**shape 级垃圾**（非 dict、损坏 JSON、未知顶层字段）过不了 `validate_delta_shape`，结算会响亮中止（SettlementAbort + 诊断错误包），不再静默吞——产出前自查顶层 23 字段，别指望守门人帮忙兜。

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
  "事件结局":          {},  // dict[event_id -> 闭合结局标签]
  "cancels":          [],  // 撤销 issue
  "close_issues":     [],  // 结案 issue
  "dossier_executions": [], // 执行中案卷的明确结局（S1）
  "dossier_participants": [], // 月末新出场的案卷参与人（S2，append-only）

  // ── personnel_secret 模块 ──
  "人物变更":                    [],  // ADR 0009 单一人物入口：每项必带「动作」
  "secret_order_updates":       [],  // 密令副作用
  "secret_order_closes":        [],  // 密令核议结案
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

> ⚠️ **常踩坑**：建筑日常产出 / 固定月度收支 **不要写**（已由程序 `apply_fixed_period_flows` 落账）。这里只写本回合"诏书/事件导致的一次性真金白银收支"，每笔三要素「源→目标，金额」点死。
> 「太仓岁亏三十万」是困境描述，不是本月一笔收支，**别照写成 economy_moves**。

### `faction_delta` — 派系满意度变化
- 合法派系（7 个，写一个就够，不写就不动）：`阉党` `东林` `皇党` `军队` `宗室` `中立` `西学`
- 值：int 增量，作用于 `satisfaction`。改 `leverage` 用 `power_updates`/正文叙事，不在此处。

### `class_delta` — 阶级满意度变化
- 合法 key：`<class_name>` 或 `<class_name>@<region_id>`（如 `农民@shaanxi`）
- `class_name` 在 `content/classes.json` 里：农民 / 士绅 / 官僚 / 军户 / 商人 / 匠户 / 宗藩
- 值：int 增量 〔⚠️ 与实码不符：实际为嵌套结构 `{类:{satisfaction/leverage: int}}`，扁平值被 `_apply_class_dict` 静默跳过，见 ADR 0056〕

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

> 用于「新设关税岁额折月二十万」「新立宗藩裁革月省禄米三十万」这类**常设新增**。一次性进账（抄没/缴获）不属此类，归 `economy_moves`。

### `fiscal_removes` — 裁撤月度收支
- `key` 非空 + `reason` ≤120
- `origin_ref` **必填**，只能是 `dossier:<id>` 或 `盘面自发`；裁撤历史永久留存
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
| `cancellable` | "decree" / "never" / "by_progress" |
| `narrative` | 立项叙事 |

⚠️ **kind 白名单**：落库时 `kind` 不在 `(situation, initiative)` 内会被拒。**第二次踩的坑**：`kind="reform"` 被拒（应改 `initiative`）。

⚠️ **数量上限**：active `kind=initiative` 的 issue **总数不超过 15**，超过新立直接拒（"已有十五事在办，朝廷分身乏术"）。

「每月 X 直到补齐」这类旨意承诺必须建 `kind="initiative"` 的承诺 issue：带 `commitment_kind="until_stop"`、`ongoing_effects`、`stop_condition`，落库时会按承诺路径处理为 `inertia=0`、`cancellable="decree"`，并跳过普通国策的 resolve-effect 补全。多军合计可写 `{"army.xuan_da|jizhen.arrears.sum":"<=0"}`，人物阈值可写 `{"character.毛文龙.loyalty":">=65"}`。

「连续 N 月 / 半年为限」这类时限承诺也必须建 `kind="initiative"` 的承诺 issue：带 `commitment_kind="until_stop"`、`ongoing_effects`、`end_turn`。立项公式是 `end_turn = turn + N`，且 `end_turn` 必须严格大于当前 turn；当前回合或过去回合会被拒收，避免立项即过期的持续承诺空壳。半年按 6 个回合计。若同时要求「直到补齐」，同时写 `stop_condition`；`stop_condition` 或 `end_turn` 谁先到谁停。时限到期由结算写 `issue_advances.trigger_kind="expire"` 并标 `dropped`，不要在 delta 里伪造成 `close_issues resolved/failed`，也不要给承诺补普通 resolve/fail 效果。

开放式经常性承诺必须显式带 `commitment_kind="until_stop"` 和非空 `ongoing_effects`；可以没有 `stop_condition` 与 `end_turn`，表示皇帝主动撤销前长期挂账。缺 `commitment_kind` 的同形状会拒收，避免把承诺误落成普通 initiative。

「三月后复试 / 期满复核」这类未来一次性 form③ 承诺带 `commitment_kind="until_stop"`、`end_turn`，`ongoing_effects` 可为空。到期后程序会把它顶到待核议；皇帝/邸报明确裁决或确认已处理后，`close_issues` 可写 `reason="acknowledged"` 作 ACK 收尾，状态标 `dropped`、`issue_advances.trigger_kind="commitment_ack"`，不运行 `effect_on_resolve` / `effect_on_fail`。普通承诺不得用 `close_issues resolved/failed` 绕过专门闭环。

人物承诺型事项也属 `initiative`：如皇帝命臣安抚毛文龙，应立标题类似 `安抚毛文龙·进行中` 的玩家可见 issue，并同时写两件事：`stop_condition` 表达意图阈值（如 `{"character.毛文龙.loyalty":">=65"}`），`ongoing_effects` 表达每月持续动作（如 `{"人物变更":[{"name":"毛文龙","动作":"评定","loyalty":2,"reason":"奉旨持续安抚"}]}`）。只写 `stop_condition`、没有月度动作的载体会被拒收；一次性赏赐、抚恤、拨银若当回合办完，不立 issue，只走 `economy_moves` 与必要的 `人物变更`。

### `dossier_participants` — S2 案卷参与人追加
- 每项必须带 `dossier_id`、`character_id`、`tier`；`tier` 只收 `主办` / `协办` / `知情`，可带 `role` 与 `delegator_id`。
- 人物与委派人必须是 `characters.name`；写入只追加且精确重复项幂等，不覆盖已有名单。

### `dossier_executions` — S1 案卷执行结局
- 每项必须带 `dossier_id`、`outcome`、`note`。
- `dossier_id` 必须指向当前处于 `executing` 的案卷；`outcome` 只收 `fulfilled` / `degraded` / `failed` / `transformed`；`note` 不得为空。
- 每项独立校验并拒收；通过后写入执行记录并关闭该案卷。此字段只描述 S1 当前的案卷执行回注，不是其它效果族的通用回指机制。

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
| `issues` | `issue_advances` `new_issues` `事件结局` `cancels` `close_issues` `dossier_executions` `dossier_participants` |
| `personnel_secret` | `人物变更` `secret_order_updates` `secret_order_closes` `emperor_fate` |

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
