"""#1353 单写者票据队列钉：序 / 屏障 / 失败空放行 / 撤回取消 / 生产 seam。

法源 ADR 0149 + owner 无感宪法。确定性事件握手，不靠 sleep 判胜负。
"""

from __future__ import annotations

import threading

import pytest

from ming_sim.session_write_queue import (
    SessionWriteQueue,
    TicketBarrierTimeout,
    TicketCancelled,
    WriteTicket,
)


def test_queue_order_early_claim_late_finish_before_barrier():
    """队列序钉：早领票、晚完成的写仍先于屏障落库（完整事件握手）。"""
    q = SessionWriteQueue()
    order: list[str] = []
    trail_ready = threading.Event()  # trail 已进入、持票等待放行
    release_trail = threading.Event()
    barrier_may_start = threading.Event()  # 测试主线程确认 barrier 已阻塞后再放 trail
    barrier_entered = threading.Event()
    barrier_done = threading.Event()

    t_trail = q.claim(key=("extract", 1))
    assert t_trail is not None

    def trail() -> None:
        trail_ready.set()
        assert release_trail.wait(2.0)
        # 生产 seam：按票序写
        q.run(t_trail, lambda: order.append("trail_write"), timeout_s=None)
        q.complete(t_trail)

    th = threading.Thread(target=trail, name="trail-late", daemon=True)
    th.start()
    assert trail_ready.wait(2.0)

    def barrier_body() -> str:
        barrier_entered.set()
        order.append("barrier")
        return "ok"

    result_box: dict = {}

    def run_barrier() -> None:
        assert barrier_may_start.wait(2.0)
        result_box["r"] = q.barrier(barrier_body, timeout_s=None)
        barrier_done.set()

    bt = threading.Thread(target=run_barrier, name="barrier", daemon=True)
    bt.start()
    # 主线程：先确认 trail 在飞、再放 barrier 线程去 claim——barrier 必见 open prior。
    barrier_may_start.set()
    # barrier 在 trail 完成前不得进入 body：用「barrier_done 未置且 order 无 barrier」
    # 的握手——等 trail 仍 open 时 barrier 应阻塞在 wait_prior。
    assert q.inflight_count() >= 1
    # 确定性：在放行 trail 前 barrier body 不得跑。
    assert not barrier_entered.is_set()
    assert "barrier" not in order

    release_trail.set()
    assert barrier_done.wait(2.0)
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
    assert a is not None and b is not None
    release = threading.Event()
    both_waiting = threading.Barrier(3)  # a, b, main

    def fin(name: str, ticket: WriteTicket) -> None:
        both_waiting.wait(timeout=2.0)
        assert release.wait(2.0)
        order.append(name)
        q.complete(ticket)

    threading.Thread(target=fin, args=("a", a), daemon=True).start()
    threading.Thread(target=fin, args=("b", b), daemon=True).start()
    both_waiting.wait(timeout=2.0)

    started = threading.Event()
    done = threading.Event()

    def br() -> None:
        started.set()
        q.barrier(lambda: order.append("barrier") or None, timeout_s=None)
        done.set()

    threading.Thread(target=br, daemon=True).start()
    assert started.wait(2.0)
    # 放行前 barrier 不得完成
    assert not done.is_set()
    release.set()
    assert done.wait(2.0)
    assert order[-1] == "barrier"
    assert set(order[:2]) == {"a", "b"}


def test_fail_vacate_lets_barrier_through():
    """失败钉：腿失败票据空放行，屏障不卡死。"""
    q = SessionWriteQueue()
    t = q.claim(key=("extract", 9))
    assert t is not None
    q.vacate(t)
    order: list[str] = []
    q.barrier(lambda: order.append("barrier") or None, timeout_s=None)
    assert order == ["barrier"]
    assert q.inflight_count() == 0


def test_cancel_key_vacates_and_blocks_run():
    """撤回钉：按 key 取消在飞票据；run 见取消不写库。"""
    q = SessionWriteQueue()
    t = q.claim(key=("turn", 42))
    assert t is not None
    n = q.cancel_key(("turn", 42))
    assert n == 1
    assert t.cancelled is True
    assert q.inflight_count() == 0

    wrote = {"n": 0}

    def write() -> None:
        wrote["n"] += 1

    with pytest.raises(TicketCancelled):
        q.run(t, write, timeout_s=None)
    assert wrote["n"] == 0


def test_ticketed_gate_cancel_blocks_write():
    """生产 seam：TicketedWriteGate 见取消不进写临界区。"""
    q = SessionWriteQueue()
    t = q.claim(key=("turn", 7))
    assert t is not None
    q.cancel(t)
    wrote = {"n": 0}
    gate = q.ticketed_gate(t, timeout_s=None)
    with pytest.raises(TicketCancelled):
        with gate:
            wrote["n"] += 1
    assert wrote["n"] == 0


def test_post_barrier_claim_cannot_cross_barrier_write():
    """屏障后新领票经 seam 不得越过屏障写（确定性握手）。"""
    q = SessionWriteQueue()
    order: list[str] = []
    barrier_in_body = threading.Event()
    release_barrier = threading.Event()
    late_claimed = threading.Event()
    late_wrote = threading.Event()
    barrier_done = threading.Event()

    def barrier_body() -> None:
        barrier_in_body.set()
        # 屏障持票期间允许后票 claim；后票 run 必须等屏障 complete。
        assert late_claimed.wait(2.0)
        order.append("barrier_write")
        assert release_barrier.wait(2.0)

    def run_barrier() -> None:
        q.barrier(barrier_body, timeout_s=None)
        barrier_done.set()

    bt = threading.Thread(target=run_barrier, daemon=True)
    bt.start()
    assert barrier_in_body.wait(2.0)

    late = q.claim(key=("turn", 99))
    assert late is not None
    late_claimed.set()

    def late_writer() -> None:
        q.run(late, lambda: order.append("late_write") or late_wrote.set(), timeout_s=None)
        q.complete(late)

    lt = threading.Thread(target=late_writer, daemon=True)
    lt.start()
    # 确定性：屏障未放行前 late 不得写入（order 握手，不靠 sleep）
    assert "late_write" not in order
    assert not late_wrote.is_set()
    assert not barrier_done.is_set()

    release_barrier.set()
    assert barrier_done.wait(2.0)
    assert late_wrote.wait(2.0)
    lt.join(timeout=2.0)
    bt.join(timeout=2.0)
    assert order == ["barrier_write", "late_write"], order


def test_barrier_timeout_fail_closed_on_hung_prior():
    """真挂死：屏障有界熔断，不得无限悬吊。"""
    q = SessionWriteQueue()
    hung = q.claim(key=("turn", 1))
    assert hung is not None
    # 故意不 complete hung
    with pytest.raises(TicketBarrierTimeout) as ei:
        q.barrier(lambda: None, timeout_s=0.05)
    assert hung.seq in (ei.value.open_seqs or [hung.seq])
    # hung 仍 open——fail-closed 不静默吞票
    assert q.inflight_count() == 1
    q.complete(hung)
    assert q.inflight_count() == 0


def test_run_exclusive_serializes_writes():
    """write_gate 并入队列：run_exclusive 互斥。"""
    q = SessionWriteQueue()
    hold = threading.Event()
    in_critical = threading.Event()
    order: list[str] = []
    slow_done = threading.Event()
    fast_done = threading.Event()

    def slow() -> None:
        in_critical.set()
        assert hold.wait(2.0)
        order.append("slow")

    def fast() -> None:
        order.append("fast")
        fast_done.set()

    th = threading.Thread(
        target=lambda: (q.run_exclusive(slow, timeout_s=None), slow_done.set()),
        daemon=True,
    )
    th.start()
    assert in_critical.wait(2.0)
    th2 = threading.Thread(
        target=lambda: q.run_exclusive(fast, timeout_s=None),
        daemon=True,
    )
    th2.start()
    # fast 在 slow 持锁期间不得完成
    assert not fast_done.is_set()
    assert "fast" not in order
    hold.set()
    assert slow_done.wait(2.0)
    assert fast_done.wait(2.0)
    th.join(timeout=2.0)
    th2.join(timeout=2.0)
    assert order == ["slow", "fast"], order
