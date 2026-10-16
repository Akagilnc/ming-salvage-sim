from __future__ import annotations
from types import SimpleNamespace
import pytest
from ming_sim.audience_night import (
    METHOD_XUANRU,
    METHOD_YUECI,
    TAG_ENTER,
    get_night,
    get_open_night,
    list_chat_turns_for_night,
    list_ledger,
    open_night,
    present_names_at,
    summon_enter,
)
from ming_sim.materials import _safe_segment, list_materials, prepare_scene_materials
from ming_sim.session import GameSession
from ming_sim.session_write_queue import SessionWriteQueue
"""#1836 T1：一个 LLM 演整场召对。

Seams:
- prepare_scene_materials（在场诸人各一棵私有子树 + 开场最小集）
- GameSession.scene_chat（宣 X 落入殿账 → 场景调用；退朝收夜；一轮一次调用）
- 关档重开：list_chat_turns_for_night 回到最后一条持久化对话轮
"""





def _sess(db, state, content, *, llm_config=None):
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.llm_config = llm_config or SimpleNamespace(channel="api")
    sess.agno_db = None
    sess._write_queue = SessionWriteQueue()
    sess._write_gate = sess._write_queue.write_gate
    return sess

@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_scene_chat_one_call_returns_multi_person_script(game, monkeypatch):
    """AC1：一轮戏文（可含多人）出自同一次场景调用。

    #1914：同一入口实交 agent 的 PreparedMaterials 须含近侍公事档案与派系态势路径
    （召对消费接缝；不另建无关材料树）。
    """
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
    prepared_box: list = []

    class FakeAgent:
        tools = []

        def run(self, message):
            calls.append(message)
            return SimpleNamespace(content=script, tools=[])

    def _factory(_llm_config, prepared, **_kwargs):
        prepared_box.append(prepared)
        return FakeAgent()

    monkeypatch.setattr("ming_sim.session.create_scene_agent", _factory)
    # #1842：ctid=0 同步转译走 conftest 离线空声明缝，不另造平行 fixture。
    sess = _sess(db, state, content, llm_config=SimpleNamespace(channel=""))
    emperor = "洪承畴可堪大任？"
    result = sess.scene_chat(emperor, write_gate=sess._write_gate)

    assert len(calls) == 1, "整段戏文必须出自同一次场景调用"
    # #1842：opening 已在 create_scene_agent instructions；run 输入不得再拼一份。
    assert calls[0] == emperor
    assert result.court_action == ""

    assert prepared_box, "scene_chat must hand prepared materials to the scene agent"
    mats = list_materials(prepared_box[0].root)
    assert "盘面/派系态势.txt" in mats
    attendant = "王承恩"
    assert attendant in present_names_at(db, night_id)
    assert f"人物/{_safe_segment(attendant)}/公事档案.txt" in mats

@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_xuan_lands_enter_then_present_on_next_prepare(game, monkeypatch, tmp_path):
    """AC2：「宣 X」后入殿账落下，下一次场景材料准备他在场。

    #1913：普通召法（低品级未以越次点名）记宣入、不记越次——并入本单人案，不另立平行测试。
    """
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    # 杨嗣昌开局低品、非常在员额：验普通「宣」不因品级自动越次。
    target = "杨嗣昌"
    night_id = int(get_open_night(db)["id"])
    assert target not in present_names_at(db, night_id)

    class FakeAgent:
        tools = []

        def run(self, message):
            return SimpleNamespace(content=f"{target}入殿叩见。", tools=[])

    monkeypatch.setattr("ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent())
    sess = _sess(db, state, content, llm_config=SimpleNamespace(channel=""))

    def _xuan(msg: str):
        # 正数源轮：与生产 scene 入口一致，覆盖在场去重接缝。
        ctid = db.create_chat_turn(
            state, "殿上", f"scene-1836:{msg}", 0,
            night_id=night_id, status="generating",
        )
        return sess.scene_chat(msg, write_gate=sess._write_gate, chat_turn_id=int(ctid))

    # 语气尾与无尾同形；不得整串预剥把合法名截坏（#1913 身份与尾缀统一解析）。
    result = _xuan(f"宣{target}来")

    def _enters():
        return [
            e for e in list_ledger(db, night_id)
            if TAG_ENTER in (e.get("tags") or [])
            and target in (e.get("person_names") or [])
            and "常在员额" not in (e.get("tags") or [])
        ]

    # 本次宣入必须新落一条 TAG_ENTER（非常在员额开夜账）。
    enters = _enters()
    assert enters, f"宣{target} must land a non-roster TAG_ENTER ledger entry"
    enter_tags = enters[0].get("tags") or []
    assert METHOD_XUANRU in enter_tags
    assert METHOD_YUECI not in enter_tags
    assert target in present_names_at(db, night_id)

    # 已在场再普通宣：不重复入殿（正数源轮下仍走在场去重）。
    _xuan(f"宣{target}")
    assert len(_enters()) == 1
    assert target in present_names_at(db, night_id)

    prepared = prepare_scene_materials(db, state, dest_root=tmp_path / "after-xuan")
    assert any(p.startswith(f"人物/{_safe_segment(target)}/") for p in list_materials(prepared.root))
    assert result.court_action == ""


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

    result = sess.scene_chat("边饷如何？", write_gate=sess._write_gate)
    assert result.court_action == ""
    user_mid = db.chat_messages.insert(minister_name='殿上', turn=state.turn, role='user', content='边饷如何？')
    minister_mid = db.chat_messages.insert(minister_name='殿上', turn=state.turn, role='assistant', content=result.answer or '众臣叩首：臣等遵旨。')
    ctid = db.create_chat_turn(
        state, "殿上", "scene-sess", 0, night_id=night_id, status="generating",
    )
    db.reign.update_chat_turn_messages(ctid, user_message_id=user_mid, minister_message_id=minister_mid)
    # 场景入口不跑故事抽取（转译 C1 接上）；标 done 以免收夜走旧抽取耗尽。
    db.conn.execute(
        "UPDATE chat_turns SET extract_status='done' WHERE id=?", (ctid,),
    )
    db.conn.commit()

    turns_before = list_chat_turns_for_night(db, night_id)
    assert turns_before and int(turns_before[-1]["id"]) == ctid

    # 场景只标退朝；持久化尾调度后台封夜。
    close_result = sess.scene_chat("退朝", write_gate=sess._write_gate)
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
