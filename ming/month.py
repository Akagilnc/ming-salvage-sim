"""Month user: ledger products are the only durable continuation state."""

import asyncio
import json
from uuid import UUID

from pydantic_ai import Agent
from pydantic_ai.models import Model

from ming.middle.court import Court
from ming.middle.invoke import invoke, transport_model
from ming.middle.declaration import Declaration, PendingPetition
from ming.middle.translate import Unhandled
from ming.middle.view import Identity, Officials, character_input


class Month:
    def __init__(self, court: Court, model: Model) -> None:
        self.court = court
        self._model = transport_model(model)

    async def text(
        self,
        instructions: str,
        identity: Identity,
        context: object,
        background: bool = False,
    ) -> str:
        rows = self.court.entities(identity)
        agent = Agent(
            self._model,
            output_type=str,
            instructions=instructions
            + "用 read_records 按类型和正名查账；材料只据所读，不猜未读实况。",
        )

        @agent.tool_plain
        async def read_records(
            kind: str | None = None, key: str | None = None
        ) -> dict[str, object]:
            """按类型与正名取本身份材料；空参取全部可读材料，含各衙门呈报的文字。"""
            return character_input(await self.court.read_records(identity, kind, key))

        result = await invoke(
            agent,
            json.dumps(
                character_input(
                    {
                        "context": context,
                        "catalogue": [{"kind": e.kind, "key": e.key} for e in rows],
                    }
                ),
                ensure_ascii=False,
            ),
            background,
        )
        self.court.log.info("model output: %s", result.output)
        return result.output

    async def prepare(self, route_id: UUID, *, background: bool = False) -> None:
        async with self.court.locks[route_id]:
            try:
                route = next(e for e in self.court.entities("audit") if e.id == route_id)
                if any(
                    f.entity_id == route_id and f.kind in {"landed", "unhandled"}
                    for f in self.court.facts("audit")
                ):
                    return
                if any(p.route_id == route.id for p in self.court.petitions()):
                    return
                history = self.court.products(route.id)
                round_number = max(
                    (f.detail["round"] + 1 for f in history if f.kind == "choice"),
                    default=0,
                )
                products = {
                    f.kind: f
                    for f in history
                    if f.detail.get("round", round_number) == round_number
                }
                if route.kind == "decree" and "deliberation" not in products:
                    output = await self.text(
                        "你演外廷内阁票拟、六科封驳、部院议处。只写文字，准驳由你判断，"
                        "不交判决字段。按经手官员所知议处这道定稿圣旨，不得用世界全知。",
                        Officials(people=route.data["people"]),
                        {"route": route.model_dump(mode="json")},
                        background,
                    )
                    self.court.record_product(route.id, "deliberation", {"text": output})
                history = self.court.products(route.id)
                context = {
                    "route": route.model_dump(mode="json"),
                    "history": [f.model_dump(mode="json") for f in history],
                }
                if "simulation" not in products:
                    output = await self.text(
                        "你推演真实世界。只写文字，不交字段。各道旨依外廷准驳办理；"
                        "世界推演只推进在途事务与世界局势，别重复办理同月新旨。"
                        "旨意以 decree 实体为准，night 是谈话记录，未成旨的拟议不执行。"
                        "按史实尺度推演后果，需要皇帝定夺就写奏疏与处置选项，停在岔路。"
                        "皇帝已经选了则从岔路继续。官员可谎报，奏报与物理实况分别写清。",
                        "world",
                        context,
                        background,
                    )
                    self.court.record_product(
                        route.id, "simulation", {"text": output, "round": round_number}
                    )
                if "declaration" not in products:
                    result = await self.court.translate_month(
                        json.dumps(
                            {
                                "route": route.model_dump(mode="json"),
                                "products": [
                                    f.model_dump(mode="json")
                                    for f in self.court.products(route.id)
                                ],
                                "round": round_number,
                            },
                            ensure_ascii=False,
                        ),
                        background,
                    )
                    self.court.store_declaration(route.id, result, round_number)
            except Exception:
                self.court.log.exception(
                    "prepare route=%s background=%s", route_id, background
                )
                # Night work is speculative; the documented recovery is month.advance().
                if not background:
                    raise

    async def choose(
        self, petition_id: UUID, option: int, *, background: bool = True
    ) -> None:
        route_id = self.court.choose(petition_id, option)
        # A task is only live caller context; the current month's world route
        # survives reopening and makes a presented petition foreground work.
        background = (
            background
            and not self.court.locks[self.court.calendar().id].locked()
            and self.court.world_route(create=False) is None
        )
        await self.prepare(route_id, background=background)

    async def advance(self) -> list[PendingPetition]:
        async with self.court.locks[self.court.calendar().id]:
            try:
                world = self.court.world_route()
                assert world is not None  # Creation is enabled for month advancement.
                for night_id in self.court.pending_nights():
                    await self.court.translate_night(night_id)
                landed = {
                    f.entity_id
                    for f in self.court.facts("audit")
                    if f.kind in {"landed", "unhandled"}
                }
                routes = [
                    e for e in self.court.approved_decrees() if e.id not in landed
                ] + [world]
                results = await asyncio.gather(
                    *(self.prepare(e.id) for e in routes), return_exceptions=True
                )
                for result in results:
                    if isinstance(result, BaseException):
                        raise result
                if pending := self.court.petitions():
                    return pending
                for route in routes:
                    # A choice can arrive while the other routes are still preparing.
                    await self.prepare(route.id)
                    if pending := self.court.petitions():
                        return pending
                    products = self.court.products(route.id)
                    if any(f.kind in {"landed", "unhandled"} for f in products):
                        continue
                    declarations = [f.detail for f in products if f.kind == "declaration"]
                    last = declarations[-1]
                    result = (
                        Unhandled if last["unhandled"] else Declaration
                    ).model_validate(last["result"])
                    self.court.store_declaration(route.id, result, None)
                calendar = self.court.calendar()
                if not any(f.kind == "gazette" for f in self.court.products(calendar.id)):
                    output = await self.text(
                        "全部月末后果已落账。以朝廷公开口径写本月邸报，保留官员奏报说法，"
                        "用 read_records() 读各衙门奏报文字，不套模板，不把奏报当核算数。",
                        "public",
                        calendar.model_dump(mode="json"),
                    )
                    self.court.record_product(calendar.id, "gazette", {"text": output})
                month = calendar.data["month"]
                self.court.record_product(
                    calendar.id,
                    "advanced",
                    {},
                    {
                        "year": calendar.data["year"] + (month == 12),
                        "month": month % 12 + 1,
                    },
                )
                return []
            except Exception:
                self.court.log.exception("advance month")
                raise
