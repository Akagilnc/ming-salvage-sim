"""Medium: unchanged CLI arguments and JSONL protocol use the shared actions."""

import io
import json
from pathlib import Path
from shutil import copyfile

import pytest
from pydantic_ai.models.test import TestModel
from starlette.testclient import TestClient

from ming.web import create_app

from ming.__main__ import main
from tests.test_court import replaying

RECORDED = Path(__file__).parent / "recorded"


@pytest.mark.parametrize("steps", ["approved"], indirect=True)
def test_cli_preserves_jsonl_and_resumes_failed_month(
    game_db: Path, steps, monkeypatch, capsys, opening_db
) -> None:
    case = json.loads((RECORDED / "night_approved.json").read_text())
    steps["Declaration"] = replaying([
        (RECORDED / "month_decree_money.txt").read_text(),
        (RECORDED / "month_empty.txt").read_text(),
    ])
    steps["simulation"] = replaying(
        [
            (RECORDED / "month_petition.txt").read_text(),
        ]
    )
    db = str(game_db)
    requests = [
        {"action": "open"},
        *[{"action": "say", "words": words} for words in case["words"]],
    ]
    requests += [
        {"action": action} for action in ("dismiss", "drain", "month", "drain", "state")
    ]
    monkeypatch.setattr(
        "sys.stdin", io.StringIO("\n".join(json.dumps(r) for r in requests))
    )
    main(["audience", "--db", db, "--backend", "claude-cli"])
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert set(rows[0]) == {"night"}
    assert all(
        set(row)
        == {"scene", "night", "month_running", "month_error", "petitions", "date"}
        for row in rows[1:]
    )
    assert rows[-1]["date"]["month"] == 10
    assert rows[-1]["month_running"] is False
    assert rows[-1]["month_error"] is None
    assert rows[-1]["night"]["closed"] is True
    assert len(rows[-1]["petitions"]) == 1
    petition = rows[-1]["petitions"][0]
    main(["read", "--db", db, "--identity", "audit"])
    before = json.loads(capsys.readouterr().out)
    rejected = [
        "not json", "1", ' {"words":"x"}', "[]", '{"action":["x"]}',
        '{"action":"say","words":5}',
        json.dumps({"action": "choose", "petition": petition["id"], "option": -1}),
        '{"action":"choose","petition":"00000000-0000-0000-0000-000000000000","option":0}',
        '{"action":"say","words":"退朝后说话"}',
    ]
    with TestClient(create_app(game_db.parent)) as client:
        client.post("/actions", json={"action": "load", "save": game_db.name}).raise_for_status()
        client.portal.call(client.app.state.web.game.drain)
        assert [client.post("/actions", content=line).status_code for line in rejected] == [400] * 8 + [409]
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join([*rejected, '{"action":"state"}'])))
    main(["audience", "--db", db, "--backend", "claude-cli"])
    refused = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [r["error"]["status"] for r in refused[1:-1]] == [400] * 8 + [409]
    assert refused[-1]["month_error"] is None
    main(["read", "--db", db, "--identity", "audit"])
    assert json.loads(capsys.readouterr().out) == before
    for entry in ("audience", "choose"):
        if entry == "audience":
            monkeypatch.setattr(
                "sys.stdin",
                io.StringIO(
                    json.dumps(
                        {"action": "choose", "petition": petition["id"], "option": 0}
                    )
                    + '\n{"action":"drain"}\n{"action":"state"}\n'
                ),
            )
            main(["audience", "--db", db, "--backend", "claude-cli"])
            result = json.loads(capsys.readouterr().out.splitlines()[-1])
            assert result["petitions"] == []
            assert result["date"]["month"] == 11
        else:
            steps["simulation"] = replaying(
                [
                    (RECORDED / "month_petition.txt").read_text(),
                ]
            )
            main(["month", "--db", db, "--backend", "claude-cli"])
            petition = json.loads(capsys.readouterr().out)["petitions"][0]
            main(
                [
                    "choose",
                    "--db",
                    db,
                    "--backend",
                    "claude-cli",
                    "--petition",
                    petition["id"],
                    "--option",
                    "0",
                ]
            )
            result = json.loads(capsys.readouterr().out)
            assert result["petitions"] == []
            assert result["date"]["month"] == 12
    main(["read", "--db", db, "--identity", "audit"])
    ledger = json.loads(capsys.readouterr().out)
    assert not [f for f in ledger["facts"] if f["kind"] == "interaction" and f["detail"]["status"] == "done"]
    decree = next(e for e in ledger["entities"] if e["kind"] == "decree")
    assert {f["kind"] for f in ledger["facts"] if f["entity_id"] == decree["id"]} >= {
        "deliberation",
        "landed",
    }
    assert [
        f
        for f in ledger["facts"]
        if f["kind"] == "changed" and f["detail"].get("origin_ref") == decree["id"] and "taels" in f["detail"]["actual"]
    ]
    steps["NightDeclaration"] = TestModel(
        call_tools=[],
        custom_output_text=json.loads((RECORDED / "night_invalid.json").read_text())[
            "cases"
        ]["missing_fields"]["reply"],
    )
    steps["Declaration"] = TestModel(
        call_tools=[], custom_output_text=(RECORDED / "month_empty.txt").read_text()
    )
    steps["simulation"] = replaying(
        [RuntimeError("backend unavailable"), (RECORDED / "simulation.txt").read_text()]
    )
    monkeypatch.setattr(
        "sys.stdin",
        io.StringIO(
            "\n".join(
                json.dumps({"action": action})
                for action in (
                    "dismiss",
                    "drain",
                    "month",
                    "drain",
                    "state",
                    "month",
                    "drain",
                    "state",
                )
            )
        ),
    )
    main(["audience", "--db", db, "--backend", "claude-cli"])
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert rows[5]["month_error"]["type"] == "RuntimeError"
    assert set(rows[5]["month_error"]) == {"type", "message", "log"}
    assert rows[-1]["month_error"] is None
    assert rows[-1]["date"]["month"] == rows[5]["date"]["month"] % 12 + 1
    assert rows[-1]["date"]["year"] == rows[5]["date"]["year"] + (
        rows[5]["date"]["month"] == 12
    )
    steps["simulation"] = replaying(
        [RuntimeError("backend unavailable"), (RECORDED / "simulation.txt").read_text()]
    )
    with pytest.raises(SystemExit) as stopped:
        main(["month", "--db", db, "--backend", "claude-cli"])
    assert stopped.value.code == 1
    failed_date = json.loads(capsys.readouterr().out)["date"]
    main(["read", "--db", db, "--identity", "audit"])
    ledger = json.loads(capsys.readouterr().out)
    assert any(
        f["kind"] == "interaction" and f["detail"]["status"] == "failed"
        for f in ledger["facts"]
    )
    main(["month", "--db", db, "--backend", "claude-cli"])
    resumed = json.loads(capsys.readouterr().out)
    assert resumed["date"]["month"] == failed_date["month"] % 12 + 1
    assert resumed["date"]["year"] == failed_date["year"] + (failed_date["month"] == 12)
    assert resumed["petitions"] == []
    # A world-only month can also be continued through JSONL before any audience exists.
    db = str(copyfile(opening_db, game_db.with_name("world.sqlite")))
    steps["simulation"] = replaying(
        [
            (RECORDED / "month_petition.txt").read_text(),
        ]
    )
    main(["month", "--db", db, "--backend", "claude-cli"])
    petition = json.loads(capsys.readouterr().out)["petitions"][0]
    steps["scene"] = replaying([
        RuntimeError("scene unavailable"),
        json.loads((RECORDED / "night_invalid.json").read_text())["cases"]["missing_fields"]["scene"],
    ])
    monkeypatch.setattr("sys.stdin", io.StringIO("\n".join(json.dumps(r) for r in [
        {"action": "open"}, {"action": "say", "words": "召对"},
        {"action": "choose", "petition": petition["id"], "option": 0},
        *({"action": action} for action in ("retry", "drain", "state")),
    ])))
    main(["audience", "--db", db, "--backend", "claude-cli"])
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert rows[0] == {"night": None}
    assert rows[-1]["date"]["month"] == 11
    assert rows[-1]["month_error"] is None
