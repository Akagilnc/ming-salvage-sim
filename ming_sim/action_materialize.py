"""登记表驱动的动作物化委派（#515）。

唯一扩展挂点：本模块 `install_action_catalog` 装入的 ACTION_CLUSTERS 行
直接携带 materialize_fn + FieldSpec。真实 consumer 只调
`run_materialize_pipeline`。串行 fallback 与并发判词共用 handler。

新增聚类 = 在 `_build_catalog()` 加一行（含 fn），不改编排散点、无副作用 register。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

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
    # #519：一句多旨整表消费（N>1 已注册候选）时为 True；handler 不得 upsert 压扁兄弟项
    multi_intent_batch: bool = False
    batch_state: Dict[str, Any] = field(default_factory=dict)
    conversation_intent_handled: bool = False
    draft_staged: bool = False
    # ADR 0028 / #520：最近相关召对上下文（与分类器同源喂料，案卷 text 取链）
    recent_context: str = ""


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
        multi_batch = len(ctx.intent_candidates) > 1
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
                multi_intent_batch=multi_batch,
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
        # 多旨批无 pending_target 时不得把 committed draft 当成改写目标（P1）。
        is_existing_update = (
            pending_target is not None
            or (
                committed_draft is not None
                and not has_pending_directive
                and not ctx.multi_intent_batch
            )
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
            "execution_surface", "assignee", "deadline_months", "punish_action",
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
        elif pending_target is not None:
            # 显式 id 或 #502 单 pending 推断：仍更新该条（P2）；sibling 由各自 handler 独立落。
            ctx.out["pending_action_id"] = session.db.update_directive_candidate(
                int(pending_target["id"]),
                payload=semantic_payload,
            )
        elif ctx.multi_intent_batch:
            # #519：一句多旨——无 pending_target 时独立 stage，不得改写 committed（P1）。
            ctx.out["pending_action_id"] = session.db.stage_directive_candidate(
                session.state.turn, minister_name,
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


def stage_punishment_candidate(
    db: Any,
    turn: int,
    minister_name: str,
    *,
    text: str,
    target_id: str,
    punish_action: str,
    emperor_text: object = None,
    extracted_mode: object = None,
    amount: object = 0,
    pend_for_minister: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Shared punishment candidate write: mode + same-target update."""
    from ming_sim.cli_backend import resolve_directive_mode

    target = str(target_id or "").strip()
    action = str(punish_action or "").strip()
    if not target or action not in punish_actions_effective():
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
        existing_id = int(row["id"])
        existing_mode = payload.get("mode")
        break

    mode = resolve_directive_mode(emperor_text, extracted_mode, existing_mode)
    staged = {
        "text": body,
        "actor": minister_name,
        "dossier_action_type": "punishment",
        "target_kind": "character",
        "target_id": target,
        "punish_action": action,
        "mode": mode,
    }
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
    return db.stage_directive_candidate(int(turn), minister_name, payload=staged)


def _materialize_punishment(ctx: MaterializeCtx) -> None:
    """暂存惩处案卷；人物效果按 ADR 0055 判决后落。"""
    if (
        ctx.intent_kind != "punishment"
        or ctx.explicit_prefixed
        or ctx.draft_staged
        or ctx.out.get("pending_action_id")
        or ctx.conversation_intent_handled
    ):
        return
    intent = ctx.intent or {}
    target_id = str(intent.get("name") or intent.get("target_id") or "").strip()
    punish_action = str(intent.get("punish_action") or "").strip()
    if not target_id or punish_action not in punish_actions_effective():
        return
    pending_id = stage_punishment_candidate(
        ctx.session.db,
        ctx.session.state.turn,
        ctx.character.name,
        text=ctx.reply,
        target_id=target_id,
        punish_action=punish_action,
        emperor_text=ctx.player_message,
        extracted_mode=intent.get("mode"),
        amount=intent.get("amount"),
        pend_for_minister=ctx.pend_for_minister,
    )
    if pending_id:
        ctx.out["pending_action_id"] = pending_id


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


def _context_line_present(haystack: str, needle: str) -> bool:
    """整行/整句相等才算已在上下文中；禁止 substring 吞掉当轮短句。"""
    n = str(needle or "").strip()
    if not n:
        return False
    for raw in str(haystack or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line == n:
            return True
        if "：" in line:
            content = line.split("：", 1)[1].strip()
            if content == n:
                return True
    return False


def stage_assignment_candidate(
    db: Any,
    turn: int,
    minister_name: str,
    *,
    text: str,
    title: str = "",
    target_id: str = "",
    emperor_text: object = None,
    extracted_mode: object = None,
    commitment_kind: object = None,
    stop_condition: object = None,
    end_turn: object = 0,
    deadline_months: object = 0,
    ongoing_effects: object = None,
    target_candidate: object = None,
    pend_for_minister: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Shared assignment candidate write (#520 / #502).

    Independent matters each stage a new candidate; only a structured
    target_candidate id updates the named pending assignment (cross-round
    reinforce / ADR 0038 before-image).
    owner 单一来源 = 当前召对大臣（minister_name）；不接受分类器改派。
    """
    from ming_sim.cli_backend import resolve_directive_mode

    body = str(text or "").strip()
    if not body:
        return 0
    # 标题须调用方给当轮锚；禁止缺 title 时吃多轮 body 前 40（前轮头）
    matter_title = str(title or "").strip()
    if not matter_title:
        # 最后兜底：当轮皇帝句，仍不用跨轮 body 头
        matter_title = str(emperor_text or "").strip()[:40]
    if not matter_title:
        return 0
    matter_id = str(target_id or "").strip() or matter_title
    owner = str(minister_name or "").strip()
    if not owner:
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

    mode = resolve_directive_mode(emperor_text, extracted_mode, existing_mode)
    staged: Dict[str, Any] = {
        "text": body,
        "actor": minister_name,
        "dossier_action_type": "assignment",
        "target_kind": "issue",
        "target_id": matter_id,
        "title": matter_title,
        "assignee": owner,
        "mode": mode,
    }
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
    if kind_raw == "until_stop" or has_stop or absolute_end > 0 or has_ongoing:
        if has_stop:
            staged["stop_condition"] = parsed_stop
        if absolute_end > 0:
            staged["end_turn"] = absolute_end
        if has_ongoing:
            staged["ongoing_effects"] = parsed_ongoing
    if existing_id:
        return db.update_directive_candidate(existing_id, staged)
    return db.stage_directive_candidate(int(turn), minister_name, payload=staged)


def _assignment_dossier_text(ctx: MaterializeCtx) -> str:
    """案卷 text：ADR 0028 最近相关对话上下文链 + 本轮皇帝/大臣句。

    不得仅取 ctx.reply or ctx.player_message；recent_context 与分类器同源。
    当轮句按整行锚接入，禁止 substring 判断把短句吞进前轮长文。
    recent_context 空时仍须同时保留皇帝任务描述与大臣领命回话（首轮交办）。
    """
    recent = str(ctx.recent_context or "").strip()
    reply = str(ctx.reply or "").strip()
    player = str(ctx.player_message or "").strip()
    chunks: list[str] = []
    if recent:
        chunks.append(recent)
    if player and not _context_line_present(recent, player):
        chunks.append(f"皇帝：{player}")
    if reply and not _context_line_present(recent, reply):
        chunks.append(f"大臣：{reply}")
    return "\n".join(chunks).strip()


def _materialize_assignment(ctx: MaterializeCtx) -> None:
    """暂存交办·责成案卷；initiative 按 ADR 0055 判决后落。"""
    if (
        ctx.intent_kind != "assignment"
        or ctx.explicit_prefixed
        or ctx.draft_staged
        or ctx.out.get("pending_action_id")
        or ctx.conversation_intent_handled
    ):
        return
    intent = ctx.intent or {}
    title = str(intent.get("title") or "").strip()
    target_id = str(intent.get("target_id") or "").strip()
    # 标题来源：分类 title → 当轮皇帝句；不得在缺 title 时吃跨轮 body 头
    if not title:
        title = str(ctx.player_message or "").strip()[:40]
    body = _assignment_dossier_text(ctx)
    if not title and not target_id and not body:
        return
    pending_id = stage_assignment_candidate(
        ctx.session.db,
        ctx.session.state.turn,
        ctx.character.name,
        text=body,
        title=title,
        target_id=target_id,
        emperor_text=ctx.player_message,
        extracted_mode=intent.get("mode"),
        commitment_kind=intent.get("commitment_kind"),
        stop_condition=intent.get("stop_condition"),
        end_turn=intent.get("end_turn"),
        deadline_months=intent.get("deadline_months"),
        ongoing_effects=intent.get("ongoing_effects"),
        target_candidate=intent.get("target_candidate"),
        pend_for_minister=ctx.pend_for_minister,
    )
    if pending_id:
        ctx.out["pending_action_id"] = pending_id


def stage_military_order_candidate(
    db: Any,
    turn: int,
    minister_name: str,
    *,
    text: str,
    target_id: str,
    assignee: str = "",
    station: object = "",
    deadline_months: object = 0,
    due_turn: object = 0,
    office: object = "",
    emperor_text: object = None,
    extracted_mode: object = None,
    target_candidate: object = None,
    pend_for_minister: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Shared military_order candidate write (#521 / #502).

    收夜只成案卷；station/office 按 ADR 0055 判后物化。既有军调驻不写 new_armies。
    期限只落 due_turn；admission 仅对限期出战（无 station）强制未来 due。
    同军多道独立军令各自成候选；仅 structured target_candidate id 才改草点名更新。
    """
    from ming_sim.cli_backend import resolve_directive_mode

    target = str(target_id or "").strip()
    if not target:
        return 0
    body = str(text or "").strip()
    if not body:
        return 0
    owner = str(assignee or minister_name or "").strip()
    if not owner:
        return 0

    pending_rows = list(pend_for_minister or [])
    if not pending_rows:
        pending_rows = [
            p for p in db.list_pending_actions(int(turn), minister_name=minister_name)
            if p.get("kind") == "directive" and p.get("status") == "pending"
        ]

    # #521 r2 / #502：不得仅凭同一 target_id 把独立军令当改草覆盖。
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
            if str(payload.get("dossier_action_type") or "").strip() != "military_order":
                break
            existing_id = want_id
            existing_mode = payload.get("mode")
            break

    mode = resolve_directive_mode(emperor_text, extracted_mode, existing_mode)
    staged: Dict[str, Any] = {
        "text": body,
        "actor": minister_name,
        "dossier_action_type": "military_order",
        "target_kind": "army",
        "target_id": target,
        "assignee": owner,
        "mode": mode,
    }
    dest = str(station or "").strip()
    if dest:
        staged["station"] = dest
    # 相对月数 / 绝对 due_turn → 未来 due（与 admission 同形）
    try:
        absolute_due = int(due_turn or 0)
    except (TypeError, ValueError):
        absolute_due = 0
    try:
        months = int(deadline_months or 0)
    except (TypeError, ValueError):
        months = 0
    cur = int(turn)
    if absolute_due <= cur and months > 0:
        absolute_due = cur + months
    if absolute_due > cur:
        staged["due_turn"] = absolute_due
    elif months > 0:
        staged["deadline_months"] = months
    office_title = str(office or "").strip()
    if office_title:
        staged["office"] = office_title
    if existing_id:
        return db.update_directive_candidate(existing_id, staged)
    return db.stage_directive_candidate(int(turn), minister_name, payload=staged)


def _materialize_military_order(ctx: MaterializeCtx) -> None:
    """暂存军令·调遣案卷；station/office 按 ADR 0055 判决后落。"""
    if (
        ctx.intent_kind != "military_order"
        or ctx.explicit_prefixed
        or ctx.draft_staged
        or ctx.out.get("pending_action_id")
        or ctx.conversation_intent_handled
    ):
        return
    intent = ctx.intent or {}
    target_id = str(intent.get("target_id") or "").strip()
    if not target_id:
        return
    assignee = str(
        intent.get("name") or intent.get("assignee") or ctx.character.name or ""
    ).strip()
    body = str(ctx.reply or ctx.player_message or "").strip()
    if not body:
        return
    pending_id = stage_military_order_candidate(
        ctx.session.db,
        ctx.session.state.turn,
        ctx.character.name,
        text=body,
        target_id=target_id,
        assignee=assignee,
        station=intent.get("station"),
        deadline_months=intent.get("deadline_months"),
        due_turn=intent.get("due_turn"),
        office=intent.get("office"),
        emperor_text=ctx.player_message,
        extracted_mode=intent.get("mode"),
        target_candidate=intent.get("target_candidate"),
        pend_for_minister=ctx.pend_for_minister,
    )
    if pending_id:
        ctx.out["pending_action_id"] = pending_id


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


def stage_revoke_authority_candidate(
    db: Any,
    turn: int,
    minister_name: str,
    *,
    text: str,
    authority_id: object = 0,
    holder_id: object = "",
    privilege: object = "",
    emperor_text: object = None,
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

    mode = resolve_directive_mode(emperor_text, extracted_mode, existing_mode)
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


def _materialize_revoke_authority(ctx: MaterializeCtx) -> None:
    """暂存收权·罢差案卷；authority_changes 收回按 ADR 0055 判决后落。"""
    if (
        ctx.intent_kind != "revoke_authority"
        or ctx.explicit_prefixed
        or ctx.draft_staged
        or ctx.out.get("pending_action_id")
        or ctx.conversation_intent_handled
    ):
        return
    intent = ctx.intent or {}
    if str(intent.get("target_candidate") or "").strip() == "含糊":
        ctx.out["directive_confirmation_ambiguous"] = {"candidates": []}
        return
    body = str(ctx.reply or ctx.player_message or "").strip()
    if not body:
        return
    holder = str(intent.get("name") or intent.get("holder_id") or "").strip()
    pending_id = stage_revoke_authority_candidate(
        ctx.session.db,
        ctx.session.state.turn,
        ctx.character.name,
        text=body,
        authority_id=intent.get("authority_id"),
        holder_id=holder,
        privilege=intent.get("privilege"),
        emperor_text=ctx.player_message,
        extracted_mode=intent.get("mode"),
        target_candidate=intent.get("target_candidate"),
        pend_for_minister=ctx.pend_for_minister,
    )
    if pending_id:
        ctx.out["pending_action_id"] = pending_id


# 纯授权案卷归收权·罢差（ADR 0041/0071）；不得入撤回成命目标域。
_PURE_AUTHORITY_DOSSIER_ACTIONS = frozenset({
    "authorization", "secret_authorization",
})


def _dossier_is_revocable_decree(db: Any, dossier: Dict[str, Any]) -> bool:
    """可撤成命：已颁/执行中的承诺·旨意；纯授权归收权·罢差。

    直接 dossier、initiative 回指、含糊候选三入口共用本资格。
    """
    status = str(dossier.get("status") or "").strip()
    if status not in {"promulgated", "executing"}:
        return False
    action = str(dossier.get("action_type") or "").strip()
    if action in _PURE_AUTHORITY_DOSSIER_ACTIONS:
        return False
    return True


def _list_revocable_decree_candidates(db: Any) -> List[Dict[str, Any]]:
    """含糊问清候选：与 admission 同一语义资格的可撤成命。"""
    rows = db.conn.execute(
        "SELECT id, decree_text, status, action_type FROM decree_dossiers "
        "WHERE status IN ('promulgated', 'executing') ORDER BY id",
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for row in rows:
        dossier = {
            "id": int(row["id"]),
            "decree_text": row["decree_text"],
            "status": row["status"],
            "action_type": row["action_type"],
        }
        if not _dossier_is_revocable_decree(db, dossier):
            continue
        text = str(row["decree_text"] or "").strip() or f"案卷{int(row['id'])}"
        out.append({"id": int(row["id"]), "summary": text})
    return out


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


def stage_revoke_decree_candidate(
    db: Any,
    turn: int,
    minister_name: str,
    *,
    text: str,
    target_id: object = "",
    target_kind: object = "",
    emperor_text: object = None,
    extracted_mode: object = None,
    target_candidate: object = None,
    pend_for_minister: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Shared revoke_decree candidate write (#523 / ADR 0041).

    有代价的新命令入闸；目标仅承诺/旨意。非 undo、不删旧账。
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

    mode = resolve_directive_mode(emperor_text, extracted_mode, existing_mode)
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
    if existing_id:
        return db.update_directive_candidate(existing_id, staged)
    return db.stage_directive_candidate(int(turn), minister_name, payload=staged)


def _materialize_revoke_decree(ctx: MaterializeCtx) -> None:
    """暂存撤回成命案卷；breach/initiative 终结按 ADR 0055 判决后落。"""
    if (
        ctx.intent_kind != "revoke_decree"
        or ctx.explicit_prefixed
        or ctx.draft_staged
        or ctx.out.get("pending_action_id")
        or ctx.conversation_intent_handled
    ):
        return
    intent = ctx.intent or {}
    if str(intent.get("target_candidate") or "").strip() == "含糊":
        # #502 含糊三态：给出真实可撤成命候选，供皇帝点名；不静默暂存
        ctx.out["directive_confirmation_ambiguous"] = {
            "candidates": _list_revocable_decree_candidates(ctx.session.db),
        }
        return
    body = str(ctx.reply or ctx.player_message or "").strip()
    if not body:
        return
    pending_id = stage_revoke_decree_candidate(
        ctx.session.db,
        ctx.session.state.turn,
        ctx.character.name,
        text=body,
        target_id=intent.get("target_id"),
        target_kind=intent.get("target_kind"),
        emperor_text=ctx.player_message,
        extracted_mode=intent.get("mode"),
        target_candidate=intent.get("target_candidate"),
        pend_for_minister=ctx.pend_for_minister,
    )
    if pending_id:
        ctx.out["pending_action_id"] = pending_id


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


# 旧名别名：避免外部/测试仍 import _parse_responsible_bodies 时分叉
_parse_responsible_bodies = parse_responsible_bodies


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
    emperor_text: object = None,
    extracted_mode: object = None,
    target_candidate: object = None,
    pend_for_minister: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Shared referral candidate write (#524 / #502).

    下议只承 deadline_months(1–36) 与非空机关/职司 responsible_bodies；
    落 end_turn=turn+N 与 payload.responsible_bodies。禁个人 owner/assignee。
    initiative 按 ADR 0055 判后创建。
    """
    from ming_sim.cli_backend import resolve_directive_mode

    body = str(text or "").strip()
    if not body:
        return 0
    matter_title = str(title or "").strip()
    if not matter_title:
        matter_title = str(emperor_text or "").strip()[:40]
    if not matter_title:
        return 0
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

    mode = resolve_directive_mode(emperor_text, extracted_mode, existing_mode)
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
    # 禁个人 owner：显式不写 assignee/assignee_id
    if existing_id:
        return db.update_directive_candidate(existing_id, staged)
    return db.stage_directive_candidate(int(turn), minister_name, payload=staged)


def _materialize_referral(ctx: MaterializeCtx) -> None:
    """暂存下议案卷；initiative 按 ADR 0055 判决后落。"""
    if (
        ctx.intent_kind != "referral"
        or ctx.explicit_prefixed
        or ctx.draft_staged
        or ctx.out.get("pending_action_id")
        or ctx.conversation_intent_handled
    ):
        return
    intent = ctx.intent or {}
    title = str(intent.get("title") or "").strip()
    target_id = str(intent.get("target_id") or "").strip()
    if not title:
        title = str(ctx.player_message or "").strip()[:40]
    body = str(ctx.reply or ctx.player_message or "").strip()
    if not body and not title and not target_id:
        return
    if not body:
        body = title or target_id
    pending_id = stage_referral_candidate(
        ctx.session.db,
        ctx.session.state.turn,
        ctx.character.name,
        text=body,
        title=title,
        target_id=target_id,
        deadline_months=intent.get("deadline_months"),
        responsible_bodies=intent.get("responsible_bodies"),
        emperor_text=ctx.player_message,
        extracted_mode=intent.get("mode"),
        target_candidate=intent.get("target_candidate"),
        pend_for_minister=ctx.pend_for_minister,
    )
    if pending_id:
        ctx.out["pending_action_id"] = pending_id


def validate_tingtui_appointment_shape(obj: Any) -> Tuple[bool, str]:
    """廷推会推产出 shape：须与任免 FieldSpec 同形；本片只验不裁定。

    正例：kind=appointment + appoint_action∈{任命,罢免} + name + (任命须 office)。
    反例：appoint_action=无；缺 name/office；塞交办 owner/assignee；kind=assignment。
    """
    from ming_sim.action_clusters import validate_action_candidate_shape

    if not isinstance(obj, dict):
        return False, "tingtui result must be a mapping"
    kind = str(obj.get("kind") or "").strip()
    if kind != "appointment":
        return False, f"tingtui result kind must be appointment, got {kind!r}"
    # 塞交办个人 owner/assignee → 拒（下议/交办语义互斥）
    for banned in ("owner", "assignee", "assignee_id"):
        if str(obj.get(banned) or "").strip():
            return False, f"tingtui appointment must not carry {banned}"
    ok, reason = validate_action_candidate_shape(obj)
    if not ok:
        return False, reason
    action = str(obj.get("appoint_action") or "").strip()
    if action not in {"任命", "罢免"}:
        return False, f"appoint_action must be 任命 or 罢免, got {action!r}"
    name = str(obj.get("name") or "").strip()
    if not name:
        return False, "tingtui appointment missing name"
    if action == "任命" and not str(obj.get("office") or "").strip():
        return False, "tingtui 任命 missing office"
    return True, ""


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
                # 与 grant_allocation 共享 target_id：须能承载人物/地区/项目/军队
                FieldSpec("target_id", "目标", None, "", max_len=80),
                FieldSpec(
                    "mode", "颁布方式",
                    frozenset({"ordinary", "midzhi"}), "",
                ),
            ),
            materialize_fn=_materialize_pacification,
        ),
        ActionCluster(
            "交办·责成", "assignment", EFFECT_MATERIALIZE, priority=56,
            fields=(
                FieldSpec("title", "标题", None, "", max_len=80),
                # owner=当前召对大臣；不设 assignee/name 改派字段（#520 r2）
                # 与 grant/pacification 共享 target_id：事项锚（跨轮强化身份）
                FieldSpec("target_id", "目标", None, "", max_len=80),
                FieldSpec(
                    "commitment_kind", "承诺类型",
                    frozenset({"无", "until_stop"}), "无",
                ),
                FieldSpec("stop_condition", "停止条件", None, "", max_len=500),
                # 相对月数（共享 secret 的期限月数）由 stage 换算绝对 end_turn
                FieldSpec("end_turn", "截止回合", None, 0, as_int=True),
                FieldSpec("ongoing_effects", "持续效果", None, "", max_len=1000),
                FieldSpec(
                    "mode", "颁布方式",
                    frozenset({"ordinary", "midzhi"}), "",
                ),
                # 明确改草指向：分类归一化须保留，供 stage 只更新点名候选
                FieldSpec("target_candidate", "目标候选", None, "", max_len=40),
            ),
            materialize_fn=_materialize_assignment,
        ),
        ActionCluster(
            "恩赏·拨帑", "grant_allocation", EFFECT_MATERIALIZE, priority=57,
            fields=(
                FieldSpec(
                    "grant_action", "恩赏拨帑",
                    GRANT_ACTIONS, "无",
                ),
                FieldSpec("name", "姓名", None, "", max_len=20),
                # 政务拨款对象：赈灾地区 / 项目 / 协饷军队 / 恩赏人物
                FieldSpec("target_id", "目标", None, "", max_len=80),
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
                # 明确改草指向：分类归一化须保留，供 stage 只更新点名候选
                FieldSpec("target_candidate", "目标候选", None, "", max_len=40),
            ),
            materialize_fn=_materialize_grant_allocation,
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
                ),
                FieldSpec("name", "姓名", None, "", max_len=20),
                # 与 pacification/grant_allocation 共享 target_id 中文键（#518 契约）
                FieldSpec("target_id", "目标", None, "", max_len=80),
                FieldSpec("amount", "金额", None, 0, as_int=True),
                FieldSpec(
                    "mode", "颁布方式",
                    frozenset({"ordinary", "midzhi"}), "",
                ),
            ),
            materialize_fn=_materialize_punishment,
        ),
        ActionCluster(
            "军令·调遣", "military_order", EFFECT_MATERIALIZE, priority=59,
            fields=(
                # 与 grant/pacification 共享 target_id：既有军队稳定 id
                FieldSpec("target_id", "目标", None, "", max_len=80),
                # 承办人 / 责任军将（admission 映 assignee_id）
                FieldSpec("name", "姓名", None, "", max_len=20),
                FieldSpec("station", "驻地", None, "", max_len=80),
                # 与 secret 共享期限月数；限期出战 stage/admission 换算绝对 due_turn
                FieldSpec(
                    "deadline_months", "期限月数", None, 0, as_int=True, int_hi=36,
                ),
                # 可选：军将职守真变才填；判后走人物变更/任免唯一核
                FieldSpec("office", "官职", None, "", max_len=40),
                # #521 r2 / #502：明确改草指向；同军独立军令不得仅凭 target_id 覆盖
                FieldSpec("target_candidate", "目标候选", None, "", max_len=40),
                FieldSpec(
                    "mode", "颁布方式",
                    frozenset({"ordinary", "midzhi"}), "",
                ),
            ),
            materialize_fn=_materialize_military_order,
        ),
        ActionCluster(
            "收权·罢差", "revoke_authority", EFFECT_MATERIALIZE, priority=61,
            fields=(
                FieldSpec("name", "姓名", None, "", max_len=20),
                FieldSpec(
                    "authority_id", "授权编号", None, 0, as_int=True,
                ),
                FieldSpec(
                    "privilege", "权项",
                    frozenset({
                        "无", "尚方剑密授", "便宜行事", "专差督办", "新机构专办",
                    }), "无",
                ),
                FieldSpec("target_candidate", "目标候选", None, "", max_len=40),
                FieldSpec(
                    "mode", "颁布方式",
                    frozenset({"ordinary", "midzhi"}), "",
                ),
            ),
            materialize_fn=_materialize_revoke_authority,
        ),
        ActionCluster(
            "撤回成命", "revoke_decree", EFFECT_MATERIALIZE, priority=62,
            fields=(
                # 目标成命：承诺/旨意 id（dossier:<id> / issue:<id> / 裸数字）
                FieldSpec("target_id", "目标", None, "", max_len=80),
                FieldSpec("name", "姓名", None, "", max_len=20),
                # #502：指称含糊三态
                FieldSpec("target_candidate", "目标候选", None, "", max_len=40),
                FieldSpec(
                    "mode", "颁布方式",
                    frozenset({"ordinary", "midzhi"}), "",
                ),
            ),
            materialize_fn=_materialize_revoke_decree,
        ),
        ActionCluster(
            "下议", "referral", EFFECT_MATERIALIZE, priority=63,
            fields=(
                FieldSpec("title", "标题", None, "", max_len=80),
                # 事项锚；与 grant/assignment 共享 target_id
                FieldSpec("target_id", "目标", None, "", max_len=80),
                # 议期月数 1–36；stage 换算绝对 end_turn=turn+N
                FieldSpec(
                    "deadline_months", "期限月数", None, 0, as_int=True, int_hi=36,
                ),
                # 机关/职司名 JSON 列表（如 ["吏部","廷推会"]）；禁个人名
                FieldSpec(
                    "responsible_bodies", "责任机关", None, "", max_len=500,
                ),
                FieldSpec(
                    "mode", "颁布方式",
                    frozenset({"ordinary", "midzhi"}), "",
                ),
                FieldSpec("target_candidate", "目标候选", None, "", max_len=40),
            ),
            materialize_fn=_materialize_referral,
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
