def test_get_session_write_queue_wiring_fail_loud_no_broad_swallow():
    """WebGame/session 共享同一写入队列。"""
    from ming_sim.session_write_queue import get_session_write_queue

    class _Sess:
        pass

    class _Owner:
        def __init__(self) -> None:
            self.session = _Sess()

    owner = _Owner()
    q1 = get_session_write_queue(owner)
    q2 = get_session_write_queue(owner)
    q3 = get_session_write_queue(owner.session)
    assert q1 is q2 is q3
    assert owner._write_queue is q1
    assert owner.session._write_queue is q1
    assert owner._write_gate is q1.write_gate
    assert owner.session._write_gate is q1.write_gate
