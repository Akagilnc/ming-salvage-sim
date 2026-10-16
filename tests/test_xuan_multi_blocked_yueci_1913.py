from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from ming_sim.audience_night import (
    METHOD_XUANRU,
    METHOD_YUECI,
    get_open_night,
    list_ledger,
    list_unsettled_summons,
    open_night,
    present_names_at,
)
from ming_sim.db import GameDB
from ming_sim.materials import _safe_segment, list_materials
import ming_sim.session as session_mod

from tests.test_scene_llm_1836 import (
    _non_roster_enters,
    _scene_chat_with_turn,
    _sess as _base_scene_sess,
)

"""#1913：一口宣多人、拒召供料、越次宣召记账。

普通「宣」低品记宣入不记越次、已在场再宣不叠账：见 tests/test_scene_llm_1836.py，
不在本文件平行重跑。

Seams:
- GameSession.scene_chat（真实召对入口「宣…」）
- 入殿／传召账（list_ledger / list_unsettled_summons / present_names_at）
- prepare_scene_materials.extra_pending_facts（拒召供料接缝）
- create_scene_agent 收到的 PreparedMaterials（场景调用边界）
- 存档重开后 list_ledger 召法 tag
"""


def _sess(db, state, content, monkeypatch, *, capture_prepared=None):
    """复用 1836 轻量 GameSession 装配；本票加 fake agent／材料捕获。"""

    class FakeAgent:
        tools = []

        def run(self, message):
            return SimpleNamespace(content="臣等遵旨。", tools=[])

    def _factory(llm_config, prepared, **kwargs):
        if capture_prepared is not None:
            capture_prepared.append(prepared)
        return FakeAgent()

    monkeypatch.setattr("ming_sim.session.create_scene_agent", _factory)
    return _base_scene_sess(db, state, content, llm_config=SimpleNamespace(channel=""))


def _enter_methods(db, night_id: int, person: str) -> list[str]:
    methods: list[str] = []
    for entry in _non_roster_enters(db, night_id, person):
        for tag in entry.get("tags") or []:
            if tag in {METHOD_XUANRU, METHOD_YUECI, "传召"}:
                methods.append(tag)
    return methods


def _unsettled_entry_tags(db, person: str) -> list[str]:
    for row in list_unsettled_summons(db):
        if row["person_name"] != person:
            continue
        for entry in list_ledger(db, int(row["night_id"])):
            if int(entry["id"]) == int(row["entry_id"]):
                return list(entry.get("tags") or [])
    return []


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_xuan_two_in_capital_both_enter_with_materials(game, monkeypatch):
    """「宣甲来、乙」二人均可即时入殿：均记入殿；场景调用边界材料目录各备。

    甲带语气尾、乙名以「来」结尾——覆盖整串预剥会截坏身份、逐人须先全名再试尾的接缝。
    """
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(get_open_night(db)["id"])
    a, b = "毕自严", "施凤来"

    prepared_box: list = []
    sess = _sess(db, state, content, monkeypatch, capture_prepared=prepared_box)
    sess.scene_chat(f"宣{a}来、{b}", write_gate=sess._write_gate)

    assert a in present_names_at(db, night_id)
    assert b in present_names_at(db, night_id)
    assert _enter_methods(db, night_id, a)
    assert _enter_methods(db, night_id, b)

    assert prepared_box, "scene_chat must hand prepared materials to the scene agent"
    mats = list_materials(prepared_box[0].root)
    assert any(p.startswith(f"人物/{_safe_segment(a)}/") for p in mats)
    assert any(p.startswith(f"人物/{_safe_segment(b)}/") for p in mats)
    opening = prepared_box[0].opening
    assert a in opening and b in opening


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_xuan_capital_and_remote_splits_enter_and_summon(game, monkeypatch):
    """「宣甲、乙」乙为合法别名且在京外：甲入殿，别名主体记传召不入殿。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(get_open_night(db)["id"])
    capital = "毕自严"
    # 懋和 = 朱燮元别名（含「和」）；开局在贵州，走传召分流。
    remote_alias, remote_name = "懋和", "朱燮元"

    sess = _sess(db, state, content, monkeypatch)
    sess.scene_chat(f"宣{capital}、{remote_alias}", write_gate=sess._write_gate)

    assert capital in present_names_at(db, night_id)
    assert remote_name not in present_names_at(db, night_id)
    unsettled = {
        row["person_name"]: row["kind"] for row in list_unsettled_summons(db)
    }
    assert unsettled.get(remote_name) in {"fresh", "in_transit"}
    assert capital not in unsettled


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_xuan_blocked_offstage_feeds_materials_not_enter(game, monkeypatch):
    """宣尚未起复者：供料接缝收到结构化拒召事实（含真实 reason）；未记入殿。"""
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
    # 与生产 scene_chat 同一资格闸：预期 reason 必须原样进供料，不能只验非空。
    decision = sess.admit_audience(content.characters[person])
    assert decision.result is None
    expected_reason = str(decision.reason or "").strip()
    assert expected_reason, "fixture person must be blocked with a concrete reason"

    sess.scene_chat(f"宣{person}", write_gate=sess._write_gate)

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


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_yueci_explicit_lands_method_and_survives_reopen(game, monkeypatch, tmp_path):
    """越次宣召：完整复合前缀不截身份；在京记入殿越次；京外记传召账越次；已在场仍留越次；同轮恢复不叠账；关库重开仍可读。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(get_open_night(db)["id"])
    capital, remote = "杨嗣昌", "洪承畴"
    standing = "王承恩"
    assert standing in present_names_at(db, night_id)

    sess = _sess(db, state, content, monkeypatch)

    def _scene(msg: str, *, chat_turn_id: int = 0) -> int:
        return _scene_chat_with_turn(
            sess, db, state, night_id, msg,
            chat_turn_id=chat_turn_id, label="xuan-1913",
        )

    def _enter_ids(person: str) -> list[int]:
        return [int(entry["id"]) for entry in _non_roster_enters(db, night_id, person)]

    # 复合「宣召」须整词匹配；短前缀「宣」会把身份截成「召…」。
    _scene(f"越次宣召{capital}、{remote}")

    methods = _enter_methods(db, night_id, capital)
    assert METHOD_YUECI in methods
    assert METHOD_XUANRU not in methods
    assert capital in present_names_at(db, night_id)

    assert remote not in present_names_at(db, night_id)
    unsettled = [row for row in list_unsettled_summons(db) if row["person_name"] == remote]
    assert unsettled and unsettled[0]["kind"] in {"fresh", "in_transit"}
    assert METHOD_YUECI in _unsettled_entry_tags(db, remote)

    # 已在场·常在员额：越次点名仍记召法；同轮恢复重试复用，不新增入殿。
    # 普通宣不叠账见 test_scene_llm_1836，不在此重复。
    yueci_msg = f"越次点名{standing}"
    yueci_ctid = _scene(yueci_msg)
    standing_ids = _enter_ids(standing)
    assert METHOD_YUECI in _enter_methods(db, night_id, standing)
    assert standing in present_names_at(db, night_id)
    _scene(yueci_msg, chat_turn_id=yueci_ctid)
    assert _enter_ids(standing) == standing_ids

    # 已在场·先普通宣入再越次：保留宣入，另留越次账；同轮恢复复用。
    # 重复普通宣不叠加见 test_scene_llm_1836，不在此重复。
    prior = "毕自严"
    _scene(f"宣{prior}")
    assert METHOD_XUANRU in _enter_methods(db, night_id, prior)
    prior_yueci_ctid = _scene(f"越次点名{prior}")
    prior_ids = _enter_ids(prior)
    prior_methods = _enter_methods(db, night_id, prior)
    assert METHOD_XUANRU in prior_methods
    assert METHOD_YUECI in prior_methods
    _scene(f"越次点名{prior}", chat_turn_id=prior_yueci_ctid)
    assert _enter_ids(prior) == prior_ids

    db.conn.commit()
    copy_path = Path(tmp_path) / "reopen.db"
    shutil.copyfile(db.path, copy_path)
    restored = GameDB(str(copy_path), content)
    try:
        assert METHOD_YUECI in _enter_methods(restored, night_id, capital)
        assert METHOD_YUECI in _unsettled_entry_tags(restored, remote)
        assert METHOD_YUECI in _enter_methods(restored, night_id, standing)
        restored_prior = _enter_methods(restored, night_id, prior)
        assert METHOD_XUANRU in restored_prior
        assert METHOD_YUECI in restored_prior
    finally:
        restored.conn.close()
