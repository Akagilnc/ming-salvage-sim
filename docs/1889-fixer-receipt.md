# #1889 修内司回执：冻结判词 J1 + J10（主席核查续修）

本轮基线施工前 HEAD `a47eaad57`；判词基线仍为 `ddf53881f` / 对比基线 `0ca77fecc`。派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a107b5-f070-73d0-88af-e3e6011de1d0@fixer/fix-packet.md`；判词附件 `attachments/00-1889-judge-newacc-ddf53881f.json`。本文件是施工证据，不另立 authority。

官方依据（施工前检索）：Repository / persistence owner — https://www.cosmicpython.com/book/chapter_02_repository.html ；SQLite 事务编排留调用方 https://www.sqlite.org/lang_transaction.html 。落法：事实 SQL 只活在 owner；GameDB/月链/分派只编排并调用 owner；不新造通用回滚/查询框架。

主席核查纠正：上一回执把 `pending_actions`「约 42 处」常规 SQL 及若干调用方统称「事务编排可保留」且又写未整迁——不满足 J1。编排可留，但**持久原语必须归事实 owner**；不得用编排称呼保留平行持久写口。本轮按此处置。

## 逐类结算

| 类 | 根因 | 正确行为 / 整类处置 | 保留项依据 |
|---|---|---|---|
| J1 持久职责归位不完整 | 判词举证动态恢复/初始化已在 `a47eaad57` 归位；主席核查：`pending_actions` 常规 SQL 仍散在 GameDB 与调用方，属平行持久写口。 | 全仓机械枚举 owned 表 SQL；`pending_actions` 全部 SELECT/INSERT/UPDATE/DELETE 迁入 `DossierStore` 薄原语；`db.py`/`declaration_dispatch`/`decree*`/`action_materialize`/`audience_*`/`month_chain` 只调 owner。复扫 outside-owner = 0。 | 事务编排（`commit_pending_actions` 循环、SAVEPOINT、夜闸、forecast discard 联动）仍在 GameDB。跨实体 JOIN 投影（案卷↔旨稿、夜↔已应允暂存）以 owner 方法承载，不另造查询框架。`schema.py` DDL 例外。 |
| J10 复杂度下降 | 被取代旧路与无必要重复仍在；不设行数百分比目标。 | 删 Electron 桌面壳 + Steam 登录面（`web/electron/*`、`steam.d.ts`、`steamworks.js`、`electron-builder`、product scripts）；上一 commit 已删 admin/Steam events/inventory/动态恢复。消除 `pending_actions` 平行写口（机制维度，非整文件排版）。 | 布局几何测试仍可选用 electron 包（非产品壳）；功能缺口/测试红归 #1873。 |

## 全仓枚举命令

```sh
# J1：owned 表 SQL 落在 owner 外的成员（本轮脚本产出）
python3 - <<'PY'
import re
from pathlib import Path
OWNER = {
  'pending_actions': {'ming_sim/entities/dossier/store.py','ming_sim/schema.py'},
  'turn_directives': {'ming_sim/entities/issue/store.py','ming_sim/schema.py'},
}
PATS = [re.compile(rf'(?is)\b{k}\s+([a-z_][a-z0-9_]*)') for k in
        ('FROM','INTO','UPDATE','JOIN')] + [re.compile(r'(?is)\bDELETE\s+FROM\s+([a-z_][a-z0-9_]*)')]
# …扫描 ming_sim/**/*.py，筛 table∈OWNER 且 path∉OWNER[table]
PY

rg -n 'FROM pending_actions|INTO pending_actions|UPDATE pending_actions|DELETE FROM pending_actions|JOIN pending_actions' \
  ming_sim --glob '*.py'
rg -n 'FROM turn_directives|INTO turn_directives|UPDATE turn_directives|DELETE FROM turn_directives' \
  ming_sim --glob '*.py'
rg -n 'table_has_rows|SELECT \* FROM \{|UPDATE \{table\}|DELETE FROM \{table\}' ming_sim --glob '*.py'

# J10
rg -n 'admin_upsert|/api/admin|steam_events|person_write_inventory|electron/main|steamworks' \
  ming_sim web web_app.py --glob '*.{py,ts,tsx,json,cjs}'
```

## J1 成员表（完整，非约数）

### A. 施工前（`a47eaad57`）`pending_actions` SQL outside owner — 60 处

| 文件 | 行号（施工前） |
|---|---|
| `ming_sim/action_materialize.py` | 100, 188 |
| `ming_sim/audience_night.py` | 1106 |
| `ming_sim/audience_translate.py` | 70 |
| `ming_sim/db.py` | 6469, 6530, 11994, 11999, 12005, 12025, 12085, 12102, 12155, 12207, 12216, 12246, 12260, 12294, 12304, 12327, 12338, 12352, 12456, 12588, 12602, 12608, 12630, 12757, 12801, 12808, 12824, 12897, 12905, 12916, 13082, 13113, 13442, 13453, 13485, 13523, 13530, 13537, 13554, 13560, 13573, 13815, 15142 |
| `ming_sim/declaration_dispatch.py` | 254, 1580, 1985, 2031, 2071, 2076 |
| `ming_sim/decree.py` | 806 |
| `ming_sim/decree_forecast.py` | 168, 267, 359, 461, 501 |
| `ming_sim/month_chain.py` | 140 |

合计 **60**。另：`list_pending_actions` 等编排方法调用点不是 SQL，不计入平行写口。

### B. 施工后 outside-owner

| 表 | outside owner+schema 命中 |
|---|---:|
| `pending_actions` | **0** |
| `turn_directives`（排除 dossier 跨实体 JOIN 投影） | **0** |
| 动态 `{table}` DML（恢复/init） | **0**（`column_write`/`fiscal_container`/`character_knowledge` 为既有 owner 内 upsert 工具，非 GameDB 平行口） |

施工后全部 `pending_actions` SQL 仅在：

| 文件 | 处置 |
|---|---|
| `ming_sim/entities/dossier/store.py` | owner 真源（51 处 SQL；含既有 urge/snapshot/restore + 本轮薄原语） |
| `ming_sim/schema.py` | DDL 例外 |

### C. 有依据 exceptions

| 成员 | 依据 |
|---|---|
| `schema.py` `CREATE TABLE pending_actions` | DDL 非运行时写口 |
| `DossierStore.directives_with_dossiers` / `committed_directive_candidates` JOIN `turn_directives` | 跨实体投影；IssueStore 仍是 turn_directives 权威写口 |
| `DossierStore.closed_nights_with_approved_pending` JOIN `audience_nights` | 跨实体投影，方法落在 pending 事实 owner |
| `DossierStore.army_pay_row` JOIN `armies` | 案卷读投影，非军队写口 |
| GameDB `capture_chat_rollback_snapshot` / `_ROLLBACK_TABLE_PK` 中的表名字符串 | 编排分派键，不含 SQL |
| `opening_seed` `*.has_any` | 已在 `a47eaad57` 归各实体 owner |

### D. 处置映射（平行 SQL → owner 原语）

| 原平行形态 | owner 方法 |
|---|---|
| INSERT pending | `insert_pending_action` |
| UPDATE payload / clear approval / bump version / rehome night | `set_pending_payload*` / `rehome_pending_payload` |
| UPDATE status / night_approved / held_over / committed_directive_id / carry turn | `set_pending_status` / `mark_pending_night_approved` / `hold_over_pending_actions` / `set_committed_directive_id` / `carry_pending_to_turn` |
| SELECT 各类投影 | `pending_action_row` / `pending_*_row` / `list_pending_*` / `list_pending_for_translate` / … |
| DELETE withdraw/drop/discard | `delete_pending_if_pending` / `delete_pending_matching_minister` / `delete_pending_directives_for_turn` / `delete_failed_secret_order_intents` |

GameDB 的 `stage_pending_action` / `commit_pending_actions` / `withdraw_*` 等**保留为编排**，内部只调上述原语。

## J10 成员表

| 成员 | 处置 | 复杂度维度 |
|---|---|---|
| `pending_actions` 平行持久写口（60 处） | 整迁 owner，outside=0 | **重复持久路径消除**（1 机制：双写口 → 单 owner） |
| `web/electron/main.cjs` `preload.cjs` `steam.cjs` | 删除 | **产品壳机制删除**（#1812 待拍 7） |
| `web/src/steam.d.ts` | 删除 | Steam 登录类型面 |
| `web/package.json` main + electron scripts；`steamworks.js`；`electron-builder` | 删除 | 打包/登录依赖图 |
| （上轮 `a47eaad57`）`table_has_rows`+动态恢复、`person_write_inventory`、`/admin`、`steam_events` | 已删 | 平行入口/死模块 |

不凑排版；不为全绿加机制。核心行数相对 `0ca77fecc` 仍净增——**不以行数百分比署完成**；复杂度看平行路径与机制数。

## 同口径生产行数

口径 A = 世界记录核心：`ming_sim/db.py` + `ming_sim/entities/**/*.py` + `ming_sim/schema.py` + `ming_sim/opening_seed.py`  
口径 B = 宽口径 runtime：全部 `ming_sim/**/*.py` + `web_app.py`

| 参照 | 口径 A（核心） | 口径 B（runtime） | db.py alone |
|---|---:|---:|---:|
| 判词基线 `0ca77fecc` | 23622 | 91166 | 22574 |
| 判词时 HEAD `ddf53881f` | 24491 | 90329 | 16482 |
| 上轮 `a47eaad57` | 24434 | 89855 | 16369 |
| 本轮工作树（commit 前） | 24715 | 90090 | 16160 |
| 相对 `0ca77fecc` | +2093 | −1076 | −6414 |
| 相对 `a47eaad57` | +281 | +235 | −209 |

说明：本轮核心行数上升主要因 SQL 搬入 `DossierStore` 薄原语（+~490）而编排壳未整段删除；**平行写口 60→0** 才是 J1 完成判据。宽口径相对基线仍净减；Electron/Steam 删减主要在 `web/` 非口径 B。

`git diff --numstat 0ca77fecc -- ming_sim web_app.py`（工作树）：added 11604 deleted 12680 net **−1076**。

### 复杂度机制量化

| 维度 | 初始 `ddf53881f` | 最终（本轮） |
|---|---|---|
| `pending_actions` outside-owner SQL | 60（上轮回执误标「编排可留」） | **0** |
| 通用动态恢复 `{table}` DML（GameDB） | 有（判词举证） | **0**（上轮已删） |
| `/admin` 平行写入口 | 有 | **0**（上轮） |
| Steam events 桥 | 有 | **0**（上轮） |
| Electron 桌面壳 + Steam 登录 | 有 | **0**（本轮） |
| 死模块 `person_write_inventory` | 有 | **0**（上轮） |

## 测试改动复核（上轮 + 本轮）

上轮 `a47eaad57` 删 steam/admin 断言与 monkeypatch：对应功能面已删，属契约跟随删除，**非**删失败路径凑绿。本轮未改测试、未 mock、未放松断言。

## 聚焦验证

```sh
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
python3 -m pytest tests/test_settlement_write_guard_393.py \
  tests/test_draft_admission_resubmit_1769.py \
  tests/test_menu_lifecycle_drain_396.py \
  tests/test_menu_continue_stream_1195.py \
  tests/test_declaration_dispatch_1835.py \
  tests/test_decree_forecast_1861.py \
  tests/test_audience_night_498.py \
  tests/test_audience_undo_506.py \
  tests/test_audience_restore_505.py -q --tb=line
```

结果：`161 passed`，约 9.77s。另：GameDB+DossierStore 真入口 insert/list/status/snapshot 探针 PASS；临时目录已清理。未跑全量。未造证明性测试。

## 未结项

1. 世界记录核心相对 `0ca77fecc` 仍净增；家族收尾继续删简，由 owner 看复杂度对比拍「大幅」。
2. 功能缺口/测试红仍归 #1873。
3. `electron` 包仍留在 web devDependencies，仅供布局几何测试——非产品壳；若家族要连测试几何一起扔可另票。

## 合法性自查

- 未 amend / 未 push / 未开 PR / 未 stash；分支 `ak-roles/1889-j1-j8`；保留既有 commit，仅追加。
- 未造通用回滚或查询框架；复用既有 `upsert_by_pk`。
- 未为凑行数压缩排版；未为全绿加机制；未保全旧功能。
- 自建物仅工作树与 `/tmp`；探针临时目录已清理。
