"""密令推演副作用段（``secret_order_updates``）。

写 active 密令的推演副作用（泄漏/反弹）到 sim_note。**结案不走这里**——结案
真源是到期核账 ``settle_due_secret_orders``。

未知/非 active 密令的副作用写不进（追加静默返 False）→ 必须显式拒收，否则未知
id 被无脑报成「已应用」。
"""

from __future__ import annotations

from ming_sim.applier import RejectedItem

from typing import Dict, List

from ming_sim.applier import SectionResult


def apply(run):
    from ming_sim.strict_types import _parse_sqlite_id
    from ming_sim.entities.secret_order.disclosure import record_secret_order_disclosure

    applied: List[Dict[str, object]] = []
    rejections: List[RejectedItem] = []
    for item in run.current_extracted.get("secret_order_updates") or []:
        # sanitize 已滤非 dict 列表项。
        raw_id = item.get("order_id")
        raw_note = item.get("sim_note")
        if raw_note is None:
            raw_note = item.get("result")
        sim_note = raw_note
        if sim_note is not None and not isinstance(sim_note, str):
            rejections.append(RejectedItem(item=item, reason="sim_note 须为字符串", category="invalid_shape", source=run.ctx.source))
            continue
        disclosed = item.get("disclosed") is True
        if raw_id is None or sim_note is None or not sim_note.strip():
            rejections.append(RejectedItem(item=item, reason="order_id 或 sim_note 缺失", category="invalid_enum", source=run.ctx.source))
            continue
        try:
            real_id = _parse_sqlite_id(raw_id)
        except (TypeError, ValueError) as exc:
            rejections.append(RejectedItem(item=item, reason=str(exc), category="invalid_enum", source=run.ctx.source))
            continue
        order = run.db.character_knowledge.get_secret_order(real_id)
        if order is None:
            rejections.append(RejectedItem(item=item, reason="密令不存在", category="missing_ref", source=run.ctx.source))
            continue
        if order["status"] != "active":
            rejections.append(RejectedItem(item=item, reason=f"密令当前 {order['status']}，非 active，不写推演副作用", category="invalid_enum", source=run.ctx.source))
            continue
        run.db.update_secret_order_sim_note(
            real_id, sim_note, commit=False,
        )
        if disclosed and not run.ctx.defer_disclosure:
            record_secret_order_disclosure(
                run.db, run.state, real_id, sim_note
            )
        print(f"[secret_order] 推演副作用 id={real_id} note={sim_note!r}")
        applied.append({
            "order_id": real_id, "sim_note": sim_note, "disclosed": disclosed,
        })
    return SectionResult(applied=applied, rejected=rejections)
