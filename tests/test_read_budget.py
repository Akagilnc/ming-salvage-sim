"""Medium: HTTP query work excludes closed nights and settled months.

Closed nights or settled empty months precede the same current work and questions.
The measured requests need the current night and unresolved question, not those
older nights. Month opening (which legitimately reads all emperor material) is
outside the measurement; the measured month request resumes an already open month.
"""

import json
from pathlib import Path
from shutil import copyfile

import pytest
from sqlalchemy import Engine, event
from starlette.testclient import TestClient

from ming.web import create_app

RECORDED = Path(__file__).parent / "recorded"


@pytest.mark.parametrize("history", ["night", "month"], indirect=True)
@pytest.mark.parametrize("action", ["state", "say", "month", "choose"])
def test_http_read_work_ignores_unrelated_history(
    tmp_path, steps, action, pending_histories
):
    budgets = []
    for size in (1, 2, 4):
        petitions = (RECORDED / "month_multiple_petitions.txt").read_text()
        source = pending_histories[size]
        directory = tmp_path / str(size)
        directory.mkdir()
        save = copyfile(source, directory / source.name).name
        app = create_app(directory)
        with TestClient(app) as client:
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
