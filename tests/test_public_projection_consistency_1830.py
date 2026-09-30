"""#1830 S1：同一公开记录经场景／单人／世界三类目录的准入一致（共用读侧契约）。

现象：场景目录的 _write_one_present_person 自行逐条写 公开说法/，与 _write_public_by_month
的邸报排除门分叉——同一条已落邸报在场景里混入公开说法，而单人／世界目录只放进既定
邸报载体。本文件钉契约：准入与载体同形，密令不借公开层泄出，开场仍限最小集。
"""

from __future__ import annotations

from ming_sim.audience_night import get_open_night, open_night, present_names_at, summon_enter
from ming_sim.materials import (
    list_materials,
    material_tools,
    prepare_character_materials,
    prepare_scene_materials,
    prepare_world_materials,
    read_material,
)
from ming_sim.models import GameState
from ming_sim.public_sayings import record_public_saying
from tests.dossier_test_helpers import create_test_secret_order


def _active_minister(db, content):
    for character in content.characters.values():
        if character.office_type in ("后宫", "宗藩"):
            continue
        if db.get_character_status(character.name)[0] == "active":
            return character
    raise AssertionError("no active minister")


def _seed_public_world(db, state):
    """一条独立公开说法 + 一份已落邸报 + 一条密令。"""
    from ming_sim.public_sayings import list_public_sayings

    saying_state = GameState(
        turn=int(state.turn), year=int(state.year) + 50, period=6,
        metrics=dict(state.metrics),
    )
    record_public_saying(db, saying_state, "公开说法探针正文")
    assert any(True for _ in list_public_sayings(db))

    past_state = GameState(
        turn=max(1, int(state.turn)), year=int(state.year) - 1,
        period=max(1, int(state.period) - 1), metrics=dict(state.metrics),
    )
    # 邸报的公开层来源是已入档的公开说法载体（turn_report:<turn>:public），
    # 与归档标题（turn_reports.title）各司其职——与 #1830 人物目录同一条真源。
    db.record_public_knowledge_event(
        past_state, "邸报", "邸报探针正文",
        source_id=f"turn_report:{past_state.turn}:public",
    )
    db.save_turn_report(past_state, "邸报探针正文", title="辽东告急")
    return saying_state, past_state


def _public_texts(root, prefix):
    return {
        path: read_material(root, path)
        for path in list_materials(root)
        if path.startswith(prefix)
    }


def test_scene_person_public_layer_matches_character_and_world_admission(game, tmp_path):
    """场景人物私有子树：邸报不混入公开说法，且只经既定邸报载体可读。"""
    db, state, content = game
    character = _active_minister(db, content)
    _seed_public_world(db, state)
    create_test_secret_order(
        db, state, character.name, "探针密令", "密令探针正文", [],
        deadline_months=6,
    )

    open_night(db, state, location="乾清宫", time_of_day="夜")
    night = get_open_night(db)
    assert night is not None
    night_id = int(night["id"])
    if character.name not in present_names_at(db, night_id):
        summon_enter(db, night_id, character.name)

    scene = prepare_scene_materials(db, state, dest_root=tmp_path / "scene")
    solo = prepare_character_materials(db, state, character, dest_root=tmp_path / "solo")
    world = prepare_world_materials(db, state, dest_root=tmp_path / "world")

    scene_public = _public_texts(scene.root, f"人物/{character.name}/公开说法/")
    assert scene_public, "场景人物仍应有自己的公开说法层"
    # 邸报有既定载体：按月公开说法里不得再重复承载它，且载体本身应在。
    gazette_paths = [p for p in scene_public if "/公开说法/邸报/" in p]
    for path, body in scene_public.items():
        if path in gazette_paths:
            continue
        assert "邸报探针正文" not in body, f"邸报经公开说法重复出现：{path}"
        assert "密令探针正文" not in body
    assert gazette_paths, "场景人物目录应保留本人有权读取的历月邸报载体"
    assert any("邸报探针正文" in scene_public[p] for p in gazette_paths)

    # 同类公开说法在三类目录都可达，且都带同一条独立公开说法。
    solo_public = _public_texts(solo.root, "公开说法/")
    world_public = _public_texts(world.root, "公开说法/")
    for tree, prefix in (
        (scene.root, f"人物/{character.name}/公开说法/"),
        (solo.root, "公开说法/"),
        (world.root, "公开说法/"),
    ):
        bodies = "\n".join(
            body for path, body in _public_texts(tree, prefix).items()
            if "/邸报/" not in path
        )
        assert "公开说法探针正文" in bodies, prefix
        assert "邸报探针正文" not in bodies, prefix
        assert "密令探针正文" not in bodies, prefix

    # 场景每份材料都在 INDEX 里，API 列目录／读文件读到同一内容。
    index = read_material(scene.root, "INDEX.txt")
    for path in list_materials(scene.root):
        if path == "INDEX.txt":
            continue
        assert any(
            line.strip() == path or line.strip().startswith(path + " ")
            for line in index.splitlines()
        ), path
    tools = {tool.__name__: tool for tool in material_tools(scene.root)}
    assert set(tools["list_materials"]("").splitlines()) == set(list_materials(scene.root))
    gazette_rel = next(p for p in gazette_paths)
    assert tools["read_material"](gazette_rel) == read_material(scene.root, gazette_rel)


def test_openings_stay_minimum_sets_after_projection_unification(game, tmp_path):
    """开场仍只给各自已定最小集；目录落定新记录后重备可读到更新。"""
    db, state, content = game
    character = _active_minister(db, content)
    _seed_public_world(db, state)

    solo = prepare_character_materials(db, state, character, dest_root=tmp_path / "s1")
    world = prepare_world_materials(db, state, dest_root=tmp_path / "w1")
    assert "公开说法探针正文" not in solo.opening
    assert "公开说法探针正文" not in world.opening
    assert "邸报探针正文" not in solo.opening
    assert "邸报探针正文" not in world.opening

    later = GameState(
        turn=int(state.turn) + 1, year=int(state.year) + 60, period=7,
        metrics=dict(state.metrics),
    )
    record_public_saying(db, later, "后落公开说法")
    rebuilt = prepare_character_materials(db, state, character, dest_root=tmp_path / "s2")
    bodies = "\n".join(_public_texts(rebuilt.root, "公开说法/").values())
    assert "后落公开说法" in bodies
