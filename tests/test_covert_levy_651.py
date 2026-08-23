import pytest


def _event(db, event_id):
    db.conn.execute(
        "INSERT INTO events(id,title,kind,summary,urgency,severity,credibility,interests,audiences) "
        "VALUES (?,?,'民变','无散文案卷线索',1,1,1,'[]','[]')",
        (event_id, event_id),
    )


def _dossier(db, state, text="陕西军饷"):
    return db.create_decree_dossier(
        state,
        action_type="special_decree",
        decree_text=text,
        target_kind="army",
        target_id="陕西边军",
    )


def test_event_trigger_pins_dossier_without_narrative_matching(game):
    db, state, _ = game
    dossier_id = _dossier(db, state)
    _event(db, "covert-levy-uprising")

    db.mark_event_triggered(
        state,
        "covert-levy-uprising",
        source="simulation",
        terminal_reason="乡民抗税",
        target_dossier_id=dossier_id,
    )

    row = db.conn.execute(
        "SELECT target_dossier_id FROM event_triggers WHERE event_id=?",
        ("covert-levy-uprising",),
    ).fetchone()
    assert row["target_dossier_id"] == dossier_id


def test_event_trigger_binding_is_optional_but_invalid_binding_fails_loud(game):
    db, state, _ = game
    _event(db, "unrelated-event")
    _event(db, "bad-binding")
    db.mark_event_triggered(state, "unrelated-event")
    assert db.conn.execute(
        "SELECT target_dossier_id FROM event_triggers WHERE event_id='unrelated-event'"
    ).fetchone()["target_dossier_id"] is None

    with pytest.raises(ValueError, match="案卷不存在"):
        db.mark_event_triggered(state, "bad-binding", target_dossier_id=999999)

    for invalid_id in (True, 0, -1, "1"):
        with pytest.raises(ValueError, match="案卷 ID 非法"):
            db.mark_event_triggered(
                state, "bad-binding", target_dossier_id=invalid_id  # type: ignore[arg-type]
            )


def test_event_terminal_upgrade_keeps_first_structured_binding(game):
    db, state, _ = game
    first = _dossier(db, state, "陕西军饷甲案")
    second = _dossier(db, state, "陕西军饷乙案")
    _event(db, "bound-uprising")
    db.mark_event_triggered(state, "bound-uprising", target_dossier_id=first)
    db.mark_event_triggered(state, "bound-uprising", target_dossier_id=second)

    row = db.conn.execute(
        "SELECT target_dossier_id FROM event_triggers WHERE event_id='bound-uprising'"
    ).fetchone()
    assert row["target_dossier_id"] == first
