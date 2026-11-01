"""Domain read predicates, expressed once with SQLAlchemy's query vocabulary.

Ledger executes selections; it has no night, inbox, identity or workflow modes.
"""

from typing import Any
from sqlalchemy import JSON, Select, and_, case, false, func, or_, select, true, tuple_, type_coerce
from sqlalchemy.sql.base import ReadOnlyColumnCollection
from sqlalchemy.sql.elements import ColumnElement, KeyedColumnElement
from ming.ledger import (
    Item,
    ENTITY_COLUMNS as E,
    ENTITY_ORDER,
    FACT_COLUMNS as F,
    ENTITY_ROWS,
    FACT_ROWS,
    facts_in_month,
)
from ming.middle.appointments import APPOINTMENT_ROLES

CALENDAR = select(E.data).where(E.kind == "calendar").correlate(None).scalar_subquery()

NIGHT_RESULT = (
    select(F.kind)
    .where(F.entity_id == E.id, F.kind.in_(("translated", "unhandled")))
    .order_by(F.position.desc())
    .limit(1)
    .correlate(E.id.table)
    .scalar_subquery()
)
NIGHT_ROWS = ENTITY_ROWS.where(E.kind == "night")
LATEST_NIGHT = NIGHT_ROWS.order_by(None).order_by(ENTITY_ORDER.desc()).limit(1)
# Translation's names and fields: imported kinds plus those landing creates.
CATALOGUE = ENTITY_ROWS.where(
    or_(
        E.kind.in_(select(E.kind).where(E.source != "").distinct()),
        E.kind.in_(("affair", "decree")),
    )
)

APPOINTMENT = E.id.table.alias("appointment").c
CURRENT_APPOINTMENT = select(APPOINTMENT.id).where(
    APPOINTMENT.kind == "incumbency",
    or_(*(select(members.c.value).where(members.c.value == E.key)
          .correlate(E.id.table, APPOINTMENT.id.table).exists()
          for role in APPOINTMENT_ROLES
          for members in [func.json_each(APPOINTMENT.data[role]).table_valued("value")])),
).correlate(E.id.table)
IN_OFFICE = CURRENT_APPOINTMENT.exists()


def available_on(date: Item) -> ColumnElement[bool]:
    """Identity visibility follows each petition's recorded availability."""
    if not date:
        return true()
    return or_(
        F.kind != "petition",
        tuple_(
            func.coalesce(F.detail["available"]["year"].as_integer(), date["year"]),
            func.coalesce(F.detail["available"]["month"].as_integer(), date["month"]),
        )
        <= tuple_(date["year"], date["month"]),
    )


def matching_details(column: ColumnElement[Any], detail: Item) -> tuple[ColumnElement[bool], ...]:
    return tuple(column[field].as_string().in_(values if isinstance(values, list) else [values])
                 for field, values in detail.items())


def unmatched(kind: str, response: str, link: tuple[str, str]) -> ColumnElement[bool]:
    answer = F.position.table.alias("answer").c
    return and_(F.kind == kind, F.detail[link[0]].as_string().is_not(None), ~select(answer.position).where(
        answer.kind == response,
        answer.detail[link[1]].as_string() == F.detail[link[0]].as_string(),
    ).exists())


def returned_petitions(date: Item | None = None) -> Select[Any]:
    choice = F.position.table.alias().c
    revision = F.position.table.alias().c
    return FACT_ROWS.where(
        F.kind == "petition",
        F.detail["source"].as_string() == "urgent",
        select(choice.position)
        .where(
            choice.kind == "choice",
            choice.detail["petition_id"].as_string() == F.detail["id"].as_string(),
            choice.detail["disposition"].as_string() == "returned",
            *([choice.date != date] if date is not None else []),
        )
        .exists(),
        ~select(revision.position)
        .where(
            revision.kind == "petition",
            revision.detail["revision_of"].as_string() == F.detail["id"].as_string(),
        )
        .exists(),
    )


def interactions(date: Item) -> Select[Any]:
    """Latest acceptance or failure for each key in this month."""
    positions = (
        select(
            F.detail["key"].as_string().label("key"),
            func.min(F.position).label("first"),
            func.max(F.position).label("last"),
        )
        .where(F.kind == "interaction", facts_in_month(date))
        .group_by(F.detail["key"].as_string())
        .subquery()
    )
    return (
        FACT_ROWS.join(positions, F.position == positions.c.last)
        .order_by(None)
        .order_by(positions.c.first)
    )


def decrees_with(kind: str, date: Item | ColumnElement[Any]) -> Select[Any]:
    return ENTITY_ROWS.where(
        E.kind == "decree",
        select(F.position)
        .where(
            F.entity_id == E.id,
            F.kind == kind,
            F.date == date,
        )
        .exists(),
    )


FUNDED_AFFAIRS = ENTITY_ROWS.where(
    E.kind == "affair", E.data["monthly_funding"]["account"].as_string().is_not(None)
)


def without_events(kind: str, data: Item, event: str, date: Item | ColumnElement[Any]) -> Select[Any]:
    query = ENTITY_ROWS.where(E.kind == kind, ~select(F.position).where(
        F.entity_id == E.id, F.kind == event, F.date != date,
    ).exists())
    for field, value in data.items():
        query = query.where(E.data[field].as_string() == value)
    return query


def landing_rows(date: Item | ColumnElement[Any], *, include_history: bool = True) -> Select[Any]:
    """One source set and order for complete materials, landing and reference counts."""
    errand = E.id.in_(without_events("decree", {"secret": True}, "completed", date).with_only_columns(E.id).order_by(None)).label("errand")
    deliberated = E.id.in_(decrees_with("deliberation", date).with_only_columns(E.id).order_by(None)).label("deliberated")
    # History rows only number decree references: public by definition, bodies unread.
    data = type_coerce(case((or_(errand, deliberated), E.data), else_='{"secret": false}'), JSON).label("data")
    return ENTITY_ROWS.with_only_columns(E.id, E.kind, E.key, E.source, data, errand, deliberated).where(or_(
        errand, deliberated, public_decree() if include_history else false(),
    )).order_by(None).order_by(case((errand, 0), (deliberated, 1), else_=2), ENTITY_ORDER)


def public_decree(entity: ReadOnlyColumnCollection[str, KeyedColumnElement[Any]] = E) -> ColumnElement[bool]:
    return and_(
        entity.kind == "decree",
        entity.data["secret"].as_boolean().is_(False),
        select(F.position)
        .where(F.entity_id == entity.id, F.kind == "landed")
        .correlate(entity.id.table)
        .exists(),
    )
