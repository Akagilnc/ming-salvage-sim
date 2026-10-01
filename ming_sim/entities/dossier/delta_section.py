"""案卷落库段：执行格终值（``dossier_executions``）与两路名册（participants）。

两路名册**字段名即来源**，权威集合分开不合并（#1252：公开案卷名册与密令案卷名册
是两个来源通道，不是并集）。授权 fail-closed：不在本批可见输入闭集内的案卷
名册拒收。
"""

from __future__ import annotations

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
    """执行格终值。

    #621 接管窗：正式复核所辖案卷禁并行终值（防第二真源）；所有权查询失败须
    响亮上抛，不得 fail-open 成空集放行（ADR 0005 / 0076）。
    """
    from ming_sim.db import GameDB
    from ming_sim.due_review import dossiers_with_pending_due_review
    from ming_sim.issues import _parse_sqlite_id, terminal_report_facade

    applied: List[object] = []
    rejected: List[RejectedItem] = []
    source = run.ctx.source
    due_review_owned = dossiers_with_pending_due_review(run.db, run.state)

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
        if int(dossier_id) in due_review_owned:
            _refuse(item, "正式复核接管：extractor 不得并行写执行格终值")
            continue
        dossier = run.db.get_decree_dossier(dossier_id)
        if dossier is None or dossier["status"] != "executing":
            _refuse(item, "案卷不存在或不在 executing")
            continue
        if raw_parties is not None and outcome in GameDB._JOINT_LIABILITY_TRIGGERS:
            try:
                run.db.validate_joint_liability_affected_parties(raw_parties, outcome)
            except ValueError as exc:
                _refuse(item, str(exc))
                continue
        run.db.record_dossier_execution(
            dossier_id, outcome, note, run.state.turn, close=True, commit=False,
        )
        # #567：S10 结案同源读被护侧对账，经 merge_execution_note 增补（单写口）。
        run.db.merge_grant_reconciliation_into_execution_note(dossier_id, commit=False)
        # #619/#622：表报终值旁路——仅 degraded/transformed 挂奏报行；
        # 变形案载承办人假象（不得回填判官真值）。
        if outcome in {"degraded", "transformed"}:
            prior = list(run.db.list_dossier_progress(int(dossier_id)))
            band, memorial = terminal_report_facade(outcome, prior_reports=prior)
            run.db.record_dossier_progress(
                dossier_id, run.state.turn, band, memorial,
                is_terminal=True,
                origin=GameDB.DOSSIER_REPORT_ORIGIN_VERDICT,
                commit=False,
            )
        # 连坐挂载点＝本段落终值笔；禁对 execution_outcome 列事后扫描。
        run.db.apply_execution_joint_liability(
            run.state, dossier_id, outcome, reason=note, commit=False,
        )
        applied.append({
            "dossier_id": dossier_id,
            "outcome": outcome,
            "source_item": item,
        })
    return SectionResult(applied=applied, rejected=rejected)
