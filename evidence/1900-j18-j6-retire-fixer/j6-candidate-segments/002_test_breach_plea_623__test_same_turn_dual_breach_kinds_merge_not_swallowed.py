def test_same_turn_dual_breach_kinds_merge_not_swallowed(game):
    """同回合第二类松手不得静默吞：并入既有 pending + meta 记全被吞类。"""
    db, state, content = game
    db.conn.execute("UPDATE issues SET status='dropped' WHERE status='active'")
    db.conn.commit()
    did, _ = _executing_policy_dossier(db, state, token="dual-kind")
    origin = f"dossier:{did}"
    db.record_issue_economy_move(
        state, "国库", -3, "月供", "历史供拨", origin_ref=origin, commit=True,
    )
    cid, _ = _insert_commitment(
        db, state, title="同回合双类之诺", origin_ref=origin,
        ongoing_effects={}, bar_value=20, end_turn=state.turn + 40,
        tags=["专款:国库"],
    )
    t1 = write_breach_plea_todo(
        db, state, commitment_ref=cid, breach_kind=BREACH_KIND_FUNDING,
        reason="断供", target_dossier_id=did, commit=True,
    )
    assert t1 > 0
    # 同回合第二类：改弦（不推进 turn）
    t2 = write_breach_plea_todo(
        db, state, commitment_ref=cid, breach_kind=BREACH_KIND_POLICY_REVERSAL,
        reason="改弦", target_dossier_id=did, commit=True,
    )
    assert t2 == t1  # 并入同一条
    pleas = _pending_pleas(db)
    assert len(pleas) == 1
    from ming_sim.breach_plea import decode_plea_meta
    meta = decode_plea_meta(pleas[0]["origin_context"])
    assert meta.get("breach_kind") == BREACH_KIND_FUNDING
    absorbed = meta.get("absorbed_breach_kinds") or []
    assert BREACH_KIND_POLICY_REVERSAL in absorbed
    # try_defer 不得返空 todo_ids
    deferred = try_defer_revoke_to_breach_plea(
        db, state, target_dossier_id=did, reason="再撤", commit=True,
    )
    assert deferred and deferred.get("deferred")
    assert deferred.get("todo_ids"), "try_defer 不得返空 todo_ids 掩蔽"
