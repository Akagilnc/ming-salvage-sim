"""#346 transit-aging 兜底：≤2月强制到任 + transit_start_turn 计时。

覆盖：
1. 在途 ≥2 月 → force_transit_arrivals 强制到任（location=transit_to, transit_to=''）
2. 在途 0 月（刚启程）→ 不强制
3. 在途 1 月 → 不强制
4. legacy 旧数据：transit_to 有值但 transit_start_turn=0 → 强制（保守兜底）
5. 强制到任后 content 内存镜像同步
6. 行止 apply 写 transit_to 时同步写 transit_start_turn
7. 任命写路径失败回滚：_restore_person_write_state 还原 transit_start_turn（P1-B）
"""

from __future__ import annotations

import ming_sim.issues as issues
from ming_sim.issues import _restore_person_write_state, _snapshot_person_write_state
from ming_sim.decree import force_transit_arrivals, pre_settle
from ming_sim.models import Event
from tests.conftest import active_ming_character

DEST = "liaodong"


def _set_departure_origin(db, content, name: str) -> None:
    db.conn.execute("UPDATE characters SET location='beizhili' WHERE name=?", (name,))
    content.characters[name].location = "beizhili"


def _set_transit(db, name: str, transit_to: str, transit_start_turn: int) -> None:
    db.conn.execute(
        "UPDATE characters SET transit_to=?, transit_start_turn=? WHERE name=?",
        (transit_to, transit_start_turn, name),
    )
    db.conn.commit()


# ── 1) 在途 ≥2 月 → 强制到任 ──────────────────────────────────────────────────


def test_force_transit_arrivals_forces_overdue(game):
    """在途计时 ≥2 回合 → force_transit_arrivals 强制 location=transit_to, transit_to=''。"""
    db, state, content = game
    name = active_ming_character(db, content)
    state.turn = 5
    _set_transit(db, name, DEST, transit_start_turn=3)  # 5-3=2 ≥ 2 → 强制

    forced = force_transit_arrivals(db, state, content)

    names = [f["name"] for f in forced]
    assert name in names

    row = db.conn.execute(
        "SELECT location, transit_to, transit_start_turn FROM characters WHERE name=?",
        (name,),
    ).fetchone()
    assert row["location"] == DEST, "强制到任后 location 应等于原 transit_to"
    assert row["transit_to"] == "", "强制到任后 transit_to 应被清空"
    assert row["transit_start_turn"] == 0, "强制到任后 transit_start_turn 应清零"


# ── 2) 在途 0 月（刚启程）→ 不强制 ──────────────────────────────────────────


def test_force_transit_arrivals_skips_fresh_transit(game):
    """刚启程（transit_start_turn=本回合）→ 不强制（0 < 2）。"""
    db, state, content = game
    name = active_ming_character(db, content)
    state.turn = 5
    _set_transit(db, name, DEST, transit_start_turn=5)  # 5-5=0 < 2 → 不强制

    forced = force_transit_arrivals(db, state, content)

    names = [f["name"] for f in forced]
    assert name not in names

    row = db.conn.execute(
        "SELECT transit_to FROM characters WHERE name=?", (name,)
    ).fetchone()
    assert row["transit_to"] == DEST, "不满 2 月，transit_to 不应被清"


# ── 3) 在途 1 月 → 不强制 ────────────────────────────────────────────────────


def test_force_transit_arrivals_skips_one_month(game):
    """在途 1 回合（transit_start_turn=当前-1）→ 不强制（1 < 2）。"""
    db, state, content = game
    name = active_ming_character(db, content)
    state.turn = 5
    _set_transit(db, name, DEST, transit_start_turn=4)  # 5-4=1 < 2 → 不强制

    forced = force_transit_arrivals(db, state, content)

    names = [f["name"] for f in forced]
    assert name not in names

    row = db.conn.execute(
        "SELECT transit_to FROM characters WHERE name=?", (name,)
    ).fetchone()
    assert row["transit_to"] == DEST, "1 月在途，transit_to 不应被清"


# ── 4) 旧数据 transit_start_turn=0 → 保守强制 ──────────────────────────────


def test_force_transit_arrivals_legacy_zero_start(game):
    """旧数据 transit_to 有值但 transit_start_turn=0 → 视为过期，保守强制到任。"""
    db, state, content = game
    name = active_ming_character(db, content)
    _set_transit(db, name, DEST, transit_start_turn=0)  # transit_start_turn=0 = 旧数据

    forced = force_transit_arrivals(db, state, content)

    names = [f["name"] for f in forced]
    assert name in names

    row = db.conn.execute(
        "SELECT location, transit_to FROM characters WHERE name=?", (name,)
    ).fetchone()
    assert row["location"] == DEST
    assert row["transit_to"] == ""


# ── 5) 强制到任后 content 内存镜像同步 ───────────────────────────────────────


def test_force_transit_arrivals_syncs_content_mirror(game):
    """force_transit_arrivals 后 content 镜像 location=transit_to, transit_to=''。"""
    db, state, content = game
    name = active_ming_character(db, content)
    state.turn = 5
    _set_transit(db, name, DEST, transit_start_turn=3)  # overdue

    if name in content.characters:
        content.characters[name].transit_to = DEST

    force_transit_arrivals(db, state, content)

    if name in content.characters:
        ch = content.characters[name]
        assert getattr(ch, "location", None) == DEST, "content 镜像 location 应同步"
        assert getattr(ch, "transit_to", "") == "", "content 镜像 transit_to 应被清空"


# ── 6) 行止 apply 写 transit_to 时同步写 transit_start_turn ─────────────────


def test_行止_sets_transit_start_turn(game):
    """apply_score_extraction 处理 行止 时，写入 transit_to 同时记录 transit_start_turn=当前回合。"""
    db, state, content = game
    name = active_ming_character(db, content)
    _set_departure_origin(db, content, name)

    issues.apply_score_extraction(
        db,
        state,
        {"人物变更": [{"origin_ref": "盘面自发", "name": name, "动作": "行止", "transit_to": DEST}]},
        content=content,
    )

    row = db.conn.execute(
        "SELECT transit_to, transit_start_turn FROM characters WHERE name=?", (name,)
    ).fetchone()
    assert row["transit_to"] == DEST, "行止 后 transit_to 应被设置"
    assert row["transit_start_turn"] == state.turn, (
        f"行止 后 transit_start_turn 应等于当前回合 {state.turn}，实测 {row['transit_start_turn']}"
    )


def test_行止_arrival_clears_transit_start_turn(game):
    """行止 抵达（transit_to=''）后 transit_start_turn 应清零。"""
    db, state, content = game
    name = active_ming_character(db, content)

    # 先置为在途
    _set_transit(db, name, DEST, transit_start_turn=99)

    # 再抵达
    issues.apply_score_extraction(
        db,
        state,
        {"人物变更": [{"origin_ref": "盘面自发", "name": name, "动作": "行止", "location": DEST, "transit_to": ""}]},
        content=content,
    )

    row = db.conn.execute(
        "SELECT transit_to, transit_start_turn FROM characters WHERE name=?", (name,)
    ).fetchone()
    assert row["transit_to"] == "", "抵达后 transit_to 应被清空"
    assert row["transit_start_turn"] == 0, "抵达后 transit_start_turn 应清零"


# ── 6b) 重复 re-emit 同一 transit_to 不刷新 transit_start_turn（CMR P2）──────


def test_行止_reemit_same_dest_preserves_start_turn(game):
    """同一 transit_to 被逐月 re-emit 时，transit_start_turn 不应被刷新（CMR P2 / #346）。

    若每月刷新启程回合，force_transit_arrivals 的 `turn - start >= 2` 永不成立 →
    兜底失效、永久在途。原启程回合必须保留，使兜底仍在原启程 +2 月强制到任。
    """
    db, state, content = game
    name = active_ming_character(db, content)
    _set_departure_origin(db, content, name)

    # 第 3 月启程赴 DEST
    state.turn = 3
    issues.apply_score_extraction(
        db, state,
        {"人物变更": [{"origin_ref": "盘面自发", "name": name, "动作": "行止", "transit_to": DEST}]},
        content=content,
    )
    assert db.conn.execute(
        "SELECT transit_start_turn FROM characters WHERE name=?", (name,)
    ).fetchone()["transit_start_turn"] == 3

    # 第 4 月 simulator 仍叙述「在途赴 DEST」，re-emit 同一 transit_to
    state.turn = 4
    issues.apply_score_extraction(
        db, state,
        {"人物变更": [{"origin_ref": "盘面自发", "name": name, "动作": "行止", "transit_to": DEST}]},
        content=content,
    )
    row = db.conn.execute(
        "SELECT transit_start_turn FROM characters WHERE name=?", (name,)
    ).fetchone()
    assert row["transit_start_turn"] == 3, (
        f"re-emit 同一目的地不应刷新启程回合，应仍为 3，实测 {row['transit_start_turn']}"
    )

    # 第 5 月：原启程(3) +2 = 到期，兜底应强制到任
    state.turn = 5
    forced = force_transit_arrivals(db, state, content)
    assert name in [f["name"] for f in forced], (
        "原启程第 3 月、现第 5 月（在途 2 月）→ 兜底应强制到任，re-emit 不得使其逃逸"
    )


def test_行止_change_dest_is_rejected(game):
    """在途人物不可改道，原 transit ledger 保持不变。"""
    db, state, content = game
    name = active_ming_character(db, content)
    _set_departure_origin(db, content, name)

    state.turn = 3
    issues.apply_score_extraction(
        db, state,
        {"人物变更": [{"origin_ref": "盘面自发", "name": name, "动作": "行止", "transit_to": DEST}]},
        content=content,
    )

    state.turn = 6
    results = issues.apply_score_extraction(
        db, state,
        {"人物变更": [{"origin_ref": "盘面自发", "name": name, "动作": "行止", "transit_to": "shandong"}]},
        content=content,
    )
    row = db.conn.execute(
        "SELECT transit_to, transit_start_turn FROM characters WHERE name=?", (name,)
    ).fetchone()
    assert row["transit_to"] == DEST
    assert row["transit_start_turn"] == 3
    assert results["applied_person_changes"][0]["category"] == "invalid_transition"


def test_行止_reemit_same_dest_preserves_legacy_zero_start(game):
    """旧数据 transit_start_turn=0（启程未知哨兵）+ 同目的地 re-emit → 哨兵须保留（CMR 跨片复审）。

    若同目的地 re-emit 把 0 刷成 state.turn，旧在途数据被「洗白」成新在途，
    既逃过 force_transit_arrivals 的 `start==0` 兜底、当回合 `turn-start>=2` 也不成立，
    强制到任被延迟最多两回合，违背「transit_start_turn==0 = 按超期处理」不变式。
    """
    db, state, content = game
    name = active_ming_character(db, content)
    # 旧数据：transit_to 有值但 transit_start_turn=0
    _set_transit(db, name, DEST, transit_start_turn=0)

    state.turn = 7
    issues.apply_score_extraction(
        db, state,
        {"人物变更": [{"origin_ref": "盘面自发", "name": name, "动作": "行止", "transit_to": DEST}]},
        content=content,
    )
    start = db.conn.execute(
        "SELECT transit_start_turn FROM characters WHERE name=?", (name,)
    ).fetchone()["transit_start_turn"]
    assert start == 0, (
        f"同目的地 re-emit 不得刷新旧数据 0 哨兵，应仍为 0，实测 {start}"
    )
    # 哨兵保留 → 兜底仍按超期强制到任
    forced = force_transit_arrivals(db, state, content)
    assert name in [f["name"] for f in forced], (
        "transit_start_turn==0 旧数据 re-emit 后仍应被 force_transit_arrivals 强制到任"
    )


# ── 6c) 兜底到任须先于事件终态评估（CMR P2 r2 / 排序）─────────────────────


def test_pre_settle_forces_arrival_before_terminal_states(game):
    """force_transit_arrivals 必须在 apply_event_terminal_states 之前跑（CMR r2）。

    person-core 事件门控 character.X.location==DEST：若 X 超期在途赴 DEST，
    兜底强制到任须先于终态评估，否则终态评估读到旧 location → 门控不达标 →
    事件被误判 avoided 永久作废，#346 兜底形同虚设。
    """
    db, state, content = game
    issues.bind_content(content)
    name = active_ming_character(db, content)

    ev = Event(
        id="__test_transit_gate__", title="测试在途门控", kind="situation",
        summary="x", urgency=50, severity=50, credibility=50,
        interests=[], audiences=[],
        trigger_year=1, trigger_month=0,  # 窗口必开、无 end → 不会 expired
        trigger_gate={
            f"character.{name}.location": "==liaodong",
            f"character.{name}.status": "==active",
        },
        person_core_subjects=[name],
    )
    content.events.append(ev)
    try:
        # 超期在途赴 liaodong：启程第 3 月、现第 5 月（在途 2 月 → 到期）
        state.turn = 5
        db.conn.execute(
            "UPDATE characters SET location='beizhili', transit_to='liaodong', "
            "transit_start_turn=3 WHERE name=?", (name,),
        )
        db.conn.commit()

        pre_settle(state, db, content=content)

        row = db.conn.execute(
            "SELECT location, transit_to FROM characters WHERE name=?", (name,),
        ).fetchone()
        assert row["location"] == "liaodong" and row["transit_to"] == "", (
            "兜底应已强制到任"
        )
        assert not db.has_event_terminal_state("__test_transit_gate__", "avoided"), (
            "超期在途赴门控地的 person-core 事件不应在到任兜底前被误判 avoided"
        )
    finally:
        content.events.remove(ev)


# ── 7) snapshot/restore 包含 transit_start_turn（P1-B fix 直接验证）──────────


def test_snapshot_restore_preserves_transit_start_turn(game):
    """_restore_person_write_state 回滚后 transit_start_turn 随 transit_to 一并还原（P1-B）。

    直接调用 _snapshot_person_write_state / _restore_person_write_state，
    模拟「写路径中途失败 → 用快照还原」场景，验证 transit_start_turn 包含在快照内。
    （原 vacuous 版靠调任路径，但 set_character_office 不校验职位字符串 → 调任永不拒收
    → if rejected_this: 分支永远不跑 → 测试形同虚设。）
    """
    db, _state, content = game
    name = active_ming_character(db, content)

    # 在途态：transit_to=DEST, transit_start_turn=99
    _set_transit(db, name, DEST, transit_start_turn=99)

    # 拍快照（此刻 transit_start_turn=99 应进快照）
    snapshot = _snapshot_person_write_state(db, content)

    # 模拟写路径中途改了 transit_start_turn（如 行止 被 apply 后才抛异常）
    db.conn.execute(
        "UPDATE characters SET transit_start_turn=0 WHERE name=?", (name,)
    )
    db.conn.commit()
    assert db.conn.execute(
        "SELECT transit_start_turn FROM characters WHERE name=?", (name,)
    ).fetchone()["transit_start_turn"] == 0, "前置：已改成 0"

    # 还原快照
    _restore_person_write_state(db, content, snapshot, commit=True)

    # transit_start_turn 应随快照回到 99
    row = db.conn.execute(
        "SELECT transit_to, transit_start_turn FROM characters WHERE name=?", (name,)
    ).fetchone()
    assert row["transit_to"] == DEST, "restore 后 transit_to 应还原"
    assert row["transit_start_turn"] == 99, (
        f"restore 后 transit_start_turn 应还原为 99，实测 {row['transit_start_turn']}（P1-B 未覆盖则此处为 0）"
    )
