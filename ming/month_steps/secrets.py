"""Monthly exposure from recorded counts, and each unfinished errand's own report."""

from ming.middle.court import Court
from ming.middle.invoke import ModelSource, build_agent, invoke
from ming.middle.view import EntityView, Officials
from ming.middle.month_work import prompt
from ming.middle.records import Materials, read_records


class Secrets:
    def __init__(self, court: Court, model: ModelSource) -> None:
        self.court = court
        self.agent = build_agent(
            model,
            name="secret_report",
            output_type=str,
            deps_type=Materials,
            tools=[read_records],
            instructions="按本月实况与风声，用本旨承办人复命的口吻给皇帝写这一道密令的密报。按 catalogue 用 read_records 查本人所知材料，按本人的立场与利害复命；查得什么、听得什么、尚有何难处，由承办人据其所知复命。人物的打算与文字由你发挥。",
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
        identity = Officials(people=decree.data["people"] or sorted(self.court.known_people(decree)))
        result = await invoke(
            self.agent,
            prompt(self.court, identity, {
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
            }),
            deps=Materials(self.court, identity),
        )
        self.court.log.info("model output: %s", result.output)
        self.court.record_product(decree.id, "secret_report", {"text": result.output})
