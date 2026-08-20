"""#1353 单写者票据队列钉：序 / 屏障 / 失败空放行 / 撤回取消。

法源 ADR 0149 + owner 无感宪法。确定性编排，不靠 sleep 判胜负。
"""

from __future__ import annotations

import threading

import pytest

from ming_sim.session_write_queue import (
    SessionWriteQueue,
    TicketCancelled,
    WriteTicket,
)


def test_queue_order_early_claim_late_finish_before_barrier():
    """队列序钉：早领票、晚完成的写仍先于屏障落库。"""
    q = SessionWriteQueue()
    order: list[str] = []
    trail_entered = threading.Event()
    release_trail = threading.Event()
    barrier_entered = threading.Event()

    t_trail = q.claim(key=("extract", 1))

    def trail() -> None:
        trail_entered.set()
        assert release_trail.wait(2.0)
        # late finish: write then complete
        with q.write_gate:
            order.append("trail_write")
        q.complete(t_trail)

    th = threading.Thread(target=trail, name="trail-late", daemon=True)
    th.start()
    assert trail_entered.wait(2.0)

    def barrier_body() -> str:
        barrier_entered.set()
        order.append("barrier")
        return "ok"

    # Barrier claimed while trail still open → must wait for trail complete.
    result_box: dict = {}

    def run_barrier() -> None:
        result_box["r"] = q.barrier(barrier_body)

    bt = threading.Thread(target=run_barrier, name="barrier", daemon=True)
    bt.start()
    # Barrier must not run while trail open (deterministic: trail not released yet).
    assert not barrier_entered.wait(0.05)
    assert "barrier" not in order

    release_trail.set()
    bt.join(timeout=2.0)
    th.join(timeout=2.0)
    assert not bt.is_alive() and not th.is_alive()
    assert result_box.get("r") == "ok"
    assert order == ["trail_write", "barrier"], order
    assert q.inflight_count() == 0


def test_barrier_waits_multiple_prior_tickets():
    """屏障钉：多张先领票全清后屏障才跑。"""
    q = SessionWriteQueue()
    order: list[str] = []
    a = q.claim()
    b = q.claim()
    release = threading.Event()

    def fin(name: str, ticket: WriteTicket, delay_event: threading.Event) -> None:
        assert delay_event.wait(2.0)
        order.append(name)
        q.complete(ticket)

    threading.Thread(target=fin, args=("a", a, release), daemon=True).start()
    threading.Thread(target=fin, args=("b", b, release), daemon=True).start()

    started = threading.Event()
    done = threading.Event()

    def br() -> None:
        started.set()
        q.barrier(lambda: order.append("barrier") or None)
        done.set()

    threading.Thread(target=br, daemon=True).start()
    assert started.wait(2.0)
    assert not done.wait(0.05)
    release.set()
    assert done.wait(2.0)
    assert order[-1] == "barrier"
    assert set(order[:2]) == {"a", "b"}


def test_fail_vacate_lets_barrier_through():
    """失败钉：腿失败票据空放行，屏障不卡死。"""
    q = SessionWriteQueue()
    t = q.claim(key=("extract", 9))
    # fail path: vacate without write
    q.vacate(t)
    order: list[str] = []
    q.barrier(lambda: order.append("barrier") or None)
    assert order == ["barrier"]
    assert q.inflight_count() == 0


def test_cancel_key_vacates_and_blocks_run():
    """撤回钉：按 key 取消在飞票据；run 见取消不写库。"""
    q = SessionWriteQueue()
    t = q.claim(key=("turn", 42))
    n = q.cancel_key(("turn", 42))
    assert n == 1
    assert t.cancelled is True
    assert q.inflight_count() == 0

    wrote = {"n": 0}

    def write() -> None:
        wrote["n"] += 1

    with pytest.raises(TicketCancelled):
        q.run(t, write)
    assert wrote["n"] == 0


def test_run_exclusive_serializes_writes():
    """write_gate 并入队列：run_exclusive 互斥。"""
    q = SessionWriteQueue()
    hold = threading.Event()
    in_critical = threading.Event()
    order: list[str] = []

    def slow() -> None:
        in_critical.set()
        assert hold.wait(2.0)
        order.append("slow")

    def fast() -> None:
        order.append("fast")

    th = threading.Thread(target=lambda: q.run_exclusive(slow), daemon=True)
    th.start()
    assert in_critical.wait(2.0)
    th2 = threading.Thread(target=lambda: q.run_exclusive(fast), daemon=True)
    th2.start()
    # fast must not finish while slow holds gate via run_exclusive
    assert th2.is_alive()
    assert "fast" not in order
    hold.set()
    th.join(timeout=2.0)
    th2.join(timeout=2.0)
    assert order == ["slow", "fast"], order
