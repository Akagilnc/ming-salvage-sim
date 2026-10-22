"""Medium: HTTP query work excludes closed nights and settled months.

Closed nights or settled empty months precede the same current work and questions.
The measured requests need the current night and unresolved question, not those
older nights. Month opening (which legitimately reads all emperor material) is
outside the measurement; the measured month request resumes an already open month.
"""

import json
import sqlite3
from pathlib import Path

import pytest
from pydantic_ai.models.test import TestModel
from sqlalchemy import Engine, event, text
from sqlalchemy.orm import Session
from starlette.testclient import TestClient

from ming.web import create_app
from tests.test_court import replaying

RECORDED = Path(__file__).parent / "recorded"


@pytest.mark.parametrize("history", ["night", "month"])
@pytest.mark.parametrize("action", ["state", "say", "month", "choose"])
def test_http_read_work_ignores_unrelated_history(tmp_path, steps, action, history):
    budgets = []
    for size in (1, 2, 4):
        steps["NightDeclaration"] = TestModel(
            call_tools=[],
            custom_output_text=json.dumps({"facts": [], "reports": [], "decrees": []}),
        )
        petitions = (RECORDED / "month_multiple_petitions.txt").read_text()
        steps["simulation"] = TestModel(
            call_tools=[], custom_output_text=(RECORDED / "simulation.txt").read_text()
        )
        app = create_app(tmp_path / str(size))
        with TestClient(app) as client:
            save = client.post("/actions", json={"action": "new"}).json()["save"]
            fresh = client.get("/state").json()["game"]
            assert (fresh["night"], fresh["date"]) == (
                None,
                {"id": "world", "year": 1627, "month": 10},
            )
            if history == "month":
                for _ in range(size):
                    client.post("/actions", json={"action": "month"})
                    client.portal.call(app.state.web.game.drain)
            for _ in range(size if history == "night" else 1):
                client.post("/actions", json={"action": "open"})
                client.post("/actions", json={"action": "dismiss"})
                client.portal.call(app.state.web.game.drain)
            steps["simulation"] = replaying(
                [
                    petitions,
                    *[(RECORDED / "simulation.txt").read_text()]
                    * sum(
                        len(p["options"]) for p in json.loads(petitions)["petitions"]
                    ),
                ]
            )
            client.post("/actions", json={"action": "month"})
            client.portal.call(app.state.web.game.drain)
            client.post("/actions", json={"action": "load", "save": save})
            client.portal.call(app.state.web.game.drain)
            payload = {"action": action, "words": "召见。"}
            if action == "say":
                client.post("/actions", json={"action": "open"})
            elif action == "choose":
                petition = client.get("/state").json()["game"]["petitions"][0]
                payload.update(petition=petition["id"], option=0)

            budget = [0, 0]

            def count_reads(**query):
                statement, parameters = query["statement"], query["parameters"]
                if statement.lstrip().upper().startswith("SELECT"):
                    # Count returned rows without consuming or replacing the real
                    # cursor; the probe bypasses SQLAlchemy's event listeners.
                    probe = query["conn"].connection.cursor()
                    try:
                        probe.execute(
                            "SELECT count(*) FROM (" + statement + ")", parameters
                        )
                        budget[0] += 1
                        budget[1] += probe.fetchone()[0]
                    finally:
                        probe.close()

            event.listen(Engine, "after_cursor_execute", count_reads, named=True)
            try:
                response = (
                    client.get("/state")
                    if action == "state"
                    else client.post("/actions", json=payload)
                )
                client.portal.call(app.state.web.game.drain)
            finally:
                event.remove(Engine, "after_cursor_execute", count_reads)
            assert response.status_code == (200 if action == "state" else 204)
            assert client.get("/state").json()["game"]["failure"] is None
            if action == "choose":
                # Other questions remain; no world read for final gazette work
                # is falsely classified as unrelated to this measured request.
                assert (
                    len(client.get("/state").json()["game"]["petitions"])
                    == len(json.loads(petitions)["petitions"]) - 1
                )
            budgets.append(tuple(budget))

    assert budgets[0] == budgets[1] == budgets[2]


@pytest.mark.parametrize("crash", [False, True])
def test_http_commit_keeps_events_rows_and_tracking_atomic(
    tmp_path, steps, audit, crash
):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        save = client.post("/actions", json={"action": "new"}).json()["save"]
        db = tmp_path / save
        before = audit(db)
        with sqlite3.connect(db) as connection:
            position = connection.execute(
                "SELECT max(id) FROM ledger_events"
            ).fetchone()[0]
        observed = []

        def before_commit(session):
            # Session.commit is the outer SQLAlchemy commit: policy and library
            # tracking have run, but neither is durable yet.
            observed.append(
                tuple(
                    session.execute(text(query)).scalar_one()
                    for query in (
                        "SELECT max(id) FROM ledger_events",
                        "SELECT count(*) FROM entities WHERE kind = 'night'",
                        "SELECT max(notification_id) FROM readmodel_tracking",
                    )
                )
            )
            if crash:
                raise RuntimeError("injected pre-commit failure")

        event.listen(Session, "before_commit", before_commit)
        try:
            if crash:
                with pytest.raises(RuntimeError):
                    client.post("/actions", json={"action": "open"})
            else:
                assert (
                    client.post("/actions", json={"action": "open"}).status_code == 200
                )
        finally:
            event.remove(Session, "before_commit", before_commit)
        assert observed == [(position + 1, 1, position + 1)]
    with sqlite3.connect(db) as connection:
        assert tuple(
            connection.execute(query).fetchone()[0]
            for query in (
                "SELECT max(id) FROM ledger_events",
                "SELECT count(*) FROM entities WHERE kind = 'night'",
                "SELECT max(notification_id) FROM readmodel_tracking",
            )
        ) == (position + int(not crash), int(not crash), position + int(not crash))
    reopened = audit(db)
    assert reopened == audit(db, True)
    if crash:
        assert reopened == before
    else:
        assert len([e for e in reopened["entities"] if e["kind"] == "night"]) == 1
