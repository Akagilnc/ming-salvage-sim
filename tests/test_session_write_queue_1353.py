"""#1353 单写者票据队列钉：序 / 屏障 / 失败空放行 / 撤回取消 / 生产 seam。

法源 ADR 0149 + owner 无感宪法。确定性事件握手，不靠 sleep 判胜负。
屏障只等工人终态（K10a：无 elapsed 熔断）。
"""

from __future__ import annotations

import threading
import time

import pytest

from ming_sim.session_write_queue import (
    SessionWriteQueue,
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
        q.run(t_trail, lambda: order.append("trail_write"))
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
        result_box["r"] = q.barrier(barrier_body)
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
        q.barrier(lambda: order.append("barrier") or None)
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
    q.barrier(lambda: order.append("barrier") or None)
    assert order == ["barrier"]
    assert q.inflight_count() == 0


def test_post_barrier_claim_run_waits_for_barrier():
    """#1353 r6：屏障已开后才领的尾随票，run()/TicketedWriteGate 须等屏障结束后才写。

    生产路径：issue barrier 常在 chat hang 时 claim，回话收尾才 spawn 尾随——
    尾随 seq > barrier。契约：尾随凡碰共享 conn 必先 wait_prior（经 run/ticketed
    gate），不得闸外读库与 gate-free close 并发。
    """
    q = SessionWriteQueue()
    order: list[str] = []
    barrier_hold = threading.Event()
    barrier_entered = threading.Event()
    trail_blocked = threading.Event()

    def barrier_body() -> None:
        order.append("barrier_start")
        barrier_entered.set()
        assert barrier_hold.wait(2.0)
        order.append("barrier_end")

    bt = threading.Thread(
        target=lambda: q.barrier(barrier_body), name="barrier", daemon=True,
    )
    bt.start()
    assert barrier_entered.wait(2.0)

    t_trail = q.claim(key=("turn", 1))
    assert t_trail is not None

    def trail() -> None:
        trail_blocked.set()
        q.run(t_trail, lambda: order.append("trail_write"))
        q.complete(t_trail)

    th = threading.Thread(target=trail, name="trail-post", daemon=True)
    th.start()
    assert trail_blocked.wait(2.0)
    # 屏障未放行前尾随不得写
    assert "trail_write" not in order
    assert order == ["barrier_start"]

    barrier_hold.set()
    bt.join(timeout=2.0)
    th.join(timeout=2.0)
    assert not bt.is_alive() and not th.is_alive()
    assert order == ["barrier_start", "barrier_end", "trail_write"], order
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
        q.run(t, write)
    assert wrote["n"] == 0


def test_ticketed_gate_cancel_blocks_write():
    """生产 seam：TicketedWriteGate 见取消不进写临界区。"""
    q = SessionWriteQueue()
    t = q.claim(key=("turn", 7))
    assert t is not None
    q.cancel(t)
    wrote = {"n": 0}
    gate = q.ticketed_gate(t)
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
        q.barrier(barrier_body)
        barrier_done.set()

    bt = threading.Thread(target=run_barrier, daemon=True)
    bt.start()
    assert barrier_in_body.wait(2.0)

    late = q.claim(key=("turn", 99))
    assert late is not None
    late_claimed.set()

    def late_writer() -> None:
        q.run(late, lambda: order.append("late_write") or late_wrote.set())
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


def test_barrier_waits_healthy_slow_worker_terminal():
    """K10a：健康工人慢于原 30s 熔断窗仍正常终态 → 屏障续跑，不伪造成挂死。"""
    q = SessionWriteQueue()
    t = q.claim(key=("turn", 1))
    assert t is not None
    order: list[str] = []
    barrier_done = threading.Event()
    # 用可观测的“慢于旧熔断”窗（原 DEFAULT_TICKET_WAIT_S=30）；测试缩到 0.08s
    # 证明屏障不按 elapsed 失败——工人 0.08s 后 complete，屏障必等其终态。
    slow_s = 0.08

    def slow_worker() -> None:
        time.sleep(slow_s)
        order.append("worker_terminal")
        q.complete(t)

    def run_barrier() -> None:
        q.barrier(lambda: order.append("barrier") or None)
        barrier_done.set()

    threading.Thread(target=slow_worker, daemon=True).start()
    threading.Thread(target=run_barrier, daemon=True).start()
    assert barrier_done.wait(2.0)
    assert order == ["worker_terminal", "barrier"], order
    assert q.inflight_count() == 0


def test_barrier_proceeds_after_worker_fail_vacate():
    """可控失败终态：工人 vacate 后屏障放行（无 elapsed 伪失败）。"""
    q = SessionWriteQueue()
    t = q.claim(key=("turn", 2))
    assert t is not None
    order: list[str] = []
    started = threading.Event()
    done = threading.Event()

    def failing_worker() -> None:
        started.set()
        time.sleep(0.02)
        order.append("fail_vacate")
        q.vacate(t)  # 失败空放行

    def run_barrier() -> None:
        assert started.wait(2.0)
        q.barrier(lambda: order.append("barrier") or None)
        done.set()

    threading.Thread(target=failing_worker, daemon=True).start()
    threading.Thread(target=run_barrier, daemon=True).start()
    assert done.wait(2.0)
    assert order == ["fail_vacate", "barrier"], order


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
        target=lambda: (q.run_exclusive(slow), slow_done.set()),
        daemon=True,
    )
    th.start()
    assert in_critical.wait(2.0)
    th2 = threading.Thread(
        target=lambda: q.run_exclusive(fast),
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


def test_no_elapsed_timeout_api_on_barrier():
    """队列层已删 elapsed 熔断分类：barrier/wait_prior/run 无 timeout_s 形参。"""
    import inspect
    from pathlib import Path

    import ming_sim.session_write_queue as swq

    q = SessionWriteQueue()
    assert "timeout_s" not in inspect.signature(q.barrier).parameters
    assert "timeout_s" not in inspect.signature(q.wait_prior).parameters
    assert "timeout_s" not in inspect.signature(q.run).parameters
    assert "timeout_s" not in inspect.signature(q.ticketed_gate).parameters
    text = Path(swq.__file__).read_text(encoding="utf-8")
    assert "TicketBarrierTimeout" not in text
    assert "DEFAULT_TICKET_WAIT_S" not in text
    assert not hasattr(swq, "TicketBarrierTimeout")


def test_get_session_write_queue_wiring_fail_loud_no_broad_swallow():
    """#1353 r7 / ADR 0005：接线赋值禁宽吞；WebGame/session 必共享同一 queue/gate。"""
    import re
    from pathlib import Path

    import ming_sim.session_write_queue as swq
    from ming_sim.session_write_queue import get_session_write_queue

    text = Path(swq.__file__).read_text(encoding="utf-8")
    # 定位 get_session_write_queue 函数体，禁 except Exception + pass 宽吞。
    m = re.search(
        r"def get_session_write_queue\(.*?(?=\ndef |\Z)",
        text,
        flags=re.S,
    )
    assert m is not None
    body = m.group(0)
    assert "except Exception" not in body
    assert re.search(r"except\s+Exception\s*:\s*\n\s*pass", body) is None

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
