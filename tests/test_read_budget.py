"""Medium: HTTP query work excludes closed nights and settled months.

Closed nights or settled empty months precede the same current work and questions.
The measured requests need the current night and unresolved question, not those
older nights. Scene generation is excluded: #1978 explicitly makes the earlier
witnessed nights part of its readable catalogue, so those nights are relevant.
Month opening (which legitimately reads all emperor material) is outside the
measurement; the measured month request resumes an already open month.
"""

import json
from contextlib import contextmanager
from pathlib import Path
from shutil import copyfile

import pytest
from sqlalchemy import Engine, event
from starlette.testclient import TestClient

from ming.web import create_app

RECORDED = Path(__file__).parent / "recorded"


@contextmanager
def measure_reads():
    """Observe SQL without consuming or replacing its real cursor."""
    result = {"budget": [0, 0], "entity_writes": 0}

    def count_reads(**query):
        compiled = query["context"].compiled
        if compiled is None:
            return
        if compiled.statement.is_insert and compiled.statement.table.name == "entities":
            result["entity_writes"] += len(query["parameters"]) if query["executemany"] else 1
        if compiled.statement.is_select:
            probe = query["conn"].connection.cursor()
            try:
                probe.execute(query["statement"], query["parameters"])
                result["budget"][0] += 1
                result["budget"][1] += len(probe.fetchall())
            finally:
                probe.close()

    event.listen(Engine, "after_cursor_execute", count_reads, named=True)
    try:
        yield result
    finally:
        event.remove(Engine, "after_cursor_execute", count_reads)


@pytest.mark.parametrize(
    "pending_histories",
    [
        pytest.param("night", marks=pytest.mark.xdist_group("history-night")),
        pytest.param("month", marks=pytest.mark.xdist_group("history-month")),
    ],
    indirect=True,
)
@pytest.mark.parametrize("action", ["state", "month", "choose"])
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
            if action == "choose":
                petition = client.get("/state").json()["game"]["petitions"][0]
                payload.update(petition=petition["id"], option=0)

            with measure_reads() as reads:
                response = (
                    client.get("/state")
                    if action == "state"
                    else client.post("/actions", json=payload)
                )
                client.portal.call(app.state.web.game.drain)
            assert response.status_code == (200 if action == "state" else 204)
            assert client.get("/state").json()["game"]["failure"] is None
            if action == "choose":
                assert (
                    len(client.get("/state").json()["game"]["petitions"])
                    == len(json.loads(petitions)["petitions"]) - 1
                )
            budgets.append(tuple(reads["budget"]))

    assert budgets[0] == budgets[1] == budgets[2]
