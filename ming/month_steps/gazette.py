"""Public gazette after landing (and, when added, the fiscal month's product)."""

from collections.abc import Callable
from functools import partial

from pydantic_ai import Agent
from pydantic_ai.models import Model

from ming.middle.court import Court
from ming.middle.invoke import TextUpdate, invoke, stream_text
from ming.middle.month_work import prompt
from ming.middle.records import Materials, read_records
from ming.middle.view import EntityView


class Gazette:
    agent = Agent(
        name="gazette",
        output_type=str,
        deps_type=Materials,
        tools=[read_records],
        instructions="按输入本月日期，以朝廷公开口径写本月邸报。按输入 catalogue 的正名与事件数，用 read_records 带本月日期先列有事件的实体，再点正名并带本月日期取各衙门奏报全文；不空参读全账，保留官员奏报说法，不套模板。",
    )

    def __init__(
        self, court: Court, model: Callable[[], Model], on_delta: Callable[[TextUpdate], None] | None
    ) -> None:
        self.court, self.model, self.on_delta = court, model, on_delta

    async def run(self, calendar: EntityView) -> None:
        if self.court.has_product(calendar.id, "gazette", date=calendar.data):
            return
        result = await invoke(
            self.agent,
            prompt(self.court, "public", calendar.model_dump(mode="json"), date=calendar.data),
            deps=Materials(self.court, "public"), model=self.model(),
            event_stream_handler=partial(stream_text, self.on_delta)
            if self.on_delta
            else None,
        )
        self.court.log.info("model output: %s", result.output)
        self.court.record_product(calendar.id, "gazette", {"text": result.output})
