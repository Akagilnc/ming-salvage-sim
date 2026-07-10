"""#608：六科官署与言官 seed。"""

from __future__ import annotations

from ming_sim.db import _OFFICE_LEVERAGE_WEIGHT, infer_office_type_from_office


def test_six_sciences_offices_infer_to_own_category():
    """六科、给事中和都给事中均确定性归入六科。"""
    assert infer_office_type_from_office("六科") == "六科"
    assert infer_office_type_from_office("兵科给事中") == "六科"
    assert infer_office_type_from_office("礼科都给事中") == "六科"
    assert _OFFICE_LEVERAGE_WEIGHT["六科"] == _OFFICE_LEVERAGE_WEIGHT["都察院"]


def test_fresh_seed_contains_sourced_six_sciences_censors(game):
    """开局名册有两名史实给事中，并保留可追溯的史料出处。"""
    db, _state, content = game
    names = {"许誉卿", "韩一良"}

    assert names <= set(content.characters)
    rows = db.conn.execute(
        "SELECT name, office, office_type, status, summary FROM characters "
        "WHERE name IN (?, ?) ORDER BY name",
        tuple(sorted(names)),
    ).fetchall()

    assert len(rows) == 2
    for row in rows:
        assert row["status"] == "active"
        assert row["office_type"] == "六科"
        assert "给事中" in row["office"]
        assert "《明史》卷258" in row["summary"]


def test_six_sciences_censor_exit_recomputes_its_faction_leverage(game, monkeypatch):
    """TD-6：给事中退场仍经过 #9 的派系权势重算链。"""
    db, state, _content = game
    censor = db.conn.execute(
        "SELECT name, faction FROM characters WHERE name='许誉卿'"
    ).fetchone()
    assert censor is not None

    calls: list[str] = []
    monkeypatch.setattr(db, "recompute_faction_leverage", lambda faction: calls.append(faction))

    db.set_character_status(state, censor["name"], "dismissed", reason="测试退场")

    assert calls == [censor["faction"]]
