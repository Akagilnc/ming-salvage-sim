"""#1836 T1：一个 LLM 演整场召对。

Seams:
- prepare_scene_materials（在场诸人各一棵私有子树 + 开场最小集）
- create_scene_agent（零动作工具、只读材料工具）
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
    recognize_xuan_command,
    summon_enter,
)
from ming_sim.materials import list_materials, prepare_scene_materials, read_material
from ming_sim.models import Character, LLMConfig
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

    # 每人一棵子树：人物档料/经历/公事档案/朝臣名册 都在 人物/<名>/ 下。
    for name in ("毕自严", "王绍徽", "王承恩"):
        assert any(
            p.startswith(f"人物/{name}/") and p.endswith("/经历.txt") for p in listed
        ), f"{name} 须有私有经历"
        # ADR 0033/0155：人物+派系档料入私有子树；确定性字段（派系名）可核，不锁措辞。
        dossier_rel = next(
            (
                p for p in listed
                if p.startswith(f"人物/{name}/") and p.endswith("人物档料.txt")
            ),
            None,
        )
        assert dossier_rel, f"{name} 须有人物档料文件"
        dossier_body = read_material(prepared.root, dossier_rel)
        faction = str(getattr(content.characters[name], "faction", "") or "")
        assert faction and faction in dossier_body, (
            f"{name} 人物档料须含派系名 {faction!r}（character_context_with_db 投影）"
        )
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


def test_prepare_scene_materials_db_only_present_person_writes_dossier(game, tmp_path):
    """DB 补档人物不在 content.characters 时：真入口不崩，人物档料落出且含 DB 派系名。"""
    db, state, content = game
    name = "张三补档"
    faction = "东林"
    content.characters.pop(name, None)
    assert name not in content.characters

    db.add_character(
        state,
        Character(
            name=name,
            office="御前近臣",
            office_type="司礼监",
            faction=faction,
            aliases=[],
            personal_skills=[],
            loyalty=55,
            ability=55,
            integrity=60,
            courage=55,
            style="",
            power_id="ming",
            status="active",
        ),
    )
    # 仅落 DB，不入 content.characters（模拟运行时补档与静态 JSON 分叉）。
    assert name not in content.characters

    night = open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(night["id"])
    if name not in present_names_at(db, night_id):
        summon_enter(db, night_id, name, body="", empty_scaffold=True)
    assert name in present_names_at(db, night_id)

    prepared = prepare_scene_materials(db, state, dest_root=tmp_path / "scene-db-only")
    listed = list_materials(prepared.root)
    dossier_rel = next(
        (
            p for p in listed
            if p.startswith(f"人物/{name}/") and p.endswith("人物档料.txt")
        ),
        None,
    )
    assert dossier_rel, f"{name} 须有人物档料文件（DB 投影，不得因不在 content 而跳过）"
    dossier_body = read_material(prepared.root, dossier_rel)
    assert name in dossier_body
    assert faction in dossier_body, (
        f"DB 补档人物档料须含派系名 {faction!r}（character_context_with_db 投影）"
    )


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
            # 摹 agno 3.0.9：两者皆空时 num_history_runs 归一为 3。
            self.num_history_runs = kwargs.get("num_history_runs")
            self.num_history_messages = kwargs.get("num_history_messages")
            if self.num_history_messages is None and self.num_history_runs is None:
                self.num_history_runs = 3

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
    # ADR 0155：本夜全量 runs；不得留固定正整数硬截断（含 agno 默认 3）。
    assert captured.get("add_history_to_context") is True
    assert agent.num_history_runs is None, (
        f"create_scene_agent 须放开本夜历史，得 num_history_runs={agent.num_history_runs!r}"
    )
    # 构造入参也不得夹带未授权固定裁切；全量靠构造后显式 None。
    init_runs = captured.get("num_history_runs", None)
    assert init_runs is None, f"不得传入固定 num_history_runs={init_runs!r}"


@pytest.mark.usefixtures("_offline_scene_beat_generator")
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
    assert target in prepared.opening
    assert any(p.startswith(f"人物/{target}/") for p in list_materials(prepared.root))
    assert result.answer  # 宣后仍起一次场景调用


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


@pytest.mark.usefixtures("_offline_scene_beat_generator")
def test_scene_chat_no_longer_calls_parallel_classifier(game, monkeypatch):
    """#1837：场景入口退役并行分类器；回话后走转译（复用 conftest 离线空声明缝）。"""
    db, state, content = game
    open_night(db, state)

    class FakeAgent:
        tools = []

        def run(self, message):
            return SimpleNamespace(content="臣领旨。", tools=[])

    import ming_sim.cli_backend as cb

    def boom(*a, **k):
        raise AssertionError("scene_chat 不得再调 classify_cli_action_intent")

    monkeypatch.setattr("ming_sim.session.create_scene_agent", lambda *a, **k: FakeAgent())
    monkeypatch.setattr(cb, "classify_cli_action_intent", boom)

    sess = _sess(
        db, state, content,
        llm_config=SimpleNamespace(channel="cli", cli_runner="codex"),
    )
    result = sess.scene_chat("着户部拨银三十万两赈灾")
    assert result.answer == "臣领旨。"
    assert result.pending_action_id == 0
