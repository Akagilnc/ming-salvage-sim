import sqlite3
from pathlib import Path

from ming_sim.db import GameDB
import ming_sim.issues as I


def _table_columns(db, table: str) -> dict[str, dict[str, object]]:
    return {
        row["name"]: dict(row)
        for row in db.conn.execute(f"PRAGMA table_info({table})").fetchall()
    }


def test_issues_schema_has_commitment_deadline_columns(game):
    db, _, _ = game

    cols = _table_columns(db, "issues")

    assert "end_turn" in cols
    assert "stop_condition" in cols
    assert cols["end_turn"]["dflt_value"] == "0"
    assert cols["stop_condition"]["dflt_value"] == "''"


def test_insert_issue_persists_commitment_deadline_columns(game):
    db, state, _ = game

    issue_id = db.insert_issue(
        state,
        kind="initiative",
        title="补辽饷直到补齐",
        origin_kind="decree",
        end_turn=state.turn + 6,
        stop_condition='{"_gate_passed":true}',
    )

    row = db.conn.execute(
        "SELECT end_turn, stop_condition FROM issues WHERE id=?", (issue_id,)
    ).fetchone()
    assert dict(row) == {
        "end_turn": state.turn + 6,
        "stop_condition": '{"_gate_passed":true}',
    }


def test_decree_initiative_cap_allows_fifteen_active_issues(game):
    db, state, _ = game
    for idx in range(14):
        db.insert_issue(
            state,
            kind="initiative",
            title=f"既有国策{idx}",
            origin_kind="decree",
            effect_on_resolve={"metrics": {"民心": 1}},
        )

    out = I.apply_issue_tracker_output(db, state, {
        "new_issues": [{
            "origin_kind": "decree",
            "kind": "initiative",
            "title": "第十五条承诺地基",
            "effect_on_resolve": {"metrics": {"民心": 1}},
        }],
    })

    created = [item for item in out["new_issues"] if item.get("issue_id")]
    assert len(created) == 1, out
    assert db.count_active_initiatives() == 15


def test_show_active_issues_uses_fifteen_initiative_cap(game, capsys):
    db, state, _ = game
    db.insert_issue(state, kind="initiative", title="国策展示", origin_kind="decree")

    I.show_active_issues(db)

    out = capsys.readouterr().out
    assert "玩家 1/15" in out
    assert "玩家 1/10" not in out


def test_existing_issues_table_gets_commitment_columns_idempotently(tmp_path, content):
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE issues (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            origin_kind TEXT NOT NULL DEFAULT '',
            origin_ref TEXT NOT NULL DEFAULT '',
            origin_turn INTEGER NOT NULL,
            bar_value INTEGER NOT NULL DEFAULT 40,
            bar_good_meaning TEXT NOT NULL DEFAULT '已平',
            bar_bad_meaning TEXT NOT NULL DEFAULT '失控',
            inertia INTEGER NOT NULL DEFAULT 0,
            phase TEXT NOT NULL DEFAULT '起',
            stage_text TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'active',
            severity INTEGER NOT NULL DEFAULT 50,
            region_hint TEXT NOT NULL DEFAULT '',
            faction_hint TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '[]',
            ongoing_effects TEXT NOT NULL DEFAULT '{}',
            cancellable TEXT NOT NULL DEFAULT 'never',
            cancel_cost TEXT NOT NULL DEFAULT '{}',
            effect_on_resolve TEXT NOT NULL DEFAULT '{}',
            effect_on_fail TEXT NOT NULL DEFAULT '{}',
            resolve_condition TEXT NOT NULL DEFAULT '',
            fail_condition TEXT NOT NULL DEFAULT '',
            resolution_summary TEXT NOT NULL DEFAULT '',
            last_advance_turn INTEGER NOT NULL DEFAULT 0,
            closed_turn INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    conn.close()

    db = GameDB(str(path), content)
    db.close()
    db = GameDB(str(path), content)
    try:
        cols = _table_columns(db, "issues")
        assert cols["end_turn"]["dflt_value"] == "0"
        assert cols["stop_condition"]["dflt_value"] == "''"
    finally:
        db.close()


def test_decree_initiative_cap_rejects_sixteenth_with_updated_message(game):
    db, state, _ = game
    for idx in range(15):
        db.insert_issue(
            state,
            kind="initiative",
            title=f"既有国策{idx}",
            origin_kind="decree",
            effect_on_resolve={"metrics": {"民心": 1}},
        )

    out = I.apply_issue_tracker_output(db, state, {
        "new_issues": [{
            "origin_kind": "decree",
            "kind": "initiative",
            "title": "第十六条应拒",
            "effect_on_resolve": {"metrics": {"民心": 1}},
        }],
    })

    rejected = [item for item in out["new_issues"] if item.get("rejected")]
    assert len(rejected) == 1, out
    assert "十五事在办" in rejected[0]["reason"]
    assert "十事在办" not in rejected[0]["reason"]


def test_delta_schema_pitfall_table_documents_fifteen_initiative_cap():
    text = Path("docs/DELTA_SCHEMA.md").read_text(encoding="utf-8")

    assert "active `initiative` ≤15" in text
    assert "active `initiative` ≤10" not in text
