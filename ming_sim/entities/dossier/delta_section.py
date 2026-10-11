"""案卷落库段：执行格终值（``dossier_executions``）与两路名册（participants）。

两路名册**字段名即来源**，权威集合分开不合并（#1252：公开案卷名册与密令案卷名册
是两个来源通道，不是并集）。授权 fail-closed：不在本批可见输入闭集内的案卷
名册拒收。
"""

from __future__ import annotations
from ming_sim.exceptions import DeclarationDataError

from typing import List

from ming_sim.applier import RejectedItem, SectionResult


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

    def _refuse(item: object, reason: str, category: str = "invalid_transition") -> None:
        rejected.append(RejectedItem(
            item=item if isinstance(item, dict) else {"raw_value": item},
            reason=reason,
            category=category,
            source=source,
        ))

    for item in run.current_extracted.get("dossier_executions") or []:
        if not isinstance(item, dict):
            _refuse(item, "执行格须为对象", "invalid_shape")
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
            _refuse(item, str(exc))
            continue
        dossier = run.db.get_decree_dossier(dossier_id)
        if dossier is None or dossier["status"] != "executing":
            _refuse(item, "案卷不存在或不在 executing")
            continue
        if raw_parties is not None and outcome in GameDB._JOINT_LIABILITY_TRIGGERS:
            try:
                run.db.validate_joint_liability_affected_parties(raw_parties, outcome)
            except DeclarationDataError as exc:
                _refuse(item, str(exc))
                continue
        run.db.record_dossier_execution(
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
