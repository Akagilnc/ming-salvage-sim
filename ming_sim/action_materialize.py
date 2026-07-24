"""登记表驱动的动作物化委派（#515）。

唯一扩展挂点：本模块 `install_action_catalog` 装入的 ACTION_CLUSTERS 行
直接携带 materialize_fn + FieldSpec。真实 consumer 只调
`run_materialize_pipeline`。串行 fallback 与并发判词共用 handler。

新增聚类 = 在 `_build_catalog()` 加一行（含 fn），不改编排散点、无副作用 register。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from ming_sim.action_clusters import (
    ActionCluster,
    FieldSpec,
    EFFECT_ANSWER_EXISTING,
    EFFECT_MATERIALIZE,
    EFFECT_NOOP,
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
    conversation_intent_handled: bool = False
    draft_staged: bool = False


def run_materialize_pipeline(ctx: MaterializeCtx) -> None:
    """按登记 priority 依次调用已注册 materializer。

    各 handler 内部保留既有互斥/结构化判词/串行抽取语义；编排层不再出现
    secret/cultivate/draft/appointment 字面量分叉。
    同一 callable 只跑一次（secret/cultivate 共享 extract 缝）。
    """
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
    from ming_sim.cli_backend import extract_minister_actions

    if ctx.out.get("pending_action_id") or ctx.out.get("secret_order_id") or ctx.explicit_prefixed:
        return
    session = ctx.session
    minister_name = ctx.character.name
    is_consort = getattr(ctx.character, "office_type", "") == "后宫"
    active = session.db.get_active_secret_orders_for_minister(minister_name)
    if not (active or is_consort):
        return

    intent = ctx.intent
    intent_kind = ctx.intent_kind
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
    from ming_sim.cli_backend import extract_draft_intent

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
        dir_candidates.append({"id": int(_p["id"]), "text": _txt, "summary": _txt[:40]})
    existing_draft_text = ""
    if dir_candidates:
        existing_draft_text = str(dir_candidates[-1].get("text") or "")
    elif committed_draft is not None and not has_pending_directive:
        existing_draft_text = str(committed_draft["text"] or "")

    if intent is not None and intent_kind == "draft" and not has_existing_draft:
        draft_res = {"draft_action": "拟旨", "draft_text": ctx.reply, "target_candidate": ""}
    else:
        draft_res = extract_draft_intent(
            ctx.player_message, ctx.reply, llm_config=ctx.llm_config,
            has_pending_draft=has_existing_draft,
            existing_draft_text=existing_draft_text,
            existing_candidates=dir_candidates or None,
        )

    if draft_res["draft_action"] == "拟旨" and str(draft_res.get("target_candidate") or "") == "含糊":
        ctx.out["directive_confirmation_ambiguous"] = {
            "candidates": [{"id": c["id"], "summary": c["summary"]} for c in dir_candidates]
        }
        ctx.draft_staged = True
        return
    if draft_res["draft_action"] == "拟旨" and draft_res["draft_text"]:
        _target = str(draft_res.get("target_candidate") or "")
        _target_id = int(_target) if _target.isdigit() else None
        if dir_candidates and _target == "新":
            ctx.out["pending_action_id"] = session.db.stage_directive_candidate(
                session.state.turn, minister_name,
                payload={"text": draft_res["draft_text"], "actor": minister_name},
            )
        elif _target_id is not None and any(c["id"] == _target_id for c in dir_candidates):
            ctx.out["pending_action_id"] = session.db.update_directive_candidate(
                _target_id,
                payload={"text": draft_res["draft_text"], "actor": minister_name},
            )
        elif committed_draft is not None and not has_pending_directive:
            did = int(committed_draft["id"])
            session.db.update_directive_text(did, draft_res["draft_text"])
            ctx.out["directive"] = {
                "id": did,
                "text": draft_res["draft_text"],
                "status": "draft",
                "notes": f"由{minister_name}拟旨入档",
            }
        else:
            pid = session.db.upsert_pending_directive(
                session.state.turn, minister_name,
                payload={"text": draft_res["draft_text"], "actor": minister_name},
            )
            ctx.out["pending_action_id"] = pid
        ctx.draft_staged = True


def _materialize_appointment(ctx: MaterializeCtx) -> None:
    from ming_sim.cli_backend import extract_appointment_action
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
                    frozenset({"无", "更新", "提交核议", "催办", "记进展"}), "无",
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
            "任免", "appointment", EFFECT_MATERIALIZE, priority=60,
            fields=(
                FieldSpec(
                    "appoint_action", "任免动作",
                    frozenset({"无", "任命", "罢免"}), "无",
                ),
                FieldSpec("name", "姓名", None, "", max_len=20),
                FieldSpec("office", "官职", None, "", max_len=40),
            ),
            materialize_fn=_materialize_appointment,
        ),
    )


install_action_catalog(_build_catalog())
