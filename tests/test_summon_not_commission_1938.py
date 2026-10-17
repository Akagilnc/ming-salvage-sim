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
    list_unsettled_summons,
    open_night,
    present_names_at,
)
from ming_sim.session_write_queue import get_session_write_queue
from tests.conftest import persist_and_schedule_scene
from tests.test_audience_travel_gating_670 import _set_place
from tests.test_scene_llm_1836 import _sess as _base_scene_sess

"""#1938：宣召口令已由引擎落账 → 转译输入侧可见本轮结构化事实。

Seams:
- GameSession.scene_chat（真实召对入口：宣入／传召／越次）
- run_turn_translation_job → build_audience_translate_prompt（转译输入 kwargs）
- present_names_at / list_unsettled_summons（入殿／传召账）

契约：本轮 engine_summon_landings 精确反映谁被召、怎么召；他轮不串入。
真实 LLM 是否不再声明 commission 以真跑验收；离线桩不读 prompt，不在此冒充语义修复。
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
    return [
        json.loads(item) if isinstance(item, str) else dict(item)
        for item in raw
    ]


def _run_scene_turn(sess, db, state, night_id: int, message: str, *, label: str):
    ctid = db.create_chat_turn(
        state, "殿上", label, 0, night_id=night_id, status="generating",
    )
    result = sess.scene_chat(
        message, chat_turn_id=ctid, write_gate=sess._write_gate,
    )
    fut = persist_and_schedule_scene(sess, db, result)
    if fut is not None:
        fut.result(timeout=30)
    assert get_session_write_queue(sess).wait_idle()
    return ctid


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_three_summon_methods_feed_exact_engine_landings(game, monkeypatch):
    """宣入／传召／越次：账照落；转译输入 method+person 精确；后轮不串前轮。"""
    db, state, content = game
    _set_place(game, "杨嗣昌", location="beizhili")
    _set_place(game, "毕自严", location="shaanxi")  # 在外 → 传召
    open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(get_open_night(db)["id"])
    captured: list = []
    sess = _sess(db, state, content, monkeypatch, capture_prompt=captured)

    # ── 宣入 ──
    _run_scene_turn(sess, db, state, night_id, "宣杨嗣昌", label="1938:xuanru")
    assert "杨嗣昌" in present_names_at(db, night_id)
    xuan_rows = _landing_rows(captured)
    assert xuan_rows == [{
        "kind": "engine_summon_landed",
        "method": METHOD_XUANRU,
        "person_name": "杨嗣昌",
    }], xuan_rows

    # ── 传召（普通宣在外者 → METHOD_CHUANZHAO，不得宽放越次）──
    n_before = len(captured)
    _run_scene_turn(sess, db, state, night_id, "宣毕自严", label="1938:chuan")
    assert len(captured) > n_before
    unsettled = [
        r for r in list_unsettled_summons(db) if r["person_name"] == "毕自严"
    ]
    assert unsettled, "在外宣召须落传召未结账"
    chuan_rows = _landing_rows(captured)
    assert chuan_rows == [{
        "kind": "engine_summon_landed",
        "method": METHOD_CHUANZHAO,
        "person_name": "毕自严",
    }], chuan_rows
    # 本轮隔离：前轮杨嗣昌不得串入本轮供料
    assert all(r["person_name"] != "杨嗣昌" for r in chuan_rows)

    # ── 越次（在京已在场亦可留 METHOD_YUECI）──
    # 杨嗣昌已在场；越次点名仍写越次账并供料。
    n_before = len(captured)
    _run_scene_turn(sess, db, state, night_id, "越次宣杨嗣昌", label="1938:yueci")
    assert len(captured) > n_before
    yue_rows = _landing_rows(captured)
    assert yue_rows == [{
        "kind": "engine_summon_landed",
        "method": METHOD_YUECI,
        "person_name": "杨嗣昌",
    }], yue_rows
    assert all(r["person_name"] != "毕自严" for r in yue_rows)
