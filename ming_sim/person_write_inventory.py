"""ADR 0009 inventory for current direct writes to ``characters``."""

from __future__ import annotations

import ast
from pathlib import Path


PERSON_WRITE_POINT_INVENTORY = (
    {
        "location": "ming_sim/db.py:seed_static_data",
        "owner": "seed",
        "disposition": "adr0009_exempt",
        "reason": "开局 seed 不产 RejectedItem，ADR 0009 明确豁免。",
    },
    {
        "location": "ming_sim/db.py:_migrate_legacy_office_pollution",
        "owner": "migration",
        "disposition": "adr0009_exempt",
        "reason": "决定9/L94 一次性老档数据清洗（init 时跑、幂等），属豁免路径，不产 RejectedItem。",
    },
    {
        "location": "ming_sim/db.py:_backfill_person_core_character_static_fields",
        "owner": "migration",
        "disposition": "adr0009_exempt",
        "reason": "#191 旧档静态字段补丁（init 时幂等，仅补缺省值），不产 RejectedItem。",
    },
    {
        "location": "ming_sim/db.py:_migrate_character_identity_seed",
        "owner": "migration",
        "disposition": "adr0009_exempt",
        "reason": "#488 旧档身份/污点补丁（init 时幂等，仅补未初始化字段及缺失名册），不产 RejectedItem。",
    },
    {
        "location": "ming_sim/db.py:_backfill_bandit_power_split",
        "owner": "migration",
        "disposition": "adr0009_exempt",
        "reason": "#190 旧档流寇分股静态补丁（init 时幂等，仅迁移 legacy bandits/空值），不产 RejectedItem。",
    },
    {
        "location": "ming_sim/db.py:set_character_status",
        "owner": "legacy_person_path",
        "disposition": "migrate_to_person_applier",
        "reason": "状态迁移应收口到人物单入口。",
    },
    {
        "location": "ming_sim/db.py:apply_character_power_changes",
        "owner": "legacy_person_path",
        "disposition": "migrate_to_person_applier",
        "reason": "易主应收口到人物单入口。",
    },
    {
        "location": "ming_sim/db.py:set_character_office",
        "owner": "legacy_person_path",
        "disposition": "migrate_to_person_applier",
        "reason": "任命/调任应收口到人物单入口。",
    },
    {
        "location": "ming_sim/db.py:set_portrait_id",
        "owner": "profile_metadata",
        "disposition": "outside_person_archive",
        "reason": "头像字段不是 ADR 0009 人事状态/名分契约。",
    },
    {
        "location": "ming_sim/db.py:add_character",
        "owner": "legacy_person_path",
        "disposition": "migrate_to_person_applier",
        "reason": "运行时建人仅后宫 candidate 专用入口可保留，其余应收口。",
    },
    {
        "location": "ming_sim/issues.py:_displace_duplicate_offices",
        "owner": "legacy_person_path",
        "disposition": "migrate_to_person_applier",
        "reason": "顶替腾缺是任命派生事件，需收口。",
    },
    {
        "location": "ming_sim/issues.py:apply_office_appointment",
        "owner": "legacy_person_path",
        "disposition": "migrate_to_person_applier",
        "reason": "任官后清状态原因仍是人物状态/名分写入，需随任命核收口。",
    },
    {
        "location": "ming_sim/issues.py:_apply_person_changes",
        "owner": "adr0009_tracer_person_path",
        "disposition": "migrate_to_person_applier",
        "reason": "Slice 6 处置 tracer bullet 的过渡写点，后续随 C1 applier 收口。",
    },
    {
        "location": "ming_sim/issues.py:_restore_person_write_state",
        "owner": "adr0009_tracer_person_path",
        "disposition": "migrate_to_person_applier",
        "reason": "任官失败局部恢复的过渡写点，后续随 C1 applier 收口。",
    },
    {
        "location": "ming_sim/decree.py:tick_transit_arrivals",
        "owner": "deterministic_settle_path",
        "disposition": "adr0009_exempt",
        "reason": "#668/0095 在途倒数 tick：remaining-=速度后 ≤0 时引擎落抵达（location=transit_to、清四量），属确定性结算逻辑（非 LLM 产 delta），豁免于 ADR 0009 person applier 收口。",
    },
    {
        "location": "ming_sim/session.py:apply_appointment:candidate_upgrade",
        "owner": "candidate_entry",
        "disposition": "dedicated_person_entry",
        "reason": "后宫 candidate 创建/册封是 ADR 0009 明确专用入口。",
    },
)

_MUTATING_SQL_MARKERS = (
    "UPDATE characters SET",
    "INSERT INTO characters",
    "INSERT OR REPLACE INTO characters",
    "REPLACE INTO characters",
    "DELETE FROM characters",
)


def discover_character_write_sql_locations() -> tuple[dict[str, str], ...]:
    """Return current source locations that directly mutate ``characters`` via SQL."""
    root = Path(__file__).resolve().parents[1]
    locations: set[str] = set()
    for path in sorted((root / "ming_sim").rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        locations.update(_write_locations_in_source(path.read_text(encoding="utf-8"), relative))
    return tuple({"location": location} for location in sorted(locations))


def _write_locations_in_source(source: str, relative: str) -> set[str]:
    """Scan one module's source for direct ``characters``-mutating execute() SQL.

    Handles both plain string literals AND f-strings (``ast.JoinedStr``): an
    f-string execute arg like ``f"DELETE FROM characters WHERE ..."`` is the
    Call arg as a whole, so it matches directly (its inner ``Constant`` parts
    have the JoinedStr as parent — not the Call — so they are correctly skipped
    by ``_is_sql_execute_argument``; before this an f-string-only write point
    escaped the inventory scan entirely)."""
    tree = ast.parse(source)
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            sql_src = node.value
        elif isinstance(node, ast.JoinedStr):
            sql_src = "".join(
                v.value for v in node.values
                if isinstance(v, ast.Constant) and isinstance(v.value, str)
            )
        else:
            continue
        if not _is_sql_execute_argument(node, parents):
            continue
        sql = " ".join(sql_src.split())
        if not any(marker in sql for marker in _MUTATING_SQL_MARKERS):
            continue
        function_name = _enclosing_function_name(node, parents)
        found.add(_inventory_location(relative, function_name, sql))
    return found


def person_write_locations_by_disposition(disposition: str) -> tuple[str, ...]:
    """Return inventory locations for one migration disposition."""
    return tuple(
        sorted(
            item["location"]
            for item in PERSON_WRITE_POINT_INVENTORY
            if item["disposition"] == disposition
        )
    )


def _enclosing_function_name(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> str:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
    return "<module>"


def _is_sql_execute_argument(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, ast.Call):
            return node in current.args and _call_name(current.func) in {
                "execute",
                "executemany",
                "executescript",
            }
    return False


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _inventory_location(relative: str, function_name: str, sql: str) -> str:
    if relative == "ming_sim/db.py" and "INSERT INTO characters" in sql:
        if function_name == "add_character":
            return "ming_sim/db.py:add_character"
        if function_name == "seed_static_data":
            return "ming_sim/db.py:seed_static_data"
    if relative == "ming_sim/session.py" and "office_type='后宫'" in sql:
        return "ming_sim/session.py:apply_appointment:candidate_upgrade"
    return f"{relative}:{function_name}"
