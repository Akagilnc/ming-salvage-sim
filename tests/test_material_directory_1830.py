"""#1830 S1：材料目录骨架与目录读取。

Seams: prepare_character_materials (directory + opening min set),
list_materials/read_material (API), CLI cwd/readonly flags, restore rebuild.
"""

from __future__ import annotations


import pytest
from tests.dossier_test_helpers import create_test_secret_order

from ming_sim.materials import (
    _safe_segment,
    list_materials,
    material_tools,
    prepare_character_materials,
    read_material,
)


def _active_minister(db, content, *, office_type=None):
    for character in content.characters.values():
        if character.office_type in ("后宫", "宗藩"):
            continue
        if office_type and character.office_type != office_type:
            continue
        if db.characters.get_character_status(character.name)[0] == "active":
            return character
    raise AssertionError("no active minister")


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
    status, _reason = db.characters.get_character_status(character.name)


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


def test_opening_handled_matters_are_filtered_within_authorized_knowledge(
    game, tmp_path, monkeypatch,
):
    """Real issue entry + prepare: handled roster lands in opening; bare issue stays out."""
    import ming_sim.materials as materials_mod

    db, state, content = game
    character = _active_minister(db, content)
    handled_id = db.insert_issue(
        state,
        kind="situation",
        title="经手事项",
        participants=[{"character_id": character.name, "tier": "主办"}],
    )
    other_id = db.insert_issue(
        state,
        kind="situation",
        title="无人承办事项",
        participants=[],
    )
    captured: dict[str, object] = {}
    real_opening = materials_mod.minimal_opening_context

    def _spy_opening(character_arg, state_arg, present, affairs, spoken):
        # 实际消费入参：affairs 结构化 id，不扫 opening 自由正文。
        captured["affair_ids"] = [item.get("id") for item in affairs]
        return real_opening(character_arg, state_arg, present, affairs, spoken)

    monkeypatch.setattr(materials_mod, "minimal_opening_context", _spy_opening)
    prepared = prepare_character_materials(
        db, state, character, dest_root=tmp_path / "materials",
    )

    affair_ids = {
        int(i) for i in (captured.get("affair_ids") or [])
        if str(i).isdigit()
    }
    assert int(handled_id) in affair_ids
    assert int(other_id) not in affair_ids
    # 字段搬运：经手 title 进入 opening 原文（非身份 oracle）
    handled_title = db.conn.execute(
        "SELECT title FROM issues WHERE id=?", (int(handled_id),),
    ).fetchone()["title"]
    assert str(handled_title or "") in prepared.opening
    issue_paths = {
        line for line in prepared.index_lines
        if line.startswith("事务/issue-")
    }
    assert any(f"issue-{handled_id}/" in line for line in issue_paths)
    assert other_id != handled_id


def test_prepare_fails_loud_when_dossier_read_breaks(game, tmp_path):
    """dossier 读失败响亮上抛；来源保真：冒出的须是注入的原异常对象，不锁诊断措辞。"""
    db, state, content = game
    character = _active_minister(db, content)

    fault = RuntimeError("dossier boom")

    def boom(*_a, **_k):
        raise fault

    db.list_referenceable_dossiers = boom
    try:
        prepare_character_materials(db, state, character, dest_root=tmp_path / "m")
        raise AssertionError("expected fail loud")
    except RuntimeError as exc:
        assert exc is fault


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

    from ming_sim.models import GameState, reign_period_label

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
    assert not any(p.startswith("邸报/") and not p.startswith("公开说法/") for p in names)
    for month in range(1, 8):
        assert any(f"1627年{month}月.txt" in p for p in gazette_paths)
    rel = next(p for p in gazette_paths if p.endswith("1627年1月.txt"))
    assert rel.startswith("公开说法/邸报/")


def test_secret_order_material_read_failure_propagates(
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
    next((p for p in list_materials(prepared.root) if p.startswith('密令/')))

    fault = RuntimeError("secret-order-db-boom")

    def boom(_name):
        raise fault

    monkeypatch.setattr(db.character_knowledge, "get_active_secret_orders_for_minister", boom)
    with pytest.raises(RuntimeError):
        prepare_character_materials(
            db, state, character, dest_root=tmp_path / "secret-fail",
        )
    assert ei.value is fault
