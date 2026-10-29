"""Identity-specific structured read boundary; no summaries of model prose."""

from collections.abc import Iterable, Sequence
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Select, bindparam, case, func, literal, or_, select
from sqlalchemy.sql.elements import BindParameter, ColumnElement

from ming.ledger import Item, Ledger
from ming.ledger import ENTITY_COLUMNS as E, FACT_COLUMNS as F, ENTITY_ROWS, FACT_ROWS, ENTITY_ORDER, facts_in_month
from ming.middle.queries import CALENDAR, available_on, public_decree
from ming.middle.calendar import calendar_row
from ming.middle.appointments import APPOINTMENT_ROLES, CATALOGUE_KINDS, held_by
from ming.middle.night import known_people, read_nights, witnessed_nights
from ming.middle.travel import travel_days

OPENING_CONTROLS = {"interaction", "petition", "choice", "gazette", "secret_report"}
EMPTY_ACCOUNTS = select(E.id).where(literal(False)).correlate(None)
READ_PEOPLE: BindParameter[str] = bindparam("read_people", expanding=True)
APPOINTED_PEOPLE: BindParameter[str] = bindparam("appointed_people", expanding=True)
HELD_BY = held_by(APPOINTED_PEOPLE)
EXCLUDE_SECRETS: BindParameter[bool] = bindparam("exclude_secrets", False)
READ_KIND: BindParameter[str] = bindparam("read_kind")
MONTH_OPEN_QUERY = FACT_ROWS.with_only_columns(F.position).where(
    E.kind == "calendar", F.kind == "month_open",
).order_by(None).order_by(F.position.desc()).limit(1).correlate(None)

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
    if isinstance(value, (list, tuple)):
        return [character_input(item) for item in cast(list[Any], value)]
    if not isinstance(value, dict):
        return value
    result = {
        key: character_input(item)
        for key, item in cast(Item, value).items()
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


def view_parameters(identity: Identity, kind: str | None = None) -> Item:
    return {
        "read_people": identity.people if isinstance(identity, Officials) else [],
        "exclude_secrets": identity.exclude_secrets if isinstance(identity, Officials) else False,
        "read_kind": kind,
    }


def identity_key(identity: Identity) -> str:
    return "official" if isinstance(identity, Officials) else identity


def month_open(date: Item) -> ColumnElement[int]:
    """One opening cutoff expression, with the current calendar bound explicitly."""
    return MONTH_OPEN_QUERY.where(facts_in_month(date)).scalar_subquery()


def decree_access(identity: Identity, reference: ColumnElement[Any]) -> dict[str, ColumnElement[bool]]:
    """Correlated permission predicates, never an eager collection of decrees."""
    decree = E.id.table.alias().c
    query = select(decree.id).where(
        decree.kind == "decree", decree.id == func.replace(reference, "-", ""),
    ).correlate(E.id.table, F.position.table)
    known = public_decree(decree)
    handled = literal(identity == "emperor")
    if isinstance(identity, Officials):
        people = func.json_each(decree.data["people"]).table_valued("value")
        handled = case(
            (decree.data["secret"].as_boolean(), decree.data["handler"].as_string().in_(READ_PEOPLE)),
            else_=select(people.c.value).where(people.c.value.in_(READ_PEOPLE)).exists(),
        )
        known = or_(known, known_people(decree.data, READ_PEOPLE).exists())
        allowed = ~EXCLUDE_SECRETS | decree.data["secret"].as_boolean().is_(False)
        known = known & allowed
        handled = handled & allowed
    return {
        "known": query.where(literal(True) if identity == "emperor" else known).exists(),
        "handled": query.where(handled).exists(),
        "secret": query.where(decree.data["secret"].as_boolean().is_(True)).exists(),
    }


def visible_appointments(ledger: Ledger, identity: Identity, rows: Sequence[Item]) -> Sequence[Item]:
    """Both office queries and person projections use the same appointment access."""
    if identity in ("audit", "world"):
        return rows
    if not rows:
        return []
    visible = {row["id"] for row in ledger.read(
        select(E.id).where(E.id.in_([r["id"] for r in rows]), APPOINTMENT_ACCESS[identity_key(identity)]),
        view_parameters(identity),
    )}
    return [r for r in rows if r["id"] in visible]


def person_projection(dossiers: Item, row: Item, identity: Identity, appointments: Iterable[Item]) -> Item:
    """One current-office and character-material projection for UI and every model."""
    data = dict(row["data"])
    if identity == "audit":
        return data
    if isinstance(identity, Officials) and row["key"] in identity.people:
        data.setdefault("seed_guilt", None)
        data["dossier"] = dossiers.get(row["key"], {})
        data = character_input(data)
    elif identity != "world":
        data = {k: v for k, v in data.items() if k in {
            "name", "location", "status", "identity_description", "transit_to", "waiting_audience",
            "departure_date", "arrival_date", "travel_speed",
        }}
    data.pop("historical_office", None)
    data["appointments"] = [{**r["data"], "role": role}
                            for r in appointments for role in APPOINTMENT_ROLES
                            if row["key"] in r["data"][role]]
    if data["appointments"]:
        data.pop("identity_description", None)
    return data


def entities(
    ledger: Ledger, identity: Identity, selection: Item | None = None,
    *, cutoff: ColumnElement[int] | None = None,
) -> tuple[EntityView, ...]:
    selection = dict(selection or {})
    keys = selection.pop("keys", None)
    if identity == "emperor" and (opening := next(iter(ledger.read(FACT_ROWS.where(
        F.position == (month_open(calendar_row(ledger)["data"]) if cutoff is None else cutoff),
    ))), None)):
        return tuple(
            EntityView.model_validate(e)
            for e in opening["detail"]["entities"]
            if all(e[k] == v for k, v in (selection or {}).items()) and (keys is None or e["key"] in keys)
        )
    query = ENTITY_SOURCES[identity_key(identity)]
    query = query.where(E.kind == selection["kind"]) if selection.get("kind") is not None else query
    query = query.where(E.key == selection["key"]) if selection.get("key") is not None else query
    query = query.where(E.key.in_(keys)) if keys is not None else query
    parameters = view_parameters(identity, selection.get("kind"))
    rows = ledger.read(query, parameters)
    people = [row["key"] for row in rows if row["kind"] == "person" and identity != "audit"]
    appointments = {row["id"]: row for row in rows if row["kind"] == "incumbency"} if people else {}
    if people and (selection or keys is not None):
        # Keep database order for partial selections without returning bodies already acquired.
        appointments = {row["id"]: appointments[row["id"]] if row["data"] is None else row for row in ledger.entities(
            kind="incumbency", query=ENTITY_ROWS.with_only_columns(
                E.id, case((E.id.in_(appointments), None), else_=E.data).label("data"),
            ).where(HELD_BY, APPOINTMENT_ACCESS[identity_key(identity)]),
            parameters={**parameters, "appointed_people": people},
        )}
    own: set[str] = set(identity.people) if isinstance(identity, Officials) else set()
    dossiers = {r["key"]: r["data"] for r in ledger.entities(
        kind="dossier", query=ENTITY_ROWS.where(E.key.in_(own.intersection(people))),
    )} if own.intersection(people) else {}
    factions: set[Any] = set()
    if any(row["exposure"] == "faction" for row in rows):
        factions.update(row["data"].get("faction") for row in rows if row["kind"] == "person" and row["key"] in own)
        own.difference_update(row["key"] for row in rows if row["kind"] == "person")
        if own:
            factions.update(r["faction"] for r in ledger.entities(
                kind="person", query=ENTITY_ROWS.with_only_columns(E.data["faction"].as_string().label("faction")).where(E.key.in_(own)),
            ))
    nights = {night.id: night.model_dump(mode="json") for night in read_nights(
        ledger, [row for row in rows if row["exposure"] == "night"],
    )}
    result: list[EntityView] = []
    for row in map(dict, rows):
        if row["kind"] == "person":
            row["data"] = person_projection(dossiers, row, identity, appointments.values())
        row["data"] = ({destination: travel_days(distance) for destination, distance in row["data"].items()}
                       if row["kind"] == "distance" and identity != "audit" else row["data"])
        if identity not in ("audit", "world"):
            if row["exposure"] == "faction":
                if row["key"] not in factions:
                    row["data"] = {"name": row["key"]}
            elif row["exposure"] == "account_name":
                row["data"] = {"name": row["key"]}
            elif row["exposure"] == "night":
                row["data"] = nights[row["id"]]
            elif row["exposure"] == "decree":
                row["data"] = {
                    k: v
                    for k, v in row["data"].items()
                    if k in {"text", "origin", "people", "night_id", "secret", "turn", "endorsements", "interim"}
                }
        result.append(EntityView.model_validate(row))
    return tuple(result)


def appointment_access(identity: Identity) -> ColumnElement[bool]:
    if identity in ("audit", "world"):
        return literal(True)
    exposure = fact_exposure(identity, EMPTY_ACCOUNTS)
    newer = F.position.table.alias().c
    return ~or_(*(select(F.position).where(
        F.entity_id == E.id, F.kind == "changed",
        F.detail["changes"][field].as_string().is_not(None), exposure.is_(None),
        ~select(newer.position).where(
            newer.entity_id == F.entity_id, newer.kind == "changed",
            newer.detail["changes"][field].as_string().is_not(None), newer.position > F.position,
        ).correlate(F.position.table).exists(),
    ).correlate(E.id.table).exists() for field in APPOINTMENT_ROLES))


def owned_accounts(identity: Identity) -> Select[Any]:
    if not isinstance(identity, Officials):
        return EMPTY_ACCOUNTS
    offices = select(E.data["office"].as_string()).where(
        E.kind == "incumbency", APPOINTMENT_ACCESS["official"],
        held_by(READ_PEOPLE),
    ).correlate(None)
    departments = select(E.data["department"].as_string()).where(
        E.kind == "office", E.key.in_(offices),
    ).correlate(None)
    factions = select(E.data["faction"].as_string()).where(
        E.kind == "person", E.key.in_(READ_PEOPLE),
    ).correlate(None)
    readers = func.json_each(E.data["known_to"]).table_valued("value")
    return select(E.id).where(E.kind == "account", or_(
        E.data["department"].as_string().in_(departments),
        select(readers.c.value).where(or_(
            readers.c.value.in_(READ_PEOPLE), readers.c.value.in_(factions),
        )).exists(),
    )).correlate(None)


def entity_exposure(
    identity: Identity, accounts: Select[Any],
) -> ColumnElement[str]:
    if identity == "audit":
        return literal("full")
    if identity == "world":
        return case((READ_KIND.is_not(None) | E.kind.not_in(CATALOGUE_KINDS), "full"))
    rules = [
        (E.id.in_(accounts), "full"),
        (E.kind == "person", "person"),
        (E.kind.in_(("gazette", "calendar")), "full"),
        (decree_access(identity, E.id)["known"], "decree"),
    ]
    rules.append((READ_KIND.in_(CATALOGUE_KINDS) & E.kind.in_(CATALOGUE_KINDS), "full"))
    rules.insert(0, ((E.kind == "incumbency") & APPOINTMENT_ACCESS[identity_key(identity)], "full"))
    if isinstance(identity, Officials):
        rules.append((WITNESSED_NIGHT, "night"))
        rules.append((E.kind == "account", "account_name"))
        rules.append((E.kind == "faction", "faction"))
    if identity == "emperor":
        rules.append((E.kind == "night", "night"))
    return case(*rules)


def fact_exposure(
    identity: Identity, accounts: Select[Any]
) -> ColumnElement[str]:
    if identity == "audit":
        return literal("full")
    if identity == "world":
        return case((F.kind != "forecast", "full"))
    access = decree_access(identity, E.id)
    origin = decree_access(identity, F.detail["origin_ref"].as_string())
    endorsement = decree_access(identity, F.detail["decree_id"].as_string())
    audiences = (
        ("public", "official")
        if isinstance(identity, Officials)
        else ("public",)
    )
    # A person reads his whole own history (scene dossier) before any audience
    # rule; person-side decree links surface through the decree entity instead.
    rules: list[tuple[ColumnElement[bool], str]] = (
        [
            (
                (E.kind == "person")
                & E.key.in_(READ_PEOPLE)
                & (F.kind != "decreed"),
                "dated",
            )
        ]
        if isinstance(identity, Officials)
        else []
    )
    if identity == "emperor":
        rules.append((F.kind == "gazette", "dated"))
    rules.append(
        (
            or_(F.kind == "gazette", F.detail["audience"].as_string().in_(audiences)),
            "text",
        )
    )
    rules.extend(
        [
            (access["known"] & (F.kind == "decreed"), "dated"),
            (access["handled"] & (F.kind == "secret_report"), "dated"),
            (endorsement["known"] & (F.kind == "endorsed"), "dated"),
            (
                (E.kind == "person")
                & F.kind.in_(
                    (
                        "changed",
                        "appointed",
                        "displaced",
                        "departed",
                        "arrived",
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
    return case(
        (origin["secret"] & ~origin["handled"] & F.detail["discovered"].as_boolean().is_(True), None),
        (or_(E.kind == "incumbency", F.kind.in_(("appointed", "displaced")))
         & origin["secret"] & ~origin["known"], None),
        ((E.kind == "incumbency") & F.kind.in_(("changed", "appointed", "displaced")), "dated"),
        else_=case(*rules),
    )


def fact_sources(
    ledger: Ledger, identity: Identity, *, cutoff: ColumnElement[int] | None = None,
) -> Select[Any]:
    """One query for live controls and immutable facts at the opening cutoff."""
    exposure = FACT_EXPOSURE[identity_key(identity)]
    query = FACT_ROWS.add_columns(exposure.label("exposure")).where(exposure.is_not(None))
    if identity != "audit":
        query = query.where(AVAILABLE)
    if identity == "emperor":
        live = F.kind.in_(OPENING_CONTROLS)
        opening = month_open(calendar_row(ledger)["data"]) if cutoff is None else cutoff
        query = query.where(or_(opening.is_(None), live, F.position < opening)).order_by(None).order_by(
            case((opening.is_not(None), live), else_=False), ENTITY_ORDER, F.position,
        )
    return query


def project(
    ledger: Ledger, identity: Identity, selection: Item | None = None,
    query: Select[Any] | None = None,
) -> tuple[FactView, ...]:
    selection = selection or {}
    query = fact_sources(ledger, identity) if query is None else query
    result: list[FactView] = []
    for item in ledger.facts(**selection, query=query, parameters=view_parameters(identity)):
        detail = item["detail"]
        if identity not in ("audit", "world"):
            if item["exposure"] in ("text", "dated"):
                detail = {
                    "text": detail.get("text", ""),
                    **{
                        k: v
                        for k, v in detail.items()
                        if item["exposure"] == "dated"
                        and k in (
                            {"date", "office", "territory", "holders", "acting", "role"}
                            | ({"decree_id", "endorser", "form"} if item["kind"] == "endorsed" else set())
                        )
                    },
                }
            elif item["exposure"] == "empty":
                detail = {}
        result.append(FactView.model_validate({**item, "detail": detail,
                                              "emperor_words": item["emperor_words"] if identity in ("audit", "world") else ""}))
    return tuple(result)


# Construct permission expressions once. Only parameter values vary at execution;
# correlated queries evaluate the current ledger, including same-say hall changes.
IDENTITIES: dict[str, Identity] = {
    key: cast(Identity, key) for key in ("audit", "world", "emperor", "public")
}
IDENTITIES["official"] = Officials(people=[])
APPOINTMENT_ACCESS = {key: appointment_access(identity) for key, identity in IDENTITIES.items()}
WITNESSED_NIGHT = E.id.in_(witnessed_nights(READ_PEOPLE, select(E.id)).correlate(None))
ACCOUNTS = {key: owned_accounts(identity) for key, identity in IDENTITIES.items()}
ENTITY_EXPOSURE = {key: entity_exposure(identity, ACCOUNTS[key]) for key, identity in IDENTITIES.items()}
ENTITY_SOURCES = {key: ENTITY_ROWS.add_columns(exposure.label("exposure")).where(exposure.is_not(None))
                  for key, exposure in ENTITY_EXPOSURE.items()}
FACT_EXPOSURE = {key: fact_exposure(identity, ACCOUNTS[key]) for key, identity in IDENTITIES.items()}
AVAILABLE = or_(CALENDAR.is_(None), available_on({
    "year": CALENDAR["year"].as_integer(), "month": CALENDAR["month"].as_integer(),
}))
