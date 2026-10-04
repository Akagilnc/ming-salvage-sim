# #1889 修内司回执：冻结判词 J1 + J10（框架表漏枚举补齐交卷）

本轮在已提交 `a47eaad57`、`81acc3ab6`、`7cfce2e5b`、`ba6a5cc53` 之上保留全部历史继续施工；判词基线 `ddf53881f` / 对比基线 `0ca77fecc` / 施工前 `ba6a5cc53`。派单：`~/.ak-roles/books/Ming_LLM/1889/runs/01a107b5-f070-73d0-88af-e3e6011de1d0@fixer/fix-packet.md`；判词附件 `attachments/00-1889-judge-newacc-ddf53881f.json`。本文件是施工证据，不另立 authority。

官方依据（施工轨迹沿用，不伪造）：Repository / persistence owner — https://www.cosmicpython.com/book/chapter_02_repository.html ；SQLite 事务编排留调用方 https://www.sqlite.org/lang_transaction.html ；Agno merge 官方原语 `agno.db.utils.merge_runs_table_with_legacy_blob`。落法：事实 SQL 只活在 owner；GameDB/月链/分派/召对编排只调 owner；不新造通用回滚/查询框架/新 owner。

## 更正：原「全仓 0」结论的范围错误

前版回执称 OUTSIDE_WRITE/READ=0，**枚举全集仅 `schema.py` CREATE TABLE（54 张）**。框架表 `agno_sessions` / `agno_runs` 不在 schema DDL，故扫描看不见；当时 GameDB 仍直接 PRAGMA/SELECT/UPDATE/DELETE 这两张表（约 `db.py` 5352–5520），却被误报为全仓 0。

**更正表述**：原范围内（schema 54 表）OUTSIDE=0 仍成立；**完整真实 SQL 全集下该结论错误**。本轮按「真实 SQL + schema CREATE + store CREATE + PRAGMA/sqlite_master 发现」重扫。

审查已举证真实事实（本轮核对仍成立于施工前 `ba6a5cc53`）：
- GameDB 直读写 `agno_sessions` / `agno_runs`：`_agno_session_columns`（PRAGMA）、`_agno_table_run_dicts`（SELECT agno_runs）、`_agno_legacy_runs_blob`、`_rewrite_session_legacy_runs_blob`、`_truncate_agno_runs_in_tx`
- `ReignStateStore` 已有 `agno_runs_before` 记账；持久职责本应分居 → 本轮整迁会话历史持久原语到 `ReignStateStore`
- GameDB 只留 undo/fail/reconcile 事务编排调用 `self.reign._truncate_agno_runs_in_tx`；已删被替代薄包装（无 GameDB `agno_runs_length` / `truncate_*` 残留）

同形遗漏（非 agno）：`month_chain._month_fact_materials` 曾直读 `rejection_reports` + sqlite_master → 读口迁入既有 owner `applier.list_rejection_reports_for_turn`（不新造 Store）。

## 已有产出已删简的核心机制（本轮核对）

| 机制 | 状态 |
|---|---|
| GameDB 呈现/摘要旧路（J10 八方法，见下；**不重开 J10 finding**） | 已删；本轮仅更新行数 |
| `pending_decisions` / rescript desk 持久原语 | 整迁 `IssueStore` |
| chat / night / ledger / kv / rollback 持久原语 | 整迁 `ReignStateStore` |
| **agno 会话历史持久原语**（本轮） | 整迁 `ReignStateStore`；GameDB 无 agno SQL |
| `rejection_reports` 月链直读（本轮同形） | 改调 `applier.list_rejection_reports_for_turn` |
| audience/rescript/declaration/materials/cli/web_app 平行 SQL | 改调 owner（前序已结） |

## 逐类结算

| 类 | 根因 | 正确行为 / 整类处置 | 保留项依据 |
|---|---|---|---|
| J1 持久职责归位不完整 | 原枚举漏框架表；GameDB 平行持久 agno；月链直读 rejection_reports。 | **全仓 78 张事实表**（schema 54 + store CREATE + 框架 owned）机械枚举；常规/初始化/恢复/动态 SQL 归单一主写 owner；编排可留。复扫：OUTSIDE_WRITE=0、OUTSIDE_READ=0、DYNAMIC_GDB=0、GAMEDB_AGNO_SQL=0。 | schema DDL；跨实体投影读；VIEW 相关域读；owner 闭集动态助手；META_DISCOVERY；事务 SAVEPOINT/atomic；`agno_memories`=Agno 自管、生产 SQL=0。 |
| J10 复杂度下降 | **不重开 finding**；只更新同口径行数。 | 诚实报告；**不以「大幅下降」署核心净增**。 | 功能重接/全绿归 #1873；不为凑行数排版。 |

## 可重跑完整机械枚举命令

工作目录：仓库根。先跑口径 A/B 行数，再跑 J1 全表扫描。扫描脚本写入 `/tmp/1889-j1-scan.py` 后执行；完整迭代输出落 `/tmp/1889-j1-full-enum-rerun.txt`（格式 `file:line:table:op:class`）。完整可复制扫描脚本见下文「J1 扫描脚本全文」。

### 口径 A / B 行数

```sh
python3 - <<'PY'
from pathlib import Path
import subprocess

def core(ref=None):
    if ref:
        out = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", ref, "--",
             "ming_sim/db.py", "ming_sim/entities", "ming_sim/schema.py", "ming_sim/opening_seed.py"],
            text=True,
        )
        return sum(
            len(subprocess.check_output(["git", "show", f"{ref}:{p}"]).splitlines())
            for p in out.splitlines() if p.endswith(".py")
        )
    n = sum(len(Path(p).read_text().splitlines()) for p in [
        "ming_sim/db.py", "ming_sim/schema.py", "ming_sim/opening_seed.py",
    ])
    return n + sum(len(p.read_text().splitlines()) for p in Path("ming_sim/entities").rglob("*.py"))

def runtime(ref=None):
    if ref:
        out = subprocess.check_output(
            ["git", "ls-tree", "-r", "--name-only", ref, "--", "ming_sim", "web_app.py"],
            text=True,
        )
        return sum(
            len(subprocess.check_output(["git", "show", f"{ref}:{p}"]).splitlines())
            for p in out.splitlines()
            if p.endswith(".py") and (p.startswith("ming_sim/") or p == "web_app.py")
        )
    return (
        sum(len(p.read_text().splitlines()) for p in Path("ming_sim").rglob("*.py"))
        + len(Path("web_app.py").read_text().splitlines())
    )

def db_alone(ref=None):
    if ref:
        return len(subprocess.check_output(["git", "show", f"{ref}:ming_sim/db.py"]).splitlines())
    return len(Path("ming_sim/db.py").read_text().splitlines())

for label, ref in [
    ("0ca77fecc", "0ca77fecc"),
    ("ddf53881f", "ddf53881f"),
    ("ba6a5cc53", "ba6a5cc53"),
    ("WORKTREE", None),
]:
    print(label, "A", core(ref), "B", runtime(ref), "db", db_alone(ref))
PY
```

### 本轮实测扫描摘要（核对输出，非回执自称）

| 项 | 值 | 核路径 |
|---|---:|---|
| SCHEMA_TABLES | 54 | `/tmp/1889-j1-full-enum-rerun.txt` |
| TABLES_ENUMERATED（完整） | **78** | 含 store CREATE + agno_sessions/agno_runs + rejection_reports 等 |
| VIEWS | 2 | economy_accounts, office_vacancies |
| FRAMEWORK_EXTERNAL_NO_SQL | agno_memories | Agno SqliteDb 自管；生产 SQL hits=0 |
| OWNER_KEYS | 78；MISSING=[]；每表 primary_count=1 | OWNER / SINGULARITY |
| TRACKED_PY / PROD_PY / EXCLUDED_PY | 382 / 131 / 251 | 同上 |
| OWNER | 791 | CLASS COUNTS |
| META_DISCOVERY | 4 | reign/character_knowledge/applier/db sqlite_master |
| PROJ_READ | 12 | INTERESTING HITS |
| VIEW_RELATED | 3 | INTERESTING HITS |
| OWNER_DYNAMIC | 13 | owner 闭集助手 |
| FALSE_POS_MSG | 10 | 报错文案 |
| OUTSIDE_WRITE | **0** | OUTSIDE detail |
| OUTSIDE_READ | **0** | OUTSIDE detail |
| DYNAMIC_GDB | **0** | OUTSIDE detail |
| GAMEDB_AGNO_SQL | **0** | AGNO OWNERSHIP PROOF |
| AGNO hits | 6 全部 OWNER 于 reign_state/store.py | 同上 |

PRAGMA 发现：`agno_sessions`。sqlite_master 位点：`applier.py` / `db.py` / `character_knowledge/store.py` / `reign_state/store.py`（均 META_HELPERS）。

## J1 完整成员表（78 张事实表）

### Owner 归属（权威写口；每表单一）

| owner | 表 |
|---|---|
| `character/store.py` | characters, character_offices, offices, office_slots, office_change_records, authority_records, recommendation_events |
| `region/store.py` | regions, region_logs |
| `army/store.py` | armies, army_logs |
| `building/store.py` | buildings, building_logs |
| `power/store.py` | powers, power_logs, power_name_logs |
| `social_class/store.py` | classes, population_transfer_ledger |
| `faction/store.py` | factions, faction_axis_debt, faction_stance_summaries, centrifuge_log |
| `fiscal_container/store.py` | fiscal_containers |
| `fiscal_container/config.py` | fiscal_config, fiscal_config_changes, fiscal_config_creations, fiscal_config_tombstones |
| `issue/store.py` | issues, issue_advances, events, event_triggers, turn_directives, pending_decisions |
| `dossier/store.py` | pending_actions, next_audience_todos, decree_*, dossier_*, faction_denunciations, pending_promulgation_verdicts |
| `character_knowledge/store.py` | secret_orders, secret_order_briefs, public_sayings, character_knowledge_events, character_knowledge_sources |
| `person_log/store.py` | relation_edge_events, relation_summaries, relation_brew_pending, person_logs |
| `reign_state/store.py` | story_ledger_entries, save_meta, kv_store, chat_turns, chat_turn_rollback_items, audience_nights, economy_ledger, ending_summary, legacies, game_state, metrics, **agno_sessions, agno_runs** |
| `record_store.py` | chat_messages, turn_reports, month_open_snapshot, pending_resolve_context |
| `affair/store.py` | affairs |
| `staged_declaration/store.py` | staged_declarations |
| `textual_fact/store.py` | textual_facts |
| `applier.py` | rejection_reports |

### 有据 exceptions

| class | 成员 | 依据 |
|---|---|---|
| PROJ_READ | dossier↔secret_orders/turn_directives/armies/audience_nights；person_log↔characters/factions/faction_stance_summaries；character_knowledge↔issues；social_class↔regions；affair↔story_ledger_entries | 跨实体投影读，非写 |
| VIEW_RELATED | character↔office_vacancies；reign↔economy_accounts | 域内读 VIEW |
| OWNER_DYNAMIC | character/character_knowledge/fiscal_config/dossier/column_write/affair 闭集助手 | 非 GameDB 通用恢复 |
| META_DISCOVERY | reign/db/character_knowledge/applier 的 sqlite_master | 表存在/名册发现，非平行事实写口 |
| FRAMEWORK_EXTERNAL | agno_memories | Agno 自管；本仓生产 SQL=0 |
| SCHEMA | schema.py DDL | 非运行时写口 |

## J10 机制删简（不重开 finding；仅更新行数）

相对 `ddf53881f` 已删 GameDB 呈现摘要方法仍为 8 个（本轮未再动）：faction_report、turn_power_summary、turn_region_summary、building_detail、turn_economy_summary、treasury_ledger、list_office_vacancies、turn_army_summary。

## 同口径生产行数

口径 A = `ming_sim/db.py` + `ming_sim/entities/**/*.py` + `ming_sim/schema.py` + `ming_sim/opening_seed.py`
口径 B = 全部 `ming_sim/**/*.py` + `web_app.py`

| 参照 | 口径 A（核心） | 口径 B（runtime） | db.py alone |
|---|---:|---:|---:|
| 判词基线 `0ca77fecc` | 23622 | 91166 | 22574 |
| 判词时 HEAD `ddf53881f` | 24491 | 90329 | 16482 |
| 施工前 `ba6a5cc53` | 24550 | 89769 | 15017 |
| 本轮工作树（commit 前） | **24558** | **89786** | **14850** |
| 相对 `0ca77fecc` | **+936** | **−1380** | −7724 |
| 相对 `ddf53881f` | +67 | −543 | −1632 |
| 相对 `ba6a5cc53` | +8 | +17 | −167 |

诚实结论：核心相对 `0ca77fecc` 仍净增 **+936**；相对施工前仅 +8（agno 原语平移 + rejection 读口）。宽口径 runtime 相对 `0ca77fecc` 净减 1380。**不署「复杂度大幅下降」**。勿伪称大幅。

## 测试改动必要成本及契约

- 调用面跟随 owner：`db.reign.agno_runs_length` / `truncate_*`；agents 经 `game_db.reign`；月链经 `list_rejection_reports_for_turn`。
- **未**放松断言、**未**用 mock 顶替真实入口凑绿。
- **未**造证明性测试；未跑全量。
- 复用既有 restore/undo/transport 测试，仅改调用面到 reign。

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

### 聚焦验证实测

命令同上（`/usr/bin/time -p`）。结果：`254 passed`，墙钟 **real 8.14s**（pytest 报告 7.40s）。未跑全量。未造证明性测试。

`git diff --check ba6a5cc53 --`：无 trailing whitespace。

## 未结项

1. 口径 A 相对 `0ca77fecc` 仍 +936；是否「够简单」由家族收尾看机制对比拍板，本回执不伪造大幅下降。
2. 功能缺口/测试红归 #1873。
3. J10 finding 不重开；仅更新行数如上。
4. owner 闭集动态助手（OWNER_DYNAMIC=13）与 META_DISCOVERY 保留；非 GameDB 通用 `{table}` 恢复。

## 合法性自查

- 未 amend / 未 push / 未开 PR / 未 stash；保留历史提交，仅追加。
- 未造通用回滚或查询框架；未新建生产扫描机制（扫描仅为 `/tmp` 分析命令）。
- 未为凑行数压缩排版；未为全绿加机制。
- 自建物仅工作树与 `/tmp`。

## J1 扫描脚本全文

工作目录仓库根；下列命令可完整复现（脚本无省略）：

```sh
cat > /tmp/1889-j1-scan.py <<'PY'
#!/usr/bin/env python3
"""#1889 J1 full mechanical enumeration — real SQL + schema + store CREATE + PRAGMA/sqlite_master.

Corrects prior schema-only TABLE set (54). Includes framework/external tables.
"""
from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(".").resolve()

# --- collect table universe ---
schema_text = (ROOT / "ming_sim" / "schema.py").read_text(encoding="utf-8")
SCHEMA_TABLES = sorted(set(re.findall(r"CREATE TABLE(?: IF NOT EXISTS)?\s+(\w+)", schema_text, re.I)))
VIEWS = sorted(set(re.findall(r"CREATE VIEW(?: IF NOT EXISTS)?\s+(\w+)", schema_text, re.I)))

STORE_CREATE: dict[str, set[str]] = defaultdict(set)
for p in (ROOT / "ming_sim").rglob("*.py"):
    rel = str(p.relative_to(ROOT))
    text = p.read_text(encoding="utf-8")
    for t in re.findall(r"CREATE TABLE(?: IF NOT EXISTS)?\s+(\w+)", text, re.I):
        if t == "IF":
            continue
        STORE_CREATE[t].add(rel)

# Framework tables Agno creates (not in our schema DDL); discovered via real SQL / PRAGMA
FRAMEWORK_TABLES = {"agno_sessions", "agno_runs", "agno_memories"}

OWNER: dict[str, set[str]] = {
    "characters": {"ming_sim/entities/character/store.py"},
    "character_offices": {"ming_sim/entities/character/store.py"},
    "offices": {"ming_sim/entities/character/store.py"},
    "office_slots": {"ming_sim/entities/character/store.py"},
    "office_change_records": {"ming_sim/entities/character/store.py"},
    "authority_records": {"ming_sim/entities/character/store.py"},
    "recommendation_events": {"ming_sim/entities/character/store.py"},
    "regions": {"ming_sim/entities/region/store.py"},
    "region_logs": {"ming_sim/entities/region/store.py"},
    "armies": {"ming_sim/entities/army/store.py"},
    "army_logs": {"ming_sim/entities/army/store.py"},
    "buildings": {"ming_sim/entities/building/store.py"},
    "building_logs": {"ming_sim/entities/building/store.py"},
    "powers": {"ming_sim/entities/power/store.py"},
    "power_logs": {"ming_sim/entities/power/store.py"},
    "power_name_logs": {"ming_sim/entities/power/store.py"},
    "classes": {"ming_sim/entities/social_class/store.py"},
    "population_transfer_ledger": {"ming_sim/entities/social_class/store.py"},
    "factions": {"ming_sim/entities/faction/store.py"},
    "faction_axis_debt": {"ming_sim/entities/faction/store.py"},
    "faction_stance_summaries": {"ming_sim/entities/faction/store.py"},
    "centrifuge_log": {"ming_sim/entities/faction/store.py"},
    "fiscal_containers": {"ming_sim/entities/fiscal_container/store.py"},
    "fiscal_config": {"ming_sim/entities/fiscal_container/config.py"},
    "fiscal_config_changes": {"ming_sim/entities/fiscal_container/config.py"},
    "fiscal_config_creations": {"ming_sim/entities/fiscal_container/config.py"},
    "fiscal_config_tombstones": {"ming_sim/entities/fiscal_container/config.py"},
    "issues": {"ming_sim/entities/issue/store.py"},
    "issue_advances": {"ming_sim/entities/issue/store.py"},
    "events": {"ming_sim/entities/issue/store.py"},
    "event_triggers": {"ming_sim/entities/issue/store.py"},
    "turn_directives": {"ming_sim/entities/issue/store.py"},
    "pending_decisions": {"ming_sim/entities/issue/store.py"},
    "pending_actions": {"ming_sim/entities/dossier/store.py"},
    "next_audience_todos": {"ming_sim/entities/dossier/store.py"},
    "secret_orders": {"ming_sim/entities/character_knowledge/store.py"},
    "secret_order_briefs": {"ming_sim/entities/character_knowledge/store.py"},
    "public_sayings": {"ming_sim/entities/character_knowledge/store.py"},
    "relation_edge_events": {"ming_sim/entities/person_log/store.py"},
    "relation_summaries": {"ming_sim/entities/person_log/store.py"},
    "relation_brew_pending": {"ming_sim/entities/person_log/store.py"},
    "story_ledger_entries": {"ming_sim/entities/reign_state/store.py"},
    "save_meta": {"ming_sim/entities/reign_state/store.py"},
    "kv_store": {"ming_sim/entities/reign_state/store.py"},
    "chat_turns": {"ming_sim/entities/reign_state/store.py"},
    "chat_turn_rollback_items": {"ming_sim/entities/reign_state/store.py"},
    "audience_nights": {"ming_sim/entities/reign_state/store.py"},
    "economy_ledger": {"ming_sim/entities/reign_state/store.py"},
    "ending_summary": {"ming_sim/entities/reign_state/store.py"},
    "legacies": {"ming_sim/entities/reign_state/store.py"},
    "chat_messages": {"ming_sim/entities/record_store.py"},
    "turn_reports": {"ming_sim/entities/record_store.py"},
    "month_open_snapshot": {"ming_sim/entities/record_store.py"},
    "pending_resolve_context": {"ming_sim/entities/record_store.py"},
    # store-local CREATE (outside schema.py DDL)
    "game_state": {"ming_sim/entities/reign_state/store.py"},
    "metrics": {"ming_sim/entities/reign_state/store.py"},
    "affairs": {"ming_sim/entities/affair/store.py"},
    "character_knowledge_events": {"ming_sim/entities/character_knowledge/store.py"},
    "character_knowledge_sources": {"ming_sim/entities/character_knowledge/store.py"},
    "decree_cost_events": {"ming_sim/entities/dossier/store.py"},
    "decree_dossier_decisions": {"ming_sim/entities/dossier/store.py"},
    "decree_dossier_endorsements": {"ming_sim/entities/dossier/store.py"},
    "decree_dossier_link_rejections": {"ming_sim/entities/dossier/store.py"},
    "decree_dossier_links": {"ming_sim/entities/dossier/store.py"},
    "decree_dossier_reconciliations": {"ming_sim/entities/dossier/store.py"},
    "decree_dossiers": {"ming_sim/entities/dossier/store.py"},
    "dossier_actual_progress": {"ming_sim/entities/dossier/store.py"},
    "dossier_loophole_exposures": {"ming_sim/entities/dossier/store.py"},
    "dossier_reported_progress": {"ming_sim/entities/dossier/store.py"},
    "dossier_supervision_presence": {"ming_sim/entities/dossier/store.py"},
    "faction_denunciations": {"ming_sim/entities/dossier/store.py"},
    "pending_promulgation_verdicts": {"ming_sim/entities/dossier/store.py"},
    "person_logs": {"ming_sim/entities/person_log/store.py"},
    "staged_declarations": {"ming_sim/entities/staged_declaration/store.py"},
    "textual_facts": {"ming_sim/entities/textual_fact/store.py"},
    # framework tables we persist against (Agno creates; our truncate/count owner = reign)
    "agno_sessions": {"ming_sim/entities/reign_state/store.py"},
    "agno_runs": {"ming_sim/entities/reign_state/store.py"},
}

# Agno-managed; our production code must not SQL-touch (FRAMEWORK_EXTERNAL exception)
FRAMEWORK_EXTERNAL_NO_SQL = {"agno_memories"}

# ephemeral / non-save tables with documented owners or exceptions
SPECIAL_OWNER: dict[str, set[str]] = {
    "rejection_reports": {"ming_sim/applier.py"},
}

VIEW_RELATED_OWNER: dict[str, set[str]] = {
    "office_vacancies": {"ming_sim/entities/character/store.py"},
    "economy_accounts": {"ming_sim/entities/reign_state/store.py"},
}

SCHEMA_FILE = "ming_sim/schema.py"

PROJECTION_READ_EXCEPTIONS: dict[str, set[str]] = {
    "armies": {"ming_sim/entities/dossier/store.py"},
    "audience_nights": {"ming_sim/entities/dossier/store.py"},
    "turn_directives": {"ming_sim/entities/dossier/store.py"},
    "secret_orders": {"ming_sim/entities/dossier/store.py"},
    "characters": {"ming_sim/entities/person_log/store.py"},
    "factions": {"ming_sim/entities/person_log/store.py"},
    "faction_stance_summaries": {"ming_sim/entities/person_log/store.py"},
    "issues": {"ming_sim/entities/character_knowledge/store.py"},
    "regions": {"ming_sim/entities/social_class/store.py"},
    "story_ledger_entries": {"ming_sim/entities/affair/store.py"},
}

OWNER_DYNAMIC_HELPERS: set[str] = {
    "ming_sim/entities/character/store.py",
    "ming_sim/entities/character_knowledge/store.py",
    "ming_sim/entities/fiscal_container/config.py",
    "ming_sim/entities/dossier/store.py",
    "ming_sim/entities/column_write.py",
    "ming_sim/entities/affair/store.py",
}

# META discovery (sqlite_master / PRAGMA) allowed on helpers
META_HELPERS: set[str] = {
    "ming_sim/entities/reign_state/store.py",
    "ming_sim/entities/character_knowledge/store.py",  # roster discovery via sqlite_master
    "ming_sim/applier.py",  # rejection_reports existence check
    "ming_sim/db.py",  # rollback _table_exists only; no fact-table SQL via it for agno
}

tracked = subprocess.check_output(["git", "ls-files", "*.py"], text=True).splitlines()
EXCLUDE_PREFIXES = ("tests/", "archive/", "scripts/", "tools/", "spike")

def is_production_py(path: str) -> bool:
    if not path.endswith(".py"):
        return False
    for pref in EXCLUDE_PREFIXES:
        if path.startswith(pref):
            return False
    base = path.rsplit("/", 1)[-1]
    if base.startswith("test_") or base.endswith("_test.py") or base == "conftest.py":
        return False
    return True

PROD_FILES = sorted(p for p in tracked if is_production_py(p))
EXCLUDED_TRACKED = sorted(p for p in tracked if p.endswith(".py") and p not in PROD_FILES)

# Discover tables from real SQL hits (filter noise)
OP_PATS = [
    (re.compile(r"(?is)\bINSERT\s+INTO\s+([a-z_][a-z0-9_]*)"), "INSERT"),
    (re.compile(r"(?is)\bUPDATE\s+([a-z_][a-z0-9_]*)"), "UPDATE"),
    (re.compile(r"(?is)\bDELETE\s+FROM\s+([a-z_][a-z0-9_]*)"), "DELETE"),
    (re.compile(r"(?is)\bFROM\s+([a-z_][a-z0-9_]*)"), "FROM"),
    (re.compile(r"(?is)\bJOIN\s+([a-z_][a-z0-9_]*)"), "JOIN"),
    (re.compile(r"(?is)PRAGMA\s+table_info\(([a-z_][a-z0-9_]*)\)"), "PRAGMA"),
]
WRITE_OPS = {"INSERT", "UPDATE", "DELETE"}

SQLISH = re.compile(
    r"(?is)(?:execute|executemany|executescript)\s*\(|[\"'].*\b(?:SELECT|INSERT|UPDATE|DELETE|PRAGMA|CREATE\s+TABLE)"
)

TRUE_DYNAMIC_SQL = re.compile(
    r"(?is)(?:execute|executemany)\s*\(\s*f(?:\'\'\'|\"\"\"|\'|\")[^\'\"]*(?:FROM|INTO|UPDATE|DELETE\s+FROM)\s*\{"
    r"|(?:execute|executemany)\s*\(\s*(?:\'\'\'|\"\"\"|\'|\")[^\'\"]*(?:FROM|INTO|UPDATE|DELETE\s+FROM)\s*\{"
)

# First pass: discover SQL-touched identifiers that are real tables
KNOWN = set(SCHEMA_TABLES) | set(VIEWS) | set(STORE_CREATE) | set(FRAMEWORK_TABLES) | set(SPECIAL_OWNER) | set(OWNER)
sql_discovered: set[str] = set()
pragma_discovered: set[str] = set()
sqlite_master_sites: list[tuple[str, int]] = []

for path in PROD_FILES:
    lines = (ROOT / path).read_text(encoding="utf-8").splitlines()
    for lineno, line in enumerate(lines, start=1):
        if line.lstrip().startswith("#"):
            continue
        if "sqlite_master" in line or "sqlite_schema" in line:
            sqlite_master_sites.append((path, lineno))
        for pat, op in OP_PATS:
            for m in pat.finditer(line):
                table = m.group(1)
                # require nearby SQL context for FROM/JOIN to cut Python imports
                if op in ("FROM", "JOIN"):
                    window = "\n".join(lines[max(0, lineno - 2) : min(len(lines), lineno + 1)])
                    if not SQLISH.search(window) and "PRAGMA" not in line:
                        # also allow multiline string continuing SQL
                        if not any(
                            ("SELECT" in lines[j] or "DELETE" in lines[j] or "INSERT" in lines[j]
                             or "UPDATE" in lines[j] or '"""' in lines[j] or "'''" in lines[j])
                            for j in range(max(0, lineno - 6), lineno)
                        ):
                            continue
                if op == "PRAGMA":
                    pragma_discovered.add(table)
                if table in KNOWN or table in FRAMEWORK_TABLES or table in STORE_CREATE:
                    sql_discovered.add(table)

TABLES = sorted(
    (
        set(SCHEMA_TABLES)
        | {t for t in STORE_CREATE if t not in ("IF",)}
        | (FRAMEWORK_TABLES - FRAMEWORK_EXTERNAL_NO_SQL)  # owned framework we touch
        | set(SPECIAL_OWNER)
        | {t for t in sql_discovered if t in KNOWN or t in FRAMEWORK_TABLES or t in STORE_CREATE}
    ) - set(VIEWS)
)
# Include agno_memories in universe as framework-external (no owner SQL expected)
ALL_UNIVERSE = sorted(set(TABLES) | FRAMEWORK_EXTERNAL_NO_SQL | set(VIEWS))

def classify_hit(path: str, table: str, op: str) -> str:
    if path == SCHEMA_FILE:
        return "SCHEMA"
    if table == "sqlite_master":
        if path in META_HELPERS:
            return "META_DISCOVERY"
        return "OUTSIDE_READ"
    if table in FRAMEWORK_EXTERNAL_NO_SQL:
        return "FRAMEWORK_EXTERNAL_HIT"
    if table in VIEWS:
        if path in VIEW_RELATED_OWNER.get(table, set()):
            return "VIEW_RELATED"
        if op in WRITE_OPS:
            return "OUTSIDE_WRITE"
        return "OUTSIDE_READ"
    owners = OWNER.get(table) or SPECIAL_OWNER.get(table) or set()
    if path in owners:
        return "OWNER"
    # store CREATE DDL for owned tables
    if op == "FROM" and "CREATE" in path:
        pass
    if path in STORE_CREATE.get(table, set()) and "CREATE TABLE" in (ROOT / path).read_text(encoding="utf-8"):
        # ensure_schema CREATE counts as OWNER schema helper if path is owner
        if path in owners:
            return "OWNER"
    if op in WRITE_OPS:
        return "OUTSIDE_WRITE"
    if path in PROJECTION_READ_EXCEPTIONS.get(table, set()):
        return "PROJ_READ"
    if not owners and table in FRAMEWORK_TABLES:
        return "FRAMEWORK_UNOWNED"
    if not owners:
        return "UNOWNED_TABLE"
    return "OUTSIDE_READ"

def scan_file(path: str):
    text = (ROOT / path).read_text(encoding="utf-8")
    lines = text.splitlines()
    hits = []
    seen = set()
    for lineno, line in enumerate(lines, start=1):
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        if "sqlite_master" in line or "sqlite_schema" in line:
            key = (lineno, "sqlite_master", "META")
            if key not in seen:
                seen.add(key)
                cls = "META_DISCOVERY" if path in META_HELPERS else "OUTSIDE_READ"
                hits.append((lineno, "sqlite_master", "META", cls))
        for pat, op in OP_PATS:
            for m in pat.finditer(line):
                table = m.group(1)
                if table not in ALL_UNIVERSE and table not in FRAMEWORK_TABLES:
                    continue
                if op in ("FROM", "JOIN"):
                    window = "\n".join(lines[max(0, lineno - 2) : min(len(lines), lineno + 1)])
                    if not SQLISH.search(window) and "PRAGMA" not in line:
                        if not any(
                            ("SELECT" in lines[j] or "DELETE" in lines[j] or "INSERT" in lines[j]
                             or "UPDATE" in lines[j] or '"""' in lines[j] or "'''" in lines[j])
                            for j in range(max(0, lineno - 6), lineno)
                        ):
                            continue
                if op == "FROM":
                    dm = re.search(r"(?is)DELETE\s+FROM\s+" + re.escape(table), line)
                    if dm and dm.start(0) <= m.start() <= dm.end():
                        continue
                key = (lineno, table, op)
                if key in seen:
                    continue
                seen.add(key)
                hits.append((lineno, table, op, classify_hit(path, table, op)))
        if "{table}" in line or "{quoted}" in line or "DENUNCIATION_TABLE" in line:
            window = "\n".join(lines[max(0, lineno - 3) : min(len(lines), lineno + 1)])
            if TRUE_DYNAMIC_SQL.search(window) or re.search(
                r'(?is)(?:execute|executemany)\s*\(\s*f["\'].*(?:FROM|INTO|UPDATE|DELETE)',
                window,
            ):
                key = (lineno, "{dynamic}", "DYNAMIC")
                if key not in seen:
                    seen.add(key)
                    if path in OWNER_DYNAMIC_HELPERS:
                        hits.append((lineno, "{dynamic}", "DYNAMIC", "OWNER_DYNAMIC"))
                    elif path == "ming_sim/db.py":
                        hits.append((lineno, "{dynamic}", "DYNAMIC", "DYNAMIC_GDB"))
                    else:
                        hits.append((lineno, "{dynamic}", "DYNAMIC", "DYNAMIC_OTHER"))
            elif re.search(r"(?i)raise\s+|ValueError|不支持|非法|无效", line):
                key = (lineno, "{msg}", "MSG")
                if key not in seen:
                    seen.add(key)
                    hits.append((lineno, "{msg}", "MSG", "FALSE_POS_MSG"))
    return hits

by_class = defaultdict(list)
all_hits = []
for path in PROD_FILES:
    for lineno, table, op, cls in scan_file(path):
        row = (path, lineno, table, op, cls)
        all_hits.append(row)
        by_class[cls].append(row)

print("=== SCHEMA / UNIVERSE COUNTS ===")
print(f"SCHEMA_TABLES={len(SCHEMA_TABLES)}")
print(f"STORE_CREATE_TABLES={len(STORE_CREATE)}")
print(f"FRAMEWORK_OWNED=agno_sessions,agno_runs")
print(f"FRAMEWORK_EXTERNAL_NO_SQL={','.join(sorted(FRAMEWORK_EXTERNAL_NO_SQL))}")
print(f"TABLES_ENUMERATED={len(TABLES)}")
print(f"VIEWS={len(VIEWS)}")
print("TABLE_LIST=" + ",".join(TABLES))
print("VIEW_LIST=" + ",".join(VIEWS))
print(f"PRAGMA_DISCOVERED={sorted(pragma_discovered)}")
print(f"SQLITE_MASTER_SITES={sqlite_master_sites}")
owned_keys = set(OWNER) | set(SPECIAL_OWNER)
print(
    f"OWNER_KEYS={len(owned_keys)} "
    f"MISSING_FROM_OWNER={[t for t in TABLES if t not in owned_keys]} "
    f"EXTRA_OWNER={[t for t in owned_keys if t not in TABLES and t not in FRAMEWORK_EXTERNAL_NO_SQL]}"
)

print("\n=== CORRECTION NOTE ===")
print("PRIOR_SCOPE=schema CREATE only → TABLES=54; framework agno_* invisible → false OUTSIDE=0")
print("THIS_SCOPE=schema+store CREATE+framework SQL/PRAGMA → includes agno_sessions/agno_runs")

print("\n=== PRODUCTION FILE SET ===")
print(f"TRACKED_PY={len(tracked)} PROD_PY={len(PROD_FILES)} EXCLUDED_PY={len(EXCLUDED_TRACKED)}")
print("EXCLUDE_RULES=prefix:tests/,archive/,scripts/,tools/,spike*; name:test_*,*_test.py,conftest.py")

print("\n=== OWNER DICTIONARY (complete enumerated tables) ===")
for t in TABLES:
    owners = OWNER.get(t) or SPECIAL_OWNER.get(t) or set()
    print(f"{t}\t{','.join(sorted(owners)) if owners else 'MISSING'}")

print("\n=== FRAMEWORK EXTERNAL (no our SQL expected) ===")
for t in sorted(FRAMEWORK_EXTERNAL_NO_SQL):
    print(f"{t}\texception=Agno SqliteDb manages; production SQL hits must be 0")

print("\n=== VIEW RELATED OWNERS ===")
for t in VIEWS:
    print(f"{t}\t{','.join(sorted(VIEW_RELATED_OWNER.get(t, [])))}")

print("\n=== PROJECTION READ EXCEPTIONS ===")
for t in sorted(PROJECTION_READ_EXCEPTIONS):
    print(f"{t}\t{','.join(sorted(PROJECTION_READ_EXCEPTIONS[t]))}")

print("\n=== INTERESTING HITS (non-OWNER/SCHEMA/META_DISCOVERY) ===")
print("format: file:line:table:op:class")
interesting = [r for r in all_hits if r[4] not in ("OWNER", "SCHEMA", "META_DISCOVERY")]
interesting.sort()
for path, lineno, table, op, cls in interesting:
    print(f"{path}:{lineno}:{table}:{op}:{cls}")

print("\n=== CLASS COUNTS ===")
for cls in sorted(by_class):
    print(f"{cls}={len(by_class[cls])}")

print("\n=== OUTSIDE_WRITE / OUTSIDE_READ / DYNAMIC_GDB / FRAMEWORK DETAIL ===")
for cls in ("OUTSIDE_WRITE", "OUTSIDE_READ", "DYNAMIC_GDB", "DYNAMIC_OTHER",
            "FRAMEWORK_EXTERNAL_HIT", "FRAMEWORK_UNOWNED", "UNOWNED_TABLE"):
    rows = by_class[cls]
    print(f"-- {cls} ({len(rows)}) --")
    for path, lineno, table, op, c in rows:
        print(f"  {path}:{lineno}:{table}:{op}")

print("\n=== AGNO OWNERSHIP PROOF ===")
agno_hits = [r for r in all_hits if r[2] in ("agno_sessions", "agno_runs", "agno_memories")]
for path, lineno, table, op, cls in sorted(agno_hits):
    print(f"{path}:{lineno}:{table}:{op}:{cls}")
print(f"AGNO_HIT_TOTAL={len(agno_hits)}")
gdb_agno = [r for r in agno_hits if r[0] == "ming_sim/db.py"]
print(f"GAMEDB_AGNO_SQL={len(gdb_agno)}")

print("\n=== PRIMARY OWNER SINGULARITY ===")
for t in TABLES:
    owners = OWNER.get(t) or SPECIAL_OWNER.get(t) or set()
    print(f"{t}\tprimary_count={len(owners)}\t{','.join(sorted(owners))}")

print("\nDONE")
PY
python3 /tmp/1889-j1-scan.py | tee /tmp/1889-j1-full-enum-rerun.txt
```
