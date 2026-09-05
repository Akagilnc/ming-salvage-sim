"""#1353 单写者票据队列钉：序 / 屏障 / 失败空放行 / 撤回取消 / 生产 seam。

法源 ADR 0149 + owner 无感宪法。确定性事件握手，不靠 sleep 判胜负。
屏障只等工人终态（K10a：无 elapsed 熔断）。
"""

from __future__ import annotations

import threading
import time

import pytest

from types import SimpleNamespace

from ming_sim.session_write_queue import (
    SessionWriteQueue,
    TicketCancelled,
    WriteTicket,
    get_session_write_queue,
)


def wait_pending_writes(game, *, timeout_s: float | None = None) -> None:
    """Fail-loud drain of SessionWriteQueue open tickets (teardown/body shared).

    真源＝wait_idle（Condition）；禁 sleep busy-poll。
    默认无时限（CI job 终线承接挂死）；仅负向 stuck 探测传有限 timeout_s。
    """
    q = get_session_write_queue(game)
    ok = q.wait_idle(timeout_s=timeout_s)
    if timeout_s is None:
        return
    assert ok, (
        f"pending writes did not drain in {timeout_s}s; "
        f"count={q.inflight_count()}"
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
        release_trail.wait()
        # 生产 seam：按票序写
        q.run(t_trail, lambda: order.append("trail_write"))
        q.complete(t_trail)

    th = threading.Thread(target=trail, name="trail-late", daemon=True)
    th.start()
    trail_ready.wait()

    def barrier_body() -> str:
        barrier_entered.set()
        order.append("barrier")
        return "ok"

    result_box: dict = {}

    def run_barrier() -> None:
        barrier_may_start.wait()
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
    barrier_done.wait()
    bt.join()
    th.join()
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
        both_waiting.wait()
        release.wait()
        order.append(name)
        q.complete(ticket)

    threading.Thread(target=fin, args=("a", a), daemon=True).start()
    threading.Thread(target=fin, args=("b", b), daemon=True).start()
    both_waiting.wait()

    started = threading.Event()
    done = threading.Event()

    def br() -> None:
        started.set()
        q.barrier(lambda: order.append("barrier") or None)
        done.set()

    threading.Thread(target=br, daemon=True).start()
    started.wait()
    # 放行前 barrier 不得完成
    assert not done.is_set()
    release.set()
    done.wait()
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
        barrier_hold.wait()
        order.append("barrier_end")

    bt = threading.Thread(
        target=lambda: q.barrier(barrier_body), name="barrier", daemon=True,
    )
    bt.start()
    barrier_entered.wait()

    t_trail = q.claim(key=("turn", 1))
    assert t_trail is not None

    def trail() -> None:
        trail_blocked.set()
        q.run(t_trail, lambda: order.append("trail_write"))
        q.complete(t_trail)

    th = threading.Thread(target=trail, name="trail-post", daemon=True)
    th.start()
    trail_blocked.wait()
    # 屏障未放行前尾随不得写
    assert "trail_write" not in order
    assert order == ["barrier_start"]

    barrier_hold.set()
    bt.join()
    th.join()
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
        late_claimed.wait()
        order.append("barrier_write")
        release_barrier.wait()

    def run_barrier() -> None:
        q.barrier(barrier_body)
        barrier_done.set()

    bt = threading.Thread(target=run_barrier, daemon=True)
    bt.start()
    barrier_in_body.wait()

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
    barrier_done.wait()
    late_wrote.wait()
    lt.join()
    bt.join()
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
    barrier_done.wait()
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
        order.append("fail_vacate")
        q.vacate(t)  # 失败空放行

    def run_barrier() -> None:
        started.wait()
        q.barrier(lambda: order.append("barrier") or None)
        done.set()

    threading.Thread(target=failing_worker, daemon=True).start()
    threading.Thread(target=run_barrier, daemon=True).start()
    done.wait()
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
        hold.wait()
        order.append("slow")

    def fast() -> None:
        order.append("fast")
        fast_done.set()

    th = threading.Thread(
        target=lambda: (q.run_exclusive(slow), slow_done.set()),
        daemon=True,
    )
    th.start()
    in_critical.wait()
    th2 = threading.Thread(
        target=lambda: q.run_exclusive(fast),
        daemon=True,
    )
    th2.start()
    # fast 在 slow 持锁期间不得完成
    assert not fast_done.is_set()
    assert "fast" not in order
    hold.set()
    slow_done.wait()
    fast_done.wait()
    th.join()
    th2.join()
    assert order == ["slow", "fast"], order


def test_write_turn_orders_cs_not_whole_leg_llm():
    """#1353 r10 / 66nU P5：wait_write_turn 只排写段——先票 LLM 中时后票可进材料读/写。

    事件序：extract 领票 → extract 短读放闸 → extract 入 LLM 窗 → mind 领票并完成
    材料读（证明未等 extract LLM）→ extract LLM 终 → extract 写段 → 两票 complete。
    """
    q = SessionWriteQueue()
    order: list[str] = []
    extract_in_llm = threading.Event()
    mind_read_done = threading.Event()
    release_extract_llm = threading.Event()

    t_extract = q.claim(key=("turn", 1))
    t_mind = q.claim(key=("turn", 1))
    assert t_extract is not None and t_mind is not None

    def extract_leg() -> None:
        # 首碰共享 conn：短持写段
        with q.ticketed_gate(t_extract):
            order.append("extract_read")
        order.append("extract_llm_enter")
        extract_in_llm.set()
        release_extract_llm.wait()
        order.append("extract_llm_exit")
        with q.ticketed_gate(t_extract):
            order.append("extract_write")
        q.complete(t_extract)

    def mind_leg() -> None:
        extract_in_llm.wait()
        # 此时 extract 仍 open 且在 LLM——材料读不得被整票 wait_prior 串行化
        with q.ticketed_gate(t_mind):
            order.append("mind_read")
        mind_read_done.set()
        with q.ticketed_gate(t_mind):
            order.append("mind_write")
        q.complete(t_mind)

    et = threading.Thread(target=extract_leg, name="extract", daemon=True)
    mt = threading.Thread(target=mind_leg, name="mind", daemon=True)
    et.start()
    mt.start()
    mind_read_done.wait()
    assert "mind_read" in order
    assert "extract_llm_exit" not in order  # still inside extract LLM
    release_extract_llm.set()
    et.join()
    mt.join()
    assert not et.is_alive() and not mt.is_alive()
    assert order.index("extract_read") < order.index("extract_llm_enter")
    assert order.index("mind_read") < order.index("extract_llm_exit")
    assert "extract_write" in order and "mind_write" in order
    assert q.inflight_count() == 0


def test_write_turn_still_blocks_on_open_barrier():
    """写段序仍尊重开放屏障：后票 ticketed gate 不得越过 barrier body。"""
    q = SessionWriteQueue()
    order: list[str] = []
    barrier_in = threading.Event()
    release_barrier = threading.Event()
    late_done = threading.Event()

    def barrier_body() -> None:
        barrier_in.set()
        order.append("barrier")
        release_barrier.wait()

    bt = threading.Thread(
        target=lambda: q.barrier(barrier_body), name="barrier", daemon=True,
    )
    bt.start()
    barrier_in.wait()

    late = q.claim(key=("turn", 9))
    assert late is not None

    def late_writer() -> None:
        with q.ticketed_gate(late):
            order.append("late")
        q.complete(late)
        late_done.set()

    lt = threading.Thread(target=late_writer, daemon=True)
    lt.start()
    assert "late" not in order
    assert not late_done.is_set()
    release_barrier.set()
    late_done.wait()
    bt.join()
    lt.join()
    assert order == ["barrier", "late"], order


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


def test_wait_pending_writes_fail_loud_on_false_and_exception(monkeypatch):
    """单一权威负向：wait_idle=False 与队列异常均须报红，不得被调用方洗白。"""
    stuck = SessionWriteQueue()
    ticket = stuck.claim(key=("teardown-stuck", 1))
    assert ticket is not None
    try:
        with pytest.raises(AssertionError, match="did not drain"):
            wait_pending_writes(SimpleNamespace(_write_queue=stuck), timeout_s=0.05)
    finally:
        stuck.complete(ticket)

    boom = SessionWriteQueue()

    def _raise(*, timeout_s=None):
        raise RuntimeError("queue boom")

    monkeypatch.setattr(boom, "wait_idle", _raise)
    with pytest.raises(RuntimeError, match="queue boom"):
        wait_pending_writes(SimpleNamespace(_write_queue=boom), timeout_s=0.05)
