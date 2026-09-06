# #657 施工契约（唯一真源）

> **权威声明**：本文件是 GitHub issue #657 的**唯一**规范施工与验收真源。  
> GitHub issue body 仅为元数据与非规范摘要指针；`docs/issue-657-ticket-amendment-r11.md` 为非规范历史指针桩。  
> **冲突以本文件为准**。实现 coding 轮只读本文件，不读 run 私材、不以线上半段协议为准。

法源：CLAUDE.md P1/P5/P6/P7；Accepted ADR 0035/0036/0037/0055/0070/0079/0092/0093；#647/#505/#1490。  
元数据镜像（非权威；GH 为元数据权威）：Parent=#647/#477；Blocked by=#656+#654（CLOSED∈main）；labels=enhancement, ready-for-agent。  
本契约对应之文本迁移轮：只改本文件 + GH #657 body + r11 指针桩；**零产品代码、零测试**。实现另开 coding 轮。

**CAS 归属（总则）**：`ensure_summon_scaffold_reenterable` 与一切 scaffold CAS 协议**仅**属于六动作之「召见 → 入召对流程」崩溃重入子接缝；不适用于依拟/发回改票/另旨·中旨/下部议·廷议/留中；不改变案头 C1 与其它五动作写口。

**终局验收 ID 闭集**：本文件可勾选验收项**仅**为 P1–P5、C1.1–C1.5、A1–A12、S1–S15（合计 37 条）。禁止无 ID 勾选项；禁止用「1–17」含混总称指代验收；禁止元指针「保留 r7 1–10」充独立验收条。

---

## §A 原六动作产品范围

批红案头＝0055 批红页同一页两类条目（打回件三选／急务件六动作，不建第二案头）；六动作 verdict 枚举入 DECISION 通道并各自接线：

1. **依拟**（差务落账、绑票拟所荐承办人）
2. **发回改票**（退回重拟一轮）
3. **另旨·中旨**（当回合 midzhi 案卷落库；频度／身份／离心见 **§C.8**）
4. **下部议·廷议**（议程 issue）
5. **留中**（惯性结算＋上疏者寒心）
6. **召见（入召对流程）**——完整技术义务见 §D；其中 scaffold CAS 见 §D.6，属召见子接缝

不批＝留中默认结算；每动作代价当回合落库（P1）。

**案头收敛注**：批红案头与 #473 家族 #614（收回守门+批红缘由呈现）同一物理面（0055 批红页）——先落者建面、后落者挂入条目类型，双方不得各建一套（不建第二案头）；非硬依赖，落地顺序不限。

**他动作写口（指针）**：

| 动作 | 写口 |
|---|---|
| follow/midzhi | §C ABI；幂等靠 C1+create 既有 source 键（**无** decree_dossiers.rescript_origin 列） |
| return_revise | C1 行锚（applied-revise 先于 options 校验） |
| deliberate | `insert_issue` + 既有 origin 去重 |
| hold | `write_credit_event(辜负)` |
| summon | §D |
| 编排入口 | public seam ①②③（§D.1）；HTTP/CLI 同契约 |

**行身份/窗账等已闭基线（不重开）**：

- `decision_key = "{kind}:{source_turn}:{idx}"`
- 授权＝行键 ∧ **当前** options 内 `draft_capability`（内容派生，禁位置 `d0`）
- **不**持久批红窗 id / 集合摘要 / 窗版本
- 仅急务入相：`resolve_directives` 既有 HITL atomic：`desk=backlog_pending_rescript ∪ this_turn_decisions`；非空→awaiting；双空直过
- 合并读模型：旧急务 `ORDER BY turn,idx` → 本月 decision；同缝
- 层 A 票拟候选 ≠ 层 B 六动作；禁 `option.verdict`
- 提交单缝：`POST /api/decree/resolve_decisions/stream` → 编排走 §D.1
- 中旨：`create_decree_dossiers(mode=midzhi, status=proposed)`；stigma 仅 `apply_dossier_promulgation`
- 改票史：`prior_options_json` append-only 全轮史
- 前端六钮 ∧ TestClient 六案真 HTTP
- 假 issue / 双写 / summon todo / 整批 drain：**已删，不复活**

---

## §B C1 逐行 choice 单真源（R5-F1 终局）

**不动**：行键、拒窗账、capability、合并读模、仅急务入相。

### B.1 混合提交时序（唯一序列 · 无批快照）

```
① Validate-all（内存，零写库）——见状态表「入门校验」
② 事务外 LLM（仅本批仍需新执行的行）
   return_revise → 改票 LLM
   deliberate → 站台意愿 LLM
   已匹配「本批已应用」（行上 choice 精确一致）的行不重跑 LLM
   失败 → 整批中止，零写库
③ 单 DB 事务（纯代码）
   a. 将本批每条**规范化 choice** 持久化到对应行 `choice_json`
      （急务五终态 + return_revise 均写；return_revise 的 choice 内必含
       `action=return_revise`、`applied_from_revision_round`、旧 `draft_capability`，
       供精确重放比对——全部在行上，不写 resolve_context 批副本）
   b. 对「尚未领域应用」的行：CAS + 唯一写口
      五动作成功 → status=decided
      return_revise → status 仍 pending，revision_round+=1，options 换新，
        prior_options_json append；CAS 含旧 revision_round
   c. 对「行上 choice 已与请求精确匹配且领域已应用」的行：跳过领域写与 CAS 覆写
   d. 任一条失败 → 回滚（含各行 choice 写入）
   e. 禁 save/clear_pending_decisions 触碰 rescript_draft
   f. **禁止** 任何 resolve_context 键承载本批 choices 集合
④ commit 后 → 既有 phase2（decision clear 纪律不变）
   phase2 全程成功结束时：
   - return_revise 行：清空其 choice_json（或写 `consumed_epoch` 使精确匹配失效）
     → 下一轮对新 options 的新动作是新鲜提交
   - 不存在 committed_rescript_batch 可清
```

**施工序注**：applied-revise 特例**必须先于**「capability ∈ 当前 options」校验，否则旧 revise 锚会被新 options 误判 stale。

### B.2 统一状态表（只认行事实）

**规范化**：服务端对每个 choice 做确定性 canonical JSON（键序固定、缺省填协议默认、`decision_key`/`action`/capability 必在）后再比、再存。

| 行库态 | 请求 choice | 行为 |
|---|---|---|
| `pending` 且无已应用 choice 证据 | 合法且键∈当前 desk | 入门通过 → ②必要时 LLM → ③写 choice + 领域写 |
| `pending` 同上 | 非法 / 未知键 / 重复键 / capability∉**当前** options | **整批拒**，零写 |
| `decided`，行 `choice_json` 规范后 == 请求 | 精确一致 | **已应用**：跳过领域写；计入本批满足 |
| `decided`，行 `choice_json` ≠ 请求 或 choice 空 | 不一致 / 无证据 | **整批拒**（禁静默 CAS0 当成功） |
| `pending` 且 choice 显示本轮 `return_revise` 已应用（`revision_round` 已 +1、prior 已 append、choice 含 revise 锚） | 请求 == 行上 revise choice | **已应用**：跳过 LLM/写口；计入满足 |
| `pending` 已新 options，choice 已在 phase2 清空 | 新动作对**当前** options 合法 | **新鲜**提交 |
| `pending` 已新 options，行上仍留旧 revise choice 且请求 ≠ 该 choice | 不一致重试 | **整批拒** |
| CAS 影响 0 | 仅当该行已满足「已应用 ∧ 请求精确匹配」 | 跳过；**否则整批拒** |
| desk 外键 / 非本窗应呈行 | — | **整批拒** |

**若仅靠行事实出现无法判定的状态**：实现前必须先提交可复现反例 + 缺失的最小行字段；**禁止**用另一份整批 choices 副本代替诊断。

### B.3 ready_replay（单谓词 · 无 batch_committed）

```
extracted_ready = resolve_context.extracted is not None
rows_applied   = 请求中每一行：库行 choice 规范后 == 请求 choice
                 且（status=decided ∨ 已应用 return_revise 锚）

if extracted_ready:
    # 既有 phase2 恢复：不覆写 decision 事件账；急务领域不重放；只续 phase2
elif rows_applied:
    # ③ 已 commit、phase2 未产出 extracted：跳过领域写与 choice 覆写；只开/续 phase2
else:
    # 新鲜批或混合未齐：走 ①②③；部分已应用行在 ③c 跳过
```

**P 与默认留中**（与恢复正交）：

- **新鲜批** desk P = 当前 pending 急务 ∪ 本月 pending decision（重算）
- P 内急务缺 action → **仅批红落印提交时** 机械 `hold`
- 重试批不重新默认留中；以各行已存 choice 为准
- 未入 desk 的跨月 pending 不留中

### B.4 终态

- 五动作成功：`status=decided`，`choice_json`＝规范化 choice
- `return_revise`：不终态删行；round+1 + 新 options + prior 全史；在飞期 choice 可查；phase2 成功后清 choice 锚
- restore 窗口内可读 traces；终态清理只走急务专缝

### B.5 C1 测试矩阵（规范说明 · 勾选正文见 §E.2）

- **C1.1 mixed batch**：急务 follow + decision 打回同批；③后杀进程（extracted 空）→ 同 body 重 POST → 无双写案卷/无双写 decision choice → phase2 完成；**且** `resolve_context` 无 choices 批副本键
- **C1.2 return_revise**：改票成功后 crash → 同 revise choice 重 POST → round 不双增；phase2 清行锚后，对新 options 的 follow 可新鲜提交
- **C1.3 不一致重试**：③后改 body 任一 choice → 整批 ValueError，库态不变
- **C1.4 CAS0 无 choice 证据**：status 非 pending 且 choice 不匹配/空 → 拒
- **C1.5 stale capability**：改票后旧 capability follow → 拒（新鲜批）

---

## §C 票拟/中旨 ABI 终局（**后出为准 → #1778**：原「七类」闭集已取消）

### C.1 闭集

> **后出为准 → #1778**：`RESCRIPT_ROUTABLE_ACTION_TYPES` 七类闭集及其各处闸已整体取消
> （owner 2026-09-06「1」）；choice/option.`action_type` 值域＝库级全集
> `DOSSIER_ACTION_TYPES`（ADR 0040 形状检查仍在）。emitted 闭集不动。

```
RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES = frozenset({
  "assignment", "military_order", "grant_allocation", "appointment",
  "dismiss_assignment",  # 罢免支
  "punishment", "authorization", "pacification",
})

# 库级全集 —— 禁止写成 DOSSIER_ACTION_TYPES = 七值
RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES ⊂ DOSSIER_ACTION_TYPES
```

| 规则 | 口径 |
|---|---|
| choice/option.`action_type` | ∈ **库级全集** `DOSSIER_ACTION_TYPES`（#1778 后出为准；罢免在 choice 上仍用 `appointment` + `appoint_action=罢免`） |
| create/apply 落库 `action_type` | ∈ **emitted**；任命→`appointment`；罢免→`dismiss_assignment` |
| 实现落点 | `ming_sim/decree_vocabulary.py`（或紧邻单真源模块） |

### C.2 成案前校验链（钉死函数名）

```
follow_draft / midzhi 领域写前（首写前）:
  payload0 = map_rescript_option_or_choice(...)   # 本表映射
  # 类特定显式闸（如 grant 非法 account、authorization holder 四键）在 normalize 前完成
  payload1 = db._normalize_directive_dossier_payload(
      payload0, content=..., current_turn=state.turn
  )   # 唯一结构边界；失败 → 整批拒，零案卷行
  ids = db.create_decree_dossiers(state, action_type=..., decree_text=...,
                                  target_kind=payload1["target_kind"],
                                  target_id=payload1["target_id"],
                                  payload=payload1, status=..., ...)
```

- **禁止** 引用 `_normalize_decree_dossier_payload`（仓内不存在）
- **禁止** 绕过 normalize 直接 `create_decree_dossiers`
- locality：`execution_pressure.resolve_dossier_region_ids` / `normalize_locality_scope`（8×3 矩阵；oracle 权威）。**后出为准 → #1778**：national 与 none 同为单行 `region_id=''`，不返回省列表

### C.3 公共 option 键（层 A · 缺一 shape 失败）

| 键 | 必填 | 值域 | 映入 payload |
|---|---|---|---|
| `label` | 是 | 非空 str | 不入机械字段；`decree_text` 回退源 |
| `hint` | 是 | 非空 str | 不入机械字段 |
| `action_type` | 是 | ∈ RESCRIPT_ROUTABLE | `action_type` |
| `assignee_name` | 键必须在 | str，可 `""` | 见类表 |
| `target_kind` | 是 | ∈ TARGET_KINDS 八值，**禁空** | 同名 |
| `target_id` | 是 | 非空 str | 同名 |
| `locality_scope` | 是 | `{national,single,none}`（中文别名经 normalize） | 同名 |
| `region_id` | 键必须在 | str，可 `""` | 可选冗余；oracle 权威 |
| `transaction_category` | 键必须在 | 见类表或 `""` | 同名 |
| `draft_capability` | 服务端写 | 派生闭集 canonical JSON + sha256 截断 | 不入 dossier payload |

### C.4 capability 派生闭集（全键 · 仅此表）

```
action_type,
label, hint,
assignee_name, name,
target_kind, target_id,
transaction_category,
locality_scope, region_id,
title, commitment_kind, stop_condition, end_turn, deadline_months,
station, due_turn, office,
grant_action, account, purpose, amount, cadence, execution_surface,
appoint_action, appointment_tenure,
punish_action,
privilege,
summon_target   # 仅 summon 行；差务 option 固定 ""
```

- 缺键按协议默认（`""`/0）参与派生
- 同 capability ⇒ 同机械载荷与同展示锚；上表任一有效差必须改变 capability
- 服务端回验：请求 capability 必须等于对当前 option/choice 结构化字段重算值

### C.5 name / canonical 同步（normalize 之后、create 之前）

| action_type | 同步规则 |
|---|---|
| appointment / dismiss_assignment | `name = target_id`（canonical 人物）；`_minister_name` 若用则同值 |
| grant_allocation（赏赉/发内帑/加衔/荫叙） | `name =` canonical `target_id` |
| punishment | `name =` canonical `target_id`（推荐同值保留） |
| authorization | 已由 mapper/normalize 写 `holder_id=name=assignee_id`；不得再写冲突名 |
| 其它 | 不要求 name |

### C.6 逐类终局

约定：option 列＝票拟候选；midzhi＝同名键从 **choice 显式**读（不读旧拟夹带）。

#### 1) assignment

| 键 | 必填条件 | 值域 / 映射 |
|---|---|---|
| `transaction_category` | 执行期 | `{钱粮,清丈,督赈,缉拿,缉捕,河工}` |
| 主办合法 A | 可选 | 显式 canonical assignee → named lead |
| 主办合法 B | 可选 | **仅**合法 category、**无**显式 assignee → duty route（`resolve_lead_executors`）；**不得**因缺 assignee 拒 |
| `target_kind`/`target_id` | 始终 | ∈ TARGET_KINDS / 非空 |
| `title` | 可选 | str≤80 |
| `commitment_kind` | 可选 | `{无,until_stop}` 默认 `无` |
| `stop_condition` | `until_stop` 时非空 | str |
| 期限 | 可选 | `deadline_months` 或绝对 `end_turn`；mapper **必须** `_assignment_absolute_end_turn(...)` 写绝对 `end_turn` |

- **负例**：`transaction_category` 与显式 assignee/主办**均缺**；`until_stop` 无 stop_condition
- **判后**：≥1 正例绝对 `end_turn` initiative + 承办人（**至少覆盖 duty route B**）

#### 2) military_order

| 键 | 必填条件 | 值域 |
|---|---|---|
| `assignee_name` | 执行期非空 | → assignee_id 且 name 同 canonical |
| `target_kind` | 始终 | **必须** `army` |
| `target_id` | 始终 | 已存在 `armies.id` |
| `station` | 可选 | 有 station＝调驻面，可不写 due |
| `deadline_months` / `due_turn` | 无 station 时至少一个有效未来 due | months 1..36 → `due_turn=current+months` |
| `office` / `transaction_category` | 可选 | |

- **判后**：① 调驻（station）② 限期（due_turn）各≥1 正例

#### 3) grant_allocation

**`_grant_target`**：

| grant_action | target_kind | target 来源 |
|---|---|---|
| 赏赉 / 发内帑 / 加衔 / 荫叙 | character | name or target_id |
| 项目经费 | issue | target_id or name or action |
| 协饷 | army | 真实 army id |
| 赈灾 | region 若 target_id 非空且 ≠ action 字面；否则 issue | target_id or name or action |

**account 处理序（mapper 内，normalize 前）**：

```
raw = strip(choice.account)
ga  = grant_action
if ga == "发内帑":
    account = "内库"
elif ga == "协饷":
    account = raw  # 必须显式为国库/内库；不得默认
elif ga in GRANT_MONEY_ACTIONS:
    if raw and raw not in {"国库", "内库"}:
        首写前拒
    elif raw in {"国库", "内库"}:
        account = raw
    else:
        account = "国库"   # 缺/空默认成功
else:
    account = ""  # honorific
```

| grant_action | amount | account | cadence | execution_surface |
|---|---|---|---|---|
| 加衔、荫叙 | 禁止要求 | `""` | `""` | **terminal** |
| 赏赉 | 正 int | ∈{国库,内库} 缺→国库 | 缺→一次性 | 默认 in_transit |
| 发内帑 | 正 int | **内库** | 缺→一次性 | 同上 |
| 赈灾、项目经费 | 正 int | 缺→国库 | 缺→一次性 | 同上 |
| 协饷 | 正 int | **显式输入**∈{国库,太仓,内库}；太仓→canonical 国库 | `purpose=补饷`、`target_kind=army`、真实 `target_id` 均须显式；一次性→强制 immediate；每月→建科目 | 见左 |

- **正例**须覆盖：普通金钱 grant 缺 account→国库；发内帑→内库；缺 cadence→一次性；honorific；协饷五字段显式且真 army（输入太仓 canonicalize 为国库）；项目经费→issue；赈灾 region/issue 分叉
- **负例**：缺 amount；赏赉显式非法 account；协饷缺 account/purpose/target_kind/target_id 或非 army；honorific 缺 name/target
- **判后**：honorific / 金钱扣库或月度科目 / 协饷补饷销欠 各≥1

#### 4) appointment

| 项 | 钉死 |
|---|---|
| `appoint_action` | ∈{任命,罢免} |
| 任命 | `office` **非空**；缺→拒；emitted `appointment` |
| 罢免 | `office` **可空**；目标须 **active 明臣**；emitted **`dismiss_assignment`** |
| 映射 | `payload['appoint_action']=…` **且** `payload['_office_action']=appoint_action` |
| canonical | `name=target_id`；`target_kind=character` |
| 禁 | 只写 appoint_action 不写 `_office_action`（缺省会默任命） |
| 验收 | 任命+非空 office→授官；任命缺 office→拒；罢免+active 明臣 office 空→去职；罢免非 active→拒；缺 `_office_action` 对照不得默任命 |

#### 5) punishment

| 键 | 必填 |
|---|---|
| `punish_action` | `punish_actions_effective()` 非空；禁 `无` |
| `name` / target | character；name＝canonical target_id |
| `amount` | **仅**罚俸：正 int；其它动作不得正 amount |

- 判后：普通处置人物效果；罚俸钱粮/俸禄；负：罚俸 amount≤0 首写前拒

#### 6) authorization（R9 终局）

mapper 在 normalize **之前**：

```
holder = first_nonempty(choice.holder_id, choice.assignee_id, choice.assignee, choice.name)
canonical = resolve_active_minister(content, db, holder)  # _find_existing_minister 同族
if not canonical:
    首写前拒
payload["holder_id"] = payload["assignee_id"] = payload["name"] = canonical
# 然后再 normalize（复核 privilege/scope）
```

| 项 | 口径 |
|---|---|
| privilege 缺/`""`/`"无"` | **成功** → canonical `便宜行事` |
| privilege ∈ `AUTHORITY_PRIVILEGE_SET` | `{尚方剑密授,便宜行事,专差督办,新机构专办}` 原样 |
| privilege 显式非闭集 | 首写前拒 |
| holder | 四键任一非空且可解析同一 active minister；**name-only 合法** |
| 负例缺 holder | 四键皆空，或无法解析 → 首写前拒 |
| scope | 仅由 normalize `scope=f"{target_kind}:{target_id}"`；不可派生则拒 |
| 判后 | `authority_changes`≥1；**集成全链** mapper→normalize→create→apply；禁半段单测冒充 |

#### 7) pacification

- `target_kind=character`；`_find_pacification_target`：active 内乱 ∧ stance∈{敌对,潜伏} ∧ leader=matched
- 判后：易主归明 + 反噬终局事实

### C.7 follow_draft / midzhi

| 项 | follow_draft | midzhi |
|---|---|---|
| 字段来源 | 所选 option | **choice 显式** |
| `executor_kind` | character（有 assignee 时） | 同 |
| `decree_text` | note 非空? note : label | choice.note 或 label |
| `payload.mode` | ordinary | midzhi |
| `status` | ordinary 默认 | **proposed** |

### C.8 dossier 幂等（废止 rescript_origin 列）＋中旨 D+（本文件唯一完整定义）

| 项 | 口径 |
|---|---|
| **删除** | `decree_dossiers.rescript_origin` 列；`UNIQUE(rescript_origin,region_id)`；create 按该键查补；对应测试 |
| **主幂等** | C1：同事务 choice＋完整 fan-out＋CAS；已 decided 精确匹配→跳过；不匹配→拒 |
| **fan-out** | create Plan→Validate-all→Write-once；既有 `(source,region_id)` 查补 |
| **验收** | ③ 后 crash / 同 body 重交 → **不增** dossier；每 region 恰一行（**后出为准 → #1778**：national 不拆省，「恰一行」＝全旨一行） |
| **可选 provenance** | payload 普通字段可写 decision_key；**不得**第二幂等真源/加列索引 |

#### 中旨 D+（本契约唯一完整位；ADR／GH 只 later-wins 指针，不复述整套）

**Owner 直支**（真源 GH #657 owner 评论 2026-08-25T00:47:48Z）：

1. 每次中旨仅在现有案卷以 `mode=midzhi` + **既有 decision identity** 持久化
2. 频度从案卷直接派生
3. **三不**：不建全局计数器、不向全部派系扇出、不猜受影响派系
4. 正式派系离心归 **M12** 按上下文落账

中旨**当下**可写：`mode=midzhi` 案卷行、decision identity、不依赖猜派的 STIGMA／污名标记、provisional 等既有非猜派机制。  
中旨**当下不可写**（施工义）：该派血债、相关价值派血债、中旨侧 `edict_overdraw`、频度进血债账、向派系扇出累加。  
正式逐派离心／频度反噬落派：**仅 M12**（指针；本契约不实现 M12）。旧 0011 系「中旨当回合立即撞派写 blood_debt／edict_overdraw／频度计数器」施工义 **later-wins 废止**，以本条为准。

**施工结论**（**非** owner 原话；保留行为、改归因——由 owner「既有 decision identity」+ 本契约 C1／本条 fan-out 结构推出，防重复计频；锚 §A 行身份基线 `decision_key = "{kind}:{source_turn}:{idx}"` 与上表 **主幂等**／**fan-out** 行）：

- fan-out **共用同一** decision identity
- 频度按案卷 **distinct identity** 计数
- 不得另建第二幂等真源／全局计数器／加列索引

### C.9 ABI 契约矩阵（A 组 · 规范说明 · 勾选正文见 §E.3）

| ID | 动作 | 首写前正 | 首写前负 | 判后 |
|---|---|---|---|---|
| A1 | assignment | 最小合法+绝对 end_turn；**duty 无 assignee** | category 与主办均缺；until_stop 无 stop | initiative 绝对 end_turn+承办人 |
| A2 | military_order | army+due 或 station | 非 army/假军/无 due 无 station | 调驻+限期 |
| A3 | grant honorific | 无 amount | 缺 name/target | honorific 效果 |
| A4 | grant 金钱 | amount；缺 account→国库；发内帑→内库 | 缺 amount；显式非法 account | 扣库/科目 |
| A5 | grant 项目/赈灾 | 按 _grant_target | 非法 target | kind 落对 |
| A6 | grant 协饷 | 真 army+补饷 | 非 army | 补饷/销欠 |
| A7 | appointment 任命 | `_office_action=任命`+非空 office | 缺 office/name | 授官 |
| A8 | appointment 罢免 | `_office_action=罢免`+dismiss_assignment+active 明臣 office 可空 | 非 active；缺 _office_action 对照 | 去职 |
| A9 | punishment×2 | 普通/罚俸+amount | 非法 action/罚俸无 amount | 两支判后 |
| A10 | authorization | 缺 privilege→便宜行事；**name-only 全链** | 非法 privilege；四键皆空；缺 scope | authority_changes |
| A11 | pacification | 合法内乱 leader | 非 leader | 易主终局 |
| A12 | 闭集/幂等/capability | choice∈`DOSSIER_ACTION_TYPES`（**后出为准 → #1778**，原「七类 routable」作废）；罢免 emitted dismiss；capability 扰动变键 | 无 DOSSIER=七值；无 rescript_origin 列；同 capability 两套 payload | 同 body 重交不增行 |

---

## §D 召见 → 入召对（唯一 CAS 归属面）

### D.0 原则

1. 批红 ③：行 `status=decided` + `choice_json={action:summon,summon_target,…}`（C1）
2. **同一次**提交成功领域写之后、**phase2 推月之前**，为每个未消费 summon **主动**走召对进入流
3. 消费事实（唯一）＝全局 ledger 行：`origin_ref=本 origin` ∧ `TAG_ENTER∈tags` ∧ `body.strip()` 非空 ∧ `body==` 本轮 registry join 所得 generator 非空返回值（P7）
4. **禁止**等玩家日后 attach；**禁止**「仅 decided choice」算召见完成
5. **禁止**整批 drain / 第二 registry / 顺序 `generate_open`→`generate_enter` 主路径 / todo / 假 issue
6. **CAS 仅属本召见子接缝**（见扉页）

**origin 公式**：

```
origin_ref = f"rescript_draft:{source_turn}:{idx}:summon:r{revision_round}"
# revision_round = 该行落 decided 时的 revision_round
```

**consumed / 未消费**：

```
consumed(origin) ≔ 存在 ledger 行:
  origin_ref=origin AND TAG_ENTER∈tags AND body.strip()非空
  AND body==已成功 persist 的 generator 返回值
未消费 ≔ decided summon 行对应 origin 不满足 consumed
```

- **空 body 行 ≠ 消费**（即便已占 origin_ref UNIQUE 槽）
- **禁止**「INSERT UNIQUE 冲突 ⇒ 返回已消费成功」

### D.1 Public orchestration seam（R7）

```
① 短写（持既有 per-session write_gate / write_cm）：
   - C1 事务：canonical choice + 完整领域写 + status/CAS
   - 对每个未消费 summon target（稳定序 source_turn, idx）：
       * 新鲜或复用垫位（D.4 / D.5）
       * 主线程 discover_open_enter_tasks / 组装 BeatInputs（零 LLM）
       * 对**全部** target 桶 start_open_enter —— 必须先全部 start，
         禁止 start-A→join-A→start-B
   - 释放写锁

② 无锁等待：
   - 逐桶 join_chat_turn_scene；**不得**持 write_gate
   - 多 target Future 时间重叠可观测

③ 短写（重新取得同一 write_gate）：
   - 逐 target 短事务 persist_chat_turn_scene：body=generator 原样写**原** entry_id
   - phase2 门闩（D.8）
   - 门闩通过后才续 phase2 / 推月 / ISSUED
```

| 层 | 必须 |
|---|---|
| session | 分段 API 或 `submit_decisions` **不在内部 join LLM**，由调用方按 ①②③ 编排 |
| `web_app` resolve stream | **禁止** `with write_gate: submit_decisions(...)` 覆盖 LLM join |
| CLI/其它入口 | 同一编排契约 |
| 锁 | 只复用既有 write_gate；禁第二锁 |

**批红侧**：预校验 `summon_target` 非空且 can_summon；③ 内仅 CAS→decided+choice；**不**在 C1 事务内写成功正文 ledger。

### D.2 空垫位 + scroll（P7）

| 规则 | 口径 |
|---|---|
| 垫位写入 | 只许持久 **`body=""`** 的 TAG_ENTER 账 + chat_turn(generating) + origin 绑定 |
| **禁止** | `open_night`/`summon_enter` 的 `body or 固定句` 默认分支作成功垫位；不得事后黑名单擦模板 |
| 读侧 | `read_night_scroll`：OPEN/ENTER 仅当 `body.strip()` 非空才投影；验收以 `/api/audience/scroll`（及 archive 同源）轮询为准 |
| ready | 唯一＝非空 generator 正文已 persist 到带 origin 的 TAG_ENTER 且 body==join 返回值 |
| 已在场 | 不得 `ensure_summon_enter` 早退 None 当消费；须仍落/复用独立 origin TAG_ENTER 再经 registry |
| 多 target | 独立 chat_turn+失败域；A 失败不回滚 B；不要求全成或全零；① 内先全部 start |

### D.3 origin_ref 最小扩展 + 冲突语义

```
ensure_column(story_ledger_entries, origin_ref, TEXT NOT NULL DEFAULT '')
CREATE UNIQUE INDEX IF NOT EXISTS idx_ledger_origin_ref
  ON story_ledger_entries(origin_ref) WHERE origin_ref != ''
```

| 事件 | 行为 |
|---|---|
| 按 origin 查无行 | 新鲜垫位路径（D.4） |
| 查得行且 body.strip() 非空 | consumed；跳过生成；不改写 body |
| 查得行且 body.strip() 空 | 未消费空垫位 → D.5 复用；**禁止**再 append 同 origin |
| 竞态 INSERT 撞 UNIQUE | 再 SELECT：非空→consumed；空→复用；**禁止**把冲突当成功 |
| 禁 | 新表、todo 伪 origin、第二 registry、恢复表、origin 只藏文案 |

### D.4 新鲜垫位 atomic 三步（R9-F2.6t）

```
# write_gate = 互斥编排锁，不是事务
from ming_sim.applier import atomic
with atomic(db):
    entry_id = append_ledger_entry(..., body="", tags=[TAG_ENTER,...],
                                   origin_ref=origin, ...)
    chat_turn_id = create_chat_turn(..., status=generating, night_id=...)
    UPDATE story_ledger_entries
       SET origin_chat_turn_id = chat_turn_id
     WHERE id = entry_id
# 退出 = 一次 commit；异常 = 全回滚
```

| 注入点 | 期望 |
|---|---|
| atomic 内、enter INSERT 后 / create_chat_turn 前崩溃 | 零孤儿 |
| atomic 内、create_chat_turn 后 / 回绑前崩溃 | 零孤儿 |
| atomic 提交后、② 前崩溃 | 恰 1 空 TAG_ENTER（已绑 chat_turn_id>0）+ 1 scaffold；重入复用，id 不变 |

对齐 `attach_chat_turn_to_night` 既有 atomic 形。

### D.5 复用分支骨架（R9-F2.6r′）

```
origin = f"rescript_draft:{source_turn}:{idx}:summon:r{revision_round}"
row = SELECT ... FROM story_ledger_entries WHERE origin_ref = origin

if row is None:
    with atomic(db):  # D.4
        空 TAG_ENTER + create_chat_turn + 回绑
elif body.strip():
    continue  # consumed
else:
    entry_id = row.id
    chat_turn_id = row.origin_chat_turn_id
    assert chat_turn_id > 0 且 chat_turns 存在且 night 一致
    ensure_summon_scaffold_reenterable(db, chat_turn_id, entry_id, origin, night_id)
    # D.6；失败响亮；禁止静默新建第二轮

# 汇合（均在 CAS/新鲜 atomic 已提交之后）：
discover_open_enter_tasks(..., chat_turn_id)  # 命中同一 entry_id
session._scene_registry.start_open_enter(..., chat_turn_id=chat_turn_id)
# 全部 target start 完才释放 write_gate
```

② 锁外 join；③ persist 写原 entry_id → 非空 body → 门闩。

### D.6 scaffold 可重入 CAS（R10-F2.6s）

**CAS 归属**：本函数与协议仅属「召见 → 入召对」崩溃重入子接缝（见扉页总则）。

**选定做法（判词唯一路径 · 最小）**：复用路径对 `failed` scaffold 做 **一次短 `atomic(db)` 内完整复核 + 严格 CAS + 退出即提交**；**不**改 reconcile；**不**新建 reopen API；**不**恢复表；**不**第二 chat_turn。

#### D.6.1 调用位置（编排边界）

```
# ① 内、持 write_gate：
#   - 新鲜垫位：R9-F2.6t 自己的 atomic（三步）——不改
#   - 空垫位复用：先读 origin 命中空行，再：
ensure_summon_scaffold_reenterable(db, chat_turn_id, entry_id, origin, night_id)
#   ↑ 函数返回时 CAS（若发生）**必须已提交**
#   然后才允许（均在 CAS 事务外）：
discover_open_enter_tasks(..., chat_turn_id)
session._scene_registry.start_open_enter(..., chat_turn_id=chat_turn_id)
# ② 锁外 join；③ persist 原 entry_id
# 硬禁：discover / start / join / generator / persist 进入 ensure_* 的 atomic 内
```

#### D.6.2 严格协议（伪码 · 施工必遵）

```
ensure_summon_scaffold_reenterable(db, chat_turn_id, entry_id, origin, expected_night_id):
  """空垫位复用唯一状态入口。失败一律 raise（响亮）；禁止静默新建第二轮。"""
  from ming_sim.applier import atomic

  with atomic(db):   # 短事务：期内复核 + 可选 CAS；退出 = 一次真 commit
      # —— 以下全部在同一 atomic 内重新 SELECT，禁止信任事务前快照 ——

      ct = SELECT id, status, user_message_id, minister_message_id, night_id
           FROM chat_turns WHERE id = ?  -- chat_turn_id
      if ct is None:
          raise  # 响亮失败

      le = SELECT id, body, origin_ref, origin_chat_turn_id, night_id, tags...
           FROM story_ledger_entries WHERE id = ?  -- entry_id
      if le is None:
          raise

      # 事务内完整谓词（全部满足才允许 no-op 或 CAS）
      assert le.origin_ref == origin
      assert TAG_ENTER ∈ le.tags          # 与 discover 同族判定
      assert le.body.strip() == ""        # 未消费
      assert int(le.origin_chat_turn_id) == int(chat_turn_id)
      assert int(ct.night_id) == int(le.night_id) == int(expected_night_id)
      assert ct.user_message_id IS NULL
      assert ct.minister_message_id IS NULL OR ct.minister_message_id == 0

      if ct.status == 'generating':
          return  # 同进程、reconcile 未跑；谓词已在事务内复核；无写

      if ct.status == 'failed':
          cur = UPDATE chat_turns
                SET status = 'generating'
              WHERE id = ?
                AND status = 'failed'
                AND user_message_id IS NULL
                AND (minister_message_id IS NULL OR minister_message_id = 0)
              -- 绑定 chat_turn_id
          if cur.rowcount != 1:
              raise  # 竞态 / 谓词漂移 → 响亮失败，不得新建第二轮
          return

      if ct.status == 'interrupted':
          # interrupted 语义上必有 user_message；无问话 scaffold 不应落入
          raise  # 响亮失败；不得调用 reopen_interrupted_chat_turn_for_retry

      # active / undone / 其它终态
      raise

  # atomic 正常退出 ⇒ 已 commit
  # 调用方此后的 discover/start/join 所见必为已提交状态
```

#### D.6.3 钉死规则表

| 规则 | 口径 |
|---|---|
| **唯一 CAS 路径** | `failed → generating`，且仅当事务内全部 chat_turn + ledger + night 谓词成立 |
| **事务边界** | 复核 SELECT + CAS UPDATE **同属一个** `with atomic(db):`；退出即提交；异常全回滚 |
| **rowcount** | `!= 1` → raise；禁止当成功；禁止回退新建 chat_turn / DELETE 空垫位再 INSERT |
| **generating no-op** | 仍须在同一 atomic 内跑完全部谓词复核；只是不写 status |
| **reconcile** | **零改动**。无问话在飞 scaffold 启动后仍标 `failed`；有问话仍标 `interrupted`。**删除** r9「可选跳过 scaffold」全文，无二选一、无并存等价路径 |
| **不调用** | `reopen_interrupted_chat_turn_for_retry`（谓词不匹配 scaffold） |
| **不修改** | reconcile 有问话→interrupted；reopen 仅 interrupted→generating；#505 恢复提示链 |
| **事务外** | `discover_open_enter_tasks` / `start_open_enter` / join / generator / `persist_chat_turn_scene` **禁止**进入该 atomic |
| **硬禁** | 因 failed 而 `create_chat_turn` 第二轮；换 entry_id；新 registry/恢复表；把 CAS 写拖到 join；信任事务前只读快照做 CAS |

#### D.6.4 与新鲜垫位 atomic 的关系

| 路径 | 事务 | 内容 |
|---|---|---|
| 新鲜垫位 | R9-F2.6t 自己的 `atomic` | INSERT 空 TAG_ENTER + create_chat_turn + 回绑 origin |
| 空垫位复用 | R10-F2.6s **另一**短 `atomic` | 仅复核 + 可选 status CAS；**不**再 INSERT |
| 二者 | 均在 write_gate 内、均在 discover/start **之前**结束并提交 | 不得合并成跨 join 的长事务 |

### D.7 断点表（R10-F2.6g″）

| 断点 | 行为 |
|---|---|
| ③ 后、① 前 crash | choice 已 decided；重试新鲜 ①（R9-F2.6t atomic 三步） |
| **① 新鲜 atomic 内任一步** | 全回滚；零孤儿；重试走新鲜路径 |
| **① 新鲜 atomic 提交后、② 前（进程级）** | DB：空 TAG_ENTER+已绑 origin + scaffold（generating）。重启 → **未改动的** reconcile → 无问话 → **failed**。重试：C1 跳过已应用；按 origin 命中空行 → **R10-F2.6s 短 atomic 内复核+CAS** failed→generating（退出已提交）→ 同 ledger id + 同 chat_turn id → **事务外** discover/start；不增行；③ 写原行 |
| **CAS atomic 内崩溃** | 回滚；status 仍 failed；空垫位仍在；重试再走完整 ensure_* |
| **CAS 成功提交后、start 前再 crash** | DB 已是 generating + 空 TAG_ENTER；再启动 → reconcile **再**标 failed → 再 CAS → 不增行 |
| ② 中 / ② 后 ③ 前 | 空行未消费；复用+CAS（若需）再 join；以最终非空 body 为准 |
| persist 成功后 | consumed；重试 skip |
| 已在场夜 | 仍落/复用该 origin 的 TAG_ENTER |

**删除**任何「reconcile 跳过 scaffold 故保持 generating、可不走 CAS」的断点叙述。

### D.8 phase2 门闩

```
unconsumed = decided summon 行中仍无合法消费事实者
if unconsumed:
    响亮失败（明确 target/origin）
    保留：行 decided+choice、已成功 origin 账、resolve_context 可续
    不：next_period、不假装 phase2 完成、不 clear 未消费 choice
```

重试：同 body → C1 跳过已应用 → 仅 unconsumed 再跑 ①②③ → 门闩再检。  
generator 失败：该 target 零成功消费；空垫位不可投影；**不得**模板垫位过门闩。

### D.9 P7 正文

| 规则 | 口径 |
|---|---|
| 合法缝 | 主线程 BeatInputs → registry Future 内 `run_beat_generator` → 返回值原样 persist |
| 禁止成功旁路 | generator is None / 空白 / 异常 → 不得成功消费；不得固定模板充成功 |
| Future 重叠 | 全部 start 后、任一 join 完成前，多 target（及同桶 open/enter）in-flight 重叠 |

---

## §E 验收全表

> **编号闭集**：本节可勾选项 **仅** P1–P5、C1.1–C1.5、A1–A12、S1–S15（合计 **37**）。  
> 每个可勾选项恰有一个 ID；每个 ID 恰有一份正文。禁止无 ID 勾选项；禁止再并列无号的 CAS/#505/HTTP 条。

### E.0 旧编号映射（正文内副本 · 与迁移方案 §2.2 字节一致）

| 旧号 | 来源标签 | 处置 | 终局 ID | 终局标题 |
|---|---|---|---|---|
| 1 | r7 | **保留** | **S1** | 当回合自动进入 |
| 2 | r7 | **保留** | **S2** | 编排锁边界 |
| 3 | r7 | **保留** | **S3** | 多 target 真并行 |
| 4 | r7 | **保留** | **S4** | P7 垫位不可见 |
| 5 | r7 | **保留** | **S5** | phase2 不越过欠消费 |
| 6 | r7 | **保留** | **S6** | 已在场 |
| 7 | r7 | **保留** | **S7** | 失败域 |
| 8 | r7 | **保留** | **S8** | 同 origin 至多一条 |
| 9 | r7 | **保留** | **S9** | 无 todo/第二 registry/顺序 generate |
| 10 | r7 | **保留** | **S10** | 其余五动作 HTTP + 前端六钮 + #1490 |
| 11 | r9/r10/r11 | **保留** | **S11** | atomic 三边界 fault-inject |
| 12 | r10「真实进程恢复链」 | **合并** → 同库三轮 | **S12** | 同库三轮行为矩阵（含原 12 终点与 #505 不回归） |
| 13 | r10/r11 | **保留** | **S13** | CAS 后再崩（含无限重入不增行） |
| 14 | r10/r11 | **保留** | **S14** | CAS 提交可观察（独立连接） |
| 15 | r10「#505 不回归」 | **合并** → S12；其中源码路径/`inspect`/`getsource`/路径/子串/分支扫描断言 | **→S12**；源码断言 **废止** | （无独立终局号） |
| 16 | r8-12 / r10-16 / r11-16 | **保留** | **S15** | 空冲突非成功 |
| 17 | r10/r11「保留 r7 条 1–10」 | **废止为独立验收条**（纯元指针，零增量义务）；实质已由 S1–S10 承担 | **无** | — |

终局召见行为编号 **仅 S1–S15**；**无**独立条 17；旧 12+15→S12；旧 16→S15。

### E.1 产品 AC（P1–P5）

- [ ] **P1** 同一批红页呈现两类条目，web 真实操作路径可用（六动作各可点、留中默认）
- [ ] **P2** 六动作各自后果当回合落库（依拟绑人吃带宽/改票退回/中旨入账/廷议立 issue/留中惯性/召见入召对）
- [ ] **P3** 用例②：同一条急务六种批法各见不同后果（e2e）
- [ ] **P4** 依拟夹带生效：票拟荐的承办人/钱路照单落账（代理人问题可被玩家事后察觉）
- [ ] **P5** restore 接续：未批急务下月仍在案头或已按留中结算

### E.2 C1 矩阵（C1.1–C1.5）

- [ ] **C1.1 mixed batch**：急务 follow + decision 打回同批；③后杀进程（extracted 空）→ 同 body 重 POST → 无双写案卷/无双写 decision choice → phase2 完成；**且** `resolve_context` 无 choices 批副本键；无 `committed_rescript_batch`；applied-revise 先于 options 校验
- [ ] **C1.2 return_revise**：改票成功后 crash → 同 revise choice 重 POST → round 不双增；phase2 清行锚后，对新 options 的 follow 可新鲜提交
- [ ] **C1.3 不一致重试**：③后改 body 任一 choice → 整批 ValueError，库态不变
- [ ] **C1.4 CAS0 无 choice 证据**：status 非 pending 且 choice 不匹配/空 → 拒（禁静默 CAS0 当成功）
- [ ] **C1.5 stale capability**：改票后旧 capability follow → 拒（新鲜批）

### E.3 ABI 契约矩阵（A1–A12）

- [ ] **A1 assignment**：首写前正＝最小合法+绝对 end_turn 且 **duty 无 assignee** 可过；负＝category 与主办均缺、until_stop 无 stop；判后＝initiative 绝对 end_turn+承办人（至少覆盖 duty route B）
- [ ] **A2 military_order**：正＝army+due 或 station；负＝非 army/假军/无 due 无 station；判后＝调驻+限期各≥1
- [ ] **A3 grant honorific**：正＝无 amount 的加衔/荫叙；负＝缺 name/target；判后＝honorific 效果
- [ ] **A4 grant 金钱**：正＝amount；缺 account→国库；发内帑→内库；负＝缺 amount、显式非法 account；判后＝扣库/科目
- [ ] **A5 grant 项目/赈灾**：正＝按 `_grant_target`；负＝非法 target；判后＝kind 落对
- [ ] **A6 grant 协饷**：正＝真 army+补饷；负＝非 army；判后＝补饷/销欠
- [ ] **A7 appointment 任命**：正＝`_office_action=任命`+非空 office；负＝缺 office/name；判后＝授官
- [ ] **A8 appointment 罢免**：正＝`_office_action=罢免`+emitted `dismiss_assignment`+active 明臣 office 可空；负＝非 active、缺 `_office_action` 对照不得默任命；判后＝去职
- [ ] **A9 punishment×2**：正＝普通处置 / 罚俸+正 amount；负＝非法 action、罚俸无 amount 或 amount≤0；判后＝两支人物/钱粮效果
- [ ] **A10 authorization**：正＝缺 privilege→便宜行事、**name-only 全链** mapper→normalize→create→apply；负＝非法 privilege、四键皆空、缺 scope；判后＝`authority_changes`≥1
- [ ] **A11 pacification**：正＝合法内乱 leader；负＝非 leader；判后＝易主归明终局
- [ ] **A12 闭集/幂等/capability**（**后出为准 → #1778**：七类 routable 项作废，改咬 choice∈`DOSSIER_ACTION_TYPES`）：正＝choice∈库级全集、罢免 emitted dismiss、capability 扰动变键；负＝无 `DOSSIER_ACTION_TYPES=七值`、无 `rescript_origin` 列、同 capability 不得两套 payload；判后＝同 body 重交不增 dossier 行

### E.4 召见行为（S1–S15）

- [ ] **S1 当回合自动进入**：HTTP summon 提交后无需再 attach，即存在全局 `origin_ref`+TAG_ENTER，且 `body==generator` 非空原文
- [ ] **S2 编排锁边界**：① 与 ③ 持写锁；② join 期间写锁**必须**释放；不得整段 gate 覆盖 join
- [ ] **S3 多 target 真并行**：同批 ≥2 summon → 全部 start 后 join 前 Future 时间重叠；禁止串行 start-join
- [ ] **S4 P7 垫位不可见**：generator 阻塞/失败/崩溃期间轮询 scroll——不出现空入口、人物锚或固定开夜/入殿句；成功后只出现原样 LLM 正文
- [ ] **S5 phase2 不越过欠消费**：注入 generator 失败 → 月不推、非 ISSUED、choice 仍在；修 generator 后重 POST 同 body → 消费成功且月可推
- [ ] **S6 已在场**：仍恰一条 origin 消费账 + 正文原样
- [ ] **S7 失败域**：单 target 失败不影响另一 target 已消费 origin
- [ ] **S8 同 origin 至多一条**（ledger UNIQUE；且至多一条非空消费正文）
- [ ] **S9 无** todo/假 issue/整批 drain API/第二 registry/顺序 generate 主路径
- [ ] **S10 其余五动作 HTTP + 前端六钮 + #1490**：依拟/改票/中旨/廷议/留中 各至少一案真 HTTP（TestClient）；前端六钮可点；#1490 不回归。召见 HTTP 主路径由 S1 覆盖，不在本条重复建召唤成功夹具

- [ ] **S11 atomic 三边界 fault-inject**（新鲜垫位 R9-F2.6t）：  
  | 注入点 | 期望 |  
  |---|---|  
  | atomic 内、enter INSERT 后 / create_chat_turn 前崩溃 | 零孤儿 |  
  | atomic 内、create_chat_turn 后 / 回绑前崩溃 | 零孤儿 |  
  | atomic 提交后、② 前崩溃 | 恰 1 空 TAG_ENTER（已绑 `chat_turn_id>0`）+ 1 scaffold；重入复用，id 不变 |  
  事务内崩溃均零孤儿；提交后复用原 id。本条验证 atomic 回滚边界，不因与 S12 合并夹具而删除。

- [ ] **S12 同库三轮行为矩阵（合并旧 12 与旧 15；含 #505 不回归与进程重入主路径）**：  
  单一聚焦同库夹具，一次建库放入三者（均 `generating` 在飞）：  

  | 行 | 构造 |
  |---|---|
  | **S** summon scaffold | 空 origin TAG_ENTER 已绑 + 无 `user_message_id` / 无 minister 消息（R10-F2.6t 提交后形态） |
  | **U** 不相关无问话轮 | 非本 origin 空垫位；普通 generating 且无 `user_message_id`（#505 orphan 同类） |
  | **Q** 有问话在飞轮 | `user_message_id` 已链、回话未落（#505 半途 kill 同类） |

  **步骤（单次真实 reconcile，禁止只 `del registry` 冒充）**：  
  1. 真正调用 `reconcile_interrupted_chat_turns()`（或等价 `__init__` / `_rebuild_session`）  
  2. 断言状态：**S=`failed`，U=`failed`，Q=`interrupted`**；ledger 行数/id 相对 reconcile 前不删账  
  3. **仅**对 S 调用 `ensure_summon_scaffold_reenterable`（§D.6）→ 断言 **仅 S=`generating`**；U 仍 `failed`；Q 仍 `interrupted`；同 origin ledger 行数=1、id 不变；chat_turns 不增  
  4. 对 Q 走既有 `reopen_interrupted_chat_turn_for_retry` → Q→`generating`；问话消息行仍在；账不删；**U 仍 `failed`**（不被 scaffold CAS、不被 reopen 误拨）  
  5. S 路径继续：**事务外** discover/start；最终非空 body；phase2 可过  

  **进程重入主路径（并入本条，不再单列无 ID 勾选）**：① 后真实 `reconcile_interrupted_chat_turns`（**不**收窄、scaffold→failed）→ **单短 `atomic` 内**完整复核 chat_turn+ledger+night 谓词并 CAS `failed→generating`（退出即提交，`rowcount!=1` 响亮失败）→ **事务外** discover/start/join → 同 id 完成 persist；空 body≠consumed；无第二 chat_turn/恢复表/第二 registry。不改 reconcile/reopen 生产语义。  

  **硬禁（验收层）**：`inspect`/`getsource`、文件路径、源码子串、分支名/「特判」字符串扫描；不得以源码形态代替上表状态与行数断言。  
  **明确删除**：r10 第15条「断言 reconcile 源码路径无 scaffold 特判分支」及任何等价源码路径/字符串断言。

- [ ] **S13 CAS 后再崩（含无限重入不增行）**：可与 S12 共享建库/S 行状态；在 `ensure_*` 提交后、start 前再 crash / 再 reconcile+重试 → 仍同 ledger id + 同 chat_turn id、不增行、可完成 persist。CAS 后再崩仍可无限重入不增行。本条验证 CAS 后窗口，不因与 S12 合并夹具而删除。

- [ ] **S14 CAS 提交可观察（独立连接）**：可与 S12 共享建库；`ensure_*` 返回后、**join 之前**，用 **独立 SQLite 连接**（非同一 `db.conn`）读 S：`status=='generating'` 且 `user_message_id IS NULL`。本条验证提交可见性，不因与 S12 合并夹具而删除。

- [ ] **S15 空冲突非成功**：空 body 行 ≠ 消费（即便已占 `origin_ref` UNIQUE 槽）；竞态 INSERT 撞 UNIQUE → 再 SELECT：非空→consumed；空→复用；**禁止**「INSERT UNIQUE 冲突 ⇒ 返回已消费成功」

### E.5 What to build 召见句（规范叙述 · 非独立勾选项）

> **召见**：决定真源＝行 choice；提交成功后当回合按 §D.1 ①短写（D.4 atomic 或 D.5 复用+D.6 CAS）→ 全部 start → ②锁外 join → ③ persist 原行 + 门闩。消费＝全局 TAG_ENTER+origin 且 body==generator 非空。空 body≠consumed。已在场仍落/复用独立 origin 账。  
> **崩溃重入状态机**：进程启动必经未改动的 `reconcile_interrupted_chat_turns`；无问话 summon scaffold → failed。复用路径在一次短 `atomic(db)` 内重新复核后 CAS 回 generating，退出即提交；discover/start/join 仅在事务外。禁止改 reconcile 跳过 scaffold；禁止新建 chat_turn/恢复表/第二 registry；CAS 后 start 前再崩仍不增行。验收含：独立连接观察已提交 CAS（**S14**）；**同库三轮行为矩阵**（**S12**）；CAS 后再崩（**S13**）；**不以源码路径或字符串扫描代替状态与行数断言**。

---

## §F 废止表（闭集 · 防回潮）

committed_rescript_batch / 批 choices 副本；整批 drain / 整批零账；summon todo；第二 registry / 恢复表 / 第二 chat_turn；新 reopen API 族；`decree_dossiers.rescript_origin` 列与 UNIQUE 与查补；reconcile 可选跳过 scaffold / 与 CAS 二选一并存；源码路径/`inspect`/`getsource`/分支名扫描验收；UNIQUE 冲突或空 body ⇒ 已消费成功；write_gate＝事务；只毁 registry＝进程崩溃；`DOSSIER_ACTION_TYPES=七值`；推迟 attach 消费；顺序 generate 主路径；name-only 直塞 normalize 未映射；CAS 事务前只读当真理；CAS 与 join 同事务；「票面正文以线上为准」双真源；元指针「保留 r7 1–10」充独立验收第 17 条；持久批红窗/集合摘要；假 issue；禁止模板集平行断言代替 body==generator；CAS0 无证据成功；§E 编号外重复勾选项（含无 ID 的「召见进程重入 / CAS 提交可观察 / #505 不回归 / HTTP 六案」并列条）。

---

## §G OOS

御笔手敕/M12/扩 RESCRIPT routable 至全 DOSSIER（**已由 #1778 落地**）/改 ADR 0036·0037 本文/改 #505 有问话语义/due_review·urge/持久批红窗/dossier 第二幂等索引/实现 coding 轮（另开，严格按本契约）。

---

## §H 双向对表（apply 落盘后勾核）

| 项 | GH body | Canonical | 一致？ |
|---|---|---|---|
| Parent | #647/#477 | 镜像 | 是（GH 权威元数据） |
| Blocked by | #656/#654 CLOSED | 镜像 | 是 |
| Labels | enhancement, ready-for-agent | 镜像 | 是 |
| What to build 六动作 | 可读摘要+指针 | §A 全文 | 摘要⊆全文 |
| 召见 CAS | **无规范半段**（仅指针） | §D.4–D.7 唯一全文 | 是 |
| AC | **零 checkbox**；仅指针→§E | §E 全表（P1–P5 / C1.1–C1.5 / A1–A12 / S1–S15＝37） | 是 |
| 旧号映射 | 不出现含混总称 | 映射表 E.0 + S1–S15 | 是 |
| 编号外勾选项 | 不出现 | 不出现 | 是 |
| OOS | 可不列或指针 | §F/G | 是 |
| 真源句 | 指向 canonical | 自称为唯一真源 | 是 |
| r11 文件 | 不承载协议 | 非规范指针桩（APPENDIX B） | 是 |
