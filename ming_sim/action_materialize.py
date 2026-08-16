"""登记表驱动的动作物化委派（#515）。

唯一扩展挂点：本模块 `install_action_catalog` 装入的 ACTION_CLUSTERS 行
直接携带 materialize_fn + FieldSpec。真实 consumer 只调
`run_materialize_pipeline`。串行 fallback 与并发判词共用 handler。

新增聚类 = 在 `_build_catalog()` 加一行（含 fn），不改编排散点、无副作用 register。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Tuple

from ming_sim.action_clusters import (
    ActionCluster,
    FieldSpec,
    EFFECT_ANSWER_EXISTING,
    EFFECT_MATERIALIZE,
    EFFECT_NOOP,
    cluster_by_kind,
    install_action_catalog,
    materialize_clusters_ordered,
)


@dataclass
class MaterializeCtx:
    """物化上下文——真实 session/db 引用，handler 不另开落库路径。"""

    session: Any
    character: Any
    player_message: str
    reply: str
    message_text: str
    explicit_prefixed: bool
    has_directive: bool
    pend_for_minister: List[Dict[str, Any]]
    out: Dict[str, Any]
    intent: Optional[Dict[str, Any]]
    intent_kind: str
    llm_config: Any
    intent_candidates: Optional[List[Dict[str, Any]]] = None
    candidate_kind_index: int = 0
    candidate_kind_count: int = 1
    batch_state: Dict[str, Any] = field(default_factory=dict)
    conversation_intent_handled: bool = False
    draft_staged: bool = False


def run_materialize_pipeline(ctx: MaterializeCtx) -> None:
    """按登记 priority 依次调用已注册 materializer。

    各 handler 内部保留既有互斥/结构化判词/串行抽取语义；编排层不再出现
    secret/cultivate/draft/appointment 字面量分叉。
    同一 callable 只跑一次（secret/cultivate 共享 extract 缝）。
    """
    if ctx.intent_candidates:
        # classifier 的列表契约逐项消费；confirmation 仍在 session 上游按 primary
        # 裁决并提前返回。每项复用登记行自带的同一 handler，不复制 kind 分支。
        baseline_out = dict(ctx.out)
        kind_counts: Dict[str, int] = {}
        for candidate in ctx.intent_candidates:
            kind = str(candidate.get("kind") or "")
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
        kind_indexes: Dict[str, int] = {}
        for candidate in ctx.intent_candidates:
            kind = str(candidate.get("kind") or "")
            cluster = cluster_by_kind(kind)
            if cluster is None or cluster.effect != EFFECT_MATERIALIZE:
                continue
            fn = cluster.materialize_fn
            if fn is None:
                continue
            kind_index = kind_indexes.get(kind, 0)
            kind_indexes[kind] = kind_index + 1
            candidate_out = dict(baseline_out)
            candidate_ctx = replace(
                ctx,
                out=candidate_out,
                intent=candidate,
                intent_kind=cluster.kind,
                intent_candidates=None,
                candidate_kind_index=kind_index,
                candidate_kind_count=kind_counts[kind],
                conversation_intent_handled=False,
                draft_staged=False,
            )
            fn(candidate_ctx)
            ctx.out.update(candidate_out)
        return

    seen: set = set()
    for cluster in materialize_clusters_ordered():
        fn = cluster.materialize_fn
        if fn is None or fn in seen:
            continue
        seen.add(fn)
        fn(ctx)


# ── handlers（委派既有 stage，不另造落库）────────────────────────────


def _materialize_secret_and_cultivate(ctx: MaterializeCtx) -> None:
    """密令会话动作 + 调教：并发判词与串行 extract_minister_actions 同缝。"""
    from ming_sim.cli_backend import _extract_secret_order, extract_minister_actions

    if ctx.out.get("pending_action_id") or ctx.out.get("secret_order_id") or ctx.explicit_prefixed:
        return
    session = ctx.session
    minister_name = ctx.character.name
    intent = ctx.intent
    intent_kind = ctx.intent_kind
    if (
        intent is not None
        and intent_kind == "secret"
        and intent.get("secret_action") == "新建"
    ):
        secret = _extract_secret_order(
            ctx.player_message,
            ctx.reply,
            minister_name,
            ctx.llm_config,
            force_default_assignee=False,
            dossier_candidates=session.db.list_referenceable_dossiers(
                minister_name, session.state.turn),
        )
        ctx.conversation_intent_handled = True
        ctx.out["pending_action_id"] = session.db.stage_pending_action(
            session.state.turn,
            kind="secret_order",
            action="新建",
            minister_name=minister_name,
            target_id=None,
            payload={
                "title": secret["title"],
                "content": secret["content"],
                "assignee": secret.get("assignee") or minister_name,
                "tags": secret.get("tags") or [],
                "deadline_months": secret.get("deadline_months", 0),
                "excluded_names": secret.get("excluded_names") or [],
                "excluded_offices": secret.get("excluded_offices") or [],
                "dossier_links": secret.get("dossier_links") or [],
            },
        )
        return

    is_consort = getattr(ctx.character, "office_type", "") == "后宫"
    active = session.db.get_active_secret_orders_for_minister(minister_name)
    if not (active or is_consort):
        return

    # 仅当分类器未跑，或判为 secret/cultivate 时走抽取/物化；
    # 其它 kind 的并发判词不得串行重抽密令。
    if intent is not None and intent_kind not in ("secret", "cultivate", "none"):
        return
    if intent is not None and intent_kind in ("secret", "cultivate"):
        extracted = extract_minister_actions(
            ctx.player_message, ctx.reply, active, is_consort, llm_config=ctx.llm_config)
        act = extracted if (
            extracted.get("secret_action") != "无"
            or extracted.get("cultivate_skill")
            or extracted.get("cultivate_trait")
        ) else intent
    elif intent is not None and intent_kind == "none":
        act = {
            "secret_action": "无", "order_id": 0, "new_title": "", "new_content": "",
            "deadline_months": 0, "cultivate_skill": "", "cultivate_trait": "",
        }
    else:
        act = extract_minister_actions(
            ctx.player_message, ctx.reply, active, is_consort, llm_config=ctx.llm_config)

    sa = act["secret_action"]
    if sa and sa != "无":
        ctx.conversation_intent_handled = True
    target = None
    if act["order_id"]:
        target = next((o for o in active if int(o["id"]) == act["order_id"]), None)
    if target is None and len(active) == 1:
        target = active[0]
    if target is not None and sa and sa != "无":
        oid = int(target["id"])
        target_active = str(target.get("status") or "active") == "active"
        if target_active and sa == "更新":
            ctx.out["pending_action_id"] = session.db.stage_pending_action(
                session.state.turn, kind="secret_order", action="更新",
                minister_name=minister_name, target_id=oid,
                payload=session.db.attach_secret_oral_pin(
                    minister_name, int(session.state.turn), {
                        "new_title": act["new_title"] or str(target.get("title") or ""),
                        "new_content": act["new_content"] or str(target.get("content") or ""),
                        "deadline_months": act["deadline_months"],
                    },
                ),
            )
        elif target_active and sa == "催办":
            rush_deadline = int(act.get("deadline_months") or 0)
            if rush_deadline <= 0 and not any(
                token in ctx.message_text
                for token in ("即刻", "立即", "立刻", "马上", "本月", "当月", "即日")
            ):
                rush_deadline = 1
            ctx.out["pending_action_id"] = session.db.stage_pending_action(
                session.state.turn, kind="secret_order", action="催办",
                minister_name=minister_name, target_id=oid,
                payload={
                    "deadline_months": rush_deadline,
                    "reason": ctx.player_message[:80],
                },
            )
        elif target_active and sa == "提交核议":
            ctx.out["pending_action_id"] = session.db.stage_pending_action(
                session.state.turn, kind="secret_order", action="提交核议",
                minister_name=minister_name, target_id=oid,
                payload={"claim": ctx.reply.strip()},
            )
        elif target_active and sa == "记进展" and int(target.get("turn_issued") or 0) != int(session.state.turn):
            ctx.out["pending_action_id"] = session.db.stage_pending_action(
                session.state.turn, kind="secret_order", action="记进展",
                minister_name=minister_name, target_id=oid,
                payload={"note": ctx.reply.strip()},
            )
    if is_consort and (act["cultivate_skill"] or act["cultivate_trait"]):
        ctx.conversation_intent_handled = True
        ctx.out["pending_action_id"] = session.db.stage_pending_action(
            session.state.turn, kind="consort", action="调教",
            minister_name=ctx.character.name, target_id=None,
            payload={
                "name": ctx.character.name,
                "skill": act["cultivate_skill"],
                "trait": act["cultivate_trait"],
            },
        )


def _materialize_draft(ctx: MaterializeCtx) -> None:
    from ming_sim.cli_backend import extract_draft_intent, resolve_directive_mode

    session = ctx.session
    minister_name = ctx.character.name
    intent = ctx.intent
    intent_kind = ctx.intent_kind
    pend_for_minister = ctx.pend_for_minister

    # 一次扫描 pending + 最近 committed draft（入口条件与后续物化共用）
    has_pending_directive = any(p["kind"] == "directive" for p in pend_for_minister)
    committed_draft = None
    if not has_pending_directive:
        for _directive in reversed(session.db.list_directives(session.state, statuses=("draft",))):
            if session.db.get_dossier_for_directive(int(_directive["id"])) is not None:
                continue
            if str(_directive["actor"] or "") == minister_name:
                committed_draft = _directive
                break
    has_committed_directive = committed_draft is not None
    has_existing_draft = has_pending_directive or has_committed_directive
    if not (
        (intent is not None and intent_kind == "draft")
        or has_pending_directive
        or has_committed_directive
    ):
        return

    if ctx.explicit_prefixed or ctx.has_directive or ctx.out.get("pending_action_id"):
        return

    dir_candidates = []
    for _p in pend_for_minister:
        if _p["kind"] != "directive":
            continue
        _val = _p["payload_json"] or "{}"
        try:
            _cp = _val if isinstance(_val, (list, dict)) else json.loads(_val)
        except (ValueError, TypeError):
            _cp = {}
        _txt = str(_cp.get("text") or "") if isinstance(_cp, dict) else ""
        _mode = _cp.get("mode") if isinstance(_cp, dict) else None
        dir_candidates.append({
            "id": int(_p["id"]), "text": _txt, "summary": _txt[:40], "mode": _mode,
        })
    existing_draft_text = ""
    if dir_candidates:
        existing_draft_text = str(dir_candidates[-1].get("text") or "")
    elif committed_draft is not None and not has_pending_directive:
        existing_draft_text = str(committed_draft["text"] or "")

    if (
        intent is not None
        and intent_kind == "draft"
        and ctx.candidate_kind_count > 1
    ):
        if "drafts" not in ctx.batch_state:
            batch_res = extract_draft_intent(
                ctx.player_message,
                ctx.reply,
                llm_config=ctx.llm_config,
                draft_count=ctx.candidate_kind_count,
            )
            ctx.batch_state["drafts"] = list(batch_res.get("drafts") or [])
        drafts = ctx.batch_state["drafts"]
        if ctx.candidate_kind_index >= len(drafts):
            return
        batch_draft = drafts[ctx.candidate_kind_index]
        if not isinstance(batch_draft, dict):
            return
        draft_res = dict(batch_draft)
    else:
        draft_res = extract_draft_intent(
            ctx.player_message, ctx.reply, llm_config=ctx.llm_config,
            has_pending_draft=has_existing_draft,
            existing_draft_text=existing_draft_text,
            existing_candidates=dir_candidates or None,
        )
        if intent is not None and intent_kind == "draft" and not has_existing_draft:
            # #515 的并行 classifier 已经确定“拟旨”，大臣回话仍是正文真源；
            # #571 的串行抽取只补案卷结构字段，失败不得吞掉已判定的动作。
            draft_res = {
                **draft_res,
                "draft_action": "拟旨",
                "draft_text": ctx.reply,
                "target_candidate": "",
            }

    if draft_res["draft_action"] == "拟旨" and str(draft_res.get("target_candidate") or "") == "含糊":
        ctx.out["directive_confirmation_ambiguous"] = {
            "candidates": [{"id": c["id"], "summary": c["summary"]} for c in dir_candidates]
        }
        ctx.draft_staged = True
        return
    if draft_res["draft_action"] == "拟旨" and draft_res["draft_text"]:
        semantic_payload = {
            "text": draft_res["draft_text"],
            "actor": minister_name,
        }
        roster = draft_res.get("participant_roster")
        if "participant_roster" in draft_res:
            if not isinstance(roster, list):
                raise ValueError("参与人须为对象列表")
            from ming_sim.session import _canonical_minister_key

            roster = session.db._normalize_participant_roster(
                roster, strict_structured=True,
            )
            roster = [
                {
                    **item,
                    "character_id": _canonical_minister_key(
                        session.content, item.get("character_id"), session.db,
                    ),
                    **({
                        "delegator_id": _canonical_minister_key(
                            session.content, item.get("delegator_id"), session.db,
                        ),
                    } if item.get("delegator_id") else {}),
                }
                for item in roster
            ]
            draft_res["participant_roster"] = roster
        _target = str(draft_res.get("target_candidate") or "")
        _target_id = int(_target) if _target.isdigit() else None
        pending_target = next(
            (c for c in dir_candidates if c["id"] == _target_id), None,
        ) if _target_id is not None else None
        # 单候选且抽取器未回目标时，下面的真实落点仍是 upsert 该候选，不是新建。
        if pending_target is None and len(dir_candidates) == 1 and _target != "新":
            pending_target = dir_candidates[0]
        is_existing_update = (
            pending_target is not None
            or (committed_draft is not None and not has_pending_directive)
        )
        existing_mode = None
        if is_existing_update:
            if pending_target is not None:
                existing_mode = pending_target.get("mode")
            elif committed_draft is not None:
                existing_mode = session.db.read_directive_dossier_payload(
                    committed_draft
                ).get("mode")
        # Batch extractor already requires+normalizes per-item mode. Do not
        # rebroadcast the whole utterance (often the first item's declaration)
        # over every sibling; keep single-item/supplement path on emperor text.
        if ctx.candidate_kind_count > 1:
            draft_res["mode"] = resolve_directive_mode(
                extracted=draft_res.get("mode"),
            )
        else:
            draft_res["mode"] = resolve_directive_mode(
                ctx.player_message, draft_res.get("mode"), existing_mode,
            )

        mechanical_fields = (
            "dossier_action_type", "target_kind", "target_id", "mode", "amount", "account",
            "execution_surface", "assignee", "deadline_months",
        )
        for field_name in mechanical_fields:
            if draft_res.get(field_name) not in (None, ""):
                semantic_payload[field_name] = draft_res[field_name]
        if isinstance(draft_res.get("participant_roster"), list):
            semantic_payload["participant_roster"] = draft_res["participant_roster"]
        if not is_existing_update:
            semantic_payload.setdefault("dossier_action_type", "special_decree")
            semantic_payload.setdefault("target_kind", "policy")
            semantic_payload.setdefault("target_id", ctx.player_message.strip())
        if ctx.candidate_kind_count > 1:
            ctx.out["pending_action_id"] = session.db.stage_directive_candidate(
                session.state.turn, minister_name,
                payload=semantic_payload,
            )
        elif dir_candidates and _target == "新":
            ctx.out["pending_action_id"] = session.db.stage_directive_candidate(
                session.state.turn, minister_name,
                payload=semantic_payload,
            )
        elif _target_id is not None and any(c["id"] == _target_id for c in dir_candidates):
            ctx.out["pending_action_id"] = session.db.update_directive_candidate(
                _target_id,
                payload=semantic_payload,
            )
        elif committed_draft is not None and not has_pending_directive:
            did = int(committed_draft["id"])
            session.db.update_directive_text(
                did, draft_res["draft_text"], dossier_payload=semantic_payload,
            )
            ctx.out["directive"] = {
                "id": did,
                "text": draft_res["draft_text"],
                "status": "draft",
                "notes": f"由{minister_name}拟旨入档",
            }
        else:
            pid = session.db.upsert_pending_directive(
                session.state.turn, minister_name,
                payload=semantic_payload,
            )
            ctx.out["pending_action_id"] = pid
        ctx.draft_staged = True


def stage_pacification_candidate(
    db: Any,
    turn: int,
    minister_name: str,
    *,
    text: str,
    target_id: str,
    emperor_text: object = None,
    extracted_mode: object = None,
    pend_for_minister: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Shared pacification candidate write: mode + same-target update.

    Used by classifier materialize and API/CLI tool propose_directive so both
    channels share admission payload shape (commit still runs _find_pacification_target).
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

    mode = resolve_directive_mode(emperor_text, extracted_mode, existing_mode)
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
    return db.stage_directive_candidate(int(turn), minister_name, payload=staged)


def _materialize_pacification(ctx: MaterializeCtx) -> None:
    """暂存招抚案卷；确认与判后人物易主仍走既有案卷链。"""
    if (
        ctx.intent_kind != "pacification"
        or ctx.explicit_prefixed
        or ctx.draft_staged
        or ctx.out.get("pending_action_id")
        or ctx.conversation_intent_handled
    ):
        return
    intent = ctx.intent or {}
    target_id = intent.get("target_id")
    if not isinstance(target_id, str) or not target_id.strip():
        return
    minister_name = ctx.character.name
    pending_id = stage_pacification_candidate(
        ctx.session.db,
        ctx.session.state.turn,
        minister_name,
        text=ctx.reply,
        target_id=target_id.strip(),
        emperor_text=ctx.player_message,
        extracted_mode=intent.get("mode"),
        pend_for_minister=ctx.pend_for_minister,
    )
    if pending_id:
        ctx.out["pending_action_id"] = pending_id


GRANT_ACTIONS = frozenset({
    "无", "赏赉", "发内帑", "加衔", "荫叙", "赈灾", "项目经费", "协饷",
})
GRANT_HONORIFICS = frozenset({"加衔", "荫叙"})
GRANT_MONEY_ACTIONS = GRANT_ACTIONS - {"无"} - GRANT_HONORIFICS


def _grant_account(intent: Dict[str, Any]) -> str:
    action = str(intent.get("grant_action") or "").strip()
    account = str(intent.get("account") or "").strip()
    if action == "发内帑":
        return "内库"
    if account in {"国库", "内库"}:
        return account
    if action in GRANT_MONEY_ACTIONS:
        return "国库"
    return ""


def _grant_cadence(intent: Dict[str, Any]) -> str:
    cadence = str(intent.get("cadence") or "").strip()
    if cadence in {"一次性", "每月"}:
        return cadence
    if str(intent.get("grant_action") or "").strip() in GRANT_MONEY_ACTIONS:
        return "一次性"
    return ""


def _grant_target(intent: Dict[str, Any]) -> Tuple[str, str]:
    action = str(intent.get("grant_action") or "").strip()
    name = str(intent.get("name") or "").strip()
    target_id = str(intent.get("target_id") or "").strip()
    if action in {"赏赉", "发内帑", "加衔", "荫叙"}:
        return "character", name or target_id
    if action == "项目经费":
        return "issue", target_id or name or action
    if action == "协饷":
        return "army", target_id or name or action
    if action == "赈灾":
        kind = "region" if target_id and target_id != action else "issue"
        return kind, target_id or name or action
    return "issue", target_id or name or action


def stage_grant_allocation_candidate(
    db: Any,
    turn: int,
    minister_name: str,
    *,
    text: str,
    grant_action: str,
    target_kind: str,
    target_id: str,
    emperor_text: object = None,
    extracted_mode: object = None,
    amount: object = 0,
    account: str = "",
    cadence: str = "",
    target_candidate: object = None,
    pend_for_minister: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Shared grant candidate write: mode + explicit-target update only.

    Same grant_action+target_id alone must not overwrite. Independent 另拨/再赏
    each stage a new candidate (#502 / #518); only a structured target_candidate
    id updates the named pending grant.
    """
    from ming_sim.cli_backend import resolve_directive_mode

    action = str(grant_action or "").strip()
    target = str(target_id or "").strip()
    kind = str(target_kind or "").strip()
    if not target or not kind or action not in (GRANT_ACTIONS - {"无"}):
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

    mode = resolve_directive_mode(emperor_text, extracted_mode, existing_mode)
    staged = {
        "text": body,
        "actor": minister_name,
        "dossier_action_type": "grant_allocation",
        "target_kind": kind,
        "target_id": target,
        "grant_action": action,
        "mode": mode,
    }
    if account in {"国库", "内库"}:
        staged["account"] = account
    if cadence in {"一次性", "每月"}:
        staged["cadence"] = cadence
    try:
        n = int(amount or 0)
    except (TypeError, ValueError):
        n = 0
    if n > 0:
        staged["amount"] = n
    if existing_id:
        return db.update_directive_candidate(existing_id, staged)
    return db.stage_directive_candidate(int(turn), minister_name, payload=staged)


def _materialize_grant_allocation(ctx: MaterializeCtx) -> None:
    """暂存恩赏·拨帑案卷；钱粮按 ADR 0055 分流落地。"""
    if (
        ctx.intent_kind != "grant_allocation"
        or ctx.explicit_prefixed
        or ctx.draft_staged
        or ctx.out.get("pending_action_id")
        or ctx.conversation_intent_handled
    ):
        return
    intent = ctx.intent or {}
    grant_action = str(intent.get("grant_action") or "").strip()
    if grant_action not in (GRANT_ACTIONS - {"无"}):
        return
    target_kind, target_id = _grant_target(intent)
    if not target_id:
        return
    pending_id = stage_grant_allocation_candidate(
        ctx.session.db,
        ctx.session.state.turn,
        ctx.character.name,
        text=ctx.reply,
        grant_action=grant_action,
        target_kind=target_kind,
        target_id=target_id,
        emperor_text=ctx.player_message,
        extracted_mode=intent.get("mode"),
        amount=intent.get("amount"),
        account=_grant_account(intent),
        cadence=_grant_cadence(intent),
        target_candidate=intent.get("target_candidate"),
        pend_for_minister=ctx.pend_for_minister,
    )
    if pending_id:
        ctx.out["pending_action_id"] = pending_id


def _materialize_appointment(ctx: MaterializeCtx) -> None:
    from ming_sim.cli_backend import extract_appointment_action, resolve_directive_mode
    from ming_sim.session import (
        _appointment_intent_is_current_office_noop,
        _cancel_staged_opposing_office,
        _target_active_officeholder,
    )

    if (
        ctx.explicit_prefixed or ctx.draft_staged
        or ctx.out.get("pending_action_id") or ctx.conversation_intent_handled
    ):
        return

    session = ctx.session
    minister_name = ctx.character.name
    intent = ctx.intent
    intent_kind = ctx.intent_kind

    if intent is not None:
        appt = intent if intent_kind == "appointment" else {"appoint_action": "无", "name": "", "office": ""}
    else:
        appt = extract_appointment_action(
            ctx.player_message, ctx.reply, llm_config=ctx.llm_config)

    content_ref = getattr(session, "content", None)
    appt_name = appt.get("name", "")
    if appt.get("appoint_action") == "任命" and appt_name:
        hedged = _cancel_staged_opposing_office(
            session.db, "罢免", appt_name, int(session.state.turn), content=content_ref)
        if hedged or _appointment_intent_is_current_office_noop(
                session.db, appt_name, appt.get("office", ""), content=content_ref):
            appt = {"appoint_action": "无", "name": "", "office": ""}
    elif appt.get("appoint_action") == "罢免" and appt_name:
        cancelled = _cancel_staged_opposing_office(
            session.db, "任命", appt_name, int(session.state.turn), content=content_ref)
        if cancelled and not _target_active_officeholder(
                session.db, appt_name, content=content_ref):
            appt = {"appoint_action": "无", "name": "", "office": ""}
    if appt.get("appoint_action") in ("任命", "罢免") and appt.get("name"):
        ctx.out["pending_action_id"] = session.db.stage_pending_action(
            session.state.turn, kind="office", action=appt["appoint_action"],
            minister_name=minister_name, target_id=None,
            payload={
                "name": appt["name"], "office": appt.get("office", ""),
                "appointer": minister_name,
                "mode": resolve_directive_mode(ctx.player_message, appt.get("mode")),
            },
        )


def _build_catalog() -> Tuple[ActionCluster, ...]:
    """单一登记定义：label/kind/effect/fields/materialize_fn 同表。"""
    secret_fn = _materialize_secret_and_cultivate
    return (
        ActionCluster("无", "none", EFFECT_NOOP, priority=0),
        ActionCluster(
            "确认", "confirmation", EFFECT_ANSWER_EXISTING, priority=10,
            fields=(
                FieldSpec(
                    "confirmation", "确认",
                    frozenset({"应允", "拒绝", "无"}), "无",
                ),
            ),
        ),
        ActionCluster(
            "密令动作", "secret", EFFECT_MATERIALIZE, priority=30,
            fields=(
                FieldSpec(
                    "secret_action", "密令动作",
                    frozenset({"无", "新建", "更新", "提交核议", "催办", "记进展"}), "无",
                ),
                FieldSpec("order_id", "目标密令编号", None, 0, as_int=True),
                FieldSpec("new_title", "新标题", None, ""),
                FieldSpec("new_content", "新内容", None, "", max_len=500),
                FieldSpec("deadline_months", "期限月数", None, 0, as_int=True, int_hi=36),
            ),
            materialize_fn=secret_fn,
        ),
        ActionCluster(
            "调教", "cultivate", EFFECT_MATERIALIZE, priority=40,
            fields=(
                FieldSpec("cultivate_skill", "调教技能", None, "", max_len=30),
                FieldSpec("cultivate_trait", "调教性格", None, "", max_len=30),
            ),
            materialize_fn=secret_fn,  # 同 extract 缝，一 fn 两 kind
        ),
        ActionCluster(
            "拟旨", "draft", EFFECT_MATERIALIZE, priority=50,
            fields=(),
            materialize_fn=_materialize_draft,
        ),
        ActionCluster(
            "招抚", "pacification", EFFECT_MATERIALIZE, priority=55,
            fields=(
                FieldSpec("target_id", "目标人物", None, "", max_len=80),
                FieldSpec(
                    "mode", "颁布方式",
                    frozenset({"ordinary", "midzhi"}), "",
                ),
            ),
            materialize_fn=_materialize_pacification,
        ),
        ActionCluster(
            "恩赏·拨帑", "grant_allocation", EFFECT_MATERIALIZE, priority=57,
            fields=(
                FieldSpec(
                    "grant_action", "恩赏拨帑",
                    GRANT_ACTIONS, "无",
                ),
                FieldSpec("name", "姓名", None, "", max_len=20),
                FieldSpec("target_id", "目标人物", None, "", max_len=80),
                FieldSpec("amount", "金额", None, 0, as_int=True),
                FieldSpec(
                    "account", "账户",
                    frozenset({"国库", "内库"}), "",
                ),
                FieldSpec(
                    "cadence", "拨付节奏",
                    frozenset({"一次性", "每月"}), "",
                ),
                FieldSpec(
                    "mode", "颁布方式",
                    frozenset({"ordinary", "midzhi"}), "",
                ),
            ),
            materialize_fn=_materialize_grant_allocation,
        ),
        ActionCluster(
            "任免", "appointment", EFFECT_MATERIALIZE, priority=60,
            fields=(
                FieldSpec(
                    "appoint_action", "任免动作",
                    frozenset({"无", "任命", "罢免"}), "无",
                ),
                FieldSpec("name", "姓名", None, "", max_len=20),
                FieldSpec("office", "官职", None, "", max_len=40),
                FieldSpec(
                    "mode", "颁布方式",
                    frozenset({"ordinary", "midzhi"}), "",
                ),
            ),
            materialize_fn=_materialize_appointment,
        ),
    )


install_action_catalog(_build_catalog())
