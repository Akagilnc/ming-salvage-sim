# 1834 F21/F22 成员表（全仓枚举完整清单；非代表样本）

权威：`ENUM_CMDS.txt` + `enum_cmds.sh` + `enum_out/` + `RECEIPT.md`。
临时 AST 一次性脚本：`scripts/enum_f21_free_field_crops.py` / `scripts/enum_f22_full_defs_refs.py`（非永久分类层）。

---

## F21 自由字段搬运链改写

类定义：沿真实输入、写入、读取、物化、供料与前端显示追踪取值，删除自由字段上的裁字；判空用副本；机器键归一保留。追自由字段 candidate，禁止 AST 名滤自动 KEEP。

枚举：all_crop_write_shapes=1721；freeish_name_candidates=132（完整见 `enum_out/f21_freeish_crop_candidates.md`）。

### FIX（本类成立；读写/物化/供料/前端同在类内）

| 组 | 具体引用 | 处置 | 数据流理由 |
|---|---|---|---|
| military_order 人读 station 写入 | `ming_sim/rescript_actions.py` `station=str(...); if station.strip(): payload["station"]=station` | FIX | 输入→payload 写入保原文 |
| military_order 人读 station 物化 | `ming_sim/db.py` `_apply_military_order_station_effect` `dest=str(station or "")`；`station_region` 仍可 strip | FIX | 物化主表保原文 |
| highlights 读取 | `ming_sim/db.py` `_parse_highlights_json` `if item.strip(): out.append(item)` | FIX | 读库→呈现保原文 |
| highlights 写入/判官 | `set_message_highlights` / `highlight_judge.parse_highlight_judge_output` 短语保原文 | FIX | 写入链保原文 |
| materials 供料 spoken/body | `materials.py` `parts.append(spoken if spoken.strip() else …)`；body join 用原文 | KEEP已正确 | 供料写树：判空副本 |
| 前端高亮显示 | `web/src/highlights.ts` slice 只切显示段落，不改 phrase 存值 | KEEP | 显示链不裁字 |
| 前端邸报选读 | `useSettlementFlow.ts` `fromPayload.trim() ? fromPayload : fromState` | KEEP | 判空用 trim，赋值原文 |

### FREEISH 候选逐条处置（完整 132 条；非 AST 自动 KEEP）

| path:line | shape | targets | 处置 | 理由 |
|---|---|---|---|---|
| `ming_sim/action_clusters.py:255` | assign | label | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/action_materialize.py:1035` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/action_materialize.py:1259` | assign | body | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/appointment_tenure.py:46` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/assets.py:27` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/audience_night.py:697` | assign | message | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/audience_night.py:757` | assign | message | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/audience_night.py:1994` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/audience_night.py:2019` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/audience_translate.py:246` | assign | body | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/breach_plea.py:81` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/breach_plea.py:95` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/centrifuge_ledger.py:99` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/cli_backend.py:864` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/cli_backend.py:896` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/cli_backend.py:1310` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/cli_backend.py:2572` | assign | title | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/cli_backend.py:2578` | assign | body | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/cli_backend.py:3504` | assign | body | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/content.py:313` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/context.py:267` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/covert_progress.py:133` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/covert_progress.py:159` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/covert_progress.py:312` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/covert_progress.py:792` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/credit_events.py:65` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/credit_events.py:98` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/db.py:6155` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/db.py:7380` | assign | reason | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/db.py:7882` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/db.py:7899` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/db.py:7981` | assign | reason | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/db.py:8807` | assign | reason | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/db.py:12997` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/db.py:13666` | assign | display | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/db.py:13857` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/db.py:14246` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/db.py:16677` | assign | title | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/db.py:18522` | kwarg | decree_text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/db.py:19960` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/db.py:19992` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/db.py:20624` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/decree_vocabulary.py:372` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/due_review.py:49` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/due_review.py:77` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/entities/affair/store.py:463` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/entities/affair/store.py:542` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/execution_pressure.py:52` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/execution_pressure.py:142` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/fiscal_fact_brief.py:569` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/fiscal_fact_brief.py:589` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/flows.py:1591` | assign | reason | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/highlight_judge.py:26` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/issues.py:232` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/issues.py:506` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/issues.py:516` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/issues.py:806` | assign | display | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/issues.py:2198` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/issues.py:2325` | assign | reason | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/issues.py:2843` | assign | title | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/issues.py:4385` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/issues.py:4389` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/issues.py:4397` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/issues.py:5221` | assign | reason | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/issues.py:6158` | assign | title | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/issues.py:8064` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/issues.py:8489` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/issues.py:8499` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/issues.py:8589` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/issues.py:8750` | assign | display | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/matching.py:69` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/matching.py:102` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/matching.py:180` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/matching.py:202` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/materials.py:96` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/materials.py:276` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/materials.py:299` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/materials.py:479` | assign | opening_text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/materials.py:529` | assign | situation | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/materials.py:553` | assign | situation | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/materials.py:564` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/materials.py:587` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/materials.py:645` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/materials.py:709` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/materials.py:802` | assign | body | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/materials.py:1108` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/materials.py:1580` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/materials.py:1581` | assign | body | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/materials.py:1616` | assign | body | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/materials.py:2219` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/month_chain.py:1755` | assign | body | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/office_rank.py:31` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/office_rank.py:34` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/office_rank.py:35` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/office_rank.py:69` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/relation_read.py:104` | assign | summary | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/rescript_actions.py:472` | assign | label | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/rescript_actions.py:704` | assign | decree_text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/rescript_actions.py:1180` | kwarg | decree_text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/rescript_draft.py:379` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/rescript_draft.py:381` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/rescript_draft.py:386` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/rescript_draft.py:393` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/rescript_draft.py:398` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/rescript_draft.py:406` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/rescript_draft.py:411` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/rescript_draft.py:413` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/rescript_draft.py:528` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/rescript_draft.py:1153` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/rescript_draft.py:1155` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/session.py:1310` | assign | answer | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/session.py:2314` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/settlement_payload.py:37` | assign | label | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/settlement_payload.py:192` | assign | title | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/settlement_payload.py:213` | assign | title | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/staged_commitment.py:41` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/staged_commitment.py:99` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/staged_commitment.py:250` | assign | criterion | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/staged_commitment.py:255` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/supervision.py:185` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/supervision.py:223` | assign | body | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `ming_sim/value_matrix.py:51` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `scripts/jisi_army_dispatch_probe.py:135` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `scripts/military_flow_probe.py:150` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `scripts/play_as_emperor.py:217` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `scripts/play_as_emperor.py:480` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `web/src/highlights.ts:41` | ts_line | — | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `web/src/highlights.ts:45` | ts_line | — | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `web/src/useSettlementFlow.ts:300` | ts_line | report | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `web_app.py:244` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `web_app.py:879` | append | <append> | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |
| `web_app.py:3083` | assign | text | KEEP | 机器键/判空副本/外壳/匹配键/路径键；非自由正文落库改写 |

覆盖核对：freeish_name_candidates=132；上表行数=132。

---

## F22 退役旧接缝残留

类定义：按现行职责与真实消费者清理已作废结构及专属参数、透传、类型和测试；保留在用共享能力与公开现役 API 与冻结失败记录。
枚举：def_count=3652；zero_abs=54；zero_prod_test_only=70（完整候选 `enum_out/f22_zero_consumer_candidates.md` + 处置 `f22_zero_disposition.tsv`）。
边界：全仓 Python 函数/类/dataclass 字段 + TS export/type；**不是** ChatTurnResult 单 dataclass / 具名 expanded set。

### DELETE（本轮+已验 absent）

| 成员 | 位置 | 处置 | 职责追猎理由 |
|---|---|---|---|
| `EN_VALUE_CN` | web/src/format.ts | DELETED | 零消费者旧枚举查找表；职责已废，假借「非自由正文」绕开 F22 不成立 |
| `Suggestion` | web/src/types.ts | DELETED | 零引用 TS 类型；建议芯片契约已无前端消费者 |
| `ExtractionPendingStatus` | web/src/types.ts | DELETED | #501/#1353 待补抽取诊断类型；不再驱动 CTA，零引用 |
| `PromulgationHealEvidence(+heal_evidence 参数)` | ming_sim/exceptions.py / decree import | DELETED | NamedTuple 从未构造；专属坏输出证据结构退役 |
| `run_audience_turn_translation` | ming_sim/audience_translate.py | DELETED | 零调用包装；现役走 apply_audience_round_translation |
| `stage_referral_candidate / stage_revoke_authority_candidate` | ming_sim/action_materialize.py | DELETED | 零调用专属暂存写缝；现役仅 stage_revoke_decree_candidate 等有消费者 |
| `season_option_contract_prompt / cluster_effect` | ming_sim/action_clusters.py | DELETED | 零调用专属投影 |
| `_merge_compliant_promulgation_items / _promulgable_proposed_dossiers / _dossier_ids_from_simulator_payload / _open_affair_ids_from_payload` | ming_sim/decree.py | DELETED | 私有零调用颁布/模拟器残留 |
| `contract_axes_direction / parse_covert_exec_selections` | ming_sim/covert_progress.py | DELETED | 零调用密令辅助 |
| `discover_character_write_sql_locations / person_write_locations_by_disposition` | ming_sim/person_write_inventory.py | DELETED | 零调用库存扫描辅助 |
| `qualitative_character_attribute / disaster_severity_band` | ming_sim/qualitative.py | DELETED | 零调用定性辅助 |
| `status_delta / build_period_report` | ming_sim/report.py | DELETED | 零调用报告辅助（status_delta_from_delta 仍在） |
| `mean_aligned_stance` | ming_sim/value_matrix.py | DELETED | 零调用 |
| `release_previous_material_tree` | ming_sim/materials.py | DELETED | 零调用材料树释放 |
| `dict_of_string_lists / dict_of_strings` | ming_sim/content.py | DELETED | 零调用 content 校验器 |
| `historical_anchor_for_month / parse_json_dict / event_context / first_character_name` | ming_sim/context.py | DELETED | 零调用 context 辅助 |
| `require_non_empty_text / require_int_range / require_bool` | ming_sim/llm_contract.py | DELETED | 零调用契约校验器（abort_llm_contract 仍在） |
| `has_player_visible_rejection` | ming_sim/applier.py | DELETED | RejectionCollector 零调用方法 |
| `_primary_source_only_army_pay_container_total / _is_audience_chat_shared_channel` | ming_sim/db.py | DELETED | 私有零调用 |
| `apply_llm_config / _open_night_court_break` | web_app.py | DELETED | WebGame 零调用方法；现役保存 LLM 路径另在 |
| `appointed/registered/displaced + splitReportItems` | prior commits | DELETED | 上轮已删；本轮复验仍 absent |

### 零真实消费者候选完整清单（枚举后仍存在者；逐条处置）

| zero_kind | kind | qualname | path:line | 处置 | 理由 |
|---|---|---|---|---|---|
| absolute_zero | py_func | `_resolve_unique_active_authority` | `ming_sim/action_materialize.py:1424` | KEEP | 零调用但无退役职责证据；保留共享/公开表面 |
| absolute_zero | py_func | `apply_audience_turn_translation` | `ming_sim/audience_translate.py:525` | KEEP | 零调用但无退役职责证据；保留共享/公开表面 |
| absolute_zero | py_method | `CliChat.ainvoke_stream` | `ming_sim/cli_backend.py:3737` | KEEP | CliChat 公开流式适配表面 |
| absolute_zero | py_method | `CliChat.aresponse_stream` | `ming_sim/cli_backend.py:3762` | KEEP | CliChat 公开流式适配表面 |
| absolute_zero | py_func | `first_character` | `ming_sim/context.py:316` | KEEP | 零调用但无退役职责证据；保留共享/公开表面 |
| absolute_zero | py_method | `GameDB.list_office_vacancies` | `ming_sim/db.py:4048` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| absolute_zero | py_method | `GameDB.record_economy_moves` | `ming_sim/db.py:6519` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| absolute_zero | py_method | `GameDB.turn_power_summary` | `ming_sim/db.py:7188` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| absolute_zero | py_method | `GameDB.building_detail` | `ming_sim/db.py:8947` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| absolute_zero | py_method | `GameDB.turn_economy_summary` | `ming_sim/db.py:9033` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| absolute_zero | py_method | `GameDB.treasury_ledger` | `ming_sim/db.py:9059` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| absolute_zero | py_method | `GameDB.mark_chat_turn_failed` | `ming_sim/db.py:9683` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| absolute_zero | py_method | `GameDB.append_rescript_drafts` | `ming_sim/db.py:11067` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| absolute_zero | py_method | `GameDB.attach_secret_oral_pin` | `ming_sim/db.py:11310` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| absolute_zero | py_method | `GameDB.list_open_grant_reconciliations` | `ming_sim/db.py:12375` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| absolute_zero | py_method | `GameDB.executable_decree_dossier_ids` | `ming_sim/db.py:15167` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| absolute_zero | py_method | `GameDB.clear_directive_needs_clarification` | `ming_sim/db.py:17718` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| absolute_zero | py_method | `GameDB.list_promulgated_directives` | `ming_sim/db.py:17782` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| absolute_zero | py_method | `GameDB.discard_pending_directives` | `ming_sim/db.py:18965` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| absolute_zero | py_method | `GameDB.list_recent_issue_advances` | `ming_sim/db.py:20605` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| absolute_zero | py_method | `GameDB.read_credit_events_as_edges` | `ming_sim/db.py:22693` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| absolute_zero | py_func | `_collect_compliant_promulgation_items` | `ming_sim/decree.py:162` | KEEP | 零调用但无退役职责证据；保留共享/公开表面 |
| absolute_zero | py_method | `AffairStore.point_dossier` | `ming_sim/entities/affair/store.py:290` | KEEP | 实体 store 公开读面 |
| absolute_zero | py_method | `AffairStore.point_issue` | `ming_sim/entities/affair/store.py:322` | KEEP | 实体 store 公开读面 |
| absolute_zero | py_method | `TextualFactStore.pointing_at` | `ming_sim/entities/textual_fact/store.py:113` | KEEP | 实体 store 公开读面 |
| absolute_zero | py_func | `_province_transport_ratio` | `ming_sim/flows.py:65` | KEEP | 零调用但无退役职责证据；保留共享/公开表面 |
| absolute_zero | py_func | `_province_collection_rate` | `ming_sim/flows.py:70` | KEEP | 零调用但无退役职责证据；保留共享/公开表面 |
| absolute_zero | py_func | `_fiscal_container_value` | `ming_sim/flows.py:296` | KEEP | 零调用但无退役职责证据；保留共享/公开表面 |
| absolute_zero | py_field | `_HubOutboundResult.k` | `ming_sim/flows.py:550` | KEEP | 单字符名枚举不可靠；非退役处置面 |
| absolute_zero | py_method | `MaterialsRoot.__call__` | `ming_sim/materials.py:178` | KEEP | MaterialsRoot 协议调用面 |
| absolute_zero | py_func | `_write_locations_in_source` | `ming_sim/person_write_inventory.py:113` | KEEP | 零调用但无退役职责证据；保留共享/公开表面 |
| absolute_zero | py_func | `status_delta_from_delta` | `ming_sim/report.py:97` | KEEP | 零调用但无退役职责证据；保留共享/公开表面 |
| absolute_zero | py_method | `ClassifiedWriteGate.holder_kind` | `ming_sim/session_write_queue.py:110` | KEEP | 写闸公开属性 |
| absolute_zero | py_func | `hline` | `scripts/make_steam_assets.py:46` | KEEP | 探针/脚本本地能力；非生产退役接缝 |
| absolute_zero | py_field | `EmperorState.turn_count` | `scripts/play_as_emperor.py:162` | KEEP | 探针/脚本本地能力；非生产退役接缝 |
| absolute_zero | py_func | `S` | `spike_settle_tick.py:250` | KEEP | 单字符名枚举不可靠；非退役处置面 |
| absolute_zero | py_async | `dependency_mismatch_handler` | `web_app.py:4198` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| absolute_zero | py_async | `api_menu_continue` | `web_app.py:4518` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| absolute_zero | py_async | `api_menu_load_save` | `web_app.py:4637` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| absolute_zero | py_async | `api_menu_delete_save` | `web_app.py:4759` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| absolute_zero | py_async | `api_retry_mechanical_tail` | `web_app.py:5043` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| absolute_zero | py_async | `api_secret_orders` | `web_app.py:5091` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| absolute_zero | py_async | `api_map` | `web_app.py:5212` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| absolute_zero | py_async | `api_buildings` | `web_app.py:5217` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| absolute_zero | py_async | `api_audience_chat_history` | `web_app.py:5298` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| absolute_zero | py_async | `api_retry_audience_reply` | `web_app.py:5364` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| absolute_zero | py_async | `api_retry_pending_translation` | `web_app.py:5386` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| absolute_zero | py_async | `api_list_saves` | `web_app.py:5979` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| absolute_zero | py_async | `api_delete_save` | `web_app.py:5997` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| absolute_zero | py_async | `api_upload_portrait` | `web_app.py:6174` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| absolute_zero | py_async | `api_get_portrait` | `web_app.py:6230` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| absolute_zero | py_async | `api_admin_tables` | `web_app.py:6239` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| absolute_zero | py_async | `api_admin_table` | `web_app.py:6244` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| absolute_zero | py_async | `admin_page` | `web_app.py:6289` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_func | `stage_authorization_candidate` | `ming_sim/action_materialize.py:1622` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | py_func | `create_rescript_draft_agent` | `ming_sim/agents.py:796` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | py_func | `list_night_timeline` | `ming_sim/audience_night.py:447` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | py_func | `audit_night_direct_writes` | `ming_sim/audience_night.py:662` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | py_func | `list_arrived_unsettled_summons` | `ming_sim/audience_night.py:1492` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | py_func | `get_night_protagonist` | `ming_sim/audience_night.py:2155` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | py_func | `persons_entered_tonight` | `ming_sim/audience_night.py:2227` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | py_method | `CliChat.response_stream` | `ming_sim/cli_backend.py:3741` | KEEP | CliChat 公开流式适配表面 |
| prod_zero_test_only | py_func | `build_secret_covert_effect_briefs` | `ming_sim/covert_progress.py:646` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | py_method | `GameDB.settle_province_tick` | `ming_sim/db.py:3144` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| prod_zero_test_only | py_method | `GameDB.turn_region_summary` | `ming_sim/db.py:7324` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| prod_zero_test_only | py_method | `GameDB.turn_army_summary` | `ming_sim/db.py:7919` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| prod_zero_test_only | py_method | `GameDB.get_message_highlights` | `ming_sim/db.py:9161` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| prod_zero_test_only | py_method | `GameDB.record_monthly_supervision_facts` | `ming_sim/db.py:12675` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| prod_zero_test_only | py_method | `GameDB.list_dossiers_for_directive` | `ming_sim/db.py:14662` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| prod_zero_test_only | py_method | `GameDB.list_endorsed_dossier_candidates` | `ming_sim/db.py:14680` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| prod_zero_test_only | py_method | `GameDB.list_dossier_link_rejections` | `ming_sim/db.py:14983` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| prod_zero_test_only | py_method | `GameDB.save_pending_promulgation_verdicts` | `ming_sim/db.py:16234` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| prod_zero_test_only | py_method | `GameDB.drop_pending_actions_for_minister` | `ming_sim/db.py:18910` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| prod_zero_test_only | py_method | `GameDB.list_office_effects_for_dossier` | `ming_sim/db.py:19216` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| prod_zero_test_only | py_method | `GameDB.reject_directive` | `ming_sim/db.py:19508` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| prod_zero_test_only | py_method | `GameDB.count_active_initiatives` | `ming_sim/db.py:19632` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| prod_zero_test_only | py_method | `GameDB._is_active_secret_order_assignee` | `ming_sim/db.py:21320` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | py_method | `GameDB.get_faction_stance_summary` | `ming_sim/db.py:22889` | KEEP | GameDB 公开账本 API 表面；零调用≠删共享读面 |
| prod_zero_test_only | py_func | `execution_side_read_fields` | `ming_sim/decree.py:233` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | py_func | `build_fiscal_fact_brief` | `ming_sim/fiscal_fact_brief.py:334` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | py_func | `format_fiscal_fact_brief_tsv` | `ming_sim/fiscal_fact_brief.py:583` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | py_func | `stage_month_segment` | `ming_sim/month_translate.py:240` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | py_func | `revoke_pay_order_decree` | `ming_sim/pay_order.py:472` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | py_func | `run_month_end_relation_brew` | `ming_sim/relation_brew.py:438` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | py_func | `format_region_changes` | `ming_sim/report.py:36` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | py_func | `format_army_changes` | `ming_sim/report.py:52` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | py_func | `format_power_changes` | `ming_sim/report.py:72` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | py_func | `select_triage_actor` | `ming_sim/rescript_draft.py:1107` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | py_func | `generate_rescript_draft` | `ming_sim/rescript_draft.py:2149` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | py_method | `SessionWriteQueue.is_sealed` | `ming_sim/session_write_queue.py:262` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | py_method | `SessionWriteQueue.run_exclusive` | `ming_sim/session_write_queue.py:520` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | py_func | `value_axes` | `ming_sim/value_matrix.py:46` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | py_func | `axis_collision_stances` | `ming_sim/value_matrix.py:100` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | py_func | `matrix_snapshot` | `ming_sim/value_matrix.py:137` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | ts_export | `IssueGroup` | `web/src/components/situation.tsx:200` | KEEP | 测试消费现役缝；生产可达其它路径或公开缝 |
| prod_zero_test_only | py_async | `api_menu_new_game` | `web_app.py:4414` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_async | `api_menu_exit` | `web_app.py:4773` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_async | `api_menu_shutdown` | `web_app.py:4802` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_async | `api_menu_save_llm` | `web_app.py:4932` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_async | `api_state` | `web_app.py:5038` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_async | `api_memorials_read` | `web_app.py:5054` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_func | `api_history_turns` | `web_app.py:5163` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_async | `api_history_turn` | `web_app.py:5170` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_async | `api_add_favorite` | `web_app.py:5222` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_async | `api_remove_favorite` | `web_app.py:5233` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_func | `api_audience_scroll` | `web_app.py:5261` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_async | `api_audience_chat` | `web_app.py:5326` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_async | `api_undo_audience_chat` | `web_app.py:5373` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_async | `api_audience_chat_stream` | `web_app.py:5445` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_async | `api_update_directive` | `web_app.py:5455` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_async | `api_delete_directive` | `web_app.py:5500` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_func | `api_advance_without_edict` | `web_app.py:5516` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_func | `api_issue_decree` | `web_app.py:5642` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_async | `api_issue_decree_stream` | `web_app.py:5733` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_async | `api_resolve_decisions_stream` | `web_app.py:5856` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_async | `api_create_save` | `web_app.py:5984` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_async | `api_load_save` | `web_app.py:6003` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_async | `api_get_llm_config` | `web_app.py:6014` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_async | `api_set_llm_config` | `web_app.py:6078` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_async | `api_delete_portrait` | `web_app.py:6201` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_async | `api_get_court_layout` | `web_app.py:6216` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_async | `api_set_court_layout` | `web_app.py:6222` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_async | `api_admin_upsert` | `web_app.py:6258` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |
| prod_zero_test_only | py_async | `api_admin_delete` | `web_app.py:6276` | KEEP | 公开 HTTP/ASGI 现役 API（装饰器注册，函数名零 Python 调用属常态） |

覆盖核对：zero 候选=124；上表行数=124。

处置原则：公开 HTTP `api_*` / GameDB 公开方法 / 实体 store / CliChat 流式面 / 探针脚本 → KEEP；零调用≠全删；但零消费者旧表（如 EN_VALUE_CN）追职责后该废则删。

