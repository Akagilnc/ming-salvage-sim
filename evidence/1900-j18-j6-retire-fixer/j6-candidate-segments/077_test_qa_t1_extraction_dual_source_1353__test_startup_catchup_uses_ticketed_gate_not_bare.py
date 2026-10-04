def test_startup_catchup_uses_ticketed_gate_not_bare(web_game, monkeypatch):
    """startup catch-up 须经票据写缝：非阻塞 acquire 拒收（裸 Lock 会放行）。"""
    game = web_game
    seen = {}

    def fake_catch_up(*, write_gate=None, **_k):
        # 外部契约：票据缝拒非阻塞 acquire；threading.Lock 会返回 True。
        try:
            write_gate.acquire(blocking=False)
            seen["bare_lock"] = True
            write_gate.release()
        except RuntimeError:
            seen["ticketed_contract"] = True

    monkeypatch.setattr(web_app, "catch_up_pending_translations", fake_catch_up)
    ticket = game._mark_pending_write(key=("startup",))
    assert ticket is not None
    game._run_startup_extraction_catch_up(pending_ticket=ticket)
    assert seen.get("ticketed_contract") is True
    assert seen.get("bare_lock") is not True
    assert ticket._done is True
