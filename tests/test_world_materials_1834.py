"""#1834 [M18 供料] S4：推演者材料目录。

Seam: prepare_world_materials (directory + opening min set), reusing
list_materials/read_material (#1830 API, generic over any root).
"""

from __future__ import annotations

from ming_sim.materials import list_materials, prepare_world_materials, read_material


def _an_active_character(content):
    for character in content.characters.values():
        if character.office_type not in ("后宫", "宗藩"):
            return character.name
    raise AssertionError("no eligible character in fixture content")


def test_prepare_writes_typed_tree_with_board_affairs_and_gazette_index(game, tmp_path):
    db, state, content = game
    name = _an_active_character(content)

    # 全量盘面须来自账本本身，不来自任何奏报/邸报文本——摆一个可核对的国库真值。
    db.conn.execute(
        "UPDATE economy_accounts SET balance = ? WHERE account = ?",
        (314159, "国库"),
    )
    db.conn.commit()

    # 一件开着的事务，两条按月文字事实（ADR 0156：读时按时间顺序全部提供）。
    affair = db.affairs.open(
        name="宁远护送", origin="拨银、调将、派兵去宁远",
        year=state.year, period=state.period, turn=state.turn,
    )
    situation_old = "护送启程，尚在筹备"
    situation_new = "护送银两已出京，尚未抵宁远"
    db.textual_facts.append(
        subject_kind="affair", subject_id=str(affair.id), body=situation_old,
        year=state.year, period=max(1, state.period - 1), turn=state.turn,
    )
    db.textual_facts.append(
        subject_kind="affair", subject_id=str(affair.id), body=situation_new,
        year=state.year, period=state.period, turn=state.turn,
    )

    # 一份历史邸报（不同于当前 state.turn，模拟“历月”）：应变成目录里可读的一
    # 行索引项，且不再由已退役的章节记忆承担。
    past_year, past_period, past_turn = state.year, max(1, state.period - 1), max(0, state.turn - 1)
    from ming_sim.models import GameState
    past_state = GameState(turn=past_turn, year=past_year, period=past_period, metrics=dict(state.metrics))
    db.save_turn_report(past_state, "SENTINEL_PAST_GAZETTE_TEXT")

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
            assert read_material(prepared.root, line.strip())

    # 推演者读到的是实况数（账本真值），不是奏报数。
    board = read_material(prepared.root, "盘面/全局.txt")
    assert "314159" in board or "31.4" in board or "314,159" in board

    # 事务全史全部提供，早晚两条都在、按时间顺序；开场只放最新一句。
    affair_path = next(p for p in names if p.startswith(f"事务/affair-{affair.id}/"))
    affair_body = read_material(prepared.root, affair_path)
    assert situation_old in affair_body
    assert situation_new in affair_body
    assert affair_body.index(situation_old) < affair_body.index(situation_new)
    assert affair.name in prepared.opening
    assert situation_new in prepared.opening
    assert situation_old not in prepared.opening

    # 历月邸报以一行索引入目录：其内容可读到，且不是被压缩/摘要过的第二套文本。
    gazette_path = next(p for p in names if p.startswith("邸报/"))
    assert "SENTINEL_PAST_GAZETTE_TEXT" in read_material(prepared.root, gazette_path)

    # 无裸副本：不得直接倒出世界库/JSON。
    assert not any(n.lower().endswith((".db", ".sqlite", ".sqlite3", ".json")) for n in names)


def test_opening_is_board_and_open_affairs_only(game, tmp_path):
    db, state, content = game
    affair = db.affairs.open(
        name="辽东军情", origin="边镇急报",
        year=state.year, period=state.period, turn=state.turn,
    )
    situation = "辽东军情已奏闻，尚候圣裁"
    db.textual_facts.append(
        subject_kind="affair", subject_id=str(affair.id), body=situation,
        year=state.year, period=state.period, turn=state.turn,
    )

    prepared = prepare_world_materials(db, state, dest_root=tmp_path / "m")

    assert affair.name in prepared.opening
    assert situation in prepared.opening
    # 人物经历不是开场最小集（0155：开场只放盘面全量 + 开着的事务清单）。
    roster_names = [
        name for name in list_materials(prepared.root)
        if name.startswith("人物/") and name.endswith("/经历.txt")
    ]
    assert roster_names
    experience_body = read_material(prepared.root, roster_names[0])
    if experience_body.strip() and experience_body.strip() != "（无）":
        assert experience_body not in prepared.opening


def test_read_material_stays_inside_world_directory(game, tmp_path):
    db, state, content = game
    prepared = prepare_world_materials(db, state, dest_root=tmp_path / "m")
    try:
        read_material(prepared.root, "../outside.txt")
        raise AssertionError("expected path confinement")
    except ValueError:
        pass


def test_prepare_rebuilds_from_world_record_after_restore(game, tmp_path):
    db, state, content = game
    affair = db.affairs.open(
        name="宣府欠饷", origin="宣府镇奏报欠饷",
        year=state.year, period=state.period, turn=state.turn,
    )
    fact = "宣府欠饷已核实，尚待补发"
    db.textual_facts.append(
        subject_kind="affair", subject_id=str(affair.id), body=fact,
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
        affair_path = next(p for p in names if p.startswith(f"事务/affair-{affair.id}/"))
        assert fact in read_material(prepared.root, affair_path)
    finally:
        restored.close()
