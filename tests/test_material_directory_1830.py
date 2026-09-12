"""#1830 S1：材料目录骨架与目录读取。

Seams: prepare_character_materials (directory + opening min set),
list_materials/read_material (API), CLI cwd/readonly flags, restore rebuild.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from tests.dossier_test_helpers import create_test_secret_order

from ming_sim.audience_night import (
    AUDIBILITY_PUBLIC,
    append_ledger_entry,
    open_night,
    summon_enter,
)
from ming_sim.materials import (
    MaterialsRoot,
    _handled_affair_lines,
    _visible_affair_lines,
    list_materials,
    material_tools,
    prepare_character_materials,
    read_material,
    release_material_tree,
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


def _agent_with_materials(root: Path, *, with_cli_cwd: bool):
    """Minimal agent stand-in: MaterialsRoot always; materials_dir only for CLI."""
    handle = MaterialsRoot(root)
    model = SimpleNamespace()
    if with_cli_cwd:
        model.materials_dir = handle.root
    return SimpleNamespace(model=model, materials_root=handle)


def test_registry_owner_handoffs_release_replaced_materials(game, tmp_path):
    db, state, content = game
    character = _active_minister(db, content)
    old_root = tmp_path / "inv-old" / ("a" * 32) / "old-materials"
    new_root = tmp_path / "inv-new" / ("b" * 32) / "new-materials"
    runtime_old = tmp_path / "inv-rt-old" / ("c" * 32) / "runtime-old"
    runtime_new = tmp_path / "inv-rt-new" / ("d" * 32) / "runtime-new"
    closed = tmp_path / "inv-closed" / ("e" * 32) / "closed-materials"
    session_old = tmp_path / "inv-session" / ("f" * 32) / "session-old"
    for path in (old_root, new_root, runtime_old, runtime_new, closed, session_old):
        path.mkdir(parents=True)
    registry = object.__new__(MinisterRegistry)
    registry.content = content
    registry.context = SimpleNamespace(state=state)
    registry.session_ids = {}
    # API OpenAIChat path: no model.materials_dir; ownership is MaterialsRoot.
    registry.agents = {character.name: _agent_with_materials(old_root, with_cli_cwd=False)}
    registry._create = lambda _character: _agent_with_materials(new_root, with_cli_cwd=False)
    registry.refresh(character.name)
    assert not old_root.exists() and new_root.exists()
    assert not old_root.parent.exists()  # UUID parent released with the leaf

    registry.agents[character.name] = _agent_with_materials(runtime_old, with_cli_cwd=True)
    registry._create = lambda _character: _agent_with_materials(runtime_new, with_cli_cwd=True)
    registry.register_runtime(character)
    assert not runtime_old.exists() and runtime_new.exists()
    assert not runtime_old.parent.exists()

    # adopt_materials keeps API tools + CLI cwd on the same live root even when
    # the concrete model has no materials_dir (real API OpenAIChat).
    adopted = tmp_path / "inv-adopt" / ("1" * 32) / "adopted"
    adopted.mkdir(parents=True)
    (adopted / "INDEX.txt").write_text("live\n", encoding="utf-8")
    api_agent = _agent_with_materials(runtime_new, with_cli_cwd=False)
    registry.agents[character.name] = api_agent
    tools = material_tools(api_agent.materials_root)
    registry.adopt_materials(character.name, adopted)
    assert not runtime_new.exists() and adopted.exists()
    assert api_agent.materials_root.root == str(adopted)
    assert not hasattr(api_agent.model, "materials_dir")
    listed = tools[0]("")
    assert "INDEX.txt" in listed
    assert read_material(Path(api_agent.materials_root.root), "INDEX.txt").strip() == "live"

    # prepare failure must not leave empty UUID invocation parents behind.
    # write_tree primary stays outward even when cleanup also fails.
    fail_parent = tmp_path / ("3" * 32)
    fail_dest = fail_parent / "leaf"

    def _boom(_tmp):
        raise RuntimeError("prepare-write-boom")

    from ming_sim.materials import _publish_material_tree
    with pytest.raises(RuntimeError, match="prepare-write-boom") as boom_exc:
        _publish_material_tree(None, fail_dest, _boom)
    assert not fail_parent.exists()
    assert boom_exc.value.__cause__ is None

    dual_parent = tmp_path / ("7" * 32)
    dual_dest = dual_parent / "leaf"

    def _boom_write(_tmp):
        raise RuntimeError("ORIGINAL_WRITE")

    def _rmtree_cleanup(path, *args, **kwargs):
        raise OSError("CLEANUP_SECONDARY")

    with patch("ming_sim.materials.shutil.rmtree", side_effect=_rmtree_cleanup):
        with pytest.raises(RuntimeError, match="ORIGINAL_WRITE") as dual_exc:
            _publish_material_tree(None, dual_dest, _boom_write)
    assert isinstance(dual_exc.value.__cause__, OSError)
    assert "CLEANUP_SECONDARY" in str(dual_exc.value.__cause__)

    registry.agents["other"] = _agent_with_materials(closed, with_cli_cwd=False)
    registry.close()
    assert not closed.exists() and not adopted.exists()
    assert not closed.parent.exists()
    assert registry.agents == {}

    session = object.__new__(GameSession)
    leftover = object.__new__(MinisterRegistry)
    leftover.agents = {
        character.name: _agent_with_materials(session_old, with_cli_cwd=False)
    }
    leftover.close = MinisterRegistry.close.__get__(leftover, MinisterRegistry)
    leftover._release_materials = MinisterRegistry._release_materials
    leftover._materials_handle = MinisterRegistry._materials_handle
    session.registry = leftover
    replacement = object.__new__(MinisterRegistry)
    replacement.agents = {}
    session._adopt_registry(replacement)
    assert session.registry is replacement
    assert not session_old.exists()
    assert not session_old.parent.exists()

    session_close_dir = tmp_path / "inv-close" / ("2" * 32) / "session-close"
    session_close_dir.mkdir(parents=True)
    closing = object.__new__(GameSession)
    leftover_close = object.__new__(MinisterRegistry)
    leftover_close.agents = {
        character.name: _agent_with_materials(session_close_dir, with_cli_cwd=False)
    }
    leftover_close.close = MinisterRegistry.close.__get__(leftover_close, MinisterRegistry)
    leftover_close._release_materials = MinisterRegistry._release_materials
    leftover_close._materials_handle = MinisterRegistry._materials_handle
    closing.registry = leftover_close
    closing._scene_registry = SimpleNamespace(abandon_all=lambda: None)
    closing.agno_db = None
    closing.db = SimpleNamespace(close=lambda: None)
    closing._close_epoch = 0
    GameSession.close(closing)
    assert closing.registry is None
    assert not session_close_dir.exists()
    assert not session_close_dir.parent.exists()

    # Materials cleanup failure still releases db; error is surfaced honestly.
    failing = object.__new__(GameSession)
    bad_reg = object.__new__(MinisterRegistry)

    def _boom_close():
        raise RuntimeError("materials-cleanup-boom")

    bad_reg.agents = {"x": _agent_with_materials(tmp_path / "x", with_cli_cwd=False)}
    bad_reg.close = lambda: (_boom_close())
    failing.registry = bad_reg
    failing._scene_registry = SimpleNamespace(abandon_all=lambda: None)
    failing.agno_db = None
    closed_db = {"done": False}
    failing.db = SimpleNamespace(close=lambda: closed_db.__setitem__("done", True))
    failing._close_epoch = 0
    with pytest.raises(RuntimeError, match="materials-cleanup-boom"):
        GameSession.close(failing)
    assert closed_db["done"] is True
    assert failing.registry is None

    # release keeps the primary cleanup error when parent rmdir also fails.
    leaf = tmp_path / ("4" * 32) / "leaf-keep-primary"
    leaf.mkdir(parents=True)
    (leaf / "f.txt").write_text("x", encoding="utf-8")
    real_rmtree = __import__("shutil").rmtree

    def _rmtree_boom(path, *args, **kwargs):
        raise RuntimeError("primary-rmtree")

    with patch("ming_sim.materials.shutil.rmtree", side_effect=_rmtree_boom):
        with pytest.raises(RuntimeError, match="primary-rmtree"):
            release_material_tree(leaf)


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


def test_audience_agent_exposes_directory_tools_and_min_instructions(game, tmp_path):
    db, state, content = game
    character = _active_minister(db, content)
    from agno.agent import Agent
    from agno.db.sqlite import SqliteDb
    from agno.models.openai import OpenAIChat

    # Real Agent + real OpenAIChat API path (no model.materials_dir): prove handle
    # from the production construction entrance — do not stand in with SimpleNamespace.
    api_model = OpenAIChat(id="gpt-4o-mini", api_key="sk-test-not-used")
    assert not hasattr(api_model, "materials_dir")
    cfg_api = LLMConfig(
        api_key="sk-test-not-used", base_url="https://example.invalid/v1",
        model="gpt-4o-mini", channel="api",
    )
    agno_db = SqliteDb(db_file=str(tmp_path / "agno-materials.db"))
    with patch("ming_sim.registry.create_chat_model", return_value=api_model):
        agent = create_minister_agent(character, cfg_api, _ctx(game), agno_db)
    assert isinstance(agent, Agent)
    assert isinstance(agent.materials_root, MaterialsRoot)
    assert agent.materials_root.root
    assert Path(agent.materials_root.root).exists()
    assert agent.model is api_model
    assert not hasattr(agent.model, "materials_dir")
    tool_names = {
        getattr(fn, "__name__", "") for fn in (agent.tools or [])
    }
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
    tools = {fn.__name__: fn for fn in agent.tools if hasattr(fn, "__name__")}
    listing = tools["list_materials"]()
    rel = next(line for line in listing.splitlines() if line.endswith("经历.txt"))
    body = tools["read_material"](rel)
    assert body
    assert "INDEX.txt" in material_tools(agent.materials_root)[0]("")

    # Failure injection only: Agent ctor boom releases prepared tree, keeps primary.
    prepared_roots: list[str] = []

    def tracking_prepare(*args, **kwargs):
        prepared = prepare_character_materials(*args, **kwargs)
        prepared_roots.append(str(prepared.root))
        return prepared

    def boom_agent(**_kwargs):
        raise RuntimeError("agent-ctor-boom")

    cfg = LLMConfig(api_key="", base_url="", model="test", channel="cli", cli_runner="codex")
    with patch("ming_sim.registry.Agent", side_effect=boom_agent), \
         patch("ming_sim.registry.create_chat_model", return_value=MagicMock()), \
         patch("ming_sim.registry.prepare_character_materials", side_effect=tracking_prepare):
        with pytest.raises(RuntimeError, match="agent-ctor-boom"):
            create_minister_agent(character, cfg, _ctx(game), agno_db)
    assert prepared_roots and not Path(prepared_roots[-1]).exists()
    assert not Path(prepared_roots[-1]).parent.exists()

    # materials_root binding failure likewise releases ownership — no silent pass.
    bind_roots: list[str] = []

    def tracking_prepare_bind(*args, **kwargs):
        prepared = prepare_character_materials(*args, **kwargs)
        bind_roots.append(str(prepared.root))
        return prepared

    class _NoMaterialsAttr:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                object.__setattr__(self, key, value)

        def __setattr__(self, key, value):
            if key == "materials_root":
                raise AttributeError("materials_root frozen")
            object.__setattr__(self, key, value)

    with patch("ming_sim.registry.Agent", side_effect=lambda **kw: _NoMaterialsAttr(**kw)), \
         patch("ming_sim.registry.create_chat_model", return_value=MagicMock()), \
         patch("ming_sim.registry.prepare_character_materials", side_effect=tracking_prepare_bind):
        with pytest.raises(AttributeError, match="materials_root frozen"):
            create_minister_agent(character, cfg, _ctx(game), agno_db)
    assert bind_roots and not Path(bind_roots[-1]).exists()


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


def test_character_materials_exclude_legacy_raw_turn_report_and_keep_public_gazettes(
    game, tmp_path,
):
    """#883/#1832: raw turn_reports do not authorize person gazette files.

    Typed public counterparts still land under 公开说法/邸报/.
    """
    db, state, content = game
    character = _active_minister(db, content)
    legacy_marker = "LEGACY_RAW_GAZETTE_SHOULD_NOT_LEAK"
    db.conn.execute(
        "INSERT INTO turn_reports (turn, year, period, report, attendant_message) "
        "VALUES (?, ?, ?, ?, '')",
        (max(1, int(state.turn) + 7), 1628, 1, legacy_marker),
    )
    db.conn.commit()

    from ming_sim.models import GameState

    for month in range(1, 8):
        past = GameState(
            turn=month, year=1627, period=month, metrics=dict(state.metrics),
        )
        body = f"PUBLIC_GAZETTE_MONTH_{month}"
        db.record_public_knowledge_event(
            past, "邸报", body, source_id=f"turn_report:{month}:public",
        )
        db.conn.execute(
            "INSERT OR REPLACE INTO turn_reports (turn, year, period, report, attendant_message) "
            "VALUES (?, ?, ?, ?, '')",
            (month, 1627, month, body),
        )
    db.conn.commit()

    prepared = prepare_character_materials(
        db, state, character, dest_root=tmp_path / "char-gaz",
    )
    names = list_materials(prepared.root)
    gazette_paths = [p for p in names if p.startswith("公开说法/邸报/")]
    assert len(gazette_paths) == 7
    blob = "\n".join(read_material(prepared.root, p) for p in names if p != "INDEX.txt")
    assert legacy_marker not in blob
    assert not any(p.startswith("邸报/") and not p.startswith("公开说法/") for p in names)
    for month in range(1, 8):
        assert any(f"1627年{month}月.txt" in p for p in gazette_paths)
        assert f"PUBLIC_GAZETTE_MONTH_{month}" in blob


def test_secret_order_materials_keep_full_content_and_fail_loud_on_db_error(
    game, tmp_path, monkeypatch,
):
    db, state, content = game
    character = _active_minister(db, content)
    long_body = ("密令长正文-" * 20) + "-TAIL"
    assert len(long_body) > 80
    create_test_secret_order(
        db, state, character.name, "长密令", long_body, [], deadline_months=6,
    )
    prepared = prepare_character_materials(
        db, state, character, dest_root=tmp_path / "secret-ok",
    )
    secret_path = next(p for p in list_materials(prepared.root) if p.startswith("密令/"))
    secret_text = read_material(prepared.root, secret_path)
    assert "-TAIL" in secret_text
    assert long_body in secret_text

    def boom(_name):
        raise RuntimeError("secret-order-db-boom")

    monkeypatch.setattr(db, "get_active_secret_orders_for_minister", boom)
    with pytest.raises(RuntimeError, match="secret-order-db-boom"):
        prepare_character_materials(
            db, state, character, dest_root=tmp_path / "secret-fail",
        )
