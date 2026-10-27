"""Domain read predicates, expressed once with SQLAlchemy's query vocabulary.

Ledger executes selections; it has no night, inbox, identity or workflow modes.
"""

from typing import Any
from sqlalchemy import Select, and_, func, or_, select, true, tuple_
from sqlalchemy.sql.base import ReadOnlyColumnCollection
from sqlalchemy.sql.elements import ColumnElement, KeyedColumnElement
from sqlalchemy.sql.functions import Function
from ming.ledger import (
    Item,
    ENTITY_COLUMNS as E,
    ENTITY_ORDER,
    FACT_COLUMNS as F,
    ENTITY_ROWS,
    FACT_ROWS,
)
from ming.middle.appointments import APPOINTMENT_ROLES

CALENDAR = select(E.data).where(E.kind == "calendar").correlate(None).scalar_subquery()
CURRENT_FACTS = FACT_ROWS.where(
    F.date["year"].as_integer() == CALENDAR["year"].as_integer(),
    F.date["month"].as_integer() == CALENDAR["month"].as_integer(),
)

NIGHT_RESULT = (
    select(F.kind)
    .where(F.entity_id == E.id, F.kind.in_(("translated", "unhandled")))
    .order_by(F.position.desc())
    .limit(1)
    .correlate(E.id.table)
    .scalar_subquery()
)
NIGHT_ROWS = ENTITY_ROWS.add_columns(NIGHT_RESULT.label("result")).where(
    E.kind == "night"
)
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
    """A petition's availability, shared by identity reads and the inbox."""
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


def pending_petitions(date: Item) -> Select[Any]:
    choice = F.position.table.alias().c
    return (
        FACT_ROWS.where(
            F.kind == "petition",
            available_on(date),
            ~select(choice.position)
            .where(
                choice.kind == "choice",
                choice.detail["petition_id"].as_string() == F.detail["id"].as_string(),
            )
            .exists(),
        )
        .order_by(None)
        .order_by(
            F.detail["available"]["year"].as_integer(),
            F.detail["available"]["month"].as_integer(),
            F.detail["ordinal"].as_integer(),
            F.position,
        )
    )


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
            choice.detail["option"].as_integer()
            == Function("json_array_length", F.detail["options"]) - 1,
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


def interactions() -> Select[Any]:
    """Latest work states in first-key order; audit reads retain completed choices."""
    positions = (
        select(
            F.detail["key"].as_string().label("key"),
            func.min(F.position).label("first"),
            func.max(F.position).label("last"),
        )
        .where(F.kind == "interaction")
        .group_by(F.detail["key"].as_string())
        .subquery()
    )
    return (
        FACT_ROWS.join(positions, F.position == positions.c.last)
        .where(
            or_(
                F.detail["action"].as_string() != "choose",
                F.detail["status"].as_string() != "done",
            )
        )
        .order_by(None)
        .order_by(positions.c.first)
    )


def decrees_with(kind: str, date: Item) -> Select[Any]:
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


SECRET_DECREES = ENTITY_ROWS.where(
    E.kind == "decree", E.data["secret"].as_boolean().is_(True)
)


def errands(date: Item) -> Select[Any]:
    """Secret decrees still in hand: no completion landed before this month."""
    return SECRET_DECREES.where(
        ~select(F.position)
        .where(F.entity_id == E.id, F.kind == "completed", F.date != date)
        .exists()
    )


def public_decree(entity: ReadOnlyColumnCollection[str, KeyedColumnElement[Any]] = E) -> ColumnElement[bool]:
    return and_(
        entity.kind == "decree",
        entity.data["secret"].as_boolean().is_(False),
        select(F.position)
        .where(F.entity_id == entity.id, F.kind == "landed")
        .correlate(entity.id.table)
        .exists(),
    )
