"""Each unfinished secret errand's own report."""

from collections.abc import Callable
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.models import Model

from ming.middle.court import Court
from ming.middle.concepts import HANDLER, PEOPLE, SECRET
from ming.middle.invoke import gather_or_raise, invoke
from ming.month_steps.materials import prepare
from ming.middle.records import Materials, read_records
from ming.middle.view import EntityView, Officials, character_input
from ming.month_steps.products import record_product


class Secrets:
    agent = Agent(
        name="secret_report",
        output_type=str,
        deps_type=Materials,
        tools=[read_records],
        instructions="按本月实况与风声，用本旨承办人复命的口吻给皇帝写这一道密令的密报。按 catalogue 用 read_records 查本人所知材料，按本人的立场与利害复命；查得什么、听得什么、尚有何难处，由承办人据其所知复命。人物的打算与文字由你发挥。" + "\n" + "\n".join((SECRET, HANDLER, PEOPLE)),
    )

    def __init__(self, court: Court, model: Callable[[], Model]) -> None:
        self.court, self.model = court, model

    async def report(self, decrees: tuple[EntityView, ...], date: dict[str, Any]) -> None:
        if not decrees:
            return
        reported = set(self.court.read.fact_ids("audit", "secret_report", date=date))
        pending = {index: Officials(people=[decree.data["handler"]])
                   for index, decree in enumerate(decrees) if decree.id not in reported}
        await gather_or_raise(*(
            self.call(decrees[index], identity, inputs)
            for index, (identity, inputs) in prepare(self.court, pending, {}, date=date).items()
        ))

    async def call(self, decree: EntityView, identity: Officials, inputs: dict[str, Any]) -> None:
        result = await invoke(
            self.agent,
            {**inputs, "context": character_input({
                "decree": decree.model_dump(mode="json"),
                "facts": [
                    f.model_dump(mode="json", exclude={"emperor_words"})
                    for f in self.court.read.facts(
                        "audit", kind=("changed", "received", "reported", "unhandled"),
                        date=inputs["date"], detail={"origin_ref": str(decree.id)},
                    )
                ],
                "products": [
                    f.model_dump(mode="json", exclude={"emperor_words"})
                    for f in self.court.read.facts(
                        "audit", entity_id=decree.id, kind=("completed", "handled"), date=inputs["date"]
                    )
                ],
            })},
            deps=Materials(self.court, identity), model=self.model(),
        )
        self.court.log.info("model output: %s", result.output)
        record_product(self.court, decree.id, "secret_report", {"text": result.output, "date": inputs["date"]})
