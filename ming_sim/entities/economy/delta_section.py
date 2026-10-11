"""经济条目（``economy_moves``）落库段。

同批合法项照落（ADR 0015 逐项拒收）。归属（``origin_ref``）非法是**窄**的
授权失败——只接 ``UnauthorizedAffairOriginRef``，且只包在写前的归属解析上。
条目核在写前返回拒收。代码故障由外层事务回滚（ADR 0005）。
"""

from __future__ import annotations

from ming_sim.applier import RejectedItem

from typing import List

from ming_sim.applier import SectionResult


def apply(run, moves: List[object] | None = None) -> SectionResult:
    """落 ``economy_moves``。

    ``moves`` 缺省读当前笔的 ``economy_moves``。本段不再自建 savepoint。
    """
    from ming_sim.entities.affair import UnauthorizedAffairOriginRef
    from ming_sim.entities.economy.apply import _apply_economy_list
    from ming_sim.entities.authority.apply import _payload_owned_dossier_for_origin

    if moves is None:
        moves = list(run.current_extracted.get("economy_moves") or [])

    rows: List[object] = []
    rejections: List[RejectedItem] = []
    for raw_move in moves:
        move = raw_move
        origin_ref = ""
        if isinstance(move, dict):
            try:
                origin_ref = run.origin_ref_from_result_item(move)
            except UnauthorizedAffairOriginRef as exc:
                rejections.append(RejectedItem(item=raw_move, reason=str(exc), category="invalid_enum", source=run.ctx.source))
                continue
            if origin_ref and not str(
                move.get("origin_ref") or move.get("来源引用") or ""
            ).strip():
                move["origin_ref"] = origin_ref
            if origin_ref.startswith("dossier:"):
                dossier = _payload_owned_dossier_for_origin(run.db, origin_ref)
                if dossier is not None and str(
                    dossier.get("action_type") or ""
                ) == "grant_allocation":
                    # 拨款单轨已有唯一承载（#1503），重复申报不认。
                    continue
        results, refused = _apply_economy_list(
            run.db, run.state, [move], require_origin=True, source=run.ctx.source,
        )
        if refused:
            rejections.extend(refused)
        else:
            rows.extend(results)
    return SectionResult(applied=rows, rejected=rejections)
