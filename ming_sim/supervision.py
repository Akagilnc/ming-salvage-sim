"""#625 / ADR 0077 钝化事实底＋人身条件化判官口径；#627 政敌检举轨。

DB 只机械记事实（监督在场 / 空子暴露 / 任期读既有 appointment_tenure），
不建钝化数值列。判官读事实软判；本模块提供：
- 在场连号派生（不落库）
- 派系同/敌判定
- #619 origin 结构化私货/同派标记
- #627 政敌检举：fork 单源谓词、真伪 origin 派生、去重键（检举人×案卷×真伪类）
  （判断权归 LLM；引擎只供事实/承接 clamp/真伪底——禁烈度门/quota/文字模板）

#1895：原「孤直稽核满 12 月 → 自动立反制 issue」硬门退役——代码不再按
characters.integrity 档判定「这位大臣会不会反制」，也不再 hash 指定反制形态。
人物据其可及事实决定是否反制、采取何种行动（#1861 逐旨推演／#1843 世界段
run）；监督在场行、连续月数、稽核人派系与操守定性等事实素材全部照留。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from ming_sim.appointment_tenure import normalize_appointment_tenure
from ming_sim.participant_roster import resolve_dossier_owner_name
from ming_sim.qualitative import qualitative_character_axis

# 监督关系：本票只记「稽核」在场（护卫属 #567 押解口径，不入钝化事实底）
SUPERVISION_RELATION = "稽核"

# 督办判官读面的三个结构化键
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

# 人身条件化：操守定性档（读 characters.integrity，不落钝化分）
INTEGRITY_UPRIGHT_BANDS = frozenset({"操守清正", "清介可称"})  # 孤直型
INTEGRITY_MEDIOCRE_BANDS = frozenset({"操守多亏", "操守未稳", "操守平常"})  # 庸吏

# #1895：反制硬门常量（连续在场月数门／反制形态闭集／origin kind）随
# GameDB.trigger_supervision_countermeasures 一并退役——代码不再按 integrity 档
# 判定人物是否反制、不再 hash 指定反制形态。监督在场事实与稽核人定性仍照留，
# 供 #1861 逐旨推演／#1843 世界段 run 依人物可及事实自选。

def integrity_band(value: object) -> str:
    return str(qualitative_character_axis("integrity", value) or "")


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
    """#622/#627 fork 判据单源：有奏报且奏报与旨外实况或偏离执行格分叉。"""
    bands = [
        str(b).strip()
        for b in (reported_bands or ())
        if str(b or "").strip()
    ]
    outcome = str(execution_outcome or "").strip()
    return bool(bands) and (
        bool(beyond_intent) or outcome not in {"", "fulfilled", "executing"}
    )


def derive_denunciation_is_true(*, fork: bool) -> bool:
    """#627 真伪底机械对账：所指案卷真有分叉=真检举，无分叉=私货/诬告。"""
    return bool(fork)


def compose_denunciation_origin(*, is_true: bool) -> str:
    """检举 origin：base + 真/伪 mark（#619 compose_report_origin 单源）。"""
    mark = (
        ORIGIN_MARK_DENUNCIATION_TRUE
        if is_true
        else ORIGIN_MARK_DENUNCIATION_FALSE
    )
    return compose_report_origin(DENUNCIATION_ORIGIN_BASE, [mark])


def denunciation_case_upgraded(
    previous_payload: Mapping[str, object] | None,
    fork_state: Mapping[str, object],
) -> bool:
    """案情升级：新分叉或新旨外恶果 → 同人同案可再落（去重键例外）。"""
    prev = previous_payload if isinstance(previous_payload, Mapping) else {}
    prev_exp = prev.get("fork_exposure")
    if not isinstance(prev_exp, Mapping):
        prev_exp = {}
    cur_count = int(fork_state.get("actual_effect_count") or 0)
    prev_count = int(
        prev_exp.get("actual_effect_count")
        if prev_exp.get("actual_effect_count") is not None
        else prev.get("actual_effect_count") or 0
    )
    if cur_count > prev_count:
        return True
    cur_beyond = bool(fork_state.get("beyond_intent"))
    prev_beyond = bool(
        prev_exp.get("beyond_intent")
        if "beyond_intent" in prev_exp
        else prev.get("beyond_intent")
    )
    if cur_beyond and not prev_beyond:
        return True
    cur_fork = bool(fork_state.get("fork"))
    prev_fork = bool(prev.get("fork"))
    if cur_fork and not prev_fork:
        return True
    return False


DECLARED_REPORT_ACTION_MARKS = frozenset({
    ORIGIN_MARK_PRIVATE_GOODS,
    ORIGIN_MARK_SAME_FACTION_BLIND,
})


def declared_report_action_origin(raw: object, *, base: str) -> str:
    """月报 origin 只留下人物已经声明的睁眼闭眼或带私货。

    同派／敌派是监督事实，不是行动。未声明、或声明里夹着别的记号，都不写成行动。
    """
    text = str(raw or "").strip()
    if not text:
        return base
    if text.startswith("dossier-report:"):
        _root, parsed = parse_report_origin(text)
        marks = [mark for mark in parsed if mark in DECLARED_REPORT_ACTION_MARKS]
        return compose_report_origin(base, marks)
    parts = [part.strip() for part in text.split(ORIGIN_MARK_SEP) if part.strip()]
    marks = [part for part in parts if part in DECLARED_REPORT_ACTION_MARKS]
    return compose_report_origin(base, marks)


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
    """为督办复核解包监督读面的三个结构化键。"""
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
