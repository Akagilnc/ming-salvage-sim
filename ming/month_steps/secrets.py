"""Each unfinished secret errand's own report."""

from collections.abc import Awaitable
from typing import Any

from ming.middle.court import Court
from ming.middle.concepts import HANDLER, PEOPLE, SECRET
from ming.middle.invoke import ModelSource, build_agent, gather_or_raise, invoke
from ming.middle.month_work import prompt
from ming.middle.records import Materials, read_records
from ming.middle.view import EntityView, Officials, character_input
from ming.month_steps.products import record_product


class Secrets:
    def __init__(self, court: Court, model: ModelSource) -> None:
        self.court = court
        self.agent = build_agent(
            model,
            name="secret_report",
            output_type=str,
            deps_type=Materials,
            tools=[read_records],
            instructions="按本月实况与风声，用本旨承办人复命的口吻给皇帝写这一道密令的密报。按 catalogue 用 read_records 查本人所知材料，按本人的立场与利害复命；查得什么、听得什么、尚有何难处，由承办人据其所知复命。人物的打算与文字由你发挥。" + "\n" + "\n".join((SECRET, HANDLER, PEOPLE)),
        )

    async def report(self, decrees: tuple[EntityView, ...], date: dict[str, Any]) -> None:
        pending: dict[str, list[int]] = {}
        for index, decree in enumerate(decrees):
            if not self.court.read.has_facts(decree.id, "secret_report", date=date):
                pending.setdefault(decree.data["handler"], []).append(index)
        calls: dict[int, Awaitable[None]] = {}
        for handler, indices in pending.items():
            identity = Officials(people=[handler])
            inputs = prompt(self.court, identity, {}, date=date)
            calls.update((index, self.call(decrees[index], identity, inputs)) for index in indices)
        await gather_or_raise(*(calls[index] for index in sorted(calls)))

    async def call(self, decree: EntityView, identity: Officials, inputs: dict[str, Any]) -> None:
        result = await invoke(
            self.agent,
            {**inputs, "context": character_input({
                "decree": decree.model_dump(mode="json"),
                "facts": [
                    f.model_dump(mode="json", exclude={"emperor_words"})
                    for f in self.court.consequences(decree.id, inputs["date"])
                ],
                "products": [
                    f.model_dump(mode="json", exclude={"emperor_words"})
                    for f in self.court.read.facts(
                        "audit", entity_id=decree.id, kind=("completed", "handled"), date=inputs["date"]
                    )
                ],
            })},
            deps=Materials(self.court, identity),
        )
        self.court.log.info("model output: %s", result.output)
        record_product(self.court, decree.id, "secret_report", {"text": result.output, "date": inputs["date"]})
