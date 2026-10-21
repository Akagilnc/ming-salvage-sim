"""Identity-specific structured read boundary; no summaries of model prose."""

from typing import Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel

from ming.ledger import Item, Ledger
from ming.middle.night import read_night

PublicIdentity = Literal["emperor", "audit", "world", "public"]


class Officials(BaseModel):
    people: list[str]


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
    result = {key: character_input(item) for key, item in cast(Item, value).items()}
    fields = [(key, key) for key in CHARACTER_BANDS if key in result]
    if result.get("field") in CHARACTER_BANDS and "value" in result:
        fields.append(("value", result["field"]))
    for key, axis in fields:
        if type(result[key]) in (int, float):
            result[key] = CHARACTER_BANDS[axis][
                sum(int(result[key]) >= cutoff for cutoff in (20, 40, 60, 80))
            ]
    return result


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


def owned_accounts(rows: list[Item], identity: Identity) -> set[UUID]:
    if not isinstance(identity, Officials):
        return set()
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
        and r["key"] in identity.people
        and r["data"].get("office")
        and r["data"].get("status", "active") == "active"
    } - {None, "内阁", "司礼监"}
    return {
        r["id"]
        for r in rows
        if r["kind"] == "account" and r["data"].get("department") in departments
    }


def month_open(rows: list[Item]) -> Item | None:
    """The month's persisted emperor projection, not execution state."""
    calendar = next((r for r in rows if r["kind"] == "calendar"), None)
    if calendar is None:
        return None
    return next(
        (
            e["detail"]
            for e in reversed(calendar["events"])
            if e["kind"] == "month_open" and e["detail"]["date"] == calendar["data"]
        ),
        None,
    )


def entities(
    ledger: Ledger, identity: Identity, replay: bool = False
) -> list[EntityView]:
    rows = ledger.entities(replay)
    if identity == "emperor" and (opening := month_open(rows)):
        return [EntityView.model_validate(e) for e in opening["entities"]]
    accounts = owned_accounts(rows, identity)
    result: list[EntityView] = []
    for row in rows:
        if identity not in ("audit", "world"):
            if row["id"] in accounts:
                pass
            elif row["kind"] == "person":
                row["data"] = {
                    k: v
                    for k, v in row["data"].items()
                    if k in {"name", "office", "location", "status"}
                }
            elif row["kind"] == "night" and identity == "emperor":
                row["data"] = read_night(ledger, row["id"]).model_dump(mode="json")
            elif row["kind"] == "decree" and identity == "emperor":
                row["data"] = {
                    k: v
                    for k, v in row["data"].items()
                    if k in {"text", "origin", "people", "night_id"}
                }
            elif row["kind"] not in {"gazette", "calendar"}:
                continue
        result.append(EntityView.model_validate(row))
    return result


def project(ledger: Ledger, identity: Identity, replay: bool = False) -> list[FactView]:
    rows = ledger.entities(replay)
    opening = month_open(rows) if identity == "emperor" else None
    date = next(r["data"] for r in rows if r["kind"] == "calendar")
    controls = {"interaction", "petition", "choice", "gazette"}
    accounts = owned_accounts(rows, identity)
    result: list[FactView] = (
        [
            FactView.model_validate(f)
            for f in opening["facts"]
            if f["kind"] not in controls
        ]
        if opening
        else []
    )
    for row in rows:
        for item in row["events"]:
            fact = FactView(entity_id=row["id"], **item)
            available = fact.detail.get("available", date)
            if (
                (opening and fact.kind not in controls)
                or (identity == "world" and fact.kind == "forecast")
                or (
                    identity != "audit"
                    and fact.kind == "petition"
                    and (available["year"], available["month"])
                    > (date["year"], date["month"])
                )
            ):
                continue
            if identity == "world" and fact.kind == "simulation":
                fact.detail = {k: v for k, v in fact.detail.items() if k != "messages"}
            if identity not in ("audit", "world"):
                if (
                    fact.kind == "gazette"
                    or fact.detail.get("audience") == "public"
                    or (
                        (identity == "public" or isinstance(identity, Officials))
                        and fact.detail.get("audience") == "official"
                    )
                ):
                    fact.detail = {"text": fact.detail["text"]}
                elif fact.kind == "interaction" and identity == "emperor":
                    pass
                elif fact.kind in {"petition", "choice"}:
                    pass
                elif fact.kind == "unhandled" and identity == "emperor":
                    fact.detail = {}
                elif (
                    isinstance(identity, Officials)
                    and (
                        row["id"] in accounts
                        or (
                            row["kind"] == "decree"
                            and set(identity.people).intersection(
                                row["data"].get("people", [])
                            )
                        )
                    )
                    and fact.kind in {"changed", "received", "decreed"}
                ):
                    fact.detail = {"text": fact.detail.get("text", "")}
                else:
                    continue
                fact.emperor_words = ""
            result.append(fact)
    return result
