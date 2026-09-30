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
    close_night,
    open_night,
    summon_enter,
)
from ming_sim.materials import (
    MaterialsRoot,
    _handled_affair_lines,
    _safe_segment,
    _visible_affair_lines,
    list_materials,
    material_tools,
    prepare_character_materials,
    read_material,
    release_material_tree,
)
from ming_sim.models import CourtContext, LLMConfig
from ming_sim.registry import create_scene_agent
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
    listed = set(names)
    for line in index.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped in listed:
            assert read_material(prepared.root, stripped)
        else:
            assert any(stripped.startswith(rel + " ") for rel in listed)
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
    region_text = read_material(prepared.root, region_paths[0])
    army_text = read_material(prepared.root, army_paths[0])
    region_name = db.conn.execute(
        "SELECT name FROM regions WHERE id=?", ("shaanxi",),
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
    assert miss.startswith("无法读取：")
    assert "本月邸报" not in miss


def test_character_materials_exclude_legacy_raw_turn_report_and_keep_public_gazettes(
    game, tmp_path,
):
    """#883/#1832: raw turn_reports do not authorize person gazette files.

    Typed public counterparts still land under 公开说法/邸报/。契约只落结构化
    字段：载体路径集合（数量与所属月份）、INDEX 行只由路径＋朝代月标签＋已入档
    标题拼成。不扫描合并正文找固定片段——载体归属与准入由路径集合承担。
    """
    db, state, content = game
    character = _active_minister(db, content)
    db.conn.execute(
        "INSERT INTO turn_reports (turn, year, period, report, attendant_message) "
        "VALUES (?, ?, ?, ?, '')",
        (max(1, int(state.turn) + 7), 1628, 1, "raw turn report body"),
    )
    db.conn.commit()

    from ming_sim.models import GameState, reign_period_label

    for month in range(1, 8):
        past = GameState(
            turn=month, year=1627, period=month, metrics=dict(state.metrics),
        )
        db.record_public_knowledge_event(
            past, "邸报", f"gazette body {month}", source_id=f"turn_report:{month}:public",
        )
        db.conn.execute(
            "INSERT OR REPLACE INTO turn_reports (turn, year, period, report, attendant_message) "
            "VALUES (?, ?, ?, ?, '')",
            (month, 1627, month, f"gazette body {month}"),
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
    # 载体路径集合恰是七份已入档 typed 公开邸报；那份只有 raw report 的 1628 年
    # 记录不产生任何人物邸报载体。
    assert gazette_paths == [
        f"公开说法/邸报/1627年{month}月.txt" for month in range(1, 8)
    ]
    assert not any(p.startswith("邸报/") for p in names)
    index_lines = read_material(prepared.root, "INDEX.txt").splitlines()
    rel = next(p for p in gazette_paths if p.endswith("1627年1月.txt"))
    titled = next(
        line for line in index_lines
        if line.strip() == rel or line.strip().startswith(rel + " ")
    )
    # 索引行 = 路径 + 朝代月标签 + 已入档标题；不夹带报告正文。
    assert set(titled.split()) == {rel, reign_period_label(1627, 1), "辽东标题"}


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
