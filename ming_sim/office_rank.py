"""明制品级带与任命破格标记的确定性领域函数。"""
from __future__ import annotations

import re
from typing import Any, Optional

from ming_sim.assets import load_json_asset

FIRST_APPOINTMENT_HIGH_OFFICE_THRESHOLD = 4
DEFAULT_LEVERAGE_MULTIPLIER = 1.0
_INACTIVE_STATUSES = frozenset({
    "offstage", "retired", "dismissed", "imprisoned", "exiled",
})
_NON_OFFICES = frozenset({
    "", "待铨", "听用候铨", "白身", "白丁", "布衣", "未仕", "童子",
    "进士", "举人", "生员", "贡生", "监生", "秀才", "诸生", "庠生", "国子监生",
})
_UNOFFICED_TYPES = frozenset({"", "未仕", "生员", "乡绅", "富商", "布衣", "待铨"})
_TITLE_NOISE_SUFFIXES = (
    "革职候勘", "革职", "候勘", "闲住", "罢居", "致仕", "赋闲",
)


def _table() -> dict[str, Any]:
    data = load_json_asset("offices.json")
    return data if isinstance(data, dict) else {}


def concurrent_office_titles(office: object) -> list[str]:
    """Canonical tokenizer shared by rank, leverage, and archive cleanup."""
    text = str(office or "").strip()
    if not text:
        return []
    text = re.sub(r"^(?:前|原任|原)", "", text).strip()
    text = (text.replace("兼掌", ",").replace("兼署", ",").replace("兼", ",")
            .replace("，", ",").replace("、", ","))
    titles: list[str] = []
    for segment in text.split(","):
        part = segment.strip()
        if not part:
            continue
        pollution_at = min(
            (part.find(noise) for noise in _TITLE_NOISE_SUFFIXES if noise in part),
            default=-1,
        )
        if pollution_at >= 0:
            clean = part[:pollution_at].strip()
            if clean:
                titles.append(clean)
            break
        titles.append(part)
    return titles


def canonical_office_title(office: object) -> str:
    """Return clean comma-separated substantive/status title segments."""
    return ",".join(concurrent_office_titles(office))


def _iter_rank_rules(table: dict[str, Any]) -> list[dict[str, Any]]:
    rules = table.get("rank_rules") or []
    return [rule for rule in rules if isinstance(rule, dict)]


def _match_rank_rule(
    title: str, table: dict[str, Any], required_field: str
) -> Optional[dict[str, Any]]:
    """Return the longest matching stem that defines the requested behavior."""
    text = str(title or "").strip()
    if not text:
        return None
    best: Optional[dict[str, Any]] = None
    best_score = (-1, -1)
    for rule in _iter_rank_rules(table):
        if required_field not in rule:
            continue
        # Leverage-bearing rules describe substantive titles.  Rank-only rules also
        # contain institutional/category fallbacks such as 翰林院 and 锦衣卫.
        title_specific = int(
            required_field == "rank_band" and "leverage_multiplier" in rule
        )
        for stem in rule.get("stems") or []:
            token = str(stem or "").strip()
            if not token or token not in text:
                continue
            score = (title_specific, len(token))
            if score > best_score:
                best = rule
                best_score = score
    return best


def office_rank_band(office: object, office_type: object = "") -> int:
    """Return the deterministic 1(high)-to-9(low) broad Ming rank band."""
    title = canonical_office_title(office)
    table = _table()
    # Concurrent offices: the highest substantive rank (lowest band number) wins.
    parts = concurrent_office_titles(title) or [title]
    bands: list[int] = []
    for part in parts:
        matched = _match_rank_rule(part, table, "rank_band")
        if matched is not None and "rank_band" in matched:
            bands.append(int(matched["rank_band"]))
    if bands:
        return min(bands)

    declared = str(office_type or "").strip()
    raw_title = str(office or "").strip()
    for entry in table.get("priority", []):
        if declared == str(entry.get("type") or "") or any(
            str(stem) in raw_title or str(stem) in title
            for stem in entry.get("stems", [])
        ):
            return int(entry["rank_band"])
    return int((table.get("fallback") or {}).get("rank_band", 9))


def office_leverage_multiplier(office: object, already_normalized: bool = False) -> float:
    """Map an office title to the faction-leverage rank multiplier via offices.json.

    Comma-separated concurrent titles take the highest recognized multiplier. Titles with
    no leverage-bearing stem keep the historical conservative default 1.0.
    """
    del already_normalized  # retained for the historical caller contract
    parts = concurrent_office_titles(office)
    if not parts:
        return DEFAULT_LEVERAGE_MULTIPLIER

    table = _table()
    office_weights: list[float] = []
    for part in parts:
        matches: list[tuple[int, float]] = []
        modifiers: list[float] = []
        for rule in _iter_rank_rules(table):
            if "leverage_multiplier" not in rule:
                continue
            for stem in rule.get("stems") or []:
                token = str(stem or "").strip()
                if not token or token not in part:
                    continue
                weight = float(rule["leverage_multiplier"])
                if token in {"候补", "候用"}:
                    modifiers.append(weight)
                else:
                    matches.append((len(token), weight))
        if matches or modifiers:
            longest = max((length for length, _weight in matches), default=-1)
            base_weights = [weight for length, weight in matches if length == longest]
            # Longest title stem identifies the office; explicit status modifiers then
            # constrain it. This preserves old min-within-title semantics without letting
            # generic substrings (御史 inside 佥都御史) demote the base title.
            office_weights.append(min([*base_weights, *modifiers]))
    # Concurrent offices contribute at the strongest real office, as before.
    return max(office_weights, default=DEFAULT_LEVERAGE_MULTIPLIER)


def _is_substantive_office(title: object, office_type: object = "") -> bool:
    text = canonical_office_title(title)
    if not text or str(office_type or "").strip() in _UNOFFICED_TYPES:
        return False
    if any(label in text for label in _NON_OFFICES if label):
        return False
    return any(
        _match_rank_rule(part, _table(), "leverage_multiplier") is not None
        for part in concurrent_office_titles(text)
    ) or str(office_type or "").strip() not in _UNOFFICED_TYPES


def appointment_break_rank(
    db: Any, name: object, new_office: object, new_office_type: object = "",
) -> dict[str, object]:
    """Classify one appointment from current/latest archived office, without LLM."""
    person = str(name or "").strip()
    target = str(new_office or "").strip()
    target_type = str(new_office_type or "").strip()
    new_band = office_rank_band(target, target_type)
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
        may_have_history = (
            str(row["status"] or "") in _INACTIVE_STATUSES
            or (current_title == "听用候铨" and str(row["reason_code"] or "") == "被顶替")
            or (current_title.startswith(("前", "原")) and any(
                marker in current_title for marker in ("罢居", "革职", "致仕", "闲住")
            ))
        )
        if may_have_history:
            archived = db.conn.execute(
                "SELECT office_title,office_type FROM character_offices WHERE character_name=?",
                (person,),
            ).fetchone()
            if archived is not None and _is_substantive_office(
                archived["office_title"], archived["office_type"]
            ):
                historical = True
                current_title = canonical_office_title(archived["office_title"])
                current_type = str(archived["office_type"] or "").strip()
            else:
                current_title = ""
                current_type = ""

    if not _is_substantive_office(current_title, current_type):
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
