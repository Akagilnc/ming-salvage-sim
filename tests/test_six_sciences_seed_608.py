"""#608：六科官署与言官 seed。"""

from __future__ import annotations

from ming_sim.db import infer_office_type_from_office


def test_six_sciences_offices_infer_to_own_category():
    """六科、给事中和都给事中均确定性归入六科。"""
    assert infer_office_type_from_office("六科") == "六科"
    assert infer_office_type_from_office("兵科给事中") == "六科"
    assert infer_office_type_from_office("礼科都给事中") == "六科"


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
