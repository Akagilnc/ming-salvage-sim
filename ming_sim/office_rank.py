"""明制品级带与任命破格标记的确定性领域函数。"""
from __future__ import annotations

from typing import Any, Optional

from ming_sim.assets import load_json_asset, require_dict, require_list

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


def _table() -> dict[str, Any]:
    return require_dict(load_json_asset("offices.json"), "offices.json")


def normalize_office(office: str) -> str:
    """官职多职统一为半角逗号分隔：旧「兼/兼掌/兼署」与全角「，」「、」一律归一逗号，
    去空分项、去重、保序。是 office 字段落库的唯一规范化入口——所有写 characters.office
    的路径都过它，保证去重/顶缺时能按逗号分项匹配。"""
    s = (office or "").strip()
    if not s:
        return ""
    s = s.replace("兼掌", ",").replace("兼署", ",").replace("兼", ",")
    s = s.replace("，", ",").replace("、", ",")
    seen: set = set()
    parts: list[str] = []
    for p in (x.strip() for x in s.split(",")):
        if p and p not in seen:
            seen.add(p)
            parts.append(p)
    return ",".join(parts)


def office_title_continues(current_office: object, desired_office: object) -> bool:
    """Desired titles are a non-empty subset of current — same posting restatement.

    Single authority for noop / seat reuse / concurrent-title preserve. True transfer
    declares titles outside the current set or a different seat (checked by caller).
    """
    current = normalize_office(str(current_office or ""))
    desired = normalize_office(str(desired_office or ""))
    if not current or not desired:
        return False
    desired_parts = {p for p in desired.split(",") if p}
    current_parts = {p for p in current.split(",") if p}
    return bool(desired_parts) and desired_parts.issubset(current_parts)


def appointment_seat_continues(
    *,
    current_seat: object = "",
    desired_seat: object = "",
    office_type: object = "",
    local_office_types: frozenset[str] = frozenset(),
) -> bool:
    """Same-posting seat after canonical rules (non-local ignores stuffed region).

    Omitted desired seat continues the current seat. Explicit different local seat
    is a transfer. Callers pass the archive local-type set; no parallel type table.
    """
    kind = str(office_type or "").strip()
    if kind not in local_office_types:
        return True
    desired = str(desired_seat or "").strip()
    if not desired:
        return True
    return desired == str(current_seat or "").strip()


def concurrent_office_titles(office: object) -> list[str]:
    """Split concurrent office titles by formal conjunction / comma separators.

    No prefix/suffix vocabulary peel: polluted free-text office strings are not
    rewritten into status or cleaned titles here.
    """
    text = str(office or "").strip()
    if not text:
        return []
    text = (text.replace("兼掌", ",").replace("兼署", ",").replace("兼", ",")
            .replace("，", ",").replace("、", ","))
    return [part.strip() for part in text.split(",") if part.strip()]


def canonical_office_title(office: object) -> str:
    """Return clean comma-separated substantive/status title segments."""
    return ",".join(concurrent_office_titles(office))


def _iter_rank_rules(table: dict[str, Any]) -> list[dict[str, Any]]:
    # 静态 offices.json 内容：成员坏即响亮（ADR 0005），不静默丢规则。
    rules = table.get("rank_rules")
    if rules is None:
        return []
    if not isinstance(rules, list) or any(not isinstance(rule, dict) for rule in rules):
        raise ValueError("offices.json rank_rules 须为对象数组")
    return list(rules)


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
        for stem in require_list(rule.get("stems", []), "offices.json.rank_rules.stems"):
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
    return int(require_dict(table.get("fallback", {}), "offices.json.fallback").get("rank_band", 9))


def office_leverage_multiplier(office: object) -> float:
    """Map an office title to the faction-leverage rank multiplier via offices.json.

    Comma-separated concurrent titles take the highest recognized multiplier. Titles with
    no leverage-bearing stem keep the historical conservative default 1.0.
    """
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
            for stem in require_list(rule.get("stems", []), "offices.json.rank_rules.stems"):
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
    """Identity kinds are not offices; rank vocabulary does not gate new office titles."""
    text = canonical_office_title(title)
    if str(office_type or "").strip() in {"身名分", "无名分"}:
        return False
    if not text or any(label and label in text for label in _NON_OFFICES):
        return False
    return True


def appointment_break_rank(
    db: Any, name: object, new_office: object, new_office_type: object = "",
) -> dict[str, object]:
    """Classify one appointment from current/latest archived office, without LLM."""
    person = str(name or "").strip()
    target = str(new_office or "").strip()
    target_type = str(new_office_type or "").strip()
    new_band = office_rank_band(target, target_type)
    row = db.conn.execute(
        'SELECT office,office_type,status,reason_code FROM characters WHERE name=?',
        (person,),
    ).fetchone()

    historical = False
    current_title = ""
    current_type = ""
    if row is not None:
        current_title = str(row["office"] or "").strip()
        current_type = str(row["office_type"] or "").strip()
        # History archive lookup is gated only by closed status / reason enums —
        # never by free-text office prefixes or status-word substrings.
        may_have_history = (
            str(row["status"] or "") in _INACTIVE_STATUSES
            or (current_title == "听用候铨" and str(row["reason_code"] or "") == "被顶替")
        )
        if may_have_history:
            archived = db.conn.execute(
                """
                SELECT o.office_title,
                       (
                         SELECT c.office_type FROM office_change_records c
                         WHERE c.character_name=o.character_name
                           AND c.office_title=o.office_title
                         ORDER BY c.id DESC LIMIT 1
                       ) AS office_type
                FROM character_offices o
                WHERE o.character_name=?
                """,
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
