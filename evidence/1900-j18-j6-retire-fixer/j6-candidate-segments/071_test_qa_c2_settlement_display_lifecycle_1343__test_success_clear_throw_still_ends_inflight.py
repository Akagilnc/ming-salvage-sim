def test_success_clear_throw_still_ends_inflight(game, monkeypatch):
    """验收：成功支 clear 抛错仍执行 _end_settlement_entry（inflight 归零）。

    且 settled_ok 不得在 clear 前预置真——clear 抛须走失败 exit，
    禁「成功态 + 死遮罩」绕过失败收口。
    """
    db, state, content = game
    runtime = _shell(db, state, content)
    state.turn_phase = TurnPhase.SUMMONING.value
    db.save_state(state)
    db.capture_month_open_snapshot(state)

    monkeypatch.setattr(web_app, "_accept_settlement_period", lambda _g: True)
    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", lambda _g, **_k: None)

    exit_calls = {"n": 0}
    real_exit = web_app._exit_settlement_display_on_failure

    def _spy_exit(g, *, blocking=False):
        exit_calls["n"] += 1
        return real_exit(g, blocking=blocking)

    monkeypatch.setattr(web_app, "_exit_settlement_display_on_failure", _spy_exit)

    def _boom_clear(_t):
        raise RuntimeError("clear boom")

    db.clear_month_open_snapshot = _boom_clear  # type: ignore[method-assign]

    raised = None
    try:
        with web_app._settlement_period_entry(runtime, write_cm=_blocking_gate):
            pass
    except RuntimeError as exc:
        raised = exc

    assert raised is not None and "clear boom" in str(raised)
    assert web_app._settlement_entry_inflight(runtime) == 0, "clear 抛错后 inflight 须归零"
    assert exit_calls["n"] == 1, "clear 抛须走失败 exit（settled_ok 未在 clear 前预置）"
