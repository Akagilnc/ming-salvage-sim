"""#1830 S1：材料目录骨架与目录读取。

Seams: prepare_character_materials (directory + opening min set),
list_materials/read_material (API), CLI cwd/readonly flags, restore rebuild.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.dossier_test_helpers import create_test_secret_order

from ming_sim.materials import (
    MaterialsRoot,
    _handled_affair_lines,
    _safe_segment,
    _visible_affair_lines,
    list_materials,
    material_tools,
    prepare_character_materials,
    read_material,
)
from ming_sim.models import CourtContext


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
    for rel in names:
        if rel != "INDEX.txt":
            assert rel in index
            assert read_material(prepared.root, rel)
    roster = read_material(prepared.root, "人物/朝臣名册.txt")
    status, _reason = db.get_character_status(character.name)
    assert character.name in roster
    if character.office:
        assert character.office in roster
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
    army = db.conn.execute("SELECT id,name FROM armies ORDER BY id LIMIT 1").fetchone()
    # Real declaration entrance (not office_slots vacancy catalog / bare DB hook).
    from ming_sim.issues import apply_person_changes_only
    applied = apply_person_changes_only(
        db, state,
        [{
            "name": character.name,
            "动作": "任命",
            "office": "陕西巡抚",
            "office_type": "地方",
            "region_id": "shaanxi",
            "reason": "test-materials-posting",
        }],
        content=content,
    )["applied_person_changes"]
    assert applied and not applied[0].get("rejected"), applied
    db.conn.execute("UPDATE armies SET commander='' WHERE commander=?", (character.name,))
    db.conn.execute(
        "UPDATE armies SET commander=?,supply=17,morale=23,loyalty=31,training=44,equipment=52 "
        "WHERE id=?", (character.name, army["id"]),
    )
    db.conn.execute(
        "UPDATE regions SET public_support=13,unrest=87 WHERE id=?", ("shaanxi",),
    )
    db.conn.commit()

    prepared = prepare_character_materials(db, state, character, dest_root=tmp_path / "materials")
    names = list_materials(prepared.root)
    region_paths = [path for path in names if path.startswith("地区/")]
    army_paths = [path for path in names if path.startswith("军队/")]
    assert len(region_paths) == 1 and len(army_paths) == 1



def _agent_with_materials(root: Path, *, with_cli_cwd: bool):
    """Minimal agent stand-in: MaterialsRoot always; materials_dir only for CLI."""
    handle = MaterialsRoot(root)
    model = SimpleNamespace()
    if with_cli_cwd:
        model.materials_dir = handle.root
    return SimpleNamespace(model=model, materials_root=handle)


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
    issue_paths = {path for path in list_materials(prepared.root) if path.startswith("事务/issue-")}
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
    spaced_rel = f"人物/{_safe_segment('John Doe')}/经历.txt"
    spaced_path = prepared.root / spaced_rel
    spaced_path.parent.mkdir(parents=True, exist_ok=True)
    spaced_path.write_text("经历正文\n", encoding="utf-8")
    listing = tools["list_materials"]("")
    assert spaced_rel in listing.splitlines()
    assert tools["read_material"](spaced_rel) == "经历正文\n"
    gazette_rel = "邸报/1627年9月.txt"
    gazette_path = prepared.root / gazette_rel
    gazette_path.parent.mkdir(parents=True, exist_ok=True)
    gazette_path.write_text("本月邸报\n", encoding="utf-8")
    display = f"{gazette_rel} 任意非路径后缀"
    assert tools["read_material"](gazette_rel) == "本月邸报\n"
    with pytest.raises(FileNotFoundError):
        read_material(prepared.root, display)
    miss = tools["read_material"](display)
    assert miss
    assert "本月邸报" not in miss


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
    db.conn.execute(
        "UPDATE turn_reports SET title=? WHERE turn=?",
        ("辽东标题", 1),
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
    index = read_material(prepared.root, "INDEX.txt")
    assert all(rel in index for rel in gazette_paths)
    assert "辽东标题" in index
    assert "PUBLIC_GAZETTE_MONTH_1" not in index


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
