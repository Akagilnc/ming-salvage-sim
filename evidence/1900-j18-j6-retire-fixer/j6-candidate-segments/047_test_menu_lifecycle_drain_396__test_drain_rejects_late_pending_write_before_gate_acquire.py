def test_drain_rejects_late_pending_write_before_gate_acquire():
    """#402 R3（Sourcery）：drain 开始后，迟到的旧 game 写入不得再登记进关闭队列。"""
    runtime = object.__new__(web_app.WebGame)
    runtime._write_queue = SessionWriteQueue()
    runtime._write_gate = runtime._write_queue.write_gate
    runtime._runtime_write_queue = lambda: runtime._write_queue  # type: ignore
    runtime._mark_pending_write = lambda key=None: runtime._write_queue.claim(key=key or ("pending",))  # type: ignore
    runtime._complete_pending_write = lambda ticket=None: runtime._write_queue.complete(ticket)  # type: ignore
    closed: list[int] = []
    runtime.session = SimpleNamespace(close=lambda: closed.append(1))

    runtime._write_gate.acquire()
    done = threading.Event()
    thread = threading.Thread(
        target=lambda: (web_app._drain_and_close_session(runtime), done.set()),
        daemon=True,
    )
    thread.start()

    wait_until(lambda: runtime._write_queue.is_sealed())
    assert runtime._mark_pending_write() is None
    # 屏障票据在等 gate 期间可占 1；新 claim 已拒。
    assert runtime._pending_writes_count <= 1

    runtime._write_gate.release()

    done.wait()
    assert closed == [1]
