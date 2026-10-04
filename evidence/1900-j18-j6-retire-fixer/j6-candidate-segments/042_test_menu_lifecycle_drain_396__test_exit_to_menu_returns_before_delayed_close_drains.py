def test_exit_to_menu_returns_before_delayed_close_drains(monkeypatch, tmp_path):
    queue = SessionWriteQueue()
    gate = queue.write_gate
    closed: list[int] = []
    db_path = str(tmp_path / "exit-delay.db")
    fake_game = SimpleNamespace(
        _write_queue=queue,
        _write_gate=gate,
        db_path=db_path,
        session=SimpleNamespace(close=lambda: closed.append(1)),
    )
    _reset_path_leases()
    assert web_app._register_holder(db_path, fake_game) is not None
    monkeypatch.setattr(web_app, "web_game", fake_game)

    gate.acquire()

    result = asyncio.run(web_app.api_menu_exit())

    assert result == {"ok": True}
    assert web_app.web_game is None
    assert closed == []

    gate.release()

    wait_until(lambda: closed == [1])
    assert not gate.locked()
