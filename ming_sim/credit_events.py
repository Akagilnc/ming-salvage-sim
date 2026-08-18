"""#628 / ADR 0079 信用事件写端——只写不读。

载体=relation_edge_events；写口=record_relation_edge_event 唯一入口。
禁第二信用事件表/第二方向表/第二 origin 拼装器。
知遇类归 #479，本片不产。

跨家族字段（方案 b）：弃卒保车施弃方∈{皇帝,党魁} 由 origin 类型机械可判、
消费侧派生（见 scapegoat_actor_kind_from_origin）；写端零新列。

挽留回绝→辜负由 #623 breach_plea.finalize_persist 既有写口承担，本模块不重复实现。

语境=extraction 真叙事字段（note/reason/purpose/criterion_text），禁 CTX_* 模板（P7）。
去重=origin+端点写前判重，不动表 UNIQUE 结构。
识别只消费校验后未 rejected 的落格项（由 apply_score_extraction 后置传入）。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from ming_sim.breach_plea import _extract_ref_ids
from ming_sim.participant_roster import project_execution_liability_parties
from ming_sim.relations import CREDIT_DIRECTION, CREDIT_EDGE_KINDS, EMPEROR_NODE
from ming_sim.staged_commitment import (
    ENTRY_KIND_GRACE_PLEA,
    ENTRY_KIND_RUSH_REMONSTRANCE,
    TODO_STATUS_CONSUMED,
    TODO_STATUS_PENDING,
)
from ming_sim.urge_lever import resolve_host_character

# ── 事件类（0079 四类；知遇不在本片）────────────────────────────────
KIND_FULFILL = "兑现所托"
KIND_BETRAY = "辜负"
KIND_BACK = "撑腰"
KIND_SCAPEGOAT = "弃卒保车"

_WRITE_KINDS = frozenset({KIND_FULFILL, KIND_BETRAY, KIND_BACK, KIND_SCAPEGOAT})
assert _WRITE_KINDS <= CREDIT_EDGE_KINDS

# ── 结构化 origin 后缀（方案 b：类型可判）────────────────────────────
# dossier:{id}:credit:fulfill
# dossier:{id}:credit:back
# dossier:{id}:credit:scapegoat:pawn:{name}
# dossier:{id}:credit:scapegoat:car:{name}
# dossier:{id}:credit:cover:{name}
# issue:{id}:credit:grant_grace
# issue:{id}:credit:reject_grace
# issue:{id}:credit:reject_remonstrance

_ORIGIN_CREDIT = "credit"
_PUNISH_STATUSES = frozenset({
    "dismissed", "imprisoned", "exiled", "dead", "retired", "offstage",
})
_DOSSIER_REF_RE = re.compile(r"^dossier:([1-9][0-9]*)$")
_ISSUE_REF_RE = re.compile(r"^issue:([1-9][0-9]*)$")

# 玩家可见面禁词（内部 origin 片段 + 机读键；全族终验归 #629）
CREDIT_BANNED_PLAYER_TOKENS = (
    "credit:fulfill",
    "credit:back",
    "credit:scapegoat",
    "credit:cover",
    "credit:grant_grace",
    "credit:reject_grace",
    "credit:reject_remonstrance",
    "scapegoat_actor_kind",
    "credit_events",
    "CREDIT_EDGE_KINDS",
)

# 扫描面清单（与 #624/#622 同形；#629 收口全族）
CREDIT_BANNED_SCAN_SURFACES = (
    "scene_text",
    "narrative",
    "turn_report",
    "knowledge_items",
    "memorial_text",
    "origin_context",
    "criterion_text",
)

# 根基档/哭谏通道系统词（#623 场面投影剥离；#629 并入全族）
FOUNDATION_BANNED_PLAYER_TOKENS = (
    "foundation_tier",
    "assess_foundation_tier",
    "just_started",
    "halfway",
    "rooted",
    "midcourse_breach_plea",
)


def _family_p4_banned_tokens() -> tuple[str, ...]:
    """全族 P4 禁词并集——变形/真伪底/信用事件/钝化/根基档。"""
    from ming_sim.commitment_backlash import BACKLASH_BANNED_PLAYER_TOKENS
    from ming_sim.decree_vocabulary import (
        DEFORMATION_BANNED_PLAYER_TOKENS,
        URGE_TRUTH_BANNED_PLAYER_TOKENS,
    )
    from ming_sim.supervision import SUPERVISION_BANNED_PLAYER_TOKENS

    ordered: list[str] = []
    seen: set[str] = set()
    for token in (
        *DEFORMATION_BANNED_PLAYER_TOKENS,
        *URGE_TRUTH_BANNED_PLAYER_TOKENS,
        *SUPERVISION_BANNED_PLAYER_TOKENS,
        *CREDIT_BANNED_PLAYER_TOKENS,
        *BACKLASH_BANNED_PLAYER_TOKENS,
        *FOUNDATION_BANNED_PLAYER_TOKENS,
    ):
        if token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return tuple(ordered)


FAMILY_P4_BANNED_PLAYER_TOKENS = _family_p4_banned_tokens()


def assert_no_family_p4_banned_tokens(text: object, *, surface: str) -> None:
    """#629 全族 P4 哨兵：七扫描面共用。"""
    raw = str(text or "")
    for token in FAMILY_P4_BANNED_PLAYER_TOKENS:
        if token in raw:
            raise AssertionError(f"{surface} 裸露禁词：{token!r}")


def scapegoat_actor_kind_from_origin(origin: object) -> Optional[str]:
    """方案 b 消费侧契约：由 origin 类型机械派生施弃方∈{皇帝,党魁}。

    缺失或不识别 → None（0104/0102 fail-closed 不派生）。
    写端本片只产 dossier:…:credit:scapegoat:…（皇帝侧）。
    """
    text = str(origin or "").strip()
    # bind_origin_round 可能附 |round:N
    base = text.split("|", 1)[0]
    if ":credit:scapegoat:" not in base:
        return None
    if base.startswith("dossier:"):
        return "皇帝"
    if base.startswith("faction:") or base.startswith("party:"):
        return "党魁"
    return None


def _parse_dossier_ref(ref: object) -> Optional[int]:
    m = _DOSSIER_REF_RE.match(str(ref or "").strip())
    return int(m.group(1)) if m else None


def _parse_issue_ref(ref: object) -> Optional[int]:
    m = _ISSUE_REF_RE.match(str(ref or "").strip())
    return int(m.group(1)) if m else None


def _credit_origin(scope: str, scope_id: int, *parts: str) -> str:
    """唯一 origin 拼装器——禁第二拼装路径。"""
    tail = ":".join(str(p) for p in parts if str(p))
    if tail:
        return f"{scope}:{int(scope_id)}:{_ORIGIN_CREDIT}:{tail}"
    return f"{scope}:{int(scope_id)}:{_ORIGIN_CREDIT}"


def _narrative_context(*parts: object) -> str:
    """承接 extraction 真叙事字段；首个非空即用。禁固定句式模板。"""
    for part in parts:
        text = str(part or "").strip()
        if text:
            return text
    return ""


def _existing_edge_id(
    db: Any,
    *,
    source: str,
    target: str,
    event_kind: str,
    origin: str,
) -> Optional[int]:
    """写前按 origin+端点判重（不动表 UNIQUE；语境可变时仍幂等）。"""
    base = str(origin or "").strip()
    if not base:
        return None
    bare = base.split("|", 1)[0]
    row = db.conn.execute(
        """
        SELECT id FROM relation_edge_events
        WHERE source=? AND target=? AND event_kind=?
          AND (origin=? OR origin LIKE ?)
        ORDER BY id LIMIT 1
        """,
        (source, target, event_kind, base, f"{bare}|%"),
    ).fetchone()
    return int(row["id"]) if row is not None else None


def write_credit_event(
    db: Any,
    state: Any,
    *,
    person: str,
    event_kind: str,
    context: str,
    origin: str,
) -> int:
    """四字段薄记录写口：方向由 CREDIT_DIRECTION 决定，落 record_relation_edge_event。"""
    person = str(person or "").strip()
    kind = str(event_kind or "").strip()
    context = str(context or "").strip()
    origin = str(origin or "").strip()
    if not person:
        raise ValueError("信用事件缺少当事人")
    if kind not in _WRITE_KINDS:
        raise ValueError(f"非本片信用事件类目: {kind!r}")
    if not context:
        raise ValueError("信用事件语境不能为空")
    if not origin:
        raise ValueError("信用事件 origin 不能为空")
    direction = CREDIT_DIRECTION[kind]
    if direction == "emperor_to_person":
        source, target = EMPEROR_NODE, person
    else:
        source, target = person, EMPEROR_NODE
    existing = _existing_edge_id(
        db, source=source, target=target, event_kind=kind, origin=origin,
    )
    if existing is not None:
        return existing
    return int(
        db.record_relation_edge_event(
            source=source,
            target=target,
            event_kind=kind,
            context=context,
            origin=origin,
            turn=int(state.turn),
            year=int(state.year),
            period=int(state.period),
        )
    )


def _sponsor_names(db: Any, dossier_id: int) -> List[str]:
    dossier = db.get_decree_dossier(int(dossier_id))
    if not isinstance(dossier, dict):
        return []
    parties = project_execution_liability_parties(dossier.get("participant_roster"))
    names: List[str] = []
    seen: Set[str] = set()
    for p in parties:
        if str(p.get("responsibility") or "") != "primary":
            continue
        name = str(p.get("character_id") or "").strip()
        if name and name not in seen:
            seen.add(name)
            names.append(name)
    return names


def _commitment_ids_for_dossier(db: Any, dossier_id: int) -> List[int]:
    rows = db.conn.execute(
        "SELECT id FROM issues WHERE origin_ref=?",
        (f"dossier:{int(dossier_id)}",),
    ).fetchall()
    return [int(row["id"]) for row in rows]


def _dossier_has_urge_pressure(db: Any, dossier_id: int) -> bool:
    """撑完承诺：案卷所系承诺曾承催办压力。"""
    from ming_sim.urge_lever import collect_urge_history

    cids = _commitment_ids_for_dossier(db, dossier_id)
    if cids:
        for cid in cids:
            hist = collect_urge_history(
                db, commitment_ref=cid, dossier_id=int(dossier_id),
            )
            if hist:
                return True
        return False
    # 无承诺行时仍扫密令催办史（commitment_ref 占位 -1，不命中承诺层）
    hist = collect_urge_history(
        db, commitment_ref=-1, dossier_id=int(dossier_id),
    )
    return bool(hist)


def _fulfillment_context(db: Any, dossier_id: int, *, hint: object = "") -> str:
    text = _narrative_context(hint)
    if text:
        return text
    dossier = db.get_decree_dossier(int(dossier_id))
    if isinstance(dossier, dict):
        return _narrative_context(dossier.get("execution_note"))
    return ""


def record_fulfillment_credit(
    db: Any, state: Any, *, dossier_id: int, context: str = "",
) -> List[Dict[str, object]]:
    """兑付→兑现所托；若曾承催压则同落撑完承诺→撑腰。供 extraction / due_review 共调。

    只认 DB 已落格 fulfilled（防校验前伪事件）。
    """
    did = int(dossier_id)
    out: List[Dict[str, object]] = []
    dossier = db.get_decree_dossier(did)
    if not isinstance(dossier, dict):
        return out
    if str(dossier.get("execution_outcome") or "").strip() != "fulfilled":
        return out
    sponsors = _sponsor_names(db, did)
    if not sponsors:
        return out
    ctx = _fulfillment_context(db, did, hint=context)
    if not ctx:
        return out
    back = _dossier_has_urge_pressure(db, did)
    for person in sponsors:
        eid = write_credit_event(
            db, state,
            person=person,
            event_kind=KIND_FULFILL,
            context=ctx,
            origin=_credit_origin("dossier", did, "fulfill"),
        )
        out.append({
            "kind": KIND_FULFILL, "person": person,
            "dossier_id": did, "edge_id": eid,
        })
        if back:
            eid_b = write_credit_event(
                db, state,
                person=person,
                event_kind=KIND_BACK,
                context=ctx,
                origin=_credit_origin("dossier", did, "back"),
            )
            out.append({
                "kind": KIND_BACK, "person": person,
                "dossier_id": did, "edge_id": eid_b, "trigger": "撑完承诺",
            })
    return out


def _roster_entries(dossier: Dict[str, object]) -> List[Dict[str, object]]:
    roster = dossier.get("participant_roster") or []
    if not isinstance(roster, list):
        return []
    return [e for e in roster if isinstance(e, dict)]


def _pawn_car_pairs(roster: Sequence[Dict[str, object]]) -> List[Tuple[str, str]]:
    """卒=带委派人的主办/协办本人；车=其 delegator_id。"""
    pairs: List[Tuple[str, str]] = []
    seen: Set[Tuple[str, str]] = set()
    for entry in roster:
        tier = str(entry.get("tier") or "").strip()
        if tier not in {"主办", "协办"}:
            continue
        pawn = str(entry.get("character_id") or "").strip()
        car = str(entry.get("delegator_id") or "").strip()
        if not pawn or not car or pawn == car:
            continue
        key = (pawn, car)
        if key in seen:
            continue
        seen.add(key)
        pairs.append(key)
    return pairs


def _is_exposed_transformed(dossier: Dict[str, object]) -> bool:
    return str(dossier.get("execution_outcome") or "").strip() == "transformed"


def _person_change_items(extracted: Dict[str, object]) -> List[Dict[str, object]]:
    """消费调用方已滤 rejected 的落格项；本轴不再二次闸（单一保护点在 apply_score_extraction）。"""
    raw = extracted.get("人物变更") or extracted.get("person_changes") or []
    if not isinstance(raw, list):
        return []
    return [it for it in raw if isinstance(it, dict)]


def _item_dossier_id(item: Dict[str, object]) -> Optional[int]:
    for key in ("origin_ref", "来源引用"):
        did = _parse_dossier_ref(item.get(key))
        if did is not None:
            return did
    raw = item.get("dossier_id")
    if raw in (None, ""):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _item_narrative(item: Dict[str, object]) -> str:
    return _narrative_context(
        item.get("reason"),
        item.get("note"),
        item.get("说明"),
        item.get("status_reason"),
    )


def _is_punitive_change(item: Dict[str, object]) -> bool:
    action = str(item.get("动作") or item.get("action") or "").strip()
    if action == "罢黜":
        return True
    if action != "处置":
        return False
    status = str(item.get("status") or "").strip()
    return status in _PUNISH_STATUSES


def _is_cover_change(item: Dict[str, object]) -> bool:
    """包庇：非惩处性、仍挂变形案卷 origin 的人事动作（留任/开释口径）。"""
    if _is_punitive_change(item):
        return False
    action = str(item.get("动作") or item.get("action") or "").strip()
    if action in {"任命", "调任", "册封"}:
        return True
    if action == "处置":
        status = str(item.get("status") or "").strip()
        return status in {"active", "candidate"} or not status
    return False


def _group_person_sets(
    group: Sequence[Dict[str, object]],
) -> Tuple[Set[str], Set[str], Dict[str, str], str]:
    """分 punitive / covered，并收叙事。"""
    punitive: Set[str] = set()
    covered: Set[str] = set()
    by_person_ctx: Dict[str, str] = {}
    group_ctx = ""
    for it in group:
        name = str(it.get("name") or it.get("character_id") or "").strip()
        if not name:
            continue
        narr = _item_narrative(it)
        if narr:
            by_person_ctx[name] = narr
            if not group_ctx:
                group_ctx = narr
        if _is_punitive_change(it):
            punitive.add(name)
        elif _is_cover_change(it):
            covered.add(name)
    return punitive, covered, by_person_ctx, group_ctx


def _write_scapegoat_pair(
    db: Any,
    state: Any,
    *,
    did: int,
    pawn: str,
    car: str,
    context: str,
) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    if not context:
        return out
    for person, role in ((pawn, "pawn"), (car, "car")):
        origin = _credit_origin("dossier", did, "scapegoat", role, person)
        eid = write_credit_event(
            db, state,
            person=person,
            event_kind=KIND_SCAPEGOAT,
            context=context,
            origin=origin,
        )
        out.append({
            "kind": KIND_SCAPEGOAT,
            "person": person,
            "role": role,
            "dossier_id": did,
            "edge_id": eid,
            "actor_kind": scapegoat_actor_kind_from_origin(origin),
        })
    return out


def _write_cover_backs(
    db: Any,
    state: Any,
    *,
    did: int,
    targets: Set[str],
    punitive: Set[str],
    by_person_ctx: Dict[str, str],
    group_ctx: str,
) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    for person in sorted(targets):
        if person in punitive:
            continue
        ctx = by_person_ctx.get(person) or group_ctx
        if not ctx:
            continue
        eid = write_credit_event(
            db, state,
            person=person,
            event_kind=KIND_BACK,
            context=ctx,
            origin=_credit_origin("dossier", did, "cover", person),
        )
        out.append({
            "kind": KIND_BACK,
            "person": person,
            "disposition": "包庇",
            "dossier_id": did,
            "edge_id": eid,
        })
    return out


def resolve_disposition_credit_from_extraction(
    db: Any, state: Any, extracted: Dict[str, object],
) -> List[Dict[str, object]]:
    """处置映射：丢卒保车 / 包庇 / 查办(不记)。对象须为已暴露变形案卷。"""
    if not isinstance(extracted, dict):
        return []
    items = _person_change_items(extracted)
    if not items:
        return []

    by_dossier: Dict[int, List[Dict[str, object]]] = {}
    for it in items:
        did = _item_dossier_id(it)
        if did is None:
            continue
        by_dossier.setdefault(did, []).append(it)

    out: List[Dict[str, object]] = []
    for did, group in by_dossier.items():
        dossier = db.get_decree_dossier(int(did))
        if not isinstance(dossier, dict) or not _is_exposed_transformed(dossier):
            continue
        roster = _roster_entries(dossier)
        parties = project_execution_liability_parties(roster)
        primary_ids = {
            str(p["character_id"])
            for p in parties
            if str(p.get("responsibility") or "") == "primary"
            and str(p.get("character_id") or "").strip()
        }
        liability_ids = {
            str(p["character_id"])
            for p in parties
            if str(p.get("character_id") or "").strip()
        }

        punitive, covered, by_person_ctx, group_ctx = _group_person_sets(group)

        # 1) 丢卒保车：卒受惩、委派人未惩 → 两笔弃卒保车
        scapegoat_hit = False
        for pawn, car in _pawn_car_pairs(roster):
            if pawn in punitive and car not in punitive:
                scapegoat_hit = True
                ctx = by_person_ctx.get(pawn) or group_ctx
                out.extend(_write_scapegoat_pair(
                    db, state, did=did, pawn=pawn, car=car, context=ctx,
                ))
        if scapegoat_hit:
            continue

        # 2) 查办：惩处落在连坐责任面（主办/委派）→ 不记事件
        if punitive & liability_ids:
            out.append({
                "kind": None,
                "disposition": "查办",
                "dossier_id": did,
                "punitive": sorted(punitive & liability_ids),
                "edge_id": None,
            })
            continue

        # 3) 包庇：责任面求交（删 or covered 兜底逸出）
        cover_targets = (covered & liability_ids) or (covered & primary_ids)
        out.extend(_write_cover_backs(
            db, state,
            did=did,
            targets=cover_targets,
            punitive=punitive,
            by_person_ctx=by_person_ctx,
            group_ctx=group_ctx,
        ))
    return out


def _grace_purpose(text: object) -> bool:
    s = str(text or "")
    return any(tok in s for tok in ("宽限", "准宽限", "展限", "宽之"))


def _issue_refs_strict(item: Dict[str, object]) -> Set[int]:
    """资金项专用：只认 issue_id/commitment_ref/origin_ref/target_id，禁裸 id 误吞。"""
    out: Set[int] = set()
    for key in ("issue_id", "commitment_ref"):
        raw = item.get(key)
        if raw in (None, ""):
            continue
        try:
            out.add(int(raw))
        except (TypeError, ValueError):
            continue
    tid = str(item.get("target_id") or "").strip()
    if tid.startswith("issue:"):
        try:
            out.add(int(tid.split(":", 1)[1]))
        except (TypeError, ValueError):
            pass
    for key in ("origin_ref", "来源引用"):
        iid = _parse_issue_ref(item.get(key))
        if iid is not None:
            out.add(iid)
    return out


def _collect_grant_issue_ids(extracted: Dict[str, object]) -> Set[int]:
    """准宽限：显式宽限叙事 + 非负资金；issue_advances / 负 delta 不算准。"""
    grant_ids: Set[int] = set()
    for key in ("economy_moves", "fiscal_creates", "fiscal_changes"):
        for it in extracted.get(key) or []:
            if not isinstance(it, dict) or it.get("rejected"):
                continue
            purpose = str(
                it.get("purpose") or it.get("reason") or it.get("category") or ""
            )
            if not _grace_purpose(purpose):
                continue
            try:
                delta = int(it.get("delta") or 0)
            except (TypeError, ValueError):
                delta = 0
            if delta < 0:
                continue
            grant_ids |= _issue_refs_strict(it)
    return grant_ids


def _collect_reject_issue_ids(extracted: Dict[str, object]) -> Set[int]:
    """拒/斥退：只认 cancels 显式信号；close_issues / 办砸终值不算。"""
    cancels = [
        it for it in (extracted.get("cancels") or [])
        if isinstance(it, dict) and not it.get("rejected")
    ]
    return _extract_ref_ids(cancels, prefixes=("issue",))


def _pending_urge_todos(db: Any, state: Any) -> List[Dict[str, object]]:
    """只取已过召对窗的谏/宽限（created_turn < 当前 turn），与 #624 消费护栏同形。"""
    turn = int(getattr(state, "turn", 0) or 0)
    kinds = {ENTRY_KIND_GRACE_PLEA, ENTRY_KIND_RUSH_REMONSTRANCE}
    return [
        t for t in db.list_next_audience_todos(status=TODO_STATUS_PENDING)
        if str(t.get("entry_kind") or "") in kinds
        and int(t.get("created_turn") or 0) < turn
    ]


def _host_person_for_commitment(db: Any, cid: int) -> str:
    host = resolve_host_character(db, commitment_ref=cid, dossier_id=None)
    row = db.conn.execute(
        "SELECT origin_ref FROM issues WHERE id=?", (cid,),
    ).fetchone()
    if row is not None:
        did = _parse_dossier_ref(row["origin_ref"])
        if did is not None:
            host = resolve_host_character(
                db, commitment_ref=cid, dossier_id=did,
            )
    return str(host.get("name") or "").strip()


def _urge_todo_context(todo: Dict[str, object], *, grant_hint: str = "") -> str:
    return _narrative_context(
        grant_hint,
        todo.get("criterion_text"),
        todo.get("origin_context"),
    )


def _grant_narrative_for_issue(
    extracted: Dict[str, object], cid: int,
) -> str:
    for key in ("economy_moves", "fiscal_creates", "fiscal_changes"):
        for it in extracted.get(key) or []:
            if not isinstance(it, dict) or it.get("rejected"):
                continue
            if cid not in _issue_refs_strict(it):
                continue
            purpose = str(
                it.get("purpose") or it.get("reason") or it.get("category") or ""
            )
            if _grace_purpose(purpose):
                return _narrative_context(purpose, it.get("reason"), it.get("note"))
    return ""


def _resolve_one_urge_todo(
    db: Any,
    state: Any,
    todo: Dict[str, object],
    *,
    grant_ids: Set[int],
    reject_ids: Set[int],
    extracted: Dict[str, object],
) -> Optional[Dict[str, object]]:
    cid = int(todo["commitment_ref"])
    kind = str(todo.get("entry_kind") or "")
    person = _host_person_for_commitment(db, cid)
    if not person:
        return None

    if cid in grant_ids and cid not in reject_ids:
        decision = "准宽限"
        event_kind = KIND_BACK
        context = _urge_todo_context(
            todo, grant_hint=_grant_narrative_for_issue(extracted, cid),
        )
        origin = _credit_origin("issue", cid, "grant_grace")
    elif cid in reject_ids:
        if kind == ENTRY_KIND_GRACE_PLEA:
            decision = "拒宽限强催"
            origin = _credit_origin("issue", cid, "reject_grace")
        else:
            decision = "斥退顶谏"
            origin = _credit_origin("issue", cid, "reject_remonstrance")
        event_kind = KIND_BETRAY
        context = _urge_todo_context(todo)
    else:
        return None

    if not context:
        return None

    eid = write_credit_event(
        db, state,
        person=person,
        event_kind=event_kind,
        context=context,
        origin=origin,
    )
    consumed = db.mark_next_audience_todo_status(
        int(todo["id"]), TODO_STATUS_CONSUMED, commit=False,
    )
    return {
        "kind": event_kind,
        "person": person,
        "decision": decision,
        "todo_id": int(todo["id"]),
        "commitment_ref": cid,
        "entry_kind": kind,
        "edge_id": eid,
        "consumed": bool(consumed),
    }


def resolve_urge_credit_from_extraction(
    db: Any, state: Any, extracted: Dict[str, object], *, commit: bool = False,
) -> List[Dict[str, object]]:
    """谏处置三型：准宽限→撑腰；拒宽限强催/斥退顶谏→辜负。识别后消费 todo。"""
    if not isinstance(extracted, dict):
        return []
    pending = _pending_urge_todos(db, state)
    if not pending:
        return []

    grant_ids = _collect_grant_issue_ids(extracted)
    reject_ids = _collect_reject_issue_ids(extracted)

    out: List[Dict[str, object]] = []
    for todo in pending:
        row = _resolve_one_urge_todo(
            db, state, todo,
            grant_ids=grant_ids,
            reject_ids=reject_ids,
            extracted=extracted,
        )
        if row is not None:
            out.append(row)
    if commit and out:
        db.conn.commit()
    return out


def resolve_fulfillment_credit_from_extraction(
    db: Any, state: Any, extracted: Dict[str, object],
) -> List[Dict[str, object]]:
    """dossier_executions outcome=fulfilled → 兑付/撑完。

    消费调用方已滤 rejected 的落格项；本轴不再二次闸（单一保护点在
    apply_score_extraction 的 minus-rejections）。fulfilled 仍以 DB 终值为门。
    """
    if not isinstance(extracted, dict):
        return []
    out: List[Dict[str, object]] = []
    seen: Set[int] = set()
    for it in extracted.get("dossier_executions") or []:
        if not isinstance(it, dict):
            continue
        if str(it.get("outcome") or "").strip() != "fulfilled":
            continue
        try:
            did = int(it.get("dossier_id"))
        except (TypeError, ValueError):
            continue
        if did in seen:
            continue
        seen.add(did)
        out.extend(
            record_fulfillment_credit(
                db, state,
                dossier_id=did,
                context=_narrative_context(it.get("note"), it.get("reason")),
            )
        )
    return out


def resolve_credit_events_from_extraction(
    db: Any,
    state: Any,
    extracted: Dict[str, object],
    *,
    commit: bool = False,
) -> Dict[str, List[Dict[str, object]]]:
    """召对/结算 extraction 真入口同缝（resolve_breach_pleas_from_extraction 先例）。

    调用方须在 applier 校验之后传入未 rejected 落格项；本轴只写不读。
    不重复实现 #623 挽留回绝辜负。
    """
    if not isinstance(extracted, dict):
        return {
            "fulfillment": [],
            "dispositions": [],
            "urge": [],
        }
    fulfillment = resolve_fulfillment_credit_from_extraction(db, state, extracted)
    dispositions = resolve_disposition_credit_from_extraction(db, state, extracted)
    urge = resolve_urge_credit_from_extraction(
        db, state, extracted, commit=False,
    )
    if commit and (fulfillment or dispositions or urge):
        db.conn.commit()
    return {
        "fulfillment": fulfillment,
        "dispositions": dispositions,
        "urge": urge,
    }
