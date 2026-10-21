"""Recorded model boundary: native overrides selected only by the declared call name."""

import asyncio
import io
import json
from contextlib import redirect_stdout
from pathlib import Path

import pytest
from pydantic_ai import Agent, models
from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelResponse
from pydantic_ai.models.test import TestModel

from ming.__main__ import main
from tests.test_court import replaying

RECORDED = Path(__file__).parent / "recorded"


@pytest.fixture
def steps(monkeypatch, request):
    monkeypatch.setattr(models, "ALLOW_MODEL_REQUESTS", False)
    invalid = json.loads((RECORDED / "night_invalid.json").read_text())["cases"][
        "missing_fields"
    ]
    replies = {
        "scene": TestModel(call_tools=[], custom_output_text=invalid["scene"]),
        "NightDeclaration": TestModel(
            call_tools=[], custom_output_text=invalid["reply"]
        ),
        "Declaration": TestModel(
            call_tools=[], custom_output_text=(RECORDED / "month_empty.txt").read_text()
        ),
        **{
            name: TestModel(
                call_tools=[], custom_output_text=(RECORDED / f"{name}.txt").read_text()
            )
            for name in ("deliberation", "simulation", "gazette")
        },
    }
    if getattr(request, "param", None) == "approved":
        case = json.loads((RECORDED / "night_approved.json").read_text())
        replies["scene"] = replaying(
            [
                m
                for m in ModelMessagesTypeAdapter.validate_python(
                    case["scene_responses"]
                )
                if isinstance(m, ModelResponse)
            ]
        )
        replies["NightDeclaration"] = replaying(case["replies"])
    run = Agent.run

    async def recorded(agent, *args, **kwargs):
        # Only the external model is substituted; Agent, tools and validators run normally.
        with agent.override(model=replies[agent.name]):
            return await run(agent, *args, **kwargs)

    monkeypatch.setattr(Agent, "run", recorded)
    return replies


@pytest.fixture
def audit():
    def read(db: Path, replay: bool = False, *, identity: str = "audit"):
        output = io.StringIO()
        with redirect_stdout(output):
            main(
                [
                    "read",
                    "--db",
                    str(db),
                    "--identity",
                    identity,
                    *(["--replay"] if replay else []),
                ]
            )
        return json.loads(output.getvalue())

    return read


@pytest.fixture
def clock(monkeypatch):
    waits = []
    real_sleep = asyncio.sleep

    async def sleep(delay):
        if delay == 5:
            waits.append(delay)
            delay = 0
        await real_sleep(delay)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    return waits
