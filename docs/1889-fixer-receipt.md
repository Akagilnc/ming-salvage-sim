# #1889 修内司回执：冻结判词 J1 + J10

本轮基线 `ddf53881f`（施工前 HEAD）。派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a107b5-f070-73d0-88af-e3e6011de1d0@fixer/fix-packet.md`；判词附件 `attachments/00-1889-judge-newacc-ddf53881f.json`。旧轮回执可由 `git show ddf53881f:docs/1889-fixer-receipt.md` 读取。本文件是施工证据，不另立 authority。

官方依据（施工前检索）：SQLite 事务文档 https://www.sqlite.org/lang_transaction.html —— 读写在连接事务内编排；BEGIN/COMMIT/ROLLBACK 由调用方保留。落法：不新造通用回滚/查询框架；事实 SQL 归 owner；GameDB 只保留事务编排与按表分派。

## 逐类结算

| 类 | 根因 | 正确行为 / 整类处置 | 保留项依据 |
|---|---|---|---|
| J1 持久职责归位不完整 | 判词举证：`turn_directives` 常规已在 `IssueStore`，但召对恢复仍经 `db.py` `_snapshot_table` / `_restore_row_in_tx` / `_delete_row_in_tx` 的 `{table}` 动态 SQL；新档初始化经 `GameDB.table_has_rows` 直查实体表。 | 恢复：`turn_directives`→`IssueStore.snapshot/restore/delete_directive_*`；`pending_actions`→`DossierStore.snapshot_rows/restore_pending_action/delete_pending_action`。初始化：`CharacterStore/FactionStore/ClassStore/ArmyStore/BuildingStore.has_any`，`opening_seed` 只走 owner。删除 `table_has_rows` 与恢复 else 分支动态 SQL；删除死路径 `armies` 回滚特例（不在 `_ROLLBACK_TABLE_PK`）。 | 事务编排（`capture_chat_rollback_snapshot`、差异还原循环、`commit_pending_actions` 等）保留在 GameDB。`pending_actions` 常规编排 SQL 仍在 GameDB/夜/转译调用方（判词允许事务编排保留；非通用动态框架）。案卷对旨稿的 JOIN 读（`directives_with_dossiers` 等）保留为跨实体投影，不另造查询框架。 |
| J10 复杂度下降不足及量化交付缺口 | 相对 `0ca77fecc` 世界记录核心仍净增；宽口径 runtime 仅小幅下降；上回执缺前后行数。 | 删被替代平行入口与死模块：通用动态恢复 SQL、`table_has_rows`、未引用 `person_write_inventory.py`、#1812 已裁定 `/admin` 调试台（`web_app`+`GameDB.admin_*`）、Steam 壳桥（`steam_events.py`、`web/src/steamEvents.ts` 及调用）。回执同口径列施工前 HEAD / 施工后 / 判词基线行数。不为凑行数压缩排版，不为保旧功能或全绿加机制。 | 暂存动作编排、召对撤回编排、实体 Store 本身保留。功能缺口/测试红不在本切片门槛（#1873）。 |

## 全仓枚举命令与成员

### J1（持久职责：常规 / 初始化 / 恢复）

```sh
rg -n 'table_has_rows|_snapshot_table|_restore_row_in_tx|_delete_row_in_tx|SELECT \* FROM \{|SELECT 1 FROM \{' ming_sim --glob '*.py'
rg -n 'FROM turn_directives|INTO turn_directives|UPDATE turn_directives|DELETE FROM turn_directives' ming_sim --glob '*.py'
rg -n 'pending_actions' ming_sim --glob '*.py'
# AST 整类（owned 表 SQL 落在 owner 文件外的候选；JOIN/{X} 白名单误伤另注）
python3 /tmp/1889-j1-enum.py   # 本轮输出 /tmp/1889-j1-members.txt
```

**判词举证成员 → 处置**

| 成员 | 处置 |
|---|---|
| `db.py:table_has_rows` + `opening_seed` 七处调用 | 删除方法；改 `*.has_any` |
| `db.py:_snapshot_table` else `SELECT * FROM {table}`（`turn_directives`/`pending_actions`） | 改走 IssueStore / DossierStore；else 改 `ValueError` |
| `db.py:_restore_row_in_tx` / `_delete_row_in_tx` 动态 UPDATE/INSERT/DELETE | 同上；删除 generic 分支与无用 `armies` 特例 |
| `IssueStore` 常规 turn_directives | 已有；本轮补 snapshot/restore/delete |
| `DossierStore` pending_actions 催办读写 | 已有；本轮补 snapshot/restore/delete |

**复扫（施工后）**：`table_has_rows` 零命中；`db.py` 无 `{table}` 动态 DML；`opening_seed` 仅 `has_any`。真实入口探针：`seed_static_data` → `capture_chat_rollback_snapshot` → `_delete_row_in_tx`/`_restore_row_in_tx` 对 `turn_directives`/`pending_actions` PASS（临时目录已清理）。

**扩扫仍见、本轮按编排保留的 pending_actions 常规 SQL**：`ming_sim/db.py` 约 42 处（stage/commit/list/withdraw 等）、`declaration_dispatch`/`decree_forecast`/`audience_night`/`action_materialize`/`decree` 若干。归「事务编排可保留」；未新造通用框架。完整抽到 DossierStore 薄原语记未结项。

### J10（被替代旧码 / 入口 / 兼容）

```sh
rg -n 'admin_upsert|/api/admin|ADMIN_TABLES|steam_events|person_write_inventory' ming_sim web web_app.py tests --glob '*.{py,ts,tsx}'
git diff --numstat 0ca77fecc HEAD -- ming_sim web_app.py
# 世界记录核心（同判词口径）
for ref in 0ca77fecc HEAD; do
  git ls-tree -r --name-only "$ref" -- ming_sim/db.py ming_sim/entities ming_sim/schema.py ming_sim/opening_seed.py \
    | grep '\.py$' | while IFS= read -r f; do git show "$ref:$f"; done | wc -l
done
```

**删除成员**

| 成员 | 理由 |
|---|---|
| `GameDB.table_has_rows` + 动态恢复 SQL | 被 owner 路径替代的平行持久 |
| `ming_sim/person_write_inventory.py` | 生产零引用；审计已标工具自测可删 |
| `GameDB.admin_*` + `web_app` `/admin` HTML/API | #1812 待拍事项 12「/admin 全表编辑器删」；平行写入口 |
| `ming_sim/steam_events.py` + `web/src/steamEvents.ts` + web_app/测试桥 | #1812 待拍事项 7 Electron/Steam 删 |

## 同口径生产行数

口径 A = 世界记录核心：`ming_sim/db.py` + `ming_sim/entities/**/*.py` + `ming_sim/schema.py` + `ming_sim/opening_seed.py`  
口径 B = 宽口径 runtime：全部 `ming_sim/**/*.py` + `web_app.py`  
不以 `db.py` 单独下降代替整体。

| 参照 | 口径 A（核心） | 口径 B（runtime） | db.py  alone（仅对照） |
|---|---:|---:|---:|
| 判词基线 `0ca77fecc` | 23622 | 91166 | 22574 |
| 施工前 HEAD `ddf53881f` | 24490 | 90329 | 16482 |
| 施工后（本工作树） | 24434 | 89855 | 16369 |
| 相对基线净变 | +812 | −1311（约 −1.44%） | −6205 |
| 相对施工前 HEAD | −56 | −474 | −113 |

`git diff --numstat 0ca77fecc` 对 runtime：施工前 net −837；施工后 net −1311。世界记录核心相对基线仍净增——本轮有删搬，但**不能**署为「核心已大幅低于基线」；相对本轮 HEAD 核心与宽口径均净减。复杂度机制删除见上表（动态恢复框架、admin、steam、死 inventory），非排版压缩。

## 聚焦验证

七变量前缀：

```sh
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
python -m pytest tests/test_settlement_write_guard_393.py \
  tests/test_draft_admission_resubmit_1769.py \
  tests/test_menu_lifecycle_drain_396.py \
  tests/test_menu_continue_stream_1195.py -q --tb=line
```

结果：`75 passed`，约 2.95s（wall ~3.49s）。另：真实入口 seed+rollback 变异探针 PASS（见上）。未跑全量。不为证明修复新造测试。

## 未结项

1. `pending_actions` 常规编排 SQL 仍散在 GameDB 等调用方——可继续收成 DossierStore 薄原语，本轮未整迁（编排保留）。
2. 世界记录核心相对 `0ca77fecc` 仍 +812；家族收尾需继续删简或由 owner 看对比拍「大幅」。
3. 功能缺口/测试红仍归 #1873，本切片不挡。

## 合法性自查

- 未 amend / 未 push / 未开 PR / 未 stash；分支 `ak-roles/1889-j1-j8`。
- 未造通用回滚或查询框架；复用既有 `upsert_by_pk`。
- 未为凑行数压缩排版；未为全绿加机制。
- 自建物仅工作树与 `/tmp`；探针临时目录已清理。
