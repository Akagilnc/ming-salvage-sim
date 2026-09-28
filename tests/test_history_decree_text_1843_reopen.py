
"""#1843 reopen：史册本月诏书改读 pending_resolve_context.decree_text。"""

from __future__ import annotations


def test_history_turn_reads_decree_text_from_resolve_context(game):
    db, state, content = game
    turn = int(state.turn)
    db.save_resolve_context(
        turn,
        decree_text="着宁远补饷三十万两",
        narrative="",
        simulator_payload={},
    )
    db.save_turn_report(state, "邸报正文", knowledge_items=[], attendant_message="")
    # No turn_extractions table/row.
    assert not hasattr(db, "get_turn_extraction")
    row = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='turn_extractions'"
    ).fetchone()
    assert row is None

    ctx = db.get_resolve_context(turn) or {}
    assert str(ctx.get("decree_text") or "") == "着宁远补饷三十万两"


def test_dispatch_settles_arrived_summons_and_exposure_hooks(game):
    """#670/#651 挂在 declaration_dispatch 逐段落账之后（与落账同事务）。

    settle_exposure 必须收到本段 report，不能空 dict（默许/查办依赖 applied）。
    """
    from ming_sim.applier import Provenance
    from ming_sim.declaration_dispatch import dispatch_declaration
    import ming_sim.covert_levy as cl
    import ming_sim.audience_night as an_mod

    db, state, content = game
    calls = {"summon": 0, "write": 0, "settle": 0, "settle_applied": []}
    real_summon = an_mod.settle_applied_arrived_summons
    real_write = cl.write_exposure_todos
    real_settle = cl.settle_exposure_from_canonical_actions

    def spy_summon(db, applied):
        calls["summon"] += 1
        return real_summon(db, applied)

    def spy_write(db, state, applied=None):
        calls["write"] += 1
        return real_write(db, state, applied)

    def spy_settle(db, state, applied):
        calls["settle"] += 1
        calls["settle_applied"].append(applied)
        return real_settle(db, state, applied)

    an_mod.settle_applied_arrived_summons = spy_summon
    cl.write_exposure_todos = spy_write
    cl.settle_exposure_from_canonical_actions = spy_settle
    try:
        dispatch_declaration(
            db, state,
            {"effects": {"metric_delta": {"public_support": 0}}},
            source=Provenance.player_decree,
        )
    finally:
        an_mod.settle_applied_arrived_summons = real_summon
        cl.write_exposure_todos = real_write
        cl.settle_exposure_from_canonical_actions = real_settle
    assert calls["summon"] == 1
    assert calls["write"] == 1
    assert calls["settle"] == 1
    # 必须是本段 report（mapping），不是空 dict 冒充。
    assert calls["settle_applied"] and isinstance(calls["settle_applied"][0], dict)
    assert calls["settle_applied"][0] is not None
    assert calls["settle_applied"][0] != {}


def test_month_drift_runs_exposure_settlement(game, monkeypatch):
    """#651 settle_exposure_from_canonical_actions 进 _run_month_drift。"""
    from ming_sim.month_chain import _run_month_drift
    from ming_sim.applier import Provenance
    import ming_sim.covert_levy as cl

    db, state, content = game
    seen = []
    real = cl.settle_exposure_from_canonical_actions

    def spy(db, state, applied):
        seen.append(True)
        return real(db, state, applied)

    monkeypatch.setattr(cl, "settle_exposure_from_canonical_actions", spy)
    chain = {
        "world_committed": True,
        "inertia_done": False,
    }
    _run_month_drift(db, state, chain, int(state.turn), "诏", Provenance.player_decree)
    assert seen == [True]
    assert chain.get("inertia_done") is True
