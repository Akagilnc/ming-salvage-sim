# #1889 修内司回执：冻结判词 J1 + J10（证据复核交卷）

本轮在已提交 `a47eaad57`、`81acc3ab6`、`7cfce2e5b` 之上保留全部历史继续施工；判词基线 `ddf53881f` / 对比基线 `0ca77fecc`。派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a107b5-f070-73d0-88af-e3e6011de1d0@fixer/fix-packet.md`；判词附件 `attachments/00-1889-judge-newacc-ddf53881f.json`。本文件是施工证据，不另立 authority。

官方依据（施工轨迹沿用，不伪造）：Repository / persistence owner — https://www.cosmicpython.com/book/chapter_02_repository.html ；SQLite 事务编排留调用方 https://www.sqlite.org/lang_transaction.html 。落法：事实 SQL 只活在 owner；GameDB/月链/分派/召对编排只调 owner；不新造通用回滚/查询框架。

## 已有产出已删简的核心机制（本轮核对）

| 机制 | 状态 |
|---|---|
| GameDB 呈现/摘要旧路（见下方 J10 具体方法名单） | 已从 `db.py` 删除；本轮补删残留 `turn_army_summary` |
| `pending_decisions` / rescript desk 持久原语 | 整迁 `IssueStore`；删 GameDB SQL 与 desk 投影副本 |
| chat / night / ledger / kv / rollback 持久原语 | 整迁 `ReignStateStore`；GameDB 只留编排 |
| `audience_night` / `audience_translation` / `rescript_actions` / `declaration_dispatch` / `materials` / `cli/terminal` / `web_app` 平行 SQL | 改调 owner；本轮复扫又清 `web_app` 五处 owner 外直读 |
| reign 未使用薄包装 | 已删 |
| （已提交）`pending_actions` outside-owner、Electron/Steam 壳、admin、动态 `{table}` 恢复 | `81acc3ab6` / `a47eaad57` |

## 逐类结算

| 类 | 根因 | 正确行为 / 整类处置 | 保留项依据 |
|---|---|---|---|
| J1 持久职责归位不完整 | 判词举证动态恢复/初始化；平行持久路径。 | **全仓 schema 54 张事实表**（脚本计数）机械枚举；常规/初始化/恢复/动态 SQL 归单一主写 owner；编排可留。复扫：OUTSIDE_WRITE=0、OUTSIDE_READ=0、DYNAMIC_GDB=0。 | schema DDL；跨实体投影读；VIEW 相关域读；owner 闭集动态助手；事务 SAVEPOINT/atomic。 |
| J10 复杂度下降 | 被取代旧路与无必要重复；回执须列前后行数。 | 删 GameDB 呈现摘要旧路具体方法（见下）；计入搬入成本后诚实报告行数。**不以「大幅下降」署核心净增。** | 功能重接/全绿归 #1873；不为凑行数排版。 |

## 可重跑完整机械枚举命令

工作目录：仓库根。先跑口径 A/B 行数，再跑 J1 全表扫描。扫描脚本写入 `/tmp/1889-j1-scan.py` 后执行；完整迭代输出落 `/tmp/1889-j1-full-enum-rerun.txt`（格式 `file:line:table:op:class`）。

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
    ("81acc3ab6", "81acc3ab6"),
    ("7cfce2e5b", "7cfce2e5b"),
    ("WORKTREE", None),
]:
    print(label, "A", core(ref), "B", runtime(ref), "db", db_alone(ref))
PY
```

### 24490 / 24491 定位命令

判词 `coreLines` 用 `wc -l`（计换行符）；本仓 `splitlines()` 计逻辑行。差 1 的文件：

```sh
python3 - <<'PY'
import subprocess
files = [
    p for p in subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", "ddf53881f", "--",
         "ming_sim/db.py", "ming_sim/entities", "ming_sim/schema.py", "ming_sim/opening_seed.py"],
        text=True,
    ).splitlines() if p.endswith(".py")
]
for p in files:
    raw = subprocess.check_output(["git", "show", f"ddf53881f:{p}"])
    split_n = len(raw.decode("utf-8", errors="replace").splitlines())
    wc_n = raw.count(b"\n")
    if split_n != wc_n:
        print(p, "splitlines=", split_n, "wc=", wc_n,
              "endswith_newline=", raw.endswith(b"\n"))
cmd = (
    "git ls-tree -r --name-only ddf53881f -- "
    "ming_sim/db.py ming_sim/entities ming_sim/schema.py ming_sim/opening_seed.py "
    r"| grep '\.py$' | while IFS= read -r file; do git show \"ddf53881f:$file\"; done | wc -l"
)
print("judge-style:", subprocess.check_output(["bash", "-lc", cmd], text=True).strip())
PY
```

实测：`ming_sim/entities/army/__init__.py` 在 `ddf53881f` **末行无换行**（`endswith_newline=False`）；`splitlines=8`，`wc=7`。故判词 24490 = `wc -l`；本回执 A 口径统一用 `splitlines()` → **24491**。

### J1 全表 / 全生产 py 扫描（完整脚本，无省略）

排除说明（Git 跟踪 `*.py`）：
- 排除前缀：`tests/`、`archive/`、`scripts/`、`tools/`、`spike*`
- 排除文件名：`test_*`、`*_test.py`、`conftest.py`
- 保留：`ming_sim/**`、`web_app.py` 及其他非上述生产模块（脚本打印 `PROD_PY` 与完整 `EXCLUDED_ALL`）

```sh
cat > /tmp/1889-j1-scan.py <<'PY'
#!/usr/bin/env python3
"""#1889 J1 full mechanical enumeration — complete, no ellipsis."""
from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from pathlib import Path

ROOT = Path(".").resolve()

schema_text = (ROOT / "ming_sim" / "schema.py").read_text(encoding="utf-8")
TABLES = sorted(set(re.findall(r"CREATE TABLE(?: IF NOT EXISTS)?\s+(\w+)", schema_text, re.I)))
VIEWS = sorted(set(re.findall(r"CREATE VIEW(?: IF NOT EXISTS)?\s+(\w+)", schema_text, re.I)))

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

OP_PATS = [
    (re.compile(r"(?is)\bINSERT\s+INTO\s+([a-z_][a-z0-9_]*)"), "INSERT"),
    (re.compile(r"(?is)\bUPDATE\s+([a-z_][a-z0-9_]*)"), "UPDATE"),
    (re.compile(r"(?is)\bDELETE\s+FROM\s+([a-z_][a-z0-9_]*)"), "DELETE"),
    (re.compile(r"(?is)\bFROM\s+([a-z_][a-z0-9_]*)"), "FROM"),
    (re.compile(r"(?is)\bJOIN\s+([a-z_][a-z0-9_]*)"), "JOIN"),
]
WRITE_OPS = {"INSERT", "UPDATE", "DELETE"}

TRUE_DYNAMIC_SQL = re.compile(
    r"(?is)(?:execute|executemany)\s*\(\s*f(?:\'\'\'|\"\"\"|\'|\")[^\'\"]*(?:FROM|INTO|UPDATE|DELETE\s+FROM)\s*\{"
    r"|(?:execute|executemany)\s*\(\s*(?:\'\'\'|\"\"\"|\'|\")[^\'\"]*(?:FROM|INTO|UPDATE|DELETE\s+FROM)\s*\{"
)

def classify_hit(path: str, table: str, op: str) -> str:
    if path == SCHEMA_FILE:
        return "SCHEMA"
    if table in VIEWS:
        if path in VIEW_RELATED_OWNER.get(table, set()):
            return "VIEW_RELATED"
        if op in WRITE_OPS:
            return "OUTSIDE_WRITE"
        return "OUTSIDE_READ"
    owners = OWNER.get(table, set())
    if path in owners:
        return "OWNER"
    if op in WRITE_OPS:
        return "OUTSIDE_WRITE"
    if path in PROJECTION_READ_EXCEPTIONS.get(table, set()):
        return "PROJ_READ"
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
        for pat, op in OP_PATS:
            for m in pat.finditer(line):
                table = m.group(1)
                if table not in TABLES and table not in VIEWS:
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

print("=== SCHEMA COUNTS ===")
print(f"TABLES={len(TABLES)}")
print(f"VIEWS={len(VIEWS)}")
print("TABLE_LIST=" + ",".join(TABLES))
print("VIEW_LIST=" + ",".join(VIEWS))
print(
    f"OWNER_KEYS={len(OWNER)} MISSING={[t for t in TABLES if t not in OWNER]} "
    f"EXTRA={[t for t in OWNER if t not in TABLES]}"
)

print("\n=== PRODUCTION FILE SET ===")
print(f"TRACKED_PY={len(tracked)} PROD_PY={len(PROD_FILES)} EXCLUDED_PY={len(EXCLUDED_TRACKED)}")
print("EXCLUDE_RULES=prefix:tests/,archive/,scripts/,tools/,spike*; name:test_*,*_test.py,conftest.py")
print("EXCLUDED_ALL:")
for p in EXCLUDED_TRACKED:
    print(" ", p)

print("\n=== OWNER DICTIONARY (complete) ===")
for t in TABLES:
    print(f"{t}\t{','.join(sorted(OWNER[t]))}")

print("\n=== VIEW RELATED OWNERS ===")
for t in VIEWS:
    print(f"{t}\t{','.join(sorted(VIEW_RELATED_OWNER.get(t, [])))}")

print("\n=== PROJECTION READ EXCEPTIONS ===")
for t in sorted(PROJECTION_READ_EXCEPTIONS):
    print(f"{t}\t{','.join(sorted(PROJECTION_READ_EXCEPTIONS[t]))}")

print("\n=== INTERESTING HITS (non-OWNER/SCHEMA) ===")
print("format: file:line:table:op:class")
interesting = [r for r in all_hits if r[4] not in ("OWNER", "SCHEMA")]
interesting.sort()
for path, lineno, table, op, cls in interesting:
    print(f"{path}:{lineno}:{table}:{op}:{cls}")

print("\n=== CLASS COUNTS ===")
for cls in sorted(by_class):
    print(f"{cls}={len(by_class[cls])}")

print("\n=== OUTSIDE_WRITE / OUTSIDE_READ / DYNAMIC_GDB DETAIL ===")
for cls in ("OUTSIDE_WRITE", "OUTSIDE_READ", "DYNAMIC_GDB", "DYNAMIC_OTHER"):
    rows = by_class[cls]
    print(f"-- {cls} ({len(rows)}) --")
    for path, lineno, table, op, c in rows:
        print(f"  {path}:{lineno}:{table}:{op}")

print("\n=== PRIMARY OWNER SINGULARITY ===")
for t, owners in sorted(OWNER.items()):
    print(f"{t}\tprimary_count={len(owners)}\t{','.join(sorted(owners))}")

print("\n=== PROD FILES ===")
for p in PROD_FILES:
    print(p)
print("\nDONE")
PY
python3 /tmp/1889-j1-scan.py | tee /tmp/1889-j1-full-enum-rerun.txt
```

### 本轮实测扫描摘要（核对输出，非回执自称）

| 项 | 值 | 核路径 |
|---|---:|---|
| TABLES | 54 | `/tmp/1889-j1-full-enum-rerun.txt` `TABLES=` |
| VIEWS | 2（`economy_accounts`,`office_vacancies`） | 同上 `VIEW_LIST=` |
| OWNER_KEYS | 54；MISSING=[]；每表 primary_count=1 | 同上 OWNER / SINGULARITY |
| TRACKED_PY / PROD_PY / EXCLUDED_PY | 382 / 131 / 251 | 同上 |
| OWNER 实例 | 615 | CLASS COUNTS |
| SCHEMA | 2 | CLASS COUNTS |
| PROJ_READ | 12 | INTERESTING HITS |
| VIEW_RELATED | 3 | INTERESTING HITS |
| OWNER_DYNAMIC | 13（owner 闭集助手，非 GameDB 通用恢复） | INTERESTING HITS |
| FALSE_POS_MSG | 10（报错文案含 `{table}`） | INTERESTING HITS |
| OUTSIDE_WRITE | **0** | OUTSIDE detail |
| OUTSIDE_READ | **0** | OUTSIDE detail |
| DYNAMIC_GDB | **0** | OUTSIDE detail |
| DYNAMIC_OTHER | **0** | OUTSIDE detail |

本轮施工修复（复扫前曾命中、属整类平行读）：
- `web_app.py` `characters` / `economy_ledger` / `chat_turns`×2 / `kv_store` → 改调 `characters.read_admit_audience` / `reign.read_budget_ledger_rows` / `reign.read_chat_turn` / `reign.chat_turn_user_message_id` / `ReignStateStore.kv_get`
- 新增 owner 读口：`ReignStateStore.read_budget_ledger_rows`（SQL 从 web_app 迁入）

## J1 完整成员表（54 张事实表，脚本计数）

### Owner 归属（权威写口；每表单一）

| 表 | owner |
|---|---|
| characters, character_offices, offices, office_slots, office_change_records, authority_records, recommendation_events | `character/store.py` |
| regions, region_logs | `region/store.py` |
| armies, army_logs | `army/store.py` |
| buildings, building_logs | `building/store.py` |
| powers, power_logs, power_name_logs | `power/store.py` |
| classes, population_transfer_ledger | `social_class/store.py` |
| factions, faction_axis_debt, faction_stance_summaries, centrifuge_log | `faction/store.py` |
| fiscal_containers | `fiscal_container/store.py` |
| fiscal_config, fiscal_config_changes, fiscal_config_creations, fiscal_config_tombstones | `fiscal_container/config.py` |
| issues, issue_advances, events, event_triggers, turn_directives, pending_decisions | `issue/store.py` |
| pending_actions, next_audience_todos | `dossier/store.py` |
| secret_orders, secret_order_briefs, public_sayings | `character_knowledge/store.py` |
| relation_edge_events, relation_summaries, relation_brew_pending | `person_log/store.py` |
| story_ledger_entries, save_meta, kv_store, chat_turns, chat_turn_rollback_items, audience_nights, economy_ledger, ending_summary, legacies | `reign_state/store.py` |
| chat_messages, turn_reports, month_open_snapshot, pending_resolve_context | `record_store.py` |

`story_ledger_entries` 主写唯一 = `reign_state/store.py`；`affair/store.py` 仅投影读（PROJ_READ）。

### 施工后合法例外（脚本 INTERESTING 实测）

| class | file:line:table:op | 依据 |
|---|---|---|
| PROJ_READ | dossier/store.py:1262,1304:secret_orders:JOIN | 案卷↔密令投影 |
| PROJ_READ | dossier/store.py:1480:turn_directives:FROM；1672:JOIN | 案卷↔旨稿投影 |
| PROJ_READ | dossier/store.py:1623:armies:JOIN | 案卷↔军队欠饷投影 |
| PROJ_READ | dossier/store.py:2133:audience_nights:FROM | 案卷↔夜投影 |
| PROJ_READ | person_log/store.py:188:characters/factions/faction_stance_summaries:JOIN | 关系酿造认领 |
| PROJ_READ | character_knowledge/store.py:417:issues:FROM | 知识源登记读 |
| PROJ_READ | social_class/store.py:99:regions:JOIN | 人口迁移读 |
| PROJ_READ | affair/store.py:441:story_ledger_entries:FROM | 经历投影读（非写） |
| VIEW_RELATED | character/store.py:461:office_vacancies:FROM | 官职域读 VIEW |
| VIEW_RELATED | reign_state/store.py:292,295:economy_accounts:FROM | 财政域读 VIEW |
| SCHEMA | schema.py DDL | 非运行时写口 |

## J10 机制删简：GameDB 呈现摘要旧路具体成员

相对 `ddf53881f` 的 `ming_sim/db.py`，下列**呈现/摘要**方法已删除（以 `def` 名枚举；本轮核对 `git show ddf53881f` vs HEAD/WT）：

1. `faction_report`
2. `turn_power_summary`
3. `turn_region_summary`
4. `building_detail`
5. `turn_economy_summary`
6. `treasury_ledger`
7. `list_office_vacancies`
8. `turn_army_summary`（本轮补删：前序已删其它摘要后仍残留的 20 行格式化旧路；调用方 0；数据读仍在 `ArmyStore.read_turn_army_summary`）

对应 owner 侧仅保留**数据读**（如 `FactionStore.read_faction_report`、`ReignStateStore.read_treasury_ledger` 等），不再经 GameDB 拼装呈现字符串。

同票已删但属职责归位/壳层（非上列呈现摘要类）的方法另计：`table_has_rows`、admin_*、`kv_get`/`kv_set`、chat/rescript/pending_decisions 平行写口、Electron/Steam/`/admin` 等——见提交史 `a47eaad57`/`81acc3ab6`/`7cfce2e5b`。

| 维度 | `ddf53881f` | 本轮工作树 |
|---|---|---|
| GameDB 上列 8 个呈现摘要方法 | 均在 | **0** |
| OUTSIDE_WRITE / OUTSIDE_READ / DYNAMIC_GDB | 判词点名残留 | **0 / 0 / 0** |
| Electron/Steam/`/admin`/通用 `{table}` 恢复 | 有→已删 | 0 |

## 同口径生产行数

口径 A = 世界记录核心：`ming_sim/db.py` + `ming_sim/entities/**/*.py` + `ming_sim/schema.py` + `ming_sim/opening_seed.py`
口径 B = 宽口径 runtime：全部 `ming_sim/**/*.py` + `web_app.py`

| 参照 | 口径 A（核心） | 口径 B（runtime） | db.py alone |
|---|---:|---:|---:|
| 判词基线 `0ca77fecc` | 23622 | 91166 | 22574 |
| 判词时 HEAD `ddf53881f` | **24491**（判词原文 wc=24490，见上定位） | 90329 | 16482 |
| 上轮提交 `81acc3ab6` | 24715 | 90090 | 16160 |
| 前序提交 `7cfce2e5b` | 24565 | 89794 | 15038 |
| 本轮工作树（commit 前） | **24550** | **89769** | **15017** |
| 相对 `0ca77fecc` | **+928** | **−1397** | −7557 |
| 相对 `ddf53881f` | +59 | −560 | −1465 |
| 相对 `7cfce2e5b` | −15 | −25 | −21 |

诚实结论：核心相对 `0ca77fecc` 仍净增 **+928**（搬入 entities 成本大于 db.py 删减）；宽口径 runtime 净减 1397。不署「复杂度大幅下降」。前版回执末段误写「核心 +877」与表内 +943 矛盾——以本表为准，旧句作废。

## 测试改动必要成本及契约

- 调用面跟随 owner：`db.characters.*` / `db.reign.*` / `ReignStateStore.kv_get`（含 `web_app`）。
- **未**放松断言、**未**用 mock 顶替真实入口凑绿。
- **未**造证明性测试；未跑全量。
- 未改契约的旧测试若仍写 `db.kv_get` / `db.save_rescript_drafts` 会红 → 归 #1873。

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

命令同上（另加 `/usr/bin/time -p`）。结果：`254 passed`，墙钟 **real 10.89s**（pytest 报告 9.99s）。未跑全量。未造证明性测试。

`git diff --check ddf53881f --`（工作树）：无 trailing whitespace / 无 EOF 多余空行（已修 `docs/1889-fixer-receipt.md` 两处与 `reign_state/store.py` 末行）。

## 未结项

1. 口径 A 相对 `0ca77fecc` 仍 +928；是否「够简单」由家族收尾看机制对比拍板，本回执不伪造大幅下降。
2. 功能缺口/测试红归 #1873。
3. owner 闭集动态助手（OWNER_DYNAMIC=13）保留；非 GameDB 通用 `{table}` 恢复。

## 合法性自查

- 未 amend / 未 push / 未开 PR / 未 stash；保留历史提交，仅追加。
- 未造通用回滚或查询框架；未新建生产扫描机制（扫描仅为 `/tmp` 分析命令）。
- 未为凑行数压缩排版；未为全绿加机制。
- 自建物仅工作树与 `/tmp`。
