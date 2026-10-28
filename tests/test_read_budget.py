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
def measure_reads(operations=None):
    """Observe real SQL without consuming its cursor or replacing the read path."""
    result = {"budget": [0, 0], "repeated": [], "queries": [], "singletons": {}, "notifications": []}
    previous = {}
    fields = {"id", "entity_id", "position", "kind", "key", "event_count", "person", "ordinal", "result", "exposure", "originator_id", "originator_version"}

    def count_reads(**query):
        statement, parameters = query["statement"], query["parameters"]
        if query["context"].compiled is not None and query["context"].compiled.statement.is_select:
            probe = query["conn"].connection.cursor()
            try:
                probe.execute(statement, parameters)
                rows = tuple(probe.fetchall())
                columns = [column[0] for column in probe.description]
                if "ledger_events_id" in columns:
                    result["notifications"].extend(row[columns.index("ledger_events_id")] for row in rows)
                identity_column = columns.index("id") if {"id", "kind", "key", "data"} <= set(columns) else None
                identities = {row[identity_column] for row in rows} if identity_column is not None else set()
                versions = {}
                if identities:
                    probe.execute(
                        "SELECT originator_id, max(originator_version) FROM ledger_events WHERE originator_id IN ("
                        + ",".join("?" for _ in identities) + ") AND (originator_version = 1 "
                        "OR EXISTS (SELECT 1 FROM json_each(CAST(state AS TEXT), '$.changes') WHERE key IS NOT NULL)) GROUP BY originator_id",
                        tuple(bytes.fromhex(identity) for identity in identities),
                    )
                    versions = {identity.hex(): version for identity, version in probe.fetchall()}
                # Compare only row identities, revisions and typed query outputs;
                # model prose/data payloads are neither hashed nor constrained.
                indices = [i for i, name in enumerate(columns) if name in fields]
                state = tuple((tuple(row[i] for i in indices),
                               versions.get(row[identity_column]) if identity_column is not None else None) for row in rows)
            finally:
                probe.close()
            if operations is not None and identity_column is not None and len(rows) == 1:
                # Associate actual single-entity results with the issued model
                # request, independent of lookup predicates or parameter layout.
                result["singletons"].setdefault((len(operations), query["conn"].engine, statement), set()).add(
                    (rows[0][columns.index("kind")], rows[0][columns.index("key")]),
                )
            result["queries"].append((query["conn"].engine, tuple(parameters)))
            result["budget"][0] += 1
            result["budget"][1] += len(rows)
            key = query["conn"].engine, statement, tuple(parameters)
            if key in previous and previous[key] == state:
                result["repeated"].append((statement, parameters))
            previous[key] = state

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
                # Other questions remain; no world read for final gazette work
                # is falsely classified as unrelated to this measured request.
                assert (
                    len(client.get("/state").json()["game"]["petitions"])
                    == len(json.loads(petitions)["petitions"]) - 1
                )
            budgets.append(tuple(reads["budget"]))

    assert budgets[0] == budgets[1] == budgets[2]
