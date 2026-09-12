"""#1830 S1：材料目录骨架与目录读取。

Seams: prepare_character_materials (directory + opening min set),
list_materials/read_material (API), CLI cwd/readonly flags, restore rebuild.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from ming_sim.audience_night import (
    AUDIBILITY_PUBLIC,
    append_ledger_entry,
    open_night,
    summon_enter,
)
from ming_sim.materials import (
    _handled_affair_lines,
    _visible_affair_lines,
    list_materials,
    material_tools,
    prepare_character_materials,
    read_material,
)
from ming_sim.models import CourtContext, LLMConfig
from ming_sim.registry import MinisterRegistry, create_minister_agent
from ming_sim.session import GameSession


def _active_minister(db, content, *, office_type=None):
    for character in content.characters.values():
        if character.office_type in ("后宫", "宗藩"):
            continue
        if office_type and character.office_type != office_type:
            continue
        if db.get_character_status(character.name)[0] == "active":
            return character
    raise AssertionError("no active minister")


def _ctx(game):
    db, state, _ = game
    return CourtContext(state=state, db=db, previous_summary="")


def test_prepare_writes_typed_tree_and_index(game, tmp_path):
    db, state, content = game
    character = _active_minister(db, content)
    db.textual_facts.append(
        subject_kind="character",
        subject_id=character.name,
        body="本官亲见府库告罄。",
        year=state.year, period=state.period, turn=state.turn,
    )
    dest = tmp_path / "materials"
    prepared = prepare_character_materials(db, state, character, dest_root=dest)

    names = list_materials(prepared.root)
    assert "INDEX.txt" in names
    assert "人物/朝臣名册.txt" in names
    assert any(p.startswith("人物/") and p.endswith("/经历.txt") for p in names)
    assert any(p.startswith("人物/") and p.endswith("/公事档案.txt") for p in names)
    assert any(p.startswith("密令/") for p in names)
    assert any(p.startswith("荐人/") for p in names)
    assert any(p.startswith("事实/") for p in names)
    index = read_material(prepared.root, "INDEX.txt")
    assert "人物/朝臣名册.txt" in index.splitlines()
    assert any(line.startswith("密令/") for line in index.splitlines())
    assert any(line.startswith("荐人/") for line in index.splitlines())
    assert any(line.startswith("事实/") for line in index.splitlines())
    for line in index.splitlines():
        if line.strip():
            assert line.strip() in names
            assert read_material(prepared.root, line.strip())
    roster = read_material(prepared.root, "人物/朝臣名册.txt")
    status, _reason = db.get_character_status(character.name)
    assert character.name in roster
    assert (character.office or "无现任官职") in roster
    assert status in roster


def test_same_requested_root_creates_independent_material_invocations(game, tmp_path):
    db, state, content = game
    character = _active_minister(db, content)
    requested = tmp_path / "materials"

    first = prepare_character_materials(db, state, character, dest_root=requested)
    second = prepare_character_materials(db, state, character, dest_root=requested)

    assert first.root != second.root
    assert read_material(first.root, "INDEX.txt")
    assert read_material(second.root, "INDEX.txt")


def test_material_tree_contains_only_structurally_related_world_details(game, tmp_path):
    db, state, content = game
    character = _active_minister(db, content)
    slot = db.conn.execute(
        "SELECT office_title,region_id FROM office_slots WHERE region_id<>'' ORDER BY sort_order LIMIT 1"
    ).fetchone()
    army = db.conn.execute("SELECT id,name FROM armies ORDER BY id LIMIT 1").fetchone()
    db.set_character_office(character.name, slot["office_title"], office_type="地方")
    db.conn.execute("UPDATE armies SET commander='' WHERE commander=?", (character.name,))
    db.conn.execute(
        "UPDATE armies SET commander=?,supply=17,morale=23,loyalty=31,training=44,equipment=52 "
        "WHERE id=?", (character.name, army["id"]),
    )
    db.conn.execute(
        "UPDATE regions SET public_support=13,unrest=87 WHERE id=?", (slot["region_id"],),
    )
    db.conn.commit()

    prepared = prepare_character_materials(db, state, character, dest_root=tmp_path / "materials")
    names = list_materials(prepared.root)
    region_paths = [path for path in names if path.startswith("地区/")]
    army_paths = [path for path in names if path.startswith("军队/")]
    assert len(region_paths) == 1 and len(army_paths) == 1
    region_text = read_material(prepared.root, region_paths[0])
    army_text = read_material(prepared.root, army_paths[0])
    region_name = db.conn.execute(
        "SELECT name FROM regions WHERE id=?", (slot["region_id"],),
    ).fetchone()["name"]
    assert region_name in region_text and army["name"] in army_text
    assert "民心13" not in region_text and "动乱87" not in region_text
    assert "补给：17" not in army_text
    assert "士气：23" not in army_text and "士气23" not in army_text
    assert "忠诚：31" not in army_text and "军心：31" not in army_text
    assert "训练：44" not in army_text
    assert "装备：52" not in army_text


def test_registry_owner_handoffs_release_replaced_materials(game, tmp_path):
    db, state, content = game
    character = _active_minister(db, content)
    old_root = tmp_path / "old-materials"
    new_root = tmp_path / "new-materials"
    runtime_old = tmp_path / "runtime-old"
    runtime_new = tmp_path / "runtime-new"
    closed = tmp_path / "closed-materials"
    session_old = tmp_path / "session-old"
    for path in (old_root, new_root, runtime_old, runtime_new, closed, session_old):
        path.mkdir()
    registry = object.__new__(MinisterRegistry)
    registry.content = content
    registry.context = SimpleNamespace(state=state)
    registry.session_ids = {}
    registry.agents = {
        character.name: SimpleNamespace(model=SimpleNamespace(materials_dir=str(old_root)))
    }
    registry._create = lambda _character: SimpleNamespace(
        model=SimpleNamespace(materials_dir=str(new_root))
    )
    registry.refresh(character.name)
    assert not old_root.exists() and new_root.exists()

    registry.agents[character.name] = SimpleNamespace(
        model=SimpleNamespace(materials_dir=str(runtime_old))
    )
    registry._create = lambda _character: SimpleNamespace(
        model=SimpleNamespace(materials_dir=str(runtime_new))
    )
    registry.register_runtime(character)
    assert not runtime_old.exists() and runtime_new.exists()

    registry.agents["other"] = SimpleNamespace(
        model=SimpleNamespace(materials_dir=str(closed))
    )
    registry.close()
    assert not closed.exists() and not runtime_new.exists()
    assert registry.agents == {}

    session = object.__new__(GameSession)
    leftover = object.__new__(MinisterRegistry)
    leftover.agents = {
        character.name: SimpleNamespace(model=SimpleNamespace(materials_dir=str(session_old)))
    }
    session.registry = leftover
    replacement = object.__new__(MinisterRegistry)
    replacement.agents = {}
    session._adopt_registry(replacement)
    assert session.registry is replacement
    assert not session_old.exists()

    session_close_dir = tmp_path / "session-close"
    session_close_dir.mkdir()
    closing = object.__new__(GameSession)
    leftover_close = object.__new__(MinisterRegistry)
    leftover_close.agents = {
        character.name: SimpleNamespace(model=SimpleNamespace(materials_dir=str(session_close_dir)))
    }
    closing.registry = leftover_close
    closing._scene_registry = SimpleNamespace(abandon_all=lambda: None)
    closing.agno_db = None
    closing.db = SimpleNamespace(close=lambda: None)
    closing._close_epoch = 0
    GameSession.close(closing)
    assert closing.registry is None
    assert not session_close_dir.exists()


def test_opening_handled_matters_are_filtered_within_authorized_knowledge(game, tmp_path):
    db, state, content = game
    character = _active_minister(db, content)
    current_office = "当回合新任官职"
    db.conn.execute(
        "UPDATE characters SET office = ? WHERE name = ?", (current_office, character.name),
    )
    knowledge = {"issues": [
        {"id": 101, "title": "经手事项", "participant_roster": json.dumps([
            {"character_id": character.name, "tier": "主办"},
        ])},
        {"id": 102, "title": "无人承办事项", "participant_roster": "[]"},
    ]}

    original_get = db.get_character_knowledge
    db.get_character_knowledge = lambda *_args: knowledge
    try:
        prepared = prepare_character_materials(
            db, state, character, dest_root=tmp_path / "materials",
        )
    finally:
        db.get_character_knowledge = original_get
    assert current_office in prepared.opening
    assert character.office not in prepared.opening
    issue_paths = {line for line in prepared.index_lines if line.startswith("事务/issue-")}
    assert issue_paths == {
        "事务/issue-101/当前情况.txt", "事务/issue-102/当前情况.txt",
    }
    projected = _visible_affair_lines(knowledge)
    assert [row["id"] for row in _handled_affair_lines(
        db, state, character.name, projected,
    )] == [101]


def test_prepare_fails_loud_when_dossier_read_breaks(game, tmp_path):
    db, state, content = game
    character = _active_minister(db, content)

    def boom(*_a, **_k):
        raise RuntimeError("dossier boom")

    db.list_referenceable_dossiers = boom
    try:
        prepare_character_materials(db, state, character, dest_root=tmp_path / "m")
        raise AssertionError("expected fail loud")
    except RuntimeError as exc:
        assert "dossier boom" in str(exc)


def test_read_material_stays_inside_directory(game, tmp_path):
    db, state, content = game
    character = _active_minister(db, content)
    prepared = prepare_character_materials(
        db, state, character, dest_root=tmp_path / "m",
    )
    try:
        read_material(prepared.root, "../outside.txt")
        raise AssertionError("expected path confinement")
    except ValueError:
        pass
    tools = {tool.__name__: tool for tool in material_tools(prepared.root)}
    assert tools["list_materials"]("../outside") == tools["read_material"]("../outside")


def test_audience_agent_exposes_directory_tools_and_min_instructions(game):
    db, state, content = game
    character = _active_minister(db, content)
    captured = {}

    def fake_agent(**kwargs):
        captured.update(kwargs)
        return kwargs

    cfg = LLMConfig(api_key="", base_url="", model="test", channel="cli", cli_runner="codex")
    with patch("ming_sim.registry.Agent", side_effect=fake_agent), \
         patch("ming_sim.registry.create_chat_model", return_value=MagicMock()):
        create_minister_agent(character, cfg, _ctx(game), db)

    tool_names = {getattr(fn, "__name__", "") for fn in captured["tools"]}
    assert "list_materials" in tool_names
    assert "read_material" in tool_names
    assert "propose_directive" in tool_names
    retired_reads = {
        "list_regions", "inspect_region", "read_past_report", "search_memories",
        "inspect_treasury_ledger", "check_treasury", "list_memorials",
        "inspect_memorial", "list_buildings", "inspect_building",
        "estimate_resistance", "query_court_roster", "query_army_roster",
        "allocate_payroll", "audit_tax_arrears",
    }
    assert not (tool_names & retired_reads)
    tools = {fn.__name__: fn for fn in captured["tools"]}
    listing = tools["list_materials"]()
    rel = next(line for line in listing.splitlines() if line.endswith("经历.txt"))
    body = tools["read_material"](rel)
    assert body


def test_audience_prompt_rebuilds_from_directory_and_persisted_turns(game):
    db, state, content = game
    character = _active_minister(db, content)
    night = open_night(db, state, location="乾清宫", time_of_day="戌时")
    summon_enter(db, int(night["id"]), character.name)
    from ming_sim.audience_night import attach_chat_turn_to_night
    _nid, ct = attach_chat_turn_to_night(
        db, state, character.name, agno_session_id="sess", agno_runs_before=0,
    )
    spoken = "SENTINEL_NIGHT_SPOKEN_1830"
    uid = db.append_chat_message(character.name, state.turn, "user", "问边饷")
    db.update_chat_turn_messages(ct, user_message_id=uid)
    mid = db.append_chat_message(character.name, state.turn, "minister", spoken)
    db.update_chat_turn_messages(ct, minister_message_id=mid)
    db.conn.execute("UPDATE chat_turns SET extract_status='done' WHERE id=?", (ct,))
    db.conn.commit()
    append_ledger_entry(
        db, int(night["id"]), person_names=[character.name],
        body=spoken, audibility=AUDIBILITY_PUBLIC,
    )

    model = SimpleNamespace(materials_dir="")
    registry = SimpleNamespace(agents={character.name: SimpleNamespace(model=model)})
    session = SimpleNamespace(db=db, state=state, registry=registry)
    GameSession._audience_prompt_for_message(session, "下一句", character)
    prepared_root = Path(model.materials_dir)
    index_before = tuple(
        line for line in read_material(prepared_root, "INDEX.txt").splitlines() if line
    )
    turn_pointer = db.conn.execute(
        "SELECT user_message_id, minister_message_id FROM chat_turns WHERE id=?", (ct,),
    ).fetchone()
    assert tuple(turn_pointer) == (uid, mid)

    path = str(db.path)
    db.close()
    from ming_sim.db import GameDB
    restored = GameDB(path, content)
    try:
        state2 = restored.load_state()
        character2 = content.characters[character.name]
        restored_pointer = restored.conn.execute(
            "SELECT user_message_id, minister_message_id FROM chat_turns WHERE id=?", (ct,),
        ).fetchone()
        assert tuple(restored_pointer) == (uid, mid)
        restored_model = SimpleNamespace(materials_dir="")
        restored_registry = SimpleNamespace(
            agents={character2.name: SimpleNamespace(model=restored_model)},
        )
        restored_session = SimpleNamespace(
            db=restored, state=state2, registry=restored_registry,
        )
        GameSession._audience_prompt_for_message(
            restored_session, "重开后一句", character2,
        )
        rebuilt_root = Path(restored_model.materials_dir)
        rebuilt_index = tuple(
            line for line in read_material(rebuilt_root, "INDEX.txt").splitlines() if line
        )
        assert rebuilt_index == index_before
        tools = {tool.__name__: tool for tool in material_tools(rebuilt_root)}
        rel = next(p for p in rebuilt_index if p.endswith("经历.txt"))
        assert rel in tools["list_materials"]().splitlines()
        assert tools["read_material"](rel)
    finally:
        restored.close()
