"""Month user: explicit opening, route products, petitions and monthly landing."""

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from uuid import UUID, uuid4
from typing import Any

from pydantic_ai import Agent, RunContext

from ming.middle.court import Court
from ming.middle.invoke import ModelSource, build_agent, invoke, stream_text
from ming.middle.declaration import Declaration, PendingPetition, Petition, Unhandled
from ming.middle.opening import CONTENT
from ming.middle.view import EntityView, FactView, Identity, Officials, character_input


@dataclass
class Materials:
    court: Court
    identity: Identity


async def read_records(
    ctx: RunContext[Materials], kind: str | None = None, key: str | None = None
) -> dict[str, object]:
    """按类型与正名取本身份材料；空参取全部可读材料，含各衙门呈报的文字。"""
    return character_input(
        await ctx.deps.court.read_records(ctx.deps.identity, kind, key)
    )


class Month:
    def __init__(
        self,
        court: Court,
        model: ModelSource,
        on_delta: Callable[[str], None] | None = None,
    ) -> None:
        self.court = court
        self.on_delta = on_delta
        self.tasks: dict[UUID, tuple[asyncio.Task[None], bool]] = {}
        self.translation = court.translation_agent(
            Declaration, (CONTENT / "prompts/month_translate.md").read_text()
        )
        self.deliberation = build_agent(
            model,
            name="deliberation",
            output_type=str,
            deps_type=Materials,
            tools=[read_records],
            instructions="你演外廷内阁票拟、六科封驳、部院议处。只写文字，准驳由你判断，不交判决字段。按经手官员所知议处这道定稿圣旨，不得用世界全知。用 read_records 按类型和正名查账；材料只据所读，不猜未读实况。",
        )
        self.simulation = build_agent(
            model,
            name="simulation",
            output_type=str,
            deps_type=Materials,
            tools=[read_records],
            instructions="你推演真实世界。只写文字，不交字段。各道旨依外廷准驳办理；世界推演只推进在途事务与世界局势，别重复办理同月新旨。旨意以 decree 实体为准，night 是谈话记录，未成旨的拟议不执行。按史实尺度推演后果，需要皇帝定夺就写奏疏与处置选项，停在岔路。皇帝已经选了则从岔路继续。官员可谎报，奏报与物理实况分别写清。用 read_records 按类型和正名查账；材料只据所读，不猜未读实况。",
        )
        self.gazette = build_agent(
            model,
            name="gazette",
            output_type=str,
            deps_type=Materials,
            tools=[read_records],
            instructions="全部月末后果已落账。以朝廷公开口径写本月邸报，保留官员奏报说法，用 read_records() 读各衙门奏报文字，不套模板，不把奏报当核算数。",
        )

    def decrees(self) -> list[EntityView]:
        landed = {
            f.entity_id
            for f in self.court.facts("audit")
            if f.kind in {"landed", "unhandled"}
        }
        return [
            e
            for e in self.court.entities("audit")
            if e.kind == "decree" and e.id not in landed
        ]

    def products(self, entity_id: UUID) -> list[FactView]:
        date = self.court.calendar().data
        return [
            f
            for f in self.court.facts("audit")
            if f.entity_id == entity_id and f.detail.get("date") == date
        ]

    def record_product(
        self,
        entity_id: UUID,
        kind: str,
        detail: dict[str, object],
        changes: dict[str, object] | None = None,
    ) -> None:
        self.court.record(
            entity_id, [(kind, {**detail, "date": self.court.calendar().data})], changes
        )

    def opened(self) -> bool:
        return any(
            f.kind == "month_open" for f in self.products(self.court.calendar().id)
        )

    def open(self) -> EntityView:
        date = self.court.calendar().data
        key = f"world:{date['year']}:{date['month']}"
        if not self.opened():
            self.record_product(
                self.court.calendar().id,
                "month_open",
                {
                    "entities": [
                        e.model_dump(mode="json")
                        for e in self.court.entities("emperor")
                    ],
                    "facts": [
                        f.model_dump(mode="json") for f in self.court.facts("emperor")
                    ],
                },
            )
        route = next(
            (
                e
                for e in self.court.entities("audit")
                if e.kind == "affair" and e.key == key
            ),
            None,
        )
        if route is None:
            self.court.record(
                ("affair", key), [("route", {"date": date})], {"text": "世界局势"}
            )
        return next(
            e
            for e in self.court.entities("audit")
            if e.kind == "affair" and e.key == key
        )

    def petitions(self) -> list[PendingPetition]:
        facts = self.court.facts("audit")
        chosen = {f.detail["petition_id"] for f in facts if f.kind == "choice"}
        return [
            PendingPetition.model_validate(
                {k: v for k, v in f.detail.items() if k != "date"}
            )
            for f in facts
            if f.kind == "petition" and f.detail["id"] not in chosen
        ]

    def choose(self, petition_id: UUID, option: int) -> UUID:
        petition = next(
            (
                PendingPetition.model_validate(
                    {k: v for k, v in f.detail.items() if k != "date"}
                )
                for f in self.court.facts("audit")
                if f.kind == "petition" and f.detail["id"] == str(petition_id)
            ),
            None,
        )
        if (
            petition is None
            or type(option) is not int
            or not 0 <= option < len(petition.options)
        ):
            raise ValueError("not a petition option")
        history = self.products(petition.route_id)
        if any(
            f.kind in {"landed", "unhandled"}
            or (f.kind == "simulation" and f.detail["round"] > petition.round)
            for f in history
        ) or not any(
            f.kind == "petition" and f.detail["id"] == str(petition_id) for f in history
        ):
            raise ValueError("petition continuation already written")
        self.record_product(
            petition.route_id,
            "choice",
            {
                "petition_id": str(petition_id),
                "option": option,
                "round": petition.round,
                "text": petition.options[option],
            },
        )
        work = self.tasks.get(petition.route_id)
        if work is not None and not work[0].done():
            work[0].cancel()
        return petition.route_id

    def store_declaration(
        self, route_id: UUID, result: Declaration | Unhandled, round_number: int
    ) -> None:
        events: list[tuple[str, dict[str, Any]]] = []
        date = self.court.calendar().data
        if isinstance(result, Declaration):
            for fact in result.facts:
                for change in fact.changes:
                    if change.field == "petition":
                        petition = PendingPetition(
                            **Petition.model_validate(change.value).model_dump(),
                            id=uuid4(),
                            route_id=route_id,
                            entity_id=route_id,
                            round=round_number,
                        )
                        events.append(
                            (
                                "petition",
                                {**petition.model_dump(mode="json"), "date": date},
                            )
                        )
        events.append(
            (
                "declaration",
                {
                    "result": result.model_dump(),
                    "unhandled": isinstance(result, Unhandled),
                    "round": round_number,
                    "date": date,
                },
            )
        )
        self.court.record(route_id, events)

    async def text(
        self, agent: Agent[Materials, str], identity: Identity, context: object
    ) -> str:
        result = await invoke(
            agent,
            json.dumps(
                character_input(
                    {
                        "context": context,
                        "catalogue": [
                            {"kind": e.kind, "key": e.key}
                            for e in self.court.entities(identity)
                        ],
                    }
                ),
                ensure_ascii=False,
            ),
            deps=Materials(self.court, identity),
            event_stream_handler=partial(stream_text, self.on_delta)
            if identity == "public" and self.on_delta
            else None,
        )
        self.court.log.info("model output: %s", result.output)
        return result.output

    async def prepare(self, route_id: UUID, *, speculative: bool = False) -> None:
        while True:
            work = self.tasks.get(route_id)
            if work is None or work[0].done():
                work = self.tasks[route_id] = (
                    asyncio.create_task(self._prepare(route_id)),
                    speculative,
                )
            task, was_speculative = work
            try:
                await asyncio.shield(task)
                return
            except asyncio.CancelledError:
                current = asyncio.current_task()
                if current is None or current.cancelling() or not task.cancelled():
                    raise
                # A newer recorded choice replaced this route's in-flight call.
            except Exception:
                if speculative or not was_speculative:
                    raise
                # The night caller logs its failure; month fills the missing products.

    async def _prepare(self, route_id: UUID) -> None:
        route = next(e for e in self.court.entities("audit") if e.id == route_id)
        history = self.products(route_id)
        if any(f.kind in {"landed", "unhandled"} for f in history) or any(
            p.route_id == route_id for p in self.petitions()
        ):
            return
        round_number = max(
            (f.detail["round"] + 1 for f in history if f.kind == "choice"), default=0
        )
        products = {
            f.kind
            for f in history
            if f.detail.get("round", round_number) == round_number
        }
        if route.kind == "decree" and "deliberation" not in products:
            output = await self.text(
                self.deliberation,
                Officials(people=route.data["people"]),
                {"route": route.model_dump(mode="json")},
            )
            self.record_product(route_id, "deliberation", {"text": output})
        if "simulation" not in products:
            history = self.products(route_id)
            latest = {f.detail["petition_id"]: f for f in history if f.kind == "choice"}
            output = await self.text(
                self.simulation,
                "world",
                {
                    "route": route.model_dump(mode="json"),
                    "history": [
                        f.model_dump(mode="json")
                        for f in history
                        if f.kind != "choice" or latest[f.detail["petition_id"]] is f
                    ],
                },
            )
            self.record_product(
                route_id, "simulation", {"text": output, "round": round_number}
            )
        if "declaration" not in products:
            result = await self.court.translate(
                self.translation,
                json.dumps(
                    {
                        "route": route.model_dump(mode="json"),
                        "products": [
                            f.model_dump(mode="json") for f in self.products(route_id)
                        ],
                        "round": round_number,
                    },
                    ensure_ascii=False,
                ),
            )
            self.store_declaration(route_id, result, round_number)

    async def advance(self) -> list[PendingPetition]:
        world = self.open()
        routes = self.decrees() + [world]
        results = await asyncio.gather(
            *(self.prepare(e.id) for e in routes), return_exceptions=True
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result
        if pending := self.petitions():
            return pending
        for route in routes:
            await self.prepare(route.id)
            if pending := self.petitions():
                return pending
            products = self.products(route.id)
            if any(f.kind in {"landed", "unhandled"} for f in products):
                continue
            last = [f.detail for f in products if f.kind == "declaration"][-1]
            result = (Unhandled if last["unhandled"] else Declaration).model_validate(
                last["result"]
            )
            self.court.land(result, route.id, monthly=True)
        calendar = self.court.calendar()
        if not any(f.kind == "gazette" for f in self.products(calendar.id)):
            output = await self.text(
                self.gazette, "public", calendar.model_dump(mode="json")
            )
            self.record_product(calendar.id, "gazette", {"text": output})
        month = calendar.data["month"]
        self.record_product(
            calendar.id,
            "advanced",
            {},
            {"year": calendar.data["year"] + (month == 12), "month": month % 12 + 1},
        )
        return []
