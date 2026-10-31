"""Medium: HTTP query work excludes closed nights and settled months.

Closed nights or settled empty months precede the same current work and questions.
The measured requests need the current night and unresolved question, not those
older nights. Scene generation is excluded: #1978 explicitly makes the earlier
witnessed nights part of its readable catalogue, so those nights are relevant.
Month opening (which legitimately reads all emperor material) is outside the
measurement; the measured month request resumes an already open month.
"""

import json
from collections import Counter
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
    result = {"budget": [0, 0], "entity_writes": 0, "event_rows": 0, "catalogues": Counter()}

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
                row_count = len(probe.fetchall())
                result["budget"][1] += row_count
                # The public catalogue's projection, not SQL text or a total-query ceiling.
                if (tuple(column[0] for column in probe.description) == ("kind", "key", "event_count")
                        and "read_people" in query["context"].compiled.params):
                    parameters = query["context"].compiled_parameters[0]
                    identity = (tuple(value for key, value in parameters.items() if key.startswith("read_people_")),
                                parameters.get("exclude_secrets", False))
                    result["catalogues"][identity] += 1
                if any(getattr(table, "name", None) == "ledger_events"
                       for table in compiled.statement.get_final_froms()):
                    result["event_rows"] += row_count
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
    tmp_path, steps, action, pending_histories, audit
):
    budgets = []
    for size in (1, 2, 4):
        petitions = (RECORDED / "month_multiple_petitions.txt").read_text()
        source = pending_histories[size]
        ledger = audit(source)
        calendar = next(e["id"] for e in ledger["entities"] if e["kind"] == "calendar")
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
            # Read-only opening no longer accidentally warms the calendar by
            # writing redundant action states. A first write must reconstruct
            # this aggregate's Created event plus its own recorded facts.
            expected = 0 if action == "state" else 1 + sum(f["entity_id"] == calendar for f in ledger["facts"])
            assert reads["event_rows"] == expected
            budgets.append((reads["budget"][0], reads["budget"][1] - expected))

    assert budgets[0] == budgets[1] == budgets[2]
