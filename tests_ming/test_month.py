"""Medium (SQLite): month actions through the package's user/read boundaries."""

import asyncio
import sqlite3
from pathlib import Path

from eventsourcing.persistence import IntegrityError

import pytest

from pydantic_ai.models.test import TestModel

from ming.middle.court import Court
from ming.middle.view import Officials
from ming.month import Month
from tests_ming.test_court import replaying


def test_month_without_decrees_advances_and_replays_after_reopening(
    tmp_path: Path,
) -> None:
    # Real model responses and input provenance: recorded/month_README.md.
    reply = (Path(__file__).parent / "recorded/month_empty.txt").read_text()
    court = Court.new_game(tmp_path, replaying([reply]))
    month = Month(court, TestModel(custom_output_text="本月诸务平稳，未有新事。"))
    asyncio.run(month.advance())
    calendar = next(e for e in court.entities("audit") if e.kind == "calendar")
    assert (calendar.data["year"], calendar.data["month"]) == (1627, 11)
    assert [f.kind for f in court.facts("emperor")] == ["gazette"]
    path = court.db_path
    court.close()
    court = Court(path, replaying([reply, reply]))
    assert court.entities("audit") == court.entities("audit", replay=True)
    assert court.facts("audit") == court.facts("audit", replay=True)
    asyncio.run(
        Month(court, TestModel(custom_output_text="本月诸务平稳，未有新事。")).advance()
    )
    calendar = next(e for e in court.entities("audit") if e.kind == "calendar")
    assert (calendar.data["year"], calendar.data["month"]) == (1627, 12)
    asyncio.run(
        Month(court, TestModel(custom_output_text="本月诸务平稳，未有新事。")).advance()
    )
    assert (court.calendar().data["year"], court.calendar().data["month"]) == (1628, 1)
    court.close()


@pytest.mark.parametrize(
    ("nominal", "actual", "interrupt"),
    [
        (300000, 300000, False),
        (3200000, 3200000, False),
        (5000000, 3200000, False),
        (5000000, 3200000, True),
    ],
)
def test_month_lands_both_sides_at_source_stock_and_preserves_nominal(
    tmp_path: Path, nominal: int, actual: int, interrupt: bool
) -> None:
    reply = (Path(__file__).parent / f"recorded/month_money_{nominal}.txt").read_text()
    court = Court.new_game(tmp_path, replaying([reply, reply]))
    if interrupt:
        with sqlite3.connect(court.db_path) as connection:
            connection.execute(
                "CREATE TRIGGER interrupt BEFORE UPDATE ON entities WHEN NEW.key='内库' BEGIN SELECT RAISE(ABORT, 'injected'); END"
            )
        with pytest.raises(IntegrityError):
            asyncio.run(
                Month(
                    court, TestModel(custom_output_text="议准拨银，已经交割。")
                ).advance()
            )
        assert {
            e.key: e.data["taels"]
            for e in court.entities("audit")
            if e.kind == "account"
        } == {
            "国库": 3200000,
            "内库": 4400000,
        }
        assert not [f for f in court.facts("audit") if f.kind in {"changed", "landed"}]
        path = court.db_path
        court.close()
        with sqlite3.connect(path) as connection:
            connection.execute("DROP TRIGGER interrupt")
        court = Court(path, replaying([]))
    asyncio.run(
        Month(court, TestModel(custom_output_text="议准拨银，已经交割。")).advance()
    )
    accounts = {
        e.key: e.data["taels"] for e in court.entities("audit") if e.kind == "account"
    }
    assert accounts == {"国库": 3200000 - actual, "内库": 4400000 + actual}
    assert {
        e.key
        for e in court.entities(Officials(people=["杨嗣昌"]))
        if e.kind == "account"
    } == {"国库"}
    assert {
        e.key
        for e in court.entities(Officials(people=["王承恩"]))
        if e.kind == "account"
    } == {"内库"}
    assert not [e for e in court.entities("public") if e.kind == "account"]
    assert all(
        "nominal" not in f.detail and "actual" not in f.detail
        for f in court.facts("public")
    )
    if nominal == 5000000:
        reports = [f for f in court.facts("public") if f.kind == "changed"]
        assert reports
        assert all(set(f.detail) == {"text"} for f in reports)
        assert all(
            f.entity_id
            == next(e.id for e in court.entities("audit") if e.key == "国库")
            for f in reports
        )
    transfers = [
        f.detail
        for f in court.facts("audit")
        if f.kind == "changed" and "taels" in f.detail["nominal"]
    ]
    assert [(t["nominal"]["taels"], t["actual"]["taels"]) for t in transfers] == [
        (-nominal, -actual),
        (nominal, actual),
    ]
    assert court.entities("audit") == court.entities("audit", replay=True)
    assert court.facts("audit") == court.facts("audit", replay=True)
    court.close()


def test_petition_waits_for_choice_then_takes_effect_this_month(tmp_path: Path) -> None:
    recorded = Path(__file__).parent / "recorded"
    court = Court.new_game(
        tmp_path,
        replaying(
            [
                (recorded / "month_petition.txt").read_text(),
                (recorded / "month_money_300000.txt").read_text(),
            ]
        ),
    )
    month = Month(court, TestModel(custom_output_text="陕西待赈，请旨。"))
    pending = asyncio.run(month.advance())
    assert len(pending) == 1
    assert court.calendar().data["month"] == 10
    assert not [f for f in court.facts("audit") if f.kind == "landed"]
    assert [f.kind for f in court.facts("emperor")] == ["petition"]
    with pytest.raises(ValueError):
        asyncio.run(month.choose(pending[0].id, 5))
    asyncio.run(month.choose(pending[0].id, 0))
    assert asyncio.run(month.advance()) == []
    assert court.calendar().data["month"] == 11
    assert {
        e.key: e.data["taels"] for e in court.entities("audit") if e.kind == "account"
    } == {
        "国库": 2900000,
        "内库": 4700000,
    }
    with pytest.raises(ValueError):
        asyncio.run(month.choose(pending[0].id, 0))
    court.close()


def test_exhausted_month_declaration_is_unhandled_not_a_stopped_month(
    tmp_path: Path,
) -> None:
    reply = (Path(__file__).parent / "recorded/month_invalid.txt").read_text()
    court = Court.new_game(tmp_path, replaying([reply, reply]))
    assert (
        asyncio.run(
            Month(court, TestModel(custom_output_text="陕西待赈，请旨。")).advance()
        )
        == []
    )
    assert court.calendar().data["month"] == 11
    assert {f.kind for f in court.facts("emperor")} == {"unhandled", "gazette"}
    assert all(not f.detail for f in court.facts("emperor") if f.kind == "unhandled")
    assert {
        e.key: e.data["taels"] for e in court.entities("audit") if e.kind == "account"
    } == {
        "国库": 3200000,
        "内库": 4400000,
    }
    court.close()
