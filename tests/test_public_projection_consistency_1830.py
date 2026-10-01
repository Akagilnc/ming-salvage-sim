"""#1830 S1：同一公开记录经场景／单人／世界三类目录的准入一致（共用读侧契约）。

现象（两轮）：其一，场景目录的 _write_one_present_person 曾自行逐条写 公开说法/，
与 _write_public_by_month 的邸报排除门分叉；其二，改走共用入口后，单人目录仍留一份
render_character_knowledge 的整体重投影 人物/<名>/见闻.txt——world.public 把公开层
正文再拼一遍，public_events/events 又逐条重述，于是同一条邸报同时可经
公开说法/邸报/ 与 见闻.txt 读到。公开材料因此存在非既定重复载体。

契约面：来源身份、载体路径集合、载体归属、INDEX 与工具一致性；终端文件
及两种读取入口保留独立输入原文，不规定标题／正文分隔符、记录顺序或拼接
换行。原文存在不替代 source_id 的准入证明，也不证明同正文记录的出现次数。
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


def _layer_paths(root, prefix):
    """公开层的结构化形状：相对路径集合。不读任何正文。"""
    return {
        path[len(prefix):] for path in list_materials(root)
        if path.startswith(prefix)
    }


def _public_layer(root, prefix):
    """公开层按既定载体划分：按月公开说法 vs 邸报载体。"""
    shape = _layer_paths(root, prefix)
    return (
        {rel for rel in shape if not rel.startswith("邸报/")},
        {rel for rel in shape if rel.startswith("邸报/")},
    )


def test_scene_person_public_layer_matches_character_and_world_admission(game, tmp_path):
    """三类目录公开层同形；邸报只经既定载体；单人目录无第二处综合公开投影。"""
    db, state, content = game
    character = _active_minister(db, content)
    _seed_public_world(db, state)

    open_night(db, state, location="乾清宫", time_of_day="夜")
    night = get_open_night(db)
    assert night is not None
    night_id = int(night["id"])
    if character.name not in present_names_at(db, night_id):
        summon_enter(db, night_id, character.name)

    shared_year, shared_period = int(state.year) + 80, 3
    shared_state = GameState(
        turn=int(state.turn) + 3, year=shared_year, period=shared_period,
        metrics=dict(state.metrics),
    )
    shared = "  赈济已奉准。\r\n原文第二段。  \r"
    db.record_public_knowledge_event(
        shared_state, "陕西赈务", shared, source_id="judge:shaanxi",
    )
    db.record_public_knowledge_event(
        shared_state, "河南赈务", shared, source_id="judge:henan",
    )

    scene = prepare_scene_materials(db, state, dest_root=tmp_path / "scene")
    solo = prepare_character_materials(db, state, character, dest_root=tmp_path / "solo")
    world = prepare_world_materials(db, state, dest_root=tmp_path / "world")

    scene_by_month, scene_gazette = _public_layer(
        scene.root, f"人物/{character.name}/公开说法/",
    )
    solo_by_month, solo_gazette = _public_layer(solo.root, "公开说法/")
    world_by_month, _unused = _public_layer(world.root, "公开说法/")
    # 推演者的历月邸报是顶层 邸报/ 载体（_write_world_tree），不在公开说法子树内。
    world_gazette = _layer_paths(world.root, "邸报/")

    # 准入一致：三类目录的按月公开说法载体路径完全同形（路径集合，非正文）。
    assert scene_by_month, "场景人物仍应有自己的公开说法层"
    assert scene_by_month == solo_by_month == world_by_month
    # 邸报只经既定载体：人物目录 公开说法/邸报/，推演者顶层 邸报/，各只一份。
    # 同一月份在人物目录里至多一条邸报载体路径——这就是「同一份公开材料不被
    # 重投影」的结构化证明（同一载体名在同一根目录不可能出现两次）。
    assert scene_gazette == solo_gazette
    assert scene_gazette and world_gazette
    assert set(world_gazette) == {rel.removeprefix("邸报/") for rel in scene_gazette}
    # 世界目录不另生 公开说法/邸报/ 副本（推演者的邸报只在顶层 邸报/）。
    assert not any(
        path.startswith("公开说法/邸报/") for path in list_materials(world.root)
    )

    # 单人目录的人物子树只有既定载体：朝臣名册 + 本人经历 + 本人公事档案。
    # 修前这里多一份 人物/<名>/见闻.txt，把公开层正文整体重渲一遍。
    # 契约落结构：恰一棵人物子树、以读者本人命名、其下恰两个既定载体。
    # 不钉 _safe_segment 的摘要后缀——那是内部表示，与本契约无关（大理寺
    # aa62c7def：换任一合法在职读者都应同样成立）。
    person_paths = {
        path for path in list_materials(solo.root) if path.startswith("人物/")
    }
    person_dirs = {path.split("/")[1] for path in person_paths if path.count("/") == 2}
    assert len(person_dirs) == 1, person_paths
    person_dir = person_dirs.pop()
    assert person_dir.startswith(f"{character.name}-"), person_dir
    assert person_paths == {
        "人物/朝臣名册.txt",
        f"人物/{person_dir}/经历.txt",
        f"人物/{person_dir}/公事档案.txt",
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
    public_events = db.get_character_knowledge(state, character.name)["public_events"]
    by_source = {
        str(item.get("source_id") or ""): item for item in public_events
    }
    assert {"judge:shaanxi", "judge:henan"} <= set(by_source)
    # 只核独立输入的完整搬运；不把记录间的排版当契约。
    originals = ("陕西赈务", "河南赈务", shared)
    month_name = f"{shared_year}年{shared_period}月.txt"
    for root, prefix in (
        (scene.root, f"人物/{character.name}/公开说法/"),
        (solo.root, "公开说法/"),
        (world.root, "公开说法/"),
    ):
        rel = prefix + month_name
        disk = (root / rel).read_bytes().decode("utf-8")
        direct = read_material(root, rel)
        tools = {tool.__name__: tool for tool in material_tools(root)}
        api = tools["read_material"](rel)
        for original in originals:
            assert original in disk
            assert original in direct
            assert original in api


def test_rebuild_adds_only_the_new_record_own_carrier(game, tmp_path):
    """重备按新记录增自己的载体，既有公开层载体路径一概不动。"""
    db, state, content = game
    character = _active_minister(db, content)
    _seed_public_world(db, state)

    before = _public_layer(
        prepare_character_materials(
            db, state, character, dest_root=tmp_path / "before",
        ).root,
        "公开说法/",
    )

    later = GameState(
        turn=int(state.turn) + 1, year=int(state.year) + 60, period=7,
        metrics=dict(state.metrics),
    )
    record_public_saying(db, later, "后落公开说法")
    after = _public_layer(
        prepare_character_materials(
            db, state, character, dest_root=tmp_path / "after",
        ).root,
        "公开说法/",
    )

    (before_by_month, before_gazette) = before
    (after_by_month, after_gazette) = after
    # 新记录恰好新增自己那一月的一份载体；既有月份与邸报载体均不动。
    assert set(after_by_month) - set(before_by_month) == {
        f"{later.year}年{later.period}月.txt",
    }
    assert set(before_by_month) <= set(after_by_month)
    assert after_gazette == before_gazette
