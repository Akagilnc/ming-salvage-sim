"""Identity-specific structured read boundary; no summaries of model prose."""

from typing import Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import case, literal, or_
from sqlalchemy.sql.elements import ColumnElement

from ming.ledger import Item, Ledger
from ming.ledger import ENTITY_COLUMNS as E, FACT_COLUMNS as F, ENTITY_ROWS, FACT_ROWS
from ming.middle.queries import available_on, public_decree
from ming.middle.night import known_people, read_night

PublicIdentity = Literal["emperor", "audit", "world", "public"]


class Officials(BaseModel):
    people: list[str]
    exclude_secrets: bool = False


Identity = PublicIdentity | Officials

# ADR 0143: retain the canonical score bands in the independent rewrite.
CHARACTER_BANDS = {
    "loyalty": ("离心已显", "心志浮动", "大体守中", "颇知向背", "可托腹心"),
    "ability": ("才具浅薄", "才具有限", "堪当常务", "才具出众", "足任大事"),
    "integrity": ("操守多亏", "操守未稳", "操守平常", "操守清正", "清介可称"),
    "courage": ("临事易退", "多有顾忌", "进退审慎", "敢任其事", "临难不屈"),
    "identity": ("几乎不染党色", "党色较淡", "党色不显", "党色较深", "党色极深"),
    "intrigue": ("毫无城府", "心思疏浅", "善藏行迹", "机权深沉", "鬼蜮难测"),
    "imperial_prestige": ("威令未立", "威福旁落", "威令渐行", "威权深重", "威压朝野"),
}


def character_input(value: Any) -> Any:
    """Project structured axes and declaration endpoints, never model prose.

    Used only by mixed/player-facing calls; the ledger and pure-machine reads
    retain their numerical inputs, including world facts such as money and arms.
    """
    if isinstance(value, list):
        return [character_input(item) for item in cast(list[Any], value)]
    if not isinstance(value, dict):
        return value
    result = {
        key: character_input(item)
        for key, item in cast(Item, value).items()
        if key not in {"remaining_distance", "travel_speed"}
    }
    if result.get("field") == "travel_speed":
        return {
            "field": "travel_pace",
            "value": "加急" if value["value"] > 1 else "常速",
        }
    fields = [(key, key) for key in CHARACTER_BANDS if key in result]
    if result.get("field") in CHARACTER_BANDS and "value" in result:
        fields.append(("value", result["field"]))
    for key, axis in fields:
        if type(result[key]) in (int, float):
            result[key] = CHARACTER_BANDS[axis][
                sum(int(result[key]) >= cutoff for cutoff in (20, 40, 60, 80))
            ]
    return result


def journey(data: Item, events: list[Item]) -> Item:
    """Derive elapsed/total months from the existing departure and monthly ticks."""
    if not data.get("transit_to"):
        return {}
    departure = max(i for i, e in enumerate(events) if e["kind"] == "departed")
    detail = events[departure]["detail"]
    speed = detail.get("travel_speed", 1)
    return {
        "elapsed_months": sum(
            e["kind"] == "travelled" for e in events[departure + 1 :]
        ),
        "total_months": detail["distance"] / speed,
        **({"pace": "加急"} if speed > 1 else {}),
    }


class EntityView(BaseModel):
    id: UUID
    kind: str
    key: str
    source: str
    data: dict[str, Any]


class FactView(BaseModel):
    entity_id: UUID
    kind: str
    emperor_words: str
    detail: dict[str, Any]


def owned_accounts(ledger: Ledger, identity: Identity) -> set[UUID]:
    if not isinstance(identity, Officials):
        return set()
    rows = ledger.entities(kind=("office_type", "account")) + ledger.entities(
        kind="person", query=ENTITY_ROWS.where(E.key.in_(identity.people))
    )
    # Resolve the current formal title through the imported office catalogue,
    # never a person's stale office_type or an umbrella-office exception.
    departments = {
        next(
            (
                rule["data"]["type"]
                for rule in rows
                if rule["kind"] == "office_type"
                and any(stem in r["data"]["office"] for stem in rule["data"]["stems"])
            ),
            None,
        )
        for r in rows
        if r["kind"] == "person"
        and r["data"].get("office")
        and r["data"].get("status", "active") == "active"
    } - {None, "内阁", "司礼监"}
    return {
        r["id"]
        for r in rows
        if r["kind"] == "account" and r["data"].get("department") in departments
    }


def month_open(ledger: Ledger) -> Item | None:
    """The month's persisted emperor projection, not execution state."""
    calendar = next(iter(ledger.entities(kind="calendar")), None)
    if calendar is None:
        return None
    return next(
        (
            e["detail"]
            for e in reversed(
                ledger.facts(
                    entity_id=calendar["id"], kind="month_open", date=calendar["data"]
                )
            )
        ),
        None,
    )


def decree_access(ledger: Ledger, identity: Identity) -> dict[str, set[UUID]]:
    access: dict[str, set[UUID]] = {"known": set(), "handled": set(), "secret": set()}
    for row in ledger.entities(
        kind="decree", query=ENTITY_ROWS.add_columns(public_decree().label("public"))
    ):
        if row["data"]["secret"]:
            access["secret"].add(row["id"])
            if isinstance(identity, Officials) and identity.exclude_secrets:
                continue
        if (
            identity == "emperor"
            or row["public"]
            or (
                isinstance(identity, Officials)
                and known_people(ledger, row).intersection(identity.people)
            )
        ):
            access["known"].add(row["id"])
        if identity == "emperor" or (
            isinstance(identity, Officials)
            and set(row["data"]["people"]).intersection(identity.people)
        ):
            access["handled"].add(row["id"])
    return access


def entities(
    ledger: Ledger, identity: Identity, selection: Item | None = None
) -> list[EntityView]:
    selection = dict(selection or {})
    sourced = selection.pop("sourced", False)
    if identity == "emperor" and (opening := month_open(ledger)):
        return [
            EntityView.model_validate(e)
            for e in opening["entities"]
            if all(e[k] == v for k, v in (selection or {}).items())
        ]
    access = (
        decree_access(ledger, identity) if identity not in ("audit", "world") else {}
    )
    exposure = entity_exposure(identity, owned_accounts(ledger, identity), access)
    query = ENTITY_ROWS.add_columns(exposure.label("exposure")).where(
        exposure.is_not(None)
    )
    if sourced:
        query = query.where(E.source != "")
    rows = ledger.entities(**selection, query=query)
    result: list[EntityView] = []
    for row in rows:
        if identity not in ("audit", "world"):
            if row["exposure"] == "person":
                row["data"] = {
                    k: v
                    for k, v in row["data"].items()
                    if k in {"name", "office", "location", "status"}
                }
            elif row["exposure"] == "night":
                row["data"] = read_night(ledger, row["id"]).model_dump(mode="json")
            elif row["exposure"] == "decree":
                row["data"] = {
                    k: v
                    for k, v in row["data"].items()
                    if k in {"text", "origin", "people", "night_id", "secret", "turn"}
                }
        if identity == "world" and row["kind"] == "person":
            travel = (
                journey(row["data"], ledger.facts(entity_id=row["id"]))
                if row["data"].get("transit_to")
                else {}
            )
            row["data"] = {
                k: v
                for k, v in row["data"].items()
                if k not in {"remaining_distance", "travel_speed"}
            }
            if travel:
                row["data"]["journey"] = travel
        result.append(EntityView.model_validate(row))
    return result


def entity_exposure(
    identity: Identity, accounts: set[UUID], access: dict[str, set[UUID]]
) -> ColumnElement[str]:
    if identity in ("audit", "world"):
        return literal("full")
    rules = [
        (E.id.in_(accounts), "full"),
        (E.kind == "person", "person"),
        (E.kind.in_(("gazette", "calendar")), "full"),
        (E.id.in_(access["known"]), "decree"),
    ]
    if identity == "emperor":
        rules.extend([(E.kind == "night", "night"), (E.kind == "decree", "decree")])
    return case(*rules)


def fact_exposure(
    identity: Identity, accounts: set[UUID], access: dict[str, set[UUID]]
) -> ColumnElement[str]:
    if identity == "audit":
        return literal("full")
    if identity == "world":
        return case((F.kind != "forecast", "full"))
    audiences = (
        ("public", "official")
        if identity == "public" or isinstance(identity, Officials)
        else ("public",)
    )
    # A person reads his whole own history (scene dossier) before any audience
    # rule; person-side decree links surface through the decree entity instead.
    rules: list[tuple[ColumnElement[bool], str]] = (
        [
            (
                (E.kind == "person")
                & E.key.in_(identity.people)
                & (F.kind != "decreed"),
                "dated",
            )
        ]
        if isinstance(identity, Officials)
        else []
    )
    rules.append(
        (
            or_(F.kind == "gazette", F.detail["audience"].as_string().in_(audiences)),
            "text",
        )
    )
    rules.extend(
        [
            (E.id.in_(access["known"]) & (F.kind == "decreed"), "dated"),
            (E.id.in_(access["handled"]) & (F.kind == "secret_report"), "dated"),
            (
                (E.kind == "person")
                & F.kind.in_(
                    (
                        "changed",
                        "displaced",
                        "departed",
                        "arrived",
                        "travelled",
                        "audience_admitted",
                    )
                ),
                "dated",
            ),
        ]
    )
    if identity == "emperor":
        rules.append((F.kind == "interaction", "full"))
    rules.append((F.kind.in_(("petition", "choice")), "full"))
    if identity == "emperor":
        rules.append((F.kind == "unhandled", "empty"))
    if isinstance(identity, Officials):
        rules.append((E.id.in_(accounts) & F.kind.in_(("changed", "received")), "text"))
    return case(*rules)


def project(
    ledger: Ledger, identity: Identity, selection: Item | None = None
) -> list[FactView]:
    selection = selection or {}
    opening = month_open(ledger) if identity == "emperor" else None
    date = next((r["data"] for r in ledger.entities(kind="calendar")), dict[str, Any]())
    controls = {"interaction", "petition", "choice", "gazette", "secret_report"}
    access = (
        decree_access(ledger, identity) if identity not in ("audit", "world") else {}
    )
    exposure = fact_exposure(identity, owned_accounts(ledger, identity), access)
    query = FACT_ROWS.add_columns(exposure.label("exposure")).where(
        exposure.is_not(None)
    )
    if identity not in ("audit", "world"):
        query = query.where(
            ~(
                F.detail["origin_ref"]
                .as_string()
                .in_([str(i) for i in access["secret"] - access["handled"]])
                & F.detail["discovered"].as_boolean().is_(True)
            )
        )
    if identity != "audit":
        query = query.where(available_on(date))
    if opening:
        query = query.where(F.kind.in_(controls))
    result: list[FactView] = (
        [
            FactView.model_validate(f)
            for f in opening["facts"]
            if f["kind"] not in controls
            and (
                selection.get("entity_id") is None
                or f["entity_id"]
                in (
                    [
                        str(entity_id)
                        for entity_id in cast(list[UUID], selection["entity_id"])
                    ]
                    if isinstance(selection["entity_id"], list)
                    else [str(selection["entity_id"])]
                )
            )
            and (
                selection.get("kind") is None
                or f["kind"]
                in (
                    (selection["kind"],)
                    if isinstance(selection["kind"], str)
                    else selection["kind"]
                )
            )
            and (
                selection.get("date") is None
                or f["detail"].get("date") == selection["date"]
            )
        ]
        if opening
        else []
    )
    for item in ledger.facts(**selection, query=query):
        fact = FactView(**item)
        if identity == "world" and fact.kind in {"departed", "travelled", "arrived"}:
            fact.detail = {
                k: v
                for k, v in fact.detail.items()
                if k not in {"distance", "remaining_distance", "travel_speed"}
            }
        if identity == "world" and fact.kind == "simulation":
            fact.detail = {k: v for k, v in fact.detail.items() if k != "messages"}
        if identity not in ("audit", "world"):
            if item["exposure"] in ("text", "dated"):
                fact.detail = {
                    "text": fact.detail.get("text", ""),
                    **{
                        k: v
                        for k, v in fact.detail.items()
                        if item["exposure"] == "dated" and k in {"date", "successor"}
                    },
                }
            elif item["exposure"] == "empty":
                fact.detail = {}
            fact.emperor_words = ""
        result.append(fact)
    return result
