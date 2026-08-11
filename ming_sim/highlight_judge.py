"""Bounded, best-effort highlight judging for completed minister replies (#544)."""
from __future__ import annotations

import copy
import json
import multiprocessing
import os
import signal
import sys
import threading
import time
from typing import Any, Callable, List

from ming_sim.token_stats import tlog

DEFAULT_TIMEOUT_SECONDS = 3.0


def parse_highlights(raw: Any) -> List[str]:
    """Accept only the judge's hard JSON contract: an array of strings."""
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        return []
    return value


def invoke_highlight_judge(
    reply: str, llm_config: Any, *, timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> str:
    """Use the player's configured channel; no alternate model or fallback."""
    from agno.agent import Agent
    from ming_sim.llm_model import create_chat_model, extract_agent_text

    bounded_config = copy.copy(llm_config)
    budget = max(0.0, float(timeout))
    bounded_config.timeout_seconds = budget
    if getattr(bounded_config, "channel", "") == "cli":
        bounded_config.cli_timeout_seconds = budget
    agent = Agent(
        name="奏对高亮判官", id="audience-highlight-judge",
        model=create_chat_model(
            bounded_config, temperature=0, max_tokens=256, max_retries=0,
        ),
        instructions=[
            "找出最值得皇帝扫读的大臣原话短语。只输出 JSON 字符串数组；没有则输出 []。",
            "数组元素必须逐字来自给定回话，不输出解释、markdown 或其它字段。",
        ],
        markdown=False,
    )
    return extract_agent_text(agent.run(reply))


_DEFAULT_INVOKE = invoke_highlight_judge


def _invoke_in_worker(send: Any, invoke: Callable[..., Any], reply: str,
                      llm_config: Any, timeout: float) -> None:
    """Own the adapter and every subprocess it starts in one cancellable process group."""
    try:
        # POSIX descendants inherit a private process group. Windows has no setpgid;
        # the spawned worker itself remains the supported cancellation boundary.
        owns_group = sys.platform != "win32"
        if owns_group:
            os.setpgid(0, 0)
            if os.getpgrp() != os.getpid():
                raise RuntimeError("highlight judge worker has no private process group")
        send.send(("ready", os.getpid(), owns_group))
        if send.recv() != ("run",):
            raise RuntimeError("highlight judge worker was not released")
        send.send(("result", True, invoke(reply, llm_config, timeout=timeout)))
    except BaseException as error:
        send.send(("result", False, type(error).__name__, str(error)))
    finally:
        send.close()


def _cancel_owned_work(process: Any, owns_group: bool) -> None:
    """Gracefully cancel owned work without ever escalating to SIGKILL."""
    if not process.is_alive():
        return
    try:
        if owns_group:
            os.killpg(process.pid, signal.SIGTERM)
        elif sys.platform == "win32":
            process.terminate()
        else:
            os.kill(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass


def _reap_later(process: Any) -> None:
    """Reap a SIGTERM-resistant worker off the latency-critical caller path."""
    process.join()


def _bounded_reap(process: Any, deadline: float) -> None:
    process.join(max(0.0, deadline - time.monotonic()))
    if process.is_alive():
        tlog("[audience-highlights] 判官忽略温和终止；已脱离回话路径等待回收")
        threading.Thread(
            target=_reap_later, args=(process,), daemon=True,
            name="audience-highlight-reaper",
        ).start()


def _invoke_before_deadline(reply: str, llm_config: Any, timeout: float,
                            invoke: Callable[..., Any]) -> Any:
    """Run even an uncooperative adapter in work that can be stopped and reaped."""
    budget = max(0.0, float(timeout))
    if budget == 0:
        raise TimeoutError("highlight judge deadline exceeded")
    # Production uses spawn: forking the multi-threaded web process can inherit locked
    # provider/runtime state.  Injected test doubles may be local callables, so their
    # isolated test worker uses fork; they never initialize the real provider stack.
    method = "spawn" if sys.platform == "win32" or invoke is _DEFAULT_INVOKE else "fork"
    context = multiprocessing.get_context(method)
    receive, send = context.Pipe(duplex=True)
    process = context.Process(
        target=_invoke_in_worker,
        args=(send, invoke, reply, llm_config, budget),
        name="audience-highlight-judge",
    )
    # Reserve a small cancellation/reap slice inside the public deadline.  In
    # particular this makes the owner, not subprocess.run's hard timeout path,
    # win the race and deliver graceful SIGTERM to CLI descendants.
    reap_margin = min(0.05, budget * 0.1)
    deadline = time.monotonic() + budget - reap_margin
    started = False
    owns_group = False
    try:
        process.start()
        started = True
        send.close()
        while True:
            remaining = max(0.0, deadline - time.monotonic())
            if not receive.poll(remaining):
                raise TimeoutError("highlight judge deadline exceeded")
            message = receive.recv()
            if message[0] == "ready":
                if message[1] != process.pid:
                    raise RuntimeError("highlight judge worker group identity mismatch")
                owns_group = bool(message[2])
                receive.send(("run",))
                continue
            if message[1]:
                return message[2]
            raise RuntimeError(f"{message[2]}: {message[3]}")
    finally:
        receive.close()
        if started:
            _cancel_owned_work(process, owns_group)
            _bounded_reap(process, time.monotonic() + reap_margin)


def judge_highlights(
    reply: str, llm_config: Any, *, timeout: float = DEFAULT_TIMEOUT_SECONDS,
    invoke: Callable[..., Any] | None = None,
) -> List[str]:
    """Bound the real adapter invocation; failures and malformed output are decoration-only."""
    invoke = invoke or invoke_highlight_judge
    try:
        result = _invoke_before_deadline(reply, llm_config, timeout, invoke)
    except Exception as error:  # provider timeout / unavailable judge are best-effort
        tlog(f"[audience-highlights] 判官调用失败：{type(error).__name__}: {error}")
        return []
    highlights = parse_highlights(result)
    if not highlights and result not in ([], "[]"):
        tlog("[audience-highlights] 判官输出不符合 JSON 字符串数组契约")
    return highlights
