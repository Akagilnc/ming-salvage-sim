"""动作物化共享能力（#515 / #1871）。

分类器 run_materialize_pipeline 链已删。本模块保留：
- ACTION_CLUSTERS FieldSpec 目录（枚举/shape 真源）
- 现役写入共享 seam（stage_*_candidate、协饷/拨帑 shape、任免 path 辅助等）
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ming_sim.decree_vocabulary import TARGET_KINDS
from ming_sim.execution_pressure import write_locality_scope_for_target_kind
from ming_sim.executor_routing import duty_route_categories

from ming_sim.action_clusters import (
    ActionCluster,
    FieldSpec,
    EFFECT_MATERIALIZE,
    EFFECT_NOOP,
    cluster_by_kind,
    install_action_catalog,
    validate_action_candidate_shape,
)


def minister_speaker_role(
    minister_name: str,
    character: Any = None,
    db: Any = None,
) -> str:
    """ADR 0033 objective characterization for recovery speaker (not name/office alone)."""
    from ming_sim.context import faction_context_with_db, minister_dossier
    from ming_sim.models import Character

    ch = character
    if not isinstance(ch, Character) and db is not None:
        content = getattr(db, "content", None)
        roster = getattr(content, "characters", None) if content is not None else None
        if isinstance(roster, dict):
            found = roster.get(str(minister_name or "").strip())
            if isinstance(found, Character):
                ch = found
    if isinstance(ch, Character):
        parts = [
            f"{ch.name}，{ch.office}",
            minister_dossier(ch),
        ]
        if db is not None:
            parts.append(faction_context_with_db(ch, db))
        return "\n".join(p for p in parts if str(p or "").strip())
    office = str(getattr(ch, "office", "") or "").strip() if ch is not None else ""
    office_type = (
        str(getattr(ch, "office_type", "") or "").strip() if ch is not None else ""
    )
    bits = [p for p in (str(minister_name or "").strip(), office or office_type) if p]
    return "，".join(bits) or "大臣"












# ── handlers（委派既有 stage，不另造落库）────────────────────────────





def _persist_appointment_summon(
    session: Any,
    pending_id: int,
    person_name: str,
    *,
    promote_payload: bool,
    origin_chat_turn_id: int = 0,
) -> None:
    """Persist the dossier flag and its inactive origin as one staging unit.

    Shared success tail for new stage, same-person dedupe, and mode/tenure merge.
    Ledger person_names use the same roster/alias canonical key as 0009 applier.
    """
    from ming_sim.applier import atomic
    from ming_sim.audience_night import ensure_inactive_office_summon
    from ming_sim.session import _canonical_minister_key

    # Exact-name summon projections (commit/启程/origin) require the roster key;
    # raw extractor aliases must not land in inactive office:<pending_id> ledger.
    person_name = _canonical_minister_key(
        getattr(session, "content", None), str(person_name or "").strip(), session.db,
    )
    with atomic(session.db):
        if promote_payload:
            row = session.db.conn.execute(
                "SELECT payload_json FROM pending_actions WHERE id=?",
                (int(pending_id),),
            ).fetchone()
            if row is None:
                raise ValueError("任命后传召所关联的暂存任命不存在")
            stored = json.loads(row["payload_json"] or "{}")
            stored["summon_after"] = "是"
            session.db.conn.execute(
                "UPDATE pending_actions SET payload_json=? WHERE id=?",
                (json.dumps(stored, ensure_ascii=False), int(pending_id)),
            )
        ensure_inactive_office_summon(
            session.db, pending_id, person_name,
            night_id=int(session.db._current_open_night_id()),
            origin_chat_turn_id=int(origin_chat_turn_id or 0),
        )


def _same_direction_office_hits(
    db: Any,
    turn: int,
    *,
    name: str,
    office: str,
    action: str,
    region_id: str = "",
    content: Any = None,
    pend_for_minister: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """同名同职同向 pending 命中列表（调用方解释 0/1/多）。

    region_id 纳入任所身份：两省同名官不得误并；缺 region 的既有候选仍可命中
    以便字段后补。
    """
    return [
        r for r in _match_office_row_by_name_office(
            _list_pending_office_rows(
                db, int(turn), pend_for_minister=pend_for_minister,
            ),
            name=name,
            office=office,
            region_id=region_id,
            content=content,
            db=db,
        )
        if str(r.get("action") or "") == action
    ]


def _apply_existing_appointment_hit(
    session: Any,
    row: Dict[str, Any],
    *,
    extracted_mode: object = None,
    tenure_mark: Optional[str] = None,
    region_id: str = "",
    minister_name: str = "",
    turn: int = 0,
    person_name: str = "",
    summon_after: bool = False,
    origin_chat_turn_id: int = 0,
    annotate: bool = False,
    recommendation_fields: Optional[Dict[str, Any]] = None,
) -> int:
    """既有命中唯一合并点：原地更新（mode 可升可降、字段可补）→ 同一 id。

    mode 唯一规则 resolve_directive_mode(extracted→existing→ordinary)；
    调用方只传原始 extracted_mode，禁止各出口自行预过滤/只升不降。
    tenure / region_id 等字段标记原样补写。summon_after 与 annotate 同原子。
    """
    from ming_sim.applier import atomic
    from ming_sim.cli_backend import resolve_directive_mode

    with atomic(session.db):
        resolved = int(row["id"])
        if annotate:
            mode_mark = resolve_directive_mode(
                extracted=extracted_mode,
                existing=_office_payload(row).get("mode"),
            )
            pending_id = _annotate_office_pending_path(
                session.db,
                row,
                mode_mark=mode_mark,
                tenure_mark=tenure_mark,
                region_id=region_id,
                minister_name=minister_name,
                turn=turn,
            )
            if pending_id:
                resolved = int(pending_id)
        if recommendation_fields:
            current = session.db.conn.execute(
                "SELECT payload_json FROM pending_actions WHERE id=?", (resolved,),
            ).fetchone()
            stored = json.loads(current["payload_json"] or "{}")
            stored.update(recommendation_fields)
            session.db.conn.execute(
                "UPDATE pending_actions SET payload_json=? WHERE id=?",
                (json.dumps(stored, ensure_ascii=False), resolved),
            )
        if summon_after and person_name:
            _persist_appointment_summon(
                session,
                resolved,
                person_name,
                promote_payload=True,
                origin_chat_turn_id=int(origin_chat_turn_id or 0),
            )
        return resolved




def stage_pacification_candidate(
    db: Any,
    turn: int,
    minister_name: str,
    *,
    text: str,
    target_id: str,
    extracted_mode: object = None,
    source_chat_turn_id: object = 0,
    pend_for_minister: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Shared pacification candidate write: mode + same-target update.

    Reused by audience translation; commit resolves the target through
    _find_pacification_target.  ``source_chat_turn_id``（#1890）随新行落库。
    """
    from ming_sim.cli_backend import resolve_directive_mode

    target = str(target_id or "").strip()
    if not target:
        return 0
    body = str(text or "").strip()
    if not body:
        return 0

    pending_rows = list(pend_for_minister or [])
    if not pending_rows:
        pending_rows = [
            p for p in db.list_pending_actions(int(turn), minister_name=minister_name)
            if p.get("kind") == "directive" and p.get("status") == "pending"
        ]

    existing_id = 0
    existing_mode = None
    for row in pending_rows:
        if row.get("kind") != "directive":
            continue
        try:
            payload = json.loads(str(row.get("payload_json") or "{}"))
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("dossier_action_type") or "").strip() != "pacification":
            continue
        if str(payload.get("target_id") or "").strip() != target:
            continue
        existing_id = int(row["id"])
        existing_mode = payload.get("mode")
        break

    mode = resolve_directive_mode(extracted=extracted_mode, existing=existing_mode)
    staged = {
        "text": body,
        "actor": minister_name,
        "dossier_action_type": "pacification",
        "target_kind": "character",
        "target_id": target,
        "mode": mode,
    }
    if existing_id:
        return db.update_directive_candidate(existing_id, staged)
    return db.stage_directive_candidate(
        int(turn), minister_name, payload=staged,
        source_chat_turn_id=int(source_chat_turn_id or 0),
    )


def punish_actions_allowed() -> frozenset:
    """#517：punish_action 枚举唯一真源 = ACTION_CLUSTERS punishment FieldSpec.allowed。"""
    cluster = cluster_by_kind("punishment")
    if cluster is None:
        raise RuntimeError("punishment cluster not installed")
    for field in cluster.fields:
        if field.name == "punish_action":
            if field.allowed is None:
                raise RuntimeError("punish_action FieldSpec.allowed missing")
            return field.allowed
    raise RuntimeError("punish_action FieldSpec missing")


def punish_actions_effective() -> frozenset:
    """可物化的惩处动作（排除分类器占位「无」）。"""
    return punish_actions_allowed() - {"无"}


def appoint_actions_allowed() -> frozenset:
    """appoint_action 枚举唯一真源 = ACTION_CLUSTERS appointment FieldSpec.allowed。"""
    cluster = cluster_by_kind("appointment")
    if cluster is None:
        raise RuntimeError("appointment cluster not installed")
    for field in cluster.fields:
        if field.name == "appoint_action":
            if field.allowed is None:
                raise RuntimeError("appoint_action FieldSpec.allowed missing")
            return field.allowed
    raise RuntimeError("appoint_action FieldSpec missing")


def appoint_actions_effective() -> frozenset:
    """可物化的任免动作（排除分类器占位「无」）；层 A 与 mapper 共引。"""
    return appoint_actions_allowed() - {"无"}


def issue_dispositions_allowed() -> frozenset:
    """弹劾潮处置枚举唯一真源 = ACTION_CLUSTERS punishment 行。"""
    cluster = cluster_by_kind("punishment")
    if cluster is None:
        raise RuntimeError("punishment cluster not installed")
    for field_spec in cluster.fields:
        if field_spec.name == "issue_disposition":
            if field_spec.allowed is None:
                raise RuntimeError("issue_disposition FieldSpec.allowed missing")
            return field_spec.allowed - {"无"}
    raise RuntimeError("issue_disposition FieldSpec missing")


def stage_punishment_candidate(
    db: Any,
    turn: int,
    minister_name: str,
    *,
    text: str,
    target_id: str,
    punish_action: str,
    extracted_mode: object = None,
    amount: object = 0,
    transaction_category: object = "",
    backing_dossier_id: object = None,
    issue_id: object = None,
    issue_disposition: object = None,
    source_chat_turn_id: object = 0,
    pend_for_minister: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Shared punishment candidate write: mode + same-target update.

    ``source_chat_turn_id``（#1890）随新行落库。
    """
    from ming_sim.cli_backend import resolve_directive_mode

    target = str(target_id or "").strip()
    action = str(punish_action or "").strip()
    disposition = str(issue_disposition or "").strip()
    linked_issue_id = 0
    if disposition in issue_dispositions_allowed() and issue_id is None:
        return 0
    if issue_id is not None:
        try:
            linked_issue_id = int(issue_id)
        except (TypeError, ValueError):
            return 0
        if linked_issue_id <= 0:
            return 0
        issue = db.conn.execute(
            "SELECT origin_kind,status,target_roster FROM issues WHERE id=?",
            (linked_issue_id,),
        ).fetchone()
        if issue is None or issue["status"] != "active" or issue["origin_kind"] != "impeachment_surge":
            return 0
        if disposition not in issue_dispositions_allowed():
            return 0
        try:
            roster = json.loads(str(issue["target_roster"] or "[]"))
        except (TypeError, ValueError):
            return 0
        if not isinstance(roster, list) or not roster:
            return 0
        if disposition == "办人":
            if target not in roster:
                return 0
            action = "拿问下狱"
        else:
            target = str(linked_issue_id)
            action = "无"
    if (not target and disposition != "压下") or (
        action not in punish_actions_effective() and disposition != "压下"
    ):
        return 0
    body = str(text or "").strip()
    if not body:
        return 0

    pending_rows = list(pend_for_minister or [])
    if not pending_rows:
        pending_rows = [
            p for p in db.list_pending_actions(int(turn), minister_name=minister_name)
            if p.get("kind") == "directive" and p.get("status") == "pending"
        ]

    existing_id = 0
    existing_mode = None
    for row in pending_rows:
        if row.get("kind") != "directive":
            continue
        try:
            payload = json.loads(str(row.get("payload_json") or "{}"))
        except (TypeError, ValueError):
            continue
        if not isinstance(payload, dict):
            continue
        if str(payload.get("dossier_action_type") or "").strip() != "punishment":
            continue
        if str(payload.get("target_id") or "").strip() != target:
            continue
        try:
            stored_issue_id = int(payload.get("issue_id") or 0)
        except (TypeError, ValueError):
            stored_issue_id = 0
        if stored_issue_id != linked_issue_id:
            continue
        existing_id = int(row["id"])
        existing_mode = payload.get("mode")
        break

    mode = resolve_directive_mode(extracted=extracted_mode, existing=existing_mode)
    staged = {
        "text": body,
        "actor": minister_name,
        "dossier_action_type": "punishment",
        "target_kind": "issue" if disposition == "压下" else "character",
        "target_id": target,
        "punish_action": action,
        "mode": mode,
    }
    if linked_issue_id:
        staged["issue_id"] = linked_issue_id
        staged["issue_disposition"] = disposition
    # #658：与 durable apply 共吃 require_backing_dossier_id，禁第二份 int/存在性分支
    # 省略时显式写 None，改草 merge 不得继承旧 backing 关联
    from ming_sim.db import require_backing_dossier_id
    backing = require_backing_dossier_id(db, backing_dossier_id)
    staged["backing_dossier_id"] = int(backing) if backing is not None else None
    category = str(transaction_category or "").strip()
    if linked_issue_id and disposition == "办人" and not category:
        category = "缉拿"
    if category:
        valid, _ = validate_action_candidate_shape(
            {"kind": "punishment", "transaction_category": category}
        )
        if not valid:
            return 0
        staged["transaction_category"] = category
    try:
        n = int(amount) if amount is not None and amount != "" else 0
    except (TypeError, ValueError):
        n = 0
    # #517 r2：罚俸 admission 要求正数 amount；缺/零/非法不得成候选。
    if action == "罚俸":
        if n <= 0:
            return 0
        staged["amount"] = n
    elif n > 0:
        staged["amount"] = n
    if existing_id:
        return db.update_directive_candidate(existing_id, staged)
    return db.stage_directive_candidate(
        int(turn), minister_name, payload=staged,
        source_chat_turn_id=int(source_chat_turn_id or 0),
    )




GRANT_ACTIONS = frozenset({
    "无", "赏赉", "发内帑", "加衔", "荫叙", "赈灾", "招抚屯田", "项目经费", "协饷",
})
GRANT_HONORIFICS = frozenset({"加衔", "荫叙"})
GRANT_MONEY_ACTIONS = GRANT_ACTIONS - {"无"} - GRANT_HONORIFICS
XIEXIANG_TARGET_KINDS = frozenset({"army"})


def _grant_shape_value_error(
    message: str,
    *,
    field: str,
    current: object = None,
    expected: object = None,
) -> ValueError:
    """ValueError carrying failed shape field + structured fact; callers catching ValueError unchanged."""
    exc = ValueError(message)
    exc.field = field  # type: ignore[attr-defined]
    exc.current = current  # type: ignore[attr-defined]
    exc.expected = expected  # type: ignore[attr-defined]
    return exc


def resolve_grant_account(*, grant_action: object = None, account: object = None) -> str:
    """grant account 归一唯一权威（无 DB）。

    #1620：shape / materialize / 协饷 共用——禁平行第二套 if 树。
    入口先太仓→国库；发内帑→内库；协饷已归一 raw 透传（空保持空，非法值留给
    xiexang 集缺，不在此 raise/默认国库）；其它金钱动作非法非空 raise、空→国库；
    其余（含 honorific）→""。
    """
    ga = str(grant_action or "").strip()
    raw_account = str(account or "").strip()
    if raw_account == "太仓":
        raw_account = "国库"
    if ga == "发内帑":
        return "内库"
    if ga == "协饷":
        return raw_account
    if ga in GRANT_MONEY_ACTIONS:
        if raw_account and raw_account not in {"国库", "内库"}:
            raise _grant_shape_value_error(
                f"grant 非法 account：{raw_account!r}",
                field="account",
                current=raw_account,
                expected=["国库", "内库"],
            )
        return raw_account if raw_account in {"国库", "内库"} else "国库"
    return ""


def require_grant_allocation_shape(
    *,
    grant_action: object = None,
    amount: object = None,
    account: object = None,
) -> Dict[str, Any]:
    """grant_allocation 金额/account shape 唯一权威（无 DB）。

    #1620：层 A 上桌与 rescript mapper 共用——禁平行第二套规则。
    顺序：action 闭集 → account（resolve_grant_account）→ amount（本函数独掌）。
    返回 grant_action、account；非 honorific 另含正 int amount。
    校验失败仍 raise ValueError；附 field 属性供物化缝转 typed 拒收（#1730）。
    """
    from ming_sim.strict_types import strict_int

    ga = str(grant_action or "").strip()
    grant_action_domain = sorted(GRANT_ACTIONS - {"无"})
    amount_expected: object = {"type": "positive_int"}
    if not ga:
        raise _grant_shape_value_error(
            "grant_allocation 缺 grant_action",
            field="grant_action",
            current=grant_action,
            expected=grant_action_domain,
        )
    if ga not in (GRANT_ACTIONS - {"无"}):
        raise _grant_shape_value_error(
            f"grant 非法 grant_action：{ga!r}",
            field="grant_action",
            current=ga,
            expected=grant_action_domain,
        )
    resolved_account = resolve_grant_account(grant_action=ga, account=account)
    out: Dict[str, Any] = {"grant_action": ga, "account": resolved_account}
    if ga in GRANT_HONORIFICS:
        return out
    if amount is None or amount == "":
        raise _grant_shape_value_error(
            "grant 金钱缺正 amount",
            field="amount",
            current=amount,
            expected=amount_expected,
        )
    # #1716：整数字符串是 classifier/LLM 运输常态（#658 normalize raw 直达本边界）；bool/float 仍拒。
    # #1620 原 accept_numeric_strings=False 把 "8" 一并拒掉，拟旨 grant 物化中断、pending 零落。
    try:
        amt = strict_int(amount, accept_numeric_strings=True)
    except ValueError as exc:
        raise _grant_shape_value_error(
            f"grant 金钱 amount 须为正整数，拒 {amount!r}",
            field="amount",
            current=amount,
            expected=amount_expected,
        ) from exc
    if amt <= 0:
        raise _grant_shape_value_error(
            "grant 金钱缺正 amount",
            field="amount",
            current=amount,
            expected=amount_expected,
        )
    out["amount"] = amt
    return out



def _grant_target(intent: Dict[str, Any]) -> Tuple[str, str]:
    action = str(intent.get("grant_action") or "").strip()
    name = str(intent.get("name") or "").strip()
    target_id = str(intent.get("target_id") or "").strip()
    if action in {"赏赉", "发内帑", "加衔", "荫叙"}:
        return "character", name or target_id
    if action == "项目经费":
        return "issue", target_id or name or action
    if action == "协饷":
        # 仅抛原始 target 文本；army id 解析在 stage 前完成，禁止把 region 标签硬改 army。
        # #1503：target_kind/target_id 须显式透传；缺失不得默认 army，不得用 name 代填。
        kind = str(intent.get("target_kind") or "").strip()
        return kind, target_id
    if action in {"赈灾", "招抚屯田"}:
        # #652：执行型赈济／招抚屯田均锚定属地省；recovery 单核读 region target。
        kind = "region" if target_id and target_id != action else "issue"
        return kind, target_id or name or action
    return "issue", target_id or name or action


def _resolve_xiexang_army_id(db: Any, raw_target: str) -> str:
    """#1503/#1620：协饷 target → 真实 army id；仅 compact 精确等值，禁模糊升格。"""
    tid = str(raw_target or "").strip()
    if not tid:
        return ""
    row = db.conn.execute("SELECT id FROM armies WHERE id=?", (tid,)).fetchone()
    if row is not None:
        return str(row["id"])
    content = getattr(db, "content", None)
    armies = getattr(content, "armies", None) if content is not None else None
    if armies:
        from ming_sim.matching import canonical_army_id_exact
        matched = canonical_army_id_exact(tid, armies)
        if matched:
            hit = db.conn.execute(
                "SELECT id FROM armies WHERE id=?", (matched,),
            ).fetchone()
            if hit is not None:
                return str(hit["id"])
    return ""


def canonicalize_xiexang_army_target(db: Any, raw_target: object) -> str:
    """显式 target → canonical army id；不可解析响亮拒绝（admission/dossier 共用）。"""
    tid = str(raw_target or "").strip()
    army_id = _resolve_xiexang_army_id(db, tid)
    if not army_id:
        raise DecreeMaterializationValidationError(
            f"协饷旨意 target 无法解析为军队：{tid!r}（不猜散文）",
            failed_fields=("target_kind", "target_id"),
        )
    return army_id


class DecreeMaterializationValidationError(ValueError):
    """Typed rejection raised before a decree candidate can be recorded."""

    def __init__(self, message: str, *, failed_fields: tuple[str, ...] = ()) -> None:
        self.failed_fields = failed_fields
        super().__init__(message)


class IncompleteXiexangPayloadError(DecreeMaterializationValidationError):
    def __init__(
        self,
        *,
        field_failures: list,
    ) -> None:
        # 权威 require_explicit_xiexang_fields 一次给出完整事实；此处只携带
        facts = tuple(dict(f) for f in field_failures)
        fields = tuple(str(f["field"]) for f in facts)
        self.missing_fields = fields  # compatibility alias for existing callers
        self.field_failures = facts
        super().__init__(
            "拨饷旨意缺少结构化字段："
            + "/".join(str(f) for f in fields)
            + "（不猜散文）",
            failed_fields=fields,
        )


def require_explicit_xiexang_fields(
    *,
    amount: object = 0,
    account: str = "",
    purpose: str = "",
    target_kind: str = "",
    target_id: str = "",
    cadence: str = "",
) -> Dict[str, Any]:
    """#1503 单一权威接缝：严格验形并归一 typed 字段。"""
    from ming_sim.strict_types import strict_int

    facts: list = []

    def _note(field: str, *, current: object, expected: object) -> None:
        facts.append({"field": field, "current": current, "expected": expected})

    try:
        n = strict_int(amount, accept_numeric_strings=False)
    except ValueError:
        n = 0
    if n <= 0:
        _note("amount", current=amount, expected={"type": "positive_int"})
    # #1620：太仓→国库唯一权威 resolve_grant_account；此处不再平行 if。
    canonical_account = resolve_grant_account(grant_action="协饷", account=account)
    if canonical_account not in {"国库", "内库"}:
        _note("account", current=account, expected=["国库", "内库"])
    purpose_cur = str(purpose or "").strip()
    if purpose_cur != "补饷":
        _note("purpose", current=purpose_cur or purpose, expected="补饷")
    canonical_target_kind = str(target_kind or "").strip()
    if canonical_target_kind not in XIEXIANG_TARGET_KINDS:
        _note(
            "target_kind",
            current=canonical_target_kind or target_kind,
            expected=sorted(XIEXIANG_TARGET_KINDS),
        )
    target_id_cur = str(target_id or "").strip()
    if not target_id_cur:
        _note("target_id", current=target_id, expected={"nonempty_str": True})
    cadence_value = str(cadence or "").strip()
    if cadence_value and cadence_value not in {"一次性", "每月"}:
        _note(
            "cadence",
            current=cadence_value,
            expected=["一次性", "每月", ""],
        )
    if facts:
        raise IncompleteXiexangPayloadError(field_failures=facts)
    return {
        "amount": n,
        "account": canonical_account,
        "purpose": "补饷",
        "target_kind": canonical_target_kind,
        "target_id": target_id_cur,
    }


def require_materializable_xiexang_payload(
    db: Any,
    *,
    text: object,
    amount: object = 0,
    account: str = "",
    purpose: str = "",
    target_kind: str = "",
    target_id: str = "",
    cadence: str = "",
) -> Dict[str, Any]:
    """协饷真实写入的完整前置条件；原生 grant 与 draft 投影共用。"""
    explicit = require_explicit_xiexang_fields(
        amount=amount,
        account=account,
        purpose=purpose,
        target_kind=target_kind,
        target_id=target_id,
        cadence=cadence,
    )
    body = str(text or "")
    if not body.strip():
        raise DecreeMaterializationValidationError(
            "协饷旨意缺少正文（不猜散文）", failed_fields=("text",),
        )
    army_id = canonicalize_xiexang_army_target(db, explicit["target_id"])
    cadence_value = str(cadence or "").strip() or "一次性"
    return {
        **explicit,
        "text": body,
        "target_id": army_id,
        "cadence": cadence_value,
    }


def stage_grant_allocation_candidate(
    db: Any,
    turn: int,
    minister_name: str,
    *,
    text: str,
    grant_action: str,
    target_kind: str,
    target_id: str,
    extracted_mode: object = None,
    amount: object = 0,
    account: str = "",
    purpose: str = "",
    cadence: str = "",
    execution_surface: object = None,
    end_turn: object = 0,
    deadline_months: object = 0,
    target_candidate: object = None,
    assignee: str = "",
    participant_roster: object = None,
    source_chat_turn_id: object = 0,
    pend_for_minister: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Shared grant candidate write: mode + explicit-target update only.

    Same grant_action+target_id alone must not overwrite. Independent 另拨/再赏
    each stage a new candidate (#502 / #518); only a structured target_candidate
    id updates the named pending grant.  ``source_chat_turn_id``（#1890）随新行落库。
    """
    from ming_sim.cli_backend import resolve_directive_mode

    action = str(grant_action or "").strip()
    target = str(target_id or "").strip()
    kind = str(target_kind or "").strip()
    body = str(text or "").strip()
    if action not in (GRANT_ACTIONS - {"无"}):
        return 0
    # #1503：协饷完整写入前置由同一权威缝收集；此处不补值。
    if action == "协饷":
        explicit = require_materializable_xiexang_payload(
            db,
            text=body,
            amount=amount,
            account=account,
            purpose=purpose,
            target_kind=kind,
            target_id=target,
            cadence=cadence,
        )
        n = int(explicit["amount"])
        account = str(explicit["account"])
        purpose = str(explicit["purpose"])
        kind = str(explicit["target_kind"])
        target = str(explicit["target_id"])
        cadence = str(explicit["cadence"])
        army_id = target
    else:
        if not target or not kind:
            return 0
        if not body:
            return 0
        # #1620：非协饷写 pending 前消费 shape 唯一权威；删宽松 int(amount or 0)
        # #1730：物化缝把 shape 族裸 ValueError 转为 typed 拒收（权威函数语义不动）。
        try:
            shaped = require_grant_allocation_shape(
                grant_action=action,
                amount=amount,
                account=account,
            )
        except ValueError as exc:
            field = str(getattr(exc, "field", "") or "").strip() or "amount"
            raise DecreeMaterializationValidationError(
                str(exc), failed_fields=(field,),
            ) from exc
        n = int(shaped["amount"]) if "amount" in shaped else 0
        account = str(shaped.get("account") or "")

    pending_rows = list(pend_for_minister or [])
    if not pending_rows:
        pending_rows = [
            p for p in db.list_pending_actions(int(turn), minister_name=minister_name)
            if p.get("kind") == "directive" and p.get("status") == "pending"
        ]

    # #502 semantics: update only when structured pointing names a candidate id.
    existing_id = 0
    existing_mode = None
    pointed = str(target_candidate or "").strip()
    if pointed.isdigit():
        want_id = int(pointed)
        for row in pending_rows:
            if row.get("kind") != "directive":
                continue
            if int(row["id"]) != want_id:
                continue
            try:
                payload = json.loads(str(row.get("payload_json") or "{}"))
            except (TypeError, ValueError):
                break
            if not isinstance(payload, dict):
                break
            if str(payload.get("dossier_action_type") or "").strip() != "grant_allocation":
                break
            existing_id = want_id
            existing_mode = payload.get("mode")
            break

    mode = resolve_directive_mode(extracted=extracted_mode, existing=existing_mode)
    staged = {
        "text": body,
        "actor": minister_name,
        "dossier_action_type": "grant_allocation",
        "target_kind": kind,
        "target_id": target,
        "grant_action": action,
        "mode": mode,
    }
    # #654/#1624：本路径为 grant materialize 自建 staged（无 LLM 属地字段），
    # 不属三入口 structured_decree 契约；仅缺省补全，非覆盖已给 locality。
    staged["locality_scope"] = write_locality_scope_for_target_kind(kind)
    if account in {"国库", "内库"}:
        staged["account"] = account
    if cadence in {"一次性", "每月"}:
        staged["cadence"] = cadence
    if n > 0:
        staged["amount"] = n
    # #1503：仅显式协饷成案透传 purpose；army 对象的军械/筑城/项目经费不得升格销欠。
    if action == "协饷":
        # fail-loud 已在上方完成；army_id 已解析通过，此处只归一化载荷、不补五字段。
        if not cadence:
            staged["cadence"] = "一次性"
            cadence = "一次性"
        staged["amount"] = n
        staged["account"] = account
        staged["purpose"] = purpose
        staged["target_kind"] = kind
        staged["target_id"] = army_id
        if cadence != "每月":
            # 颁布即扣库+销欠；在途只留叙事，不进机械对账轨。
            staged["execution_surface"] = "immediate"
    else:
        # 改案离开协饷时显式清 pay-only 残留，防止 merge 保留 purpose/immediate。
        staged["purpose"] = ""
        # #1624：普通 grant 原样转发字符串/空值；值域由 durable 独家验并对异常非空 fail-loud。
        staged["execution_surface"] = str(execution_surface or "").strip()
    # #1783：同一事完成期限挂本案；日级不足一月由分类器填截止回合=turn+1。
    # 期限单源＝due_turn（军令同款；禁 end_turn 双写）。
    absolute_due = _assignment_absolute_end_turn(
        int(turn), end_turn=end_turn, deadline_months=deadline_months,
    )
    if absolute_due > int(turn):
        staged["due_turn"] = absolute_due
        # 题名真源贯到 staged（0076 场面/判据可读）；优先用途/拨帑动作中文锚
        if not str(staged.get("title") or "").strip():
            label = purpose or action
            if label:
                staged["title"] = str(label).strip()
    # #1783+#1778：承办人/名单来自分类器或后置抽取，挂本案；不把当前大臣填成主办。
    lead = str(assignee or "").strip()
    if lead:
        staged["assignee"] = lead
    if isinstance(participant_roster, list) and participant_roster:
        staged["participant_roster"] = list(participant_roster)
    elif lead:
        staged["participant_roster"] = [{
            "character_id": lead, "tier": "主办", "role": "", "delegator_id": None,
        }]
    if existing_id:
        return db.update_directive_candidate(existing_id, staged)
    return db.stage_directive_candidate(
        int(turn), minister_name, payload=staged,
        source_chat_turn_id=int(source_chat_turn_id or 0),
    )



def _parse_json_field(raw: object) -> Any:
    """Classifier FieldSpec 只能承字符串；dict/list JSON 串在此还原。"""
    if isinstance(raw, (dict, list)):
        return raw
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return text
    return value


def _assignment_absolute_end_turn(
    turn: int, end_turn: object = 0, deadline_months: object = 0,
) -> int:
    """相对期限 → 绝对 end_turn（既有 initiative 契约：end_turn = turn + N）。

    - 显式期限月数优先：deadline_months=N → turn+N
    - end_turn 已严格大于当前 turn → 视为绝对回合
    - 否则 0<end_turn≤turn → 视为相对月数 turn+end_turn
    """
    try:
        et = int(end_turn or 0)
    except (TypeError, ValueError):
        et = 0
    try:
        months = int(deadline_months or 0)
    except (TypeError, ValueError):
        months = 0
    cur = int(turn)
    if months > 0:
        return cur + months
    if et > cur:
        return et
    if et > 0:
        return cur + et
    return 0



















# 纯授权案卷归收权·罢差（ADR 0041/0071）；不得入撤回成命目标域。







_RESPONSIBLE_BODY_SPLIT = re.compile(r"[,，、/;／|]")


def re_split_bodies(text: str) -> List[str]:
    """下议机关名分隔：逗号/顿号/斜线/分号/竖线（三缝共用）。"""
    return _RESPONSIBLE_BODY_SPLIT.split(str(text or ""))


def parse_responsible_bodies(raw: object) -> List[str]:
    """下议 responsible_bodies 唯一解析（暂存/admission/判后共用）。

    承 list/tuple，或 JSON 数组串，或「吏部、户部」类分隔串；空/不可用 → []。
    不在此做人物档语义；机关/职司个人名策略见 assert_responsible_bodies_org_only。
    """
    value = _parse_json_field(raw)
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        parts = [p.strip() for p in re_split_bodies(text) if p.strip()]
        out: List[str] = []
        for name in parts:
            if name not in out:
                out.append(name)
        return out
    if not isinstance(value, (list, tuple)):
        return []
    out = []
    for item in value:
        name = str(item or "").strip()
        if name and name not in out:
            out.append(name)
    return out


def character_person_names(db: Any) -> set[str]:
    """既有人物档名集合（禁新建机关词表；个人名比对复用此源）。"""
    if db is None or not hasattr(db, "conn"):
        return set()
    return {
        str(row["name"]).strip()
        for row in db.conn.execute("SELECT name FROM characters").fetchall()
        if str(row["name"] or "").strip()
    }


def assert_responsible_bodies_org_only(
    bodies: Sequence[str],
    *,
    known_person_names: Iterable[str] = (),
    current_minister: str = "",
) -> None:
    """机关/职司语义：个人名与当前召对大臣不得入 responsible_bodies。"""
    persons = {str(n).strip() for n in known_person_names if str(n or "").strip()}
    minister = str(current_minister or "").strip()
    if minister:
        persons.add(minister)
    if not persons:
        return
    for body in bodies:
        name = str(body or "").strip()
        if name and name in persons:
            raise ValueError(f"responsible_bodies 禁个人名：{name}")





def _list_pending_office_rows(
    db: Any,
    turn: int,
    *,
    pend_for_minister: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """本夜/本回合 pending 人事候选（kind=office）。不另建索引。"""
    rows = list(pend_for_minister or [])
    if not rows:
        rows = list(db.list_pending_actions(int(turn)))
    out: List[Dict[str, Any]] = []
    for row in rows:
        if row.get("kind") != "office":
            continue
        if str(row.get("status") or "pending") != "pending":
            continue
        out.append(row)
    return out


def _office_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    try:
        payload = json.loads(str(row.get("payload_json") or "{}"))
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _match_office_row_by_name_office(
    rows: Sequence[Dict[str, Any]],
    *,
    name: str,
    office: str,
    region_id: str = "",
    content: Any = None,
    db: Any = None,
) -> List[Dict[str, Any]]:
    """人+职(+任所)联合匹配；姓名或官职缺一则零命中（禁姓名-only 旁路）。

    两省同名官：双方都带 region 且不同 → 不命中。既有缺 region、后来补上 →
    仍命中，供合并点后补字段。中央无 region 身份两边皆空，照常匹配。
    """
    from ming_sim.session import _canonical_minister_key

    want_name = str(name or "").strip()
    want_office = str(office or "").strip()
    want_region = str(region_id or "").strip()
    if not want_name or not want_office:
        return []
    key = _canonical_minister_key(content, want_name, db) if want_name else ""
    hits: List[Dict[str, Any]] = []
    for row in rows:
        payload = _office_payload(row)
        staged_name = str(payload.get("name") or "").strip()
        if not staged_name:
            continue
        staged_key = (
            _canonical_minister_key(content, staged_name, db) if staged_name else staged_name
        )
        if staged_key != key and staged_name != want_name:
            continue
        staged_office = str(payload.get("office") or "").strip()
        if staged_office != want_office:
            continue
        staged_region = str(
            payload.get("region_id") or payload.get("任所") or payload.get("辖区") or ""
        ).strip()
        if want_region and staged_region and want_region != staged_region:
            continue
        hits.append(row)
    return hits





def _annotate_office_pending_path(
    db: Any,
    row: Dict[str, Any],
    *,
    mode_mark: Optional[str] = None,
    tenure_mark: Optional[str] = None,
    region_id: str = "",
    minister_name: str = "",
    turn: int = 0,
) -> int:
    """原地改写 office pending：typed mode 可升可降；署理只写 任别；任所可后补。

    mode 唯一规则同 resolve_directive_mode：调用方传入已 resolve 的
    midzhi|ordinary；此处负责落到 payload（含既有 midzhi 被显式 ordinary 降级）。
    region_id 后补：命中既有候选后把后来的 typed 任所写入，不得吞掉。
    """
    seat = str(region_id or "").strip()
    if not mode_mark and not tenure_mark and not seat:
        return 0
    pending_id = int(row["id"])
    payload = dict(_office_payload(row))
    changed = False
    if mode_mark in {"midzhi", "ordinary"} and payload.get("mode") != mode_mark:
        payload["mode"] = mode_mark
        changed = True
    if tenure_mark == "署理" and payload.get("任别") != "署理":
        payload["任别"] = "署理"
        payload.pop("appointment_tenure", None)
        changed = True
    existing_seat = str(
        payload.get("region_id") or payload.get("任所") or payload.get("辖区") or ""
    ).strip()
    if seat and not existing_seat:
        payload["region_id"] = seat
        changed = True
    if not changed and (
        (mode_mark in {"midzhi", "ordinary"} and payload.get("mode") == mode_mark)
        or (tenure_mark == "署理" and payload.get("任别") == "署理")
        or (seat and existing_seat == seat)
    ):
        # 语义已在：仍回 id（no-op 去重存活），可补留痕
        _write_path_nature_ledger(
            db,
            pending_id=pending_id,
            payload=payload,
            mode_mark=mode_mark,
            tenure_mark=tenure_mark,
            minister_name=minister_name,
            turn=turn,
        )
        return pending_id
    if not changed:
        return pending_id

    updated = db.update_office_candidate_payload(pending_id, payload)
    if updated:
        _write_path_nature_ledger(
            db,
            pending_id=pending_id,
            payload=payload,
            mode_mark=mode_mark,
            tenure_mark=tenure_mark,
            minister_name=minister_name,
            turn=turn,
        )
    return int(updated or pending_id)


def _write_path_nature_ledger(
    db: Any,
    *,
    pending_id: int,
    payload: Dict[str, Any],
    mode_mark: Optional[str],
    tenure_mark: Optional[str],
    minister_name: str,
    turn: int,
) -> None:
    """0035 故事账开放标签：关联候选 id / 本轮 origin；撤回走 0038 按 source 删。"""
    from ming_sim.audience_night import append_ledger_entry, get_open_night

    open_n = get_open_night(db)
    if open_n is None:
        return
    tags: List[str] = [f"pending:{int(pending_id)}"]
    labels: List[str] = []
    if mode_mark == "midzhi":
        tags.append("特旨")
        labels.append("特旨")
    if tenure_mark == "署理":
        tags.append("署理")
        labels.append("署理")
    if not labels:
        return
    name = str(payload.get("name") or "").strip()
    office = str(payload.get("office") or "").strip()
    body = (
        f"路径应答：{'/'.join(labels)}"
        + (f" · {name}" if name else "")
        + (f"/{office}" if office else "")
        + f" · pending:{int(pending_id)}"
    )
    source_cid = 0
    try:
        last = db.get_last_active_chat_turn(str(minister_name or ""), int(turn))
    except Exception:
        last = None
    if last is not None:
        source_cid = int(last.get("id") or 0)
    persons = [name] if name else ([minister_name] if minister_name else [])
    append_ledger_entry(
        db,
        int(open_n["id"]),
        person_names=persons,
        body=body,
        tags=tags,
        source_chat_turn_id=source_cid,
        check_dead=False,
    )





def _authorization_privilege(raw: object) -> str:
    """公开委任默认 privilege=便宜行事；显式四闭集权项原样保留。"""
    from ming_sim.authority_privileges import AUTHORITY_PRIVILEGE_SET

    priv = str(raw or "").strip()
    if priv in {"", "无"}:
        return "便宜行事"
    if priv in AUTHORITY_PRIVILEGE_SET:
        return priv
    return ""

def _authorization_scope_parts(
    target_id: object = "",
    *,
    target_kind: object = "",
    scope: object = "",
) -> Optional[Tuple[str, str, str]]:
    """公开委任事域：典范键 target_kind:target_id；缺事域 → None。"""
    raw_scope = str(scope or "").strip()
    if raw_scope and ":" in raw_scope:
        kind, _, tid = raw_scope.partition(":")
        kind = kind.strip()
        tid = tid.strip()
        if kind and tid:
            return kind, tid, f"{kind}:{tid}"
    tid = str(target_id or "").strip()
    kind = str(target_kind or "").strip()
    if tid and ":" in tid and not kind:
        kind, _, rest = tid.partition(":")
        kind = kind.strip()
        rest = rest.strip()
        if kind and rest:
            return kind, rest, f"{kind}:{rest}"
    if not tid:
        return None
    if not kind:
        kind = "issue"
    return kind, tid, f"{kind}:{tid}"

_PURE_AUTHORITY_DOSSIER_ACTIONS = frozenset({
    "authorization", "secret_authorization",
})


def _dossier_is_revocable_decree(db: Any, dossier: Dict[str, Any]) -> bool:
    """可撤成命：已颁/执行中的承诺·旨意；纯授权归收权·罢差。

    另：已结案但**实效仍在**的偿还序旨仍可撤（#1894）——closed 只说明那道案卷
    的办理有终局，不等于它压住的祖制默认序/系数已退出格律。判据读既有账本
    （pay_order.dossier_override_still_in_force），不全面放开 closed 案卷，也不
    反演旧账。

    直接 dossier、initiative 回指、含糊候选三入口共用本资格。
    """
    status = str(dossier.get("status") or "").strip()
    action = str(dossier.get("action_type") or "").strip()
    if action in _PURE_AUTHORITY_DOSSIER_ACTIONS:
        return False
    if status in {"promulgated", "executing"}:
        return True
    if status == "closed" and action == "pay_order_override":
        from ming_sim.pay_order import dossier_override_still_in_force

        return dossier_override_still_in_force(db, int(dossier["id"]))
    return False

def _parse_revoke_decree_target(
    db: Any, *,
    target_id: object = "",
    target_kind: object = "",
    target_candidate: object = "",
) -> Optional[Dict[str, Any]]:
    """解析撤回成命目标：仅承诺/旨意（dossier/initiative）；须可走 0056。

    - 纯授权拒（归收权·罢差）
    - issue 仅 active initiative，且 origin_ref 回指可撤案卷（禁 standalone 免代价）
    - dossier 须已颁/执行中
    """
    if str(target_candidate or "").strip() == "含糊":
        return None
    raw = str(target_id or "").strip()
    if not raw:
        return None
    if raw.startswith("authority:"):
        return None  # 纯授权归收权·罢差
    kind = str(target_kind or "").strip()
    if raw.startswith("dossier:"):
        kind = "dossier"
        raw = raw.split(":", 1)[1].strip()
    elif raw.startswith("issue:"):
        kind = "issue"
        raw = raw.split(":", 1)[1].strip()
    if not kind:
        kind = "dossier"
    try:
        tid = int(raw)
    except (TypeError, ValueError):
        return None
    if tid <= 0:
        return None
    if kind == "issue":
        row = db.conn.execute("SELECT * FROM issues WHERE id=?", (tid,)).fetchone()
        if row is None:
            return None
        if str(row["kind"] or "").strip() != "initiative":
            return None
        if str(row["status"] or "").strip() != "active":
            return None
        linked = 0
        origin = str(row["origin_ref"] or "").strip()
        if origin.startswith("dossier:"):
            try:
                linked = int(origin.split(":", 1)[1])
            except (TypeError, ValueError):
                linked = 0
        # standalone / 无合法案卷来源：拒入闸，堵住 cancel_issue 免 0056 旁路
        if linked <= 0:
            return None
        dossier = db.get_decree_dossier(linked)
        if dossier is None or not _dossier_is_revocable_decree(db, dossier):
            return None
        return {
            "target_kind": "issue",
            "target_id": str(tid),
            "issue_id": tid,
            "dossier_id": linked,
        }
    dossier = db.get_decree_dossier(tid)
    if dossier is None or not _dossier_is_revocable_decree(db, dossier):
        return None
    return {
        "target_kind": "dossier",
        "target_id": str(tid),
        "dossier_id": tid,
        "issue_id": 0,
    }

def _resolve_unique_active_authority(
    db: Any,
    turn: int,
    *,
    authority_id: object = 0,
    holder_id: object = "",
    privilege: object = "",
) -> Optional[Dict[str, Any]]:
    """候选层：自然语言/结构字段唯一解析到现存在持 authority_records 行。

    0/多条 → None（不得发生产项）。显式 authority_id 优先。
    """
    holder = str(holder_id or "").strip()
    priv = str(privilege or "").strip()
    if priv in {"", "无"}:
        priv = ""
    try:
        aid = int(authority_id or 0)
    except (TypeError, ValueError):
        aid = 0
    if aid > 0:
        rec = db.get_authority(aid)
        if rec is None or bool(rec.get("revoked")):
            return None
        try:
            effective = int(rec.get("effective_turn") or 0)
        except (TypeError, ValueError):
            effective = 0
        if effective > int(turn):
            return None
        exp = rec.get("expires_turn")
        if exp not in (None, ""):
            try:
                if int(exp) < int(turn):
                    return None
            except (TypeError, ValueError):
                return None
        if holder and str(rec.get("holder_id") or "") != holder:
            return None
        if priv and str(rec.get("privilege") or "") != priv:
            return None
        return rec
    if not holder:
        return None
    matches = list(db.list_active_authorities(int(turn), holder_id=holder))
    if priv:
        matches = [
            m for m in matches if str(m.get("privilege") or "") == priv
        ]
    if len(matches) != 1:
        return None
    return matches[0]

def stage_assignment_candidate(
    db: Any,
    turn: int,
    minister_name: str,
    *,
    text: str,
    title: str = "",
    target_id: str = "",
    assignee: str = "",
    participant_roster: object = None,
    extracted_mode: object = None,
    commitment_kind: object = None,
    stop_condition: object = None,
    end_turn: object = 0,
    deadline_months: object = 0,
    ongoing_effects: object = None,
    stages: object = None,
    target_candidate: object = None,
    transaction_category: object = "",
    source_chat_turn_id: object = 0,
    pend_for_minister: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Shared assignment candidate write (#520 / #502).

    Independent matters each stage a new candidate; only a structured
    target_candidate id updates the named pending assignment (cross-round
    reinforce / ADR 0038 before-image).
    #1778：承办人/名单来自大臣复述后置抽取（assignee / participant_roster），
    代码不得把当前召对大臣填成 assignee；#520 r2 不设改派入口仍成立。
    #1565/0142：题名=显式 title|结构化 target_id 锚；正文唯一真源=payload.text；
    禁散文截题、禁空正文借题名伪造成功、禁缺锚静默丢单。
    """
    from ming_sim.cli_backend import resolve_directive_mode

    body = str(text or "").strip()
    if not body:
        raise DecreeMaterializationValidationError(
            "交办旨意缺少正文", failed_fields=("text",),
        )
    # 题名只认结构化锚；不得从正文/皇帝散文截取
    matter_title = str(title or "").strip() or str(target_id or "").strip()
    if not matter_title:
        raise DecreeMaterializationValidationError(
            "交办旨意缺少结构化题名（title 或 target_id）",
            failed_fields=("title",),
        )
    matter_id = str(target_id or "").strip() or matter_title
    actor = str(minister_name or "").strip()
    if not actor:
        return 0

    pending_rows = list(pend_for_minister or [])
    if not pending_rows:
        pending_rows = [
            p for p in db.list_pending_actions(int(turn), minister_name=minister_name)
            if p.get("kind") == "directive" and p.get("status") == "pending"
        ]

    existing_id = 0
    existing_mode = None
    pointed = str(target_candidate or "").strip()
    if pointed.isdigit():
        want_id = int(pointed)
        for row in pending_rows:
            if row.get("kind") != "directive":
                continue
            if int(row["id"]) != want_id:
                continue
            try:
                payload = json.loads(str(row.get("payload_json") or "{}"))
            except (TypeError, ValueError):
                break
            if not isinstance(payload, dict):
                break
            if str(payload.get("dossier_action_type") or "").strip() != "assignment":
                break
            existing_id = want_id
            existing_mode = payload.get("mode")
            break

    mode = resolve_directive_mode(extracted=extracted_mode, existing=existing_mode)
    staged: Dict[str, Any] = {
        # text = 旨意正文唯一真源（供 decree_text 与 initiative stage_text）
        "text": body,
        "actor": minister_name,
        "dossier_action_type": "assignment",
        "target_kind": "issue",
        "target_id": matter_id,
        "title": matter_title,
        "mode": mode,
    }
    try:
        origin_cid = int(source_chat_turn_id or 0)
    except (TypeError, ValueError):
        origin_cid = 0
    # #1890：来源轮不写进载荷——它只落 pending_actions.source_chat_turn_id 一列
    # （交办的统一身份）。载荷里留副本等于同一事实两处可写，改草与迟到转译
    # 会让两者漂移；成案侧已改读该列。
    category = str(transaction_category or "").strip()
    if category:
        staged["transaction_category"] = category
    # #1778：承办人只来后置抽取；禁止代码填当前召对大臣。
    lead = str(assignee or "").strip()
    if lead:
        staged["assignee"] = lead
    if isinstance(participant_roster, list):
        staged["participant_roster"] = list(participant_roster)
    # 承诺形状保留：until_stop 正常携带；缺 marker 的毒字段也不得在 stage 洗掉，
    # 交既有 initiative 校验在判后接缝拒收（#520 commitment-poison-shape-preservation）。
    kind_raw = str(commitment_kind or "").strip()
    parsed_stop = _parse_json_field(stop_condition)
    has_stop = parsed_stop not in (None, "", {})
    absolute_end = _assignment_absolute_end_turn(
        int(turn), end_turn=end_turn, deadline_months=deadline_months,
    )
    parsed_ongoing = _parse_json_field(ongoing_effects)
    has_ongoing = isinstance(parsed_ongoing, dict) and bool(parsed_ongoing)
    if kind_raw == "until_stop":
        staged["commitment_kind"] = "until_stop"
    # #620 AC2 / #1890 / ADR 0142：分段里程碑是机械事实（到期判账），只承接
    # **显式结构化** stages——JSON 数组串或已结构化列表，一律走库层
    # stages_to_json 的严格串行面：非 JSON 字符串响亮 ValueError（由交办分派
    # 的既有 except 收成 durable 拒收）。全仓已无任何接缝从散文正则反推年诺。
    from ming_sim.staged_commitment import stages_to_json
    stages_norm = json.loads(stages_to_json(stages))
    if kind_raw == "until_stop" or has_stop or absolute_end > 0 or has_ongoing or stages_norm:
        if has_stop:
            staged["stop_condition"] = parsed_stop
        if absolute_end > 0:
            staged["end_turn"] = absolute_end
        if has_ongoing:
            staged["ongoing_effects"] = parsed_ongoing
        if stages_norm:
            staged["stages"] = stages_norm
            staged["commitment_kind"] = staged.get("commitment_kind") or "until_stop"
            # 段派生 end_turn（max due）不写入候选/DB（#620 勿驱动 expire）
    if existing_id:
        return db.update_directive_candidate(existing_id, staged)
    return db.stage_directive_candidate(
        int(turn), minister_name, payload=staged,
        source_chat_turn_id=origin_cid,
    )

def stage_authorization_candidate(
    db: Any,
    turn: int,
    minister_name: str,
    *,
    text: str,
    privilege: object = "",
    target_id: object = "",
    target_kind: object = "",
    scope: object = "",
    extracted_mode: object = None,
    target_candidate: object = None,
    pend_for_minister: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Shared authorization candidate write (#528 / #611).

    holder = 确认闸对象 = 当前大臣；收夜只成案卷；授予走 authority_changes，判后物化。
    禁止技能 id / grant_skill 镜像。
    """
    from ming_sim.cli_backend import resolve_directive_mode

    if str(target_candidate or "").strip() == "含糊":
        return 0
    body = str(text or "").strip()
    if not body:
        return 0
    holder = str(minister_name or "").strip()
    if not holder:
        return 0
    priv = _authorization_privilege(privilege)
    if not priv:
        return 0
    parts = _authorization_scope_parts(
        target_id, target_kind=target_kind, scope=scope,
    )
    if parts is None:
        return 0
    kind, tid, scope_key = parts

    pending_rows = list(pend_for_minister or [])
    if not pending_rows:
        pending_rows = [
            p for p in db.list_pending_actions(int(turn), minister_name=minister_name)
            if p.get("kind") == "directive" and p.get("status") == "pending"
        ]
    existing_id = 0
    existing_mode = None
    pointed = str(target_candidate or "").strip()
    if pointed.isdigit():
        want_id = int(pointed)
        for row in pending_rows:
            if int(row["id"]) != want_id:
                continue
            try:
                payload = json.loads(str(row.get("payload_json") or "{}"))
            except (TypeError, ValueError):
                break
            if not isinstance(payload, dict):
                break
            if str(payload.get("dossier_action_type") or "").strip() != "authorization":
                break
            existing_id = want_id
            existing_mode = payload.get("mode")
            break

    mode = resolve_directive_mode(extracted=extracted_mode, existing=existing_mode)
    staged: Dict[str, Any] = {
        "text": body,
        "actor": minister_name,
        "dossier_action_type": "authorization",
        "target_kind": kind,
        "target_id": tid,
        "assignee": holder,
        "holder_id": holder,
        "name": holder,
        "privilege": priv,
        "scope": scope_key,
        "mode": mode,
    }
    # #654/#1624：authorization materialize 自建 staged（无 LLM 属地字段），
    # 不属三入口 structured_decree 契约；仅缺省补全，非覆盖已给 locality。
    staged["locality_scope"] = write_locality_scope_for_target_kind(kind)
    if existing_id:
        return db.update_directive_candidate(existing_id, staged)
    return db.stage_directive_candidate(int(turn), minister_name, payload=staged)


def stage_referral_candidate(
    db: Any,
    turn: int,
    minister_name: str,
    *,
    text: str,
    title: str = "",
    target_id: str = "",
    deadline_months: object = 0,
    responsible_bodies: object = None,
    extracted_mode: object = None,
    target_candidate: object = None,
    source_chat_turn_id: object = 0,
    pend_for_minister: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Shared referral candidate write (#524 / #502).

    下议只承 deadline_months(1–36) 与非空机关/职司 responsible_bodies；
    落 end_turn=turn+N 与 payload.responsible_bodies。禁个人 owner/assignee。
    initiative 按 ADR 0055 判后创建。
    #1565/0142：题名=显式 title|结构化 target_id 锚；正文唯一真源=payload.text；
    禁散文截题、禁空正文借题名伪造成功、禁缺锚静默丢单。
    """
    from ming_sim.cli_backend import resolve_directive_mode

    body = str(text or "").strip()
    if not body:
        raise DecreeMaterializationValidationError(
            "下议旨意缺少正文", failed_fields=("text",),
        )
    matter_title = str(title or "").strip() or str(target_id or "").strip()
    if not matter_title:
        raise DecreeMaterializationValidationError(
            "下议旨意缺少结构化题名（title 或 target_id）",
            failed_fields=("title",),
        )
    matter_id = str(target_id or "").strip() or matter_title

    try:
        months = int(deadline_months or 0)
    except (TypeError, ValueError):
        months = 0
    # FieldSpec int_hi=36 已在 normalize 夹紧；此处仍守 <=0 不产项
    if months <= 0:
        return 0
    bodies = parse_responsible_bodies(responsible_bodies)
    if not bodies:
        return 0
    try:
        assert_responsible_bodies_org_only(
            bodies,
            known_person_names=character_person_names(db),
            current_minister=minister_name,
        )
    except ValueError:
        return 0

    pending_rows = list(pend_for_minister or [])
    if not pending_rows:
        pending_rows = [
            p for p in db.list_pending_actions(int(turn), minister_name=minister_name)
            if p.get("kind") == "directive" and p.get("status") == "pending"
        ]

    existing_id = 0
    existing_mode = None
    pointed = str(target_candidate or "").strip()
    if pointed.isdigit():
        want_id = int(pointed)
        for row in pending_rows:
            if row.get("kind") != "directive":
                continue
            if int(row["id"]) != want_id:
                continue
            try:
                payload = json.loads(str(row.get("payload_json") or "{}"))
            except (TypeError, ValueError):
                break
            if not isinstance(payload, dict):
                break
            if str(payload.get("dossier_action_type") or "").strip() != "referral":
                break
            existing_id = want_id
            existing_mode = payload.get("mode")
            break

    mode = resolve_directive_mode(extracted=extracted_mode, existing=existing_mode)
    staged: Dict[str, Any] = {
        "text": body,
        "actor": minister_name,
        "dossier_action_type": "referral",
        "target_kind": "issue",
        "target_id": matter_id,
        "title": matter_title,
        "end_turn": int(turn) + months,
        "deadline_months": months,
        "responsible_bodies": bodies,
        "mode": mode,
    }
    try:
        origin_cid = int(source_chat_turn_id or 0)
    except (TypeError, ValueError):
        origin_cid = 0
    # #1890：同 stage_assignment_candidate——来源轮只落身份列，不进载荷。
    # 禁个人 owner：显式不写 assignee/assignee_id
    if existing_id:
        return db.update_directive_candidate(existing_id, staged)
    return db.stage_directive_candidate(
        int(turn), minister_name, payload=staged,
        source_chat_turn_id=origin_cid,
    )

def stage_revoke_authority_candidate(
    db: Any,
    turn: int,
    minister_name: str,
    *,
    text: str,
    authority_id: object = 0,
    holder_id: object = "",
    privilege: object = "",
    extracted_mode: object = None,
    target_candidate: object = None,
    pend_for_minister: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Shared revoke_authority candidate write (#523 / #611).

    唯一解析到现存 authority_records.id；0/多匹配不暂存。
    收夜只成案卷；收回走 authority_changes，判后物化。
    """
    from ming_sim.cli_backend import resolve_directive_mode

    if str(target_candidate or "").strip() == "含糊":
        return 0
    body = str(text or "").strip()
    if not body:
        return 0
    rec = _resolve_unique_active_authority(
        db, int(turn),
        authority_id=authority_id,
        holder_id=holder_id,
        privilege=privilege,
    )
    if rec is None:
        return 0
    aid = int(rec["id"])
    holder = str(rec.get("holder_id") or "").strip()
    grant_dossier_id = int(rec.get("dossier_id") or 0)

    pending_rows = list(pend_for_minister or [])
    if not pending_rows:
        pending_rows = [
            p for p in db.list_pending_actions(int(turn), minister_name=minister_name)
            if p.get("kind") == "directive" and p.get("status") == "pending"
        ]
    existing_id = 0
    existing_mode = None
    pointed = str(target_candidate or "").strip()
    if pointed.isdigit():
        want_id = int(pointed)
        for row in pending_rows:
            if int(row["id"]) != want_id:
                continue
            try:
                payload = json.loads(str(row.get("payload_json") or "{}"))
            except (TypeError, ValueError):
                break
            if not isinstance(payload, dict):
                break
            if str(payload.get("dossier_action_type") or "").strip() != "revoke_authority":
                break
            existing_id = want_id
            existing_mode = payload.get("mode")
            break

    mode = resolve_directive_mode(extracted=extracted_mode, existing=existing_mode)
    staged: Dict[str, Any] = {
        "text": body,
        "actor": minister_name,
        "dossier_action_type": "revoke_authority",
        "target_kind": "character",
        "target_id": holder,
        "name": holder,
        "holder_id": holder,
        "authority_id": aid,
        "privilege": str(rec.get("privilege") or ""),
        "grant_dossier_id": grant_dossier_id,
        "mode": mode,
    }
    if existing_id:
        return db.update_directive_candidate(existing_id, staged)
    return db.stage_directive_candidate(int(turn), minister_name, payload=staged)

def stage_revoke_decree_candidate(
    db: Any,
    turn: int,
    minister_name: str,
    *,
    text: str,
    target_id: object = "",
    target_kind: object = "",
    extracted_mode: object = None,
    target_candidate: object = None,
    affair_declaration: Optional[Mapping[str, object]] = None,
    pend_for_minister: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Shared revoke_decree candidate write (#523 / ADR 0041).

    有代价的新命令入闸；目标仅承诺/旨意。非 undo、不删旧账。
    ``affair_declaration`` 是既有事务关联接缝（#1894 / ADR 0154）：原旨与撤令
    沿同一事务，缺席即无关联，代码不据正文推断。
    """
    from ming_sim.cli_backend import resolve_directive_mode

    if str(target_candidate or "").strip() == "含糊":
        return 0
    body = str(text or "").strip()
    if not body:
        return 0
    resolved = _parse_revoke_decree_target(
        db,
        target_id=target_id,
        target_kind=target_kind,
        target_candidate=target_candidate,
    )
    if resolved is None:
        return 0

    pending_rows = list(pend_for_minister or [])
    if not pending_rows:
        pending_rows = [
            p for p in db.list_pending_actions(int(turn), minister_name=minister_name)
            if p.get("kind") == "directive" and p.get("status") == "pending"
        ]
    existing_id = 0
    existing_mode = None
    pointed = str(target_candidate or "").strip()
    if pointed.isdigit():
        want_id = int(pointed)
        for row in pending_rows:
            if int(row["id"]) != want_id:
                continue
            try:
                payload = json.loads(str(row.get("payload_json") or "{}"))
            except (TypeError, ValueError):
                break
            if not isinstance(payload, dict):
                break
            if str(payload.get("dossier_action_type") or "").strip() != "revoke_decree":
                break
            existing_id = want_id
            existing_mode = payload.get("mode")
            break

    mode = resolve_directive_mode(extracted=extracted_mode, existing=existing_mode)
    staged: Dict[str, Any] = {
        "text": body,
        "actor": minister_name,
        "dossier_action_type": "revoke_decree",
        "target_kind": resolved["target_kind"],
        "target_id": resolved["target_id"],
        "revoke_target_dossier_id": int(resolved.get("dossier_id") or 0),
        "revoke_target_issue_id": int(resolved.get("issue_id") or 0),
        "mode": mode,
    }
    if affair_declaration:
        staged["affair_declaration"] = dict(affair_declaration)
    if existing_id:
        return db.update_directive_candidate(existing_id, staged)
    return db.stage_directive_candidate(int(turn), minister_name, payload=staged)

def _build_catalog() -> Tuple[ActionCluster, ...]:
    """单一登记定义：label/kind/effect/fields 同表（FieldSpec 枚举真源）。"""
    return (
        ActionCluster("无", "none", EFFECT_NOOP, priority=0),
        ActionCluster(
            "密令动作", "secret", EFFECT_MATERIALIZE, priority=30,
            fields=(
                FieldSpec(
                    "secret_action", "密令动作",
                    frozenset({"无", "新建", "更新", "提交核议", "催办", "记进展"}), "无",
                ),
                FieldSpec("order_id", "目标密令编号", None, 0, as_int=True),
                FieldSpec("new_title", "新标题", None, ""),
                FieldSpec("new_content", "新内容", None, ""),
                FieldSpec("deadline_months", "期限月数", None, 0, as_int=True, int_hi=36),
            ),
        ),
        ActionCluster(
            "拟旨", "draft", EFFECT_MATERIALIZE, priority=50,
            fields=(),
        ),
        ActionCluster(
            "禁绝暗渠摊派", "prohibit_covert_levy", EFFECT_MATERIALIZE, priority=54,
            fields=(),
        ),
        ActionCluster(
            "招抚", "pacification", EFFECT_MATERIALIZE, priority=55,
            fields=(
                # 与 grant_allocation 共享 target_id：须能承载人物/地区/项目/军队
                FieldSpec("target_id", "目标", None, ""),
                FieldSpec(
                    "mode", "颁布方式",
                    frozenset({"ordinary", "midzhi"}), "",
                ),
            ),
        ),
        ActionCluster(
            "交办·责成", "assignment", EFFECT_MATERIALIZE, priority=56,
            fields=(
                FieldSpec("title", "标题", None, ""),
                FieldSpec(
                    "transaction_category", "事务类别",
                    duty_route_categories(), "",
                ),
                # #1778：承办人/名单来后置抽取，不经分类器改派入口（#520 r2 仍成立）
                # 与 grant/pacification 共享 target_id：事项锚（跨轮强化身份）
                FieldSpec("target_id", "目标", None, ""),
                FieldSpec(
                    "commitment_kind", "承诺类型",
                    frozenset({"无", "until_stop"}), "无",
                ),
                FieldSpec("stop_condition", "停止条件", None, ""),
                # 相对月数（共享 secret 的期限月数）由 stage 换算绝对 end_turn
                FieldSpec("end_turn", "截止回合", None, 0, as_int=True),
                FieldSpec("ongoing_effects", "持续效果", None, ""),
                # #620 扩展面：分段里程碑（不改 #520 本体字段语义）
                FieldSpec("stages", "分段里程碑", None, ""),
                FieldSpec(
                    "mode", "颁布方式",
                    frozenset({"ordinary", "midzhi"}), "",
                ),
                # 明确改草指向：分类归一化须保留，供 stage 只更新点名候选
                FieldSpec("target_candidate", "目标候选", None, ""),
            ),
        ),
        ActionCluster(
            "恩赏·拨帑", "grant_allocation", EFFECT_MATERIALIZE, priority=57,
            fields=(
                FieldSpec(
                    "grant_action", "恩赏拨帑",
                    GRANT_ACTIONS, "无", season_option=True,
                ),
                FieldSpec("name", "姓名", None, ""),
                # 政务拨款对象：赈灾地区 / 项目 / 协饷军队 / 恩赏人物
                FieldSpec(
                    "target_id", "目标", None, "",
                    season_option=True,
                ),
                FieldSpec(
                    "target_kind", "目标类型", TARGET_KINDS, "",
                    season_option=True,
                    allowed_when=("grant_action", "协饷", XIEXIANG_TARGET_KINDS),
                ),
                FieldSpec(
                    "amount", "金额", None, None, as_int=True, int_lo=1,
                    quantity_unit="万两", season_option=True,
                ),
                FieldSpec(
                    "account", "账户",
                    frozenset({"国库", "内库", "太仓"}), "", season_option=True,
                ),
                FieldSpec(
                    "purpose", "用途", frozenset({"补饷"}), "",
                    season_option=True,
                    populated_when=("grant_action", frozenset({"协饷"})),
                ),
                FieldSpec(
                    "cadence", "拨付节奏",
                    frozenset({"一次性", "每月"}), "", season_option=True,
                ),
                FieldSpec(
                    "mode", "颁布方式",
                    frozenset({"ordinary", "midzhi"}), "",
                ),
                # #1624：执行面仅 grant 可选；prompt/投影由此单轨派生，禁通用透传。
                FieldSpec(
                    "execution_surface", "执行面",
                    frozenset({"immediate", "in_transit"}), "",
                ),
                # #1783：同一事完成期限挂本候选；日级不足一月→截止回合=当前+1
                FieldSpec("deadline_months", "期限月数", None, 0, as_int=True, int_hi=36),
                FieldSpec("end_turn", "截止回合", None, 0, as_int=True),
                # 明确改草指向：分类归一化须保留，供 stage 只更新点名候选
                FieldSpec("target_candidate", "目标候选", None, ""),
            ),
        ),
        ActionCluster(
            "委任授权", "authorization", EFFECT_MATERIALIZE, priority=56,
            fields=(
                FieldSpec(
                    "privilege", "权项",
                    frozenset({
                        "无", "尚方剑密授", "便宜行事", "专差督办", "新机构专办",
                    }), "无",
                ),
                # 事域：确认闸落典范键 target_kind:target_id（缺 kind 默认 issue）
                FieldSpec("target_id", "目标", None, ""),
                FieldSpec("target_candidate", "目标候选", None, ""),
                FieldSpec(
                    "mode", "颁布方式",
                    frozenset({"ordinary", "midzhi"}), "",
                ),
            ),
        ),
        ActionCluster(
            "惩处", "punishment", EFFECT_MATERIALIZE, priority=58,
            fields=(
                FieldSpec(
                    "punish_action", "惩处动作",
                    frozenset({
                        "无", "拿问下狱", "拿问去职", "赐死", "廷杖", "罚俸",
                        "削籍", "放归", "昭雪", "流放",
                    }), "无",
                    execution_coverage={
                        "拿问下狱": "strike", "拿问去职": "strike",
                        "赐死": None, "廷杖": None, "罚俸": None, "削籍": None,
                        "放归": None, "昭雪": None, "流放": None, "无": None,
                    },
                ),
                FieldSpec("name", "姓名", None, ""),
                # 与 pacification/grant_allocation 共享 target_id 中文键（#518 契约）
                FieldSpec("target_id", "目标", None, ""),
                FieldSpec(
                    "amount", "金额", None, 0, as_int=True,
                    quantity_unit="两",
                ),
                FieldSpec(
                    "transaction_category", "事务类别",
                    duty_route_categories(), "",
                ),
                FieldSpec(
                    "mode", "颁布方式",
                    frozenset({"ordinary", "midzhi"}), "",
                ),
                # #658：处置指向哪次站台；optional positive int（as_int+default None+int_lo=1），禁 generic clamp
                FieldSpec(
                    "backing_dossier_id", "站台案卷", None, None, as_int=True, int_lo=1,
                ),
                FieldSpec("issue_id", "事项标识", None, None, as_int=True, int_lo=1),
                FieldSpec(
                    "issue_disposition", "事项处置",
                    frozenset({"无", "办人", "压下"}), "无",
                ),
            ),
        ),
        ActionCluster(
            "军令·调遣", "military_order", EFFECT_MATERIALIZE, priority=59,
            fields=(
                # 与 grant/pacification 共享 target_id：既有军队稳定 id
                FieldSpec("target_id", "目标", None, ""),
                FieldSpec(
                    "transaction_category", "事务类别",
                    duty_route_categories(), "",
                ),
                # 承办人 / 责任军将（admission 映 assignee_id）
                FieldSpec("name", "姓名", None, ""),
                FieldSpec("station", "驻地", None, ""),
                # #659：结构化实际驻地=regions.id；与 station 双写，不改饷源
                FieldSpec("station_region", "驻地省", None, ""),
                # 与 secret 共享期限月数；限期出战 stage/admission 换算绝对 due_turn
                FieldSpec(
                    "deadline_months", "期限月数", None, 0, as_int=True, int_hi=36,
                ),
                # 可选：军将职守真变才填；判后走人物变更/任免唯一核
                FieldSpec("office", "官职", None, ""),
                # Local/边镇 任所；与 appointment 同键，不从 station 推断
                FieldSpec("region_id", "任所", None, ""),
                # #521 r2 / #502：明确改草指向；同军独立军令不得仅凭 target_id 覆盖
                FieldSpec("target_candidate", "目标候选", None, ""),
                FieldSpec(
                    "mode", "颁布方式",
                    frozenset({"ordinary", "midzhi"}), "",
                ),
            ),
        ),
        ActionCluster(
            "收权·罢差", "revoke_authority", EFFECT_MATERIALIZE, priority=61,
            fields=(
                FieldSpec("name", "姓名", None, ""),
                FieldSpec(
                    "authority_id", "授权编号", None, 0, as_int=True,
                ),
                FieldSpec(
                    "privilege", "权项",
                    frozenset({
                        "无", "尚方剑密授", "便宜行事", "专差督办", "新机构专办",
                    }), "无",
                ),
                FieldSpec("target_candidate", "目标候选", None, ""),
                FieldSpec(
                    "mode", "颁布方式",
                    frozenset({"ordinary", "midzhi"}), "",
                ),
            ),
        ),
        ActionCluster(
            "撤回成命", "revoke_decree", EFFECT_MATERIALIZE, priority=62,
            fields=(
                # 目标成命：承诺/旨意 id（dossier:<id> / issue:<id> / 裸数字）
                FieldSpec("target_id", "目标", None, ""),
                FieldSpec("name", "姓名", None, ""),
                # #502：指称含糊三态
                FieldSpec("target_candidate", "目标候选", None, ""),
                FieldSpec(
                    "mode", "颁布方式",
                    frozenset({"ordinary", "midzhi"}), "",
                ),
            ),
        ),
        ActionCluster(
            "下议", "referral", EFFECT_MATERIALIZE, priority=63,
            fields=(
                FieldSpec("title", "标题", None, ""),
                # 事项锚；与 grant/assignment 共享 target_id
                FieldSpec("target_id", "目标", None, ""),
                # 议期月数 1–36；stage 换算绝对 end_turn=turn+N
                FieldSpec(
                    "deadline_months", "期限月数", None, 0, as_int=True, int_hi=36,
                ),
                # 机关/职司名 JSON 列表（如 ["吏部","廷推会"]）；禁个人名
                FieldSpec(
                    "responsible_bodies", "责任机关", None, "",
                ),
                FieldSpec(
                    "mode", "颁布方式",
                    frozenset({"ordinary", "midzhi"}), "",
                ),
                FieldSpec("target_candidate", "目标候选", None, ""),
            ),
        ),
        ActionCluster(
            "任免", "appointment", EFFECT_MATERIALIZE, priority=60,
            fields=(
                FieldSpec(
                    "appoint_action", "任免动作",
                    frozenset({"无", "任命", "罢免"}), "无",
                ),
                FieldSpec("name", "姓名", None, ""),
                FieldSpec("office", "官职", None, ""),
                # Local/督抚/边镇 seat jurisdiction (typed region_id); not 行止.
                FieldSpec("region_id", "任所", None, ""),
                FieldSpec(
                    "summon_after", "任命后传召",
                    frozenset({"是", "否"}), "否",
                ),
                FieldSpec(
                    "mode", "颁布方式",
                    frozenset({"ordinary", "midzhi"}), "",
                ),
                # #529 / 0064：任别轴；路径应答署理只写此字段
                FieldSpec(
                    "appointment_tenure", "任别",
                    frozenset({"真除", "署理", "兼署", "加衔"}), "",
                ),
                FieldSpec("target_candidate", "目标候选", None, ""),
            ),
        ),
    )


install_action_catalog(_build_catalog())
