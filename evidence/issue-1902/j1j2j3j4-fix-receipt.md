# #1902 修内司 J1–J4 交卷

- 判词真源：`~/.ak-roles/books/Ming_LLM/1902/runs/01a11209-c090-7524-9191-3436b624c3af@judge/current.json` submission.latest.accepted
- 成员表：`evidence/issue-1902/j1j2j3j4-member-tables.json`
- 聚焦日志：`evidence/issue-1902/j1j2j3j4-focus-pytest.txt`
- **不宣称合并/关票**；未 amend/stash/push

七 BIN 前缀全程。

## 四类

### 1. T2：自由文本参与机械控制（J1）
- **谓词**：自由文本参与机械控制（含已结异常正则／交付 strip 与未结正文子串／前缀同人证明；不得收窄）。
- **本轮成员**：`_person_grounded_in_source` 及其专属证明（`_grounding_source_text`／`_roster_identity_forms`／`_all_roster_identity_forms`／`_MIN_PERSON_PREFIX_LEN`／patch 接地闸）。
- **修复**：拆除上述机制；槽级修补只认结构化名册校验 + 模型交付规范名。
- **复扫**：无生产接地函数；仅注释命中。

### 2. 换库恢复生命周期阶段混淆（J2）
- **谓词**：旧关闭未完成、文件尚未替换时仍无条件删库／恢复／重建。
- **成员**：`save_slots.replace_database` 失败分支（`backup_complete` 后、close 失败仍恢复）。
- **修复**：引入 `old_closed`／`files_replaced`；close 未完成且未替换文件时直接上抛，不碰主库。
- **复扫**：恢复路径仅在 close 完成或文件已替换后。

### 3. T4：共享职责仍归入口（J3）
- **谓词**：共享资格／业务编排仍由入口拥有。
- **本轮成员**：`WebGame.can_undo_last_chat`／`undo_last_chat` 整段编排。
- **修复**：迁至 `GameSession.can_undo_last_audience_chat`／`undo_last_audience_chat`（+ `AudienceChatUndoError`／`AudienceChatUndoResult`）；Web 只映射 HTTP 与呈现缓存。
- **复扫**：入口无 `db.undo_chat_turn`／`cancel_turn_translation` 业务体；不新增 CLI 撤回玩法。

### 4. 搬迁引入无语义生产兼容层（J4）
- **谓词**：为 monkeypatch 新增的无语义生产间接层。
- **成员**：`draft_intent._transport`／`_log`／`_loads_lenient`／`_run_backend_for_config`。
- **修复**：删除四函数；`import ming_sim.cli_backend as _cli_backend` 直接调用。
- **复扫**：无 `_transport`／Lazy binding。

## 聚焦测试

```
238 passed in 11.41s
```

## 质量
未改治理文件／席位；无新监督层／兼容转发／证明测；禁止 amend/stash/push。
