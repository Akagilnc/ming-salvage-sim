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
    by_name = {row["name"]: row for row in rows}
    for row in rows:
        assert row["office_type"] == "六科"
    # 在朝给事中有现职；未登场者 office 空，职衔在 status_reason（seed 不解析造历史职）。
    assert "给事中" in by_name["许誉卿"]["office"]
    assert by_name["许誉卿"]["status"] == "active"
    assert by_name["韩一良"]["status"] == "offstage"
    assert by_name["韩一良"]["office"] == ""
    assert by_name["韩一良"]["debut_year"] == 1628
    reason = db.conn.execute(
        "SELECT status_reason FROM characters WHERE name='韩一良'"
    ).fetchone()["status_reason"]
    assert "给事中" in reason

    before = db._faction_office_weight_sum("中立")
    assert state.year == 1627
    assert db.apply_historical_debuts(state) == []
    assert db._faction_office_weight_sum("中立") == before

    state.year = 1628
    debuted = db.apply_historical_debuts(state)
    assert any(item["name"] == "韩一良" for item in debuted)
    assert db.get_character_status("韩一良")[0] == "active"
    # 登场只改 status；不把 status_reason 写回 office，故派系职权重不变。
    assert db._faction_office_weight_sum("中立") == before
    office = db.conn.execute(
        "SELECT office FROM characters WHERE name='韩一良'"
    ).fetchone()["office"]
    assert office == ""
