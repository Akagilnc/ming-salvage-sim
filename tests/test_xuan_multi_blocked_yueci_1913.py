from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from ming_sim.audience_night import (
    METHOD_XUANRU,
    METHOD_YUECI,
    TAG_ENTER,
    get_open_night,
    list_ledger,
    list_unsettled_summons,
    open_night,
    present_names_at,
)
from ming_sim.db import GameDB
from ming_sim.materials import _safe_segment, list_materials
from ming_sim.session import GameSession
from ming_sim.session_write_queue import SessionWriteQueue

"""#1913：一口宣多人、拒召供料、越次召见记账。

Seams:
- GameSession.scene_chat（真实召对入口「宣…」）
- 入殿／传召账（list_ledger / list_unsettled_summons / present_names_at）
- create_scene_agent 收到的 PreparedMaterials（场景调用边界，非事后另 prepare）
- 存档重开后 list_ledger 召法 tag
"""


def _sess(db, state, content, monkeypatch, *, capture_prepared=None):
    class FakeAgent:
        tools = []

        def run(self, message):
            return SimpleNamespace(content="臣等遵旨。", tools=[])

    def _factory(llm_config, prepared, **kwargs):
        if capture_prepared is not None:
            capture_prepared.append(prepared)
        return FakeAgent()

    monkeypatch.setattr("ming_sim.session.create_scene_agent", _factory)
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.llm_config = SimpleNamespace(channel="")
    sess.agno_db = None
    sess._write_queue = SessionWriteQueue()
    sess._write_gate = sess._write_queue.write_gate
    return sess


def _enter_methods(db, night_id: int, person: str) -> list[str]:
    methods: list[str] = []
    for entry in list_ledger(db, night_id):
        tags = entry.get("tags") or []
        if TAG_ENTER not in tags:
            continue
        if "常在员额" in tags:
            continue
        if person not in (entry.get("person_names") or []):
            continue
        for tag in tags:
            if tag in {METHOD_XUANRU, METHOD_YUECI, "传召"}:
                methods.append(tag)
    return methods


def _summon_ledger_tags_for(db, person: str) -> list[str]:
    tags_out: list[str] = []
    for row in list_unsettled_summons(db):
        if row["person_name"] != person:
            continue
        entry = next(
            (e for e in list_ledger(db, int(row["night_id"])) if int(e["id"]) == int(row["entry_id"])),
            None,
        )
        if entry is not None:
            tags_out.extend(entry.get("tags") or [])
    return tags_out


def _blocked_facts_from_opening(opening: str) -> list[dict]:
    facts: list[dict] = []
    for line in str(opening or "").splitlines():
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("kind") == "summon_blocked":
            facts.append(payload)
    return facts


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_xuan_two_in_capital_both_enter_with_materials(game, monkeypatch):
    """「宣甲、乙」二人均可即时入殿：均记入殿；场景调用边界材料目录各备。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(get_open_night(db)["id"])
    a, b = "毕自严", "王绍徽"

    prepared_box: list = []
    sess = _sess(db, state, content, monkeypatch, capture_prepared=prepared_box)
    sess.scene_chat(f"宣{a}、{b}", write_gate=sess._write_gate)

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
    """「宣甲、丙」丙在京外：甲入殿，丙记传召不入殿。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(get_open_night(db)["id"])
    capital, remote = "毕自严", "洪承畴"

    sess = _sess(db, state, content, monkeypatch)
    sess.scene_chat(f"宣{capital}、{remote}", write_gate=sess._write_gate)

    assert capital in present_names_at(db, night_id)
    assert remote not in present_names_at(db, night_id)
    unsettled = {
        row["person_name"]: row["kind"] for row in list_unsettled_summons(db)
    }
    assert unsettled.get(remote) in {"fresh", "in_transit"}
    assert capital not in unsettled


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_xuan_blocked_offstage_feeds_materials_not_enter(game, monkeypatch):
    """宣尚未起复者：场景材料含结构化拒召事实（含 reason）；未记入殿。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(get_open_night(db)["id"])
    person = "徐光启"
    status, _ = db.characters.get_character_status(person)
    assert status != "active"

    prepared_box: list = []
    sess = _sess(db, state, content, monkeypatch, capture_prepared=prepared_box)
    sess.scene_chat(f"宣{person}", write_gate=sess._write_gate)

    assert person not in present_names_at(db, night_id)
    assert not _enter_methods(db, night_id, person)

    assert prepared_box
    blocked = _blocked_facts_from_opening(prepared_box[0].opening)
    hit = [fact for fact in blocked if fact.get("person_name") == person]
    assert hit, f"summon_blocked fact missing:\n{prepared_box[0].opening}"
    reason = str(hit[0].get("reason") or "").strip()
    assert reason, "blocked fact must carry a non-empty structured reason"


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_yueci_explicit_lands_method_and_survives_reopen(game, monkeypatch, tmp_path):
    """越次点名：召见方式为越次；关库重开仍可读。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(get_open_night(db)["id"])
    person = "杨嗣昌"

    sess = _sess(db, state, content, monkeypatch)
    sess.scene_chat(f"越次宣{person}", write_gate=sess._write_gate)

    methods = _enter_methods(db, night_id, person)
    assert METHOD_YUECI in methods
    assert METHOD_XUANRU not in methods

    db.conn.commit()
    copy_path = Path(tmp_path) / "reopen.db"
    shutil.copyfile(db.path, copy_path)
    restored = GameDB(str(copy_path), content)
    try:
        methods_after = _enter_methods(restored, night_id, person)
        assert METHOD_YUECI in methods_after
    finally:
        restored.conn.close()


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_ordinary_xuan_low_rank_is_xuanru_not_yueci(game, monkeypatch):
    """普通「宣某人」品级低但未以越次点名：记宣入，不记越次。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(get_open_night(db)["id"])
    person = "杨嗣昌"

    sess = _sess(db, state, content, monkeypatch)
    sess.scene_chat(f"宣{person}", write_gate=sess._write_gate)

    methods = _enter_methods(db, night_id, person)
    assert METHOD_XUANRU in methods
    assert METHOD_YUECI not in methods


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_xuan_alias_containing_he_not_split(game, monkeypatch):
    """在册别名「懋和」整段匹配，不被「和」切开。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    person = "朱燮元"
    # 别名「懋和」；场外以便落传召账可观察
    db.conn.execute(
        "UPDATE characters SET location=? WHERE name=?",
        ("sichuan", person),
    )
    db.conn.commit()

    sess = _sess(db, state, content, monkeypatch)
    sess.scene_chat("宣懋和", write_gate=sess._write_gate)

    unsettled = [row for row in list_unsettled_summons(db) if row["person_name"] == person]
    assert unsettled, "alias 懋和 must resolve to 朱燮元 and record summons"


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_yueci_remote_method_lands_on_summon_ledger(game, monkeypatch):
    """越次点名京外：传召账保留越次召法，同时仍是传召分流。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(get_open_night(db)["id"])
    remote = "洪承畴"

    sess = _sess(db, state, content, monkeypatch)
    sess.scene_chat(f"越次点名{remote}", write_gate=sess._write_gate)

    assert remote not in present_names_at(db, night_id)
    unsettled = [row for row in list_unsettled_summons(db) if row["person_name"] == remote]
    assert unsettled and unsettled[0]["kind"] in {"fresh", "in_transit"}
    tags = _summon_ledger_tags_for(db, remote)
    assert METHOD_YUECI in tags
