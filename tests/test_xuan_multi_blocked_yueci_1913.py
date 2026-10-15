from __future__ import annotations

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
from ming_sim.materials import _safe_segment, list_materials, prepare_scene_materials
from ming_sim.session import GameSession
from ming_sim.session_write_queue import SessionWriteQueue

"""#1913：一口宣多人、拒召供料、越次召见记账。

Seams:
- GameSession.scene_chat（真实召对入口「宣…」）
- 入殿／传召账（list_ledger / list_unsettled_summons / present_names_at）
- prepare_scene_materials 开场最小集（拒召事实，经 scene_chat 内 prepare 捕获）
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


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_xuan_two_in_capital_both_enter_with_materials(game, monkeypatch, tmp_path):
    """「宣甲、乙」二人均可即时入殿：均记入殿，首轮材料各备。"""
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

    prepared = prepare_scene_materials(db, state, dest_root=tmp_path / "both")
    mats = list_materials(prepared.root)
    assert any(p.startswith(f"人物/{_safe_segment(a)}/") for p in mats)
    assert any(p.startswith(f"人物/{_safe_segment(b)}/") for p in mats)
    assert prepared_box, "scene_chat must prepare materials before the scene call"
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
    """宣尚未起复者：材料含被拦及原因；未记入殿。"""
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
    opening = prepared_box[0].opening
    blocked_lines = [
        line for line in opening.splitlines()
        if person in line
        and ("尚未登场" in line or "无法召见" in line or "summon_blocked" in line)
    ]
    assert blocked_lines, f"blocked fact missing from opening:\n{opening}"


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
