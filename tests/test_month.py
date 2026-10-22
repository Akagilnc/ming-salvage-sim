"""Medium: month products and landing through HTTP, read through the CLI."""

import json
import sqlite3
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel
from sqlalchemy import event, text
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from ming.web import create_app
from tests.test_court import replaying

RECORDED = Path(__file__).parent / "recorded"
# Event log, read rows, and tracking: one landing commit lands all three.
LANDING = (
    "SELECT max(id) FROM ledger_events",
    "SELECT count(*) FROM facts WHERE kind = 'landed'",
    "SELECT max(notification_id) FROM readmodel_tracking",
)


@pytest.mark.parametrize(
    ("first", "extra"),
    [("simulation.txt", 0), ("month_deferred.txt", 0), ("month_zero.txt", 1)],
)
def test_month_without_decrees_advances_after_reopening(
    game_db: Path, steps, audit, first: str, extra: int
) -> None:
    received = []
    steps["simulation"] = replaying(
        [
            (RECORDED / first).read_text(),
            *[(RECORDED / "simulation.txt").read_text()] * (2 + extra),
        ],
        received,
    )
    with TestClient(create_app(game_db.parent)) as client:
        save = client.post(
            "/actions", json={"action": "load", "save": game_db.name}
        ).json()["save"]
        for year, month in [(1627, 11), (1627, 12), (1628, 1)]:
            assert client.post("/actions", json={"action": "month"}).status_code == 204
            state = client.get("/state").json()["game"]
            assert state["date"] == {"id": "world", "year": year, "month": month}
            assert (state["running"], state["pending"], state["failure"]) == (
                False,
                None,
                None,
            )
            for petition in state["petitions"]:
                calls = len(received)
                assert (
                    client.post(
                        "/actions",
                        json={
                            "action": "choose",
                            "petition": petition["id"],
                            "option": 0,
                        },
                    ).status_code
                    == 204
                )
                assert len(received) == calls
                assert client.get("/state").json()["game"]["date"] == state["date"]
            ledger = audit(game_db.parent / save)
            assert not [e for e in ledger["entities"] if e["kind"] == "affair"]
            assert not [f for f in ledger["facts"] if f["kind"] == "forecast"]
            assert (
                len([f for f in ledger["facts"] if f["kind"] == "simulation"])
                == (year - 1627) * 12 + month - 10 + extra
            )
            material = json.loads(
                received[0 if month == 11 and extra else -1].parts[0].content
            )
            assert {c["petition_id"] for c in material["context"]["prior_choices"]} == {
                f["detail"]["petition_id"]
                for f in ledger["facts"]
                if f["kind"] == "choice" and f["detail"]["date"] == material["date"]
            }
            calendar = next(
                e["id"] for e in ledger["entities"] if e["kind"] == "calendar"
            )
            assert all(
                f["entity_id"] == calendar
                for f in ledger["facts"]
                if f["kind"] == "simulation"
            )
            state = client.get("/state").json()["game"]
            client.post("/actions", json={"action": "load", "save": save})
            assert client.get("/state").json()["game"] == state


@pytest.mark.parametrize(
    "case",
    [
        (300000, 300000, False),
        (3200000, 3200000, False),
        (5000000, 3200000, False),
        (5000000, 3200000, "write"),
        (5000000, 3200000, "commit"),
    ],
)
def test_month_lands_both_sides_at_source_stock_and_preserves_nominal(
    tmp_path: Path, game_db: Path, case, steps, audit
) -> None:
    nominal, actual, interrupt = case
    steps["Declaration"] = TestModel(
        call_tools=[],
        custom_output_text=(RECORDED / f"month_money_{nominal}.txt").read_text(),
    )
    observed = []

    def before_commit(session):
        # Outer SQLAlchemy commit: policy rows and tracking exist, none durable.
        current = tuple(session.execute(text(q)).scalar_one() for q in LANDING)
        if current[1] and not observed:
            observed.append(current)
            raise RuntimeError("injected pre-commit failure")

    with TestClient(create_app(tmp_path)) as client:
        save = client.post(
            "/actions", json={"action": "load", "save": game_db.name}
        ).json()["save"]
        db = tmp_path / save
        if interrupt == "write":
            with sqlite3.connect(db) as connection:
                connection.execute(
                    "CREATE TRIGGER interrupt BEFORE UPDATE ON entities WHEN NEW.key='内库' BEGIN SELECT RAISE(ABORT, 'injected'); END"
                )
        if interrupt == "commit":
            event.listen(Session, "before_commit", before_commit)
        try:
            client.post("/actions", json={"action": "month"})
        finally:
            if interrupt == "commit":
                event.remove(Session, "before_commit", before_commit)
        with sqlite3.connect(db) as connection:
            durable = tuple(connection.execute(q).fetchone()[0] for q in LANDING)
        assert durable[0] == durable[2] and bool(durable[1]) != bool(interrupt)
        if interrupt == "commit":
            assert observed[0][0] == observed[0][2] > durable[0]
        if interrupt:
            ledger = audit(db)
            assert {
                e["key"]: e["data"]["taels"]
                for e in ledger["entities"]
                if e["kind"] == "account"
            } == {"国库": 3200000, "内库": 4400000}
            assert not [
                f for f in ledger["facts"] if f["kind"] in {"changed", "landed"}
            ]
            with sqlite3.connect(db) as connection:
                connection.execute("DROP TRIGGER IF EXISTS interrupt")
            client.post("/actions", json={"action": "load", "save": save})
            assert client.get("/state").json()["game"]["failure"] is not None
            client.post("/actions", json={"action": "retry"})
        ledger = audit(db)
        assert {
            e["key"]: e["data"]["taels"]
            for e in ledger["entities"]
            if e["kind"] == "account"
        } == {"国库": 3200000 - actual, "内库": 4400000 + actual}
        transfers = [
            f["detail"]
            for f in ledger["facts"]
            if f["kind"] == "changed" and "taels" in f["detail"]["nominal"]
        ]
        assert [(t["nominal"]["taels"], t["actual"]["taels"]) for t in transfers] == [
            (-nominal, -actual),
            (nominal, actual),
        ]
        public = audit(db, identity="public")
        assert not [e for e in public["entities"] if e["kind"] == "account"]
        assert all(
            "nominal" not in f["detail"] and "actual" not in f["detail"]
            for f in public["facts"]
        )
        if nominal == 5000000:
            reports = [f for f in public["facts"] if f["kind"] == "reported"]
            assert reports
            assert all(set(f["detail"]) == {"text"} for f in reports)
            treasury = next(e["id"] for e in ledger["entities"] if e["key"] == "国库")
            assert all(f["entity_id"] == treasury for f in reports)
        state = client.get("/state").json()["game"]
        assert state["failure"] is None
        assert state["date"]["month"] == 11


def test_exhausted_month_declaration_is_unhandled_not_a_stopped_month(
    tmp_path: Path, game_db: Path, steps, audit
) -> None:
    reply = (RECORDED / "month_invalid.txt").read_text()
    steps["Declaration"] = replaying([reply, reply])
    with TestClient(create_app(tmp_path)) as client:
        save = client.post(
            "/actions", json={"action": "load", "save": game_db.name}
        ).json()["save"]
        client.post("/actions", json={"action": "month"})
        state = client.get("/state").json()["game"]
        assert (state["date"]["month"], state["running"], state["failure"]) == (
            11,
            False,
            None,
        )
        facts = client.get("/records").json()["facts"]
        assert {f["kind"] for f in facts if f["kind"] != "interaction"} == {
            "unhandled",
            "gazette",
        }
        assert all(not f["detail"] for f in facts if f["kind"] == "unhandled")
        assert {
            e["key"]: e["data"]["taels"]
            for e in audit(tmp_path / save)["entities"]
            if e["kind"] == "account"
        } == {"国库": 3200000, "内库": 4400000}
