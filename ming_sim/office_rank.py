"""明制品级带与任命破格标记的确定性领域函数。"""
from __future__ import annotations

from typing import Any, Optional

from ming_sim.assets import load_json_asset

FIRST_APPOINTMENT_HIGH_OFFICE_THRESHOLD = 4
_INACTIVE_STATUSES = frozenset({
    "offstage", "retired", "dismissed", "imprisoned", "exiled",
})
_NON_OFFICES = frozenset({"", "待铨", "听用候铨", "白身", "布衣", "进士", "举人", "生员"})


def _table() -> dict[str, Any]:
    data = load_json_asset("offices.json")
    return data if isinstance(data, dict) else {}


def office_rank_band(office: object, office_type: object = "") -> int:
    """Return the deterministic 1(high)-to-9(low) broad Ming rank band."""
    title = str(office or "").strip()
    table = _table()
    for rule in table.get("rank_rules", []):
        if any(str(stem) in title for stem in rule.get("stems", [])):
            return int(rule["rank_band"])
    declared = str(office_type or "").strip()
    for entry in table.get("priority", []):
        if declared == str(entry.get("type") or "") or any(
            str(stem) in title for stem in entry.get("stems", [])
        ):
            return int(entry["rank_band"])
    return int((table.get("fallback") or {}).get("rank_band", 9))


def appointment_break_rank(db: Any, name: object, new_office: object) -> dict[str, object]:
    """Classify one appointment from current/latest archived office, without LLM."""
    person = str(name or "").strip()
    target = str(new_office or "").strip()
    new_band = office_rank_band(target)
    row = db.conn.execute(
        "SELECT office,office_type,status,reason_code FROM characters WHERE name=?",
        (person,),
    ).fetchone()

    historical = False
    current_title = ""
    current_type = ""
    if row is not None:
        current_title = str(row["office"] or "").strip()
        current_type = str(row["office_type"] or "").strip()
        historical = (
            str(row["status"] or "") in _INACTIVE_STATUSES
            or (current_title == "听用候铨" and str(row["reason_code"] or "") == "被顶替")
            or (current_title.startswith(("前", "原")) and any(
                marker in current_title for marker in ("罢居", "革职", "致仕", "闲住")
            ))
        )
    if historical:
        archived = db.conn.execute(
            "SELECT office_title,office_type FROM character_offices WHERE character_name=?",
            (person,),
        ).fetchone()
        if archived is not None and str(archived["office_title"] or "").strip() not in _NON_OFFICES:
            current_title = str(archived["office_title"]).strip()
            current_type = str(archived["office_type"] or "").strip()
        else:
            # Historical people must never be compared from the 待铨 fallback.
            raise ValueError(f"{person} 缺最近任职备档，无法确定起复品级")

    if not current_title or current_title in _NON_OFFICES:
        broken = new_band <= FIRST_APPOINTMENT_HIGH_OFFICE_THRESHOLD
        return {
            "is_break_rank": broken,
            "basis": "first_appointment_high_office" if broken else "first_appointment_regular",
            "new_rank_band": new_band,
            "threshold_band": FIRST_APPOINTMENT_HIGH_OFFICE_THRESHOLD,
        }

    current_band = office_rank_band(current_title, current_type)
    return {
        "is_break_rank": current_band - new_band >= 2,
        "basis": "historical_office" if historical else "current_office",
        "current_rank_band": current_band,
        "new_rank_band": new_band,
    }
