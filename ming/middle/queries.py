"""Domain read predicates, expressed once with SQLAlchemy's query vocabulary.

Ledger executes selections; it has no night, inbox, identity or workflow modes.
"""

from typing import Any
from sqlalchemy import JSON, Select, and_, func, or_, select, true, tuple_, type_coerce
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.functions import Function
from ming.ledger import (
    Item,
    ENTITY_COLUMNS as E,
    ENTITY_ORDER,
    FACT_COLUMNS as F,
    ENTITY_ROWS,
    FACT_ROWS,
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

IN_OFFICE = and_(
    or_(
        E.data["status"].as_string().is_(None),
        E.data["status"].as_string() == "active",
    ),
    E.data["office"].as_string() != "",
)


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
        <= (date["year"], date["month"]),
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


def due_decrees(date: Item) -> Select[Any]:
    decision = type_coerce(
        select(F.detail)
        .where(F.entity_id == E.id, F.kind == "choice")
        .order_by(F.position.desc())
        .limit(1)
        .correlate(E.id.table)
        .scalar_subquery(),
        JSON,
    )
    return ENTITY_ROWS.where(
        E.kind == "decree",
        ~select(F.position)
        .where(F.entity_id == E.id, F.kind.in_(("landed", "unhandled")))
        .exists(),
        or_(
            decision.is_(None),
            and_(
                decision["text"].as_string() != "收回",
                ~and_(
                    decision["text"].as_string() == "留中",
                    decision["date"]["year"].as_integer() == date["year"],
                    decision["date"]["month"].as_integer() == date["month"],
                ),
            ),
        ),
    )
