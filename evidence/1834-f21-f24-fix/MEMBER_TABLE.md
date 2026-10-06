# 1834 F21–F24 成员表（本轮全仓枚举）

## 枚举命令

见 `ENUM_CMDS.txt` / `RESCAN.txt`。

## F21 自由正文保真未贯穿写入与供料

类定义：写入与供料链对自由字段零删改；机器键规范化与局部判空不禁止；退役链删除不修补。

| 成员 | 处置 | 理由 |
|---|---|---|
| `declaration_dispatch._commission_grant_payload` purpose 写入 strip | FIX | 自由 purpose 写入 pending 保原文 |
| `db.set_character_status` → interrupt note `.rstrip('；')` | FIX | 退场原因自由正文写入 execution_note 保原文 |
| `cli_backend` stalled 案卷 title/body 供料 strip | FIX | 供模型事实块保原文 |
| station / highlights（上轮已修） | KEEP已正确 | 庭核有效 |
| materials 判空副本 | KEEP | 局部判空 |
| purpose/title 作枚举匹配（ECONOMY_PURPOSES、PERSON_IDENTITY_TITLES 等） | KEEP | 机器键规范化 |
| region/army/building 文本字段已 F16 保真 | KEEP | 写入链已正确 |

## F22 退役闭包及专属测试漏删

谓词：已退役独占闭包 + 无生产 Load 消费者 + 专属测试；非「零引用即删」新法。独立 API / 动态注册 / 别名保留。

| 成员 | 处置 |
|---|---|
| `validate_rescript_draft_items` + 独占 helpers（`_item_failure`/`_top_failure`/`_apply_option_heal`/…）+ `RescriptOptionMissingFailure/Batch` | DELETE |
| `execution_distortion_weight` + `AUTHORITY_COMMAND_RELIEF` + decree 未用 import | DELETE |
| `run_agent_stream_text`（`_agent_run_accepts_stream` 仍被 `run_agent_text` 用 → KEEP） | DELETE 定义 |
| `stage_grant_allocation_candidate` | DELETE |
| 专属测试：validate 案、distortion 案、stream 三案、stage_grant 一案 | DELETE |
| `for_role` / `_llm_for_role` 别名 | KEEP |
| `prepare_character_materials` 独立材料 API | KEEP |
| HTTP `@app.*` 动态注册（非 admin） | KEEP |

## F23 御批删除的旧入口

| 成员 | 处置 |
|---|---|
| CLI `review_directives` add/edit 手写拟诏 | DELETE 入口；del/issue/back/恢复 issue 保留 |
| `web_app` `/admin` + `/api/admin/*` + `_ADMIN_HTML` | DELETE |
| `GameDB.ADMIN_TABLES` + `admin_*` | DELETE 独占 |
| `capture_manual_directive_payload` / web PATCH update | KEEP 共享现役 |
| `session.add_directive` | KEEP 共享（测试/既有草稿路径） |

## F24 CLI 自动首选批红

| 成员 | 处置 |
|---|---|
| `_submit_first_cli_decisions` + `project_preferred_hitl_choice` | DELETE |
| CLI `play_turn` awaiting | FIX：`_report_cli_hitl_gap` 如实报告并 return |
| scripts `family_tail` / `agy_turn_probe` 自动代裁 | FIX：停 awaiting 报告 |
| 未完成转译恢复（FRONT_HALF_DONE → issue） | KEEP |
