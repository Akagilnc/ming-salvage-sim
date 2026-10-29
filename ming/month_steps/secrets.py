"""Each unfinished secret errand's own report."""

from typing import Any

from ming.middle.court import Court
from ming.middle.concepts import HANDLER, PEOPLE, SECRET
from ming.middle.invoke import ModelSource, build_agent, gather_or_raise, invoke
from ming.middle.month_work import prompt, prompt_materials
from ming.middle.records import Materials, read_records
from ming.middle.view import EntityView, Officials


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

    async def run(self, decrees: list[EntityView], calendar: EntityView) -> None:
        if not decrees:
            return
        done = {f.entity_id for f in self.court.facts(
            "audit", entity_id=[d.id for d in decrees], kind="secret_report", date=calendar.data,
        )}
        pending = [d for d in decrees if d.id not in done]
        materials = {handler: prompt_materials(self.court, Officials(people=[handler]))
                     for handler in dict.fromkeys(d.data["handler"] for d in pending)}
        await gather_or_raise(*(self.report(d, calendar, materials[d.data["handler"]]) for d in pending))

    async def report(self, decree: EntityView, calendar: EntityView, materials: dict[str, Any]) -> None:
        identity = Officials(people=[decree.data["handler"]])
        result = await invoke(
            self.agent,
            prompt(
                self.court, identity,
                {
                    "decree": decree.model_dump(mode="json"),
                    "facts": [
                        f.model_dump(mode="json", exclude={"emperor_words"})
                        for f in self.court.consequences(decree.id, calendar.data)
                    ],
                    "products": [
                        f.model_dump(mode="json", exclude={"emperor_words"})
                        for f in self.court.products(
                            decree.id, kind=("completed", "handled"), date=calendar.data
                        )
                    ],
                }, calendar.data, materials,
            ),
            deps=Materials(self.court, identity),
        )
        self.court.log.info("model output: %s", result.output)
        self.court.record_product(decree.id, "secret_report", {"text": result.output}, date=calendar.data)
