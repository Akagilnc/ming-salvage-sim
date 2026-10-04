"""#14 / #1889：JSON 损坏面随 Store 权威归位后的契约。

IssueStore / ResolveContextStore 对在场损坏 JSON fail-loud（ValueError）。
legacy_modifiers 仍在 GameDB：损坏项跳过并经 tlog 留痕。
"""

import pytest

import ming_sim.db as db_mod



def test_pending_decisions_corrupt_options_json_fails_loud(game, monkeypatch):
    db, _state, _content = game
    db.conn.execute(
        "INSERT INTO pending_decisions "
        "(turn, idx, title, context, options_json, choice_json, status) "
        "VALUES (?, ?, ?, ?, ?, '', 'pending')",
        (999, 0, "测试抉择", "", "{不是合法JSON"),
    )
    db.conn.commit()

    with pytest.raises(ValueError):
        db.issues.list_pending_decisions(999)


def test_pending_decisions_corrupt_choice_json_fails_loud(game, monkeypatch):
    db, _state, _content = game
    db.conn.execute(
        "INSERT INTO pending_decisions "
        "(turn, idx, title, context, options_json, choice_json, status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'pending')",
        (998, 0, "测试抉择", "", "[]", "{坏choice"),
    )
    db.conn.commit()

    with pytest.raises(ValueError):
        db.issues.list_pending_decisions(998)


def test_resolve_context_corrupt_payload_fails_loud(game, monkeypatch):
    db, _state, _content = game
    db.save_resolve_context(
        500, decree_text="旨", simulator_payload={"a": 1},
    )
    db.conn.execute(
        "UPDATE pending_resolve_context SET simulator_payload_json = ? WHERE turn = ?",
        ("{坏payload", 500),
    )
    db.conn.commit()

    with pytest.raises(ValueError):
        db.resolve_contexts.get(500)


def test_legacy_modifiers_corrupt_json_fails_loud(game, monkeypatch):
    db, state, _content = game
    baseline = db.legacy_modifiers(state).get("国库", 0)

    lid = db.insert_legacy(state, name="测试遗产", modifiers={"国库": 10})
    db._legacy_mod_cache = None
    assert db.legacy_modifiers(state).get("国库", 0) == baseline + 10

    db.conn.execute("UPDATE legacies SET modifiers = ? WHERE id = ?", ("{坏掉的JSON", lid))
    db.conn.commit()
    db._legacy_mod_cache = None

    # #1889 applier.load_stored_object：损坏 modifiers fail-loud，不再静默跳过。
    with pytest.raises(ValueError):
        db.legacy_modifiers(state)
