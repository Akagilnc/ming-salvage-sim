"""Per-decree verdict products; month drafts publish the initial forks together."""

from typing import Any

from pydantic_ai import PromptedOutput

from ming.middle.court import Court
from ming.middle.concepts import ACTING, IMPERIAL_PUSH, INTERIM, VERDICT
from ming.middle.invoke import ModelSource, build_agent, invoke
from ming.middle.month_work import Deliberation, prompt
from ming.middle.records import Materials, read_records
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
            instructions="你演外廷内阁票拟、六科封驳、部院议处。交议处原文和判词。按经手官员所知议处定稿圣旨，不用世界全知。按输入 catalogue 用 read_records 按需查本身份材料。合规常务准行；越制破格、撞派系逆鳞、撞把关关口才审视封驳。皇威高触发面收窄但有谏言寒蝉、无人担名的反噬，皇威低触发面变宽；命门不因皇威高而豁免。背书人只是担名，不是办事人；会签、当面站台的分量据人物与局势判断。御笔手敕的分量仍由外廷判词决定。撤旨照常议处，收权罢差是正当治术。" + "\n" + "\n".join((ACTING, INTERIM, VERDICT, IMPERIAL_PUSH)),
        )

    async def run(
        self, decree: EntityView, decision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Initial verdict or next-month reconsideration of one selected push."""
        date = self.court.calendar().data
        done = next((f.detail for f in self.court.products(decree.id, kind="deliberation", date=date)
                     if f.detail["decision_key"] == decision), None)
        if done is not None:
            return done
        decree = self.court.entity(decree.id)
        identity = Officials(people=decree.data["people"], exclude_secrets=True)
        result = await invoke(
            self.agent,
            prompt(
                self.court, identity,
                {
                    "decree": decree.model_dump(mode="json"),
                    "imperial_prestige": self.court.entities("audit", kind="world")[0].data["imperial_prestige"],
                }, date=date,
            ),
            deps=Materials(self.court, identity),
        )
        self.court.log.info("model output: %s", result.output.model_dump_json())
        verdict: dict[str, Any] = {
            **result.output.model_dump(),
            "decision_key": decision,
        }
        self.court.record_product(decree.id, "deliberation", verdict)
        return verdict
