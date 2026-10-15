"""案卷落库段：执行格终值（``dossier_executions``）与两路名册（participants）。

两路名册**字段名即来源**，权威集合分开不合并（#1252：公开案卷名册与密令案卷名册
是两个来源通道，不是并集）。授权 fail-closed：不在本批可见输入闭集内的案卷
名册拒收。
"""

from __future__ import annotations
from ming_sim.exceptions import DeclarationDataError

from typing import List

from ming_sim.applier import RejectedItem, SectionResult, reject_item


def apply_participants(run):
    from ming_sim.entities.dossier.apply import apply_dossier_participant_items

    rows, rejections = apply_dossier_participant_items(
        run.db, run.state, run.current_extracted,
        source=run.ctx.source,
        items_key="dossier_participants",
        authority_set=run.ctx.dossier_ids_at_input,
        not_in_batch_msg="案卷不在本批可见输入",
    )
    return SectionResult(applied=rows, rejected=rejections)


def apply_secret_dossier_participants(run):
    from ming_sim.entities.dossier.apply import apply_dossier_participant_items

    rows, rejections = apply_dossier_participant_items(
        run.db, run.state, run.current_extracted,
        source=run.ctx.source,
        items_key="secret_dossier_participants",
        authority_set=run.ctx.secret_dossier_ids_at_input,
        not_in_batch_msg="密令案卷不在本批可见输入",
    )
    return SectionResult(applied=rows, rejected=rejections)


def apply_executions(run):
    """执行格终值：模型声明经本段正式写格。

    #1835 J18：到期复核只供事实/场面，不排斥模型终值；终值唯一真源＝本声明写口。
    """
    from ming_sim.db import GameDB
    from ming_sim.strict_types import _parse_sqlite_id

    applied: List[object] = []
    rejected: List[RejectedItem] = []
    source = run.ctx.source

    for item in run.current_extracted.get("dossier_executions") or []:
        if not isinstance(item, dict):
            reject_item(rejected, item, "执行格须为对象", "invalid_shape", source)
            continue
        try:
            dossier_id = _parse_sqlite_id(item.get("dossier_id"))
            outcome = str(item.get("outcome") or "").strip()
            if outcome not in {"fulfilled", "degraded", "failed", "transformed"}:
                raise ValueError("执行结果必须为 fulfilled/degraded/failed/transformed")
            note = item.get("note")
            note = note if isinstance(note, str) else str(note or "")
            if not note.strip():
                raise ValueError("执行说明不能为空")
            has_parties = "affected_parties" in item
            raw_parties = item["affected_parties"] if has_parties else None
        except (TypeError, ValueError, KeyError) as exc:
            reject_item(rejected, item, str(exc), "invalid_transition", source)
            continue
        dossier = run.db.dossiers.get(dossier_id)
        if dossier is None or dossier["status"] != "executing":
            reject_item(rejected, item, "案卷不存在或不在 executing", "invalid_transition", source)
            continue
        if raw_parties is not None and outcome in GameDB._JOINT_LIABILITY_TRIGGERS:
            try:
                run.db.validate_joint_liability_affected_parties(raw_parties, outcome)
            except DeclarationDataError as exc:
                reject_item(rejected, item, str(exc), "invalid_transition", source)
                continue
        run.db.dossiers.record_execution(
            dossier_id, outcome, note, run.state.turn, close=True, commit=False,
        )
        # #1900：对账金额落 reconciliations 结构化行；不向 execution_note 灌核账模板。
        # 连坐挂载点＝本段落终值笔；禁对 execution_outcome 列事后扫描。
        # 人物奏报只经模型声明/既有存储写入，执行格不代写奏报行。
        run.db.apply_execution_joint_liability(
            run.state, dossier_id, outcome, reason=note, commit=False,
        )
        applied.append({
            "dossier_id": dossier_id,
            "outcome": outcome,
            "source_item": item,
        })
    return SectionResult(applied=applied, rejected=rejected)


def apply_deliberation_outcomes(run):
    """#1917：过月转译声明廷议结果——无人站台标 stalled，原案待裁。

    人物肯不肯站台归推演 LLM；本段只记录声明、不代判。
    """
    from ming_sim.strict_types import _parse_sqlite_id

    applied: List[object] = []
    rejected: List[RejectedItem] = []
    source = run.ctx.source

    from ming_sim.simulation import _canonical_item_fields

    for raw_item in run.current_extracted.get("deliberation_outcomes") or []:
        if not isinstance(raw_item, dict):
            reject_item(rejected, raw_item, "廷议声明须为对象", "invalid_shape", source)
            continue
        item = _canonical_item_fields(raw_item)
        try:
            dossier_id = _parse_sqlite_id(item.get("dossier_id"))
            outcome = str(item.get("outcome") or "").strip()
            if outcome != "stalled":
                raise ValueError("廷议结果只收 stalled")
            note = item.get("note")
            note = note if isinstance(note, str) else str(note or "")
            if not note.strip():
                raise ValueError("廷议说明不能为空")
        except (TypeError, ValueError) as exc:
            reject_item(rejected, raw_item, str(exc), "invalid_transition", source)
            continue
        dossier = run.db.dossiers.get(dossier_id)
        status = str((dossier or {}).get("status") or "")
        # #1917 runner 裁定（二）：先答效果可已颁/执行；后道 stalled 转待裁，不回滚已落。
        # ADR0055：密令绕外廷，不入无人站台待裁。
        if (
            dossier is None
            or status not in {"proposed", "promulgated", "executing"}
            or dossier.get("secret_order_id")
        ):
            reject_item(
                rejected, raw_item, "无人站台只接原案", "invalid_transition", source,
            )
            continue
        payload = dict(dossier.get("payload") or {})
        if str(payload.get("deliberation_state") or "") == "stalled":
            applied.append({
                "dossier_id": dossier_id, "outcome": "stalled", "source_item": item,
            })
            continue
        payload["deliberation_state"] = "stalled"
        if note.strip() and not str(payload.get("deliberation_note") or "").strip():
            payload["deliberation_note"] = note
        if status != "proposed":
            # 记拨回前状态，强推恢复办理时不重放载荷（#1917 C1）。
            payload["_pre_stall_status"] = status
        run.db.dossiers.update_payload(dossier_id, payload, commit=False)
        if status != "proposed":
            # 回 proposed 仅供待裁案头；已落效果不动。
            run.db.conn.execute(
                "UPDATE decree_dossiers SET status='proposed', "
                "updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (int(dossier_id),),
            )
        origin = f"dossier:{dossier_id}"
        # 廷议局势身份＝origin_kind=deliberation + origin_ref；不与同 ref 国策/承诺混同。
        existing = run.db.issues.by_origin("deliberation", origin)
        if existing is None:
            title = str(dossier.get("decree_text") or "").strip() or note.strip() or "无人站台原案"
            run.db.insert_issue(
                run.state,
                kind="situation",
                title=title[:80],
                origin_kind="deliberation",
                origin_ref=origin,
                stage_text=note,
                commit=False,
            )
        elif str(existing["status"] or "") != "active":
            # 再次待裁：重开局势，保留历史 resolved 记录语义由 status 翻转承接。
            run.db.conn.execute(
                "UPDATE issues SET status='active', stage_text=COALESCE(?, stage_text) "
                "WHERE id=?",
                (note.strip() or None, int(existing["id"])),
            )
        applied.append({
            "dossier_id": dossier_id, "outcome": "stalled", "source_item": item,
        })
    return SectionResult(applied=applied, rejected=rejected)
