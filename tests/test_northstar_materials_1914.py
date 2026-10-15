"""#1914：近侍底账、派系态势、人物行止进可读材料。

验收入口（票面行为）：
- 真实召对入口开夜 → prepare_scene_materials：近侍 knowledge/公事档案接通官缺与省况键
- 真实过月/召对材料入口：派系态势路径在册
- 真实过月入口：人物行止（含非在朝）按人结构化字段可读

契约只落路径与机器字段；不锁人读措辞、不埋散文哨兵。
"""

from __future__ import annotations

from ming_sim.audience_night import open_night
from ming_sim.knowledge import build_character_knowledge
from ming_sim.materials import (
    _safe_segment,
    list_materials,
    prepare_scene_materials,
    prepare_world_materials,
    read_material,
)


_STANCE_REL = "盘面/派系态势.txt"


def _parse_machine_fields(body: str) -> dict[str, str]:
    """Parse ``key：value`` machine-marker lines; ignore free-prose residue."""
    fields: dict[str, str] = {}
    for line in str(body or "").splitlines():
        if "：" not in line:
            continue
        key, value = line.split("：", 1)
        key = key.strip()
        if key:
            fields[key] = value.strip()
    return fields


def test_scene_open_night_attendant_gets_vacancy_and_province_keys(game, tmp_path):
    """从真实召对入口开夜：近侍 world 接通 personnel/regional，公事档案非空。"""
    db, state, _content = game
    open_night(db, state, location="乾清宫", time_of_day="夜")

    prepared = prepare_scene_materials(db, state, dest_root=tmp_path / "scene")
    office_rel = f"人物/{_safe_segment('王承恩')}/公事档案.txt"
    assert office_rel in list_materials(prepared.root)
    # 可读性：路径在册且可读通；供料接通由 knowledge 结构化键证明，不锁占位措辞。
    read_material(prepared.root, office_rel)

    world = build_character_knowledge(db, state, "王承恩")["world"]
    assert str(world.get("personnel") or "").strip()
    assert str(world.get("regional") or "").strip()


def test_faction_stance_path_in_world_and_next_scene_materials(game, tmp_path):
    """派系态势写入后，世界材料与下一场召对材料目录均有态势路径。"""
    db, state, _content = game
    db.apply_faction_brew_result(
        faction="东林",
        stance_segment="东林与帝渐行渐远",
        last_event_id=1,
        turn=int(state.turn),
        year=int(state.year),
        period=int(state.period),
    )

    world = prepare_world_materials(db, state, dest_root=tmp_path / "world")
    assert _STANCE_REL in list_materials(world.root)

    open_night(db, state, location="乾清宫", time_of_day="夜")
    scene = prepare_scene_materials(db, state, dest_root=tmp_path / "scene-next")
    assert _STANCE_REL in list_materials(scene.root)


def test_world_whereabouts_cover_off_court_and_unranked_with_bound_fields(
    game, tmp_path,
):
    """过月材料：离朝／未仕人物行止按人落 location_id／transit_to_id。"""
    db, state, content = game
    off_court = "徐光启"
    unranked = "史可法"
    active_names = {
        row["name"]
        for row in db.characters.current_court_rows(int(state.year), int(state.period))
    }
    assert off_court not in active_names

    unranked_row = db.conn.execute(
        "SELECT office_type, status FROM characters WHERE name=?",
        (unranked,),
    ).fetchone()
    assert unranked_row is not None
    assert str(unranked_row["office_type"] or "") == "未仕" or unranked not in active_names

    db.characters.update(off_court, {"location": "nanzhili"})
    db.set_character_transit(
        unranked,
        transit_to="shaanxi",
        distance_remaining=2.0,
        speed_factor=1.0,
        start_turn=int(state.turn),
        location="henan",
        content=content,
    )
    db.conn.commit()

    prepared = prepare_world_materials(db, state, dest_root=tmp_path / "world-loc")
    names = list_materials(prepared.root)

    off_rel = f"人物/{_safe_segment(off_court)}/行止.txt"
    assert off_rel in names
    off_fields = _parse_machine_fields(read_material(prepared.root, off_rel))
    assert off_fields.get("location_id") == "nanzhili"
    assert "transit_to_id" not in off_fields

    travel_rel = f"人物/{_safe_segment(unranked)}/行止.txt"
    assert travel_rel in names
    travel_fields = _parse_machine_fields(read_material(prepared.root, travel_rel))
    assert travel_fields.get("location_id") == "henan"
    assert travel_fields.get("transit_to_id") == "shaanxi"
