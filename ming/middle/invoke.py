"""One transport retry policy, independent of declaration validation retries."""

from typing import Any, TypeVar

from httpx2 import TimeoutException
from openai import APIConnectionError
from pydantic_ai import Agent, AgentRunResult
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.models import Model
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIResponsesModel
from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_fixed

T = TypeVar("T")
D = TypeVar("D")


def transport_model(model: Model) -> Model:
    if isinstance(model, (OpenAIChatModel, OpenAIResponsesModel)):
        model.client.max_retries = 0
    return model


def transient(error: BaseException) -> bool:
    return (
        isinstance(error, (TimeoutException, TimeoutError))
        or (isinstance(error, ModelHTTPError) and 500 <= error.status_code < 600)
        or (
            isinstance(error, ModelAPIError)
            and isinstance(error.__cause__, APIConnectionError)
        )
    )


async def invoke(
    agent: Agent[D, T], prompt: str | list[str], background: bool = False, **kwargs: Any
) -> AgentRunResult[T]:
    async for attempt in AsyncRetrying(
        stop=stop_after_attempt(1 if background else 3),
        wait=wait_fixed(5),
        retry=retry_if_exception(transient),
        reraise=True,
    ):
        with attempt:
            return await agent.run(prompt, **kwargs)
    raise AssertionError("tenacity completed without a result")
