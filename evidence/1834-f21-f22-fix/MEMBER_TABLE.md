# 1834 F21/F22 成员表（可审；非原始 grep 堆叠）

权威导航：本文件 + `RECEIPT.md`。
枚举命令与命中计数：`ENUM_CMDS.txt`。
上轮伪变异：`MUTATION_FAKE_REVOKED.txt`（撤销，不作结清证据）。
冻结失败记录（不改写）：`evidence/1834-f16-*` / `evidence/1834-f18-*` 内 REVOKED_*。

谓词覆盖（相对上轮纠正）：生产 globs 含 `main.py`/`launcher.py`/`spike_settle_tick.py`；前端含 `.replace`/`.slice`/`.substring`/`.split`/`.join`；含带参 `strip/trim`；自由字段赋值形再扫。未新建自动分类层。

---

## F21 自由字段搬运链改写

类定义：沿真实输入、写入、读取、物化与供料追踪取值，删除自由字段上的裁字；判空用副本；机器键归一保留。

### FIX（本类成立并已修）

| 组 | 具体引用 | 处置 | 理由 |
|---|---|---|---|
| military_order 人读 station 写入 | `ming_sim/rescript_actions.py` `map_rescript_option_or_choice` military_order 支路：`station` 判空用 `.strip()` 副本，`payload["station"]=station` 保原文 | FIX（4bc6994 + 本轮复核仍在） | 人读驻地曾 strip 后写入 payload |
| military_order 人读 station 物化 | `ming_sim/db.py` `_apply_military_order_station_effect`：`dest=str(station or "")`；`station_region` 仍 strip | FIX | 物化曾 `dest=strip(station)` 改主表 |
| highlights 读取 | `ming_sim/db.py` `_parse_highlights_json`：`item.strip()` 仅判空，`out.append(item)` | FIX | 读取曾 `out.append(item.strip())` |
| highlights 写入 | `ming_sim/db.py` `set_message_highlights`；`ming_sim/highlight_judge.py` `parse_highlight_judge_output` | FIX（既有 F16 保留） | 短语写出保原文；判空副本 |

### KEEP（逐组语义；摘录不得冒充本组）

| 组 | 具体引用（代表+同责） | 处置 | 理由 |
|---|---|---|---|
| station_region 机器键 | `db.py` army 写入 `station_region=...strip()`；`content.py` seed | KEEP | 结构化驻地键归一，非人读 station |
| office / 职衔匹配键 | `rescript_actions.py` `assignee_name/region_id.strip`；`office_rank.py`；`appointment_tenure.py`；`matching.py` | KEEP | 身份/职衔匹配机器键 |
| decision label 选项键 | `rescript_actions.py:472` `label=...strip()` 后对 `bind_decision_options`；`note` 保原文 | KEEP | label 是选项身份键；自由批注在 note |
| decree_text 判空回退 | `rescript_actions.py:704` `note_raw if note_raw.strip() else label_raw`；`:1183` body/title | KEEP | 判空副本；非空走原文 |
| staged criterion/origin | `staged_commitment.py` 段写入/到期扫描：判空副本，字段存原文 | KEEP | F16 已保原文；JSON envelope strip 非自由字段值 |
| fiscal/event reason 枚举键 | `flows.py:1591` `POPULATION_TRANSFER_REASONS.get(reason)`；`issues.py` reason.lower 匹配 | KEEP | 枚举/矩阵键，非自由奏报正文落库改写 |
| origin_ref 机器键 | `audience_night.py`/`breach_plea.py`/`entities/*/store.py`/`due_review.py`/`credit_events.py` origin_ref strip | KEEP | 引用键归一；`textual_fact` body 走 `sanitize_sqlite_text` 不 strip |
| responsible_bodies 机关名 | `action_materialize.py` `parse_responsible_bodies` 分割后 strip | KEEP | 机关名身份键；非奏对自由正文 |
| matter_title 判空回退 | `action_materialize.py:1519/:1742` `title_raw if title_raw.strip() else tid_raw` | KEEP | 非空保 title_raw |
| settlement 候选标题绑 id | `settlement_payload.py:192/:213` title strip 仅用于候选 id 重绑 | KEEP | 匹配键；不改材料目录自由正文 |
| materials 路径/状态 | `materials.py:326` root 路径；`:2289` status；`:506/:591` 判空后包装 | KEEP | 路径/状态键；`:591` 呈送加后缀非裁字，DOM/供料仍以 body 原文为核 |
| highlight JSON 外壳 | `highlight_judge.py:26` 整段 LLM 输出 strip 再 parse JSON；短语保原文 | KEEP | 外壳判空；成员短语不裁 |
| 口令/消息局部副本 | `audience_night.py` `recognize_*` `message.strip()`；`useChatActions.ts:151` `message.trim()` 发送门 | KEEP | 局部匹配/门闩，不回写存储正文 |
| 前端展示切片 | `web/src/highlights.ts` `slice` 分段高亮；`historyModal.tsx` attendant trim 仅判空、DOM 写原文 | KEEP | 不改存储短语/递话原文 |
| SSE/错误包装 | `api.ts`/`settleStream.ts` event 行 trim；HTTP 错误 `message.trim()` 抛错 | KEEP | 协议行/错误包装，非自由字段落库 |
| format.splitReportItems | `web/src/format.ts:124–131` | KEEP | **零调用**；非生产搬运链；不泛删工具函数 |
| 根 launcher | `main.py`/`launcher.py`/`spike_settle_tick.py` 本轮谓词无自由字段赋值裁字落库命中 | KEEP | 无本类成员 |
| 带参 strip | `ENUM_CMDS.txt` F21 CMD2 命中均为机器键/空白字符集参数，无自由字段值裁字 | KEEP | 见命令输出 |
| 旧错误 KEEP 撤销（导航） | 冻结 `f16_disposition_member_locs.tsv` 将 station/highlight 标 `emptiness_predicate_only` | REVOKED_AS_AUTHORITY | 冻结表不改写；**不得**再作现行全清证据；以本表+真实入口为准 |

---

## F22 退役旧接缝残留

类定义：按现行职责与真实消费者清理已作废结构及专属参数、透传、类型和测试；保留在用共享能力与冻结失败记录。语义判断退役接缝，**禁止**泛删无调用 API。

### DELETE

| 成员 | 消费者证明 | 处置 | 理由 |
|---|---|---|---|
| `_target_active_officeholder` | 上轮后 `rg` 生产/测试无定义无调用 | DELETED（4bc6994） | 零调用；F18 KEEP「出类」被本类重开撤销 |
| `night_dossiers_ready` | 同上 | DELETED（4bc6994） | 零调用退役水位谓词 |
| `ChatTurnResult.directive_confirmation_ambiguous` + `web_app._chat_payload` 参数/透传 + `DirectiveConfirmationAmbiguous` 类型字段 | 无生产赋值、前端曾仅类型 | DELETED（4bc6994） | 专属含糊确认接缝零消费 |
| `GameDB.complete_rescript_summon_scaffold_turn` | 本轮 `rg` 仅原 def；`prepare_rescript_summon_scaffold` 注明「不再建 generating 对话轮」；消费改 `TAG_ENTER` | DELETED（本轮） | #1838 废除 generating scaffold 后的唯一 consumed 写点残留 |
| `models.ChatResult` | 全仓除原定义外零引用（`rg \bChatResult\b`） | DELETED（本轮） | 被 `ChatTurnResult` 取代的死类型 |
| `ChatTurnResult.refresh_ministers` | 仅字段声明；无赋值、无 web/测试消费 | DELETED（本轮） | 与死 `ChatResult.refresh_ministers` 同族零消费字段 |

### KEEP（有真实消费者，或非退役接缝）

| 成员 | 具体引用 | 处置 | 理由 |
|---|---|---|---|
| `secret_order_can_land` / `secret_order_landing_gaps` | `declaration_dispatch.py` 现役落库闸 | KEEP | 真实消费者 |
| `_canonical_minister_key` / `_appointment_intent_is_current_office_noop` | session/appointment 现役 | KEEP | 真实消费者 |
| `prepare_rescript_summon_scaffold` / `rescript_summon_origin_consumed` | `session.commit_rescript_phase1`；消费=`TAG_ENTER` | KEEP | 现役召见入殿账；非 generating 旧路 |
| `list_in_flight_chat_turns` 对 `consumed` 状态过滤 | `db.py` | KEEP | 状态字仍合法；写点退役不等于删读侧过滤 |
| `ChatTurnResult.appointed_minister` / `registered_minister` / `displaced_minister` + web 透传 | 字段默认 `""`；`web_app` 透传；前端类型仅 `registered_minister`；**无 `result.*=` 生产赋值** | KEEP | 无「已作废职责」权威链；零赋值≠本类授权泛删 API 面 |
| `ChatTurnResult.proposed_directive` / `secret_order_id` / `pending_action_id` / `next_minister` / `pending_audience_translation` / `court_action` / `answer` | court_action/answer/pending_audience_translation 有生产写；其余为载荷契约面 | KEEP | 现役召对结果载体；非退役接缝 |
| `require_fresh_cli_trace` | `scripts/*gate*.py` | KEEP | CLI 闸守卫，有调用 |
| `_compose_inworld_fact_report` 等 inworld 共享 | `cli_backend.py` | KEEP | 现役共享回禀 |
| 财政 `legacy_*` 修饰 | `db.py` `insert_legacy`/`apply_legacy_pct` 等 | KEEP | 「legacy」=帝国修正实体，非退役代码 |
| 冻结 evidence / docs 叙述旧符号 | `evidence/1834-f18-*/report.md` 等 | KEEP | 冻结失败记录，不改写 |

### 本轮枚举范围声明

- 扫描：`ming_sim/**/*.py`、`web_app.py`、`web/src`、`tests`、`main.py`、`launcher.py` 上定义/类型/字段/参数与 `name(` 消费者。
- 退役形候选（compose/recovery/ambiguous/ready/prefix/extract_secret/ChatResult 等）逐项看职责是否被后出路径废除。
- **未**把一切零调用私有函数删光；仅删有退役职责证据或与已删样本同形的零消费结构。
