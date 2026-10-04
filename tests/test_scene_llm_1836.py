"""#1836 T1：一个 LLM 演整场召对。

Seams:
- prepare_scene_materials（在场诸人各一棵私有子树 + 开场最小集）
- GameSession.scene_chat（宣 X 落入殿账 → 场景调用；退朝收夜；一轮一次调用）
- 关档重开：list_chat_turns_for_night 回到最后一条持久化对话轮
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ming_sim.audience_night import (
    TAG_ENTER,
    get_night,
    get_open_night,
    list_chat_turns_for_night,
    list_ledger,
    open_night,
    present_names_at,
    summon_enter,
)
from ming_sim.materials import list_materials, prepare_scene_materials
from ming_sim.session import GameSession
from ming_sim.session_write_queue import SessionWriteQueue


def _sess(db, state, content, *, llm_config=None):
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = None
    sess.llm_config = llm_config or SimpleNamespace(channel="api")
    sess.temporary_characters = {}
    sess.agno_db = None
    sess._beat_generator = None
    sess._scene_registry = None
    sess._write_queue = SessionWriteQueue()
    sess._write_gate = sess._write_queue.write_gate
    return sess


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_scene_chat_one_call_returns_multi_person_script(game, monkeypatch):
    """AC1：一轮戏文（可含多人）出自同一次场景调用。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(get_open_night(db)["id"])
    for name in ("王绍徽", "毕自严"):
        if name not in present_names_at(db, night_id):
            summon_enter(db, night_id, name)

    script = (
        "王绍徽出列奏道：臣以为洪承畴可当一面。\n"
        "毕自严侧身插话：户部库藏尚可挪移三十万两。\n"
        "王承恩欠身低语：皇爷，此人可用。"
    )
    calls: list[str] = []

    class FakeAgent:
        tools = []

        def run(self, message):
            calls.append(message)
            return SimpleNamespace(content=script, tools=[])

    monkeypatch.setattr("ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent())
    # #1842：ctid=0 同步转译走 conftest 离线空声明缝，不另造平行 fixture。
    sess = _sess(db, state, content, llm_config=SimpleNamespace(channel=""))
    emperor = "洪承畴可堪大任？"
    result = sess.scene_chat(emperor)

    assert len(calls) == 1, "整段戏文必须出自同一次场景调用"
    # #1842：opening 已在 create_scene_agent instructions；run 输入不得再拼一份。
    assert calls[0] == emperor
    assert result.answer == script
    assert result.court_action == ""


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_xuan_lands_enter_then_present_on_next_prepare(game, monkeypatch, tmp_path):
    """AC2：「宣 X」后入殿账落下，下一次场景材料准备他在场。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    target = "王绍徽"
    night_id = int(get_open_night(db)["id"])
    # 王绍徽非常在员额，开夜后不应在场。
    assert target not in present_names_at(db, night_id)

    class FakeAgent:
        tools = []

        def run(self, message):
            return SimpleNamespace(content=f"{target}入殿叩见。", tools=[])

    monkeypatch.setattr("ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent())
    sess = _sess(db, state, content, llm_config=SimpleNamespace(channel=""))
    result = sess.scene_chat(f"宣{target}")

    # 本次宣入必须新落一条 TAG_ENTER（非常在员额开夜账）。
    enters = [
        e for e in list_ledger(db, night_id)
        if TAG_ENTER in (e.get("tags") or [])
        and target in (e.get("person_names") or [])
        and "常在员额" not in (e.get("tags") or [])
    ]
    assert enters, f"宣{target} must land a non-roster TAG_ENTER ledger entry"
    assert target in present_names_at(db, night_id)

    prepared = prepare_scene_materials(db, state, dest_root=tmp_path / "after-xuan")
    assert any(p.startswith(f"人物/{target}/") for p in list_materials(prepared.root))
    assert result.answer  # 宣后仍起一次场景调用


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_cli_selection_uses_scene_turn_as_admission_origin(game, monkeypatch):
    from ming_sim.cli.terminal import minister_chat

    db, state, content = game
    character = content.characters["王绍徽"]
    sess = _sess(db, state, content, llm_config=SimpleNamespace(channel=""))
    sess.schedule_pending_scene_translation = lambda result: None
    calls = []
    readings = []

    class FakeAgent:
        tools = []

        def run(self, message):
            calls.append(message)
            return SimpleNamespace(content="臣在。", tools=[])

    def scene_agent(_config, prepared, **_kwargs):
        readings.append(prepared.opening)
        return FakeAgent()

    monkeypatch.setattr("ming_sim.session.create_scene_agent", scene_agent)
    answers = iter(["边饷如何？", "done"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))

    assert minister_chat(sess, character, selected=True) == "dismiss"
    assert calls == [f"宣{character.name}", "边饷如何？"]
    night = get_open_night(db)
    assert night is not None
    entries = [e for e in list_ledger(db, int(night["id"])) if TAG_ENTER in e["tags"] and character.name in e["person_names"]]
    assert len(entries) == 1
    assert entries[0]["origin_chat_turn_id"] > 0
    # The next scene invocation receives the persisted first turn, not just the admission ledger.
    first = list_chat_turns_for_night(db, int(night["id"]))[0]
    reply = db.conn.execute(
        "SELECT content FROM chat_messages WHERE id=?", (first["minister_message_id"],)
    ).fetchone()["content"]
    assert reply in readings[1]


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_retire_via_scene_chat_closes_night_and_keeps_last_turn(game, monkeypatch):
    """AC3：scene_chat('退朝') 真入口收夜；同库重读最后一条持久化对话轮仍在。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])

    class FakeAgent:
        tools = []

        def run(self, message):
            return SimpleNamespace(content="众臣叩首：臣等遵旨。", tools=[])

    monkeypatch.setattr("ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent())
    sess = _sess(db, state, content, llm_config=SimpleNamespace(channel=""))

    result = sess.scene_chat("边饷如何？")
    assert result.answer
    user_mid = db.append_chat_message("殿上", state.turn, "user", "边饷如何？")
    minister_mid = db.append_chat_message("殿上", state.turn, "assistant", result.answer)
    ctid = db.create_chat_turn(
        state, "殿上", "scene-sess", 0, night_id=night_id, status="generating",
    )
    db.update_chat_turn_messages(ctid, user_message_id=user_mid, minister_message_id=minister_mid)
    # 场景入口不跑故事抽取（转译 C1 接上）；标 done 以免收夜走旧抽取耗尽。
    db.conn.execute(
        "UPDATE chat_turns SET extract_status='done' WHERE id=?", (ctid,),
    )
    db.conn.commit()

    turns_before = list_chat_turns_for_night(db, night_id)
    assert turns_before and int(turns_before[-1]["id"]) == ctid

    # 场景只标退朝；持久化尾调度后台封夜。
    close_result = sess.scene_chat("退朝")
    assert close_result.court_action == "court_break"
    close_worker = sess.schedule_close_night_after_chat_if_needed(close_result.court_action)
    assert close_worker is not None
    close_worker.join()
    assert get_open_night(db) is None
    closed = get_night(db, night_id)
    assert closed is not None and closed.get("status") == "closed"

    turns_after = list_chat_turns_for_night(db, night_id)
    assert turns_after
    assert int(turns_after[-1]["id"]) == ctid
    assert int(turns_after[-1].get("minister_message_id") or 0) == minister_mid

