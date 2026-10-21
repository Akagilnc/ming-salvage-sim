"""Medium: month products and landing through HTTP, read through the CLI."""

import json
import sqlite3
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel
from starlette.testclient import TestClient

from ming.web import create_app
from tests.test_court import replaying

RECORDED = Path(__file__).parent / "recorded"


def test_month_without_decrees_advances_and_replays_after_reopening(
    tmp_path: Path, steps, audit
) -> None:
    with TestClient(create_app(tmp_path)) as client:
        save = client.post("/actions", json={"action": "new"}).json()["save"]
        for year, month in [(1627, 11), (1627, 12), (1628, 1)]:
            assert client.post("/actions", json={"action": "month"}).status_code == 204
            state = client.get("/state").json()["game"]
            assert state["date"] == {"id": "world", "year": year, "month": month}
            assert (state["running"], state["pending"], state["failure"]) == (
                False,
                None,
                None,
            )
            assert audit(tmp_path / save) == audit(tmp_path / save, True)
            client.post("/actions", json={"action": "load", "save": save})
            assert client.get("/state").json()["game"] == state


@pytest.mark.parametrize(
    "case",
    [
        (300000, 300000, False),
        (3200000, 3200000, False),
        (5000000, 3200000, False),
        (5000000, 3200000, True),
    ],
)
def test_month_lands_both_sides_at_source_stock_and_preserves_nominal(
    tmp_path: Path, case, steps, audit
) -> None:
    nominal, actual, interrupt = case
    steps["Declaration"] = TestModel(
        call_tools=[],
        custom_output_text=(RECORDED / f"month_money_{nominal}.txt").read_text(),
    )
    with TestClient(create_app(tmp_path)) as client:
        save = client.post("/actions", json={"action": "new"}).json()["save"]
        db = tmp_path / save
        if interrupt:
            with sqlite3.connect(db) as connection:
                connection.execute(
                    "CREATE TRIGGER interrupt BEFORE UPDATE ON entities WHEN NEW.key='内库' BEGIN SELECT RAISE(ABORT, 'injected'); END"
                )
        client.post("/actions", json={"action": "month"})
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
                connection.execute("DROP TRIGGER interrupt")
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
        assert ledger == audit(db, True)
        public = audit(db, identity="public")
        assert not [e for e in public["entities"] if e["kind"] == "account"]
        assert all(
            "nominal" not in f["detail"] and "actual" not in f["detail"]
            for f in public["facts"]
        )
        if nominal == 5000000:
            reports = [f for f in public["facts"] if f["kind"] == "changed"]
            assert reports
            assert all(set(f["detail"]) == {"text"} for f in reports)
            treasury = next(e["id"] for e in ledger["entities"] if e["key"] == "国库")
            assert all(f["entity_id"] == treasury for f in reports)
        state = client.get("/state").json()["game"]
        assert state["failure"] is None
        assert state["date"]["month"] == 11


def test_exhausted_month_declaration_is_unhandled_not_a_stopped_month(
    tmp_path: Path, steps, audit
) -> None:
    reply = (RECORDED / "month_invalid.txt").read_text()
    steps["Declaration"] = replaying([reply, reply])
    with TestClient(create_app(tmp_path)) as client:
        save = client.post("/actions", json={"action": "new"}).json()["save"]
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
