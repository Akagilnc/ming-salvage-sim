"""密令推演副作用段（``secret_order_updates``）。

写 active 密令的推演副作用（泄漏/反弹）到 sim_note。**结案不走这里**——结案
真源是到期核账 ``settle_due_secret_orders``。

未知/非 active 密令的副作用写不进（追加静默返 False）→ 必须显式拒收，否则未知
id 被无脑报成「已应用」。
"""

from __future__ import annotations

from typing import Dict, List

from ming_sim.applier import SectionResult


def apply(run) -> SectionResult:
    from ming_sim.issues import _parse_sqlite_id, record_secret_order_disclosure

    applied: List[Dict[str, object]] = []
    for item in run.current_extracted.get("secret_order_updates") or []:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("order_id")
        sim_note = str(item.get("sim_note") or item.get("result") or "").strip()
        disclosed = item.get("disclosed") is True
        if raw_id is None or not sim_note:
            applied.append({
                "order_id": raw_id, "rejected": True,
                "category": "invalid_enum", "reason": "order_id 或 sim_note 缺失",
            })
            continue
        try:
            real_id = _parse_sqlite_id(raw_id)
        except (TypeError, ValueError):
            applied.append({
                "order_id": raw_id, "rejected": True,
                "category": "invalid_enum", "reason": "order_id 非整数或超界",
            })
            continue
        order = run.db.get_secret_order(real_id)
        if order is None:
            applied.append({
                "order_id": real_id, "rejected": True,
                "category": "missing_ref", "reason": "密令不存在",
            })
            continue
        if order["status"] != "active":
            applied.append({
                "order_id": real_id, "rejected": True, "category": "invalid_enum",
                "reason": f"密令当前 {order['status']}，非 active，不写推演副作用",
            })
            continue
        try:
            run.db.update_secret_order_sim_note(
                real_id, sim_note, year=run.state.year,
                period=run.state.period, commit=run.commit_now,
            )
            if disclosed and not run.ctx.defer_disclosure:
                record_secret_order_disclosure(
                    run.db, run.state, real_id, sim_note, commit=run.commit_now,
                )
            print(f"[secret_order] 推演副作用 id={real_id} note={sim_note[:60]!r}")
            applied.append({
                "order_id": real_id, "sim_note": sim_note, "disclosed": disclosed,
            })
        except Exception as exc:
            applied.append({"order_id": real_id, "rejected": True, "reason": str(exc)})
    run.applied_secret_orders = applied
    return SectionResult(applied=[], rejected=[])
