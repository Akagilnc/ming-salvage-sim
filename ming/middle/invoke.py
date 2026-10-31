"""One transport retry policy, independent of declaration validation retries."""

import asyncio
import json
from collections.abc import AsyncIterable, Awaitable, Callable, Sequence
from typing import Any, Literal, TypeVar, cast

from httpx2 import TimeoutException
from openai import APIConnectionError
from pydantic import BaseModel, field_validator, model_validator
from pydantic_ai import Agent, AgentRunResult, RunContext, Tool
from pydantic_ai.messages import (
    AgentStreamEvent,
    PartStartEvent,
    PartDeltaEvent,
    TextPart,
    TextPartDelta,
)
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from pydantic_ai.toolsets.function import FunctionToolset
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_fixed

from ming.middle.cli_model import ClaudeCliModel, CliHost, GrokCliModel, PiCliModel
from ming.middle.codex_auth import codex_model

T = TypeVar("T")
D = TypeVar("D")


# Shared by the settings form and the optional channel's completeness check.
REQUIRED_SETTINGS = {"api": ("model", "base_url"), "codex": ("model",)}


class Settings(BaseModel):
    backend: Literal["api", "claude-cli", "codex", "grok", "pi"] = "api"
    model: str = ""
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    effort: str = ""

    @model_validator(mode="after")
    def codex_has_model(self) -> "Settings":
        if self.backend == "codex" and not self.model.strip():
            raise ValueError("codex requires a model id")
        return self


class Configuration(Settings):
    month_model: Settings | None = None

    @field_validator("month_model", mode="before")
    @classmethod
    def complete_channel(cls, value: Any) -> Any:
        if not value:
            return None
        if isinstance(value, dict):
            value = cast(dict[str, Any], value)
            if not value.get("backend") or any(
                not value.get(key, "").strip()
                for key in REQUIRED_SETTINGS.get(value["backend"], ())
            ):
                return None
        return value


ModelSource = Model | Settings
TextUpdate = str | dict[str, str]


def configured_model(settings: ModelSource) -> Model:
    if isinstance(settings, Model):
        model = settings
    elif settings.backend == "claude-cli":
        model = ClaudeCliModel(settings.model, effort=settings.effort)
    elif settings.backend == "grok":
        model = GrokCliModel(settings.model, effort=settings.effort)
    elif settings.backend == "pi":
        model = PiCliModel(settings.model, effort=settings.effort)
    else:
        native_settings = (
            cast(ModelSettings, {"openai_reasoning_effort": settings.effort})
            if settings.effort else None
        )
        if settings.backend == "codex":
            model = codex_model(settings.model, settings=native_settings)
        else:
            model = OpenAIChatModel(
                settings.model or "gpt-4.1",
                settings=native_settings,
                provider=OpenAIProvider(
                    base_url=settings.base_url, api_key=settings.api_key or "not-configured"
                ),
            )
    if isinstance(model, (OpenAIChatModel, OpenAIResponsesModel)):
        model.client.max_retries = 0
    return model


def build_agent(
    *, tools: Sequence[Callable[..., Any] | Tool[Any]] = (), **kwargs: Any,
) -> Agent[Any, Any]:
    """Define a call once; its model and dependencies belong to each run."""
    return Agent(tools=tools, **kwargs)


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
    on_delta: Callable[[TextUpdate], None],
    _ctx: RunContext[Any],
    stream: AsyncIterable[AgentStreamEvent],
) -> None:
    """Forward text deltas or an atomic replacement of the live text."""
    started: set[int] = set()
    async for event in stream:
        if isinstance(event, PartStartEvent) and isinstance(event.part, TextPart):
            if event.index in started:
                on_delta({"replace": event.part.content})
            else:
                on_delta(event.part.content)
            started.add(event.index)
        elif isinstance(event, PartDeltaEvent) and isinstance(
            event.delta, TextPartDelta
        ):
            on_delta(event.delta.content_delta)


async def invoke(
    agent: Agent[D, T], prompt: str | list[str] | dict[str, Any],
    *, model: Model, **kwargs: Any,
) -> AgentRunResult[T]:
    if isinstance(model, CliHost):
        tools = [
            tool for toolset in agent.toolsets if isinstance(toolset, FunctionToolset)
            for tool in toolset.tools.values()
        ]
        model = type(model)(model.cli_name, tools, effort=model.effort)
    if isinstance(prompt, dict):
        prompt = json.dumps(prompt, ensure_ascii=False)
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(3),
        wait=wait_fixed(5),
        retry=retry_if_exception(transient),
        reraise=True,
    ):
        with attempt:
            return await agent.run(prompt, model=model, **kwargs)
    raise AssertionError("tenacity completed without a result")


async def gather_or_raise(*awaitables: Awaitable[T]) -> list[T]:
    """Run the awaitables; the first failure is the result, not a swallowed one."""
    results = await asyncio.gather(*awaitables, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result
    return cast(list[T], results)
