# #1900 修内司回执（J20 / J19 / J6含J17）

## HEAD 基线
- 施工前 HEAD：`ee023324b87196eafb04aeef5e45bcb5f0253e19`
- 分支：`ak-roles/1900-j20-j19-j6-fixer-ee023324b`

## 施工前顾问
见 `00-advisor-precheck.md`：授权成立；最简删简；不送 J18/J21/未知委派人护栏。

## 类成员表
| 类 | 路径 |
|---|---|
| J20 | `j20-members.md` + 原始 `j20-enum-raw.txt` |
| J19 | `j19-members.md` + `j19-enum-raw.txt` |
| J6／J17 | `j6-members.md` + `j6-enum-cmds.txt` + `post-rescan.txt` |

## 根因与变更
### J20
- 根因：`bind_decisions_to_candidate_events` 用自由标题补绑 event_id。
- 变更：删除 `title_to_ids` 及标题补绑；仅保留候选内显式 id 与合法 `dossier:`；更新 docstring；`test_decision_event_binding_389` 只保结构化通道。
- 保留：dossier 能力前缀案、显式候选 id。

### J19
- 根因：交办 `merge_participant_roster_entries` 未 `strict_incoming`，字符串/缺档默认「知情」。
- 变更：`declaration_dispatch._attach_commission_staging_fields` 传 `strict_incoming=True`（与押解合并口一致）。
- 保留：完整条目 equality 合并；非法档逐项 invalid_shape；不恢复 id 先赢。

### J6（含 J17 回退）
- 根因：退役 `dossier_reconciliations` 夹具、拒收/异常盯文、持闸被无草案 ValueError 遮蔽、来源负向用名册外甲乙致端点闸遮蔽来源闸。
- 变更：清退役提案夹具；盯文改结构化；持闸补 `allow_empty_decree`+到达持闸分支；关系来源负向恢复真人物+同批合法项；同类 section4 盯文一并改。
- 保留：拒收/回滚/jsonl 同步；SettlementAbort 恢复；引擎 `list_dossier_reconciliations` 真源读缝。

## 聚焦测试
命令前缀七 BIN=/usr/bin/false。
- 最终：`focused-tests-final.log` → **49 passed in 2.72s**（real ~3.18s）

## 变异辨别力
见 `mutations.log`：
- J17 停用来源闸：2 failed；恢复：2 passed
- 持闸分支删除：1 failed；恢复：1 passed
- J20 恢复标题绑：3 failed；恢复：5 passed
- J19 宽松合并探针：基线缺档/字符串 → invalid_shape；宽松 → 知情并落账；临时探针已删

## 自审
- 未新增机制/身份补救/护栏；未改 Soul/治理/席位配置；未 amend/stash/push/PR。
- 未宣称合并或关票。
- 完成前顾问：授权范围内三类已按全仓枚举处置；J21/#1873 登记非本席。
