from __future__ import annotations
"""#1929：徐光启、毕自严开局所在地 = 南直隶；既有起复/宣召/传召规则不动。

Seams:
- content/characters.json → init_db 种子
- GameSession.admit_audience / consume_audience_admission（真实召对分流）
- audience_night.close_night（传召启程）
- resolve_turn 空月链（真实过月入口推进行程）
- settle_delta 人物变更·任命（起复落账；不改所在地）
"""

from ming_sim import audience_night as an
from ming_sim.decree import tick_transit_arrivals
from ming_sim.session import AudienceAdmission, GameSession
from ming_sim.settlement import SettlementContext, settle_delta
from ming_sim.settlement.views import section
from tests.test_due_review_621 import _settle_empty_month


def _session(game) -> GameSession:
    db, _state, content = game
    sess = GameSession.__new__(GameSession)
    sess.db, sess.content = db, content
    return sess


def _travel_row(db, name: str) -> dict:
    row = db.conn.execute(
        "SELECT location, transit_to, status FROM characters WHERE name=?",
        (name,),
    ).fetchone()
    return {
        "location": row["location"],
        "transit_to": row["transit_to"],
        "status": row["status"],
    }


def test_seed_locations_match_background(game):
    db, _state, content = game
    for name in ("徐光启", "毕自严"):
        assert content.characters[name].location == "nanzhili"
        row = db.conn.execute(
            "SELECT location FROM characters WHERE name=?", (name,),
        ).fetchone()
        assert row is not None
        assert row["location"] == "nanzhili"


def test_bi_ziyan_summon_travels_from_nanzhili_then_admits(game, monkeypatch):
    """开局宣毕自严：传召赶路；过月按南直隶→京师路程到京后可入对。"""
    db, state, content = game
    sess = _session(game)
    person = content.characters["毕自严"]

    admitted = sess.admit_audience(person)
    assert admitted.result is AudienceAdmission.SUMMON_FRESH
    assert admitted.location == "nanzhili"
    assert admitted.allowed is False

    consumed = sess.consume_audience_admission(
        person, origin_id="web:1929:bi", state=state,
    )
    assert consumed.result is AudienceAdmission.SUMMON_FRESH
    unsettled = an.list_unsettled_summons(db)
    assert len(unsettled) == 1
    assert unsettled[0]["person_name"] == "毕自严"
    assert unsettled[0]["kind"] == "fresh"
    night_id = int(unsettled[0]["night_id"])

    closed = an.close_night(db, state, night_id=night_id, content=content)
    assert closed["closed"] is True
    after_depart = _travel_row(db, "毕自严")
    assert after_depart["location"] == "nanzhili"
    assert after_depart["transit_to"] == "beizhili"
    assert an.list_unsettled_summons(db)[0]["kind"] == "in_transit"

    # 南直隶→京师 r0=1.6，常行每月扣 1.0；至少两月才到。
    arrived = False
    for _ in range(4):
        _settle_empty_month(db, state, content, monkeypatch)
        row = _travel_row(db, "毕自严")
        if row["location"] == "beizhili" and not row["transit_to"]:
            arrived = True
            break
        assert row["transit_to"] == "beizhili"
        assert row["location"] == "nanzhili"
    assert arrived, f"毕自严未按路程抵京：{_travel_row(db, '毕自严')}"

    final = sess.admit_audience(content.characters["毕自严"])
    assert final.result is AudienceAdmission.IN_CAPITAL
    assert final.allowed is True


def test_xu_guangqi_reinstated_then_summon_travels_from_nanzhili(game):
    """起复徐光启后宣他：所在地仍南直隶，判传召赶路并进入在途。"""
    db, state, content = game
    sess = _session(game)
    name = "徐光启"
    person = content.characters[name]

    blocked = sess.admit_audience(person)
    assert blocked.result is None
    assert blocked.allowed is False

    applied = settle_delta(
        state,
        db,
        {
            "人物变更": [{
                "name": name,
                "origin_ref": "盘面自发",
                "动作": "任命",
                "office": "礼部右侍郎",
                "reason": "起复任事",
            }],
        },
        SettlementContext(content=content),
    )
    assert section(applied, "applied_person_changes").rejected == []
    row = _travel_row(db, name)
    assert row["status"] == "active"
    assert row["location"] == "nanzhili"
    assert row["transit_to"] == ""

    admitted = sess.admit_audience(content.characters[name])
    assert admitted.result is AudienceAdmission.SUMMON_FRESH
    assert admitted.location == "nanzhili"
    assert admitted.allowed is False

    consumed = sess.consume_audience_admission(
        content.characters[name], origin_id="web:1929:xu", state=state,
    )
    assert consumed.result is AudienceAdmission.SUMMON_FRESH
    night_id = int(an.list_unsettled_summons(db)[0]["night_id"])
    an.close_night(db, state, night_id=night_id, content=content)
    after = _travel_row(db, name)
    assert after["location"] == "nanzhili"
    assert after["transit_to"] == "beizhili"
    # 启程后仍未到：tick 不在启程当月抵达
    assert tick_transit_arrivals(db, state, content) == []
    assert _travel_row(db, name)["transit_to"] == "beizhili"
