"""Monthly exposure from recorded counts, and each unfinished errand's own report."""

import asyncio
import json

from ming.middle.court import Court
from ming.middle.invoke import ModelSource, build_agent, invoke
from ming.middle.view import EntityView, character_input


class Secrets:
    def __init__(self, court: Court, model: ModelSource) -> None:
        self.court = court
        self.agent = build_agent(
            model,
            name="secret_report",
            output_type=str,
            instructions="按本月实况与风声档位，用本旨承办人复命的口吻给皇帝写这一道密令的密报。区分已成事实与查获说法，接不住如实奏明，不推定差事办完。人物的打算与文字由你发挥。",
        )

    def accumulate(self) -> None:
        for decree in self.court.secret_decrees():
            if self.court.products(decree.id, kind="exposure"):
                continue
            # First-playtest weights: one per knower and per recorded handling;
            # twelve reaches partial disclosure, thirty-six widespread rumour.
            score = (
                decree.data["exposure"]["score"]
                + len(self.court.known_people(decree))
                + len(self.court.products(decree.id, kind="handled", current=False))
            )
            exposure = {
                "score": score,
                "stage": "满朝风闻"
                if score >= 36
                else "半公开"
                if score >= 12
                else "密",
                "date": self.court.calendar().data,
            }
            self.court.record(
                decree.id, [("exposure", exposure)], {"exposure": exposure}
            )

    async def report(self, decree: EntityView) -> None:
        date = self.court.calendar().data
        if self.court.products(decree.id, kind="secret_report"):
            return
        result = await invoke(
            self.agent,
            json.dumps(
                character_input(
                    {
                        "date": date,
                        "decree": decree.model_dump(mode="json"),
                        "facts": [
                            f.model_dump(mode="json", exclude={"emperor_words"})
                            for f in self.court.consequences(decree.id)
                        ],
                        "products": [
                            f.model_dump(mode="json", exclude={"emperor_words"})
                            for f in self.court.products(
                                decree.id, kind=("exposure", "completed", "handled")
                            )
                        ],
                    }
                ),
                ensure_ascii=False,
            ),
        )
        self.court.log.info("model output: %s", result.output)
        self.court.record_product(decree.id, "secret_report", {"text": result.output})

    async def run(self) -> None:
        results = await asyncio.gather(
            *(self.report(d) for d in self.court.errands()),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result
