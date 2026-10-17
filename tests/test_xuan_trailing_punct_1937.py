from __future__ import annotations

import json

import pytest

from ming_sim.audience_night import (
    get_open_night,
    list_unsettled_summons,
    open_night,
    present_names_at,
)
import ming_sim.session as session_mod

from tests.test_xuan_multi_blocked_yueci_1913 import _enter_methods, _sess

"""#1937：宣召口令句末标点不改变落账结果。

Seams:
- GameSession.scene_chat（真实召对入口「宣…」）
- 入殿／传召账（present_names_at / list_unsettled_summons）
- prepare_scene_materials.extra_pending_facts（拒召供料接缝）
"""


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_xuan_trailing_period_enters_yangsichang(game, monkeypatch):
    """新开局输入「宣杨嗣昌。」：杨嗣昌当场入殿，本夜在场名单含之。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(get_open_night(db)["id"])
    person = "杨嗣昌"

    sess = _sess(db, state, content, monkeypatch)
    sess.scene_chat(f"宣{person}。", write_gate=sess._write_gate)

    assert person in present_names_at(db, night_id)
    assert _enter_methods(db, night_id, person)


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_xuan_trailing_period_mixed_targets_split(game, monkeypatch):
    """「宣杨嗣昌、毕自严。」：杨嗣昌入殿；毕自严在南直隶，传召赶路。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(get_open_night(db)["id"])
    capital, remote = "杨嗣昌", "毕自严"

    row = db.characters.row(remote, fields="location")
    assert row is not None
    remote_loc = str(row["location"] or "").strip()
    assert remote_loc and remote_loc != "beizhili", (
        f"fixture {remote} must be outside capital for mixed-target AC; got {remote_loc!r}"
    )

    sess = _sess(db, state, content, monkeypatch)
    sess.scene_chat(f"宣{capital}、{remote}。", write_gate=sess._write_gate)

    assert capital in present_names_at(db, night_id)
    assert remote not in present_names_at(db, night_id)
    unsettled = {
        row["person_name"]: row["kind"] for row in list_unsettled_summons(db)
    }
    assert unsettled.get(remote) in {"fresh", "in_transit"}
    assert capital not in unsettled


@pytest.mark.usefixtures("_offline_scene_beat_generator")
@pytest.mark.parametrize("message", ["宣徐光启！", "宣徐光启"])
def test_xuan_trailing_bang_blocked_offstage_same_as_bare(game, monkeypatch, message):
    """「宣徐光启！」与「宣徐光启」同：不入殿，本场材料含被拦事实与原因。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(get_open_night(db)["id"])
    person = "徐光启"
    status, _ = db.characters.get_character_status(person)
    assert status != "active"

    pending_facts: list[str] = []
    real_prepare = session_mod.prepare_scene_materials

    def _prepare(db_, state_, *, dest_root=None, extra_pending_facts=()):
        pending_facts.extend(str(f) for f in extra_pending_facts if str(f or "").strip())
        return real_prepare(
            db_, state_, dest_root=dest_root, extra_pending_facts=extra_pending_facts,
        )

    monkeypatch.setattr(session_mod, "prepare_scene_materials", _prepare)

    sess = _sess(db, state, content, monkeypatch)
    decision = sess.admit_audience(content.characters[person])
    assert decision.result is None
    expected_reason = str(decision.reason or "").strip()
    assert expected_reason

    sess.scene_chat(message, write_gate=sess._write_gate)

    assert person not in present_names_at(db, night_id)
    assert not _enter_methods(db, night_id, person)

    blocked = []
    for raw in pending_facts:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("kind") == "summon_blocked":
            blocked.append(payload)
    hit = [fact for fact in blocked if fact.get("person_name") == person]
    assert hit, f"summon_blocked fact missing from extra_pending_facts: {pending_facts!r}"
    assert str(hit[0].get("reason") or "") == expected_reason
