def test_drain_and_close_session_waits_for_gate_then_closes():
    queue = SessionWriteQueue()
    gate = queue.write_gate
    closed: list[int] = []
    game = SimpleNamespace(
        _write_queue=queue,
        _write_gate=gate,
        session=SimpleNamespace(close=lambda: closed.append(1)),
    )

    assert gate.acquire(blocking=False)
    done = threading.Event()

    thread = threading.Thread(
        target=lambda: (web_app._drain_and_close_session(game), done.set()),
        daemon=True,
    )
    thread.start()
    # While the live queue gate is held, drain must not close the session.
    assert not done.is_set()
    assert closed == []

    gate.release()

    done.wait()
    assert closed == [1]
    assert not gate.locked()
