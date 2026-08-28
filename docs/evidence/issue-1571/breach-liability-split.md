# 毁约/连坐拆清施工证据（issue #1571 / ADR 0151）

- 分支 `kimi/issue-1571`，HEAD `e88cc29c`（2026-08-27 逐行实读）。
- 判词（大理寺一审打回项）：「拆清毁约/连坐……breach/apply_joint_liability 不得同时被列作 store 深入口又被判为段消费。现码 breach_decree_dossier/apply_execution_joint_liability 同时写案卷、cost events、state.metrics、派系满意度和关系边……自相矛盾。」
- 设计原则（grill Q2/Q11，不重开）：store 纯 DB、不收 state/content；0056 判定数据（触发集、cost_events 流水）归 store；state.metrics/派系满意度/关系边等效果消费留段适配器/编排层。
- 表归属基线（ADR 0151 决定 2 的 12 表 + `faction_denunciations`（dossier_id 锚定卫星表，随检举子模块）= **13 表**，与 boundary-inventory §1 同口径）：`decree_dossiers`、links、reconciliations、endorsements、link_rejections、`decree_dossier_decisions`、reported_progress、supervision_presence、loophole_exposures、actual_progress、`faction_denunciations`、`decree_cost_events`、`pending_promulgation_verdicts`。下表「出界」= 所写表不在这 13 张内。

## 0. 常量群（ming_sim/db.py:16004-16015）

`_OVERRIDE_AUTHORITY_COST=-5`（16004）、`_REACTION_INTENSITY`/`_REACTION_SIGN`（16005-16006）、`_BREACH_FACTION_REACTION`（16007）、`_JOINT_LIABILITY_COST_IDENTITY="连坐"`（16010）、`_EXECUTION_OUTCOME_INTENSITY`（16011-16013）、`_JOINT_LIABILITY_TRIGGERS=frozenset(...)`（16014）、`_INTENSITY_DOWNGRADE`（16015）。纯数据、零 IO——判定数据，归 store。

出界直读现状（ADR 0151 决定 6 要求改走公开常量）：`due_review.py:554`（`GameDB._JOINT_LIABILITY_TRIGGERS`）、`issues.py:8192`（同）、`issues.py:8194` 经 `validate_joint_liability_affected_parties` 间接消费 `_EXECUTION_OUTCOME_INTENSITY`/`_INTENSITY_DOWNGRADE`（db.py:16296-16302）。拆分后去下划线公开：`JOINT_LIABILITY_TRIGGERS`、`EXECUTION_OUTCOME_INTENSITY`、`JOINT_LIABILITY_COST_IDENTITY`。

## 1. 逐函数写向表（现码事实）

| 函数 (file:line) | 写哪些表 | 写哪些内存态 | 读（判定用） | 调哪些外部模块 |
|---|---|---|---|---|
| `_record_decree_cost` (db.py:16069-16080) | `decree_cost_events` INSERT OR IGNORE（16073-16079；幂等键 = UNIQUE(dossier_id,cost_identity,cost_kind,target_kind,target_id)，schema db.py:1704-1717，**不含 turn**） | 无 | 无 | 无。turn 是纯 int 入参。**已纯** |
| `_current_judge_affected_parties` (db.py:16082-16105) | 无（零写） | 无 | `decree_dossier_decisions` 本回合最新 Judge 行 `rescript_action=''`（16086-16091）；`factions`/`classes` 名集（16102-16103） | `ming_sim.strict_types.validate_affected_parties`（import db.py:68）。turn 纯入参。**已纯** |
| `_apply_authority_cost` (db.py:16107-16123) | ① `decree_cost_events` authority 行（16111-16115，经 `_record_decree_cost`，turn 取 `state.turn`）；② `metrics` 表 upsert 皇威（16119-16123）**出界** | `state.metrics["皇威"]` clamp 写（16116-16118） | 无 | 无 import，但收 `state: GameState`（16108） |
| `_apply_override_costs` (db.py:16125-16162) | ① authority 轨全量（经 `_apply_authority_cost`，16131-16133）；② `decree_cost_events` satisfaction 行（16148-16152）；③ `factions` 表（16154-16156 经 `adjust_factions`，定义 8696-8750）**出界**；④ `classes` 表（16158-16160 经 `adjust_classes`，定义 6614-6655）**出界** | `state.metrics`（经 `_apply_authority_cost`） | `decree_cost_events` 存在性闸（parties 批级幂等，16134-16139）；`_current_judge_affected_parties(dossier_id, state.turn)`（16141） | `commit=True` 时自主 `conn.commit()`（16161-16162） |
| `breach_decree_dossier` (db.py:16164-16246) | ① `decree_cost_events` breach 门闩行（16183-16187，整笔幂等）；② authority 轨（16188）；③ `relation_edge_events` 辜负边（16214-16218 经 `record_relation_edge_event`，定义 21922-21992）**出界**；④ `decree_cost_events` satisfaction 行 + `factions` 表（16229-16235）**出界（派系部分）**；⑤ `decree_dossiers`：closed 案补 `interruption_reason`（16237-16240）否则 `status='closed',closed_turn,interruption_reason,closed_at`（16242-16245） | `state.metrics["皇威"]`（经 `_apply_authority_cost`） | `get_decree_dossier`（16175）、`dossier_authorizes_effects`（16180，定义 15558-15578 纯 DB）、`characters` 表 faction/status（16204-16206）、`factions` 名集（16219-16222） | `commit=True` 时 import `ming_sim.decree.atomic_and_reload` 自开事务+回滚重载（16170-16171）；`record_relation_edge_event` 取 `state.turn/year/period`（16216-16217） |
| `list_execution_liability_parties` (db.py:16248-16255) | 无 | 无 | `get_decree_dossier`（16252） | `ming_sim.participant_roster.project_execution_liability_parties`（16255，定义 participant_roster.py:99-152）。**已纯** |
| `validate_joint_liability_affected_parties` (db.py:16289-16317) | 无 | 无 | `factions`/`classes` 名集（16303-16309） | `validate_affected_parties`（16310）。**已纯**（纯参数 + DB 名集读） |
| `apply_execution_joint_liability` (db.py:16319-16411) | ① `decree_cost_events` liability 整笔门闩（16353-16357）；② `relation_edge_events` 连坐边（16389-16393）**出界**；③ `decree_cost_events` satisfaction 行 + `factions` 表（16396-16402）**出界（派系部分）**；④ `decree_dossiers.execution_note`（16406-16410 经 `merge_execution_note`，定义 16257-16287，commit=False 内联） | 无直写；state 仅作 `state.turn/year/period` 标量源（16354/16391/16397）与 `atomic_and_reload` 回滚重载对象 | `get_decree_dossier`（16349）、`factions` 名集（16359-16362）、`characters` 行（16375-16377）、`project_execution_liability_parties`（16365-16367） | `commit=True` 时 `atomic_and_reload`（16343-16344）；logging（已故跳过，16382） |
| `trigger_commitment_backlashes` (db.py:13838-14014) | ① `issues` INSERT（13976-13991 经 `insert_issue`，定义 19740-19841）**出界**；② `character_knowledge_sources`（`insert_issue` 内 19832-19840 经 `register_character_knowledge_source`，定义 20986+）**出界**；③ `issues` UPDATE + `issue_advances` INSERT（13992-14002 经 `advance_issue`，定义 19843-19917）**出界** | `state.metrics` 一锤子（13973-13975 经 `flows._apply_metric_dict`，定义 flows.py:912-942，flows.py:941 直改内存；修正率经 `db.legacy_modifiers`/`apply_legacy_pct` 读 DB） | `list_next_audience_todos`（13879）、`issues` 表（13890-13894、13965-13967）、`decree_dossiers` 终值扫描（13916-13926）、`dossier_has_beyond_intent`（13936）、`list_commitments_for_dossier`（13938）、`find_any_issue_by_origin`（13960）、`assess_foundation_tier(self, cid)`（13954） | import `ming_sim.commitment_backlash`（13857-13865）、`ming_sim.breach_plea`（13866-13872）、`ming_sim.flows._apply_metric_dict`（13873）；`commit=True` 且有触发时自主 commit（14012-14013） |

补充事实：

- `_append_midzhi_stigma`（db.py:15006-15036）只写 `decree_dossiers.stigma_json`（在 13 表内）、纯参数 turn——已纯，无需拆。
- `record_relation_edge_event`（db.py:21922-21992）本身已是「参与调用方事务、owns_transaction 才 commit」（21983-21984），拆后不改动，仅调用者从 store 内挪到段侧。
- `apply_dossier_promulgation`（db.py:15633+）与 `apply_dossier_verdicts`（17100+）整体收 `state/content/registry`——verdict 物化链，ADR 0150 决定 5 已划给编排层段适配器；本拆分只涉及其内联的 `_apply_override_costs` 两笔（15707-15711、17166-17172）。

## 2. 拆分投影（签名级）

### 2.1 store 侧（DossierStore；纯参数；零 commit，默认参与调用方事务——ADR 0151 决定 7，本批函数无 pending_verdicts 例外）

原样随迁（已纯，仅去前缀归属）：

```python
def _record_cost_event(self, dossier_id: int, turn: int, cost_kind: str,
    target_kind: str, target_id: str, delta: int, reason: str, *,
    cost_identity: str) -> bool                      # 现 16069，私有内核
def _judge_affected_parties(self, dossier_id: int, turn: int
    ) -> list[dict]                                  # 现 16082，私有读
def validate_joint_liability_affected_parties(self,
    affected_parties: object, outcome: str) -> None  # 现 16289，公开
def list_execution_liability_parties(self, dossier_id: int
    ) -> list[dict]                                  # 现 16248，公开
JOINT_LIABILITY_TRIGGERS: frozenset                  # 现 16014，公开常量
EXECUTION_OUTCOME_INTENSITY: dict                    # 现 16011，公开常量
```

新公开判定写动词（替代混合旧动词，效果意图作返回值）：

```python
@dataclass(frozen=True)
class OverrideEffects:            # 现 _apply_override_costs 的效果半
    authority_delta: int | None   # authority 行实写才为 -5，幂等撞键为 None
    party_deltas: tuple[tuple[str, str, int], ...]  # (kind, key, delta)，仅实写成功项

def record_override_judgment(self, dossier_id: int, turn: int, *,
    include_authority: bool, include_parties: bool, reason: str,
    ) -> OverrideEffects
    # 做：authority cost_event 幂等写（现 16111-16115）；parties 批级存在性闸
    # （现 16134-16139）；逐 party 读 _judge_affected_parties + satisfaction
    # cost_event 幂等写（现 16141-16152 的校验+写轨）。
    # 不做：state.metrics、metrics 表、adjust_factions/adjust_classes。

@dataclass(frozen=True)
class BreachEffects:              # 现 breach_decree_dossier 的效果半
    authority_delta: int | None
    faction_deltas: tuple[tuple[str, int], ...]        # (faction, delta) 仅实写成功项
    relation_edges: tuple[tuple[str, str, str], ...]   # (target, "辜负", origin)；context=reason

def record_breach_judgment(self, dossier_id: int, *,
    turn: int, reason: str,
    ) -> BreachEffects | None     # None = 现 return False 两分支（状态不合格 16179-16182 / 门闩撞键 16183-16187）
    # 做：资格读（16175-16182）、breach 门闩行、authority cost_event 行、
    # roster→主办/委派人→characters→factions 归属计算（16191-16223，全 DB 读）、
    # 逐派系 satisfaction cost_event 幂等写（16229-16232）、
    # decree_dossiers close/interruption_reason（16236-16245）。
    # 不做：state.metrics、metrics 表、record_relation_edge_event、adjust_factions。
    # 不携带 year/period：store 自身不消费时间标量（边时间戳只被段侧写边使用），
    # 由调用方把 state.year/period 直接交给段侧 apply_breach_effects。

@dataclass(frozen=True)
class JointLiabilityEffects:      # 现 apply_execution_joint_liability 的效果半
    faction_deltas: tuple[tuple[str, int], ...]
    relation_edges: tuple[tuple[str, str, str], ...]   # (target, "连坐", origin)

def record_joint_liability(self, dossier_id: int, outcome: str, *,
    turn: int, reason: str = "",
    ) -> JointLiabilityEffects | None
    # None = 非触发 outcome（现 16334-16335）或 liability 门闩撞键（现 16353-16357）。
    # 做：触发集过滤、门闩行、projection→characters 读（16359-16383，含已故/零档过滤）、
    # 逐派系 satisfaction cost_event 幂等写（16396-16399）、
    # execution_note 合并「连坐归属：…」（16404-16410 经 merge_execution_note 随迁）。
    # 不做：record_relation_edge_event、adjust_factions。
    # 不携带 year/period：边时间戳只被段侧写边使用，由调用方直交段侧
    # apply_joint_liability_effects，store 不透传。
```

backlash 的 store 部分只剩纯读组合（供编排层消费）：

```python
def list_backlash_terminal_dossiers(self, before_turn: int) -> list[dict]
    # 只做 13 表内纯读：现 13916-13926 终值扫描（decree_dossiers）
    # + list_commitments_for_dossier（13938）；不落 issue、不碰 metrics。
    # 不含 dossier_has_beyond_intent：该读面经 list_dossier_durable_effects
    # 读 economy_ledger/fiscal_config_*（非 13 表，db.py:20346-20354 实读），
    # 留 GameDB，beyond_intent 过滤由编排层自行组合 GameDB 侧读面
    # （与 boundary-inventory §2.1 #14/§2.2 同口径）。
```

### 2.2 段/编排侧消费点

```python
# 段适配器（就近落 breach_plea.py / issues.py 调用点所在层，或 0150 段模块）：
def apply_breach_effects(db, state, dossier_id, turn, year, period, reason,
                         fx: BreachEffects) -> None
def apply_joint_liability_effects(db, state, turn, year, period, reason,
                                  fx: JointLiabilityEffects) -> None
def apply_override_effects(db, state, dossier_id, reason,
                           fx: OverrideEffects) -> None
```

消费逻辑 = 现码原样搬迁，逐条对应：

- `authority_delta` → 现 16116-16123：`state.metrics["皇威"]` clamp + `metrics` 表 upsert（上浮为段助手，三处复用一份）。
- `faction_deltas` → 现 16233-16235 / 16400-16402：`db.adjust_factions({f: {"satisfaction": d}}, commit=False)`。
- `party_deltas` → 现 16153-16160：faction→`adjust_factions`、class→`adjust_classes`（均 commit=False）。
- `relation_edges` → 现 16214-16218 / 16389-16393：`db.record_relation_edge_event(source="皇帝", target=…, event_kind=…, context=reason, origin=…, turn=…, year=…, period=…)`。
- backlash 编排（decree.py:2334 所在结算段）：store 纯读 → 逐候选 `_apply_metric_dict`（现 13973-13975）→ `insert_issue`（13976-13991）→ `advance_issue`（13992-14002），均 commit=False，外层事务统一提交。

### 2.3 拆完后 store 零 state/content 依赖的证明

现码中这批函数对 `state` 的全部用法逐条消解：

| 现码用法 | 位置 | 消解 |
|---|---|---|
| `state.turn` 作 cost_event/边/closed_turn | 16112、16141、16184、16216、16230、16244、16354、16391、16397 | 纯 `turn` 入参 |
| `state.year`/`state.period` 作边时间戳 | 16217、16392 | store 不携带（签名无 year/period）；调用方把标量直交段侧 `apply_*_effects` 写边 |
| `state.metrics["皇威"]` 写 | 16116-16118 | 删出 store；进 `*_Effects.authority_delta` 返回值 |
| `atomic_and_reload(self, state)` 自开事务 | 16170-16171、16343-16344 | 删；store 一律 commit 自由、参与调用方事务（决定 7 默认态） |
| `state.metrics` 一锤子 + `_apply_metric_dict(db=self)` | 13973-13975 | 整段留编排层；store 只供读 |
| `state` 传给 `insert_issue`/`advance_issue` | 13976、13992 | 留编排层（issues 不属 13 表） |

`content`/`registry`：这批函数现码本就不收（只有 promulgation 物化链收，15639、17130——0150 段职责，不在本拆分面）。常量群、校验器（`validate_affected_parties`、`project_execution_liability_parties`）均为纯函数/纯数据 import，不构成 state/content 依赖。∎

## 3. 原子顺序（同一调用方事务内）

通用不变式：**store 判定写先于段效果消费；两者同事务；段消费抛错 → 调用方最外层 atomic 整事务回滚（含 store 已写行），内存 state 由 `atomic_and_reload` 重载刷净（decree.py:2060-2100）。无半提交面**——现码所有调用点均 `commit=False` 挂调用方事务，拆后保持。

| 调用点 | 现码顺序（file:line） | 拆后顺序 | 回滚面 |
|---|---|---|---|
| due_review 正式复核（due_review.py:533-557） | ① `record_dossier_execution`(533-536) → ② `record_dossier_progress`(540-553) → ③ `apply_execution_joint_liability`(555-557, commit=False) → ④ fulfilled 时 `record_fulfillment_credit`(560-564) | ①②不动 → ③a `store.record_joint_liability` → ③b 段 `apply_joint_liability_effects` → ④ | 本次复核的调用方事务 |
| issues dossier_executions 适配器（issues.py:8195-8219） | ① 校验门闩 `validate_joint_liability_affected_parties`(8194) → ② `record_dossier_execution`(8195-8197) → ③ `merge_grant_reconciliation_into_execution_note`(8199-8201) → ④ `record_dossier_progress`(8204-8214) → ⑤ `apply_execution_joint_liability`(8217-8219, commit=False) | ①-④不动 → ⑤a store 判定写 → ⑤b 段消费 | extraction 外层事务 |
| breach_plea 坚持落地（breach_plea.py:704-768、791-933） | ① `restore_pay_order_override`(727-735) → ② `breach_decree_dossier`(738-741, commit=False) → ③ `_guofu_targets_of_0056` **回读 relation_edge_events**(745-747；查询 782-788 按 origin 前缀+turn) → ④ `reclaim_bundled_authorities`(750-754) → ⑤ `stop_origin_commitment_ticks`(756-761) → ⑥ 执行格 `record_dossier_execution`(853-856/877-880) → ⑦ 0079 辜负边去重写（消费 ③ 的结果，892-911) → ⑧ todo 消费（913-917) | ②a `store.record_breach_judgment` → ②b 段 `apply_breach_effects` → ③回读 → ④⑤⑥⑦⑧不动 | finalize 的调用方事务（commit 在 918-919 或更外层） |
| issues cancel 路径（issues.py:6032-6054） | ① `breach_decree_dossier`(6032-6035, commit=False) → ② `cost={}` 跳过 extractor cancel_cost（6036，防双罚）→ ③ `cancel_issue`(6045-6050) → ④ `state.clamp()`(6054) | ①a store 判定写 → ①b 段消费 → ②③④不动 | `external_transaction` 调用方事务（6049） |
| promulgation 强颁内联（db.py:15660-15711） | ① `_current_judge_affected_parties` 校验（15680；读本回合 Judge 行，该行由同批次先前 rejected verdict 落库、其 affected_parties_json 在 17157-17164 回填——**跨迭代约束：rejected verdict 必须先于 force verdict 处理**）→ ② stigma(15703-15706) → ③ `_apply_override_costs`(15707-15711, commit=False) | ①②不动 → ③a `store.record_override_judgment` → ③b 段 `apply_override_effects` | `apply_dossier_promulgation` 的 `atomic(self)`(15642) ⊂ `apply_dossier_verdicts` 的 `atomic_and_reload`(17130) |
| promulgation 中旨内联（db.py:17165-17172） | `_apply_override_costs(include_parties=False)`(17166-17172, commit=False) | ③a/③b 同上；`include_parties=False` 时 `party_deltas` 恒空，段侧只可能有 authority 一笔 | 同上 17130 事务 |
| backlash 触发（decree.py:2334） | 结算前半段事务内：`apply_fixed_period_flows`(2306) → … → `auto_trigger_seed_issues`(2320) → `trigger_supervision_countermeasures`(2322) → `trigger_commitment_backlashes`(2334, commit=False) → … → `save_state`(2355) + `collector.flush_to_db`(2356)；异常即 abort(2357-2359) | store 纯读（`list_backlash_terminal_dossiers` 等）→ 编排层逐候选 `_apply_metric_dict` + `insert_issue` + `advance_issue`；调用点位次不动 | settle 前半段事务 |

三条硬顺序约束（拆分时不得改变）：

1. **判定写先于效果消费**：cost_event 幂等行是「效果已落」的唯一事实源（UNIQUE 撞键即跳过对应效果），段消费只许消费 store 返回的实写成功项，不得自行重判。
2. **breach_plea 的边回读**：`_guofu_targets_of_0056`（breach_plea.py:782-788）读的是段消费刚写的 `relation_edge_events`——②b 必须先于 ③，段消费不得推迟到函数尾批处理。
3. **强颁证据链**：`_judge_affected_parties` 读同回合已落库的 Judge 行（16086-16091），rejected verdict 的 decision 行+affected_parties 回填必须先于 force verdict 的 override 判定写。

## 4. breach / apply_joint_liability 的 interface 定性

判词矛盾点：旧票面一面把 `breach_decree_dossier`/`apply_execution_joint_liability` 列为 store 公共动词，一面称结算消费留段适配器——而现码这两个函数同时写 13 表内（案卷行、cost_events）与 13 表外（metrics、factions、relation_edge_events），无法两全。

最终归属：

- **store 只暴露纯判定写**：`record_breach_judgment` / `record_joint_liability`（外加同源拆出的 `record_override_judgment`），签名零 state/content，效果意图以返回值交给段。旧名 `breach_decree_dossier`/`apply_execution_joint_liability`/`_apply_override_costs`/`_apply_authority_cost` **整体消亡、不留转发**（ADR 0151 决定 6 无 facade）。
- **段侧消费助手**：`apply_breach_effects` / `apply_joint_liability_effects` / `apply_override_effects`（§2.2），内容是现码 state.metrics/factions/classes/关系边四段原样搬迁，落调用点就近的段适配器层。

逐调用点够用性验证：

| 调用点 | 现码对返回值的使用 | 拆后是否够用 |
|---|---|---|
| due_review.py:555-557 | 不消费返回值（裸调用） | ✓ `record_joint_liability` + `apply_joint_liability_effects` 顺序替换即可 |
| issues.py:8217-8219 | 不消费返回值 | ✓ 同上 |
| breach_plea.py:738-747 | `breach_applied = bool(...)` 门控 `_guofu_targets_of_0056` 回读 | ✓ `fx is not None` 等价表达 `True`；`None` 等价 `False`（幂等撞键/状态不合格）；意图对象另供段消费 |
| issues.py:6032-6035 | 不消费返回值 | ✓ |
| tests/test_override_breach_costs_564.py:174/192/214/525-526、tests/test_breach_plea_623.py:428 | 断言 `is True`/`is False` | ✓ 属 ADR 0151 决定 10 同 PR 机械改径（断言改 None/not-None，语义不红即过） |

结论：拆清后 store 侧 = 案卷行 + `decree_cost_events` 幂等写 + 判定读（§2.1），段侧 = state.metrics/派系/阶级/关系边消费（§2.2），同一调用方事务内「先判定写、后效果消费」（§3），breach/连坐不再存在「既是 store 深入口又是段消费」的双重身份——旧混合动词消亡，判词矛盾闭合。
