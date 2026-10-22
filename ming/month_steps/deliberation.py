"""Per-decree court verdicts; rejected decrees offer their own inbox choices."""

from uuid import UUID, uuid4

from pydantic_ai import PromptedOutput

from ming.middle.court import Court
from ming.middle.declaration import PendingPetition
from ming.middle.invoke import ModelSource, build_agent, invoke
from ming.middle.month_work import Deliberation, Materials, prompt, read_records
from ming.middle.view import EntityView, Officials


class Deliberations:
    def __init__(self, court: Court, model: ModelSource) -> None:
        self.court = court
        self.agent = build_agent(
            model,
            name="deliberation",
            output_type=PromptedOutput(Deliberation),
            deps_type=Materials,
            tools=[read_records],
            retries=1,
            instructions="你演外廷内阁票拟、六科封驳、部院议处。交议处原文和判词。按经手官员所知议处定稿圣旨，不用世界全知。用 read_records 查本身份材料。合规常务准行；越制破格、撞派系逆鳞、撞把关关口才审视封驳。皇威高触发面收窄但有谏言寒蝉、无人担名的反噬，皇威低触发面变宽；命门不因皇威高而豁免。撤旨照常议处，收权罢差是正当治术。",
        )

    async def run(self, decree: EntityView, route: UUID) -> None:
        if self.court.products(decree.id, kind="deliberation"):
            return
        identity = Officials(people=decree.data["people"], exclude_secrets=True)
        world = self.court.entities("audit", kind="world")[0]
        result = await invoke(
            self.agent,
            prompt(
                self.court,
                identity,
                {
                    "decree": decree.model_dump(mode="json"),
                    "imperial_prestige": world.data["imperial_prestige"],
                },
            ),
            deps=Materials(self.court, identity),
        )
        self.court.log.info("model output: %s", result.output.model_dump_json())
        date = self.court.calendar().data
        segment = uuid4()
        petitions: list[PendingPetition] = []
        if result.output.verdict != "准":
            petition = PendingPetition(
                text=result.output.text,
                options=(["强颁"] if result.output.verdict == "驳" else [])
                + ["收回", "留中"],
                id=uuid4(),
                route_id=route,
                entity_id=decree.id,
                segment_id=segment,
                available=date,
                blocking=True,
                source="deliberation",
            )
            petitions.append(petition)
        self.court.record_product(
            decree.id,
            "deliberation",
            {
                **result.output.model_dump(),
                "id": str(segment),
                "route_id": str(route),
            },
            petitions=petitions,
        )
