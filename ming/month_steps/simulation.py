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
from ming.middle.view import EntityView
from ming.middle.records import Materials, read_records


class Simulations:
    def __init__(self, court: Court, model: ModelSource) -> None:
        self.court = court
        self.tasks: dict[tuple[UUID, int], asyncio.Task[dict[str, Any]]] = {}
        instructions = "你推演真实世界，按输入 catalogue 用 read_records 按需查本月实况，日期由输入给定。fiscal_events 是本月到点应呈的饷率事件，写陈情与拟旨，停在本月岔路待皇帝批红，不自行准驳。拨款用途、减额、暂欠、改序与摊派仍由人物与旨意决定。上月急务按所选办理；弹劾按原奏疏的署名人、被劾人及所选处置，写清皇威、发难派系反应及被劾者去留的实际后果。查实再办要查被劾人实有行迹，写清所费工夫、所得及各方反应。arrivals 是账本记定的本月预计抵达人物、目的地与日期。写人物行程先用 read_records 查 distance 的里程与各档天数、人物的 departure_date 与 arrival_date；按引擎记定的预计到达日写，尚未启程者哪天动身由人物与戏文定。事务办完仍是日后人物行事的前情。" + "\n" + "\n".join((MONTH_DRAFT, MONTH_FINAL, FORK, IMPERIAL_PUSH, VERDICT, HELD, SECRET, HANDLER, PEOPLE, ACTING, INTERIM, DISCOVERED, DECREE_EVENT))
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

    def context(self, date: dict[str, Any]) -> dict[str, Any]:
        return {
            "decrees": self.court.landing_materials(include_history=False, date=date),
            "arrivals": self.court.arrivals_this_month(date),
            "fiscal_events": self.court.fiscal_events(date),
            "prior_choices": self.court.prior_choices(date),
        }

    async def call(self, context: dict[str, Any], date: dict[str, Any], *, final: bool = False) -> dict[str, Any]:
        result = await invoke(
            self.final_agent if final else self.draft_agent,
            prompt(self.court, "world", context, date=date), deps=Materials(self.court, "world"),
        )
        self.court.log.info("model output: %s", result.output.model_dump_json())
        return {"output": result.output.model_dump()}

    async def draft(self, verdicts: list[tuple[EntityView, dict[str, Any]]]) -> None:
        calendar = self.court.calendar()
        product = await self.call(self.context(calendar.data), calendar.data)
        petitions = [
            PendingPetition(
                **item, id=uuid4(), entity_id=calendar.id, available=calendar.data,
                blocking=True, source="simulation",
            ) for item in product["output"]["petitions"]
        ]
        for decree, verdict in verdicts:
            if verdict["verdict"] == "准":
                continue
            petitions.append(PendingPetition(
                text=verdict["text"],
                options=(["强颁"] if verdict["verdict"] == "驳" else [])
                + ["收回", "留中"]
                + (["御笔强推"] if verdict["verdict"] == "驳" and not decree.data.get("endorsements") else []),
                id=uuid4(), entity_id=decree.id, available=calendar.data,
                blocking=True, source="deliberation",
            ))
        self.court.record_product(calendar.id, "month_draft", product, petitions=petitions)

    async def forecast(self, petition: PendingPetition, option: int) -> dict[str, Any]:
        calendar = self.court.calendar()
        existing = next((f.detail for f in self.court.petition_products(
            [str(petition.id)], "forecast", current=True, date=calendar.data,
        ) if f.detail["option"] == option), None)
        if existing is not None:
            return existing
        draft = self.court.products(calendar.id, kind="month_draft", date=calendar.data)[0].detail
        result = await self.call({
            **self.context(calendar.data), "draft": draft["output"],
            "choices": [{"petition": petition.model_dump(mode="json"),
                         "option": option, "text": petition.options[option]}],
        }, calendar.data, final=True)
        result.update(petition_id=str(petition.id), option=option)
        self.court.record(calendar.id, [("forecast", {**result, "date": petition.available})])
        return result

    def log_failure(self, task: asyncio.Task[Any]) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            self.court.log.error("month candidate failed", exc_info=error)

    def speculate(self) -> None:
        petitions = self.court.month_petitions(single_pending=True)
        if not petitions:
            return
        petition = self.court.as_petition(petitions[0])
        for option in range(len(petition.options)):
            enlist(self.tasks, (petition.id, option), lambda option=option: self.forecast(petition, option), on_done=self.log_failure)

    async def final(self) -> None:
        calendar = self.court.calendar()
        petitions = {str(p.detail["id"]): p for p in self.court.month_petitions(calendar.data)}
        choices: list[dict[str, Any]] = [{**f.detail, "petition": petitions[f.detail["petition_id"]].detail}
                   for f in self.court.petition_products(list(petitions), "choice")]
        result: dict[str, Any]
        if len(petitions) == 1:
            petition = self.court.as_petition(next(iter(petitions.values())))
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
            draft = self.court.products(calendar.id, kind="month_draft", date=calendar.data)[0].detail
            result = (await self.call({**self.context(calendar.data), "draft": draft["output"], "choices": choices}, calendar.data, final=True)
                      if petitions else {**draft, "output": {"text": draft["output"]["text"]}})
        self.court.record_product(calendar.id, "month_final", result)

    async def drain(self) -> None:
        while tasks := [task for task in self.tasks.values() if not task.done()]:
            # Candidate failures are logged, not promoted to failed emperor actions.
            await asyncio.gather(*tasks, return_exceptions=True)
