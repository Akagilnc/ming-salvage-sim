# 1834 F21/F22 成员表（全仓枚举完整清单；非代表样本）

权威：`ENUM_CMDS.txt`（F21 broad `rg` 形 + F22 一次性 inline AST；非固定保原文样本文字/具名已删列表）+ 本表 + `RECEIPT.md`。
不恢复永久枚举脚本 / 700 行分类层 / 全量 jsonl 副本；处置以本表为准。

---

## F21 自由字段搬运链改写

类定义：沿真实输入、写入、读取、物化、供料与前端显示追踪取值，删除自由字段上的裁字；判空用副本；机器键归一保留。枚举入口=ENUM_CMDS F21 CMD1–3（strip 带参 / re.sub / replace / split / join / slice）；禁止自由文字哨兵或 AST 名滤自动 KEEP。

枚举记录：broad 形见 ENUM_CMDS 复跑计数；下表 132 条为 assign/append 语义候选完整处置（非抽样）。

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

类定义：按现行职责与真实消费者清理已作废结构及专属参数、透传、类型和测试；保留在用共享能力与冻结失败记录。以删除、合并收尾，不接回旧机制、不加兼容层。
枚举记录（本轮 ENUM_CMDS inline AST，含 tests/scripts 引用语料）：见 ENUM_CMDS 复跑计数。
边界：全仓定义 + 引用复验；**不是** ChatTurnResult 单 dataclass / 具名 expanded set；**禁止**「零调用但无退役证据／公开 API 表面」循环 KEEP。
F21 本庭已通过，本表 F21 节不重开。

### DELETE（本轮+级联；复验 absent）

| 成员 | 位置 | 处置 | 职责追猎理由 |
|---|---|---|---|
| 先前 F22 已删 43 项（EN_VALUE_CN / Suggestion / ExtractionPendingStatus / PromulgationHealEvidence / run_audience_turn_translation / stage_referral_candidate / stage_revoke_authority_candidate / season_option_contract_prompt / cluster_effect / _merge_compliant_promulgation_items 等） | 多处 | DELETED | 上轮已删；本轮复验仍 absent |
| `_collect_compliant_promulgation_items` | ming_sim/decree.py | DELETED | 全仓只剩定义；同族 `_merge_*` 已删 |
| `_province_transport_ratio` / `_province_collection_rate` / `_fiscal_container_value` | ming_sim/flows.py | DELETED | 全仓只剩定义（桩返回 1.0 / 无调用） |
| `status_delta_from_delta` | ming_sim/report.py | DELETED | 全仓只剩定义 |
| `_write_locations_in_source` + `_enclosing_function_name` / `_is_sql_execute_argument` / `_inventory_location` / `_call_name` + 整模块 `person_write_inventory.py`（含 `PERSON_WRITE_POINT_INVENTORY`） | ming_sim/person_write_inventory.py | DELETED | 扫描器与清单零生产消费者；级联删整模块 |
| `first_character` | ming_sim/context.py | DELETED | 全仓只剩定义 |
| `_resolve_unique_active_authority` | ming_sim/action_materialize.py | DELETED | 全仓只剩定义 |
| `apply_audience_turn_translation` | ming_sim/audience_translate.py | DELETED | 全仓只剩定义（现役走 round 路径） |
| `CliChat.ainvoke_stream` | ming_sim/cli_backend.py | DELETED | 全仓只剩定义 |
| GameDB：`mark_chat_turn_failed` / `clear_directive_needs_clarification` / `discard_pending_directives` / `executable_decree_dossier_ids` / `append_rescript_drafts` / `attach_secret_oral_pin` / `list_office_vacancies` / `record_economy_moves` / `turn_power_summary` / `building_detail` / `turn_economy_summary` / `treasury_ledger` / `list_open_grant_reconciliations` / `list_promulgated_directives` / `list_recent_issue_advances` / `read_credit_events_as_edges` / `list_night_promulgated_directives` / `turn_region_summary` / `turn_army_summary` | ming_sim/db.py | DELETED | 全仓只剩定义或仅旧摘要专属测试 |
| `AffairStore.point_dossier` / `point_issue` | ming_sim/entities/affair/store.py | DELETED | 全仓只剩定义 |
| `TextualFactStore.pointing_at` | ming_sim/entities/textual_fact/store.py | DELETED | 全仓只剩定义 |
| `ClassifiedWriteGate.holder_kind` | ming_sim/session_write_queue.py | DELETED | 全仓只剩定义 |
| `stage_authorization_candidate` + `_authorization_privilege` / `_authorization_scope_parts` | ming_sim/action_materialize.py | DELETED | 无生产接线；仅专属测试 → 结构+专属测试同删 |
| `format_region_changes` / `format_army_changes` / `format_power_changes` | ming_sim/report.py | DELETED | 仅专属拒收格式化测试 → 结构+专属测试同删 |
| 专属测试：`test_region_army_formatters_skip_rejected_items` / `test_power_change_formatter_skips_rejected_items` / `test_turn_region_summary_claim_audit_rows_do_not_consume_limit` / `test_turn_army_summary_keeps_real_morale_changes_when_log_cap_fills` / `test_authorization_region_gets_single_locality` / `test_authorization_region_to_character_amendment_clears_single_locality` | tests/… | DELETED | 旧结构专属测试随结构删 |

### 枚举后仍存在候选（完整处置；禁止「无退役证据／公开 API」循环 KEEP）

| zero_kind | kind | qualname | path:line | 处置 | 理由 |
|---|---|---|---|---|---|
| prod_zero_test_only | py_method | `GameDB.settle_province_tick` | `ming_sim/db.py:3144` | KEEP | 共享现役能力（非旧结构专属）；测试消费者：tests/test_fiscal_substrate_bridge.py,tests/test_pay_order_override_653.py。KEEP=有真实现役职责/共享面，非「公开API」空话 |
| prod_zero_test_only | py_method | `GameDB.get_message_highlights` | `ming_sim/db.py:8945` | KEEP | 共享现役能力（非旧结构专属）；测试消费者：tests/test_highlight_judge_544.py。KEEP=有真实现役职责/共享面，非「公开API」空话 |
| prod_zero_test_only | py_method | `GameDB.record_monthly_supervision_facts` | `ming_sim/db.py:12398` | KEEP | 共享现役能力（非旧结构专属）；测试消费者：tests/test_supervision_625.py。KEEP=有真实现役职责/共享面，非「公开API」空话 |
| prod_zero_test_only | py_method | `GameDB.list_dossiers_for_directive` | `ming_sim/db.py:14385` | KEEP | 共享现役能力（非旧结构专属）；测试消费者：tests/test_execution_pressure_654.py。KEEP=有真实现役职责/共享面，非「公开API」空话 |
| prod_zero_test_only | py_method | `GameDB.list_endorsed_dossier_candidates` | `ming_sim/db.py:14403` | KEEP | 共享现役能力（非旧结构专属）；测试消费者：tests/test_pihong_dossier_1490.py。KEEP=有真实现役职责/共享面，非「公开API」空话 |
| prod_zero_test_only | py_method | `GameDB.list_dossier_link_rejections` | `ming_sim/db.py:14706` | KEEP | 共享现役能力（非旧结构专属）；测试消费者：tests/test_dossier_links_559.py。KEEP=有真实现役职责/共享面，非「公开API」空话 |
| prod_zero_test_only | py_method | `GameDB.save_pending_promulgation_verdicts` | `ming_sim/db.py:15947` | KEEP | 共享现役能力（非旧结构专属）；测试消费者：tests/test_pihong_dossier_1490.py,tests/test_promulgation_judge_561.py,tests/test_promulgation_seam_560.py。KEEP=有真实现役职责/共享面，非「公开API」空话 |
| prod_zero_test_only | py_method | `GameDB.drop_pending_actions_for_minister` | `ming_sim/db.py:18464` | KEEP | 共享现役能力（非旧结构专属）；测试消费者：tests/test_audience_undo_506.py,tests/test_secret_order_isolation_883.py。KEEP=有真实现役职责/共享面，非「公开API」空话 |
| prod_zero_test_only | py_method | `GameDB.list_office_effects_for_dossier` | `ming_sim/db.py:18753` | KEEP | 共享现役能力（非旧结构专属）；测试消费者：tests/test_decree_dossiers_571.py。KEEP=有真实现役职责/共享面，非「公开API」空话 |
| prod_zero_test_only | py_method | `GameDB.reject_directive` | `ming_sim/db.py:19045` | KEEP | 共享现役能力（非旧结构专属）；测试消费者：tests/test_decree_dossiers_571.py。KEEP=有真实现役职责/共享面，非「公开API」空话 |
| prod_zero_test_only | py_method | `GameDB.count_active_initiatives` | `ming_sim/db.py:19169` | KEEP | 共享现役能力（非旧结构专属）；测试消费者：tests/test_structured_decree_contract_1624.py。KEEP=有真实现役职责/共享面，非「公开API」空话 |
| prod_zero_test_only | py_method | `GameDB._is_active_secret_order_assignee` | `ming_sim/db.py:20851` | KEEP | 共享现役能力（非旧结构专属）；测试消费者：tests/test_secret_order_isolation_883.py。KEEP=有真实现役职责/共享面，非「公开API」空话 |
| prod_zero_test_only | py_method | `GameDB.get_faction_stance_summary` | `ming_sim/db.py:22416` | KEEP | 共享现役能力（非旧结构专属）；测试消费者：tests/test_faction_brew_637.py。KEEP=有真实现役职责/共享面，非「公开API」空话 |
| prod_zero_test_only | py_func | `value_axes` | `ming_sim/value_matrix.py:46` | KEEP | 共享现役能力（模块/管线仍有生产兄弟消费者或现役架构入口）；测试消费者：tests/test_value_matrix_691.py |
| prod_zero_test_only | py_func | `axis_collision_stances` | `ming_sim/value_matrix.py:100` | KEEP | 共享现役能力（模块/管线仍有生产兄弟消费者或现役架构入口）；测试消费者：tests/test_value_matrix_691.py |
| prod_zero_test_only | py_func | `matrix_snapshot` | `ming_sim/value_matrix.py:137` | KEEP | 共享现役能力（模块/管线仍有生产兄弟消费者或现役架构入口）；测试消费者：tests/test_value_matrix_691.py |
| prod_zero_test_only | py_func | `revoke_pay_order_decree` | `ming_sim/pay_order.py:472` | KEEP | 共享现役能力（非旧结构专属）；测试消费者：tests/test_pay_order_override_653.py。KEEP=有真实现役职责/共享面，非「公开API」空话 |
| prod_zero_test_only | py_func | `build_fiscal_fact_brief` | `ming_sim/fiscal_fact_brief.py:334` | KEEP | 共享现役能力（模块/管线仍有生产兄弟消费者或现役架构入口）；测试消费者：tests/test_mutiny_actual_residence_659.py,tests/test_pay_order_override_653.py |
| prod_zero_test_only | py_func | `format_fiscal_fact_brief_tsv` | `ming_sim/fiscal_fact_brief.py:583` | KEEP | 共享现役能力（模块/管线仍有生产兄弟消费者或现役架构入口）；测试消费者：tests/test_pay_order_override_653.py |
| prod_zero_test_only | py_func | `stage_month_segment` | `ming_sim/month_translate.py:240` | KEEP | 共享现役能力（模块/管线仍有生产兄弟消费者或现役架构入口）；测试消费者：tests/test_breach_plea_623.py,tests/test_month_translate_1840.py |
| prod_zero_test_only | py_func | `execution_side_read_fields` | `ming_sim/decree.py:200` | KEEP | 共享现役能力（模块/管线仍有生产兄弟消费者或现役架构入口）；测试消费者：tests/test_execution_tenure_613.py,tests/test_secret_dossier_participants_1252.py |
| prod_zero_test_only | py_func | `select_triage_actor` | `ming_sim/rescript_draft.py:1107` | KEEP | 共享现役能力（模块/管线仍有生产兄弟消费者或现役架构入口）；测试消费者：tests/test_rescript_draft_656.py |
| prod_zero_test_only | py_func | `generate_rescript_draft` | `ming_sim/rescript_draft.py:2149` | KEEP | 共享现役能力（模块/管线仍有生产兄弟消费者或现役架构入口）；测试消费者：tests/test_pihong_dossier_1490.py,tests/test_rescript_draft_656.py,tests/test_rescript_heal_isolation_1801.py |
| prod_zero_test_only | py_func | `create_rescript_draft_agent` | `ming_sim/agents.py:796` | KEEP | 共享现役能力（模块/管线仍有生产兄弟消费者或现役架构入口）；测试消费者：tests/test_llm_channel_config.py |
| prod_zero_test_only | py_func | `run_month_end_relation_brew` | `ming_sim/relation_brew.py:438` | KEEP | 共享现役能力（模块/管线仍有生产兄弟消费者或现役架构入口）；测试消费者：tests/test_faction_brew_637.py,tests/test_relation_brew_636.py |
| prod_zero_test_only | py_func | `build_secret_covert_effect_briefs` | `ming_sim/covert_progress.py:646` | KEEP | 共享现役能力（非旧结构专属）；测试消费者：tests/test_secret_order_payoff_1504.py。KEEP=有真实现役职责/共享面，非「公开API」空话 |
| script_only_consumer | py_func | `require_fresh_cli_trace` | `ming_sim/cli_backend.py:3873` | KEEP | scripts/spike 排除域有引用；非生产退役接缝 |
| prod_zero_test_only | py_func | `list_night_timeline` | `ming_sim/audience_night.py:447` | KEEP | 共享现役能力（非旧结构专属）；测试消费者：tests/test_audience_night_498.py。KEEP=有真实现役职责/共享面，非「公开API」空话 |
| prod_zero_test_only | py_func | `audit_night_direct_writes` | `ming_sim/audience_night.py:662` | KEEP | 共享现役能力（非旧结构专属）；测试消费者：tests/test_audience_undo_506.py,tests/test_on_scene_immediate_write_1839.py。KEEP=有真实现役职责/共享面，非「公开API」空话 |
| prod_zero_test_only | py_func | `list_arrived_unsettled_summons` | `ming_sim/audience_night.py:1492` | KEEP | 共享现役能力（非旧结构专属）；测试消费者：tests/test_audience_travel_gating_670.py。KEEP=有真实现役职责/共享面，非「公开API」空话 |
| prod_zero_test_only | py_func | `get_night_protagonist` | `ming_sim/audience_night.py:2155` | KEEP | 共享现役能力（非旧结构专属）；测试消费者：tests/test_audience_translation_1838.py。KEEP=有真实现役职责/共享面，非「公开API」空话 |
| prod_zero_test_only | py_func | `persons_entered_tonight` | `ming_sim/audience_night.py:2227` | KEEP | 共享现役能力（非旧结构专属）；测试消费者：tests/test_cli_play_turn.py,tests/test_month_loop_tracer_1468.py。KEEP=有真实现役职责/共享面，非「公开API」空话 |
| prod_zero_test_only | py_method | `SessionWriteQueue.is_sealed` | `ming_sim/session_write_queue.py:258` | KEEP | 共享现役能力（非旧结构专属）；测试消费者：tests/test_menu_lifecycle_drain_396.py,tests/test_new_game_write_path_1749.py。KEEP=有真实现役职责/共享面，非「公开API」空话 |
| prod_zero_test_only | py_method | `SessionWriteQueue.run_exclusive` | `ming_sim/session_write_queue.py:516` | KEEP | 共享现役能力（非旧结构专属）；测试消费者：tests/test_audience_travel_gating_670.py,tests/test_pihong_dossier_1490.py,tests/test_session_write_queue_1353.py。KEEP=有真实现役职责/共享面，非「公开API」空话 |
| absolute_zero | py_async | `dependency_mismatch_handler` | `web_app.py:4198` | KEEP | HTTP装饰器路由排除 |
| prod_zero_test_only | py_async | `api_menu_new_game` | `web_app.py:4414` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_menu_continue_stream_1195.py,tests/test_menu_lifecycle_drain_396.py |
| absolute_zero | py_async | `api_menu_continue` | `web_app.py:4518` | KEEP | HTTP装饰器路由排除 |
| absolute_zero | py_async | `api_menu_load_save` | `web_app.py:4637` | KEEP | HTTP装饰器路由排除 |
| absolute_zero | py_async | `api_menu_delete_save` | `web_app.py:4759` | KEEP | HTTP装饰器路由排除 |
| prod_zero_test_only | py_async | `api_menu_exit` | `web_app.py:4773` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_menu_continue_stream_1195.py,tests/test_menu_lifecycle_drain_396.py |
| prod_zero_test_only | py_async | `api_menu_shutdown` | `web_app.py:4802` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_menu_lifecycle_drain_396.py |
| prod_zero_test_only | py_async | `api_menu_save_llm` | `web_app.py:4932` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_web_llm_runtime_config.py |
| prod_zero_test_only | py_async | `api_state` | `web_app.py:5038` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_web_chat_serialization_393.py |
| absolute_zero | py_async | `api_retry_mechanical_tail` | `web_app.py:5043` | KEEP | HTTP装饰器路由排除 |
| prod_zero_test_only | py_async | `api_memorials_read` | `web_app.py:5054` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_settlement_write_guard_393.py |
| absolute_zero | py_async | `api_secret_orders` | `web_app.py:5091` | KEEP | HTTP装饰器路由排除 |
| prod_zero_test_only | py_func | `api_history_turns` | `web_app.py:5163` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_p4_guard_new_surfaces_547.py |
| prod_zero_test_only | py_async | `api_history_turn` | `web_app.py:5170` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_player_payload_1022.py |
| absolute_zero | py_async | `api_map` | `web_app.py:5212` | KEEP | HTTP装饰器路由排除 |
| absolute_zero | py_async | `api_buildings` | `web_app.py:5217` | KEEP | HTTP装饰器路由排除 |
| prod_zero_test_only | py_async | `api_add_favorite` | `web_app.py:5222` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_settlement_write_guard_393.py |
| prod_zero_test_only | py_async | `api_remove_favorite` | `web_app.py:5233` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_settlement_write_guard_393.py |
| prod_zero_test_only | py_func | `api_audience_scroll` | `web_app.py:5261` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_p4_guard_new_surfaces_547.py |
| absolute_zero | py_async | `api_audience_chat_history` | `web_app.py:5298` | KEEP | HTTP装饰器路由排除 |
| prod_zero_test_only | py_async | `api_audience_chat` | `web_app.py:5326` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_web_chat_serialization_393.py |
| absolute_zero | py_async | `api_retry_audience_reply` | `web_app.py:5364` | KEEP | HTTP装饰器路由排除 |
| prod_zero_test_only | py_async | `api_undo_audience_chat` | `web_app.py:5373` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_settlement_write_guard_393.py |
| absolute_zero | py_async | `api_retry_pending_translation` | `web_app.py:5386` | KEEP | HTTP装饰器路由排除 |
| prod_zero_test_only | py_async | `api_audience_chat_stream` | `web_app.py:5445` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_web_chat_serialization_393.py |
| prod_zero_test_only | py_async | `api_update_directive` | `web_app.py:5455` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_settlement_write_guard_393.py |
| prod_zero_test_only | py_async | `api_delete_directive` | `web_app.py:5500` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_settlement_write_guard_393.py |
| prod_zero_test_only | py_func | `api_advance_without_edict` | `web_app.py:5516` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_month_open_snapshot_1234.py,tests/test_no_edict_full_settlement_1274.py,tests/test_secret_order_monthly_progress_566.py |
| prod_zero_test_only | py_func | `api_issue_decree` | `web_app.py:5642` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_error_pack.py,tests/test_issue_decree_token_1277.py,tests/test_month_open_snapshot_1234.py |
| prod_zero_test_only | py_async | `api_issue_decree_stream` | `web_app.py:5733` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_player_payload_1022.py |
| prod_zero_test_only | py_async | `api_resolve_decisions_stream` | `web_app.py:5856` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_player_payload_1022.py,tests/test_qa_b3_409_ux.py,tests/test_qa_c2_phase_settlement_mask_1374.py |
| absolute_zero | py_async | `api_list_saves` | `web_app.py:5979` | KEEP | HTTP装饰器路由排除 |
| prod_zero_test_only | py_async | `api_create_save` | `web_app.py:5984` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_settlement_write_guard_393.py |
| absolute_zero | py_async | `api_delete_save` | `web_app.py:5997` | KEEP | HTTP装饰器路由排除 |
| prod_zero_test_only | py_async | `api_load_save` | `web_app.py:6003` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_qa_b3_409_ux.py,tests/test_settlement_write_guard_393.py |
| prod_zero_test_only | py_async | `api_get_llm_config` | `web_app.py:6014` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_cli_model_choices.py,tests/test_web_llm_runtime_config.py |
| prod_zero_test_only | py_async | `api_set_llm_config` | `web_app.py:6078` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_web_llm_runtime_config.py |
| absolute_zero | py_async | `api_upload_portrait` | `web_app.py:6174` | KEEP | HTTP装饰器路由排除 |
| prod_zero_test_only | py_async | `api_delete_portrait` | `web_app.py:6201` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_settlement_write_guard_393.py |
| prod_zero_test_only | py_async | `api_get_court_layout` | `web_app.py:6216` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_court_layout_1290.py |
| prod_zero_test_only | py_async | `api_set_court_layout` | `web_app.py:6222` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_court_layout_1290.py,tests/test_settlement_write_guard_393.py |
| absolute_zero | py_async | `api_get_portrait` | `web_app.py:6230` | KEEP | HTTP装饰器路由排除 |
| absolute_zero | py_async | `api_admin_tables` | `web_app.py:6239` | KEEP | HTTP装饰器路由排除 |
| absolute_zero | py_async | `api_admin_table` | `web_app.py:6244` | KEEP | HTTP装饰器路由排除 |
| prod_zero_test_only | py_async | `api_admin_upsert` | `web_app.py:6258` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_settlement_write_guard_393.py |
| prod_zero_test_only | py_async | `api_admin_delete` | `web_app.py:6276` | KEEP | HTTP装饰器路由排除；测试亦有打面。消费者：tests/test_settlement_write_guard_393.py |
| absolute_zero | py_async | `admin_page` | `web_app.py:6289` | KEEP | HTTP装饰器路由排除 |
| prod_zero_test_only | ts_export | `IssueGroup` | `web/src/components/situation.tsx:200` | KEEP | 共享现役能力（模块/管线仍有生产兄弟消费者或现役架构入口）；测试消费者：web/src/components/situation.test.tsx |

覆盖核对：上表 = 本轮 ENUM 后仍存在之 absolute_zero(KEEP 排除项) + script_only_consumer + prod_zero_test_only 完整行。

处置原则（F22-R 纠正）：
- **全仓只剩定义** → DELETE（含级联 dead helpers）；不得用「无退役证据／公开 API 表面」循环 KEEP。
- **仅被旧结构专属测试引用** → DELETE 结构 + 专属测试。
- **排除**：装饰器 HTTP 路由、Protocol/dunder、scripts/spike 定义与仅被其消费的门面。
- **共享现役能力**（有生产兄弟入口/现役架构职责，测试只是观测面）→ KEEP；不得把「未证热路径」写成循环自保。
