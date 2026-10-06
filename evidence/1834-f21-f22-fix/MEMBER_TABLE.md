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
| `ming_sim/credit_events.py:98` / `_narrative_context` | assign→return | text | FIX | 自由语境共享搬运：判空用副本，返回原文（#1834 F21-R 纠正误 KEEP machine_key） |
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

类定义：按现行职责与真实消费者清理已作废结构及专属参数、透传、类型和测试；以删除、合并收尾，不接回旧机制、不加兼容层。
枚举记录（本轮 ENUM_CMDS inline AST，含 tests/scripts 引用语料）：见 ENUM_CMDS 复跑计数。
边界：全仓定义 + 引用复验；**不是** ChatTurnResult 单 dataclass / 具名 expanded set。
F21 本庭已通过，本表 F21 节不重开。

**本轮纠正（F22-R²）**：禁止「共享现役能力／模块有生产兄弟消费者」循环 KEEP。兄弟在用 ≠ 该定义在用。每个仅测试引用定义须找到**该定义本身**的真实生产消费者／动态注册／或本庭明确排除依据；测试运行它 ≠ 生产消费者。

### DELETE（本轮+级联；复验 absent）

| 成员 | 位置 | 处置 | 职责追猎理由 |
|---|---|---|---|
| 上轮 F22/F22-R 已删 absolute_zero／专属旧结构（含 `person_write_inventory`、`stage_authorization_candidate`、`format_*_changes`、摘要类 GameDB 读口等） | 多处 | DELETED | 上轮已删；本轮复验仍 absent |
| `GameDB.settle_province_tick` | ming_sim/db.py | DELETED | 仅 tests；现役生产走 `settle_ming_province_substrate_ticks`←`flows.py` |
| `GameDB.get_message_highlights` | ming_sim/db.py | DELETED | 仅 tests/test_highlight_judge_544；现役写口 `set_message_highlights`←`web_app.py` 仍留 |
| `GameDB.record_monthly_supervision_facts` | ming_sim/db.py | DELETED | 仅 tests；现役 `record_monthly_supervision_presence`←month_chain/declaration_dispatch |
| `GameDB.list_dossiers_for_directive` | ming_sim/db.py | DELETED | 仅 tests/test_execution_pressure_654 |
| `GameDB.list_endorsed_dossier_candidates` | ming_sim/db.py | DELETED | 仅 tests/test_pihong_dossier_1490 |
| `GameDB.list_dossier_link_rejections` | ming_sim/db.py | DELETED | 仅 tests/test_dossier_links_559 |
| `GameDB.save_pending_promulgation_verdicts` | ming_sim/db.py | DELETED | 仅 tests；读口 `get_pending_promulgation_verdicts` 有 scripts 消费者故 KEEP |
| `GameDB.drop_pending_actions_for_minister` | ming_sim/db.py | DELETED | 仅 tests |
| `GameDB.list_office_effects_for_dossier` | ming_sim/db.py | DELETED | 仅 tests/test_decree_dossiers_571 |
| `GameDB.reject_directive` | ming_sim/db.py | DELETED | 仅 tests/test_decree_dossiers_571 |
| `GameDB.count_active_initiatives` | ming_sim/db.py | DELETED | 仅 tests/test_structured_decree_contract_1624 |
| `GameDB._is_active_secret_order_assignee` | ming_sim/db.py | DELETED | 仅 tests/test_secret_order_isolation_883 |
| `GameDB.get_faction_stance_summary` | ming_sim/db.py | DELETED | 仅 tests；现役复数口 `get_faction_stance_summaries`←session/faction_brew |
| `value_axes` / `axis_collision_stances` / `matrix_snapshot` / `faction_axis_stance` / `_loaded` | ming_sim/value_matrix.py | DELETED | 仅 tests/test_value_matrix_691；现役只留 `normalize_axis/axes/direction`←covert_progress |
| `revoke_pay_order_decree` | ming_sim/pay_order.py | DELETED | 仅 tests/test_pay_order_override_653 |
| 整模块 `fiscal_fact_brief.py`（`build_fiscal_fact_brief` / `format_fiscal_fact_brief_tsv` 及专属 helper） | ming_sim/fiscal_fact_brief.py | DELETED | 全模块零生产消费者；仅 tests |
| `stage_month_segment` | ming_sim/month_translate.py | DELETED | 仅 tests；现役 `dispatch_month_segment`←month_chain |
| `execution_side_read_fields` + 级联 `resolve_executor_appointment_tenure` | ming_sim/decree.py | DELETED | 仅 tests；无生产接线 |
| `select_triage_actor` / `generate_rescript_draft` + heal 级联 helpers | ming_sim/rescript_draft.py | DELETED | 仅 tests；现役改票/校验走其它入口（session/rescript_actions） |
| `create_rescript_draft_agent` | ming_sim/agents.py | DELETED | 仅 tests/test_llm_channel_config；现役 `create_rescript_revise_agent` 仍用 `_rescript_option_instructions` |
| `run_month_end_relation_brew` | ming_sim/relation_brew.py | DELETED | 仅 tests；现役 `MonthEndRelationBrewLeg`←mechanical_tail |
| `build_secret_covert_effect_briefs` + 级联 `_current_game_turn` | ming_sim/covert_progress.py | DELETED | 仅 tests |
| `list_night_timeline` / `audit_night_direct_writes` / `list_arrived_unsettled_summons` / `get_night_protagonist` / `persons_entered_tonight` + 级联 `_night_direct_write_allowed_tables` / `_command_entry_has_tag_enter` | ming_sim/audience_night.py | DELETED | 仅 tests；无该定义生产消费者 |
| `SessionWriteQueue.is_sealed` / `run_exclusive` | ming_sim/session_write_queue.py | DELETED | 仅 tests；现役 seal/unseal/claim/complete/write_gate 仍留 |
| `IssueGroup` | web/src/components/situation.tsx | DELETED | 仅 situation.test.tsx；SituationPanel 等现役组件不调用 |
| 专属测试（随上表删）：`test_value_matrix_691.py` / `test_rescript_heal_isolation_1801.py` / `test_rescript_option_field_heal_1746.py` 整文件；以及各混合文件中直调已删定义的 `test_*` 函数 | tests/… / web/src/components/situation.test.tsx | DELETED | 旧结构专属测试随结构删 |

### 枚举后仍存在候选（完整处置；每 KEEP 须本定义消费者 path 或明确排除）

| zero_kind | kind | qualname | path:line | 处置 | 理由（本定义消费者／排除） |
|---|---|---|---|---|---|
| absolute_zero | py_method | `_PromulgationJudgeSession.__post_init__` | `ming_sim/decree.py:315` | KEEP | Protocol/dunder 排除；dataclass `__post_init__` 由 `@dataclass` 机制调用，非零消费者死缝 |
| absolute_zero | py_func | `hline` | `scripts/make_steam_assets.py:46` | KEEP | scripts/spike 排除域本地定义；本文件 `scripts/make_steam_assets.py:46` |
| script_consumer | py_func | `require_fresh_cli_trace` | `ming_sim/cli_backend.py:3873` | KEEP | 本定义 scripts 消费者：`scripts/promulgation_gate_561.py` / `scripts/midzhi_spiral_judge_gate_570.py` / `scripts/family_tail_acceptance_570.py` / `scripts/break_rank_judge_gate_562.py` |
| script_consumer | py_method | `GameDB.get_pending_promulgation_verdicts` | `ming_sim/db.py:15847` | KEEP | 本定义 scripts 消费者：`scripts/promulgation_gate_561.py`（L289/L426/L442） |
| absolute_zero | py_async | `dependency_mismatch_handler` | `web_app.py:4198` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:4197` `@app.exception_handler(DependencyMismatch)` |
| prod_zero_test_only | py_async | `api_menu_new_game` | `web_app.py:4414` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:4413` `@app.post("/api/menu/new_game")` |
| absolute_zero | py_async | `api_menu_continue` | `web_app.py:4518` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:4517` `@app.post("/api/menu/continue")` |
| absolute_zero | py_async | `api_menu_load_save` | `web_app.py:4637` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:4636` `@app.post("/api/menu/load_save/{name}")` |
| absolute_zero | py_async | `api_menu_delete_save` | `web_app.py:4759` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:4758` `@app.delete("/api/menu/saves/{name}")` |
| prod_zero_test_only | py_async | `api_menu_exit` | `web_app.py:4773` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:4772` `@app.post("/api/menu/exit_to_menu")` |
| prod_zero_test_only | py_async | `api_menu_shutdown` | `web_app.py:4802` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:4801` `@app.post("/api/menu/shutdown")` |
| prod_zero_test_only | py_async | `api_menu_save_llm` | `web_app.py:4932` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:4931` `@app.post("/api/menu/llm")` |
| prod_zero_test_only | py_async | `api_state` | `web_app.py:5038` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5037` `@app.get("/api/game/state")` |
| absolute_zero | py_async | `api_retry_mechanical_tail` | `web_app.py:5043` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5042` `@app.post("/api/game/mechanical_tail/retry")` |
| prod_zero_test_only | py_async | `api_memorials_read` | `web_app.py:5054` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5053` `@app.post("/api/memorials/read")` |
| absolute_zero | py_async | `api_secret_orders` | `web_app.py:5091` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5090` `@app.get("/api/secret_orders")` |
| prod_zero_test_only | py_func | `api_history_turns` | `web_app.py:5163` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5162` `@app.get("/api/history/turns")` |
| prod_zero_test_only | py_async | `api_history_turn` | `web_app.py:5170` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5169` `@app.get("/api/history/turn/{turn}")` |
| absolute_zero | py_async | `api_map` | `web_app.py:5212` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5211` `@app.get("/api/map")` |
| absolute_zero | py_async | `api_buildings` | `web_app.py:5217` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5216` `@app.get("/api/buildings")` |
| prod_zero_test_only | py_async | `api_add_favorite` | `web_app.py:5222` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5221` `@app.post("/api/favorites/{minister_name}")` |
| prod_zero_test_only | py_async | `api_remove_favorite` | `web_app.py:5233` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5232` `@app.delete("/api/favorites/{minister_name}")` |
| prod_zero_test_only | py_func | `api_audience_scroll` | `web_app.py:5261` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5260` `@app.get("/api/audience/scroll")` |
| absolute_zero | py_async | `api_audience_chat_history` | `web_app.py:5298` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5297` `@app.get("/api/audience/chat")` |
| prod_zero_test_only | py_async | `api_audience_chat` | `web_app.py:5326` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5325` `@app.post("/api/audience/chat")` |
| absolute_zero | py_async | `api_retry_audience_reply` | `web_app.py:5364` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5363` `@app.post("/api/audience/reply/retry")` |
| prod_zero_test_only | py_async | `api_undo_audience_chat` | `web_app.py:5373` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5372` `@app.post("/api/audience/chat/undo")` |
| absolute_zero | py_async | `api_retry_pending_translation` | `web_app.py:5386` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5385` `@app.post("/api/audience/translation/retry")` |
| prod_zero_test_only | py_async | `api_audience_chat_stream` | `web_app.py:5445` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5444` `@app.post("/api/audience/chat/stream")` |
| prod_zero_test_only | py_async | `api_update_directive` | `web_app.py:5455` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5454` `@app.patch("/api/directives/{directive_id}")` |
| prod_zero_test_only | py_async | `api_delete_directive` | `web_app.py:5500` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5499` `@app.delete("/api/directives/{directive_id}")` |
| prod_zero_test_only | py_func | `api_advance_without_edict` | `web_app.py:5516` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5515` `@app.post("/api/decree/advance_without_edict")` |
| prod_zero_test_only | py_func | `api_issue_decree` | `web_app.py:5642` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5641` `@app.post("/api/decree/issue")` |
| prod_zero_test_only | py_async | `api_issue_decree_stream` | `web_app.py:5733` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5732` `@app.post("/api/decree/issue/stream")` |
| prod_zero_test_only | py_async | `api_resolve_decisions_stream` | `web_app.py:5856` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5855` `@app.post("/api/decree/resolve_decisions/stream")` |
| absolute_zero | py_async | `api_list_saves` | `web_app.py:5979` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5978` `@app.get("/api/saves")` |
| prod_zero_test_only | py_async | `api_create_save` | `web_app.py:5984` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5983` `@app.post("/api/saves")` |
| absolute_zero | py_async | `api_delete_save` | `web_app.py:5997` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:5996` `@app.delete("/api/saves/{name}")` |
| prod_zero_test_only | py_async | `api_load_save` | `web_app.py:6003` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:6002` `@app.post("/api/saves/{name}/load")` |
| prod_zero_test_only | py_async | `api_get_llm_config` | `web_app.py:6014` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:6013` `@app.get("/api/llm/config")` |
| prod_zero_test_only | py_async | `api_set_llm_config` | `web_app.py:6078` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:6077` `@app.post("/api/llm/config")` |
| absolute_zero | py_async | `api_upload_portrait` | `web_app.py:6174` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:6173` `@app.post("/api/consorts/{name}/portrait")` |
| prod_zero_test_only | py_async | `api_delete_portrait` | `web_app.py:6201` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:6200` `@app.delete("/api/consorts/{name}/portrait")` |
| prod_zero_test_only | py_async | `api_get_court_layout` | `web_app.py:6216` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:6215` `@app.get("/api/court_layout")` |
| prod_zero_test_only | py_async | `api_set_court_layout` | `web_app.py:6222` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:6221` `@app.post("/api/court_layout")` |
| absolute_zero | py_async | `api_get_portrait` | `web_app.py:6230` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:6229` `@app.get("/portraits/custom/{name}")` |
| absolute_zero | py_async | `api_admin_tables` | `web_app.py:6239` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:6238` `@app.get("/api/admin/tables")` |
| absolute_zero | py_async | `api_admin_table` | `web_app.py:6244` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:6243` `@app.get("/api/admin/table/{table}")` |
| prod_zero_test_only | py_async | `api_admin_upsert` | `web_app.py:6258` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:6257` `@app.post("/api/admin/table/{table}/upsert")` |
| prod_zero_test_only | py_async | `api_admin_delete` | `web_app.py:6276` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:6275` `@app.post("/api/admin/table/{table}/delete")` |
| absolute_zero | py_async | `admin_page` | `web_app.py:6289` | KEEP | HTTP装饰器路由排除；注册面 `web_app.py:6288` `@app.get("/admin")` |

覆盖核对：上表 = 本轮 ENUM 后仍存在之 absolute_zero（HTTP + scripts 本地定义）+ script_consumer（scripts 真消费的 ming_sim 门面）+ prod_zero_test_only（全为 HTTP 路由）。**ming_sim 内不再残留「仅测试引用」KEEP**。

处置原则（F22-R²）：
- **全仓只剩定义** → DELETE（含级联 dead helpers）。
- **仅被测试引用、且无该定义本身生产消费者／动态注册／庭核排除** → DELETE 定义 + 专属测试。
- **排除**：装饰器 HTTP 路由（须引 `@app.*` 注册行）、Protocol/dunder、scripts/spike 定义及**本定义**被 scripts 消费的门面（须引具体 scripts path）。
- **禁止**：以兄弟现役／模块公开面／「共享能力」笼统词自证 KEEP；测试运行 ≠ 生产消费者。
