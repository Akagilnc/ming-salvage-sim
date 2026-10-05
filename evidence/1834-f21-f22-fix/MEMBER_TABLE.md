# 1834 F21/F22 成员表（完整可核；非代表样本）

权威导航：本文件 + `RECEIPT.md` + `ENUM_CMDS.txt`（含**实际 shell 命令**与 2154/91/2230/93/1155 计数）。
伪变异撤销：`MUTATION_FAKE_REVOKED.txt`（保持）。
冻结失败记录不改写：`evidence/1834-f16-*` / `evidence/1834-f18-*`。

谓词：F21 CMD1 含 scripts；语义归组以 CMD2_ALL_ASSIGN（1155）为主、CMD3 名滤仅交叉核对。未新建自动分类层。

---

## F21 自由字段搬运链改写

类定义：沿真实输入、写入、读取、物化与供料追踪取值，删除自由字段上的裁字；判空用副本；机器键归一保留。

### FIX（本类成立）

| 组 | 具体引用（全部） | 处置 | 理由 |
|---|---|---|---|
| military_order 人读 station 写入 | `ming_sim/rescript_actions.py` `map_rescript_option_or_choice`：`station=str(...)`；判空 `.strip()` 副本；`payload["station"]=station` | FIX | 人读驻地曾 strip 后写入 |
| military_order 人读 station 物化 | `ming_sim/db.py` `_apply_military_order_station_effect`：`dest=str(station or "")`；`station_region` 仍 strip | FIX | 物化曾 strip 改主表 |
| highlights 读取 | `ming_sim/db.py` `_parse_highlights_json`：`item.strip()` 仅判空，`out.append(item)` | FIX | 曾 append strip 结果 |
| highlights 写入 | `ming_sim/db.py` `set_message_highlights`；`highlight_judge.py` 短语保原文 | FIX | F16 保留 |

### CMD3_SCRIPTS 全部候选（逐条归组；非摘录）

#### KEEP — origin_ref / origin_id 机器引用键归一

| 引用 | 处置 |
|---|---|
| `ming_sim/action_materialize.py:1396:        origin = str(row["origin_ref"] or "").strip()` | KEEP |
| `ming_sim/pay_order.py:310:    origin = str(origin_ref or "").strip()` | KEEP |
| `ming_sim/credit_events.py:65:    text = str(origin or "").strip()` | KEEP |
| `ming_sim/entities/affair/store.py:450:            origin = str(row["origin_ref"] or "").strip()` | KEEP |
| `ming_sim/entities/affair/store.py:542:    text = str(origin_ref or "").strip()` | KEEP |
| `ming_sim/entities/textual_fact/store.py:80:        origin = sanitize_sqlite_text(str(origin_ref or "").strip())` | KEEP |
| `ming_sim/covert_levy.py:52:    origin = str(origin_ref or "").strip()` | KEEP |
| `ming_sim/db.py:16569:            origin = str(issue_row["origin_ref"] or "").strip()` | KEEP |
| `ming_sim/breach_plea.py:81:    text = str(origin_ref or "").strip()` | KEEP |
| `ming_sim/breach_plea.py:150:        origin = str(row["origin_ref"] or "").strip()` | KEEP |
| `ming_sim/audience_night.py:854:    origin = str(origin_ref or "").strip()` | KEEP |
| `ming_sim/audience_night.py:1391:    origin = str(origin_id or "").strip()` | KEEP |
| `ming_sim/audience_night.py:1592:    origin = str(origin_id or "").strip()` | KEEP |
| `ming_sim/audience_night.py:2318:    origin = str(origin or "").strip()` | KEEP |
| `ming_sim/audience_night.py:2358:    origin = str(origin_ref or "").strip()` | KEEP |
| `ming_sim/due_review.py:77:    text = str(origin_ref or "").strip()` | KEEP |
| `ming_sim/issues.py:232:    text = str(origin_ref or "").strip()` | KEEP |

理由：引用键归一，非人读自由正文落库改写。

#### KEEP — 判空副本后回退；非空走原文

| 引用 | 处置 |
|---|---|
| `ming_sim/action_materialize.py:1519:    matter_title = title_raw if title_raw.strip() else tid_raw` | KEEP |
| `ming_sim/action_materialize.py:1742:    matter_title = title_raw if title_raw.strip() else tid_raw` | KEEP |
| `ming_sim/staged_commitment.py:250:            criterion = title if title.strip() else "依限奏报"` | KEEP |
| `ming_sim/rescript_actions.py:704:    decree_text = note_raw if note_raw.strip() else label_raw` | KEEP |
| `ming_sim/rescript_actions.py:1183:        decree_text=body if body.strip() else title,` | KEEP |
| `ming_sim/db.py:7383:            reason = raw_reason if raw_reason.strip() else str(getattr(event, "title", "") or "")` | KEEP |
| `ming_sim/db.py:7984:            reason = raw_reason if raw_reason.strip() else str(getattr(event, "title", "") or "")` | KEEP |
| `ming_sim/db.py:8810:            reason = raw_reason if raw_reason.strip() else str(getattr(event, "title", "") or "")` | KEEP |
| `ming_sim/db.py:18527:            decree_text=decree_text if decree_text.strip() else None,` | KEEP |
| `ming_sim/materials.py:506:            opening_text = raw_latest if raw_latest.strip() else "见目录。"` | KEEP |
| `ming_sim/materials.py:591:        text = f"{body}（尚未入档）" if body.strip() else "尚未入档"` | KEEP |

理由：`.strip()` 只在判空副本；非空分支写原文。

#### KEEP — 职衔/身份标题匹配键

| 引用 | 处置 |
|---|---|
| `ming_sim/office_rank.py:31:    text = str(office or "").strip()` | KEEP |
| `ming_sim/office_rank.py:34:    text = re.sub(r"^(?:前|原任|原)", "", text).strip()` | KEEP |
| `ming_sim/office_rank.py:69:    text = str(title or "").strip()` | KEEP |
| `ming_sim/office_rank.py:108:    raw_title = str(office or "").strip()` | KEEP |
| `ming_sim/office_rank.py:187:        current_title = str(row["office"] or "").strip()` | KEEP |
| `ming_sim/matching.py:102:    text = str(raw).strip()` | KEEP |
| `ming_sim/matching.py:202:    text = str(raw).strip()` | KEEP |
| `ming_sim/db.py:16356:        office_title = str(payload.get("office") or "").strip()` | KEEP |
| `ming_sim/appointment_tenure.py:46:    text = str(value or "").strip()` | KEEP |
| `ming_sim/issues.py:2843:        title = str(item.get("new_title") or item.get("title") or "").strip()` | KEEP |
| `ming_sim/issues.py:6158:        title = str(item.get("new_title") or item.get("title") or "").strip()` | KEEP |
| `ming_sim/issues.py:7992:            explicit_title = str(item.get("new_title") or item.get("title") or "").strip()` | KEEP |

理由：职衔/身份枚举匹配键。

#### KEEP — 选项/动作类型 label 身份键

| 引用 | 处置 |
|---|---|
| `ming_sim/action_clusters.py:299:    label = str(obj.get("动作类型") or "").strip()` | KEEP |
| `ming_sim/rescript_actions.py:472:            label = str(req.get("label") or "").strip()` | KEEP |
| `ming_sim/settlement_payload.py:37:        label = str(option.get("label") or "").strip()` | KEEP |

理由：选项/动作类型身份键；自由批注在 note 等另字段。

#### KEEP — 枚举/矩阵/scope/axis 键归一

| 引用 | 处置 |
|---|---|
| `ming_sim/value_matrix.py:51:    text = str(raw or "").strip()` | KEEP |
| `ming_sim/execution_pressure.py:52:    text = str(raw).strip()` | KEEP |
| `ming_sim/issues.py:5221:        reason = str(cl.get("reason") or "").strip().lower()` | KEEP |
| `ming_sim/flows.py:1591:        reason = str(item.get("reason") or "").strip()` | KEEP |

理由：枚举矩阵/轴/scope 键，非奏报正文落库。

#### KEEP — JSON/围栏外壳 strip 再 parse；成员值另保

| 引用 | 处置 |
|---|---|
| `ming_sim/staged_commitment.py:41:        text = raw.strip()` | KEEP |
| `ming_sim/staged_commitment.py:99:        text = stages.strip()` | KEEP |
| `ming_sim/rescript_draft.py:528:            text = str(val).strip()` | KEEP |
| `ming_sim/rescript_draft.py:1153:        text = match.group(1).strip()` | KEEP |
| `ming_sim/rescript_draft.py:1155:        text = raw.strip()` | KEEP |
| `ming_sim/db.py:19963:            text = payload_json.strip()` | KEEP |
| `ming_sim/db.py:19995:        text = str(raw).strip()` | KEEP |
| `ming_sim/db.py:20627:        text = str(value).strip().lower()` | KEEP |
| `ming_sim/breach_plea.py:95:    text = str(origin_context or "").strip()` | KEEP |
| `ming_sim/highlight_judge.py:26:    text = str(raw or "").strip()` | KEEP |
| `ming_sim/covert_progress.py:159:        text = str(seed_guilt or "").strip()` | KEEP |

理由：整段 JSON/围栏外壳 strip 再 parse；成员短语/body 另保或不经此写。

#### KEEP — 机关名分割身份键

| 引用 | 处置 |
|---|---|
| `ming_sim/action_materialize.py:1035:        text = value.strip()` | KEEP |

理由：`parse_responsible_bodies` 机关名身份键分割。

#### KEEP — materials 路径/状态/包装（非裁自由正文核）

| 引用 | 处置 |
|---|---|
| `ming_sim/materials.py:96:    text = str(name or "").strip() or "未名"` | KEEP |
| `ming_sim/materials.py:326:        text = str(value or "").strip()` | KEEP |
| `ming_sim/materials.py:2289:        status_text = str(status or "").strip()` | KEEP |

理由：路径/状态键或判空后包装；DOM/供料核仍原文。

#### KEEP — 口令/消息局部匹配门闩

| 引用 | 处置 |
|---|---|
| `ming_sim/audience_night.py:1994:    text = str(message or "").strip()` | KEEP |
| `ming_sim/audience_night.py:2019:    text = str(message or "").strip()` | KEEP |

理由：recognize_* 局部匹配，不回写存储正文。

#### KEEP — settlement 候选标题绑 id

| 引用 | 处置 |
|---|---|
| `ming_sim/settlement_payload.py:192:        title = str(item.get("title") or "").strip()` | KEEP |
| `ming_sim/settlement_payload.py:213:        title = str(out.get("title") or "").strip()` | KEEP |

理由：候选 id 重绑匹配键。

#### KEEP — 密令契约字段机器键

| 引用 | 处置 |
|---|---|
| `ming_sim/covert_progress.py:133:    text = str(raw or "").strip()` | KEEP |
| `ming_sim/covert_progress.py:312:    text = str(raw or "").strip()` | KEEP |
| `ming_sim/covert_progress.py:428:        purpose_text = str(purpose or "").strip()` | KEEP |
| `ming_sim/covert_progress.py:435:                kind_text = str(target_kind or "").strip()` | KEEP |
| `ming_sim/covert_progress.py:436:                id_text = str(target_id or "").strip()` | KEEP |
| `ming_sim/covert_progress.py:441:    category_text = str(category or "").strip()` | KEEP |
| `ming_sim/covert_progress.py:444:    account_text = str(account or "").strip()` | KEEP |
| `ming_sim/covert_progress.py:449:    region_text = str(region or "").strip()` | KEEP |
| `ming_sim/covert_progress.py:452:    field_text = str(field or "").strip()` | KEEP |
| `ming_sim/covert_progress.py:458:    target_text = str(region_target or "").strip()` | KEEP |
| `ming_sim/covert_progress.py:461:    action_text = str(person_action or "").strip()` | KEEP |
| `ming_sim/covert_progress.py:800:    text = str(raw or "").strip()` | KEEP |

理由：密令契约字段归一。

#### KEEP — HTTP/异常包装

| 引用 | 处置 |
|---|---|
| `web_app.py:3116:            text = str(cur).strip()` | KEEP |

理由：异常链包装，非自由字段落库。

#### KEEP — scripts 探针键盘/JSON 外壳（非生产落库链）

| 引用 | 处置 |
|---|---|
| `scripts/play_as_emperor.py:217:    text = raw.strip()` | KEEP |
| `scripts/play_as_emperor.py:226:    input_text = str(obj.get("input", "")).strip()` | KEEP |

理由：探针解析 agent JSON/键盘输入；非生产 DB 自由字段链。

#### KEEP — 其它机器键/局部归一

| 引用 | 处置 |
|---|---|
| `ming_sim/credit_events.py:98:        text = str(part or "").strip()` | KEEP |
| `ming_sim/db.py:16680:            title = str(payload.get("target_id") or "").strip()` | KEEP |
| `ming_sim/db.py:21696:        origin = str(origin_minister_name or "").strip()` | KEEP |
| `ming_sim/supervision.py:185:    text = str(raw or "").strip()` | KEEP |
| `ming_sim/assets.py:27:            text = file.read().strip()` | KEEP |
| `ming_sim/due_review.py:49:    text = str(entry_kind or ENTRY_KIND_STAGED).strip()` | KEEP |
| `ming_sim/centrifuge_ledger.py:99:    text = str(value).strip()` | KEEP |
| `ming_sim/issues.py:387:        cond_text = cond.strip()` | KEEP |
| `ming_sim/issues.py:506:    text = str(resolve_condition or "").strip()` | KEEP |
| `ming_sim/issues.py:516:    text = str(resolve_condition or "").strip()` | KEEP |
| `ming_sim/issues.py:544:        cond_text = str(cond or "").strip()` | KEEP |
| `ming_sim/issues.py:2768:        value_text = str(value or "").strip()` | KEEP |

理由：机器键/局部归一；逐条读后非自由字段落库改写。

#### DELETE — 零调用自由正文加工工具（F22）

| 成员 | 处置 | 理由 |
|---|---|---|
| `web/src/format.ts` `splitReportItems`（曾 `text.replace/trim/split` 加工自由正文；全仓零调用；删除前亦曾出现在名滤交叉集） | DELETED（本轮） | F22 退役专属工具残留；非生产搬运链 KEEP 被封驳 |

覆盖核对：CMD3_SCRIPTS=93；已归组=93。

### CMD2_ALL_ASSIGN 额外写形（名滤未覆盖；语义 KEEP）

| 引用 | 处置 | 理由 |
|---|---|---|
| `ming_sim/db.py:14152` `normalized_payload["target_kind"]=...strip()` | KEEP | 机器 kind 键 |
| `ming_sim/db.py:14154` `normalized_payload["target_id"]=...strip()` | KEEP | 机器 id 键 |
| `ming_sim/declaration_dispatch.py:1523` `payload["region_id"]=...strip()` | KEEP | 地区 id 键 |
| `ming_sim/cli_backend.py:3337` `payload["name"]=target_id.strip()` | KEEP | 自 target_id 派生名键 |

本轮扩大枚举后**无新增**自由字段裁字落库 FIX 成员（三站点 FIX 保持）。

---

## F22 退役旧接缝残留

类定义：按现行职责与真实消费者清理已作废结构及专属参数、透传、类型和测试；保留在用共享能力与冻结失败记录。用户/末判授权清除已作废结构，**不要求逐符号御批**；零赋值零消费的专属旧能力可删。

### DELETE

| 成员 | 消费者证明 | 处置 | 理由 |
|---|---|---|---|
| `_target_active_officeholder` / `night_dossiers_ready` / `directive_confirmation_ambiguous` + 透传/类型 | 生产/测试无定义无调用 | DELETED（4bc6994） | 零调用退役 |
| `complete_rescript_summon_scaffold_turn` / `models.ChatResult` / `refresh_ministers` | 零调用 | DELETED（5b645e867） | #1838 后残留 / 死类型 |
| `ChatTurnResult.appointed_minister` / `registered_minister` / `displaced_minister` + `_chat_payload` 参数/透传 + `types.ts` `registered_minister` + `cli/terminal.py` 专属打印 + 测试空 kwargs | 全仓无 `result.*=` 生产赋值；仅默认与透传 | DELETED（本轮） | 无赋值零消费专属旧能力；上轮出类 KEEP 被封驳 |
| `web/src/format.ts` `splitReportItems` | 全仓零调用；加工自由正文 | DELETED（本轮） | 退役专属工具残留 |

### KEEP（真实消费者 / 非退役）

| 成员 | 具体引用 | 处置 | 理由 |
|---|---|---|---|
| `secret_order_can_land` / `secret_order_landing_gaps` | `declaration_dispatch` | KEEP | 现役落库闸 |
| `_canonical_minister_key` / `_appointment_intent_is_current_office_noop` | session/appointment | KEEP | 现役 |
| `prepare_rescript_summon_scaffold` / `rescript_summon_origin_consumed` | `commit_rescript_phase1`；消费=`TAG_ENTER` | KEEP | 现役召见 |
| `night_archive_metadata` / `night_scroll_container` | db/web_app 调用 | KEEP | 现役 |
| `_legacy_*` 财政/事务辅助 | models/issues 有调用 | KEEP | 「legacy」=实体修正，非退役代码 |
| `_target_catalog_for_kind` / `_compose_inworld_fact_report` / `require_fresh_cli_trace` / `list_in_flight_chat_turns` | 有调用 | KEEP | 现役共享 |
| `ChatTurnResult.answer/court_action/next_minister/proposed_directive/secret_order_id/pending_action_*/pending_audience_translation` | 有生产写或契约消费 | KEEP | 现役召对载体 |
| `test_displaced_minister_faction_leverage_recomputed` | 测派系 leverage，非 ChatTurn 字段 | KEEP | 域名「腾缺」≠死字段 |
| 冻结 evidence 叙述旧符号 | evidence/1834-f18-* 等 | KEEP | 失败记录不改写 |
| `EN_VALUE_CN`（format.ts 零引用查找表） | 无调用 | **剩余 scope** | 零调用但非自由正文加工；本轮不泛删查找表 |

### 本轮枚举范围

- F22：ChatTurnResult 全字段消费者矩阵 + format.ts 零调用文本工具 + 扩展符号集（appointed/registered/displaced/splitReportItems/scaffold/ChatResult/legacy/night_* 等，**非**仅 compose 词）。
- 删除仅限有退役职责证据或同形零消费专属结构；现役共享保留。
