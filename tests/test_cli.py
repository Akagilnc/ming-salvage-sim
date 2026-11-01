"""Medium: unchanged CLI arguments and JSONL protocol use the shared actions."""

import asyncio
import io
import json
from functools import partial
from pathlib import Path
from shutil import copyfile

import pytest
from pydantic_ai.models.test import TestModel
from starlette.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.orm import Session

from ming.web import create_app

from ming.__main__ import main
from tests.test_court import replaying
from tests.test_web import committed, counted, state_updates

RECORDED = Path(__file__).parent / "recorded"


@pytest.mark.parametrize("game_db", ["approved_night"], indirect=True)
def test_cli_preserves_jsonl_and_resumes_failed_month(
    game_db: Path, steps, monkeypatch, capsys, opening_db
) -> None:
    steps["Declaration"] = TestModel(call_tools=[], custom_output_text=(RECORDED / "month_decree_money.txt").read_text())
    steps["simulation"] = replaying([(RECORDED / "month_petition.txt").read_text()])
    db = str(game_db)
    main(["month", "--db", db, "--backend", "claude-cli"])
    pending = json.loads(capsys.readouterr().out)
    assert set(pending) == {"date", "petitions"}
    assert pending["date"]["month"] == 10
    assert len(pending["petitions"]) == 1
    petition = pending["petitions"][0]
    main(["read", "--db", db, "--identity", "audit"])
    before = json.loads(capsys.readouterr().out)
    rejected = [
        "not json", "1", ' {"words":"x"}', "[]", '{"action":["x"]}',
        '{"action":"say","words":5}',
        '{"action":"choose"}', '{"action":"choose","petition":null}',
        *(json.dumps({"action": "choose", "petition": petition["id"], "option": option})
          for option in (-1, len(petition["options"]), "0", 0.5, True)),
        '{"action":"choose","petition":"00000000-0000-0000-0000-000000000000","option":0}',
        '{"action":"say","words":"退朝后说话"}',
    ]
    invocations = counted(steps)
    with TestClient(create_app(game_db.parent)) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        events = asyncio.Queue()
        client.app.state.web.listeners.add(events)
        statuses = [([client.post("/actions", content=line).status_code for line in rejected],
                     client.get("/state").json()["game"]["failure"])]
        assert state_updates(events) == []
    main(["read", "--db", db, "--identity", "audit"])
    ledger = [json.loads(capsys.readouterr().out)]
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join([*rejected, '{"action":"state"}'])))
    main(["audience", "--db", db, "--backend", "claude-cli"])
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    statuses.append(([r["error"]["status"] for r in rows[1:-1]], rows[-1]["month_error"]))
    assert set(rows[0]) == {"night"}
    assert rows[-1]["petitions"] == pending["petitions"]
    main(["read", "--db", db, "--identity", "audit"])
    ledger.append(json.loads(capsys.readouterr().out))
    assert statuses == [([400] * 14 + [409], None)] * 2
    assert ledger == [before] * 2
    assert not invocations
    alternate = str(copyfile(game_db, game_db.with_name("choose.sqlite")))
    monkeypatch.setattr("sys.stdin", io.StringIO(
        json.dumps({"action": "choose", "petition": petition["id"], "option": 0})
        + '\n{"action":"drain"}\n{"action":"state"}\n'
    ))
    main(["audience", "--db", db, "--backend", "claude-cli"])
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    main(["choose", "--db", alternate, "--backend", "claude-cli", "--petition", petition["id"], "--option", "0"])
    result = json.loads(capsys.readouterr().out)
    assert set(result) == {"date", "petitions"}
    assert {key: rows[-1][key] for key in result} == result
    assert (result["petitions"], result["date"]["month"]) == ([], 11)
    main(["read", "--db", db, "--identity", "audit"])
    ledger = json.loads(capsys.readouterr().out)
    assert not [f for f in ledger["facts"] if f["kind"] == "interaction" and f["detail"]["status"] == "done"]
    case = json.loads((RECORDED / "night_invalid.json").read_text())
    steps["Declaration"] = TestModel(
        call_tools=[], custom_output_text=(RECORDED / "month_empty.txt").read_text()
    )
    steps["simulation"] = replaying(
        [RuntimeError("backend unavailable"), (RECORDED / "simulation.txt").read_text()]
    )
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            "\n".join(json.dumps(action) for action in [
                {"action": "open"},
                {"action": "say", "words": case["emperor_words"]},
                *({"action": action} for action in (
                    "dismiss", "drain", "state", "month", "drain", "state", "month", "drain", "state",
                )),
            ])
        ),
    )
    main(["audience", "--db", db, "--backend", "claude-cli"])
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert set(rows[0]) == {"night"}
    assert all(set(row) == {"scene", "night", "month_running", "month_error", "petitions", "date"} for row in rows[1:])
    assert (rows[5]["month_error"], rows[5]["month_running"], rows[5]["petitions"]) == (None, False, [])
    assert rows[5]["night"]["closed"] is True
    assert [turn["emperor_words"] for turn in rows[5]["night"]["turns"]] == [case["emperor_words"]]
    assert rows[8]["month_error"]["type"] == "RuntimeError"
    assert set(rows[8]["month_error"]) == {"type", "message", "log"}
    assert rows[-1]["month_error"] is None
    assert rows[-1]["date"]["month"] == rows[8]["date"]["month"] % 12 + 1
    assert rows[-1]["date"]["year"] == rows[8]["date"]["year"] + (
        rows[8]["date"]["month"] == 12
    )
    for entry in ("month", "audience"):
        steps["simulation"] = replaying(
            [RuntimeError("backend unavailable"), (RECORDED / "simulation.txt").read_text()]
        )
        with pytest.raises(SystemExit) as stopped:
            main(["month", "--db", db, "--backend", "claude-cli"])
        assert stopped.value.code == 1
        pending = json.loads(capsys.readouterr().out)
        main(["read", "--db", db, "--identity", "audit"])
        ledger = json.loads(capsys.readouterr().out)
        assert any(
            f["kind"] == "interaction" and f["detail"]["status"] == "failed"
            for f in ledger["facts"]
        )
        if entry == "audience":
            monkeypatch.setattr("sys.stdin", io.StringIO('{"action":"month"}\n{"action":"drain"}\n{"action":"state"}\n'))
        main([entry, "--db", db, "--backend", "claude-cli"])
        resumed = json.loads(capsys.readouterr().out.splitlines()[-1])
        assert resumed["date"]["month"] == pending["date"]["month"] % 12 + 1
        assert resumed["date"]["year"] == pending["date"]["year"] + (pending["date"]["month"] == 12)
        assert resumed["petitions"] == []
    main(["read", "--db", db, "--identity", "audit"])
    ledger = json.loads(capsys.readouterr().out)
    assert not {"words", "petition", "option"}.intersection(next(
        f["detail"]["payload"] for f in reversed(ledger["facts"])
        if f["kind"] == "interaction" and f["detail"]["action"] == "month"
        and f["detail"]["status"] == "accepted"))
    # A world-only month can also be continued through JSONL before any audience exists.
    db = str(copyfile(opening_db, game_db.with_name("world.sqlite")))
    steps["simulation"] = replaying(
        [
            (RECORDED / "month_petition.txt").read_text(),
        ]
    )
    main(["month", "--db", db, "--backend", "claude-cli"])
    petition = json.loads(capsys.readouterr().out)["petitions"][0]
    steps["scene"] = replaying([RuntimeError("scene unavailable")])
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(json.dumps(r) for r in [
        {"action": "open"}, {"action": "say", "words": "召对"},
        {"action": "choose", "petition": petition["id"], "option": 0},
    ])))
    main(["audience", "--db", db, "--backend", "claude-cli"])
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert rows[0] == {"night": None}
    # Preserve the accepted retry and its turn commit, with month still pending.
    snapshots = {entry: Path(db).with_name(f"retry-{entry}.sqlite") for entry in ("accepted", "product")}
    capture = partial(committed, db, "turn", "say", snapshots)
    steps["scene"] = TestModel(call_tools=["dismiss"], custom_output_text=case["cases"]["missing_fields"]["scene"])
    monkeypatch.setattr("sys.stdin", io.StringIO('{"action":"retry"}\n{"action":"drain"}\n{"action":"state"}\n'))
    event.listen(Session, "after_commit", capture)
    try:
        main(["audience", "--db", db, "--backend", "claude-cli"])
    finally:
        event.remove(Session, "after_commit", capture)
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert rows[-1]["date"]["month"] == 11
    assert rows[-1]["month_error"] is None
    for entry, alternate in snapshots.items():
        steps["scene"] = replaying([RuntimeError("scene unavailable")])
        monkeypatch.setattr("sys.stdin", io.StringIO('{"action":"state"}\n'))
        main(["audience", "--db", str(alternate), "--backend", "claude-cli"])
        rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        if entry == "accepted":
            assert rows[-1]["date"]["month"] == 10
            assert rows[-1]["month_error"]["type"] == "RuntimeError"
            steps["scene"] = TestModel(call_tools=["dismiss"], custom_output_text=case["cases"]["missing_fields"]["scene"])
            monkeypatch.setattr("sys.stdin", io.StringIO('{"action":"retry"}\n{"action":"drain"}\n{"action":"state"}\n'))
            main(["audience", "--db", str(alternate), "--backend", "claude-cli"])
            rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
        else:
            assert rows[-1]["night"]["closed"] is False
            assert rows[-1]["night"]["date"] == {"year": 1627, "month": 11}
            assert rows[0]["night"] == rows[-1]["night"]["id"]
        assert rows[-1]["date"]["month"] == 11
        assert rows[-1]["month_error"] is None
    steps["NightDeclaration"] = replaying([RuntimeError("translation unavailable")])
    monkeypatch.setattr("sys.stdin", io.StringIO('{"action":"dismiss"}\n{"action":"drain"}\n'))
    main(["audience", "--db", db, "--backend", "claude-cli"])
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    before = rows[-1]["night"]
    assert before["closed"] is True
    assert rows[-1]["month_error"]["type"] == "RuntimeError"
    monkeypatch.setattr("sys.stdin", io.StringIO('{"action":"state"}\n'))
    main(["audience", "--db", db, "--backend", "claude-cli"])
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert rows[0] == {"night": before["id"]}
    assert rows[-1]["night"]["closed"] is True
    assert rows[-1]["month_error"]["type"] == "RuntimeError"
