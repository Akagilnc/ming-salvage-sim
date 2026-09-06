"""#1465 LLM transport 重试/超时/分类单真源。

策略（次数、空转超时）只在此处与 runtime 配置区定义；
流式 attempt 循环、可重试分类、系统层终失败出口均只此一处。
切片①仅接线真实 API 召对流；CLI runner / 公共流 / 非流式由后续切片迁移。

超时所有权（切片①诊断结论）：
- 事件迭代阻塞（等下一 chunk）由既有 SDK/httpx read timeout 控制，不可用事件边界检查冒充静默可中止。
- 事件边界只做空转判死（距上次活动超时）；不设 attempt 总墙钟（宪法 #9）。
- 每次 attempt 重新取得完整空转预算。
- SDK timeout/max_retries 仅在已迁移召对接缝按 policy 覆盖；create_chat_model 默认保留未迁移调用原行为。
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Iterator, List, Optional, TypeVar

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
    # attempt_timeout_seconds：非流式/SDK 读超时预算（与 idle 同默认；流式空转用 idle）。
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
    """流式空转：距上次活动超过 idle_timeout。"""


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
    """解析策略：显式 policy/mapping/带字段对象 → runtime_llm.json transport 段 → 默认。

    load_runtime_llm 自身已对缺/坏档回空 dict（不宽吞未知异常）；此处不再 except Exception。
    """
    if isinstance(source, TransportPolicy):
        return source
    if isinstance(source, dict):
        return transport_policy_from_mapping(source)
    if source is not None:
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
    from ming_sim.llm_config import load_runtime_llm

    runtime = load_runtime_llm()
    if runtime:
        return transport_policy_from_mapping(runtime)
    return default_transport_policy()


def _status_retryable(status_i: Optional[int]) -> bool:
    return status_i is not None and (status_i >= 500 or status_i in {408, 429})


def _coerce_status(status: object) -> Optional[int]:
    if status is None:
        return None
    try:
        return int(status)
    except (TypeError, ValueError):
        return None


def classify_transport_failure(error: BaseException) -> ClassifiedFailure:
    """先分类后重试。只认 typed 信号；不从错误散文猜语义（ADR 0142）。

    可重试：瞬断/空转/5xx/408/429/空输出。
    不可重试：确定性 4xx（#1452 Unknown model 等带 4xx status）。
    未知（无 status 的笼统 stream/run error）→ 不洗成瞬断，立即上浮。

    本函数是 APITimeout/Connection/Status/空输出/RunError → code/retryable/status 的唯一权威
    （llm_unavailable_from_error / run_error_event_failure / empty_output_failure 委派或同构）。
    """
    if isinstance(error, TransportIdleTimeout):
        return ClassifiedFailure(
            retryable=True,
            code="llm_idle_timeout",
            status_code=None,
            provider_message=str(error) or "idle timeout",
            message="LLM 调用空转超时。",
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
        status_i = _coerce_status(getattr(error, "status_code", None))
        code = f"llm_http_{status_i}" if status_i is not None else "llm_http_error"
        return ClassifiedFailure(
            retryable=_status_retryable(status_i),
            code=code,
            status_code=status_i,
            provider_message=str(error),
            message=f"LLM 调用失败（HTTP {status_i}）。" if status_i else "LLM 调用失败。",
        )
    if isinstance(error, LLMUnavailable):
        status = error.status_code
        code = str(error.code or "llm_unavailable")
        pmsg = str(error.provider_message or error.message or "")
        status_i = _coerce_status(status)
        if status_i is not None:
            return ClassifiedFailure(
                retryable=_status_retryable(status_i),
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
            status_from_code = _coerce_status(tail)
            if status_from_code is not None:
                return ClassifiedFailure(
                    retryable=_status_retryable(status_from_code),
                    code=code,
                    status_code=status_from_code,
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
    """空输出失败唯一构造（web/agents 同权威）。"""
    return ClassifiedFailure(
        retryable=True,
        code="llm_empty_output",
        status_code=None,
        provider_message="empty output",
        message="LLM 调用失败：流式回复为空。",
    )


def run_error_event_failure(content: object = None) -> ClassifiedFailure:
    """RunErrorEvent → 分类唯一构造。无 typed status 时不洗成瞬断（#1452）。"""
    pmsg = str(content or "").strip() or "stream error"
    return ClassifiedFailure(
        retryable=False,
        code="llm_stream_error",
        status_code=None,
        provider_message=pmsg,
        message=f"LLM 流式调用失败：{pmsg}",
    )


def check_idle_budget(
    *,
    last_activity_at: float,
    policy: TransportPolicy,
    clock: Optional[Callable[[], float]] = None,
) -> None:
    """事件边界空转检查；超限抛 TransportIdleTimeout（可重试）。

    不检查 attempt 总墙钟。事件迭代阻塞期间的静默由 SDK read timeout 控制
    （见 bind_transport_sdk_budget），本函数不能也不冒充可中止该阻塞。
    """
    now = (clock or time.monotonic)()
    if now - last_activity_at >= policy.idle_timeout_seconds:
        raise TransportIdleTimeout(f"idle > {policy.idle_timeout_seconds}s")


@contextmanager
def bind_transport_sdk_budget(model: object, policy: TransportPolicy) -> Iterator[None]:
    """仅在已迁移 API 召对接缝临时覆盖 SDK timeout/max_retries。

    - timeout → idle 预算：流式 read 静默由 SDK 承接（与事件界空转同量级）
    - max_retries → 0：attempt 计数归本模块，禁 SDK 双重点数
    退出后恢复原值并丢弃缓存 client，避免污染未迁移的同 model 非流路径。
    """
    if model is None:
        yield
        return
    prev_timeout = getattr(model, "timeout", None)
    prev_retries = getattr(model, "max_retries", None)
    had_client = hasattr(model, "client")
    had_async = hasattr(model, "async_client")
    try:
        if hasattr(model, "timeout"):
            model.timeout = policy.idle_timeout_seconds
        if hasattr(model, "max_retries"):
            model.max_retries = 0
        # 丢缓存 client，使临时 timeout/retries 生效
        if had_client:
            model.client = None
        if had_async:
            model.async_client = None
        yield
    finally:
        if hasattr(model, "timeout"):
            model.timeout = prev_timeout
        if hasattr(model, "max_retries"):
            model.max_retries = prev_retries
        # 再丢缓存，避免绑了临时预算的 client 泄漏到未迁移路径
        if had_client:
            model.client = None
        if had_async:
            model.async_client = None


def run_with_transport(
    operation: Callable[[], R],
    *,
    policy: Optional[TransportPolicy] = None,
) -> tuple[R, List[TransportAttempt]]:
    """整次 attempt 闭包重试。operation 内可抛异常；成功返回 (result, attempts)。

    半流：不设「任一输出后一律不重试」。已呈现正文的相容由既有落账/恢复接缝承担；
    不在此新增缓冲、去重或回滚立法。
    """
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
            will_retry = failure.retryable and index < max_attempts
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
    is_activity_event: Callable[[Any], bool],
    map_error_event: Callable[[Any], Optional[BaseException]],
    after_stream: Callable[[], R],
    policy: Optional[TransportPolicy] = None,
    clock: Optional[Callable[[], float]] = None,
) -> tuple[R, List[TransportAttempt]]:
    """流式 attempt 循环唯一权威：空转预算 + 分类重试。

    is_activity_event：推进空转计时的活动（含 reasoning 等非玩家正文信号）。
    活动 ≠ 已呈现正文；不据此禁止重试。
    clock 在调用时解析（便于测试 patch time.monotonic）。
    """
    pol = policy or default_transport_policy()
    tick = clock or time.monotonic

    def _one_attempt() -> R:
        # 每次 attempt 完整空转预算
        last_activity_at = tick()
        stream = start_stream()
        for event in stream:
            check_idle_budget(
                last_activity_at=last_activity_at,
                policy=pol,
                clock=tick,
            )
            err = map_error_event(event)
            if err is not None:
                raise err
            if is_activity_event(event):
                last_activity_at = tick()
            on_event(event)
        return after_stream()

    return run_with_transport(_one_attempt, policy=pol)
