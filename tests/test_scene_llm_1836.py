"""#1836 T1：一个 LLM 演整场召对。

Seams:
- prepare_scene_materials（在场诸人各一棵私有子树 + 开场最小集）
- create_scene_agent（零动作工具、只读材料工具）
- GameSession.scene_chat（宣 X 落入殿账 → 场景调用；退朝收夜；一轮一次调用）
- 关档重开：list_chat_turns_for_night 回到最后一条持久化对话轮
"""

from __future__ import annotations

from types import SimpleNamespace

from ming_sim.audience_night import (
    TAG_ENTER,
    get_night,
    get_open_night,
    list_chat_turns_for_night,
    list_ledger,
    open_night,
    present_names_at,
    recognize_xuan_command,
    summon_enter,
)
from ming_sim.materials import list_materials, prepare_scene_materials, read_material
from ming_sim.models import LLMConfig
from ming_sim.registry import create_scene_agent
from ming_sim.session import GameSession


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
    sess._write_gate = None
    return sess


def test_recognize_xuan_command_extracts_name():
    assert recognize_xuan_command("宣王绍徽") == "王绍徽"
    assert recognize_xuan_command("宣王绍徽来") == "王绍徽"
    assert recognize_xuan_command("传毕自严入殿") == "毕自严"
    assert recognize_xuan_command("退朝") is None
    assert recognize_xuan_command("洪承畴可堪大任？") is None


def test_prepare_scene_materials_no_cross_person_overwrite(game, tmp_path):
    """在场多人的朝臣名册/公开说法/事务各写在 人物/<名>/ 下，后写不覆盖先写。"""
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    # 固定三人：毕自严、王绍徽（外廷）+ 王承恩（常在，开夜已入）。
    for name in ("毕自严", "王绍徽"):
        if name not in present_names_at(db, night_id):
            summon_enter(db, night_id, name, body="", empty_scaffold=True)

    # 单人投影：三人朝臣名册行数不同（职位透视），场景目录必须各自保留，不得只剩最后一人。
    from ming_sim.materials import prepare_character_materials
    solo_lens = {}
    for name in ("毕自严", "王承恩", "王绍徽"):
        solo = prepare_character_materials(
            db, state, content.characters[name],
            dest_root=tmp_path / f"solo-{name}",
        )
        solo_roster = read_material(solo.root, "人物/朝臣名册.txt")
        solo_lens[name] = len(solo_roster.splitlines())

    prepared = prepare_scene_materials(db, state, dest_root=tmp_path / "scene")
    listed = list_materials(prepared.root)

    # 每人一棵子树：经历/公事档案/朝臣名册 都在 人物/<名>/ 下。
    for name in ("毕自严", "王绍徽", "王承恩"):
        assert any(
            p.startswith(f"人物/{name}/") and p.endswith("/经历.txt") for p in listed
        ), f"{name} 须有私有经历"
        roster_rel = next(
            p for p in listed
            if p.startswith(f"人物/{name}/") and p.endswith("朝臣名册.txt")
        )
        scene_roster = read_material(prepared.root, roster_rel)
        # 结构化：行数与单人投影一致 → 该人视角未被后写覆盖。
        assert len(scene_roster.splitlines()) == solo_lens[name], (
            f"{name} 场景朝臣名册被覆盖（期望 {solo_lens[name]} 行，得 "
            f"{len(scene_roster.splitlines())}）"
        )

    # 不得出现根级共享路径（单人 _write_tree 叠写形状）。
    assert "人物/朝臣名册.txt" not in listed
    assert not any(
        (p.startswith("事务/") or p.startswith("公开说法/")) and not p.startswith("人物/")
        for p in listed
    )

    # 开场最小集含在场、日期、正经手事务段、本场已说。
    assert "在场：" in prepared.opening
    assert str(state.year) in prepared.opening
    assert "正经手事务" in prepared.opening
    assert "本场已说的话" in prepared.opening
    # 零形式约束：opening 不得负向约束戏文。
    assert "不填表" not in prepared.opening
    assert "不调动作" not in prepared.opening

    index = read_material(prepared.root, "INDEX.txt")
    for line in index.splitlines():
        if line.strip():
            assert line.strip() in listed


def test_scene_agent_has_only_material_read_tools(game, tmp_path, monkeypatch):
    db, state, content = game
    open_night(db, state)
    prepared = prepare_scene_materials(db, state, dest_root=tmp_path / "scene")
    cfg = LLMConfig(api_key="k", base_url="http://example.test", model="test-model")

    captured = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.tools = kwargs.get("tools") or []

    monkeypatch.setattr("ming_sim.registry.Agent", FakeAgent)
    monkeypatch.setattr(
        "ming_sim.registry.create_chat_model",
        lambda *a, **k: SimpleNamespace(materials_dir=""),
    )
    agent = create_scene_agent(cfg, prepared, content=content)
    tool_names = sorted(
        getattr(t, "__name__", getattr(t, "name", str(t))) for t in (agent.tools or [])
    )
    assert tool_names == ["list_materials", "read_material"]
    banned = {
        "dismiss_minister", "summon_minister", "propose_directive",
        "propose_appointment", "secret_order", "rush_staged_commitment",
        "register_unlisted_person",
    }
    assert banned.isdisjoint(tool_names)
    assert captured.get("skills") in (None, [])


def test_scene_chat_one_call_returns_multi_person_script(game, monkeypatch):
    """AC1：一轮戏文（可含多人）出自同一次场景调用。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(get_open_night(db)["id"])
    for name in ("王绍徽", "毕自严"):
        if name not in present_names_at(db, night_id):
            summon_enter(db, night_id, name, body="", empty_scaffold=True)

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
    # 分类器不跑真 LLM：channel 非 cli/api 且无 backend → _start_scene_action_intent 早退 None。
    sess = _sess(db, state, content, llm_config=SimpleNamespace(channel=""))
    result = sess.scene_chat("洪承畴可堪大任？")

    assert len(calls) == 1, "整段戏文必须出自同一次场景调用"
    assert result.answer == script
    assert result.court_action == ""


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
    assert target in prepared.opening
    assert any(p.startswith(f"人物/{target}/") for p in list_materials(prepared.root))
    assert result.answer  # 宣后仍起一次场景调用


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

    # 真入口：chat_turn_id=0 → scene_chat 内 close_night。
    close_result = sess.scene_chat("退朝")
    assert close_result.court_action == "court_break"
    assert get_open_night(db) is None
    closed = get_night(db, night_id)
    assert closed is not None and closed.get("status") == "closed"

    turns_after = list_chat_turns_for_night(db, night_id)
    assert turns_after
    assert int(turns_after[-1]["id"]) == ctid
    assert int(turns_after[-1].get("minister_message_id") or 0) == minister_mid


def test_scene_chat_transition_classifier_reads_player_message_only(game, monkeypatch):
    """过渡：分类器只读玩家话；经 _start_scene_action_intent 真缝调用，不绑假大臣。"""
    db, state, content = game
    open_night(db, state)

    class FakeAgent:
        tools = []

        def run(self, message):
            return SimpleNamespace(content="臣领旨。", tools=[])

    seen_messages: list[str] = []
    seen_kwargs: list[dict] = []

    def fake_classify(text, *args, **kwargs):
        seen_messages.append(text)
        # classify_cli_action_intent positional: text, active_orders, is_consort, ...
        seen_kwargs.append({"args": args, "kwargs": kwargs})
        return {"kind": "none"}

    monkeypatch.setattr("ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent())
    import ming_sim.cli_backend as cb
    monkeypatch.setattr(cb, "classify_cli_action_intent", fake_classify)

    sess = _sess(
        db, state, content,
        llm_config=SimpleNamespace(channel="cli", cli_runner="codex"),
    )
    # 同步跑分类器（不经线程池），仍走 _start_scene_action_intent 生产装配。
    def sync_start(message):
        fut = sess._start_scene_action_intent.__get__(sess, GameSession)(message)
        # Replace executor future with immediate result by joining.
        return fut

    # 直接让 _start_scene_action_intent 走真代码，但 executor 同步。
    from concurrent.futures import Future

    def immediate_submit(fn, *a, **k):
        f = Future()
        try:
            f.set_result(fn(*a, **k))
        except Exception as exc:
            f.set_exception(exc)
        return f

    monkeypatch.setattr(
        "ming_sim.session._CLI_ACTION_INTENT_EXECUTOR",
        SimpleNamespace(submit=immediate_submit),
    )

    sess.scene_chat("着户部拨银三十万两赈灾")
    assert seen_messages == ["着户部拨银三十万两赈灾"]
    # 第二参 active_orders 必须是空列表（无假大臣密令锚）。
    assert seen_kwargs and seen_kwargs[0]["args"][0] == []
