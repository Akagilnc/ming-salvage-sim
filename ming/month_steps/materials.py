"""Month interprets bounded records and assembles complete model materials."""

from collections import defaultdict
from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from ming.middle.court import Court
from ming.middle.declaration import StrictModel
from ming.middle.view import EntityView, FactView, Identity, Officials, character_input


PENDING_PETITIONS: tuple[Identity, str, str, tuple[str, str]] = ("world", "petition", "choice", ("id", "petition_id"))

COST_RULES = """背书（含御笔手敕、御笔强推）本身不走代价轨。
强颁与预先中旨共用代价轨：实际颁出才付皇威；相关派系／阶级满意度反应可正可负可零。
预先中旨被驳也有满意度反应与中旨名声，但不执行旨意、不扣皇威；收回、留中不抹去已经发生的中旨尝试反应。
同旨背书与中旨并存只计一份代价。prior_interim 是本旨已记的中旨历史，重议不重复已付反应；后来获准或强颁只补实际颁出的皇威代价。
撤回成命交皇威、当事大臣与相关派系反应；收权罢差零毁约代价。正规被驳旨收回、留中中性。民心不是这些动作的固定代价。"""


class Petition(StrictModel):
    text: str
    options: list[str] = Field(min_length=1)


class PendingPetition(Petition):
    id: UUID
    entity_id: UUID
    available: dict[str, Any]
    blocking: bool
    source: str
    signer: str | None = None
    target: str | None = None
    revision_of: UUID | None = None
    ordinal: int = 0


class Deliberation(StrictModel):
    text: str = Field(description="外廷议处原文。")
    verdict: Literal["准", "驳", "中旨亦不可颁"] = Field(description="议处结局，含义见外廷判词。")


class MonthText(StrictModel):
    text: str = Field(description="本月推演正文，含义见月草稿、月定稿。")


class Simulation(MonthText):
    petitions: list[Petition] = Field(default_factory=list[Petition], description="本月岔路口奏疏列表，无岔路可省略；含义见岔路口。")


def as_petition(fact: FactView) -> PendingPetition:
    return PendingPetition.model_validate({k: v for k, v in fact.detail.items() if k != "date"})


def next_month(date: dict[str, Any]) -> dict[str, Any]:
    return {"year": date["year"] + (date["month"] == 12), "month": date["month"] % 12 + 1}


def pending_petitions(court: Court, petition_id: str | None = None) -> tuple[PendingPetition, ...]:
    return tuple(sorted(
        (as_petition(f) for f in court.read.unmatched(
            *PENDING_PETITIONS, detail={"id": petition_id} if petition_id is not None else None,
        )),
        key=lambda p: (p.available["year"], p.available["month"], p.ordinal),
    ))


def has_pending_petitions(court: Court) -> bool:
    return court.read.has_unmatched(*PENDING_PETITIONS)


def petition_officials(court: Court, faction: str | None = None) -> tuple[str, ...]:
    return court.read.office_holders(("内阁首辅", "司礼监掌印太监") if faction is None else None, faction=faction)


def month_petitions(court: Court, date: dict[str, Any]) -> tuple[FactView, ...]:
    return court.read.facts("audit", kind="petition", date=date, detail={"blocking": True})


def pending_pushes(court: Court, date: dict[str, Any]) -> tuple[tuple[EntityView, dict[str, Any]], ...]:
    backings = [f for f in court.read.unmatched("audit", "endorsed", "deliberation", ("decision_key", "decision_key"))
                if f.detail["decision_key"].get("petition_id") is not None
                and (f.detail["date"]["year"], f.detail["date"]["month"]) < (date["year"], date["month"])]
    return tuple((e, f.detail["decision_key"]) for e in court.read.entities("audit", kind="decree", ids=[f.entity_id for f in backings])
                 for f in backings if f.entity_id == e.id)


def prior_choices(court: Court, date: dict[str, Any]) -> list[dict[str, Any]]:
    choices = court.read.related_details("choice", "petition", ("petition_id", "id"), date=date,
                                        detail={"source": ["urgent", "impeachment"]})
    returned: set[str] = court.returned_petition_ids([p["id"] for _, p in choices]) if choices else set()
    return [{**choice, "petition": petition} for choice, petition in choices if petition["id"] not in returned]


def landing_materials(court: Court, *, include_history: bool = True, date: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    materials: list[dict[str, Any]] = []
    sources = court.read.landing_sources(date, include_history=include_history)
    known = court.read.known_people([row["id"] for row, _mode, _events in sources if row["data"]["secret"]])
    prior: dict[UUID, list[dict[str, Any]]] = defaultdict(list)
    if current_ids := [row["id"] for row, mode, events in sources if mode is not None or events]:
        for event in court.read.facts("audit", entity_id=current_ids, kind="interim"):
            prior[event.entity_id].append(event.detail)
    for row, mode, events in sources:
        decree = EntityView.model_validate(row)
        deliberations = [FactView(**event) for event in events]
        current = mode is not None or bool(deliberations)
        materials.append({
            "decree": decree.model_dump(mode="json") if current else {
                "id": str(decree.id), "kind": decree.kind, "key": decree.key,
                "data": {"secret": False},
            },
            "mode": mode,
            "deliberations": [f.model_dump(mode="json") for f in deliberations],
            "prior_interim": prior[decree.id] if current else [],
            **({"known_people": known[decree.id]} if decree.data["secret"] else {}),
        })
    return tuple(materials)


def prepare(
    court: Court, pending: dict[int, Officials], context: Any, *, date: dict[str, Any],
) -> dict[int, tuple[Officials, dict[str, Any]]]:
    """Share unchanged inputs by complete identity only within this pending batch."""
    inputs: dict[str, dict[str, Any]] = {}
    prepared: dict[int, tuple[Officials, dict[str, Any]]] = {}
    for index, identity in pending.items():
        key = identity.model_dump_json()
        if key not in inputs:
            inputs[key] = prompt(court, identity, context, date=date)
        prepared[index] = identity, inputs[key]
    return prepared


def prompt(court: Court, identity: Identity, context: Any, *, date: dict[str, Any]) -> dict[str, Any]:
    speakers = {e.key: e.model_dump(mode="json") for e in court.read.entities(
        identity, kind="person", key=identity.people,
    )} if isinstance(identity, Officials) and identity.people else {}
    return character_input({
        "date": date,
        "context": context,
        "catalogue": court.read.record_catalogue(identity),
        **({"speakers": [speakers[name] for name in identity.people if name in speakers]}
           if isinstance(identity, Officials) else {}),
    })
