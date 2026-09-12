"""#1834 [M18 供料] S4：推演者材料目录。

Seam: prepare_world_materials (directory + opening min set), reusing
list_materials/read_material (#1830 API, generic over any root).

大理寺 01a08e3a 裁定：本文件只留结构化契约（目录路径、INDEX 一致性、无裸
副本）；对盘面/事务/opening/经历/邸报等人读渲染文本的措辞或固定片段机械
断言（含哨兵）已整类删除，不得换形复造——`read_material` 越目录契约已由
tests/test_material_directory_1830.py 的同一泛化入口覆盖，不在此重复。
"""

from __future__ import annotations

from pathlib import Path

from ming_sim.db import GameDB
from ming_sim.materials import (
    list_materials, prepare_world_materials, read_material, world_materials_root,
)


def test_prepare_writes_typed_tree_with_board_affairs_and_gazette_index(game, tmp_path):
    db, state, content = game

    affair = db.affairs.open(
        name="宁远护送", origin="拨银、调将、派兵去宁远",
        year=state.year, period=state.period, turn=state.turn,
    )

    # 一份历史邸报（不同于当前 state.turn，模拟“历月”）：应变成目录里可读的一
    # 行索引项，且不再由已退役的章节记忆承担。
    past_year, past_period, past_turn = state.year, max(1, state.period - 1), max(0, state.turn - 1)
    from ming_sim.models import GameState
    past_state = GameState(turn=past_turn, year=past_year, period=past_period, metrics=dict(state.metrics))
    db.save_turn_report(past_state, "历月邸报正文")

    dest = tmp_path / "world-materials"
    prepared = prepare_world_materials(db, state, dest_root=dest)

    names = list_materials(prepared.root)
    assert "INDEX.txt" in names
    assert "盘面/全局.txt" in names
    assert "人物/朝臣名册.txt" in names
    assert any(p.startswith("人物/") and p.endswith("/经历.txt") for p in names)
    assert any(p.startswith(f"事务/affair-{affair.id}-") for p in names)
    assert any(p.startswith("邸报/") for p in names)

    index = read_material(prepared.root, "INDEX.txt")
    for line in index.splitlines():
        if line.strip():
            assert line.strip() in names

    # 无裸副本：不得直接倒出世界库/JSON。
    assert not any(n.lower().endswith((".db", ".sqlite", ".sqlite3", ".json")) for n in names)


def test_all_characters_get_an_experience_file_not_just_current_court(game, tmp_path):
    """大理寺 bounce 2：经历目录曾只给当前在朝名册白名单里的人，已离朝/致仕/未在
    朝的人物经历整条消失（#1819 决定 1：各人物经历三层全可读，不按当前在朝状态
    收窄）。挑一个真实不在当前朝臣名册里的人物，断言其经历文件仍存在于目录。"""
    db, state, content = game
    active_names = {row["name"] for row in db.current_court_roster_rows(state)}
    all_names = [
        row["name"] for row in db.conn.execute("SELECT name FROM characters ORDER BY name").fetchall()
    ]
    off_court = [name for name in all_names if name not in active_names]
    assert off_court, "fixture 需天然存在不在当前朝臣名册的人物"
    name = off_court[0]

    prepared = prepare_world_materials(db, state, dest_root=tmp_path / "m")
    names = list_materials(prepared.root)
    rel = next(
        (p for p in names if p.startswith("人物/") and p.endswith("/经历.txt") and name in p),
        None,
    )
    assert rel is not None, f"{name}（不在当前朝臣名册）应仍有经历文件"


def test_prepare_rebuilds_from_world_record_after_restore(game, tmp_path):
    db, state, content = game
    affair = db.affairs.open(
        name="宣府欠饷", origin="宣府镇奏报欠饷",
        year=state.year, period=state.period, turn=state.turn,
    )
    path = str(db.path)
    db.close()

    from ming_sim.db import GameDB
    restored = GameDB(path, content)
    try:
        state2 = restored.load_state()
        prepared = prepare_world_materials(restored, state2, dest_root=tmp_path / "m2")
        names = list_materials(prepared.root)
        assert any(p.startswith(f"事务/affair-{affair.id}-") for p in names)
    finally:
        restored.close()


def test_world_materials_isolate_invocations_and_databases(game, tmp_path, monkeypatch):
    db, state, content = game
    requested = tmp_path / "world"
    first = prepare_world_materials(db, state, dest_root=requested)
    second = prepare_world_materials(db, state, dest_root=requested)
    assert first.root != second.root
    assert read_material(first.root, "INDEX.txt")
    assert read_material(second.root, "INDEX.txt")

    other = GameDB(str(Path(db.path).parent / "other.db"), content)
    try:
        other.seed_static_data()
        other_state = other.load_state()

        class _Fixed:
            hex = "a" * 32

        monkeypatch.setattr("ming_sim.materials.uuid.uuid4", lambda: _Fixed())
        same_db = world_materials_root(db, state)
        assert same_db == world_materials_root(db, state)
        other_db = world_materials_root(other, other_state)
        assert same_db != other_db
    finally:
        other.close()


def test_world_materials_include_textual_facts_once_and_gazette_not_duplicated(game, tmp_path):
    """世界目录直读权威文字事实；邸报只走 邸报/ 载体，不复制进月度公开说法。"""
    db, state, content = game
    name = next(iter(content.characters))
    db.textual_facts.append(
        subject_kind="character", subject_id=name, body="世界可见人物文字事实",
        year=int(state.year), period=int(state.period), turn=int(state.turn),
    )
    region = db.conn.execute("SELECT id FROM regions ORDER BY id LIMIT 1").fetchone()
    db.textual_facts.append(
        subject_kind="region", subject_id=str(region["id"]), body="世界可见地方文字事实",
        year=int(state.year), period=int(state.period), turn=int(state.turn),
    )
    affair = db.affairs.open(
        name="事实探针事务", origin="probe",
        year=state.year, period=state.period, turn=state.turn,
    )
    db.textual_facts.append(
        subject_kind="affair", subject_id=str(affair.id), body="PROBE_AFFAIR_FACT_ONLY_ONCE",
        year=int(state.year), period=int(state.period), turn=int(state.turn),
        origin_ref=db.affairs.origin_ref(affair.id),
    )
    past_year, past_period, past_turn = state.year, max(1, state.period - 1), max(0, state.turn - 1)
    from ming_sim.models import GameState
    past_state = GameState(
        turn=past_turn, year=past_year, period=past_period, metrics=dict(state.metrics),
    )
    db.save_turn_report(past_state, "UNIQUE_WORLD_GAZETTE_BODY")

    prepared = prepare_world_materials(db, state, dest_root=tmp_path / "world-facts")
    names = list_materials(prepared.root)
    fact_paths = [p for p in names if p.startswith("事实/")]
    assert fact_paths
    fact_blob = "\n".join(read_material(prepared.root, p) for p in fact_paths)
    assert "世界可见人物文字事实" in fact_blob
    assert "世界可见地方文字事实" in fact_blob
    # affair textual facts ride 事务/ only — not a second 事实/affair-* carrier.
    assert not any(p.startswith("事实/affair-") for p in names)
    affair_paths = [p for p in names if p.startswith(f"事务/affair-{affair.id}-")]
    assert affair_paths
    affair_blob = "\n".join(read_material(prepared.root, p) for p in affair_paths)
    assert affair_blob.count("PROBE_AFFAIR_FACT_ONLY_ONCE") == 1

    gazette_paths = [p for p in names if p.startswith("邸报/")]
    assert gazette_paths
    gazette_blob = "\n".join(read_material(prepared.root, p) for p in gazette_paths)
    assert gazette_blob.count("UNIQUE_WORLD_GAZETTE_BODY") == 1
    public_paths = [p for p in names if p.startswith("公开说法/")]
    if public_paths:
        public_blob = "\n".join(read_material(prepared.root, p) for p in public_paths)
        assert "UNIQUE_WORLD_GAZETTE_BODY" not in public_blob
