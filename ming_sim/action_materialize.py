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

from ming_sim.decree_vocabulary import TARGET_KINDS
from ming_sim.execution_pressure import write_locality_scope_for_target_kind
from ming_sim.executor_routing import duty_route_categories
from ming_sim.structured_decree import (
    StructuredDecreeCombinationError,
    apply_assembled_to_payload,
    assemble_structured_decree,
)

from ming_sim.action_clusters import (
    ActionCluster,
    FieldSpec,
    EFFECT_ANSWER_EXISTING,
    EFFECT_MATERIALIZE,
    EFFECT_NOOP,
    cluster_by_kind,
    install_action_catalog,
    materialize_clusters_ordered,
    validate_action_candidate_shape,
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
    # #568：当前对话轮 id（session.chat/web/CLI 作用域透传）；点策 origin 结构化排除本轮
    chat_turn_id: int = 0


def _draft_path_took_effect(ctx: MaterializeCtx) -> bool:
    """#1380：拟旨通道是否已占本轮（含显式前缀 / 对话拟旨 / multi draft 候选）。"""
    from ming_sim.cli_backend import _DRAFT_PREFIXES

    if ctx.draft_staged or ctx.intent_kind == "draft":
        return True
    if (ctx.message_text or "").startswith(_DRAFT_PREFIXES):
        return True
    if ctx.intent_candidates and any(
        str(c.get("kind") or "") == "draft" for c in ctx.intent_candidates
    ):
        return True
    return False


def _materializable_draft_xiexang(
    ctx: MaterializeCtx,
    candidate: Dict[str, Any],
) -> Dict[str, Any]:
    """在真实写入前置条件齐全时，把 draft 协饷投影为本轮 grant 候选。

    列表契约逐项独立物化；不按付款字段相等折叠。
    draft+协饷验证失败保持零写且产出 typed 呈现信号，不退回 ordinary draft。
    """
    if (
        str(candidate.get("kind") or "").strip() != "draft"
        or str(candidate.get("grant_action") or "").strip() != "协饷"
    ):
        return candidate
    require_materializable_xiexang_payload(
        ctx.session.db,
        text=ctx.reply,
        amount=candidate.get("amount"),
        account=str(candidate.get("account") or ""),
        purpose=str(candidate.get("purpose") or ""),
        target_kind=str(candidate.get("target_kind") or ""),
        target_id=str(candidate.get("target_id") or ""),
        cadence=str(candidate.get("cadence") or ""),
    )
    promoted = dict(candidate)
    promoted["kind"] = "grant_allocation"
    return promoted


def _record_decree_validation_failures(
    ctx: MaterializeCtx,
    out: Dict[str, Any],
    failures: list[tuple[dict[str, Any], BaseException]],
) -> None:
    """Persist every engine rejection, then generate a player-lane recovery report."""
    from ming_sim.applier import (
        Provenance, RejectedItem, RejectionCollector, atomic,
        mirror_rejections_after_commit,
    )
    from ming_sim.cli_backend import compose_decree_validation_recovery

    diagnostic_failures = [
        {
            "candidate": candidate,
            "message": str(exc),
            "failed_fields": sorted(str(field) for field in exc.failed_fields),
        }
        for candidate, exc in failures
    ]
    failed_fields = {
        field
        for failure in diagnostic_failures
        for field in failure["failed_fields"]
    }
    collector = RejectionCollector()
    for failure in diagnostic_failures:
        collector.record(
            "audience_decree",
            RejectedItem(
                item=failure["candidate"],
                reason=failure["message"],
                category="decree_validation",
                source=Provenance.player_decree,
            ),
            int(ctx.session.state.turn),
        )
    # The existing rejection owner controls flush, transaction outcome, and
    # post-commit mirror.  Recovery generation stays outside its write window.
    from ming_sim.error_pack import rejections_jsonl_path

    with atomic(ctx.session.db):
        collector.flush_to_db(ctx.session.db)
        mirror_rejections_after_commit(
            ctx.session.db, collector, rejections_jsonl_path,
        )
    # Recovery is downstream of the committed engine facts: backend failure
    # cannot erase the validation causes, and no write transaction spans LLM I/O.
    report = compose_decree_validation_recovery(
        sorted(failed_fields),
        speaker_name=ctx.character.name,
        llm_config=ctx.llm_config,
    )
    out["decree_validation_failure"] = {
        "failed_fields": sorted(failed_fields),
        "report": report,
    }


def _rejection_item_for_exc(
    original_item: dict[str, Any],
    exc: BaseException,
) -> dict[str, Any]:
    """Prefer typed partial_result when present; else fall back to classifier item."""
    partial = getattr(exc, "partial_result", None)
    if isinstance(partial, dict) and partial:
        return dict(partial)
    return dict(original_item or {})


def _raise_cached_draft_combo_failure(
    exc: StructuredDecreeCombinationError,
    candidate_kind_index: int,
) -> None:
    """Re-raise batch combo failure only for indexes marked in draft_failures.

    Legal siblings return without recording a rejection or re-extracting.
    partial_result is narrowed to the failed draft so ledger item_json keeps
    the actual rejected decree fields (ADR 0008 decision 5).
    """
    draft_failures = dict(getattr(exc, "draft_failures", None) or {})
    idx = int(candidate_kind_index)
    if draft_failures and idx not in draft_failures:
        return
    partial = getattr(exc, "partial_result", None)
    drafts = partial.get("drafts") if isinstance(partial, dict) else None
    draft_item: dict[str, Any] = {}
    if isinstance(drafts, list) and 0 <= idx < len(drafts) and isinstance(drafts[idx], dict):
        draft_item = dict(drafts[idx])
    elif isinstance(partial, dict) and partial:
        draft_item = dict(partial)
    fields = frozenset(draft_failures.get(idx) or getattr(exc, "failed_fields", None) or ())
    raise StructuredDecreeCombinationError(
        str(exc),
        partial_result=draft_item,
        failed_fields=fields,
        draft_failures={idx: fields} if fields else dict(draft_failures),
    ) from exc


def _invoke_materializer(
    ctx: MaterializeCtx,
    fn: Any,
    original_item: dict[str, Any],
    failures: list[tuple[dict[str, Any], BaseException]],
) -> None:
    """Run one materializer and route every typed validation failure identically."""
    try:
        fn(ctx)
    except (
        StructuredDecreeCombinationError,
        DecreeMaterializationValidationError,
    ) as exc:
        failures.append((_rejection_item_for_exc(original_item, exc), exc))


_PENDING_BASELINE_COLS = (
    "id", "turn", "kind", "action", "target_id", "minister_name",
    "payload_json", "status", "night_id", "night_approved", "created_at",
)
_SUMMON_LEDGER_BASELINE_COLS = (
    "id", "night_id", "seq", "person_names", "audibility", "body", "tags",
    "source_chat_turn_id", "presence_effect", "order_key", "origin_chat_turn_id",
    "origin_ref", "created_at",
)


def _snapshot_pending_baseline(db: Any, turn: int) -> tuple[dict[str, Any], ...]:
    """Full pending-row baseline for batch all-or-nothing restore.

    Covers create / in-place update / hedge-delete, not merely new ids.
    """
    rows = db.conn.execute(
        f"SELECT {', '.join(_PENDING_BASELINE_COLS)} FROM pending_actions "
        "WHERE turn=? AND status='pending' ORDER BY id",
        (int(turn),),
    ).fetchall()
    return tuple(
        {col: row[col] for col in _PENDING_BASELINE_COLS}
        for row in rows
    )


def _snapshot_office_summon_baseline(
    db: Any, pending_rows: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    """Snapshot inactive office:<pending_id> summon ledger rows as data.

    Whole-row restore — no parallel ensure/discard derivation rules.
    """
    cols_sql = ", ".join(_SUMMON_LEDGER_BASELINE_COLS)
    out: list[dict[str, Any]] = []
    for row in pending_rows:
        if str(row.get("kind") or "") != "office":
            continue
        origin = f"office:{int(row['id'])}"
        entry = db.conn.execute(
            f"SELECT {cols_sql} FROM story_ledger_entries "
            "WHERE origin_ref=? LIMIT 1",
            (origin,),
        ).fetchone()
        if entry is None:
            continue
        out.append({col: entry[col] for col in _SUMMON_LEDGER_BASELINE_COLS})
    return tuple(out)


def _snapshot_batch_write_baseline(db: Any, turn: int) -> dict[str, Any]:
    pending = _snapshot_pending_baseline(db, turn)
    return {
        "pending": pending,
        "summons": _snapshot_office_summon_baseline(db, pending),
    }


def _restore_office_summon_baseline(
    db: Any,
    *,
    pending_baseline: tuple[dict[str, Any], ...],
    summon_baseline: tuple[dict[str, Any], ...],
) -> None:
    """Restore office summon ledger rows to baseline snapshot (data, not rules)."""
    from ming_sim.audience_night import discard_inactive_office_summon

    baseline_office_ids = {
        int(row["id"])
        for row in pending_baseline
        if str(row.get("kind") or "") == "office"
    }
    by_origin = {
        str(row.get("origin_ref") or ""): row for row in summon_baseline
    }
    cols_sql = ", ".join(_SUMMON_LEDGER_BASELINE_COLS)
    placeholders = ", ".join("?" for _ in _SUMMON_LEDGER_BASELINE_COLS)
    for action_id in sorted(baseline_office_ids):
        origin = f"office:{action_id}"
        before = by_origin.get(origin)
        current = db.conn.execute(
            "SELECT id FROM story_ledger_entries WHERE origin_ref=? LIMIT 1",
            (origin,),
        ).fetchone()
        if before is None:
            if current is not None:
                # Batch-created summon on a pre-existing office — drop via owner seam.
                discard_inactive_office_summon(db, action_id)
            continue
        before_id = int(before["id"])
        if current is not None and int(current["id"]) == before_id:
            continue
        if current is not None:
            discard_inactive_office_summon(db, action_id)
        db.conn.execute(
            f"INSERT INTO story_ledger_entries ({cols_sql}) VALUES ({placeholders})",
            tuple(before[col] for col in _SUMMON_LEDGER_BASELINE_COLS),
        )


def _restore_batch_write_baseline(
    db: Any, turn: int, baseline: dict[str, Any],
) -> None:
    """Restore turn pending + office-summon write set to baseline snapshot."""
    from ming_sim.applier import atomic

    turn_i = int(turn)
    pending_baseline = tuple(baseline.get("pending") or ())
    summon_baseline = tuple(baseline.get("summons") or ())
    baseline_by_id = {int(row["id"]): row for row in pending_baseline}
    cols_sql = ", ".join(_PENDING_BASELINE_COLS)
    with atomic(db):
        current_rows = db.conn.execute(
            f"SELECT {cols_sql} FROM pending_actions "
            "WHERE turn=? AND status='pending' ORDER BY id",
            (turn_i,),
        ).fetchall()
        current_ids = {int(row["id"]) for row in current_rows}
        baseline_ids = set(baseline_by_id)

        # Drop batch-created rows (withdraw also clears inactive office summons).
        for action_id in sorted(current_ids - baseline_ids):
            db.withdraw_pending_action(action_id, turn_i)

        # Revert in-place updates to baseline payload/meta.
        for action_id in sorted(current_ids & baseline_ids):
            before = baseline_by_id[action_id]
            db.conn.execute(
                "UPDATE pending_actions SET turn=?, kind=?, action=?, target_id=?, "
                "minister_name=?, payload_json=?, status=?, night_id=?, "
                "night_approved=?, created_at=? WHERE id=?",
                (
                    int(before["turn"]),
                    str(before["kind"]),
                    str(before["action"]),
                    before["target_id"],
                    str(before["minister_name"] or ""),
                    str(before["payload_json"] or "{}"),
                    str(before["status"] or "pending"),
                    int(before["night_id"] or 0),
                    int(before["night_approved"] or 0),
                    str(before["created_at"] or ""),
                    action_id,
                ),
            )

        # Recreate baseline rows deleted by hedge/offset inside the batch.
        for action_id in sorted(baseline_ids - current_ids):
            before = baseline_by_id[action_id]
            db.conn.execute(
                "INSERT INTO pending_actions "
                "(id, turn, kind, action, target_id, minister_name, payload_json, "
                "status, night_id, night_approved, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    action_id,
                    int(before["turn"]),
                    str(before["kind"]),
                    str(before["action"]),
                    before["target_id"],
                    str(before["minister_name"] or ""),
                    str(before["payload_json"] or "{}"),
                    str(before["status"] or "pending"),
                    int(before["night_id"] or 0),
                    int(before["night_approved"] or 0),
                    str(before["created_at"] or ""),
                ),
            )

        # Summon ledger is restored as frozen rows, not re-derived from payload.
        _restore_office_summon_baseline(
            db,
            pending_baseline=pending_baseline,
            summon_baseline=summon_baseline,
        )


def _rollback_batch_writes(
    ctx: MaterializeCtx,
    *,
    write_baseline: dict[str, Any],
    baseline_out: dict[str, Any],
) -> None:
    """All-or-nothing: restore full pending+summon write set; align out projection."""
    db = ctx.session.db
    turn = int(ctx.session.state.turn)
    _restore_batch_write_baseline(db, turn, write_baseline)
    # Projection must match reality after rollback (no hidden pending id).
    if "pending_action_id" in baseline_out:
        ctx.out["pending_action_id"] = baseline_out["pending_action_id"]
    else:
        ctx.out.pop("pending_action_id", None)
    if "directive" in baseline_out:
        ctx.out["directive"] = baseline_out["directive"]
    else:
        ctx.out.pop("directive", None)
    ctx.draft_staged = False


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
        draft_total = sum(
            str(candidate.get("kind") or "") == "draft"
            for candidate in ctx.intent_candidates
        )
        draft_index = 0
        candidate_records = []
        validation_failures: list[tuple[dict[str, Any], BaseException]] = []
        for candidate in ctx.intent_candidates:
            original_candidate = dict(candidate)
            original_kind = str(candidate.get("kind") or "")
            original_draft_index = draft_index
            if original_kind == "draft":
                draft_index += 1
            try:
                materializable = _materializable_draft_xiexang(ctx, candidate)
            except DecreeMaterializationValidationError as exc:
                validation_failures.append((original_candidate, exc))
                continue
            candidate_records.append((
                materializable, original_candidate, original_kind, original_draft_index,
            ))
        if ctx.explicit_prefixed:
            candidate_records.sort(
                key=lambda record: str(record[0].get("kind") or "")
                != "grant_allocation"
            )
        kind_counts: Dict[str, int] = {}
        for candidate, _original_candidate, _original_kind, _original_index in candidate_records:
            kind = str(candidate.get("kind") or "")
            kind_counts[kind] = kind_counts.get(kind, 0) + 1
        kind_indexes: Dict[str, int] = {}
        grant_staged = False
        # Snapshot full pending + office-summon write set before mutations.
        write_baseline = _snapshot_batch_write_baseline(
            ctx.session.db, ctx.session.state.turn,
        )
        for candidate, original_candidate, original_kind, original_draft_index in candidate_records:
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
                explicit_prefixed=ctx.explicit_prefixed and not grant_staged,
                candidate_kind_index=(
                    original_draft_index if original_kind == "draft" else kind_index
                ),
                candidate_kind_count=(
                    draft_total if original_kind == "draft" else kind_counts[kind]
                ),
                multi_intent_batch=multi_batch,
                conversation_intent_handled=False,
                draft_staged=False,
            )
            failure_count = len(validation_failures)
            _invoke_materializer(
                candidate_ctx, fn, original_candidate, validation_failures,
            )
            if len(validation_failures) > failure_count:
                # Failed candidate must not wipe sibling projection via baseline_out.
                continue
            if kind == "grant_allocation" and int(
                candidate_out.get("pending_action_id") or 0
            ) > int(baseline_out.get("pending_action_id") or 0):
                grant_staged = True
            ctx.out.update(candidate_out)
            if candidate_ctx.draft_staged:
                ctx.draft_staged = True
        if validation_failures:
            # Mixed batch: any typed failure → restore full pending write set.
            # Fail path must not enter the writable office tail afterward.
            _rollback_batch_writes(
                ctx,
                write_baseline=write_baseline,
                baseline_out=baseline_out,
            )
            _record_decree_validation_failures(ctx, ctx.out, validation_failures)
            return
        # #1380：拟旨优先后仍须并行 office（仅 LLM 分类路；前缀路禁，见 #344 US3）
        if _draft_path_took_effect(ctx) and not ctx.explicit_prefixed:
            parallel_stage_office_from_appointment_intent(ctx)
        return

    seen: set = set()
    validation_failures: list[tuple[dict[str, Any], BaseException]] = []
    for cluster in materialize_clusters_ordered():
        fn = cluster.materialize_fn
        if fn is None or fn in seen:
            continue
        seen.add(fn)
        _invoke_materializer(ctx, fn, {}, validation_failures)
    if validation_failures:
        _record_decree_validation_failures(ctx, ctx.out, validation_failures)
    # #1380：LLM 分类拟旨路并行 office（无任免意图则 no-op）。
    # 显式「拟旨如下」前缀任免走随诏 extractor office_changes（#344 US3 / ADR 0028 /
    # test_decree_prefix_appointment_not_double_staged）；禁并行 LLM 抽取。
    if _draft_path_took_effect(ctx) and not ctx.explicit_prefixed:
        parallel_stage_office_from_appointment_intent(ctx)


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
        frozen = secret.get("covert_task") if isinstance(secret.get("covert_task"), dict) else None
        if frozen is None:
            reason = str(secret.get("contract_error") or "密令抽取未能冻结合同").strip()
            failures = list(ctx.out.get("pending_action_failures") or [])
            failures.append({
                "kind": "secret_order",
                "action": "新建",
                "minister_name": minister_name,
                "retryable": True,
                "message": f"密令未能正式落库：{reason}",
            })
            ctx.out["pending_action_failures"] = failures
            ctx.out["pending_action_id"] = 0
            ctx.conversation_intent_handled = True
            return
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
                "covert_task": frozen,
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
    from ming_sim.cli_backend import (
        UnknownParticipantEscalate,
        compose_unknown_participant_inworld_report,
        extract_draft_intent_with_roster_heal,
        normalize_draft_person_roster,
        resolve_directive_mode,
    )

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

    def _heal_or_escalate(**kwargs: Any) -> Optional[Dict[str, Any]]:
        """自愈抽取；真不在册 → 戏内回禀、不落草案、不炸整轮。"""
        try:
            return extract_draft_intent_with_roster_heal(**kwargs)
        except UnknownParticipantEscalate as exc:
            report = compose_unknown_participant_inworld_report(
                exc.names,
                voice="minister",
                speaker_name=minister_name,
                llm_config=ctx.llm_config,
            )
            ctx.out["unknown_participant_escalate"] = {
                "names": list(exc.names),
                "report": report,
            }
            return None

    if (
        intent is not None
        and intent_kind == "draft"
        and ctx.candidate_kind_count > 1
    ):
        cached_combo = ctx.batch_state.get("draft_combo_error")
        if isinstance(cached_combo, StructuredDecreeCombinationError):
            # 批级组合失败缓存命中：按 draft_failures 归属，不重抽。
            _raise_cached_draft_combo_failure(
                cached_combo, ctx.candidate_kind_index,
            )
            return
        if "drafts" not in ctx.batch_state:
            if "unknown_participant_escalate" in ctx.batch_state:
                ctx.out["unknown_participant_escalate"] = ctx.batch_state[
                    "unknown_participant_escalate"
                ]
                return
            try:
                batch_res = _heal_or_escalate(
                    player_message=ctx.player_message,
                    minister_reply=ctx.reply,
                    llm_config=ctx.llm_config,
                    draft_count=ctx.candidate_kind_count,
                    content=getattr(session, "content", None),
                    db=session.db,
                )
            except StructuredDecreeCombinationError as exc:
                # 批级组合失败同 unknown_participant_escalate：一次缓存，兄弟不重抽。
                ctx.batch_state["draft_combo_error"] = exc
                ctx.batch_state["drafts"] = []
                _raise_cached_draft_combo_failure(exc, ctx.candidate_kind_index)
                return
            if batch_res is None:
                # 批抽一次耗尽：记入 batch_state，兄弟 kind 同回禀不重复 LLM
                esc = ctx.out.get("unknown_participant_escalate")
                if esc is not None:
                    ctx.batch_state["unknown_participant_escalate"] = esc
                ctx.batch_state["drafts"] = []
                return
            ctx.batch_state["drafts"] = list(batch_res.get("drafts") or [])
        drafts = ctx.batch_state["drafts"]
        if ctx.candidate_kind_index >= len(drafts):
            return
        batch_draft = drafts[ctx.candidate_kind_index]
        if not isinstance(batch_draft, dict):
            return
        draft_res = dict(batch_draft)
    else:
        healed = _heal_or_escalate(
            player_message=ctx.player_message,
            minister_reply=ctx.reply,
            llm_config=ctx.llm_config,
            has_pending_draft=has_existing_draft,
            existing_draft_text=existing_draft_text,
            existing_candidates=dir_candidates or None,
            content=getattr(session, "content", None),
            db=session.db,
        )
        if healed is None:
            return
        draft_res = healed
        if intent is not None and intent_kind == "draft" and not has_existing_draft:
            # #515 的并行 classifier 已经确定“拟旨”，大臣回话仍是正文真源；
            # #571 的串行抽取只补案卷结构字段，失败不得吞掉已判定的动作。
            # #568 / ADR 0059：strategy_selection 正文沿 ADR 0028 从对话上下文展开，
            # 不得用领命回话覆盖、不得仅存皇帝点策原句。
            is_strategy_selection = (
                str(draft_res.get("dossier_action_type") or "").strip()
                == "strategy_selection"
            )
            if is_strategy_selection:
                context_body = _assignment_dossier_text(ctx)
                expanded = (
                    context_body
                    or str(draft_res.get("draft_text") or "").strip()
                    or str(ctx.reply or "").strip()
                    or str(ctx.player_message or "").strip()
                )
                draft_res = {
                    **draft_res,
                    "draft_action": "拟旨",
                    "draft_text": expanded,
                    "target_candidate": "",
                }
                origin_tid = _strategy_selection_origin_turn_id(
                    session.db,
                    minister_name,
                    int(session.state.turn),
                    exclude_turn_id=int(ctx.chat_turn_id or 0),
                )
                if origin_tid > 0:
                    draft_res["source_chat_turn_id"] = origin_tid
            else:
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
        # F3：与 capture 共用 normalize_draft_person_roster（禁第二份 inline 形）。
        if "participant_roster" in draft_res and draft_res.get("participant_roster") is not None:
            content = getattr(session, "content", None)
            if content is not None:
                draft_res["participant_roster"] = normalize_draft_person_roster(
                    draft_res.get("participant_roster"),
                    db=session.db,
                    content=content,
                )
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

        if (
            str(draft_res.get("dossier_action_type") or "") == "grant_allocation"
            and str(draft_res.get("grant_action") or "") == "协饷"
        ):
            draft_res.update(require_materializable_xiexang_payload(
                session.db,
                text=draft_res.get("draft_text"),
                amount=draft_res.get("amount"),
                account=str(draft_res.get("account") or ""),
                purpose=str(draft_res.get("purpose") or ""),
                target_kind=str(draft_res.get("target_kind") or ""),
                target_id=str(draft_res.get("target_id") or ""),
                cadence=str(draft_res.get("cadence") or ""),
            ))
        dossier_cluster = cluster_by_kind(
            str(draft_res.get("dossier_action_type") or "")
        )
        dossier_carriers = tuple(
            spec.name for spec in (dossier_cluster.fields if dossier_cluster else ())
        )
        # execution_surface 仅 grant FieldSpec→dossier_carriers 投影，禁通用透传（#1624）。
        mechanical_fields = (
            "dossier_action_type", "target_kind", "target_id", "mode",
            "assignee",
            "deadline_months", "punish_action", "locality_scope",
            # #653：pay_order_override 结构化载荷随拟旨草案整道入 staging payload。
            "entries",
            # #658：御笔强推 target 须随对话拟旨 staging 完整保留，禁第二案卷。
            "target_dossier_id",
        ) + dossier_carriers
        for field_name in mechanical_fields:
            if draft_res.get(field_name) not in (None, ""):
                semantic_payload[field_name] = draft_res[field_name]
        # #568：点策 origin 走既有 source_chat_turn_id 填值路径（directive 成案消费）
        try:
            origin_pin = int(draft_res.get("source_chat_turn_id") or 0)
        except (TypeError, ValueError):
            origin_pin = 0
        if origin_pin > 0:
            semantic_payload["source_chat_turn_id"] = origin_pin
        if isinstance(draft_res.get("participant_roster"), list):
            semantic_payload["participant_roster"] = draft_res["participant_roster"]
        # #1624：召对拟旨走共同契约组装（不按 target_kind 覆盖已给 locality）
        if semantic_payload.get("target_kind") not in (None, ""):
            assembled = assemble_structured_decree(
                semantic_payload,
                conn=getattr(session.db, "conn", None),
                regions_content=getattr(
                    getattr(session, "content", None), "regions", None,
                ),
                validate=True,
            )
            apply_assembled_to_payload(semantic_payload, assembled)
        # #658：纯强推不得 setdefault 普通 triad，否则混载触发互斥拒收 / 造第二案卷
        from ming_sim.db import classify_directive_structured_kind
        if not is_existing_update and classify_directive_structured_kind(
            semantic_payload,
        ) != "push":
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


def _structured_appointment_from_ctx(ctx: MaterializeCtx) -> Optional[Dict[str, Any]]:
    """P5：先读结构化 intent / multi 候选，有则免 LLM 抽取。

    返回 appointment 形 dict（含 appoint_action/name/office…）；无可复用结构返 None。
    注意：None 在「分类器/预分类已跑且无 appointment」与「分类器未跑」两种语义下
    均可能出现——调用方须用 intent/candidates 是否非 None 区分，见 parallel。
    """
    intent = ctx.intent
    if isinstance(intent, dict) and str(intent.get("kind") or "") == "appointment":
        return dict(intent)
    if isinstance(intent, dict):
        action = str(intent.get("appoint_action") or "").strip()
        if action in {"任命", "罢免"}:
            return dict(intent)
    for candidate in ctx.intent_candidates or []:
        if not isinstance(candidate, dict):
            continue
        if str(candidate.get("kind") or "") == "appointment":
            return dict(candidate)
        action = str(candidate.get("appoint_action") or "").strip()
        if action in {"任命", "罢免"}:
            return dict(candidate)
    return None


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


def _apply_existing_appointment_hit(
    session: Any,
    row: Dict[str, Any],
    *,
    mode_mark: Optional[str] = None,
    tenure_mark: Optional[str] = None,
    minister_name: str = "",
    turn: int = 0,
    person_name: str = "",
    summon_after: bool = False,
    origin_chat_turn_id: int = 0,
    annotate: bool = False,
) -> int:
    """Existing-hit merge: path marks + optional summon under one atomic.

    mode/任别、路径故事账、summon_after 升格与 inactive origin 同成同败——
    不得先 annotate 真提交再进 summon 自己的 atomic。
    """
    from ming_sim.applier import atomic

    with atomic(session.db):
        resolved = int(row["id"])
        if annotate:
            pending_id = _annotate_office_pending_path(
                session.db,
                row,
                mode_mark=mode_mark,
                tenure_mark=tenure_mark,
                minister_name=minister_name,
                turn=turn,
            )
            if pending_id:
                resolved = int(pending_id)
        if summon_after and person_name:
            _persist_appointment_summon(
                session,
                resolved,
                person_name,
                promote_payload=True,
                origin_chat_turn_id=int(origin_chat_turn_id or 0),
            )
        return resolved


def _stage_office_pending_core(
    ctx: MaterializeCtx,
    appt: Dict[str, Any],
    *,
    mode_mark: Optional[str] = None,
    tenure_mark: Optional[str] = None,
    annotate_existing: bool = False,
    require_office_for_appoint: bool = False,
    write_primary_pending_id: bool = True,
) -> Optional[int]:
    """#1380 DRY：_materialize_appointment 与 parallel 旁路共用 hedge/去重/落库。

    返回 pending id；对冲 no-op / 字段不全返 None。
    annotate_existing：主路径对既有同向任命并入路径标记。
    require_office_for_appoint：parallel 任命必须带职名。
    write_primary_pending_id：主路径写 out['pending_action_id']；parallel 不覆盖 directive id。
    """
    from ming_sim.applier import atomic
    from ming_sim.cli_backend import resolve_directive_mode
    from ming_sim.session import (
        _appointment_intent_is_current_office_noop,
        _cancel_staged_opposing_office,
        _canonical_minister_key,
        _target_active_officeholder,
    )

    session = ctx.session
    minister_name = ctx.character.name

    def persist_appointment_summon(
        pending_id: int, person_name: str, *, promote_payload: bool,
    ) -> None:
        _persist_appointment_summon(
            session, pending_id, person_name,
            promote_payload=promote_payload,
            origin_chat_turn_id=int(ctx.chat_turn_id or 0),
        )

    content_ref = getattr(session, "content", None)
    action = str(appt.get("appoint_action") or "").strip()
    appt_name = str(appt.get("name") or "").strip()
    appt_office = str(appt.get("office") or "").strip()
    # FieldSpec 「任命后传召」：仅任命可承载；罢免组合收敛为无传召。
    want_summon = (
        action == "任命"
        and str(appt.get("summon_after") or "否").strip() == "是"
    )

    if action not in {"任命", "罢免"} or not appt_name:
        return None
    if action == "任命" and require_office_for_appoint and not appt_office:
        return None

    # #519 同人同职 no-op 去重：仅对同向「任命」pending 并入，不双落。
    if action == "任命" and appt_name:
        existing_hits = [
            r for r in _match_office_row_by_name_office(
                _list_pending_office_rows(
                    session.db, int(session.state.turn),
                    pend_for_minister=ctx.pend_for_minister,
                ),
                name=appt_name,
                office=appt_office,
                content=content_ref,
                db=session.db,
            )
            if str(r.get("action") or "") == "任命"
        ]
        if len(existing_hits) == 1:
            resolved = _apply_existing_appointment_hit(
                session,
                existing_hits[0],
                mode_mark=mode_mark,
                tenure_mark=tenure_mark,
                minister_name=minister_name,
                turn=int(session.state.turn),
                person_name=appt_name,
                summon_after=want_summon,
                origin_chat_turn_id=int(ctx.chat_turn_id or 0),
                annotate=annotate_existing,
            )
            if write_primary_pending_id:
                ctx.out["pending_action_id"] = resolved
            return resolved

    if action == "任命":
        hedged = _cancel_staged_opposing_office(
            session.db, "罢免", appt_name, int(session.state.turn),
            content=content_ref,
        )
        if hedged:
            return None
        # 现职 no-op 只豁免重复官职写；同句 summon_after 仍须落单一 pending/origin。
        current_office_noop = _appointment_intent_is_current_office_noop(
            session.db, appt_name, appt_office or appt.get("office", ""),
            content=content_ref,
        )
        if current_office_noop and not want_summon:
            return None
        if current_office_noop:
            canonical_name = _canonical_minister_key(content_ref, appt_name, session.db)
            current_row = session.db.conn.execute(
                "SELECT office FROM characters WHERE name=?", (canonical_name,),
            ).fetchone()
            appt_office = str(current_row["office"] or "").strip()
    elif action == "罢免":
        cancelled = _cancel_staged_opposing_office(
            session.db, "任命", appt_name, int(session.state.turn),
            content=content_ref,
        )
        if cancelled and not _target_active_officeholder(
            session.db, appt_name, content=content_ref,
        ):
            return None

    payload = {
        "name": appt_name,
        "office": appt_office,
        "appointer": minister_name,
        "mode": resolve_directive_mode(ctx.player_message, appt.get("mode")),
        "summon_after": "是" if want_summon else "否",
    }
    # 署理等任别随新建候选写入；特旨仅 mode（上已 resolve）
    if tenure_mark == "署理":
        payload["任别"] = "署理"
    else:
        tenure = str(
            appt.get("appointment_tenure") or appt.get("任别") or ""
        ).strip()
        if tenure in {"真除", "署理", "兼署", "加衔"}:
            payload["任别"] = tenure
    with atomic(session.db):
        pending_id = session.db.stage_pending_action(
            session.state.turn, kind="office", action=action,
            minister_name=minister_name, target_id=None,
            payload=payload,
        )
        if not pending_id:
            return None
        resolved = int(pending_id)
        if want_summon:
            persist_appointment_summon(
                resolved, appt_name, promote_payload=False,
            )
    if write_primary_pending_id:
        ctx.out["pending_action_id"] = resolved
    return resolved


def parallel_stage_office_from_appointment_intent(ctx: MaterializeCtx) -> Optional[int]:
    """#1380 处方 A：拟旨通道并行 stage kind=office。

    仅作用于非前缀（explicit_prefixed=False）的分类/串行拟旨路。
    前缀「拟旨如下」任免走随诏 extractor office_changes（#344 US3 / ADR 0028）。
    P5 三态：
      1) intent/candidates 含 appointment 结构 → 用之，禁 LLM；
      2) 分类器/预分类已跑（intent 或 candidates 非 None）且无 appointment
         → 结构化缺席即定论，禁 LLM（#568 strategy_selection 等）；
      3) 分类器未跑（二者皆 None）→ 才允许 extract_appointment_action。
    multi 已含 appointment 时主路径 _materialize_appointment 先落库；本缝以
    实时 DB 去重并入，禁因 pend_for_minister 快照过期而双 stage（#515/#519）。
    无任免意图 → 不写 office（负向契约）。返回新建/并入的 pending id；无动作返回 None。
    """
    from ming_sim.cli_backend import extract_appointment_action

    # 前缀路零 LLM（#344 US3）——调用方亦应闸，此处双保险
    if ctx.explicit_prefixed:
        return None
    # 主路径 appointment 单项物化中；禁本缝重复
    if ctx.intent_kind == "appointment":
        return None

    # P5：结构化优先
    appt = _structured_appointment_from_ctx(ctx)
    if appt is None:
        # 分类器/预分类已给出结构化产物且无 appointment → 不得补串行抽取
        # （#568 点策 draft/strategy_selection 本就有结构，禁 must-not-call 违约）
        has_structure = ctx.intent is not None or ctx.intent_candidates is not None
        if has_structure:
            return None
        appt = extract_appointment_action(
            ctx.player_message, ctx.reply, llm_config=ctx.llm_config,
        )

    # 去重读实时 DB：同回合主路径刚 stage 的 office 不在 apply 入口 pend 快照里
    stage_ctx = replace(ctx, pend_for_minister=None)
    return _stage_office_pending_core(
        stage_ctx, appt,
        require_office_for_appoint=True,
        write_primary_pending_id=False,
    )


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
    emperor_text: object = None,
    extracted_mode: object = None,
    amount: object = 0,
    transaction_category: object = "",
    backing_dossier_id: object = None,
    issue_id: object = None,
    issue_disposition: object = None,
    pend_for_minister: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Shared punishment candidate write: mode + same-target update."""
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

    mode = resolve_directive_mode(emperor_text, extracted_mode, existing_mode)
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
    disposition = str(intent.get("issue_disposition") or "").strip()
    if disposition not in issue_dispositions_allowed() and (
        not target_id or punish_action not in punish_actions_effective()
    ):
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
        transaction_category=intent.get("transaction_category"),
        backing_dossier_id=intent.get("backing_dossier_id"),
        issue_id=intent.get("issue_id"),
        issue_disposition=intent.get("issue_disposition"),
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
    "无", "赏赉", "发内帑", "加衔", "荫叙", "赈灾", "招抚屯田", "项目经费", "协饷",
})
GRANT_HONORIFICS = frozenset({"加衔", "荫叙"})
GRANT_MONEY_ACTIONS = GRANT_ACTIONS - {"无"} - GRANT_HONORIFICS
XIEXIANG_TARGET_KINDS = frozenset({"army"})


def _grant_shape_value_error(message: str, *, field: str) -> ValueError:
    """ValueError carrying the failed shape field; callers catching ValueError unchanged."""
    exc = ValueError(message)
    exc.field = field  # type: ignore[attr-defined]
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
                f"grant 非法 account：{raw_account!r}", field="account",
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
    if not ga:
        raise _grant_shape_value_error(
            "grant_allocation 缺 grant_action", field="grant_action",
        )
    if ga not in (GRANT_ACTIONS - {"无"}):
        raise _grant_shape_value_error(
            f"grant 非法 grant_action：{ga!r}", field="grant_action",
        )
    resolved_account = resolve_grant_account(grant_action=ga, account=account)
    out: Dict[str, Any] = {"grant_action": ga, "account": resolved_account}
    if ga in GRANT_HONORIFICS:
        return out
    if amount is None or amount == "":
        raise _grant_shape_value_error("grant 金钱缺正 amount", field="amount")
    # #1716：整数字符串是 classifier/LLM 运输常态（#658 normalize raw 直达本边界）；bool/float 仍拒。
    # #1620 原 accept_numeric_strings=False 把 "8" 一并拒掉，拟旨 grant 物化中断、pending 零落。
    try:
        amt = strict_int(amount, accept_numeric_strings=True)
    except ValueError as exc:
        raise _grant_shape_value_error(
            f"grant 金钱 amount 须为正整数，拒 {amount!r}", field="amount",
        ) from exc
    if amt <= 0:
        raise _grant_shape_value_error("grant 金钱缺正 amount", field="amount")
    out["amount"] = amt
    return out


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
    def __init__(self, missing_fields: list) -> None:
        fields = tuple(missing_fields)
        self.missing_fields = fields  # compatibility projection for existing callers
        super().__init__(
            "拨饷旨意缺少结构化字段：" + "/".join(missing_fields) + "（不猜散文）",
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

    missing: list = []
    try:
        n = strict_int(amount, accept_numeric_strings=False)
    except ValueError:
        n = 0
    if n <= 0:
        missing.append("amount")
    # #1620：太仓→国库唯一权威 resolve_grant_account；此处不再平行 if。
    canonical_account = resolve_grant_account(grant_action="协饷", account=account)
    if canonical_account not in {"国库", "内库"}:
        missing.append("account")
    if str(purpose or "").strip() != "补饷":
        missing.append("purpose")
    canonical_target_kind = str(target_kind or "").strip()
    if canonical_target_kind not in XIEXIANG_TARGET_KINDS:
        missing.append("target_kind")
    if not str(target_id or "").strip():
        missing.append("target_id")
    cadence_value = str(cadence or "").strip()
    if cadence_value and cadence_value not in {"一次性", "每月"}:
        missing.append("cadence")
    if missing:
        raise IncompleteXiexangPayloadError(missing)
    return {
        "amount": n,
        "account": canonical_account,
        "purpose": "补饷",
        "target_kind": canonical_target_kind,
        "target_id": str(target_id).strip(),
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
    body = str(text or "").strip()
    if not body:
        raise DecreeMaterializationValidationError(
            "协饷旨意缺少正文（不猜散文）", failed_fields=("purpose",),
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
    emperor_text: object = None,
    extracted_mode: object = None,
    amount: object = 0,
    account: str = "",
    purpose: str = "",
    cadence: str = "",
    execution_surface: object = None,
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
    if existing_id:
        return db.update_directive_candidate(existing_id, staged)
    return db.stage_directive_candidate(int(turn), minister_name, payload=staged)


def _materialize_grant_allocation(ctx: MaterializeCtx) -> None:
    """暂存恩赏·拨帑案卷；钱粮按 ADR 0055 分流落地。

    #1503：显式拟旨前缀若带 typed grant 候选，仍走本单轨（不再因 explicit_prefixed 早退）。
    draft_staged / 已有 pending 仍互斥，避免与 generic special_decree 双写。
    """
    if (
        ctx.intent_kind != "grant_allocation"
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
    # 协饷缺 target 仍交 stage fail-loud；其它 grant 无目标则无物化。
    if not target_id and grant_action != "协饷":
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
        account=resolve_grant_account(
            grant_action=grant_action,
            account=intent.get("account"),
        ),
        purpose=str(intent.get("purpose") or "").strip(),
        cadence=_grant_cadence(intent),
        # #1624：classifier 已验 execution_surface 交 stage，禁在此静默丢弃。
        execution_surface=intent.get("execution_surface"),
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


def _strategy_selection_origin_turn_id(
    db: Any,
    minister_name: str,
    turn: int,
    *,
    exclude_turn_id: int = 0,
) -> int:
    """#568：点策案卷 origin = 大臣陈策轮（单向新指旧），非皇帝点策轮。

    复用 chat_turns 既有行；禁平行溯源表。优先本夜已落 minister 回话的轮，
    以 turn id 结构化排除当前点策轮（禁 user 文本相等过滤）。
    """
    conn = getattr(db, "conn", None)
    if conn is None:
        return 0
    night_id = 0
    night_getter = getattr(db, "_current_open_night_id", None)
    if callable(night_getter):
        try:
            night_id = int(night_getter() or 0)
        except Exception:
            night_id = 0
    name = str(minister_name or "")
    try:
        exclude_tid = int(exclude_turn_id or 0)
    except (TypeError, ValueError):
        exclude_tid = 0
    # exclude_tid<=0 时用 0 占位：chat_turns.id 自增正整数，t.id <> 0 恒真
    try:
        if night_id > 0:
            row = conn.execute(
                """
                SELECT t.id AS id
                FROM chat_turns t
                WHERE t.night_id = ?
                  AND t.minister_name = ?
                  AND t.undone_at IS NULL
                  AND t.status NOT IN ('failed', 'undone', 'consumed')
                  AND t.minister_message_id IS NOT NULL
                  AND t.minister_message_id > 0
                  AND t.id <> ?
                ORDER BY t.id DESC
                LIMIT 1
                """,
                (int(night_id), name, exclude_tid),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT t.id AS id
                FROM chat_turns t
                WHERE t.turn = ?
                  AND t.minister_name = ?
                  AND t.undone_at IS NULL
                  AND t.status NOT IN ('failed', 'undone', 'consumed')
                  AND t.minister_message_id IS NOT NULL
                  AND t.minister_message_id > 0
                  AND t.id <> ?
                ORDER BY t.id DESC
                LIMIT 1
                """,
                (int(turn), name, exclude_tid),
            ).fetchone()
    except Exception:
        return 0
    if row is None:
        return 0
    tid = int(row["id"] or 0)
    return tid if tid > 0 else 0


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
    stages: object = None,
    target_candidate: object = None,
    transaction_category: object = "",
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
        "mode": mode,
    }
    category = str(transaction_category or "").strip()
    if category:
        staged["transaction_category"] = category
    else:
        # Legacy unclassified assignments retain their explicit audience owner;
        # classified production actions route by the canonical duty table.
        staged["assignee"] = owner
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
    # #620 AC2：生产捕获——结构化 stages / JSON 串 / 正文「三年X五年Y」→ 绝对 due 段表
    # 分层：召对入口对分类器坏形 stages 容错（回落正文年诺）；库层 capture/stages_to_json 仍响亮 ValueError
    from ming_sim.staged_commitment import capture_commitment_stages
    stages_raw = stages if stages not in (None, "") else None
    try:
        stages_norm = capture_commitment_stages(
            stages_raw,
            narrative_text=body,
            origin_turn=int(turn),
        )
    except ValueError:
        stages_norm = capture_commitment_stages(
            None,
            narrative_text=body,
            origin_turn=int(turn),
        )
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
    """暂存交办·责成案卷；initiative 按 ADR 0055 判决后落。

    #1503：显式拟旨前缀若带真实 assignment 候选，仍走本单轨（不再因 explicit_prefixed 早退）。
    """
    if (
        ctx.intent_kind != "assignment"
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
        stages=intent.get("stages"),
        target_candidate=intent.get("target_candidate"),
        transaction_category=intent.get("transaction_category"),
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
    station_region: object = "",
    deadline_months: object = 0,
    due_turn: object = 0,
    office: object = "",
    emperor_text: object = None,
    extracted_mode: object = None,
    target_candidate: object = None,
    transaction_category: object = "",
    pend_for_minister: Optional[List[Dict[str, Any]]] = None,
) -> int:
    """Shared military_order candidate write (#521 / #502).

    收夜只成案卷；station/station_region/office 按 ADR 0055 判后物化。既有军调驻不写 new_armies。
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
    owner = str(assignee or "").strip()

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
        "mode": mode,
    }
    if owner:
        staged["assignee"] = owner
    category = str(transaction_category or "").strip()
    if category:
        staged["transaction_category"] = category
    dest = str(station or "").strip()
    if dest:
        staged["station"] = dest
    dest_region = str(station_region or "").strip()
    if dest_region:
        staged["station_region"] = dest_region
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
    assignee = str(intent.get("name") or intent.get("assignee") or "").strip()
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
        station_region=(
            intent.get("station_region")
            or intent.get("实际驻地")
            or intent.get("驻地省")
        ),
        deadline_months=intent.get("deadline_months"),
        due_turn=intent.get("due_turn"),
        office=intent.get("office"),
        emperor_text=ctx.player_message,
        extracted_mode=intent.get("mode"),
        target_candidate=intent.get("target_candidate"),
        transaction_category=intent.get("transaction_category"),
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


def _authorization_privilege(raw: object) -> str:
    """公开委任默认 privilege=便宜行事；显式四闭集权项原样保留。"""
    from ming_sim.authority_privileges import AUTHORITY_PRIVILEGE_SET

    priv = str(raw or "").strip()
    if priv in {"", "无"}:
        return "便宜行事"
    if priv in AUTHORITY_PRIVILEGE_SET:
        return priv
    return ""


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
    emperor_text: object = None,
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

    mode = resolve_directive_mode(emperor_text, extracted_mode, existing_mode)
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


def _materialize_authorization(ctx: MaterializeCtx) -> None:
    """暂存公开委任授权案卷；authority_changes 授予按 ADR 0055 判决后落。"""
    if (
        ctx.intent_kind != "authorization"
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
    pending_id = stage_authorization_candidate(
        ctx.session.db,
        ctx.session.state.turn,
        ctx.character.name,
        text=body,
        privilege=intent.get("privilege"),
        target_id=intent.get("target_id"),
        target_kind=intent.get("target_kind"),
        scope=intent.get("scope"),
        emperor_text=ctx.player_message,
        extracted_mode=intent.get("mode"),
        target_candidate=intent.get("target_candidate"),
        pend_for_minister=ctx.pend_for_minister,
    )
    if pending_id:
        ctx.out["pending_action_id"] = pending_id


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
    content: Any = None,
    db: Any = None,
) -> List[Dict[str, Any]]:
    """人+职联合匹配；姓名或官职缺一则零命中（禁姓名-only 旁路）。"""
    from ming_sim.session import _canonical_minister_key

    want_name = str(name or "").strip()
    want_office = str(office or "").strip()
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
        hits.append(row)
    return hits


def _select_pending_office_for_path(
    db: Any,
    turn: int,
    *,
    name: str = "",
    office: str = "",
    target_candidate: object = None,
    pend_for_minister: Optional[List[Dict[str, Any]]] = None,
    content: Any = None,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """在本夜 pending 人事候选上选对应条。

    返回 (row|None, status)：hit / ambiguous / miss / 含糊。
    单条直取；多条仅人+职联合唯一命中；禁姓名-only/纯数字 id 旁路；含糊/歧义零改。
    """
    pointed = str(target_candidate or "").strip()
    if pointed == "含糊":
        return None, "含糊"

    rows = _list_pending_office_rows(
        db, turn, pend_for_minister=pend_for_minister,
    )
    # 纯数字 target_candidate 不是人+职联合键：多候选时不得旁路直改。
    # 单条仍走下方直取；多条且无完整人+职 → 歧义零改。

    if not rows:
        return None, "miss"

    want_name = str(name or "").strip()
    want_office = str(office or "").strip()

    if len(rows) == 1:
        # #529：完全省略 name+office 的路径应答 → 唯一候选直取。
        # #672：任一身份字段在场则必须完整人+职联合命中，缺一/错配零改该 row。
        if not want_name and not want_office:
            return rows[0], "hit"
        if not want_name or not want_office:
            return None, "miss"
        hits = _match_office_row_by_name_office(
            rows, name=want_name, office=want_office, content=content, db=db,
        )
        if len(hits) == 1:
            return hits[0], "hit"
        return None, "miss"

    # 多条必须人+职同时在场；缺一（含仅数字 id / 姓名-only）→ 歧义，戏内确认
    if not want_name or not want_office:
        return None, "ambiguous"

    hits = _match_office_row_by_name_office(
        rows, name=want_name, office=want_office, content=content, db=db,
    )
    if len(hits) == 1:
        return hits[0], "hit"
    if len(hits) >= 2:
        return None, "ambiguous"
    # 人+职齐全但 0 命中 → fallback（无对应暂存）
    return None, "miss"


def _office_path_ambiguous_payload(
    db: Any,
    turn: int,
    *,
    pend_for_minister: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """路径应答歧义：统一构造 directive_confirmation_ambiguous 载荷。"""
    return {
        "candidates": [
            {"id": int(r["id"]), "summary": _pending_office_brief(r)}
            for r in _list_pending_office_rows(
                db, int(turn), pend_for_minister=pend_for_minister,
            )
        ],
    }


def _path_marks_from_appt(appt: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """从结构化意图取路径标记：特旨→mode=midzhi；署理→任别=署理。互不写对方字段。"""
    mode_mark: Optional[str] = None
    raw_mode = str(appt.get("mode") or "").strip()
    if raw_mode == "midzhi":
        mode_mark = "midzhi"

    tenure_mark: Optional[str] = None
    for key in ("appointment_tenure", "任别"):
        if key not in appt:
            continue
        raw = appt.get(key)
        if raw is None:
            continue
        val = str(raw).strip()
        if val == "署理":
            tenure_mark = "署理"
        break
    return mode_mark, tenure_mark


def _annotate_office_pending_path(
    db: Any,
    row: Dict[str, Any],
    *,
    mode_mark: Optional[str] = None,
    tenure_mark: Optional[str] = None,
    minister_name: str = "",
    turn: int = 0,
) -> int:
    """原地改写 office pending：特旨只写 mode；署理只写 任别。返回 pending id。"""
    if not mode_mark and not tenure_mark:
        return 0
    pending_id = int(row["id"])
    payload = dict(_office_payload(row))
    changed = False
    if mode_mark == "midzhi" and payload.get("mode") != "midzhi":
        payload["mode"] = "midzhi"
        changed = True
    if tenure_mark == "署理" and payload.get("任别") != "署理":
        payload["任别"] = "署理"
        payload.pop("appointment_tenure", None)
        changed = True
    if not changed and (
        (mode_mark == "midzhi" and payload.get("mode") == "midzhi")
        or (tenure_mark == "署理" and payload.get("任别") == "署理")
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


def _materialize_appointment(ctx: MaterializeCtx) -> None:
    from ming_sim.cli_backend import extract_appointment_action

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
        appt = (
            intent if intent_kind == "appointment"
            else {"appoint_action": "无", "name": "", "office": ""}
        )
    else:
        appt = extract_appointment_action(
            ctx.player_message, ctx.reply, llm_config=ctx.llm_config)

    content_ref = getattr(session, "content", None)
    mode_mark, tenure_mark = _path_marks_from_appt(appt)
    appt_name = str(appt.get("name") or "").strip()
    appt_office = str(appt.get("office") or "").strip()
    target_candidate = appt.get("target_candidate")

    # #529 路径应答：特旨/署理在既有 pending 人事候选上原地改；歧义零改。
    if mode_mark or tenure_mark:
        if str(target_candidate or "").strip() == "含糊":
            ctx.out["directive_confirmation_ambiguous"] = _office_path_ambiguous_payload(
                session.db,
                int(session.state.turn),
                pend_for_minister=ctx.pend_for_minister,
            )
            return
        row, status = _select_pending_office_for_path(
            session.db,
            int(session.state.turn),
            name=appt_name,
            office=appt_office,
            target_candidate=target_candidate,
            pend_for_minister=ctx.pend_for_minister,
            content=content_ref,
        )
        if status in {"ambiguous", "含糊"}:
            ctx.out["directive_confirmation_ambiguous"] = _office_path_ambiguous_payload(
                session.db,
                int(session.state.turn),
                pend_for_minister=ctx.pend_for_minister,
            )
            return
        incoming_action = str(appt.get("appoint_action") or "").strip()
        row_action = str(row.get("action") or "").strip() if row is not None else ""
        if (
            status == "hit" and row is not None
            and (incoming_action == "无" or incoming_action == row_action)
        ):
            # 路径只并入同向 action；反向任免继续走下方既有 staging/对冲管线。
            # 同人同职再发任命+路径：no-op 去重，中旨/任别/summon 并入既有条。
            # path-only 省略 name 时从命中 row payload 取 canonical 人名，走共享 summon tail。
            person_for_summon = appt_name or str(
                _office_payload(row).get("name") or ""
            ).strip()
            row_is_appoint = str(row.get("action") or "") == "任命"
            resolved = _apply_existing_appointment_hit(
                session,
                row,
                mode_mark=mode_mark,
                tenure_mark=tenure_mark,
                minister_name=minister_name,
                turn=int(session.state.turn),
                person_name=person_for_summon,
                summon_after=(
                    str(appt.get("summon_after") or "否").strip() == "是"
                    and bool(person_for_summon)
                    and row_is_appoint
                    and str(appt.get("appoint_action") or "").strip() != "罢免"
                ),
                origin_chat_turn_id=int(ctx.chat_turn_id or 0),
                annotate=True,
            )
            ctx.out["pending_action_id"] = resolved
            # 路径命中后：若本轮仍是完整任命语义且已并入，不再新建第二候选
            if appt.get("appoint_action") in ("任命", "罢免") and appt_name:
                same = _match_office_row_by_name_office(
                    [row], name=appt_name, office=appt_office,
                    content=content_ref, db=session.db,
                )
                if same or not appt_name:
                    return
            else:
                return
        # miss：无对应暂存 → fallback 走下方普通人事管线（需完整任命字段）

    # #519/#504/#1380：同人同职去重 + 对冲 + 落库 —— 与 parallel 共用 helper
    _stage_office_pending_core(
        ctx, appt,
        mode_mark=mode_mark,
        tenure_mark=tenure_mark,
        annotate_existing=True,
        write_primary_pending_id=True,
    )


def _pending_office_brief(row: Dict[str, Any]) -> str:
    payload = _office_payload(row)
    name = str(payload.get("name") or "").strip()
    office = str(payload.get("office") or "").strip()
    action = str(row.get("action") or "").strip()
    if name and office:
        return f"{action}{name}为{office}" if action else f"{name}/{office}"
    return name or office or f"pending:{row.get('id')}"


def _materialize_prohibit_covert_levy(ctx: MaterializeCtx) -> None:
    """Bind natural language to the one exposed case currently before the throne."""
    if ctx.intent_kind != "prohibit_covert_levy" or not ctx.intent:
        return
    from ming_sim.audience_night import mark_actions_night_approved
    from ming_sim.covert_levy import PROHIBITION_ACTION
    from ming_sim.due_review import current_audience_scene

    scene = current_audience_scene(ctx.session.db, ctx.session.state)
    if scene is None or scene.get("kind") != "covert_levy_exposure" or scene.get("decision"):
        return
    dossier_id = int(scene["dossier_id"])
    payload = {
        "text": ctx.player_message.strip(),
        "actor": str(ctx.character.name),
        "dossier_action_type": PROHIBITION_ACTION,
        "target_kind": "dossier",
        "target_id": str(dossier_id),
        "mode": "ordinary",
    }
    pending_id = ctx.session.db.stage_directive_candidate(
        int(ctx.session.state.turn), str(ctx.character.name), payload=payload,
    )
    mark_actions_night_approved(ctx.session.db, [pending_id])
    ctx.out["pending_action_id"] = pending_id


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
                    # #1376：修改=原地更新同一 pending 候选内容（owner 既裁）
                    frozenset({"应允", "拒绝", "留中", "修改", "无"}), "无",
                ),
                # #1376：修改判词携带 typed 新内容——唯一权威正文，禁从 player_message 散文裁剪
                FieldSpec("new_content", "新内容", None, ""),
                FieldSpec("target_ids", "目标编号", None, []),
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
                FieldSpec("new_content", "新内容", None, ""),
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
            "禁绝暗渠摊派", "prohibit_covert_levy", EFFECT_MATERIALIZE, priority=54,
            fields=(),
            materialize_fn=_materialize_prohibit_covert_levy,
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
                FieldSpec(
                    "transaction_category", "事务类别",
                    duty_route_categories(), "",
                ),
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
                # #620 扩展面：分段里程碑（不改 #520 本体字段语义）
                FieldSpec("stages", "分段里程碑", None, "", max_len=2000),
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
                    GRANT_ACTIONS, "无", season_option=True,
                ),
                FieldSpec("name", "姓名", None, "", max_len=20),
                # 政务拨款对象：赈灾地区 / 项目 / 协饷军队 / 恩赏人物
                FieldSpec(
                    "target_id", "目标", None, "", max_len=80,
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
                # 明确改草指向：分类归一化须保留，供 stage 只更新点名候选
                FieldSpec("target_candidate", "目标候选", None, "", max_len=40),
            ),
            materialize_fn=_materialize_grant_allocation,
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
                FieldSpec("target_id", "目标", None, "", max_len=80),
                FieldSpec("target_candidate", "目标候选", None, "", max_len=40),
                FieldSpec(
                    "mode", "颁布方式",
                    frozenset({"ordinary", "midzhi"}), "",
                ),
            ),
            materialize_fn=_materialize_authorization,
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
                FieldSpec("name", "姓名", None, "", max_len=20),
                # 与 pacification/grant_allocation 共享 target_id 中文键（#518 契约）
                FieldSpec("target_id", "目标", None, "", max_len=80),
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
            materialize_fn=_materialize_punishment,
        ),
        ActionCluster(
            "军令·调遣", "military_order", EFFECT_MATERIALIZE, priority=59,
            fields=(
                # 与 grant/pacification 共享 target_id：既有军队稳定 id
                FieldSpec("target_id", "目标", None, "", max_len=80),
                FieldSpec(
                    "transaction_category", "事务类别",
                    duty_route_categories(), "",
                ),
                # 承办人 / 责任军将（admission 映 assignee_id）
                FieldSpec("name", "姓名", None, "", max_len=20),
                FieldSpec("station", "驻地", None, "", max_len=80),
                # #659：结构化实际驻地=regions.id；与 station 双写，不改饷源
                FieldSpec("station_region", "驻地省", None, "", max_len=40),
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
                FieldSpec("target_candidate", "目标候选", None, "", max_len=40),
            ),
            materialize_fn=_materialize_appointment,
        ),
    )


install_action_catalog(_build_catalog())
