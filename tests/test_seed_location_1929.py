from __future__ import annotations
"""#1929：徐光启、毕自严开局南直隶 → 既有传召/起复自然赶路。

种子地点契约由 #670 test_fresh_seed_closes_ticket_670_named_locations 维护；
本文件只验票面两条行为：毕自严开局宣召路程，徐光启召对起复后宣召。

Seams:
- GameSession.admit_audience / consume_audience_admission
- audience_night.close_night（传召启程）
- resolve_turn 空月链（过月推进行程）
- scene_chat 交办/应允 → close_night → 月链颁布（起复真实入口）
"""

from pathlib import Path

import pytest

from ming_sim import audience_night as an
from ming_sim.distance import DistanceMatrix
from ming_sim.session import AudienceAdmission
from tests.readback_helpers import active_character_name as _minister
from tests.test_audience_tenure_authority_1912 import (
    _approve_pending,
    _close_current_night,
    _dossier_for_pending,
    _staged_commission_id,
)
from tests.test_audience_translate_1837_reopen import (
    _player_month,
    _scene_declaration,
)
from tests.test_audience_travel_gating_670 import _session
from tests.test_due_review_621 import _settle_empty_month

ROOT = Path(__file__).resolve().parents[1]
MATRIX = DistanceMatrix.from_file(ROOT / "content/distance_matrix.json")
NANZHILI_TO_CAPITAL = MATRIX.travel_time("nanzhili", "beizhili")


def _ledger(db, name: str) -> dict:
    row = db.conn.execute(
        "SELECT location, transit_to, transit_distance_remaining, status "
        "FROM characters WHERE name=?",
        (name,),
    ).fetchone()
    return {
        "location": row["location"],
        "transit_to": row["transit_to"],
        "remaining": row["transit_distance_remaining"],
        "status": row["status"],
    }


def test_bi_ziyan_summon_travels_nanzhili_distance_then_admits(game, monkeypatch):
    """开局宣毕自严：传召启程；过月按南直隶→京师距离扣程，到期抵京后可入对。"""
    db, state, content = game
    sess = _session(game)
    person = content.characters["毕自严"]
    assert _ledger(db, "毕自严")["location"] == "nanzhili"

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

    depart_turn = int(state.turn)
    closed = an.close_night(db, state, night_id=night_id, content=content)
    assert closed["closed"] is True
    after_depart = _ledger(db, "毕自严")
    assert after_depart["location"] == "nanzhili"
    assert after_depart["transit_to"] == "beizhili"
    assert after_depart["remaining"] == pytest.approx(NANZHILI_TO_CAPITAL)
    assert an.list_unsettled_summons(db)[0]["kind"] == "in_transit"

    # 0095 F2：启程当月只落账不减；次月起每月 step=1.0。r0=1.6 → 两步抵京。
    assert NANZHILI_TO_CAPITAL == pytest.approx(1.6)
    step = 1.0
    assert int(state.turn) == depart_turn

    # 启程同月的第一次过月：pre_settle 仍见 start_turn==turn，不扣程。
    _settle_empty_month(db, state, content, monkeypatch)
    assert int(state.turn) == depart_turn + 1
    same_month = _ledger(db, "毕自严")
    assert same_month["location"] == "nanzhili"
    assert same_month["transit_to"] == "beizhili"
    assert same_month["remaining"] == pytest.approx(NANZHILI_TO_CAPITAL)

    # 次月首减：1.6 → 0.6，仍在途。
    _settle_empty_month(db, state, content, monkeypatch)
    mid = _ledger(db, "毕自严")
    assert mid["location"] == "nanzhili"
    assert mid["transit_to"] == "beizhili"
    assert mid["remaining"] == pytest.approx(NANZHILI_TO_CAPITAL - step)

    # 再一月：0.6 → ≤0，抵京。
    _settle_empty_month(db, state, content, monkeypatch)
    arrived = _ledger(db, "毕自严")
    assert arrived["location"] == "beizhili"
    assert arrived["transit_to"] == ""
    assert arrived["remaining"] is None

    final = sess.admit_audience(content.characters["毕自严"])
    assert final.result is AudienceAdmission.IN_CAPITAL
    assert final.allowed is True


def test_xu_guangqi_reinstated_via_audience_then_summon_travels(game, monkeypatch):
    """召对起复徐光启 → 月链颁布生效 → 宣他：仍在南直隶，传召启程。"""
    db, state, content = game
    sess = _session(game)
    name = "徐光启"
    assert _ledger(db, name)["location"] == "nanzhili"
    assert _ledger(db, name)["status"] != "active"

    blocked = sess.admit_audience(content.characters[name])
    assert blocked.result is None
    assert blocked.allowed is False

    minister = _minister(db)
    staged = _scene_declaration(
        db, state, content, monkeypatch,
        f"起复{name}为礼部右侍郎。",
        {
            "commissions": [{
                "text": f"起复{name}为礼部右侍郎",
                "appointment": {
                    "name": name,
                    "office": "礼部右侍郎",
                    "appoint_action": "任命",
                },
            }],
        },
        minister_name=minister,
    )
    pending_id = _staged_commission_id(staged)
    _approve_pending(db, state, content, monkeypatch, pending_id, minister=minister)
    _close_current_night(db, state, content)
    dossier = _dossier_for_pending(db, pending_id)

    # 收夜成案后、月链颁布前：仍 offstage，不可宣。
    pre = _ledger(db, name)
    assert pre["status"] != "active"
    assert pre["location"] == "nanzhili"
    still_blocked = sess.admit_audience(content.characters[name])
    assert still_blocked.result is None

    _player_month(db, state, content, monkeypatch, int(dossier["id"]))
    after = _ledger(db, name)
    assert after["status"] == "active"
    assert after["location"] == "nanzhili"
    assert after["transit_to"] == ""

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
    departed = _ledger(db, name)
    assert departed["location"] == "nanzhili"
    assert departed["transit_to"] == "beizhili"
    assert departed["remaining"] == pytest.approx(NANZHILI_TO_CAPITAL)
