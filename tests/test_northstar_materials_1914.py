"""#1914：近侍底账、派系态势、在途人物进可读材料。

验收入口（票面行为）：
- 真实召对入口开夜 → prepare_scene_materials：御前近侍材料含官缺与各省概况
- 真实过月材料入口 prepare_world_materials：派系态势写入后，世界与下一场召对材料可读
- 真实过月材料入口：名册含人物所在地，以及在途人物去向

契约只落结构化可读性（路径在册、fixture 自写字段回读）；不锁人读措辞模板。
"""

from __future__ import annotations

from ming_sim.audience_night import open_night
from ming_sim.materials import list_materials, prepare_scene_materials, prepare_world_materials, read_material


def _wang_cheng_en_segment(db) -> str:
    from ming_sim.materials import _safe_segment

    return _safe_segment("王承恩")


def test_scene_open_night_attendant_materials_include_vacancy_and_province_overview(
    game, tmp_path,
):
    """从真实召对入口开夜：御前近侍可读材料里有官缺与各省概况。"""
    db, state, _content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")

    vacancy_titles = [
        str(row["office_title"])
        for row in db.conn.execute(
            "SELECT office_title FROM office_vacancies ORDER BY sort_order, office_title"
        ).fetchall()
    ]
    assert vacancy_titles, "开局须有 office_vacancies 底账"
    province_names = [
        str(row["name"])
        for row in db.conn.execute("SELECT name FROM regions ORDER BY name").fetchall()
        if str(row["name"] or "").strip()
    ]
    assert province_names, "开局须有地区档"

    prepared = prepare_scene_materials(db, state, dest_root=tmp_path / "scene")
    names = list_materials(prepared.root)
    office_rel = f"人物/{_wang_cheng_en_segment(db)}/公事档案.txt"
    assert office_rel in names

    office_body = read_material(prepared.root, office_rel)
    for title in vacancy_titles:
        assert title in office_body
    # 各省概况：至少覆盖多省名称（概况投影，不锁句式）
    hit = sum(1 for name in province_names if name in office_body)
    assert hit >= min(5, len(province_names))


def test_faction_stance_readable_after_write_in_world_and_next_scene(game, tmp_path):
    """经真实过月入口写入派系态势后，世界材料与下一场召对材料可读到。"""
    db, state, _content = game
    faction = "东林"
    stance = "东林与帝渐行渐远·1914探针"
    db.apply_faction_brew_result(
        faction=faction,
        stance_segment=stance,
        last_event_id=1,
        turn=int(state.turn),
        year=int(state.year),
        period=int(state.period),
    )

    world = prepare_world_materials(db, state, dest_root=tmp_path / "world")
    world_names = list_materials(world.root)
    stance_rel = "盘面/派系态势.txt"
    assert stance_rel in world_names
    world_body = read_material(world.root, stance_rel)
    assert faction in world_body
    assert stance in world_body

    open_night(db, state, location="乾清宫", time_of_day="夜")
    scene = prepare_scene_materials(db, state, dest_root=tmp_path / "scene-next")
    scene_names = list_materials(scene.root)
    assert stance_rel in scene_names
    scene_body = read_material(scene.root, stance_rel)
    assert faction in scene_body
    assert stance in scene_body


def test_world_roster_includes_location_and_in_transit_destination(game, tmp_path):
    """经真实过月入口：推演材料有人物所在地，以及在途人物去向。"""
    db, state, content = game
    located = "毕自严"
    traveler = "王绍徽"
    dest_id = "shaanxi"
    dest_name = str(content.regions[dest_id].name)

    db.characters.update(located, {"location": "henan"})
    db.set_character_transit(
        traveler,
        transit_to=dest_id,
        distance_remaining=2.0,
        speed_factor=1.0,
        start_turn=int(state.turn),
        location="nanzhili",
        content=content,
    )
    db.conn.commit()

    prepared = prepare_world_materials(db, state, dest_root=tmp_path / "world-loc")
    roster = read_material(prepared.root, "人物/朝臣名册.txt")

    # 所在地：河南（id 或中文名任一可读投影）
    assert located in roster
    assert ("henan" in roster) or ("河南" in roster)

    # 在途去向
    assert traveler in roster
    assert (dest_id in roster) or (dest_name in roster)
    assert "在途" in roster or dest_name in roster or dest_id in roster
