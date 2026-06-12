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
        "location": "ming_sim/session.py:_apply_appointment_delta:candidate_upgrade",
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
        tree = ast.parse(path.read_text(encoding="utf-8"))
        parents: dict[ast.AST, ast.AST] = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if not _is_sql_execute_argument(node, parents):
                continue
            sql = " ".join(node.value.split())
            if not any(marker in sql for marker in _MUTATING_SQL_MARKERS):
                continue
            function_name = _enclosing_function_name(node, parents)
            locations.add(_inventory_location(relative, function_name, sql))
    return tuple({"location": location} for location in sorted(locations))


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
        return "ming_sim/session.py:_apply_appointment_delta:candidate_upgrade"
    return f"{relative}:{function_name}"
