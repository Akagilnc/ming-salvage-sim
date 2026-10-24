"""Night/world simulations and option forecasts, all durable on their source."""

import asyncio
import json
from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID, uuid4

from pydantic_ai import PromptedOutput
from pydantic_ai.messages import ModelMessagesTypeAdapter

from ming.middle.calendar import petition_date
from ming.middle.court import Court
from ming.middle.declaration import PendingPetition
from ming.middle.invoke import ModelSource, build_agent, enlist, invoke
from ming.middle.month_work import Materials, Simulation, prompt, read_records
from ming.middle.view import EntityView


def push_key(petition_id: str, option: int) -> dict[str, Any]:
    return {"petition_id": petition_id, "option": option}


def push_verdict(petition: PendingPetition, court: Court) -> dict[str, Any] | None:
    """This petition's landed imperial-push reconsideration, or None."""
    option = next(
        (i for i, name in enumerate(petition.options) if name == "御笔强推"), None
    )
    if option is None:
        return None
    return court.deliberation(
        petition.entity_id, push_key(str(petition.id), option)
    )


def continuing_options(petition: PendingPetition, court: Court) -> range | list[int]:
    """Forks continue; imperial backing waits for its own renewed approval."""
    if petition.entity_id == petition.route_id:
        return range(len(petition.options))
    approved = (verdict := push_verdict(petition, court)) is not None and verdict["verdict"] == "准"
    return [
        i for i, option in enumerate(petition.options)
        if option == "强颁" or (option == "御笔强推" and approved)
    ]


class Simulations:
    def __init__(
        self,
        court: Court,
        model: ModelSource,
        reconsider: Callable[
            [EntityView, UUID, dict[str, Any]], Coroutine[Any, Any, dict[str, Any]]
        ],
    ) -> None:
        self.court = court
        self.reconsider = reconsider
        self.tasks: dict[tuple[UUID, str, int], asyncio.Task[dict[str, Any]]] = {}
        self.continuations: dict[tuple[UUID, str], asyncio.Task[None]] = {}
        # Selected pushes live with the other ledger-started tasks, not a second registry.
        self.pushes: dict[str, asyncio.Task[dict[str, Any]]] = {}
        self.agent = build_agent(
            model,
            name="simulation",
            output_type=PromptedOutput(Simulation),
            deps_type=Materials,
            tools=[read_records],
            retries=1,
            instructions="你推演真实世界，按输入 catalogue 用 read_records 按需查本月实况。日期由输入给定，只写本月，写到本月底结束。交本段原文、零到多道奏疏及是否已写到月底。未到月底请旨是岔路；交回的每问独立，可各自续写。到月底附带奏疏是下个月开局奏折，不在本月执行。议处里的 presented_petition_id 是外廷已呈奏折匣的奏疏；议处全文供理解阻力与后果，该岔路不另写奏疏。新的独立岔路照常请旨。旨意推演只办输入已准各旨，不推其余世界；世界推演读各夜结果，只写其余发展和本月重议已准旨、上月已批奏疏。fiscal_events是本月到点应呈的饷率事件，写陈情与拟旨，停在本月岔路待皇帝批红，不自行准驳；留中不改征收，日后是否再上疏由人物自决。拨款用途、减额、暂欠、改序与摊派仍由人物与旨意决定。上月急务按所选办理；弹劾按原奏疏的署名人、被劾人及所选处置，写清皇威、发难派系的反应和被劾者去留的实际后果。查实再办要查被劾人实有行迹，写这一查费的工夫、所得及各方反应。人物异地启程要走完路程才能抵达，在途不改道；事务办完仍是日后人物行事的前情。续写接同段对话，只写当前这一问的后果，不替其他问选择、不重复已写部分。",
        )

    def publish(self, route: UUID, segment: dict[str, Any]) -> None:
        date = self.court.calendar().data
        output = Simulation.model_validate(segment["output"])
        available = petition_date(date, ended=output.month_end)
        petitions = [
            PendingPetition(
                **item.model_dump(),
                id=uuid4(),
                route_id=route,
                entity_id=route,
                segment_id=UUID(segment["id"]),
                available=available,
                blocking=not output.month_end,
                source="simulation",
            )
            for item in output.petitions
        ]
        self.court.record_product(route, "simulation", segment, petitions=petitions)

    async def call(self, context: dict[str, Any], history: list[Any]) -> dict[str, Any]:
        result = await invoke(
            self.agent,
            prompt(
                self.court,
                "world",
                {
                    **context,
                    "secret_orders": [
                        {
                            "decree": d.model_dump(mode="json"),
                            "known_people": sorted(self.court.known_people(d)),
                        }
                        for d in self.court.secret_decrees()
                    ],
                },
            ),
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
                "decree": self.court.entity(petition.entity_id).model_dump(mode="json")
                if petition.entity_id != petition.route_id else None,
                "deliberations": [f.detail for f in self.court.products(petition.entity_id, kind="deliberation")],
                "prior_interim": self.court.prior_interim(petition.entity_id),
                "instruction": "只续写这一问的后果到本月底。其他问保持待批；强颁则续写此旨及朝野反应。御笔强推是皇帝亲自担名，获外廷准后按正常旨办理。",
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
        return enlist(
            self.tasks,
            (petition.route_id, str(petition.id), option),
            lambda: self.forecast(petition, option),
            on_done=self.log_failure,
        )

    def log_failure(self, task: asyncio.Task[Any]) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            self.court.log.error("background simulation failed", exc_info=error)

    async def wait_for_choice(self, key: tuple[UUID, str, int]) -> None:
        task = self.tasks[key]
        try:
            await asyncio.shield(task)
        except Exception:
            # Failed speculation alone may be rerun on an actual selection.
            petition = self.court.as_petition(self.court.petition(key[1]))
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
        return enlist(
            self.continuations,
            (route, segment["id"]),
            lambda: self.continue_segment(route, segment),
            on_done=self.log_failure,
        )

    def start_push(
        self, petition: PendingPetition, option: int
    ) -> asyncio.Task[dict[str, Any]]:
        """One in-flight reconsideration for this petition; a failed task stays until recovery discards it."""
        key = str(petition.id)
        return enlist(
            self.pushes,
            key,
            lambda: self.reconsider(
                self.court.entity(petition.entity_id),
                petition.route_id,
                push_key(key, option),
            ),
            on_done=self.log_failure,
        )

    def hold_push(self, petition: PendingPetition, choice: dict[str, Any] | None) -> bool:
        """Start a selected imperial push the way a forecast is started. True once it no longer blocks."""
        if (
            choice is None
            or choice.get("text") != "御笔强推"
            or push_verdict(petition, self.court) is not None
        ):
            return True
        task = self.start_push(petition, choice["option"])
        return task.done() and task.exception() is None

    def open_pushes(self, petition_id: str | None) -> list[str]:
        return [
            key
            for key, task in self.pushes.items()
            if not (task.done() and task.exception() is None)
            and (petition_id is None or key == petition_id)
        ]

    def discard_failed(self, petition_id: str | None) -> None:
        """Drop failed tasks this recovery entry will start again. A fresh failure stays."""
        chain = self.chain(petition_id)
        for key, task in list(self.continuations.items()):
            if (
                (key[1] in chain if petition_id is not None else key[1] not in chain)
                and task.done() and task.exception() is not None
            ):
                del self.continuations[key]
        for key, task in list(self.pushes.items()):
            if (
                (petition_id is None or key == petition_id)
                and task.done() and task.exception() is not None
            ):
                del self.pushes[key]

    def advance_petition(
        self,
        petition: PendingPetition,
        choice: dict[str, Any] | None,
        segments: list[dict[str, Any]],
        petition_id: str | None,
    ) -> tuple[bool, bool]:
        """Return whether this petition blocks, and whether a segment was published."""
        if choice is not None and petition_id not in (None, str(petition.id)):
            return False, False
        blocks = not self.hold_push(petition, choice)
        if not segments:
            return blocks, False
        options = continuing_options(petition, self.court)
        for option in options:
            self.start_forecast(petition, option)
        if (
            choice is None
            or choice["option"] not in options
            or any(s.get("petition_id") == str(petition.id) for s in segments)
        ):
            return blocks, False
        task = self.start_forecast(petition, choice["option"])
        if not task.done() or task.exception() is not None:
            return True, False
        self.publish(petition.route_id, task.result())
        return blocks, True

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
                self.court.as_petition(f) for f in self.court.route_petitions(route)
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
                blocks, published = self.advance_petition(
                    petition, choices.get(str(petition.id)), segments, petition_id
                )
                ready = ready and not blocks
                progressed = progressed or published
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
            *self.pushes.values(),
        ]
        if tasks:
            # Candidate failures are logged by log_failure; they are not formal work.
            await asyncio.gather(*tasks, return_exceptions=True)
