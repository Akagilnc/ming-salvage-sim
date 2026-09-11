"""#1834 [M18 供料] S4：推演者材料目录。

Seam: prepare_world_materials (directory + opening min set), reusing
list_materials/read_material (#1830 API, generic over any root).

大理寺 01a08e3a 裁定：本文件只留结构化契约（目录路径、INDEX 一致性、无裸
副本）；对盘面/事务/opening/经历/邸报等人读渲染文本的措辞或固定片段机械
断言（含哨兵）已整类删除，不得换形复造——`read_material` 越目录契约已由
tests/test_material_directory_1830.py 的同一泛化入口覆盖，不在此重复。
"""

from __future__ import annotations

from ming_sim.materials import list_materials, prepare_world_materials, read_material


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
    assert any(p.startswith(f"事务/affair-{affair.id}/") for p in names)
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


def test_character_army_region_textual_facts_reach_world_directory(game, tmp_path):
    """#1828/#1834 缺口钉：textual_facts 写口早接好（declaration_dispatch 的
    R2 分派），但修前世界目录只读 affair 一种 subject_kind，人物/军队/地区的
    按月文字事实（负伤、欠饷加剧等）落库后无处可读——100% 不可达。写一条
    character/army/region 各一条真实文字事实，断言世界目录里能读到原文。"""
    db, state, content = game
    character_name = next(iter(content.characters))
    army_id = str(db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()["id"])
    region_id = str(db.conn.execute("SELECT id FROM regions LIMIT 1").fetchone()["id"])

    character_fact = "SENTINEL_CHARACTER_FACT_1828：右臂中箭，尚未痊愈"
    army_fact = "SENTINEL_ARMY_FACT_1828：欠饷已逾三月"
    region_fact = "SENTINEL_REGION_FACT_1828：旱情加剧，流民渐增"
    db.textual_facts.append(
        subject_kind="character", subject_id=character_name, body=character_fact,
        year=state.year, period=state.period, turn=state.turn,
    )
    db.textual_facts.append(
        subject_kind="army", subject_id=army_id, body=army_fact,
        year=state.year, period=state.period, turn=state.turn,
    )
    db.textual_facts.append(
        subject_kind="region", subject_id=region_id, body=region_fact,
        year=state.year, period=state.period, turn=state.turn,
    )

    prepared = prepare_world_materials(db, state, dest_root=tmp_path / "m3")
    names = list_materials(prepared.root)

    character_rel = next(
        (p for p in names if p.startswith("人物/") and p.endswith("/按月实况.txt") and character_name in p),
        None,
    )
    army_rel = next(
        (p for p in names if p.startswith(f"军队/{army_id}/按月实况.txt")), None,
    )
    region_rel = next(
        (p for p in names if p.startswith(f"地区/{region_id}/按月实况.txt")), None,
    )
    assert character_rel and army_rel and region_rel, "三类对象的按月实况文件均应在世界目录里"
    assert character_fact in read_material(prepared.root, character_rel)
    assert army_fact in read_material(prepared.root, army_rel)
    assert region_fact in read_material(prepared.root, region_rel)


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
        assert any(p.startswith(f"事务/affair-{affair.id}/") for p in names)
    finally:
        restored.close()
