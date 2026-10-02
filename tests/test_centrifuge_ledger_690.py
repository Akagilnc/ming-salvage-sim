"""#690 / ADR 0011-2 — 血债棘轮 substrate 公开行为钉。

公开面：accrue_blood_debt / accrue_detection_wariness / rebuild_centrifuge_cache。
只观察 DB 与异常；不 spy 私有核、不 inspect.signature、不断言宽返回 DTO。
"""

from __future__ import annotations

import sqlite3
from typing import Any


# ---------------------------------------------------------------------------
# helpers（只读观察；不构成第二写缝）
# ---------------------------------------------------------------------------

_AXIS = "礼法名节"
_TARGET_EUNUCH = "崔呈秀"  # 阉党 · identity=98
_TARGET_ARMY = "袁崇焕"  # 军队 · identity=80
_SENTINEL_DEBT = 424242
_SENTINEL_WARINESS = 434343
_SENTINEL_OVERDRAW = 444444
_SENTINEL_LEG = 454545
_SENTINEL_AMOUNT = 464646
_SENTINEL_BASE = 474747


def _log_rows(db) -> list[sqlite3.Row]:
    return list(
        db.conn.execute(
            "SELECT turn, faction, axis, kind, base, legitimacy_pct, amount, "
            "source_name, reason_code, source, idem_key "
            "FROM centrifuge_log ORDER BY id"
        ).fetchall()
    )


def _cache_rows(db) -> list[sqlite3.Row]:
    return list(
        db.conn.execute(
            "SELECT faction, axis, blood_debt, wariness "
            "FROM faction_axis_debt ORDER BY faction, axis"
        ).fetchall()
    )


def _overdraw_map(db) -> dict[str, int]:
    rows = db.conn.execute(
        "SELECT name, edict_overdraw FROM factions ORDER BY name"
    ).fetchall()
    return {str(r["name"]): int(r["edict_overdraw"]) for r in rows}


def _snapshot(db) -> dict[str, Any]:
    return {
        "log": [dict(r) for r in _log_rows(db)],
        "cache": [dict(r) for r in _cache_rows(db)],
        "overdraw": _overdraw_map(db),
    }


def _faction_of(db, name: str) -> str:
    row = db.conn.execute(
        "SELECT faction FROM characters WHERE name=?", (name,)
    ).fetchone()
    assert row is not None
    return str(row["faction"])


def _set_identity(db, name: str, identity: int) -> None:
    db.conn.execute(
        "UPDATE characters SET identity=? WHERE name=?", (int(identity), name)
    )
    db.conn.commit()


def _direct_rows(db, *, idem_base: str | None = None) -> list[sqlite3.Row]:
    if idem_base is None:
        return [
            r
            for r in _log_rows(db)
            if r["kind"] == "direct"
        ]
    key = f"{idem_base}|direct"
    return [r for r in _log_rows(db) if r["idem_key"] == key]


# ---------------------------------------------------------------------------
# T1 — D2-4 三锚 +7/+61/+69
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T2 — kinship ADR 原式（杀 round(direct)×0.3×k）
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T3 — Δ=0 且命名空间无 durable → 合法零写
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T4 — 快乐路径 + 禁参 TypeError
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T5 — 廷杖 overdraw 同批；非廷杖无 overdraw
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T6 — 错误 target 零写
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T7 — 跨派隔离
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T8 — detection wrapper
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T9 — 幂等三态
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T10 — 半套 key 预插
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T11 — rebuild + 写途回滚
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T12 — restore：关库重开
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# T13 — P4 输入侧不喂
# ---------------------------------------------------------------------------


def _collect_typed_keys(obj: Any, *, _out: set[str] | None = None) -> set[str]:
    """递归收集真实 payload 的 typed dict keys；不解析自由文本。"""
    if _out is None:
        _out = set()
    if isinstance(obj, dict):
        for key, value in obj.items():
            _out.add(str(key))
            _collect_typed_keys(value, _out=_out)
    elif isinstance(obj, (list, tuple)):
        for item in obj:
            _collect_typed_keys(item, _out=_out)
    return _out


# ---------------------------------------------------------------------------
# T14 — 码集二分
# ---------------------------------------------------------------------------
