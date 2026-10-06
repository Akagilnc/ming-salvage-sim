# #1902 修内司 J1–J4 交卷（01a11209 终判）

- 工作树：`Ming_LLM-1902-w5`
- 判词：`01a11209-c090-7524-9191-3436b624c3af@judge` submission.latest.accepted
- 基线 HEAD：`03423e09f`
- FIX SHA：`d96a82d27c4eea6a5c0a403185a6551de0a327fa`（本回执 stamp 另提交）
- 成员表：`evidence/issue-1902/j1j2j3j4-member-tables.json`
- 聚焦日志：`evidence/issue-1902/j1j2j3j4-focus-pytest.txt`
- **不宣称合并/关票**；未 stash/push/PR/amend；未改治理文件与宿主席位

七 BIN 前缀全程显式展开。

## 枚举谓词与成员（修前）

### J1「T2：自由文本参与机械控制」
- **谓词（类定义全文）**：自由文本参与机械控制（含已结异常正则／交付 strip 与未结正文子串／前缀同人证明；不得收窄）。
- **枚举命令**：`rg -n --type py '_person_grounded_in_source|_grounding_source_text|_MIN_PERSON_PREFIX_LEN|_roster_identity_forms|_all_roster_identity_forms|form in text|prefix not in text' ming_sim web_app.py`
- **本轮 actionable 成员**：`draft_intent` 的 `_person_grounded_in_source` 及其专属证明（`_grounding_source_text`／`_roster_identity_forms`／`_all_roster_identity_forms`／`_MIN_PERSON_PREFIX_LEN`／patch 接地闸／backfill 的 player_message 参数）。

### J2「换库恢复生命周期阶段混淆」
- **谓词**：旧关闭未完成、文件尚未替换时仍无条件删库／恢复／重建。
- **枚举命令**：`rg -n --type py 'backup_complete|delete_sqlite_db_files_or_raise|hot replace recovery' ming_sim/save_slots.py`
- **成员**：`save_slots.replace_database` 失败分支（`backup_complete` 在 close 前为真，close 失败仍恢复）。

### J3「T4：共享职责仍归入口」
- **谓词**：共享资格／业务编排仍由入口拥有。
- **枚举命令**：`rg -n --type py 'def can_undo_last_chat|def undo_last_chat|db\\.undo_chat_turn|cancel_turn_translation' web_app.py ming_sim/session.py ming_sim/cli`
- **成员**：`WebGame.can_undo_last_chat`／`undo_last_chat` 整段编排；session 仅有 note/refresh 碎片。

### J4「搬迁引入无语义生产兼容层」
- **谓词**：为 monkeypatch 新增的无语义生产间接层。
- **枚举命令**：`rg -n --type py 'def _transport|Lazy transport|_transport\\(' ming_sim/draft_intent.py`
- **成员**：`draft_intent._transport`／`_log`／`_loads_lenient`／`_run_backend_for_config`。

## 逐类修复

### J1
- **根因**：名册自愈把玩家/失败槽正文子串与唯一前缀当同人证明。
- **修复**：删除上述五件套；`_patch_roster_slots_one_to_one` 只认结构化在册名 + 槽位一一对应；去掉 `player_message`/`failed_slot_refs`。
- **复扫**：谓词生产机制 0 hit（仅既有已结注释）。

### J2
- **根因**：`backup_complete=True` 在 close 前；close 抛错仍删库/复制备份/重建。
- **修复**：`old_closed`／`files_replaced`；close 未完成且文件未动 → 原样上抛，不碰主库。
- **复扫**：恢复条件 `not backup_complete or (not old_closed and not files_replaced)`。

### J3
- **根因**：撤回资格与整轮编排在 Web。
- **修复**：`GameSession.can_undo_last_audience_chat`／`undo_last_audience_chat` + `AudienceChatUndoError`／`AudienceChatUndoResult`；Web 只映射 HTTP 与呈现；测试假壳挂共核方法。
- **复扫**：`undo_chat_turn`／`cancel_turn_translation` 在 session；web 无 DB 逆转体。不新增 CLI 撤回玩法。

### J4
- **根因**：为保测试补丁位置增加四无语义转发。
- **修复**：删四函数；`import ming_sim.cli_backend as _cli_backend` 直接属性调用。
- **复扫**：无 `_transport`／包装 def。

## 聚焦测试

```
238 passed in 11.48s
```

判词同款文件 + `test_audience_background` / `test_new_game_write_path_1749` / `test_structured_decree_contract_1624`。

## 探针

```
J1_PATCH {"patched": "郭允厚", "no_prose_helpers": true}
J2_CLOSE {"exc": "close boom injected", "inode_same": true, "rebuilt": 0, "disposed": 0, "file_exists": true}
J3_OWN {"session_has": true, "web_thin": true}
J4_DIRECT {"no_wrappers": true, "module_ref": true}
ALL_PROBES_OK
```

## 质量 / 合法性

- 未改 CLAUDE.md / AGENTS.md / CONTEXT.md / ADR / 席位。
- 未新增监督层、恢复协议、兼容层、证明测试、词表/否定句解析。
- 禁止 amend/stash/push。

## 剩余

- 家族收尾/合并/关票不在授权。
