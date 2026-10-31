"""Per-decree verdict products; month drafts publish the initial forks together."""

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from pydantic_ai import Agent, PromptedOutput
from pydantic_ai.models import Model

from ming.middle.court import Court
from ming.middle.concepts import ACTING, IMPERIAL_PUSH, INTERIM, VERDICT
from ming.middle.invoke import gather_or_raise, invoke
from ming.month_steps.materials import Deliberation, prepare
from ming.middle.records import Materials, read_records
from ming.middle.view import EntityView, Officials, character_input
from ming.month_steps.products import record_product


class Deliberations:
    agent = Agent(
        name="deliberation",
        output_type=PromptedOutput(Deliberation),
        deps_type=Materials,
        tools=[read_records],
        retries=1,
        instructions="你演外廷内阁票拟、六科封驳、部院议处。交议处原文和判词。按经手官员所知议处定稿圣旨，不用世界全知。按输入 catalogue 用 read_records 按需查本身份材料。合规常务准行；越制破格、撞派系逆鳞、撞把关关口才审视封驳。皇威高触发面收窄但有谏言寒蝉、无人担名的反噬，皇威低触发面变宽；命门不因皇威高而豁免。背书人只是担名，不是办事人；会签、当面站台的分量据人物与局势判断。御笔手敕的分量仍由外廷判词决定。撤旨照常议处，收权罢差是正当治术。" + "\n" + "\n".join((ACTING, INTERIM, VERDICT, IMPERIAL_PUSH)),
    )

    def __init__(self, court: Court, model: Callable[[], Model]) -> None:
        self.court, self.model = court, model

    async def run(
        self, decrees: Sequence[tuple[EntityView, dict[str, Any] | None]], date: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Prepare unchanged inputs before starting independent verdict calls."""
        done: dict[int, dict[str, Any]] = {}
        pending: dict[int, Officials] = {}
        products = {key: self.court.read.facts("audit", entity_id=key, kind="deliberation", date=date)
                    for key in dict.fromkeys(d.id for d, _ in decrees)}
        for index, (decree, decision) in enumerate(decrees):
            product = next((f.detail for f in products[decree.id]
                            if f.detail["decision_key"] == decision), None)
            if product is not None:
                done[index] = product
            else:
                pending[index] = Officials(people=decree.data["people"], exclude_secrets=True)
        calls: dict[int, Awaitable[dict[str, Any]]] = {}
        if pending:
            prestige = self.court.read.entities("audit", kind="world")[0].data["imperial_prestige"]
            for index, (identity, inputs) in prepare(self.court, pending, {"imperial_prestige": prestige}, date=date).items():
                decree, decision = decrees[index]
                calls[index] = self.call(decree, decision, identity, inputs)
        done.update(zip(calls, await gather_or_raise(*calls.values()), strict=True))
        return [done[index] for index in range(len(decrees))]

    async def call(
        self, decree: EntityView, decision: dict[str, Any] | None,
        identity: Officials, inputs: dict[str, Any],
    ) -> dict[str, Any]:
        result = await invoke(
            self.agent,
            {**inputs, "context": {"decree": character_input(decree.model_dump(mode="json")), **inputs["context"]}},
            deps=Materials(self.court, identity), model=self.model(),
        )
        self.court.log.info("model output: %s", result.output.model_dump_json())
        verdict: dict[str, Any] = {
            **result.output.model_dump(),
            "decision_key": decision,
        }
        record_product(self.court, decree.id, "deliberation", {**verdict, "date": inputs["date"]})
        return verdict
