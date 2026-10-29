"""Persistent audience records, owned by the same entity/event ledger."""

from collections import defaultdict
from collections.abc import Sequence
from operator import itemgetter
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy import JSON, CompoundSelect, FromClause, Select, case, func, literal, or_, select, true, union_all
from sqlalchemy.sql.elements import BindParameter, ColumnElement

from ming.ledger import ENTITY_COLUMNS as E, FACT_COLUMNS as F, FACT_ROWS, Entity, Item, Ledger
from ming.middle.calendar import calendar_row
from ming.middle.queries import LATEST_NIGHT, NIGHT_RESULT

INITIAL_HALL = ("王承恩",)
# Resolve the referenced-night domain in the permission query itself, rather
# than issuing a separate query before every identity read.
DECREE = E.id.table.alias("history_decree").c
DECREE_HISTORY = select(
    F.position, F.entity_id, F.kind, case((F.kind == "hall", F.detail)).label("detail"),
).where(F.entity_id.in_(select(func.replace(DECREE.data["night_id"].as_string(), "-", ""))
                       .where(DECREE.kind == "decree").correlate(None)),
        F.kind.in_(("hall", "turn"))).cte()


class TurnView(BaseModel):
    id: str
    emperor_words: str
    scene: str
    hall: tuple[str, ...]


class NightView(BaseModel):
    id: UUID
    closed: bool
    hall: tuple[str, ...]
    date: dict[str, int]
    turns: tuple[TurnView, ...] = ()
    result: Literal["translated", "unhandled"] | None = None


def change_hall(hall: list[str], add: list[str], remove: list[str]) -> list[str]:
    return list(dict.fromkeys(p for p in hall + add if p not in remove))


def hall_history(
    night_id: ColumnElement[Any], turn_position: ColumnElement[Any],
    facts: FromClause = F.position.table,
) -> Select[Any]:
    """Members when this turn's words were spoken, with first surviving entries."""
    # Scene changes precede their turn record; speech uses the preceding turn's state.
    previous = facts.alias().c
    boundary = select(func.max(previous.position)).where(
        previous.entity_id == night_id, previous.kind == "turn", previous.position < turn_position,
    ).correlate_except(previous.position.table).scalar_subquery()
    hall = facts.alias().c
    added = func.json_each(hall.detail["add"]).table_valued("key", "value")
    candidates = union_all(
        *(select(literal(person).label("person"), literal(0).label("position"), literal(index).label("ordinal"))
          for index, person in enumerate(INITIAL_HALL)),
        select(added.c.value.label("person"), hall.position, added.c.key.label("ordinal")).select_from(
            hall.position.table.join(added, true()),
        ).where(hall.entity_id == night_id, hall.kind == "hall", hall.position <= boundary)
        .correlate_except(hall.position.table, added),
    ).subquery()
    removed = func.json_each(hall.detail["remove"]).table_valued("value")
    absent = select(hall.position).where(
        hall.entity_id == night_id, hall.kind == "hall",
        hall.position >= candidates.c.position, hall.position <= boundary,
        select(removed.c.value).where(removed.c.value == candidates.c.person).correlate_except(removed).exists(),
    ).correlate_except(hall.position.table)
    ranked = select(
        candidates.c.person, candidates.c.position, candidates.c.ordinal,
        func.row_number().over(
            partition_by=candidates.c.person, order_by=(candidates.c.position, candidates.c.ordinal),
        ).label("entry"),
    ).where(
        or_(candidates.c.position == 0, candidates.c.position <= boundary), ~absent.exists(),
    ).correlate_except(candidates).subquery()
    return select(ranked.c.person, ranked.c.position, ranked.c.ordinal).where(ranked.c.entry == 1).correlate_except(ranked)


TURN_MEMBERS = hall_history(F.entity_id, F.position).subquery()
TURN_HALL = select(func.json_group_array(func.json_object(
    "person", TURN_MEMBERS.c.person, "position", TURN_MEMBERS.c.position, "ordinal", TURN_MEMBERS.c.ordinal,
), type_=JSON)).scalar_subquery()
TURN_ROWS = FACT_ROWS.add_columns(TURN_HALL.label("hall"))


def read_nights(ledger: Ledger, nights: Sequence[Item]) -> tuple[NightView, ...]:
    if not nights:
        return ()
    ids = [night["id"] for night in nights]
    turns: dict[UUID, list[TurnView]] = defaultdict(list)
    for item in ledger.facts(entity_id=ids, kind="turn", query=TURN_ROWS):
        turns[item["entity_id"]].append(TurnView(
            **item["detail"], emperor_words=item["emperor_words"],
            hall=tuple(member["person"] for member in sorted(item["hall"], key=itemgetter("position", "ordinal"))),
        ))
    results = {row["id"]: row["result"] for row in ledger.read(
        select(E.id, NIGHT_RESULT.label("result")).where(E.id.in_(ids)),
    )}
    return tuple(NightView(id=night["id"], **night["data"], turns=tuple(turns[night["id"]]), result=results[night["id"]])
                 for night in nights)


def witnessed_nights(people: list[str] | BindParameter[str], query: Select[Any]) -> Select[Any]:
    added = func.json_each(F.detail["add"]).table_valued("value")
    removed = func.json_each(F.detail["remove"]).table_valued("value")
    return query.where(E.kind == "night", or_(
        or_(*(literal(person).in_(people) for person in INITIAL_HALL)),
        select(F.position).where(
            F.entity_id == E.id, F.kind == "hall",
            select(added.c.value).where(
                added.c.value.in_(people),
                ~select(removed.c.value).where(removed.c.value == added.c.value).exists(),
            ).exists(),
        ).correlate(E.id.table).exists(),
    ))


def known_people(
    data: ColumnElement[Any],
    people: list[str] | BindParameter[str] | None = None,
) -> CompoundSelect[Any]:
    """Involved people, the handler, and the hall at the approval turn."""
    night_id = func.replace(data["night_id"].as_string(), "-", "")
    turn = DECREE_HISTORY.alias().c
    turns = select(turn.position, func.row_number().over(order_by=turn.position).label("number")).where(
        turn.entity_id == night_id, turn.kind == "turn",
    ).correlate_except(turn.position.table).subquery()
    turn_position = select(turns.c.position).where(
        turns.c.number == data["turn"].as_integer(),
    ).correlate_except(turns).scalar_subquery()
    attendees = hall_history(night_id, turn_position, DECREE_HISTORY)
    attendees = attendees.with_only_columns(attendees.selected_columns.person)
    assigned = func.json_each(func.json_insert(
        data["people"], "$[#]", data["handler"].as_string(),
    )).table_valued("value")
    declared = select(assigned.c.value.label("person")).correlate_except(assigned)
    if people is not None:
        declared = declared.where(assigned.c.value.in_(people))
        attendees = attendees.where(attendees.selected_columns.person.in_(people))
    return declared.union(attendees)


def open_night(ledger: Ledger) -> tuple[UUID, bool]:
    for row in ledger.entities(query=LATEST_NIGHT):
        if not row["data"]["closed"]:
            return row["id"], False
    date = calendar_row(ledger)["data"]
    night = Entity(
        "night", str(uuid4()), "", {"closed": False, "hall": list(INITIAL_HALL), "date": {k: date[k] for k in ("year", "month")}}
    )
    ledger.commit([night])
    return night.id, True


def dismiss(ledger: Ledger, night_id: UUID) -> None:
    night = ledger.get(night_id)
    if not night.data["closed"]:
        night.record("dismissed", "", {}, {"closed": True})
        ledger.commit([night])
