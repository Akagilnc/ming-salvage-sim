"""Medium: HTTP query work excludes closed nights and settled months.

Closed nights or settled empty months precede the same current work and questions.
The measured requests need the current night and unresolved question, not those
older nights. Scene generation is excluded: #1978 explicitly makes the earlier
witnessed nights part of its readable catalogue, so those nights are relevant.
Month opening (which legitimately reads all emperor material) is outside the
measurement; the measured month request resumes an already open month.
"""

import json
import sys
from contextvars import ContextVar
from unittest.mock import patch
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from shutil import copyfile

import pytest
from pydantic_ai import RunContext
from sqlalchemy import Engine, event
from starlette.testclient import TestClient

from ming.web import create_app
from ming.game import Game
from ming.ledger import Ledger
from ming.middle.court import Court
from ming.middle.dispatch import dispatch
from ming.middle.translate import check
from ming.middle.records import read_records

RECORDED = Path(__file__).parent / "recorded"


@contextmanager
def measure_reads(operations=None):
    """Observe real SQL without consuming its cursor or replacing the read path."""
    result = {"budget": [0, 0], "entities": Counter(), "singletons": {}, "appointments": {}, "notifications": [], "actions": []}
    current = ContextVar("measured_action", default=None)
    reading = ContextVar("application_read", default=False)
    execute, presentation, read = Game.execute, Court.presentation, Ledger.read
    appointment_calls = (check.__code__, dispatch.__code__)

    @contextmanager
    def observing(action):
        observation = {"action": action, "calendar": Counter(), "night": Counter(), "active": True}
        result["actions"].append(observation)
        token = current.set(observation)
        try:
            yield
        finally:
            observation["active"] = False
            current.reset(token)

    async def observe_action(game, action, payload, *args):
        with observing(action):
            return await execute(game, action, payload, *args)

    def observe_presentation(court):
        with observing("presentation"):
            return presentation(court)

    def observe_read(ledger, query, parameters=None):
        token = reading.set(True)
        try:
            rows = read(ledger, query, parameters)
        finally:
            reading.reset(token)
        result["budget"][1] += len(rows)
        if rows and {"id", "kind", "key", "data"} <= rows[0].keys():
            result["entities"].update(row["id"] for row in rows)
            observation = current.get()
            frame = sys._getframe() if observation is not None or operations is not None else None
            model_request, model_read, failure_read, appointment_work = None, False, False, False
            while frame is not None:
                appointment_work = appointment_work or frame.f_code in appointment_calls
                model_read = model_read or frame.f_code is read_records.__code__
                failure_read = failure_read or (frame.f_code is Game.interaction.__code__ and frame.f_locals["status"] == "failed")
                if operations is not None and model_request is None and frame.f_globals.get("__name__", "").startswith("ming."):
                    ctx = frame.f_locals.get("ctx")
                    if isinstance(ctx, RunContext):
                        model_request = ctx
                if model_read and (operations is None or model_request is not None):
                    break
                frame = frame.f_back
            # A presentation and an independent model tool request each have
            # their own boundary; no SQL-text or commit-interval fingerprint.
            if observation is not None and observation["active"] and not model_read and len(rows) == 1:
                row = rows[0]
                if row["kind"] == "calendar":
                    # A failed write may already have committed before its push
                    # callback raised. Failure logging must establish the date
                    # anew; repeated reads within that recovery still fail.
                    observation["calendar"][(row["id"], row["data"]["year"], row["data"]["month"], failure_read)] += 1
                elif row["kind"] == "night" and "result" in row:
                    observation["night"][(row["id"], row["data"]["closed"], tuple(row["data"]["hall"]), row["result"] is not None)] += 1
            if operations is not None and appointment_work:
                result["appointments"].setdefault((len(operations), ledger), Counter()).update(
                    (row["kind"], row["key"]) for row in rows if row["kind"] in {"office", "territory", "incumbency"}
                )
            if operations is not None and len(rows) == 1:
                result["singletons"].setdefault((len(operations), ledger,
                                                 model_request.tool_call_id if model_request is not None else None), set()).add(
                    (rows[0]["kind"], rows[0]["key"]),
                )
        return rows

    def count_reads(**query):
        if query["context"].compiled is not None and query["context"].compiled.statement.is_select:
            result["budget"][0] += 1
            if not reading.get():
                # Library aggregate/replay reads do not pass Ledger.read.
                probe = query["conn"].connection.cursor()
                try:
                    probe.execute(query["statement"], query["parameters"])
                    rows = tuple(probe.fetchall())
                    columns = [column[0] for column in probe.description]
                    if "ledger_events_id" in columns:
                        result["notifications"].extend(row[columns.index("ledger_events_id")] for row in rows)
                    result["budget"][1] += len(rows)
                finally:
                    probe.close()

    event.listen(Engine, "after_cursor_execute", count_reads, named=True)
    try:
        with patch.object(Game, "execute", observe_action), patch.object(Court, "presentation", observe_presentation), patch.object(Ledger, "read", observe_read):
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
            presentations = [a for a in reads["actions"] if a["action"] == "presentation"]
            assert presentations and all(p["calendar"] for p in presentations)
            assert all(count == 1 for p in presentations for kind in ("calendar", "night") for count in p[kind].values())
            if action == "state":
                # One presentation needs each current entity once. This scope is
                # one HTTP request, not equal SQL across commits or requests.
                assert reads["entities"] and set(reads["entities"].values()) == {1}
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
