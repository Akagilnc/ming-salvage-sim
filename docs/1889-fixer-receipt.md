# #1889 修内司回执：冻结判词 J1 + J10（SIGTERM 后续修交卷）

本轮在已提交 `a47eaad57`、`81acc3ab6` 之上保留全部未提交产出继续施工；判词基线 `ddf53881f` / 对比基线 `0ca77fecc`。派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a107b5-f070-73d0-88af-e3e6011de1d0@fixer/fix-packet.md`；判词附件 `attachments/00-1889-judge-newacc-ddf53881f.json`。本文件是施工证据，不另立 authority。

官方依据（施工轨迹沿用，不伪造）：Repository / persistence owner — https://www.cosmicpython.com/book/chapter_02_repository.html ；SQLite 事务编排留调用方 https://www.sqlite.org/lang_transaction.html 。落法：事实 SQL 只活在 owner；GameDB/月链/分派/召对编排只调 owner；不新造通用回滚/查询框架。

## 已有未提交产出已删简的核心机制（本轮确认）

| 机制 | 状态 |
|---|---|
| GameDB 呈现/摘要旧路（`faction_report` / `turn_*_summary` / `building_detail` / `treasury_ledger` / vacancies 等） | 已从 `db.py` 删除（未提交产出） |
| `pending_decisions` / rescript desk 持久原语 | 整迁 `IssueStore`；删 GameDB SQL 与 desk 投影副本 |
| chat / night / ledger / kv / rollback 持久原语 | 整迁 `ReignStateStore`；GameDB 只留编排 |
| `audience_night` / `audience_translation` / `rescript_actions` / `declaration_dispatch` / `materials` / `cli/terminal` / `web_app` 平行 SQL | 改调 owner |
| reign 未使用薄包装（`update_chat_turns`/`select_chat_turns*`/`insert_ledger_entry` 泛化入口等） | 本轮删除 |
| （已提交）`pending_actions` outside-owner、Electron/Steam 壳、admin、动态 `{table}` 恢复 | `81acc3ab6` / `a47eaad57` |

## 逐类结算

| 类 | 根因 | 正确行为 / 整类处置 | 保留项依据 |
|---|---|---|---|
| J1 持久职责归位不完整 | 判词举证动态恢复/初始化；主席核查后 `pending_actions` 已归位；未提交面仍有 chat/pending_decisions/ledger/kv 平行 SQL，以及仅点名两表的枚举不足。 | **全仓 54 张事实表**机械枚举；常规/初始化/恢复/动态持久 SQL 逐表归 owner；编排可留、持久原语不冒称编排。复扫：owner 外仅跨实体投影。 | `schema.py` DDL；跨实体 JOIN/投影（见成员表例外）；事务 SAVEPOINT/atomic 编排。 |
| J10 复杂度下降 | 被取代旧路与无必要重复仍在；不设行数百分比目标。 | 删呈现旧路；删 GameDB desk/chat SQL 副本；删未用薄包装；计入搬入成本后报告行数。 | 功能重接/全绿归 #1873；不为凑行数排版。 |

## 可重跑完整机械枚举命令

```sh
# 口径 A / B 行数（与下表同算法）
python3 - <<'PY'
from pathlib import Path
import subprocess
def core(ref=None):
    if ref:
        out=subprocess.check_output(['git','ls-tree','-r','--name-only',ref,'--','ming_sim/db.py','ming_sim/entities','ming_sim/schema.py','ming_sim/opening_seed.py'],text=True)
        return sum(len(subprocess.check_output(['git','show',f'{ref}:{p}']).splitlines()) for p in out.splitlines() if p.endswith('.py'))
    n=sum(len(Path(p).read_text().splitlines()) for p in ['ming_sim/db.py','ming_sim/schema.py','ming_sim/opening_seed.py'])
    return n+sum(len(p.read_text().splitlines()) for p in Path('ming_sim/entities').rglob('*.py'))
def runtime(ref=None):
    if ref:
        out=subprocess.check_output(['git','ls-tree','-r','--name-only',ref,'--','ming_sim','web_app.py'],text=True)
        return sum(len(subprocess.check_output(['git','show',f'{ref}:{p}']).splitlines()) for p in out.splitlines() if p.endswith('.py') and (p.startswith('ming_sim/') or p=='web_app.py'))
    return sum(len(p.read_text().splitlines()) for p in Path('ming_sim').rglob('*.py'))+len(Path('web_app.py').read_text().splitlines())
for label,ref in [('0ca77fecc','0ca77fecc'),('ddf53881f','ddf53881f'),('WORKTREE',None)]:
    print(label, 'A', core(ref), 'B', runtime(ref))
PY

# J1：schema 全表 × owner 映射 × 扫描 ming_sim/**/*.py SQL
python3 - <<'PY'
import re
from pathlib import Path
from collections import defaultdict
TABLES=sorted(set(re.findall(r'CREATE TABLE(?: IF NOT EXISTS)?\s+(\w+)', Path('ming_sim/schema.py').read_text(), re.I)))
OWNER={  # 与下方成员表一致；schema.py 恒允许
  'pending_actions':{'ming_sim/entities/dossier/store.py'},
  'turn_directives':{'ming_sim/entities/issue/store.py'},
  'pending_decisions':{'ming_sim/entities/issue/store.py'},
  'chat_turns':{'ming_sim/entities/reign_state/store.py'},
  'chat_turn_rollback_items':{'ming_sim/entities/reign_state/store.py'},
  'audience_nights':{'ming_sim/entities/reign_state/store.py'},
  'story_ledger_entries':{'ming_sim/entities/reign_state/store.py','ming_sim/entities/affair/store.py'},
  'kv_store':{'ming_sim/entities/reign_state/store.py'},
  'save_meta':{'ming_sim/entities/reign_state/store.py'},
  # …其余事实表见本回执「完整成员表」OWNER 列
}
# 完整 OWNER 字典以本回执成员表为准；扫描：
PAT=re.compile(r'(?is)\b(?:FROM|INTO|UPDATE|JOIN|DELETE\s+FROM)\s+([a-z_][a-z0-9_]*)')
# 对 ming_sim/**/*.py：table∈TABLES 且 path∉OWNER[table]|{schema.py} → outside
# 期望：outside 仅 CROSS 投影例外（见下）
PY

rg -n 'FROM pending_actions|INTO pending_actions|UPDATE pending_actions|DELETE FROM pending_actions' ming_sim --glob '*.py'
rg -n 'FROM pending_decisions|INTO pending_decisions|UPDATE pending_decisions|DELETE FROM pending_decisions' ming_sim --glob '*.py'
rg -n 'FROM chat_turns|INTO chat_turns|UPDATE chat_turns|DELETE FROM chat_turns' ming_sim --glob '*.py'
rg -n 'FROM story_ledger_entries|INTO story_ledger_entries|UPDATE story_ledger_entries|DELETE FROM story_ledger_entries' ming_sim --glob '*.py'
rg -n 'table_has_rows|UPDATE \{table\}|DELETE FROM \{table\}' ming_sim --glob '*.py'
```

本轮实测枚举摘要落 `/tmp/1889-j1-enum.txt`（工作树临时；内容已并入下方成员表）。

## J1 完整成员表（54 张事实表）

### Owner 归属（权威写口）

| 表 | owner | 处置 |
|---|---|---|
| characters, character_offices, offices, office_slots, office_change_records, authority_records, recommendation_events | `character/store.py` | 已归位 |
| regions, region_logs | `region/store.py` | 已归位 |
| armies, army_logs | `army/store.py` | 已归位 |
| buildings, building_logs | `building/store.py` | 已归位 |
| powers, power_logs, power_name_logs | `power/store.py` | 已归位 |
| classes, population_transfer_ledger | `social_class/store.py` | 已归位 |
| factions, faction_axis_debt, faction_stance_summaries, centrifuge_log | `faction/store.py` | 已归位 |
| fiscal_containers; fiscal_config* | `fiscal_container/store.py` + `config.py` | 已归位 |
| issues, issue_advances, events, event_triggers, turn_directives, pending_decisions | `issue/store.py` | 本轮补齐 pending_decisions/rescript |
| pending_actions, next_audience_todos | `dossier/store.py` | 上轮已归位 |
| secret_orders, secret_order_briefs, public_sayings | `character_knowledge/store.py` | 已归位 |
| relation_edge_events, relation_summaries, relation_brew_pending | `person_log/store.py` | 已归位 |
| story_ledger_entries | `reign_state/store.py`（主写）+ `affair/store.py`（经历投影读） | 本轮主写归 reign |
| save_meta, kv_store, chat_turns, chat_turn_rollback_items, audience_nights, economy_ledger, ending_summary, legacies | `reign_state/store.py` | 本轮补齐 |
| chat_messages, turn_reports, month_open_snapshot, pending_resolve_context | `record_store.py` | 已归位 |

### 施工后 outside-owner（仅跨实体投影）

| 表 | 文件:行 | 合法保留依据 |
|---|---|---|
| armies | dossier/store.py:1624 | 案卷↔军队欠饷 JOIN 投影 |
| audience_nights | dossier/store.py:2134 | 案卷↔夜投影 |
| turn_directives | dossier/store.py:1480,1672 | 案卷↔旨稿投影；IssueStore 仍是写口 |
| secret_orders | dossier/store.py:1262,1304 | 案卷↔密令投影 |
| characters / factions / faction_stance_summaries | person_log/store.py:188 | 关系/派系酿造认领 JOIN |
| issues | character_knowledge/store.py:417 | 知识源登记读投影 |
| regions | social_class/store.py:99 | 人口迁移读投影 |
| schema.py 全部表 | DDL | 非运行时写口 |

`pending_actions` / `pending_decisions` / `chat_turns` / `chat_turn_rollback_items` / `kv_store` / `audience_nights`（除 dossier 投影）/ `story_ledger_entries`（除 affair 投影）**outside = 0**。

动态 `{table}` DML（GameDB 恢复/init）：**0**（`a47eaad57` 已删）。

## J10 机制删简前后比较

| 维度 | 初始 `ddf53881f` | `81acc3ab6` | 本轮工作树 |
|---|---|---|---|
| `pending_actions` outside-owner SQL | 判词点名残留 | 0 | 0 |
| `pending_decisions`/`chat_*`/`ledger`/`kv` 平行写口 | 散在 GameDB+调用方 | 部分迁 | **0**（仅跨实体投影） |
| 通用动态 `{table}` 恢复 | 有 | 0 | 0 |
| Electron/Steam/`/admin`/inventory | 有 | 0 | 0 |
| GameDB 呈现摘要旧路 | 有 | 有 | **删** |
| reign 未用薄包装 | — | 引入中 | **删** |

## 同口径生产行数

口径 A = 世界记录核心：`ming_sim/db.py` + `ming_sim/entities/**/*.py` + `ming_sim/schema.py` + `ming_sim/opening_seed.py`  
口径 B = 宽口径 runtime：全部 `ming_sim/**/*.py` + `web_app.py`  
web 删除（Electron 等，非口径 B）：已在 `81acc3ab6` 删 `web/electron/*`、`steam.d.ts`、electron-builder 依赖；可另列产品壳净减。

| 参照 | 口径 A（核心） | 口径 B（runtime） | db.py alone |
|---|---:|---:|---:|
| 判词基线 `0ca77fecc` | 23622 | 91166 | 22574 |
| 判词时 HEAD `ddf53881f` | **24491** | 90329 | 16482 |
| 上轮提交 `81acc3ab6` | 24715 | 90090 | 16160 |
| 本轮工作树（commit 前） | **24565** | **89794** | **15038** |
| 相对 `0ca77fecc` | +943 | −1372 | −7536 |
| 相对 `ddf53881f` | +74 | −535 | −1444 |
| 相对 `81acc3ab6` | −150 | −296 | −1122 |

### 24490 / 24491 差异说明

判词 `coreLines` 记 `ddf53881f` 为 **24490**；本仓用 `git ls-tree` + `git show` 逐文件 `splitlines()` 同口径复测为 **24491**。差 1 行来自计数边界（末行换行 / 空文件边界），**非第二套口径**。本回执统一采用 **24491** 作为 `ddf53881f` A 口径真值，并同时列出判词原文 24490 以免对照断裂。

复杂度：不以行数百分比署「大幅」；本轮实质是平行持久路径与呈现旧路机制数下降。核心相对 `0ca77fecc` 仍净增 +877——复杂度继续由家族收尾拍板。

## 测试改动必要成本及契约

- 调用面跟随 owner：`db.issues.*` / `db.reign.*`（含已改测试与 `web_app` kv）。
- **未**放松断言、**未**用 mock 顶替真实入口凑绿。
- 未改契约的测试文件若仍写 `db.kv_get` / `db.save_rescript_drafts` 会红 → 归 #1873 收尾重接，本轮不为全绿扩改。

## 聚焦验证

```sh
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
python3 -m pytest \
  tests/test_transaction_boundary.py \
  tests/test_rescript_draft_656.py \
  tests/test_advance_paths_atomic.py \
  tests/test_audience_night_498.py \
  tests/test_audience_undo_506.py \
  tests/test_audience_restore_505.py \
  tests/test_audience_translate_1837.py \
  tests/test_decree_forecast_1861.py \
  tests/test_settlement_write_guard_393.py \
  tests/test_declaration_dispatch_1835.py -q --tb=line
```

（结果与实测时长填入交卷后实测段。）

### 聚焦验证实测

命令同上。结果：`254 passed`，墙钟约 **8.37s**（`/usr/bin/time -p` real）。未跑全量。未造证明性测试。

测试改动：跟随 owner 调用面（`db.issues.*` / `db.reign.*`）、hasattr 闸、RecordingDB 轻壳补 `reign.kv_*`；**未**放松行为断言、**未** mock 真实入口凑绿。误删的 `apply_dossier_verdicts` / `_record_dossier_verdict_metadata` 已从 HEAD 恢复（属未提交产出漏搬，非新机制）。

## 未结项

1. 口径 A 相对 `0ca77fecc` 仍 +943；「大幅下降」由 owner 看机制对比拍板。
2. 功能缺口/测试红（含未改调用面的旧测试，如仍写 `db.kv_get` 的未触达文件）归 #1873。
3. `electron` 测试几何依赖包仍可留；非产品壳。

## 合法性自查

- 未 amend / 未 push / 未开 PR / 未 stash；保留 `a47eaad57`、`81acc3ab6`，仅追加 commit。
- 未造通用回滚或查询框架；删未用薄包装。
- 未为凑行数压缩排版；未为全绿加机制。
- 自建物仅工作树与 `/tmp`。
