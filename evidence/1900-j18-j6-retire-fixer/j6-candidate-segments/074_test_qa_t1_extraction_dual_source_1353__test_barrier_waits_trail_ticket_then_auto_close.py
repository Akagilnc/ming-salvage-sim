def test_barrier_waits_trail_ticket_then_auto_close(web_game, monkeypatch):
    """#1353 生产接缝屏障钉：尾随领票未完成时 entry 不得抢跑；完成后一次过。"""
    game = web_game
    # 空库 startup 不得占票；本钉只见自领 1 票（全量 xdist 顺序依赖根因）。
    assert int(game._pending_writes_count) == 0
    ticket = game._mark_pending_write(key=("turn", 1))
    assert ticket is not None
    assert int(game._pending_writes_count) == 1

    order: list[str] = []
    trail_holding = threading.Event()
    release = threading.Event()
    entry_done = threading.Event()

    def trail_worker() -> None:
        trail_holding.set()
        release.wait()
        order.append("trail_end")
        game._complete_pending_write(ticket)

    t = threading.Thread(target=trail_worker, name="trail-barrier", daemon=True)
    t.start()
    trail_holding.wait()

    def track_auto_close(_g, **_k):
        assert ticket._done is True
        order.append("auto_close")

    monkeypatch.setattr(web_app, "_auto_close_open_night_gate_free", track_auto_close)
    monkeypatch.setattr(web_app, "_accept_settlement_period", lambda _g: False)

    def run_entry() -> None:
        with web_app._settlement_period_entry(game, write_cm=web_app._game_write_gate):
            order.append("body")
        entry_done.set()

    et = threading.Thread(target=run_entry, name="settlement-entry", daemon=True)
    et.start()
    # 确定性：trail 未放行前 entry 不得完成（事件握手，不靠 sleep 判胜负）
    assert not entry_done.is_set()
    assert "auto_close" not in order
    assert "body" not in order

    order.append("release")
    release.set()
    entry_done.wait()
    t.join()
    et.join()
    assert not t.is_alive() and not et.is_alive()
    assert order == ["release", "trail_end", "auto_close", "body"], order
    assert int(game._pending_writes_count) == 0
