"""One durable month draft, one final timeline, and single-fork candidates."""

import asyncio
from typing import Any
from uuid import UUID, uuid4

from pydantic_ai import PromptedOutput

from ming.middle.court import Court
from ming.middle.concepts import (
    ACTING, DECREE_EVENT, DISCOVERED, FORK, HANDLER, HELD, IMPERIAL_PUSH,
    INTERIM, MONTH_DRAFT, MONTH_FINAL, PEOPLE, PREVIEW, SECRET, VERDICT,
)
from ming.middle.declaration import PendingPetition
from ming.middle.invoke import ModelSource, build_agent, enlist, invoke
from ming.middle.month_work import MonthText, Simulation, prompt
from ming.middle.records import Materials, read_records


class Simulations:
    def __init__(self, court: Court, model: ModelSource) -> None:
        self.court = court
        self.tasks: dict[tuple[UUID, int], asyncio.Task[dict[str, Any]]] = {}
        instructions = "你推演真实世界，按输入 catalogue 用 read_records 按需查本月实况，日期由输入给定。fiscal_events 是本月到点的饷率事件，人物陈情与拟旨由岔路呈皇帝。上月急务按所选办理；弹劾按原奏疏的署名人、被劾人及所选处置，写清皇威、发难派系反应及被劾者去留的实际后果。查实再办要查被劾人实有行迹，写清所费工夫、所得及各方反应。人物异地启程要走完路程才能抵达，在途不改道；事务办完仍是日后人物行事的前情。" + "\n" + "\n".join((MONTH_DRAFT, MONTH_FINAL, FORK, IMPERIAL_PUSH, VERDICT, HELD, SECRET, HANDLER, PEOPLE, ACTING, INTERIM, DISCOVERED, DECREE_EVENT))
        self.draft_agent = build_agent(
            model, name="simulation", output_type=PromptedOutput(Simulation),
            deps_type=Materials, tools=[read_records], retries=1,
            instructions=instructions,
        )
        self.final_agent = build_agent(
            model, name="month_final", output_type=PromptedOutput(MonthText),
            deps_type=Materials, tools=[read_records], retries=1,
            instructions=instructions + "\n" + PREVIEW,
        )

    def context(self) -> dict[str, Any]:
        returned = {str(f.detail["id"]) for f in self.court.returned_petitions()}
        return {
            "decrees": [
                {"decree": d.model_dump(mode="json"), "mode": mode,
                 "deliberations": [f.detail for f in self.court.products(d.id, kind="deliberation")],
                 "prior_interim": self.court.prior_interim(d.id),
                 **({"known_people": sorted(self.court.known_people(d))} if d.data["secret"] else {})}
                for d, mode in self.court.landing_sources()
            ],
            "fiscal_events": self.court.fiscal_events(),
            "prior_choices": [
                {**f.detail, "petition": self.court.petition(f.detail["petition_id"]).detail}
                for f in self.court.facts("audit", kind="choice", date=self.court.calendar().data)
                if f.detail["petition_id"] not in returned
                and self.court.petition(f.detail["petition_id"]).detail["source"] in {"urgent", "impeachment"}
            ],
        }

    async def call(self, context: dict[str, Any], *, final: bool = False) -> dict[str, Any]:
        result = await invoke(
            self.final_agent if final else self.draft_agent,
            prompt(self.court, "world", context), deps=Materials(self.court, "world"),
        )
        self.court.log.info("model output: %s", result.output.model_dump_json())
        return {"id": str(uuid4()), "output": result.output.model_dump()}

    async def draft(self) -> None:
        calendar = self.court.calendar()
        if self.court.products(calendar.id, kind="month_draft"):
            return
        product = await self.call(self.context())
        petitions = [
            PendingPetition(
                **item, id=uuid4(), route_id=calendar.id, entity_id=calendar.id,
                segment_id=UUID(product["id"]), available=calendar.data,
                blocking=True, source="simulation",
            ) for item in product["output"]["petitions"]
        ]
        for decree in self.court.current_decrees():
            if decree.data["secret"]:
                continue
            verdict = self.court.deliberation(decree.id, None)
            if verdict is None or verdict["verdict"] == "准":
                continue
            petitions.append(PendingPetition(
                text=verdict["text"],
                options=(["强颁"] if verdict["verdict"] == "驳" else [])
                + ["收回", "留中"]
                + (["御笔强推"] if verdict["verdict"] == "驳" and not decree.data.get("endorsements") else []),
                id=uuid4(), route_id=calendar.id, entity_id=decree.id,
                segment_id=UUID(product["id"]), available=calendar.data,
                blocking=True, source="deliberation",
            ))
        self.court.record_product(calendar.id, "month_draft", product, petitions=petitions)

    def choices(self) -> list[dict[str, Any]]:
        petitions = self.court.route_petitions(self.court.calendar().id)
        return [
            {**f.detail, "petition": self.court.petition(f.detail["petition_id"]).detail}
            for f in self.court.petition_products([str(p.detail["id"]) for p in petitions], "choice")
        ]

    async def forecast(self, petition: PendingPetition, option: int) -> dict[str, Any]:
        existing = next((f.detail for f in self.court.petition_products(
            [str(petition.id)], "forecast", current=True,
        ) if f.detail["option"] == option), None)
        if existing is not None:
            return existing
        draft = self.court.products(petition.route_id, kind="month_draft")[0].detail
        result = await self.call({
            **self.context(), "draft": draft["output"],
            "choices": [{"petition": petition.model_dump(mode="json"),
                         "option": option, "text": petition.options[option]}],
        }, final=True)
        result.update(petition_id=str(petition.id), option=option)
        self.court.record(petition.route_id, [("forecast", {**result, "date": petition.available})])
        return result

    def log_failure(self, task: asyncio.Task[Any]) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            self.court.log.error("month candidate failed", exc_info=error)

    def speculate(self) -> None:
        petitions = self.court.route_petitions(self.court.calendar().id)
        if len(petitions) != 1:
            return
        petition = self.court.as_petition(petitions[0])
        for option in range(len(petition.options)):
            enlist(self.tasks, (petition.id, option), lambda option=option: self.forecast(petition, option), on_done=self.log_failure)

    async def final(self) -> None:
        calendar = self.court.calendar()
        if self.court.products(calendar.id, kind="month_final"):
            return
        draft = self.court.products(calendar.id, kind="month_draft")[0].detail
        petitions = self.court.route_petitions(calendar.id)
        choices = self.choices()
        result: dict[str, Any]
        if not petitions:
            result = {**draft, "output": {"text": draft["output"]["text"]}}
        elif len(petitions) == 1:
            petition = self.court.as_petition(petitions[0])
            choice = choices[0]
            task = self.tasks.get((petition.id, choice["option"]))
            if task is not None:
                try:
                    result = await asyncio.shield(task)
                except Exception:
                    # Speculation is optional; selected work is a formal call with normal recovery.
                    result = await self.forecast(petition, choice["option"])
            else:
                result = await self.forecast(petition, choice["option"])
        else:
            result = await self.call({**self.context(), "draft": draft["output"], "choices": choices}, final=True)
        self.court.record_product(calendar.id, "month_final", result)

    async def drain(self) -> None:
        if self.tasks:
            # Candidate failures are logged, not promoted to failed emperor actions.
            await asyncio.gather(*self.tasks.values(), return_exceptions=True)
