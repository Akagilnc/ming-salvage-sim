"""#1834 [M18 供料] S4：推演者材料目录。

Seam: prepare_world_materials (directory + opening min set), reusing
list_materials/read_material (#1830 API, generic over any root).

大理寺 01a08e3a 裁定：本文件只留结构化契约（目录路径、可读载体、无裸
副本）；对盘面/事务/opening/经历/邸报等人读渲染文本的措辞或固定片段机械
断言（含哨兵）已整类删除，不得换形复造——`read_material` 越目录契约已由
tests/test_material_directory_1830.py 的同一泛化入口覆盖，不在此重复。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from ming_sim.db import GameDB
from ming_sim.materials import (
    list_materials, prepare_world_materials, read_material,
    world_materials_root,
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
    db.save_turn_report(past_state, "历月邸报正文", title="辽东告急")

    dest = tmp_path / "world-materials"
    prepared = prepare_world_materials(db, state, dest_root=dest)

    names = list_materials(prepared.root)
    assert "INDEX.txt" in names
    assert "盘面/全局.txt" in names
    read_material(prepared.root, "盘面/派系检举事实.txt")
    assert "人物/朝臣名册.txt" in names
    assert any(p.startswith("人物/") and p.endswith("/经历.txt") for p in names)
    assert any(p.startswith(f"事务/affair-{affair.id}-") for p in names)
    assert any(p.startswith("邸报/") for p in names)

    for rel in names:
        read_material(prepared.root, rel)

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
    character/army/region 各一条真实文字事实，断言世界目录三类对象各自的按月
    实况路径均已可达（#1812 P6：结构化路径契约，不对材料正文做词面/哨兵
    断言——同本文件顶部大理寺 01a08e3a 裁定）。"""
    db, state, content = game
    character_name = next(iter(content.characters))
    army_id = str(db.conn.execute("SELECT id FROM armies LIMIT 1").fetchone()["id"])
    region_id = str(db.conn.execute("SELECT id FROM regions LIMIT 1").fetchone()["id"])

    character_fact = "右臂中箭，尚未痊愈"
    army_fact = "欠饷已逾三月"
    region_fact = "旱情加剧，流民渐增"
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


def test_prepare_rebuilds_from_world_record_after_restore(game, tmp_path):
    db, state, content = game
    affair = db.affairs.open(
        name="宣府欠饷", origin="宣府镇奏报欠饷",
        year=state.year, period=state.period, turn=state.turn,
    )
    dossier_id = db.create_decree_dossier(
        state, action_type="assignment", decree_text="护送军饷",
        target_kind="issue", target_id="pay", executor_kind="character",
        executor_id="毕自严",
        payload={"assignee_id": "毕自严", "affair_declaration": {
            "attach": "existing", "affair_id": affair.id,
        }},
    )
    db.record_dossier_progress(dossier_id, state.turn, "推进", "军饷已领讫")
    db.record_dossier_actual_progress(
        dossier_id, state.turn, units=2, fidelity_state="partial",
        floor_state="partial", note="余饷未交付",
    )
    db.affairs.declare_closed(affair.id, turn=state.turn)
    path = str(db.path)
    db.close()

    from ming_sim.db import GameDB
    restored = GameDB(path, content)
    try:
        state2 = restored.load_state()
        prepared = prepare_world_materials(restored, state2, dest_root=tmp_path / "m2")
        names = list_materials(prepared.root)
        affair_paths = [p for p in names if p.startswith(f"事务/affair-{affair.id}-")]
        assert len(affair_paths) == 1
        read_material(prepared.root, affair_paths[0])
    finally:
        restored.close()


def test_world_materials_isolate_invocations_and_databases(game, tmp_path, monkeypatch):
    db, state, content = game
    requested = tmp_path / "world"
    first = prepare_world_materials(db, state, dest_root=requested)
    second = prepare_world_materials(db, state, dest_root=requested)
    assert first.root != second.root
    read_material(first.root, "INDEX.txt")
    read_material(second.root, "INDEX.txt")

    # 第二档库与夹具库同父目录（材料树按 db stem 隔层正是为同父多档互不互踩），
    # 但资源归属归本用例：在该父目录里用 mkstemp 原子占一个唯一名（不是拼一个
    # basename——basename 跨运行会撞，撞上时 GameDB 打开的是别人的库）。finally
    # 只删自己 mkstemp 出来的那两个文件，不按名字去动目录里的其它残留。
    fd, other_name = tempfile.mkstemp(dir=str(Path(db.path).parent), suffix=".db")
    os.close(fd)
    other_path = Path(other_name)
    other = GameDB(str(other_path), content)
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
        for leftover in (other_path, Path(f"{other_path}_agno.db")):
            if leftover.exists():
                leftover.unlink()


def test_world_materials_include_textual_facts_once_and_gazette_not_duplicated(game, tmp_path):
    """世界目录直读权威文字事实与独立公开说法；邸报只走 邸报/ 载体。

    契约只落列目录的结构化路径 / typed store 可达关系，不解析人读 INDEX。
    """
    db, state, content = game
    name = next(iter(content.characters))
    db.textual_facts.append(
        subject_kind="character", subject_id=name, body="人物事实",
        year=int(state.year), period=int(state.period), turn=int(state.turn),
    )
    region = db.conn.execute("SELECT id FROM regions ORDER BY id LIMIT 1").fetchone()
    db.textual_facts.append(
        subject_kind="region", subject_id=str(region["id"]), body="地方事实",
        year=int(state.year), period=int(state.period), turn=int(state.turn),
    )
    affair = db.affairs.open(
        name="事实探针事务", origin="probe",
        year=state.year, period=state.period, turn=state.turn,
    )
    db.textual_facts.append(
        subject_kind="affair", subject_id=str(affair.id), body="事务事实",
        year=int(state.year), period=int(state.period), turn=int(state.turn),
        origin_ref=db.affairs.origin_ref(affair.id),
    )
    past_year, past_period, past_turn = state.year, max(1, state.period - 1), max(0, state.turn - 1)
    from ming_sim.models import GameState
    from ming_sim.public_sayings import list_public_sayings, record_public_saying

    past_state = GameState(
        turn=past_turn, year=past_year, period=past_period, metrics=dict(state.metrics),
    )
    db.save_turn_report(past_state, "gazette-body")

    # Independent public_sayings must mint their own month path under 公开说法/,
    # even when other knowledge public rows already occupy a different month.
    saying_state = GameState(
        turn=int(state.turn),
        year=int(state.year) + 50,
        period=6,
        metrics=dict(state.metrics),
    )
    expected_public_rel = f"公开说法/{saying_state.year}年{saying_state.period}月.txt"
    saying_id = record_public_saying(db, saying_state, "independent-public-saying-body")
    assert any(int(row["id"]) == int(saying_id) for row in list_public_sayings(db))

    prepared = prepare_world_materials(db, state, dest_root=tmp_path / "world-facts")
    names = list_materials(prepared.root)
    from ming_sim.materials import _safe_segment
    assert f"人物/{_safe_segment(name)}/按月实况.txt" in names
    assert f"地区/{region['id']}/按月实况.txt" in names
    assert not any(p.startswith("事实/") for p in names)
    # typed store still reachable for the written subjects
    assert db.textual_facts.readable_materials(subject_kind="character", subject_id=name)
    assert db.textual_facts.readable_materials(
        subject_kind="region", subject_id=str(region["id"]),
    )
    # affair textual facts ride 事务/ only.
    affair_paths = [p for p in names if p.startswith(f"事务/affair-{affair.id}-")]
    assert len([p for p in affair_paths if p.endswith("/当前情况.txt")]) == 1

    gazette_paths = [p for p in names if p.startswith("邸报/")]
    assert gazette_paths
    assert expected_public_rel in names
    # 邸报 stays a top-level carrier; public layer does not grow gazette path twins.
    assert not any(p.startswith("公开说法/邸报/") for p in names)
    # _is_gazette_public_event 必须把 turn_report 挡出 公开说法/：gate 在场时
    # past 月路径不存在；gate 失效后该路径会出现（结构化路径契约，不盯正文）。
    assert f"公开说法/{past_year}年{past_period}月.txt" not in names
    assert f"邸报/{past_year}年{past_period}月.txt" in names


def test_world_materials_carry_eligible_person_event_candidates(game, tmp_path):
    """#1892 J3：世界段起调时材料目录按当前实况给出合资格人物事件候选及结构化事实。

    候选资格单一真源＝issues.gather_candidate_events；本例只钉「供料接缝接通」，
    不另设判门。已落终态者不入候选（引擎硬触发的大疫不在其中）。
    """
    from ming_sim import issues

    db, state, content = game
    issues.bind_content(content)
    state.year = 1636
    state.period = 4
    db.save_state(state)

    dest = tmp_path / "world-materials"
    prepared = prepare_world_materials(db, state, dest_root=dest)

    candidate_paths = [
        p for p in list_materials(prepared.root)
        if p.startswith("候选事件/") and p.endswith(".txt") and not p.endswith("/INDEX.txt")
    ]
    assert candidate_paths
    # 人读索引可读；实际取阅路径只从列目录取得，不解析索引排版。
    read_material(prepared.root, "候选事件/INDEX.txt")
    for rel in candidate_paths:
        read_material(prepared.root, rel)
    # 候选集合＝权威快照逐条可达；快照为空则本例无意义，故先钉非空。
    eligible = {ev.id for ev in issues.gather_candidate_events(state, db)}
    assert eligible, "fixture 需当期有合资格人物事件"
    assert "huangtaiji_chengdi" in eligible
    assert len(candidate_paths) == len(eligible)
    assert "jisi_lubian" in eligible


def test_world_materials_carry_due_fiscal_levy_petitions(game, tmp_path):
    """#1892 J5：三饷到点须皇帝亲裁，故走「请旨事项」目录交世界段上疏。

    契约＝实际列目录、可读载体与权威快照一致；不解析人读 INDEX。
    """
    from ming_sim import issues

    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)

    due = {ev.id for ev in issues.gather_fiscal_levy_petitions(state, db)}
    assert "liao_levy_rise_1631" in due

    prepared = prepare_world_materials(db, state, dest_root=tmp_path / "levy")
    read_material(prepared.root, "请旨事项/INDEX.txt")
    paths = [
        p for p in list_materials(prepared.root)
        if p.startswith("请旨事项/") and p.endswith(".txt") and not p.endswith("/INDEX.txt")
    ]
    assert paths
    from ming_sim.materials import _safe_segment
    assert set(paths) == {f"请旨事项/{_safe_segment(event_id)}.txt" for event_id in due}
    for rel in paths:
        read_material(prepared.root, rel)

    # 已落终态者不再呈请；亲裁一次后同一事件不再顶回批红。
    db.mark_event_triggered(state, "liao_levy_rise_1631", terminal_reason="已准")
    assert "liao_levy_rise_1631" not in {
        ev.id for ev in issues.gather_fiscal_levy_petitions(state, db)
    }
