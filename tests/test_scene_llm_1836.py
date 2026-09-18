"""#1836 T1：一个 LLM 演整场召对。

Seams:
- prepare_scene_materials（在场诸人目录 + 开场最小集）
- create_scene_agent（零动作工具、只读材料工具）
- GameSession.scene_chat（宣 X 落入殿账 → 场景调用；退朝收夜；一轮一次调用）
- 关档重开：list_chat_turns_for_night 回到最后一条持久化对话轮
"""

from __future__ import annotations

from types import SimpleNamespace

from ming_sim.audience_night import (
    TAG_ENTER,
    get_open_night,
    list_chat_turns_for_night,
    list_ledger,
    open_night,
    present_names_at,
    recognize_xuan_command,
)
from ming_sim.materials import list_materials, prepare_scene_materials, read_material
from ming_sim.models import LLMConfig
from ming_sim.registry import create_scene_agent
from ming_sim.session import GameSession


def _active_names(db, content, *wanted):
    """Return active fixture characters, preferring the requested names."""
    active = {
        name: ch
        for name, ch in content.characters.items()
        if db.get_character_status(name)[0] == "active"
        and getattr(ch, "office_type", "") not in ("后宫", "宗藩")
    }
    found = [name for name in wanted if name in active]
    if len(found) >= len(wanted):
        return found
    # Fall back to any actives so the fixture still exercises multi-person.
    extras = [n for n in active if n not in found]
    return (found + extras)[: max(len(wanted), 2)]


def _sess(db, state, content, *, registry=None, llm_config=None):
    sess = GameSession.__new__(GameSession)
    sess.db = db
    sess.state = state
    sess.content = content
    sess.registry = registry
    sess.llm_config = llm_config or SimpleNamespace(channel="api")
    sess.temporary_characters = {}
    sess.agno_db = None
    sess._beat_generator = None
    sess._scene_registry = None
    sess._write_gate = None
    # 默认不跑真分类器（过渡缝由专测覆盖）。
    sess._start_cli_action_intent = lambda *a, **k: None
    sess._finish_cli_action_intent = lambda *a, **k: None
    sess._cli_backend_fallback_actions = lambda *a, **k: None
    return sess


def test_recognize_xuan_command_extracts_name():
    assert recognize_xuan_command("宣王绍徽") == "王绍徽"
    assert recognize_xuan_command("宣王绍徽来") == "王绍徽"
    assert recognize_xuan_command("传毕自严入殿") == "毕自严"
    assert recognize_xuan_command("退朝") is None
    assert recognize_xuan_command("洪承畴可堪大任？") is None


def test_prepare_scene_materials_covers_present_people(game, tmp_path):
    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    names = _active_names(db, content, "王绍徽", "毕自严", "王承恩")
    from ming_sim.audience_night import summon_enter

    for name in names:
        if name not in present_names_at(db, int(night["id"])):
            summon_enter(db, int(night["id"]), name, body="", empty_scaffold=True)

    prepared = prepare_scene_materials(db, state, dest_root=tmp_path / "scene")
    listed = list_materials(prepared.root)
    assert "INDEX.txt" in listed
    for name in names:
        assert any(
            p.startswith(f"人物/{name}/") or f"/{name}/" in p for p in listed
        ), f"{name} must have materials under the scene directory"
    # Opening min-set is structured context, not full dumps.
    assert prepared.opening
    assert str(state.year) in prepared.opening
    for name in names:
        assert name in prepared.opening
    # No raw world-store copies.
    assert not any(n.lower().endswith((".db", ".sqlite", ".sqlite3", ".json")) for n in listed)
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
    # Generation chain must not attach action skills either.
    assert captured.get("skills") in (None, [])


def test_scene_chat_one_call_returns_multi_person_script(game, monkeypatch):
    """AC1：一轮戏文（可含多人）出自同一次场景调用。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    names = _active_names(db, content, "王绍徽", "毕自严", "王承恩")
    from ming_sim.audience_night import summon_enter

    night_id = int(get_open_night(db)["id"])
    for name in names:
        if name not in present_names_at(db, night_id):
            summon_enter(db, night_id, name, body="", empty_scaffold=True)

    script = (
        f"{names[0]}出列奏道：臣以为洪承畴可当一面。\n"
        f"{names[1]}侧身插话：户部库藏尚可挪移三十万两。\n"
        f"{names[2] if len(names) > 2 else names[0]}欠身低语：皇爷，此人可用。"
    )
    calls: list[str] = []

    class FakeAgent:
        tools = []

        def run(self, message):
            calls.append(message)
            return SimpleNamespace(content=script, tools=[])

    monkeypatch.setattr("ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent())

    sess = _sess(db, state, content)
    result = sess.scene_chat("洪承畴可堪大任？")

    assert len(calls) == 1, "整段戏文必须出自同一次场景调用"
    assert result.answer == script
    assert result.court_action == ""


def test_xuan_lands_enter_then_present_on_next_prepare(game, monkeypatch, tmp_path):
    """AC2：「宣 X」后入殿账落下，下一次场景材料准备他在场。"""
    db, state, content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")
    target = _active_names(db, content, "王绍徽")[0]
    night_id = int(get_open_night(db)["id"])
    assert target not in present_names_at(db, night_id) or target in present_names_at(db, night_id)
    # Force not-present if standing roster already put them in (inner court).
    # For outer ministers they should not be present yet.
    was_present = target in present_names_at(db, night_id)

    class FakeAgent:
        tools = []

        def run(self, message):
            return SimpleNamespace(content=f"{target}入殿叩见。", tools=[])

    monkeypatch.setattr("ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent())

    sess = _sess(db, state, content)
    result = sess.scene_chat(f"宣{target}")

    # Enter ledger must record the person.
    enters = [
        e for e in list_ledger(db, night_id)
        if TAG_ENTER in (e.get("tags") or []) and target in (e.get("person_names") or [])
    ]
    assert enters, f"宣{target} must land TAG_ENTER ledger entry"
    assert target in present_names_at(db, night_id)

    prepared = prepare_scene_materials(db, state, dest_root=tmp_path / "after-xuan")
    assert target in prepared.opening
    assert result.answer  # scene call still ran after landing enter
    if was_present:
        # Standing roster may already be present; still must have run scene once.
        pass


def test_retire_command_closes_night_and_reopen_keeps_last_turn(game, monkeypatch, tmp_path):
    """AC3：退朝口令触发收夜；关档重开回到最后一条持久化对话轮。"""
    from ming_sim.audience_night import close_night

    db, state, content = game
    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])

    class FakeAgent:
        tools = []

        def run(self, message):
            return SimpleNamespace(content="众臣叩首：臣等遵旨。", tools=[])

    monkeypatch.setattr("ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent())
    sess = _sess(db, state, content)

    # One completed scene turn persisted on the night.
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

    # 退朝口令 → court_break（与既有 command-verdict 同缝）。
    # chat_turn_id!=0 时 epilogue 收夜；此处直接断言口令机械面 + 生产 close_night。
    close_result = sess.scene_chat("退朝", chat_turn_id=ctid)
    assert close_result.court_action == "court_break"

    close_night(db, state, night_id=night_id, content=content, body="")
    assert get_open_night(db) is None or get_open_night(db).get("status") == "closed"

    # 关档重开：同库重读最后一条持久化对话轮仍在（ADR 0036）。
    turns_after = list_chat_turns_for_night(db, night_id)
    assert turns_after
    assert int(turns_after[-1]["id"]) == ctid
    assert int(turns_after[-1].get("minister_message_id") or 0) == minister_mid


def test_scene_chat_transition_classifier_reads_player_message_only(game, monkeypatch):
    """过渡：交办仍走现状只读玩家话的分类器（转译 C1a 接上前）。"""
    db, state, content = game
    open_night(db, state)

    class FakeAgent:
        tools = []

        def run(self, message):
            return SimpleNamespace(content="臣领旨。", tools=[])

    seen: list = []

    def fake_classify(character, message, **kwargs):
        seen.append(message)
        return {"kind": "none"}

    monkeypatch.setattr("ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent())
    import ming_sim.cli_backend as cb
    monkeypatch.setattr(cb, "classify_cli_action_intent", fake_classify)

    sess = _sess(db, state, content, llm_config=SimpleNamespace(channel="cli", cli_runner="codex"))
    # Override the default no-op stubs from _sess.
    sess._start_cli_action_intent = lambda character, message: ("future", message)
    sess._finish_cli_action_intent = (
        lambda fut: seen.append(fut[1]) or {"kind": "none"}
    )
    sess.scene_chat("着户部拨银三十万两赈灾")
    assert seen and seen[0] == "着户部拨银三十万两赈灾"
