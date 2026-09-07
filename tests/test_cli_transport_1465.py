"""#1465 切片③：CLI runner 真实入口走统一 transport。

真实缝 = HTTP `POST /api/ministers/<name>/chat/stream`（channel="cli"，model 真是
`CliChat`，只把子进程换成脚本替身）。断言只落结构化字段：transport_attempts /
code / outcome / message_id / 夜未封 / 子进程调用次数。受控时钟，不跑真墙钟。
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Callable, Dict, Optional

import pytest

import ming_sim.cli_backend as cb
import ming_sim.llm_transport as transport_mod
from tests.cli_process_doubles import SilentUntilKilled, install_fake_cli_runner
from tests.test_chat_stream_failpaths_393 import (
    _parse_sse,
    _post_chat_stream,
    _transport_web_game,
)

_OK_REPLY = "臣已核辽饷，谨复奏。\n"


def _install_read_loop_silence_clock(
    monkeypatch,
    controlled: Dict[str, float],
) -> tuple[Callable[[float], Callable[[], Optional[str]]], Dict[str, object]]:
    """把受控静默窗接到读循环 Empty→check_idle_budget 上。

    泵线程只交付块；时钟间隔在主环可观测的 queue.Empty 窗口注入。
    返回 `(silence, state)`：`silence(seconds)` 作脚本项，块入队后泵侧等主环
    真的 check 完本窗（gate 由 check_idle 在 inject 耗尽时 set）；不得用未 set
    的 wait 装睡。state 供断言 checks / injected_total（非钩子自累）。
    """
    real_check = transport_mod.check_idle_budget
    state: Dict[str, object] = {
        "inject_left": 0.0,
        "injected_total": 0.0,
        "checks": 0,
        "gate": None,
    }

    def _check_idle_with_inject(
        *,
        last_activity_at: float,
        policy,
        clock: Optional[Callable[[], float]] = None,
    ):
        left = float(state["inject_left"] or 0.0)
        if left > 0.0:
            state["checks"] = int(state["checks"]) + 1
            # 一窗一次注入整段间隔（间隔本身 < idle）；推进共享受控时钟字典。
            controlled["t"] = float(controlled["t"]) + left
            state["inject_left"] = 0.0
            state["injected_total"] = float(state["injected_total"]) + left
            gate = state["gate"]
            if isinstance(gate, threading.Event):
                gate.set()
        return real_check(
            last_activity_at=last_activity_at, policy=policy, clock=clock,
        )

    monkeypatch.setattr(transport_mod, "check_idle_budget", _check_idle_with_inject)

    def _silence(seconds: float) -> Callable[[], Optional[str]]:
        gap = float(seconds)

        def _hook() -> Optional[str]:
            gate = threading.Event()
            state["gate"] = gate
            state["inject_left"] = gap
            if not gate.wait(timeout=5.0):
                raise AssertionError(
                    f"read loop never reached Empty→check_idle during {gap}s silence"
                )
            state["gate"] = None
            return None

        return _hook

    return _silence, state


def _pin_transport_policy(
    monkeypatch,
    tmp_path,
    *,
    idle_timeout_seconds: float = 30.0,
    max_attempts: int = 3,
    attempt_timeout_seconds: float = 30.0,
) -> None:
    """把预算钉在临时 runtime 档，免受本机 runtime_llm.json 漂移影响。

    静默判死阈值走设置页那一格（cli.timeout_seconds）——与设置 API 同一落盘入口
    （save_runtime_llm），不另写一份档格式。
    """
    from ming_sim import llm_config as llm_config_mod

    path = tmp_path / "runtime_llm.json"
    monkeypatch.setattr(llm_config_mod, "RUNTIME_LLM_PATH", str(path))
    llm_config_mod.save_runtime_llm(
        "", "", "",
        channel="cli",
        cli_runner="claude",
        cli_model="cli-model-test",
        cli_timeout_seconds=idle_timeout_seconds,
        transport_max_attempts=max_attempts,
        transport_attempt_timeout_seconds=attempt_timeout_seconds,
    )


def _cli_web_game(game, *, backend: str = "claude"):
    """真实召对装配 + 真 CliChat model（channel=cli）。"""
    from agno.agent import Agent

    model = cb.CliChat(id="cli-model-test", backend=backend)
    agent = Agent(model=model, markdown=False)
    web_game, minister = _transport_web_game(game, agent)
    web_game.session.llm_config = SimpleNamespace(
        channel="cli", cli_runner=backend, cli_model="cli-model-test",
        cli_timeout_seconds=None, reasoning_strength="",
    )
    return web_game, minister


def test_cli_chat_stream_two_transient_then_success_three_attempts(
    monkeypatch, tmp_path, game,
):
    """①瞬断两次后第三次成功：CLI runner 与 API 同一 transport 次数账。

    注入 = 前两次子进程 rc=0 空输出（可重试 typed 空输出），第三次正常出文。
    """
    _pin_transport_policy(monkeypatch, tmp_path)
    script = install_fake_cli_runner(monkeypatch, [
        {"stdout": (), "returncode": 0},
        {"stdout": (), "returncode": 0},
        {"stdout": (_OK_REPLY,), "returncode": 0},
    ])
    web_game, minister = _cli_web_game(game)

    response = _post_chat_stream(monkeypatch, web_game, minister)
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    assert "done" in [e[0] for e in events], events
    done = next(e[1] for e in events if e[0] == "done")
    assert done.get("answer")
    attempts = done.get("transport_attempts") or []
    assert [a.get("outcome") for a in attempts] == [
        "retryable_fail", "retryable_fail", "ok",
    ], attempts
    assert script.calls == 3
    assert int(done.get("minister_message_id") or 0) > 0


def test_cli_chat_stream_three_transient_exhausted_system_fail_night_open_then_resend(
    monkeypatch, tmp_path, game,
):
    """②三次瞬断耗尽 → 系统层终失败呈现、夜不封、可重发。

    注入 = agy auth race（已知瞬断实证）；耗尽后换出文脚本重发即成。
    同一条测另钉：机器文本（`Authentication required`）一个字都不得进 delta ——
    终失败只以系统层人话呈现（票面「系统层人话报错」/ ADR 0046 否决失败戏内化）。
    """
    from ming_sim import audience_night as an

    _pin_transport_policy(monkeypatch, tmp_path)
    script = install_fake_cli_runner(monkeypatch, [
        {"stdout": ("Authentication required\n",), "returncode": 0},
    ])
    web_game, minister = _cli_web_game(game, backend="agy")
    db = web_game.db
    night_closed = {"n": 0}
    web_game.session.close_night_after_chat_if_needed = (
        lambda *_a, **_k: night_closed.__setitem__("n", night_closed["n"] + 1)
    )

    response = _post_chat_stream(monkeypatch, web_game, minister)
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    assert events[-1][0] == "error", events
    detail = events[-1][1]
    assert detail.get("code") == "llm_connection_error", detail
    attempts = detail.get("transport_attempts") or []
    assert [a.get("outcome") for a in attempts] == [
        "retryable_fail", "retryable_fail", "terminal_fail",
    ], attempts
    assert script.calls == 3
    # 机器文本不得以大臣口吻落到玩家眼前：delta 通道零机文（含重试起手的 replace）
    deltas = "".join(
        str(payload.get("content") or "") for name, payload in events if name == "delta"
    )
    assert "Authentication required" not in deltas, deltas
    assert deltas.strip() == "", deltas
    # 诊断串仍在系统层（provider_message），供复盘
    assert "Authentication required" in str(detail.get("provider_message") or ""), detail
    # 夜不封：终失败不封夜，玩家可再召
    assert night_closed["n"] == 0
    assert an.get_open_night(db) is not None

    ok_script = install_fake_cli_runner(monkeypatch, [
        {"stdout": (_OK_REPLY,), "returncode": 0},
    ])
    response2 = _post_chat_stream(monkeypatch, web_game, minister, message="再问边饷。")
    events2 = _parse_sse(response2.text)
    assert "done" in [e[0] for e in events2], events2
    done2 = next(e[1] for e in events2 if e[0] == "done")
    assert int(done2.get("minister_message_id") or 0) > 0
    assert ok_script.calls == 1
    assert an.get_open_night(db) is not None


def test_cli_chat_stream_deterministic_failure_runs_once(monkeypatch, tmp_path, game):
    """③确定性失败一次不重试：未知非零退出（无 typed status）不洗成瞬断。"""
    _pin_transport_policy(monkeypatch, tmp_path)
    script = install_fake_cli_runner(monkeypatch, [
        {"stdout": (), "stderr": ("error: unknown model\n",), "returncode": 1},
    ])
    web_game, minister = _cli_web_game(game)

    response = _post_chat_stream(monkeypatch, web_game, minister)
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    assert events[-1][0] == "error", events
    detail = events[-1][1]
    assert detail.get("code") == "llm_cli_claude", detail
    attempts = detail.get("transport_attempts") or []
    assert [a.get("outcome") for a in attempts] == ["terminal_fail"], attempts
    assert script.calls == 1


@pytest.mark.parametrize(
    "stdout",
    [(), (_OK_REPLY,)],
    ids=["empty_stdout", "nonempty_stdout"],
)
def test_cli_stdin_write_failure_fails_loudly_not_as_empty_output_retry(
    monkeypatch, tmp_path, game, stdout,
):
    """prompt 没写进 stdin = IO 错，须响亮确定性失败一次，不洗成空输出瞬断重试。

    ADR 0005：代码/IO 侧的错必须响亮；宽吞会让「子进程压根没被问」冒充
    llm_empty_output，白烧三次子进程还给玩家一个假瞬断。有 stdout 字同样终止。
    """
    _pin_transport_policy(monkeypatch, tmp_path)
    script = install_fake_cli_runner(monkeypatch, [{
        "stdout": stdout, "returncode": 0,
        "stdin_error": BrokenPipeError("stdin 已关闭"),
    }])
    web_game, minister = _cli_web_game(game)

    response = _post_chat_stream(monkeypatch, web_game, minister)
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    assert events[-1][0] == "error", events
    detail = events[-1][1]
    attempts = detail.get("transport_attempts") or []
    assert [a.get("outcome") for a in attempts] == ["terminal_fail"], attempts
    assert script.calls == 1
    assert "stdin" in str(detail.get("provider_message") or ""), detail


def test_cli_process_keeps_streaming_past_old_300s_wall(monkeypatch, tmp_path, game):
    """④持续出字跨旧 300s 硬墙不被杀（受控推进时钟，不跑真墙钟）。

    时钟间隔必须落在读循环 Empty→check_idle 可观测静默窗，不得藏在泵钩子里。
    """
    idle = 30.0
    _pin_transport_policy(monkeypatch, tmp_path, idle_timeout_seconds=idle)
    clock = {"t": 1000.0}
    monkeypatch.setattr(cb, "_cli_process_clock", lambda: clock["t"])
    silence, silence_state = _install_read_loop_silence_clock(monkeypatch, clock)

    # 每行后静默 25s（< idle 30s），19 窗累计 475s > 旧 300s 墙
    gap = 25.0
    chunks = []
    for i in range(20):
        chunks.append(f"第{i}段辽饷奏报。\n")
        if i < 19:
            chunks.append(silence(gap))
    script = install_fake_cli_runner(monkeypatch, [{
        "stdout": tuple(chunks),
        "returncode": 0,
    }])
    web_game, minister = _cli_web_game(game)

    response = _post_chat_stream(monkeypatch, web_game, minister)
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    assert "done" in [e[0] for e in events], events
    done = next(e[1] for e in events if e[0] == "done")
    assert int(silence_state["checks"]) >= 19, silence_state
    assert float(silence_state["injected_total"]) > 300.0, silence_state
    assert clock["t"] - 1000.0 > 300.0, clock
    assert script.calls == 1
    attempts = done.get("transport_attempts") or []
    assert [a.get("outcome") for a in attempts] == ["ok"], attempts
    assert int(done.get("minister_message_id") or 0) > 0


def test_cli_process_idle_over_budget_dies_then_retry_succeeds(
    monkeypatch, tmp_path, game,
):
    """⑤静默超阈值判死并重试；每 attempt 独立整份 idle 预算（受控时钟）。

    对照：完全无字节超 idle 仍判死可重试；无换行字节持续到达（间隔 < idle、
    累计 > idle）不算静默，不被杀。间隔必须经读循环 Empty→check_idle 注入，
    泵钩子自累不得当判据。
    """
    idle = 30.0
    _pin_transport_policy(monkeypatch, tmp_path, idle_timeout_seconds=idle)
    clock = {"t": 500.0}
    monkeypatch.setattr(cb, "_cli_process_clock", lambda: clock["t"])
    silence, silence_state = _install_read_loop_silence_clock(monkeypatch, clock)

    def _advance_while_silent() -> None:
        # 首 attempt 一个字节都不出：受控时钟持续推进 → 静默超预算判死
        clock["t"] += 5.0

    # 无换行块之间插入主环可观测静默：间隔 0.4*idle < idle，三窗累计 1.2*idle > idle
    gap = idle * 0.4
    no_nl_chunks = (
        "臣已核",
        silence(gap),
        "辽饷，",
        silence(gap),
        "又续报，",
        silence(gap),
        "谨复奏。\n",
    )

    script = install_fake_cli_runner(monkeypatch, [
        {"stdout": (SilentUntilKilled(on_tick=_advance_while_silent),), "returncode": 0},
        {"stdout": no_nl_chunks, "returncode": 0},
    ])
    web_game, minister = _cli_web_game(game)

    response = _post_chat_stream(monkeypatch, web_game, minister)
    assert response.status_code == 200, response.text
    events = _parse_sse(response.text)
    assert "done" in [e[0] for e in events], events
    done = next(e[1] for e in events if e[0] == "done")
    attempts = done.get("transport_attempts") or []
    assert [a.get("outcome") for a in attempts] == ["retryable_fail", "ok"], attempts
    assert attempts[0].get("code") == "llm_idle_timeout", attempts
    assert script.calls == 2
    # 首 attempt 的子进程确实被 kill（不留孤儿）
    assert script.processes[0].killed.is_set()
    # 判别力：attempt2 静默窗经主环 check_idle 注入，累计 > idle（非钩子自累）
    assert int(silence_state["checks"]) >= 3, silence_state
    assert float(silence_state["injected_total"]) > idle, silence_state
    assert int(done.get("minister_message_id") or 0) > 0
