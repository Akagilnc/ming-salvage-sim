"""One transport retry policy, independent of declaration validation retries."""

from collections.abc import AsyncIterable, Callable, Sequence
from typing import Any, Literal, TypeVar, cast

from httpx2 import TimeoutException
from openai import APIConnectionError
from pydantic import BaseModel
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

from ming.middle.cli_model import ClaudeCliModel

T = TypeVar("T")
D = TypeVar("D")


class Settings(BaseModel):
    backend: Literal["api", "claude-cli"] = "api"
    model: str = ""
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""


ModelSource = Model | Settings | str


def build_agent(
    model: ModelSource,
    *,
    tools: Sequence[Callable[..., Any] | Tool[Any]] = (),
    **kwargs: Any,
) -> Agent[Any, Any]:
    """Declare a call once, including its native transport and callable tools."""
    if isinstance(model, Settings):
        model = (
            ClaudeCliModel(model.model)
            if model.backend == "claude-cli"
            else OpenAIChatModel(
                model.model or "gpt-4.1",
                provider=OpenAIProvider(
                    base_url=model.base_url, api_key=model.api_key or "not-configured"
                ),
            )
        )
    elif isinstance(model, str):
        model = ClaudeCliModel() if model == "claude-cli" else infer_model(model)
    declared: list[Tool[Any]] = [
        cast(Tool[Any], tool) if isinstance(tool, Tool) else Tool[Any](tool)
        for tool in tools
    ]
    if isinstance(model, ClaudeCliModel):
        model = ClaudeCliModel(model.cli_name, declared)
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
