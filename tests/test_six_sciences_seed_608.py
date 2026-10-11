"""#608：六科官署与言官 seed。"""

from __future__ import annotations


def test_fresh_seed_contains_sourced_six_sciences_censors(game):
    """许誉卿开局在朝；韩一良至 1628 年才以户科给事中登场。"""
    db, state, content = game
    names = {"许誉卿", "韩一良"}

    assert names <= set(content.characters)
    rows = db.conn.execute(
        "SELECT name, office, office_type, status, debut_year, summary FROM characters "
        "WHERE name IN (?, ?) ORDER BY name",
        tuple(sorted(names)),
    ).fetchall()

    assert len(rows) == 2
    for row in rows:
        assert row["office_type"] == "六科"

    by_name = {row["name"]: row for row in rows}
    assert by_name["许誉卿"]["status"] == "active"
    assert by_name["韩一良"]["status"] == "offstage"
    assert by_name["韩一良"]["debut_year"] == 1628

    assert state.year == 1627
    assert db.apply_historical_debuts(state) == []

    state.year = 1628
    debuted = db.apply_historical_debuts(state)
    assert any(item["name"] == "韩一良" for item in debuted)
    assert db.get_character_status("韩一良")[0] == "active"


def test_six_sciences_censor_exit_recomputes_its_faction_leverage(game):
    """TD-6：给事中退场更新持久派系权势；持久值与公共重算口径一致。"""
    db, state, _content = game
    censor = db.conn.execute(
        "SELECT name, faction FROM characters WHERE name='许誉卿'"
    ).fetchone()
    assert censor is not None
    db.recompute_all_faction_leverage()
    db.conn.commit()
    before = db.faction_leverage(censor["faction"])

    db.set_character_status(state, censor["name"], "dismissed", reason="测试退场")

    persisted = db.faction_leverage(censor["faction"])
    assert persisted < before
    db.recompute_all_faction_leverage()
    db.conn.commit()
    assert db.faction_leverage(censor["faction"]) == persisted
