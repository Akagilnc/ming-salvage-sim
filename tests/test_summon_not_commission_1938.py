from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import ming_sim.audience_translate as audience_translate
from ming_sim.audience_night import (
    METHOD_CHUANZHAO,
    METHOD_XUANRU,
    METHOD_YUECI,
    get_open_night,
    list_ledger,
    list_unsettled_summons,
    open_night,
    present_names_at,
)
from ming_sim.session_write_queue import get_session_write_queue
from tests.conftest import persist_and_schedule_scene
from tests.test_audience_travel_gating_670 import _set_place
from tests.test_scene_llm_1836 import _sess as _base_scene_sess

"""#1938：宣召口令已由引擎落账 → 转译输入侧可见，不得再成交办。

Seams:
- build_engine_summon_landings（本轮引擎宣召事实）
- build_audience_translate_prompt / run_turn_translation_job（转译输入）
- GameSession.scene_chat（真实召对入口：宣入／传召／越次）
- list_ledger / list_unsettled_summons / pending_actions（落账与暂存）
"""


def _sess(db, state, content, monkeypatch, *, capture_prompt=None):
    class FakeAgent:
        tools = []

        def run(self, message):
            return SimpleNamespace(content="臣等遵旨。", tools=[])

    monkeypatch.setattr(
        "ming_sim.session.create_scene_agent",
        lambda *a, **k: FakeAgent(),
    )
    sess = _base_scene_sess(db, state, content, llm_config=SimpleNamespace(channel=""))
    if capture_prompt is not None:
        real_build = audience_translate.build_audience_translate_prompt

        def _capture(**kwargs):
            capture_prompt.append(dict(kwargs))
            return real_build(**kwargs)

        monkeypatch.setattr(
            audience_translate, "build_audience_translate_prompt", _capture,
        )
    return sess


def _landing_rows(captured: list) -> list[dict]:
    assert captured, "转译须收到一次 prompt 构造"
    raw = captured[-1].get("engine_summon_landings") or ()
    rows = []
    for item in raw:
        rows.append(json.loads(item) if isinstance(item, str) else dict(item))
    return rows


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_xuanru_feeds_engine_summon_into_translate_input(game, monkeypatch):
    """宣入：杨嗣昌入殿；转译输入含本轮引擎已落账事实。"""
    db, state, content = game
    _set_place(game, "杨嗣昌", location="beizhili")
    open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(get_open_night(db)["id"])
    captured: list = []
    sess = _sess(db, state, content, monkeypatch, capture_prompt=captured)

    ctid = db.create_chat_turn(
        state, "殿上", "1938:xuanru", 0, night_id=night_id, status="generating",
    )
    result = sess.scene_chat(
        "宣杨嗣昌", chat_turn_id=ctid, write_gate=sess._write_gate,
    )
    fut = persist_and_schedule_scene(sess, db, result)
    if fut is not None:
        fut.result(timeout=30)
    assert get_session_write_queue(sess).wait_idle()

    assert "杨嗣昌" in present_names_at(db, night_id)
    rows = _landing_rows(captured)
    assert any(
        r.get("kind") == "engine_summon_landed"
        and r.get("person_name") == "杨嗣昌"
        and r.get("method") == METHOD_XUANRU
        for r in rows
    ), rows
    prompt = audience_translate.build_audience_translate_prompt(
        emperor_message="宣杨嗣昌",
        reply="臣等遵旨。",
        night_said=(),
        pending_summaries=(),
        engine_summon_landings=captured[-1].get("engine_summon_landings") or (),
    )
    assert "engine_summon_landed" in prompt
    assert "杨嗣昌" in prompt
    # 应允前：离线转译无交办；真实入口暂存不得以宣召为正文。
    pending = db.conn.execute(
        "SELECT id, payload_json FROM pending_actions WHERE turn=?",
        (int(state.turn),),
    ).fetchall()
    for row in pending:
        payload = json.loads(row["payload_json"] or "{}")
        text = str(payload.get("text") or "")
        assert text.strip() != "宣杨嗣昌", (row["id"], payload)


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_chuanzhao_and_yueci_feed_engine_summon_not_commission(game, monkeypatch):
    """传召（在外）与越次点名：账照落；转译输入含引擎事实；无宣召正文交办。"""
    db, state, content = game
    _set_place(game, "毕自严", location="shaanxi")  # 在外 → 传召
    _set_place(game, "杨嗣昌", location="beizhili")
    open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(get_open_night(db)["id"])

    # ── 传召 ──
    captured_chuan: list = []
    sess = _sess(db, state, content, monkeypatch, capture_prompt=captured_chuan)
    ctid_c = db.create_chat_turn(
        state, "殿上", "1938:chuan", 0, night_id=night_id, status="generating",
    )
    result_c = sess.scene_chat(
        "宣毕自严", chat_turn_id=ctid_c, write_gate=sess._write_gate,
    )
    fut = persist_and_schedule_scene(sess, db, result_c)
    if fut is not None:
        fut.result(timeout=30)
    assert get_session_write_queue(sess).wait_idle()

    unsettled = [
        r for r in list_unsettled_summons(db) if r["person_name"] == "毕自严"
    ]
    assert unsettled, "在外宣召须落传召未结账"
    chuan_rows = _landing_rows(captured_chuan)
    assert any(
        r.get("person_name") == "毕自严"
        and r.get("method") in {METHOD_CHUANZHAO, METHOD_YUECI}
        for r in chuan_rows
    ), chuan_rows

    # ── 越次 ──
    captured_yue: list = []
    real_build = audience_translate.build_audience_translate_prompt

    def _cap(**kwargs):
        captured_yue.append(dict(kwargs))
        return real_build(**kwargs)

    monkeypatch.setattr(audience_translate, "build_audience_translate_prompt", _cap)
    ctid_y = db.create_chat_turn(
        state, "殿上", "1938:yueci", 0, night_id=night_id, status="generating",
    )
    result_y = sess.scene_chat(
        "越次宣杨嗣昌", chat_turn_id=ctid_y, write_gate=sess._write_gate,
    )
    fut = persist_and_schedule_scene(sess, db, result_y)
    if fut is not None:
        fut.result(timeout=30)
    assert get_session_write_queue(sess).wait_idle()

    assert "杨嗣昌" in present_names_at(db, night_id)
    yue_methods = []
    for entry in list_ledger(db, night_id):
        if "杨嗣昌" not in (entry.get("person_names") or []):
            continue
        if int(entry.get("origin_chat_turn_id") or 0) != int(ctid_y):
            continue
        yue_methods.extend(
            t for t in (entry.get("tags") or []) if t == METHOD_YUECI
        )
    assert yue_methods, "越次点名须留 METHOD_YUECI 账"
    yue_rows = _landing_rows(captured_yue)
    assert any(
        r.get("person_name") == "杨嗣昌" and r.get("method") == METHOD_YUECI
        for r in yue_rows
    ), yue_rows

    pending = db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE turn=?",
        (int(state.turn),),
    ).fetchall()
    for row in pending:
        payload = json.loads(row["payload_json"] or "{}")
        text = str(payload.get("text") or "").strip()
        assert text not in {"宣毕自严", "越次宣杨嗣昌", "宣杨嗣昌"}, payload


def test_build_engine_summon_landings_ignores_other_turns_and_roster(game):
    """只认本轮 origin 的口令宣召；常在员额与他轮不入。"""
    db, state, _content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    ctid = db.create_chat_turn(
        state, "殿上", "1938:iso", 0, night_id=night_id, status="active",
    )
    from ming_sim.audience_night import summon_enter
    summon_enter(
        db, night_id, "杨嗣昌",
        method=METHOD_XUANRU, origin_chat_turn_id=ctid,
    )
    other = db.create_chat_turn(
        state, "殿上", "1938:other", 0, night_id=night_id, status="active",
    )
    summon_enter(
        db, night_id, "毕自严",
        method=METHOD_XUANRU, origin_chat_turn_id=other,
    )

    rows = [
        json.loads(s)
        for s in audience_translate.build_engine_summon_landings(
            db, night_id, chat_turn_id=ctid,
        )
    ]
    names = {r["person_name"] for r in rows}
    assert names == {"杨嗣昌"}
    assert all(r["kind"] == "engine_summon_landed" for r in rows)
    assert all(r["method"] == METHOD_XUANRU for r in rows)
