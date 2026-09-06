"""#1465 LLM transport 重试/超时/分类单真源。

策略（次数、每 attempt 整份超时、空转超时）只在此处与 runtime 配置区定义；
流式 attempt 循环、可重试分类、系统层终失败出口均只此一处。
CLI runner 与外层截断点由切片③迁移；本模块 API 流入口先用。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable, List, Optional, TypeVar

from openai import APIConnectionError, APIStatusError, APITimeoutError

from ming_sim.exceptions import LLMUnavailable
from ming_sim.models import (
    TRANSPORT_DEFAULT_ATTEMPT_TIMEOUT_SECONDS,
    TRANSPORT_DEFAULT_IDLE_TIMEOUT_SECONDS,
    TRANSPORT_DEFAULT_MAX_ATTEMPTS,
)

R = TypeVar("R")


@dataclass(frozen=True)
class TransportPolicy:
    """统一 transport 预算。字段全部来自配置默认或 runtime 覆盖。"""

    max_attempts: int = TRANSPORT_DEFAULT_MAX_ATTEMPTS
    attempt_timeout_seconds: float = TRANSPORT_DEFAULT_ATTEMPT_TIMEOUT_SECONDS
    idle_timeout_seconds: float = TRANSPORT_DEFAULT_IDLE_TIMEOUT_SECONDS


@dataclass(frozen=True)
class TransportAttempt:
    """单次 attempt 账——供验收回指（≠ error_pack 写包序号）。"""

    index: int  # 1-based
    outcome: str  # "ok" | "retryable_fail" | "terminal_fail"
    code: str = ""
    status_code: Optional[int] = None
    provider_message: str = ""


@dataclass(frozen=True)
class ClassifiedFailure:
    retryable: bool
    code: str
    status_code: Optional[int]
    provider_message: str
    message: str


class TransportIdleTimeout(Exception):
    """流式空转：距上次输出超过 idle_timeout。"""


class TransportAttemptTimeout(Exception):
    """单 attempt 整份超时耗尽。"""


def default_transport_policy() -> TransportPolicy:
    return TransportPolicy()


def transport_attempts_public(attempts: List[TransportAttempt]) -> List[dict]:
    """结构化 attempts 投影（机器可回指；不锁文案）。"""
    return [
        {
            "index": a.index,
            "outcome": a.outcome,
            "code": a.code,
            "status_code": a.status_code,
        }
        for a in attempts
    ]


def transport_policy_from_mapping(data: object) -> TransportPolicy:
    """从 runtime 映射归一策略。数值解析单权威 = llm_config._transport_runtime_slot。"""
    from ming_sim.llm_config import transport_runtime_slot

    if not isinstance(data, dict):
        return default_transport_policy()
    src = data.get("transport") if isinstance(data.get("transport"), dict) else data
    if not isinstance(src, dict):
        return default_transport_policy()
    slot = transport_runtime_slot(src)
    return TransportPolicy(
        max_attempts=int(slot["max_attempts"]),
        attempt_timeout_seconds=float(slot["attempt_timeout_seconds"]),
        idle_timeout_seconds=float(slot["idle_timeout_seconds"]),
    )


def resolve_transport_policy(source: object = None) -> TransportPolicy:
    """解析策略：显式 policy/mapping/带字段对象 → runtime_llm.json transport 段 → 默认。"""
    if isinstance(source, TransportPolicy):
        return source
    if isinstance(source, dict):
        return transport_policy_from_mapping(source)
    if source is not None:
        # 仅当对象显式带 transport_* 字段时视为覆盖；否则落到 runtime 文件
        max_a = getattr(source, "transport_max_attempts", None)
        att = getattr(source, "transport_attempt_timeout_seconds", None)
        idle = getattr(source, "transport_idle_timeout_seconds", None)
        if any(v is not None for v in (max_a, att, idle)):
            return transport_policy_from_mapping(
                {
                    "max_attempts": max_a,
                    "attempt_timeout_seconds": att,
                    "idle_timeout_seconds": idle,
                }
            )
    try:
        from ming_sim.llm_config import load_runtime_llm

        runtime = load_runtime_llm()
        if runtime:
            return transport_policy_from_mapping(runtime)
    except Exception:  # noqa: BLE001 — 配置旁路失败不得阻断调用；回落默认
        pass
    return default_transport_policy()


def classify_transport_failure(error: BaseException) -> ClassifiedFailure:
    """先分类后重试。只认 typed 信号；不从错误散文猜语义（ADR 0142）。

    可重试：瞬断/空转/5xx/408/429/空输出。
    不可重试：确定性 4xx（#1452 Unknown model 等带 4xx status）。
    未知（无 status 的笼统 stream/run error）→ 不洗成瞬断，立即上浮。

    本函数是 APITimeout/Connection/Status → code/retryable 的唯一权威
    （llm_unavailable_from_error 委派于此）。
    """
    if isinstance(error, TransportIdleTimeout):
        return ClassifiedFailure(
            retryable=True,
            code="llm_idle_timeout",
            status_code=None,
            provider_message=str(error) or "idle timeout",
            message="LLM 调用空转超时。",
        )
    if isinstance(error, TransportAttemptTimeout):
        return ClassifiedFailure(
            retryable=True,
            code="llm_timeout",
            status_code=None,
            provider_message=str(error) or "attempt timeout",
            message="LLM 调用超时。",
        )
    if isinstance(error, APITimeoutError):
        return ClassifiedFailure(
            retryable=True,
            code="llm_timeout",
            status_code=None,
            provider_message=str(error),
            message="LLM 调用超时。",
        )
    if isinstance(error, APIConnectionError):
        return ClassifiedFailure(
            retryable=True,
            code="llm_connection_error",
            status_code=None,
            provider_message=str(error),
            message="LLM 连接失败。",
        )
    if isinstance(error, APIStatusError):
        status = getattr(error, "status_code", None)
        try:
            status_i = int(status) if status is not None else None
        except (TypeError, ValueError):
            status_i = None
        code = f"llm_http_{status_i}" if status_i is not None else "llm_http_error"
        retryable = status_i is not None and (
            status_i >= 500 or status_i in {408, 429}
        )
        return ClassifiedFailure(
            retryable=retryable,
            code=code,
            status_code=status_i,
            provider_message=str(error),
            message=f"LLM 调用失败（HTTP {status_i}）。" if status_i else "LLM 调用失败。",
        )
    if isinstance(error, LLMUnavailable):
        status = error.status_code
        code = str(error.code or "llm_unavailable")
        pmsg = str(error.provider_message or error.message or "")
        if status is not None:
            try:
                status_i = int(status)
            except (TypeError, ValueError):
                status_i = None
            if status_i is not None:
                retryable = status_i >= 500 or status_i in {408, 429}
                return ClassifiedFailure(
                    retryable=retryable,
                    code=code,
                    status_code=status_i,
                    provider_message=pmsg,
                    message=str(error.message or pmsg or "LLM 调用失败。"),
                )
        if code in {
            "llm_timeout",
            "llm_connection_error",
            "llm_idle_timeout",
            "llm_empty_output",
        }:
            return ClassifiedFailure(
                retryable=True,
                code=code,
                status_code=None,
                provider_message=pmsg,
                message=str(error.message or pmsg or "LLM 调用失败。"),
            )
        if code.startswith("llm_http_"):
            tail = code[len("llm_http_") :]
            try:
                status_i = int(tail)
            except ValueError:
                status_i = None
            if status_i is not None:
                retryable = status_i >= 500 or status_i in {408, 429}
                return ClassifiedFailure(
                    retryable=retryable,
                    code=code,
                    status_code=status_i,
                    provider_message=pmsg,
                    message=str(error.message or pmsg or "LLM 调用失败。"),
                )
        # 未知 typed 失败：不洗成瞬断
        return ClassifiedFailure(
            retryable=False,
            code=code,
            status_code=None,
            provider_message=pmsg,
            message=str(error.message or pmsg or "LLM 调用失败。"),
        )
    # 未识别异常：保真上浮，不重试（0005 响亮；不洗成瞬断）
    return ClassifiedFailure(
        retryable=False,
        code="llm_error",
        status_code=None,
        provider_message=str(error),
        message=f"LLM 调用失败：{error}",
    )


def transport_failure_unavailable(
    failure: ClassifiedFailure,
    *,
    attempts: int,
    exhausted: bool,
    attempt_records: Optional[List[TransportAttempt]] = None,
) -> LLMUnavailable:
    """系统层终失败呈现（P7 / ADR 0046）：不用固定戏内话术。"""
    if exhausted and attempts > 1:
        message = (
            f"LLM 调用失败（已尝试 {attempts} 次）："
            f"{failure.provider_message or failure.message}"
        )
    else:
        message = failure.message or f"LLM 调用失败：{failure.provider_message}"
    return LLMUnavailable(
        message,
        code=failure.code,
        provider_message=failure.provider_message or message,
        status_code=failure.status_code,
        transport_attempts=(
            transport_attempts_public(attempt_records) if attempt_records else None
        ),
    )


def empty_output_failure() -> ClassifiedFailure:
    return ClassifiedFailure(
        retryable=True,
        code="llm_empty_output",
        status_code=None,
        provider_message="empty output",
        message="LLM 调用失败：流式回复为空。",
    )


def run_error_event_failure(content: object = None) -> ClassifiedFailure:
    """RunErrorEvent → 分类。无 typed status 时不洗成瞬断（#1452 确定性失败）。"""
    pmsg = str(content or "").strip() or "stream error"
    return ClassifiedFailure(
        retryable=False,
        code="llm_stream_error",
        status_code=None,
        provider_message=pmsg,
        message=f"LLM 流式调用失败：{pmsg}",
    )


def check_attempt_budgets(
    *,
    attempt_started_at: float,
    last_output_at: float,
    policy: TransportPolicy,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    """在事件边界检查空转/整份超时；超限抛 Transport*Timeout（可重试）。

    SDK 层 timeout 亦绑 policy.attempt_timeout_seconds（create_chat_model），
    无事件挂死由 SDK 墙钟承接；本检查覆盖有事件推进的受控时钟与空转。
    """
    now = clock()
    if now - last_output_at >= policy.idle_timeout_seconds:
        raise TransportIdleTimeout(f"idle > {policy.idle_timeout_seconds}s")
    if now - attempt_started_at >= policy.attempt_timeout_seconds:
        raise TransportAttemptTimeout(
            f"attempt wall > {policy.attempt_timeout_seconds}s"
        )


def run_with_transport(
    operation: Callable[[], R],
    *,
    policy: Optional[TransportPolicy] = None,
    clock: Callable[[], float] = time.monotonic,
    output_emitted: Optional[Callable[[], bool]] = None,
) -> tuple[R, List[TransportAttempt]]:
    """整次 attempt 闭包重试。operation 内可抛异常；成功返回 (result, attempts)。

    output_emitted：若已向玩家发出可见输出，失败后不再重试（半流不另造缓冲规则）。
    """
    del clock  # 预算检查在 operation 内用同一 clock；此处仅保留签名对称
    pol = policy or default_transport_policy()
    attempts: List[TransportAttempt] = []
    last: Optional[ClassifiedFailure] = None
    max_attempts = pol.max_attempts

    for index in range(1, max_attempts + 1):
        try:
            result = operation()
            attempts.append(TransportAttempt(index=index, outcome="ok", code="ok"))
            return result, attempts
        except Exception as error:  # noqa: BLE001 — 分类后按契约重试或上浮
            failure = classify_transport_failure(error)
            last = failure
            emitted = bool(output_emitted and output_emitted())
            will_retry = failure.retryable and not emitted and index < max_attempts
            attempts.append(
                TransportAttempt(
                    index=index,
                    outcome="retryable_fail" if will_retry else "terminal_fail",
                    code=failure.code,
                    status_code=failure.status_code,
                    provider_message=failure.provider_message,
                )
            )
            if will_retry:
                continue
            # 非 transport 域的编程/未知异常原样上浮（0005 响亮；不改 message）
            if failure.code == "llm_error" and not isinstance(error, LLMUnavailable):
                raise error
            raise transport_failure_unavailable(
                failure,
                attempts=len(attempts),
                exhausted=failure.retryable and index >= max_attempts,
                attempt_records=attempts,
            ) from error

    assert last is not None
    raise transport_failure_unavailable(
        last,
        attempts=len(attempts),
        exhausted=True,
        attempt_records=attempts,
    )


def run_transport_stream(
    start_stream: Callable[[], Iterable[Any]],
    *,
    on_event: Callable[[Any], None],
    is_output_event: Callable[[Any], bool],
    map_error_event: Callable[[Any], Optional[BaseException]],
    after_stream: Callable[[], R],
    policy: Optional[TransportPolicy] = None,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[R, List[TransportAttempt]]:
    """流式 attempt 循环唯一权威：预算检查 + 分类重试 + 半流不重试。

    召对 web 与 agents.run_agent_stream_text 共用本函数，禁止各自手写循环。
    """
    pol = policy or default_transport_policy()
    emitted = {"n": 0}

    def _one_attempt() -> R:
        attempt_started_at = clock()
        last_output_at = attempt_started_at
        stream = start_stream()
        for event in stream:
            check_attempt_budgets(
                attempt_started_at=attempt_started_at,
                last_output_at=last_output_at,
                policy=pol,
                clock=clock,
            )
            err = map_error_event(event)
            if err is not None:
                raise err
            if is_output_event(event):
                last_output_at = clock()
                emitted["n"] += 1
            on_event(event)
        return after_stream()

    return run_with_transport(
        _one_attempt,
        policy=pol,
        clock=clock,
        output_emitted=lambda: emitted["n"] > 0,
    )
