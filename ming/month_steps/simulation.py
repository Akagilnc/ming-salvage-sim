"""Night/world simulations and option forecasts, all durable on their source."""

import asyncio
import json
from typing import Any
from uuid import UUID, uuid4

from pydantic_ai import PromptedOutput
from pydantic_ai.messages import ModelMessagesTypeAdapter

from ming.middle.court import Court
from ming.middle.declaration import PendingPetition
from ming.middle.invoke import ModelSource, build_agent, invoke
from ming.middle.month_work import Materials, Simulation, prompt, read_records
from ming.middle.view import EntityView


def continuing_options(petition: PendingPetition, route: UUID) -> range | list[int]:
    """Every option of a fork continues its segment; a rejection only 强颁 does."""
    if petition.entity_id == route:
        return range(len(petition.options))
    return [petition.options.index("强颁")] if "强颁" in petition.options else []


class Simulations:
    def __init__(self, court: Court, model: ModelSource) -> None:
        self.court = court
        self.tasks: dict[tuple[UUID, str, int], asyncio.Task[dict[str, Any]]] = {}
        self.continuations: dict[tuple[UUID, str], asyncio.Task[None]] = {}
        self.agent = build_agent(
            model,
            name="simulation",
            output_type=PromptedOutput(Simulation),
            deps_type=Materials,
            tools=[read_records],
            retries=1,
            instructions="你推演真实世界，用 read_records 查账。日期由输入账本给定，只写本月，写到本月底结束。交本段原文、零到多道奏疏及是否已写到月底。未到月底请旨是岔路；交回的每问独立，可各自续写。到月底附带奏疏是下个月开局奏折，不在本月执行。旨意推演只办输入已准各旨，不推其余世界；世界推演读各夜结果，只写其余发展和本月重议已准旨、上月已批奏疏。撤回成命照外廷判词办理，保留其皇威、当事大臣与相关派系反应；收权罢差零毁约代价。强颁付皇威及相关派系或阶级反应，反应可正可负可零，中旨标记写在旨上。民心不是强颁或撤旨的固定代价。人物异地启程按账本距离在途，所在由引擎月末倒数更新，在途不改道；事务办完只写往事，不设了结。奏报与实况分清。续写接同段对话，只写当前这一问的后果，不替其他问选择、不重复已写部分。",
        )

    def publish(self, route: UUID, segment: dict[str, Any]) -> None:
        date = self.court.calendar().data
        output = Simulation.model_validate(segment["output"])
        available = dict(date)
        if output.month_end:
            available.update(
                year=date["year"] + (date["month"] == 12), month=date["month"] % 12 + 1
            )
        events = [("simulation", {**segment, "date": date})]
        for item in output.petitions:
            petition = PendingPetition(
                **item.model_dump(),
                id=uuid4(),
                route_id=route,
                entity_id=route,
                segment_id=UUID(segment["id"]),
                available=available,
                blocking=not output.month_end,
            )
            events.append(
                ("petition", {**petition.model_dump(mode="json"), "date": date})
            )
        self.court.record(route, events)

    async def call(self, context: dict[str, Any], history: list[Any]) -> dict[str, Any]:
        result = await invoke(
            self.agent,
            prompt(self.court, "world", context),
            deps=Materials(self.court, "world"),
            message_history=ModelMessagesTypeAdapter.validate_python(history),
        )
        self.court.log.info("model output: %s", result.output.model_dump_json())
        return {
            "id": str(uuid4()),
            "output": result.output.model_dump(),
            "messages": json.loads(result.all_messages_json()),
        }

    async def forecast(self, petition: PendingPetition, option: int) -> dict[str, Any]:
        existing = next(
            (
                p.detail
                for p in self.court.petition_products(
                    [str(petition.id)], "forecast", current=True
                )
                if p.detail["option"] == option
            ),
            None,
        )
        if existing is not None:
            return existing
        segments = [
            f.detail for f in self.court.products(petition.route_id, kind="simulation")
        ]
        parent = next(
            (s for s in segments if s["id"] == str(petition.segment_id)), segments[0]
        )
        result = await self.call(
            {
                "petition": petition.model_dump(mode="json"),
                "option": option,
                "choice": petition.options[option],
                "instruction": "只续写这一问的后果到本月底。其他问保持待批；强颁则续写此旨及其代价。",
            },
            parent["messages"],
        )
        result.update(petition_id=str(petition.id), option=option)
        self.court.record(
            petition.route_id, [("forecast", {**result, "date": petition.available})]
        )
        return result

    def start_forecast(
        self, petition: PendingPetition, option: int
    ) -> asyncio.Task[dict[str, Any]]:
        key = petition.route_id, str(petition.id), option
        if key not in self.tasks:
            task = self.tasks[key] = asyncio.create_task(
                self.forecast(petition, option)
            )
            task.add_done_callback(self.log_failure)
        return self.tasks[key]

    def log_failure(self, task: asyncio.Task[Any]) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            self.court.log.error("background simulation failed", exc_info=error)

    async def wait_for_choice(self, key: tuple[UUID, str, int]) -> None:
        task = self.tasks[key]
        try:
            await asyncio.shield(task)
        except Exception:
            # Failed speculation alone may be rerun on an actual selection.
            detail = self.court.petition(key[1]).detail
            petition = PendingPetition.model_validate(
                {k: v for k, v in detail.items() if k != "date"}
            )
            if self.tasks[key] is task:
                del self.tasks[key]
            await asyncio.shield(self.start_forecast(petition, key[2]))

    async def continue_segment(self, route: UUID, segment: dict[str, Any]) -> None:
        result = await self.call(
            {"instruction": "接着写本月余下部分。"}, segment["messages"]
        )
        result["after"] = segment["id"]
        self.publish(route, result)

    def start_continuation(
        self, route: UUID, segment: dict[str, Any]
    ) -> asyncio.Task[None]:
        key = route, segment["id"]
        if key not in self.continuations:
            task = self.continuations[key] = asyncio.create_task(
                self.continue_segment(route, segment)
            )
            task.add_done_callback(self.log_failure)
        return self.continuations[key]

    async def run(self, route: EntityView, context: dict[str, Any]) -> bool:
        if not self.court.products(route.id, kind="simulation"):
            self.publish(route.id, await self.call(context, []))
        return self.progress(route.id)

    def chain(self, petition_id: str | None) -> set[str]:
        facts = (
            self.court.products(
                UUID(self.court.petition(petition_id).detail["route_id"]),
                kind="simulation",
            )
            if petition_id is not None
            else self.court.facts(
                "audit", kind="simulation", date=self.court.calendar().data
            )
        )
        segments = [f.detail for f in facts]
        chain = {
            s["id"]
            for s in segments
            if s.get("petition_id")
            and (petition_id is None or s["petition_id"] == petition_id)
        }
        while any(s.get("after") in chain and s["id"] not in chain for s in segments):
            chain |= {s["id"] for s in segments if s.get("after") in chain}
        return chain

    def progress(self, route: UUID, petition_id: str | None = None) -> bool:
        """Publish ready products without awaiting unrelated model work."""
        while True:
            segments = [f.detail for f in self.court.products(route, kind="simulation")]
            petitions = [
                PendingPetition.model_validate(
                    {k: v for k, v in f.detail.items() if k != "date"}
                )
                for f in self.court.route_petitions(route)
            ]
            choices = {
                f.detail["petition_id"]: f.detail
                for f in self.court.petition_products(
                    [str(p.id) for p in petitions], "choice"
                )
            }
            progressed = False
            ready = True
            for petition in petitions:
                choice = choices.get(str(petition.id))
                if (
                    choice is not None and petition_id not in (None, str(petition.id))
                ) or not segments:
                    # Without the parent segment no forecast of this route can run;
                    # its production re-enters here through run() once it lands.
                    continue
                options = continuing_options(petition, route)
                for option in options:
                    self.start_forecast(petition, option)
                if (
                    choice is None
                    or choice["option"] not in options
                    or any(s.get("petition_id") == str(petition.id) for s in segments)
                ):
                    continue
                task = self.start_forecast(petition, choice["option"])
                if not task.done() or task.exception() is not None:
                    ready = False
                    continue
                self.publish(route, task.result())
                progressed = True
            for segment in segments:
                if (
                    (petition_id is None or segment["id"] in self.chain(petition_id))
                    and not segment["output"]["month_end"]
                    and not segment["output"]["petitions"]
                    and not any(s.get("after") == segment["id"] for s in segments)
                ):
                    # Continuation runs off the month lock and publishes itself;
                    # the caller waits for it in resume, outside the lock.
                    task = self.start_continuation(route, segment)
                    if not task.done() or task.exception() is not None:
                        ready = False
                    else:
                        progressed = True
            if not progressed:
                return ready

    async def drain(self) -> None:
        tasks: list[asyncio.Task[Any]] = [
            *self.tasks.values(),
            *self.continuations.values(),
        ]
        if tasks:
            # Candidate failures are logged by log_failure; they are not formal work.
            await asyncio.gather(*tasks, return_exceptions=True)
