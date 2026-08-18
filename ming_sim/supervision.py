"""#625 / ADR 0077 钝化事实底＋人身条件化判官口径；#627 政敌检举轨。

DB 只机械记事实（监督在场 / 空子暴露 / 任期读既有 appointment_tenure），
不建钝化数值列。判官读事实软判；本模块提供：
- 在场连号派生（不落库）
- 派系同/敌判定
- #619 origin 结构化私货/同派标记
- 孤直反制硬门（涌现缝立 issue）
- #627 政敌检举：fork 单源谓词、烈度纯函数、真伪 origin、同渲染函数
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
# #627 检举真伪底（compose_report_origin 单源常量，不加 veracity 列）
ORIGIN_MARK_DENUNCIATION_TRUE = "denunciation_true"
ORIGIN_MARK_DENUNCIATION_FALSE = "denunciation_false"
ORIGIN_MARK_SEP = "+"

DENUNCIATION_ORIGIN_BASE = "dossier-report:faction_denunciation"
DENUNCIATION_KIND = "faction_denunciation"

# #627 烈度→条数硬门（确定性选形，禁概率抽签/新烈度列/LLM 报烈度）
# (intensity 下界, 检举条数)；按 intensity 升序，命中最高门。
DENUNCIATION_INTENSITY_GATES: Tuple[Tuple[int, int], ...] = (
    (1, 1),
    (40, 2),
    (70, 3),
)

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
    # #627 真伪底 / 烈度 / fork 暴露系统词
    "denunciation_true",
    "denunciation_false",
    "faction_conflict_intensity",
    "faction_denunciation",
    "fork_exposure",
    "veracity",
    "true_denunciation",
    "false_denunciation",
)

# #627 检举事实表列白名单（PRAGMA 验收）
DENUNCIATION_TABLE = "faction_denunciations"
DENUNCIATION_ALLOWED_COLS = frozenset({
    "id", "turn", "accuser_name", "accuser_faction",
    "subject_name", "subject_faction", "target_dossier_id",
    "origin", "payload_json", "memorial_text",
})

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


def is_reported_actual_fork(
    *,
    reported_bands: Sequence[object],
    beyond_intent: bool,
    execution_outcome: object,
) -> bool:
    """#622/#627 fork 判据单源：奏报面有 band，且（旨外实况 或 执行格非 fulfilled/executing/空）。

    全库仅此一处表达该谓词；读端（#622 稽核信号 / #627 检举）共调。
    """
    bands = [
        str(b).strip()
        for b in (reported_bands or ())
        if str(b or "").strip()
    ]
    outcome = str(execution_outcome or "").strip()
    return bool(bands) and (
        bool(beyond_intent) or outcome not in {"", "fulfilled", "executing"}
    )


def faction_conflict_intensity(
    *,
    relation: object,
    enemy_leverage: object,
    enemy_satisfaction: object = None,
) -> int:
    """派系冲突烈度纯函数：enemy × leverage(敌派)（可加 satisfaction 调制）。

    禁概率抽签 / 禁新烈度列 / 禁 LLM 报烈度。非 enemy → 0。
    """
    if str(relation or "").strip() != "enemy":
        return 0
    try:
        lev = int(enemy_leverage)
    except (TypeError, ValueError):
        lev = 0
    lev = max(0, min(100, lev))
    if enemy_satisfaction is None:
        return lev
    try:
        sat = int(enemy_satisfaction)
    except (TypeError, ValueError):
        sat = 50
    sat = max(0, min(100, sat))
    # 低满意（怨气）最多 +10；不反向扣到负
    anger_boost = max(0, (50 - sat) // 5)
    return max(0, min(100, lev + anger_boost))


def denunciation_quota(intensity: object) -> int:
    """烈度→检举条数硬门（#625 同款确定性选形，无 RNG）。"""
    try:
        value = int(intensity)
    except (TypeError, ValueError):
        value = 0
    n = 0
    for threshold, count in DENUNCIATION_INTENSITY_GATES:
        if value >= int(threshold):
            n = int(count)
    return n

def compose_denunciation_origin(*, is_true: bool) -> str:
    """检举 origin：base + 真/伪 mark（#619 compose_report_origin 单源）。"""
    mark = (
        ORIGIN_MARK_DENUNCIATION_TRUE
        if is_true
        else ORIGIN_MARK_DENUNCIATION_FALSE
    )
    return compose_report_origin(DENUNCIATION_ORIGIN_BASE, [mark])


def render_denunciation_memorial(
    *,
    accuser_name: object,
    subject_name: object,
    case_summary: object,
) -> str:
    """真/伪同一渲染函数：剔除案由变量后串相等（AC2 可证伪判据）。"""
    accuser = str(accuser_name or "").strip() or "臣工"
    subject = str(subject_name or "").strip() or "某人"
    case = str(case_summary or "").strip() or "差务"
    return f"{accuser}奏称：{subject}办理{case}有异状，请皇上按问。"


def denunciation_origin_ref(
    accuser_name: object, dossier_id: object, turn: object, *,
    is_true: bool,
) -> str:
    kind = "true" if is_true else "false"
    return (
        f"denunciation:{kind}:{str(accuser_name or '').strip()}"
        f":dossier:{int(dossier_id)}:turn:{int(turn)}"
    )


def pick_denunciation_accusers(
    names: Sequence[object],
    *,
    subject_name: object,
    dossier_id: object,
    quota: int,
) -> List[str]:
    """从敌派候选人中确定性取至多 quota 名（restore 可复现，无真 RNG）。"""
    subject = str(subject_name or "").strip()
    cleaned = sorted({
        str(n).strip()
        for n in names
        if str(n or "").strip() and str(n).strip() != subject
    })
    if not cleaned or int(quota) <= 0:
        return []
    seed = f"{subject}:{int(dossier_id)}:" + ",".join(cleaned)
    start = sum(ord(ch) for ch in seed) % len(cleaned)
    rotated = cleaned[start:] + cleaned[:start]
    return rotated[: int(quota)]


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
