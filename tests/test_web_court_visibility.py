"""Court and talent rosters are projections of the live persisted character state."""
from __future__ import annotations

import pytest

import web_app
from ming_sim.issues import apply_office_appointment


def test_state_payload_projects_court_and_talent_rosters(game, monkeypatch):
    db, state, content = game
    monkeypatch.setenv("MING_SIM_LLM_BACKEND", "agy")
    monkeypatch.setattr(web_app, "load_runtime_llm", lambda: {})
    runtime = web_app.WebGame(db_path=db.path, fresh=False)
    try:
        character = runtime.content.characters["毕自严"]
        db.conn.execute("UPDATE characters SET status='active', power_id='ming' WHERE name=?", (character.name,))
        db.conn.commit()
        # DB, not the stale runtime character, controls roster membership.
        character.status = "offstage"
        payload = runtime.state_payload()
        assert character.name in {row["name"] for row in payload["ministers"]}
        assert character.name not in {row["name"] for row in payload["talent_pool"]}

        db.set_character_status(state, character.name, "offstage", "罢居")
        character.status = "active"
        payload = runtime.state_payload()
        assert character.name not in {row["name"] for row in payload["ministers"]}
        assert character.name in {row["name"] for row in payload["talent_pool"]}

        # Future debut, vassals, consorts and amnestied rebels are not former ministers.
        character.debut_year, character.debut_month = state.year, state.period + 1
        assert character.name not in {row["name"] for row in runtime.state_payload()["talent_pool"]}
        character.debut_month = state.period
        assert character.name in {row["name"] for row in runtime.state_payload()["talent_pool"]}
        for ch in runtime.content.characters.values():
            if ch.office_type in {"宗藩", "后宫"} or ch.faction == "流寇":
                db.add_character(state, ch, source="roster setup")
                db.conn.execute("UPDATE characters SET status='offstage', power_id='ming' WHERE name=?", (ch.name,))
        db.conn.commit()
        payload = runtime.state_payload()
        excluded = {ch.name for ch in runtime.content.characters.values()
                    if ch.office_type in {"宗藩", "后宫"} or ch.faction == "流寇"}
        assert excluded.isdisjoint(row["name"] for row in payload["talent_pool"])
        assert excluded.isdisjoint(row["name"] for row in payload["ministers"])
        assert "史可法" not in {row["name"] for row in payload["ministers"]}

        # Allegiance uses the persisted power, even after an amnesty/defection.
        db.conn.execute("UPDATE characters SET status='active', power_id='houjin' WHERE name=?", (character.name,))
        db.conn.commit()
        assert character.name not in {row["name"] for row in runtime.state_payload()["ministers"]}
        db.conn.execute("UPDATE characters SET power_id='ming' WHERE name=?", (character.name,))
        db.conn.commit()
        character.power_id = "houjin"
        assert character.name in {row["name"] for row in runtime.state_payload()["ministers"]}

        # The live admission consumer rejects ineligible identities before writing a summons.
        for name in ("史可法", "朱常洵", "皇太极"):
            ch = runtime.content.characters[name]
            db.add_character(state, ch, source="admission setup")
            db.set_character_status(state, name, "active", "admission setup")
            before = db.conn.execute("SELECT COUNT(*) FROM story_ledger_entries").fetchone()[0]
            decision = runtime.session.consume_audience_admission(ch, origin_id="roster-admission")
            assert decision.result is None
            assert decision.allowed is False
            assert db.conn.execute("SELECT COUNT(*) FROM story_ledger_entries").fetchone()[0] == before
        consort = next(ch for ch in runtime.content.characters.values() if ch.office_type == "后宫" and ch.power_id == "ming")
        db.add_character(state, consort, source="admission setup")
        db.conn.execute("UPDATE characters SET status='active', location='beizhili', transit_to='' WHERE name=?", (consort.name,))
        db.conn.commit()
        assert runtime.session.consume_audience_admission(consort, origin_id="consort-admission").allowed is True
    finally:
        runtime.session.close()


@pytest.mark.parametrize("name, rejected", [("史宪之", False), ("福王", True)])
def test_alias_appointment_reuses_identity_and_rejects_vassal(game, name, rejected):
    db, state, content = game
    before = {row[0] for row in db.conn.execute("SELECT name FROM characters")}
    result = apply_office_appointment(
        db, state, content, name, "兵部职方司主事", new_office_type="兵部", reason="alias appointment",
    )
    assert bool(result.get("rejected")) is rejected
    assert {row[0] for row in db.conn.execute("SELECT name FROM characters")} == before
    if not rejected:
        assert result["name"] == "史可法"
        assert db.get_character_status("史可法")[0] == "active"
        assert db.conn.execute("SELECT office FROM characters WHERE name='史可法'").fetchone()[0] == "兵部职方司主事"
