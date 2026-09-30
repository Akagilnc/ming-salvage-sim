"""#1830 S1：同一公开记录经场景／单人／世界三类目录的准入一致（共用读侧契约）。

现象（两轮）：其一，场景目录的 _write_one_present_person 曾自行逐条写 公开说法/，
与 _write_public_by_month 的邸报排除门分叉；其二，改走共用入口后，单人目录仍留一份
render_character_knowledge 的整体重投影 人物/<名>/见闻.txt——world.public 把公开层
正文再拼一遍，public_events/events 又逐条重述，于是同一条邸报同时可经
公开说法/邸报/ 与 见闻.txt 读到。公开材料因此存在非既定重复载体。

大理寺 de0b3b266 判词（#1830 终审）：契约断言只落结构化字段——路径集合、载体归属、
行数与 INDEX／工具一致性；禁止对材料正文、固定片段或人读渲染措辞做哨兵断言及其换形
复造。「每份公开材料只经一个载体可读」由路径集合划分与行数守恒证明；密令不泄出由
「密令落库后公开层形状逐字节不变」证明；开场最小集由「公开记录落库不改变 opening
字节」证明。三者都不比对正文措辞。
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
from ming_sim.public_sayings import list_public_sayings, record_public_saying
from tests.dossier_test_helpers import create_test_secret_order


def _active_minister(db, content):
    for character in content.characters.values():
        if character.office_type in ("后宫", "宗藩"):
            continue
        if db.get_character_status(character.name)[0] == "active":
            return character
    raise AssertionError("no active minister")


def _seed_public_world(db, state):
    """一条独立公开说法 + 一份已落邸报（各带真实年月，供路径契约使用）。"""
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


def _layer_shape(root, prefix):
    """公开层的结构化形状：相对路径 → 行数。不含任何正文内容。"""
    return {
        path[len(prefix):]: len(read_material(root, path).splitlines())
        for path in list_materials(root)
        if path.startswith(prefix)
    }


def _public_layer(root, prefix):
    """公开层按既定载体划分：按月公开说法 vs 邸报载体。"""
    shape = _layer_shape(root, prefix)
    return (
        {rel: n for rel, n in shape.items() if not rel.startswith("邸报/")},
        {rel: n for rel, n in shape.items() if rel.startswith("邸报/")},
    )


def test_scene_person_public_layer_matches_character_and_world_admission(game, tmp_path):
    """三类目录公开层同形；邸报只经既定载体；单人目录无第二处综合公开投影。"""
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

    scene_by_month, scene_gazette = _public_layer(
        scene.root, f"人物/{character.name}/公开说法/",
    )
    solo_by_month, solo_gazette = _public_layer(solo.root, "公开说法/")
    world_by_month, _unused = _public_layer(world.root, "公开说法/")
    # 推演者的历月邸报是顶层 邸报/ 载体（_write_world_tree），不在公开说法子树内。
    world_gazette = _layer_shape(world.root, "邸报/")

    # 准入一致：三类目录的按月公开说法路径与行数完全同形。
    assert scene_by_month, "场景人物仍应有自己的公开说法层"
    assert scene_by_month == solo_by_month == world_by_month
    # 邸报只经既定载体：人物目录 公开说法/邸报/，推演者顶层 邸报/，各只一份。
    # （同一月可以同时有公开说法与邸报——那是两份不同材料、两个既定载体，不是重复；
    # 「同一份公开材料不被重投影」由下面按月行数守恒与 test_public_layer_carrier_
    # count_is_conserved 证明，不靠文件名不相交这种巧合。）
    assert scene_gazette == solo_gazette
    assert scene_gazette and world_gazette
    assert set(world_gazette) == {rel.removeprefix("邸报/") for rel in scene_gazette}
    # 世界目录不另生 公开说法/邸报/ 副本（推演者的邸报只在顶层 邸报/）。
    assert not any(
        path.startswith("公开说法/邸报/") for path in list_materials(world.root)
    )

    # 单人目录的人物子树只有既定载体：朝臣名册 + 本人经历 + 本人公事档案。
    # 修前这里多一份 人物/<名>/见闻.txt，把公开层正文整体重渲一遍。
    person_paths = {
        path for path in list_materials(solo.root) if path.startswith("人物/")
    }
    assert person_paths == {
        "人物/朝臣名册.txt",
        f"人物/{character.name}-51448653368b/经历.txt",
        f"人物/{character.name}-51448653368b/公事档案.txt",
    }

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
    gazette_rel = next(
        path for path in list_materials(scene.root)
        if path.startswith(f"人物/{character.name}/公开说法/邸报/")
    )
    assert tools["read_material"](gazette_rel) == read_material(scene.root, gazette_rel)


def test_public_layer_carrier_count_is_conserved(game, tmp_path):
    """密令不借公开层泄出；重建只按新记录增一份载体，不复制既有载体。"""
    db, state, content = game
    character = _active_minister(db, content)
    _seed_public_world(db, state)

    def shape(dest):
        solo = prepare_character_materials(
            db, state, character, dest_root=tmp_path / dest,
        )
        return solo, _public_layer(solo.root, "公开说法/")

    solo_before, (before_by_month, before_gazette) = shape("before")
    create_test_secret_order(
        db, state, character.name, "探针密令", "密令探针正文", [], deadline_months=6,
    )
    _, (after_by_month, after_gazette) = shape("after")
    # 密令只进 密令/ 载体；公开层两份载体清单与行数一概不变。
    assert (before_by_month, before_gazette) == (after_by_month, after_gazette)
    assert any(path.startswith("密令/") for path in list_materials(solo_before.root))

    later = GameState(
        turn=int(state.turn) + 1, year=int(state.year) + 60, period=7,
        metrics=dict(state.metrics),
    )
    record_public_saying(db, later, "后落公开说法")
    rebuilt = prepare_character_materials(
        db, state, character, dest_root=tmp_path / "rebuilt",
    )
    rebuilt_by_month, rebuilt_gazette = _public_layer(rebuilt.root, "公开说法/")
    # 新记录恰好新增自己那一月的一份载体；既有月份行数与邸报载体均不动。
    assert set(rebuilt_by_month) - set(before_by_month) == {
        f"{later.year}年{later.period}月.txt",
    }
    assert rebuilt_gazette == before_gazette
    for rel, lines in before_by_month.items():
        assert rebuilt_by_month[rel] == lines, rel


def test_openings_stay_minimum_sets_after_projection_unification(game, tmp_path):
    """开场仍只给最小集：公开记录落库不改变 opening 字节，重备后目录可读到更新。"""
    db, state, content = game
    character = _active_minister(db, content)
    _seed_public_world(db, state)

    solo = prepare_character_materials(db, state, character, dest_root=tmp_path / "s1")
    world = prepare_world_materials(db, state, dest_root=tmp_path / "w1")

    later = GameState(
        turn=int(state.turn) + 1, year=int(state.year) + 60, period=7,
        metrics=dict(state.metrics),
    )
    record_public_saying(db, later, "后落公开说法")
    rebuilt = prepare_character_materials(db, state, character, dest_root=tmp_path / "s2")
    rebuilt_world = prepare_world_materials(db, state, dest_root=tmp_path / "w2")

    # 开场最小集不随公开层增长而膨胀（结构化相等，不盯 opening 措辞）。
    assert solo.opening == rebuilt.opening
    assert world.opening == rebuilt_world.opening
    # 目录侧仍读到更新：新增记录那一月的载体在重建后可达。
    assert f"公开说法/{later.year}年{later.period}月.txt" in list_materials(rebuilt.root)
