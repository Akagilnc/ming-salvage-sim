"""#625 / ADR 0077 钝化事实底＋人身条件化判官口径。

DB 只机械记事实（监督在场 / 空子暴露 / 任期读既有 appointment_tenure），
不建钝化数值列。判官读事实软判；本模块提供：
- 在场连号派生（不落库）
- 派系同/敌判定
- #619 origin 结构化私货/同派标记
- 孤直反制硬门（涌现缝立 issue）
- 玩家可见面禁词
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from ming_sim.appointment_tenure import normalize_appointment_tenure
from ming_sim.participant_roster import resolve_dossier_owner_name
from ming_sim.qualitative import qualitative_character_axis

# 监督关系：本票只记「稽核」在场（护卫属 #567 押解口径，不入钝化事实底）
SUPERVISION_RELATION = "稽核"

# 判官读面三键（simulator / due_review / issues extractor 共调）
SUPERVISION_SURFACE_KEYS = (
    "supervision_history",
    "loophole_exposures",
    "transformation_tendency_facts",
)

# transformation_tendency_facts 空形——唯一真源（禁调用方手写七键字面量）
EMPTY_TRANSFORMATION_TENDENCY_FACTS: Dict[str, object] = {
    "longest_consecutive_presence_months": 0,
    "has_upright_auditor": False,
    "has_mediocre_auditor": False,
    "faction_relations": [],
    "auditor_names": [],
    "exposure_classes": [],
    "exposure_count": 0,
}

# 执行格形态闭集（与 GameDB._DOSSIER_EXECUTION_OUTCOMES 对齐）
EXECUTION_FORMS = frozenset({
    "executing", "fulfilled", "degraded", "failed", "transformed",
})

# #619 origin 结构化标记（扩 origin 字符串，不加列）
ORIGIN_MARK_PRIVATE_GOODS = "private_goods"
ORIGIN_MARK_SAME_FACTION_BLIND = "same_faction_blind"
ORIGIN_MARK_SEP = "+"

# 人身条件化：操守定性档（读 characters.integrity，不落钝化分）
INTEGRITY_UPRIGHT_BANDS = frozenset({"操守清正", "清介可称"})  # 孤直型
INTEGRITY_MEDIOCRE_BANDS = frozenset({"操守多亏", "操守未稳", "操守平常"})  # 庸吏

# 反制硬门：同路稽核连续在场满 12 月
COUNTERMEASURE_PRESENCE_MONTHS = 12
COUNTERMEASURE_KINDS = (
    "架空", "断信息", "诬告围攻", "明升暗调",
)
COUNTERMEASURE_ORIGIN_KIND = "supervision_countermeasure"

# 玩家可见面禁词（AC5 扫描面：scene_text/narrative/turn_report/knowledge_items/memorial_text）
SUPERVISION_BANNED_PLAYER_TOKENS = (
    "钝化",
    "钝化度",
    "陋规化",
    "supervision_history",
    "loophole_exposure",
    "loophole_exposures",
    "consecutive_months",
    "private_goods",
    "same_faction_blind",
    "transformation_tendency",
    "dulling",
    "dull_rate",
    "dullness",
)

# PRAGMA 白名单：事实表仅 id / FK / turn / 枚举 / 布尔
PRESENCE_TABLE = "dossier_supervision_presence"
EXPOSURE_TABLE = "dossier_loophole_exposures"
PRESENCE_ALLOWED_COLS = frozenset({
    "id", "dossier_id", "turn", "auditor_name", "audit_dossier_id",
    "relation_type", "present",
})
EXPOSURE_ALLOWED_COLS = frozenset({
    "id", "dossier_id", "turn", "action_type", "execution_form",
})
# 全库禁「钝化数值」列名（AC1）
FORBIDDEN_DULLING_COL_FRAGMENTS = (
    "dull", "dulling", "钝化", "陋规", "supervision_score", "dull_rate",
)


def integrity_band(value: object) -> str:
    return str(qualitative_character_axis("integrity", value) or "")


def is_upright_integrity(value: object) -> bool:
    return integrity_band(value) in INTEGRITY_UPRIGHT_BANDS


def faction_relation(auditor_faction: object, subject_faction: object) -> str:
    """same / enemy / other — 敌派＝双方非空且不等（本票不另建敌对矩阵）。"""
    a = str(auditor_faction or "").strip()
    b = str(subject_faction or "").strip()
    if not a or not b:
        return "other"
    if a == b:
        return "same"
    return "enemy"


def compose_report_origin(base: str, marks: Iterable[str] = ()) -> str:
    """结构化 origin：base[+mark...]。base 须已带 dossier-report: 前缀。"""
    cleaned = [str(m).strip() for m in marks if str(m or "").strip()]
    # 去重保序
    seen: Set[str] = set()
    ordered: List[str] = []
    for mark in cleaned:
        if mark in seen:
            continue
        seen.add(mark)
        ordered.append(mark)
    root = str(base or "").strip()
    if not ordered:
        return root
    return root + ORIGIN_MARK_SEP + ORIGIN_MARK_SEP.join(ordered)


def parse_report_origin(origin: object) -> Tuple[str, Tuple[str, ...]]:
    """拆 origin → (base_without_marks, marks_tuple)。"""
    raw = str(origin or "").strip()
    if not raw:
        return "", ()
    # namespace 前缀后的 body 才可带 mark
    ns = "dossier-report:"
    if not raw.startswith(ns):
        return raw, ()
    body = raw[len(ns):]
    if not body:
        return raw, ()
    parts = [p for p in body.split(ORIGIN_MARK_SEP) if p]
    if not parts:
        return raw, ()
    base = ns + parts[0]
    marks = tuple(parts[1:])
    return base, marks


def origin_has_mark(origin: object, mark: str) -> bool:
    _base, marks = parse_report_origin(origin)
    return str(mark) in marks


def derive_consecutive_months(
    presence_turns: Sequence[int], *, end_turn: Optional[int] = None,
) -> int:
    """读端派生：按 turn 连号从 end_turn（或最大 turn）向前数连续在场月数。"""
    turns = sorted({int(t) for t in presence_turns if int(t) > 0})
    if not turns:
        return 0
    cursor = int(end_turn) if end_turn is not None else turns[-1]
    if cursor not in turns:
        # end_turn 当月不在场 → 连续段在更早处截断
        earlier = [t for t in turns if t <= cursor]
        if not earlier:
            return 0
        cursor = earlier[-1]
    count = 0
    expected = cursor
    turn_set = set(turns)
    while expected in turn_set:
        count += 1
        expected -= 1
    return count


def unpack_supervision_surface(
    surface: Mapping[str, object] | None = None,
) -> Dict[str, object]:
    """surface 三键 unpack 单源 helper——due_review / simulator / extractor 共调。"""
    src = surface or {}
    tendency = src.get("transformation_tendency_facts")
    return {
        "supervision_history": list(src.get("supervision_history") or []),
        "loophole_exposures": list(src.get("loophole_exposures") or []),
        "transformation_tendency_facts": dict(
            tendency if isinstance(tendency, Mapping) and tendency
            else EMPTY_TRANSFORMATION_TENDENCY_FACTS
        ),
    }


def build_transformation_tendency_facts(
    *,
    supervision_history: Sequence[Mapping[str, object]],
    loophole_exposures: Sequence[Mapping[str, object]],
) -> Dict[str, object]:
    """观察槽用定性事实包——禁数值钝化分。"""
    longest = 0
    upright_hit = False
    mediocre_hit = False
    relations: List[str] = []
    auditors: List[str] = []
    for row in supervision_history:
        months = int(row.get("consecutive_months") or 0)
        if months > longest:
            longest = months
        band = str(row.get("auditor_integrity_band") or "")
        if band in INTEGRITY_UPRIGHT_BANDS:
            upright_hit = True
        if band in INTEGRITY_MEDIOCRE_BANDS:
            mediocre_hit = True
        rel = str(row.get("faction_relation") or "")
        if rel:
            relations.append(rel)
        name = str(row.get("auditor_name") or "")
        if name:
            auditors.append(name)
    exposure_classes = sorted({
        f"{row.get('action_type')}+{row.get('execution_form')}"
        for row in loophole_exposures
        if row.get("action_type") and row.get("execution_form")
    })
    out = dict(EMPTY_TRANSFORMATION_TENDENCY_FACTS)
    out.update({
        "longest_consecutive_presence_months": longest,
        "has_upright_auditor": upright_hit,
        "has_mediocre_auditor": mediocre_hit,
        "faction_relations": sorted(set(relations)),
        "auditor_names": sorted(set(auditors)),
        "exposure_classes": exposure_classes,
        "exposure_count": len(list(loophole_exposures)),
    })
    return out


def countermeasure_origin_ref(auditor_name: str, dossier_id: int) -> str:
    return f"auditor:{auditor_name}:dossier:{int(dossier_id)}"


def pick_countermeasure_kind(auditor_name: str, dossier_id: int) -> str:
    """确定性选一种反制形态（restore 可复现，无真 RNG）。"""
    seed = f"{auditor_name}:{int(dossier_id)}"
    idx = sum(ord(ch) for ch in seed) % len(COUNTERMEASURE_KINDS)
    return COUNTERMEASURE_KINDS[idx]


def assert_no_banned_tokens(text: object, *, surface: str) -> None:
    raw = str(text or "")
    for token in SUPERVISION_BANNED_PLAYER_TOKENS:
        if token in raw:
            raise AssertionError(f"{surface} 裸露禁词：{token!r}")


def character_tenure(db: Any, name: str) -> str:
    if not name:
        return "真除"
    row = db.conn.execute(
        "SELECT appointment_tenure FROM character_offices WHERE character_name=?",
        (name,),
    ).fetchone()
    if row is None:
        return "真除"
    return normalize_appointment_tenure(row["appointment_tenure"])


def character_faction_integrity(db: Any, name: str) -> Tuple[str, object]:
    if not name:
        return "", None
    row = db.conn.execute(
        "SELECT faction, integrity FROM characters WHERE name=?",
        (name,),
    ).fetchone()
    if row is None:
        return "", None
    return str(row["faction"] or ""), row["integrity"]
