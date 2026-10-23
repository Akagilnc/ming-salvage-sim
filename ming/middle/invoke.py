"""One transport retry policy, independent of declaration validation retries."""

import asyncio
from collections.abc import AsyncIterable, Awaitable, Callable, Coroutine, Sequence
from typing import Any, Literal, TypeVar, cast

from httpx2 import TimeoutException
from openai import APIConnectionError
from pydantic import BaseModel, model_validator
from pydantic_ai import Agent, AgentRunResult, RunContext, Tool
from pydantic_ai.messages import (
    AgentStreamEvent,
    PartStartEvent,
    PartDeltaEvent,
    TextPart,
    TextPartDelta,
)
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.models import Model, infer_model
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_fixed

from ming.middle.cli_model import ClaudeCliModel, CliHost, GrokCliModel, PiCliModel
from ming.middle.codex_auth import codex_model

T = TypeVar("T")
D = TypeVar("D")


class Settings(BaseModel):
    backend: Literal["api", "claude-cli", "codex", "grok", "pi"] = "api"
    model: str = ""
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""

    @model_validator(mode="after")
    def codex_has_model(self) -> "Settings":
        if self.backend == "codex" and not self.model.strip():
            raise ValueError("codex requires a model id")
        return self


ModelSource = Model | Settings | str


def configured_model(settings: Settings) -> Model:
    if settings.backend == "claude-cli":
        return ClaudeCliModel(settings.model)
    if settings.backend == "grok":
        return GrokCliModel(settings.model)
    if settings.backend == "pi":
        return PiCliModel(settings.model)
    if settings.backend == "codex":
        return codex_model(settings.model)
    return OpenAIChatModel(
        settings.model or "gpt-4.1",
        provider=OpenAIProvider(
            base_url=settings.base_url, api_key=settings.api_key or "not-configured"
        ),
    )


def named_model(model: str) -> Model:
    if model == "claude-cli":
        return ClaudeCliModel()
    if model == "grok" or model.startswith("grok:"):
        return GrokCliModel(model[5:] if model.startswith("grok:") else "")
    if model == "pi" or model.startswith("pi:"):
        return PiCliModel(model[3:] if model.startswith("pi:") else "")
    if model == "codex" or model.startswith(("codex:", "openai-codex:")):
        name = model.split(":", 1)[1] if ":" in model else ""
        return codex_model(name)
    return infer_model(model)


def build_agent(
    model: ModelSource,
    *,
    tools: Sequence[Callable[..., Any] | Tool[Any]] = (),
    **kwargs: Any,
) -> Agent[Any, Any]:
    """Declare a call once, including its native transport and callable tools."""
    if isinstance(model, Settings):
        model = configured_model(model)
    elif isinstance(model, str):
        model = named_model(model)
    declared: list[Tool[Any]] = [
        cast(Tool[Any], tool) if isinstance(tool, Tool) else Tool[Any](tool)
        for tool in tools
    ]
    if isinstance(model, CliHost):
        model = type(model)(model.cli_name, declared)
    if isinstance(model, (OpenAIChatModel, OpenAIResponsesModel)):
        model.client.max_retries = 0
    return Agent(model, tools=declared, **kwargs)


def transient(error: BaseException) -> bool:
    return (
        isinstance(error, (TimeoutException, TimeoutError))
        or (isinstance(error, ModelHTTPError) and 500 <= error.status_code < 600)
        or (
            isinstance(error, ModelAPIError)
            and isinstance(error.__cause__, APIConnectionError)
        )
    )


async def stream_text(
    on_delta: Callable[[str], None],
    _ctx: RunContext[Any],
    stream: AsyncIterable[AgentStreamEvent],
) -> None:
    """Forward native text events without exposing tools or reasoning."""
    async for event in stream:
        if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
            on_delta(event.part.content)
        elif isinstance(event, PartDeltaEvent) and isinstance(
            event.delta, TextPartDelta
        ):
            on_delta(event.delta.content_delta)


async def invoke(
    agent: Agent[D, T], prompt: str | list[str], **kwargs: Any
) -> AgentRunResult[T]:
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_fixed(5),
        retry=retry_if_exception(transient),
        reraise=True,
    ):
        with attempt:
            return await agent.run(prompt, **kwargs)
    raise AssertionError("tenacity completed without a result")


async def gather_or_raise(*awaitables: Awaitable[T]) -> list[T]:
    """Run the awaitables; the first failure is the result, not a swallowed one."""
    results = await asyncio.gather(*awaitables, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result
    return cast(list[T], results)


K = TypeVar("K")


def enlist(
    tasks: dict[K, asyncio.Task[T]],
    key: K,
    start: Callable[[], Coroutine[Any, Any, T]],
    *,
    replace: bool = False,
    on_done: Callable[[asyncio.Task[T]], object] | None = None,
) -> asyncio.Task[T]:
    """One in-flight task per key. A done task is replaced only when asked."""
    current = tasks.get(key)
    if current is None or (replace and current.done()):
        current = tasks[key] = asyncio.create_task(start())
        if on_done is not None:
            current.add_done_callback(on_done)
    return current
