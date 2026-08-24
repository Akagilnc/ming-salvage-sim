"""在途启程账与 #668 倒数 tick 的保留契约（原 #346 旧 ≥2 月硬兜底已拆除）。

覆盖：
1. 行止 apply 写 transit_to 时同步写 transit_start_turn 与矩阵距离
2. 人物变更不得平行落抵达
3. 同目的地 re-emit 不刷新 start_turn / remaining
4. 在途改道拒收
5. tick 先于事件终态评估（链顺序）
6. snapshot/restore 包含 transit 账
"""

from __future__ import annotations

import ming_sim.issues as issues
from ming_sim.issues import _restore_person_write_state, _snapshot_person_write_state
from ming_sim.decree import pre_settle, tick_transit_arrivals
from ming_sim.distance import DistanceMatrix
from ming_sim.models import Event, TurnPhase
from pathlib import Path
from tests.conftest import active_ming_character

DEST = "liaodong"
MATRIX = DistanceMatrix.from_file(Path(__file__).resolve().parents[1] / "content/distance_matrix.json")


def _set_departure_origin(db, content, name: str) -> None:
    db.conn.execute("UPDATE characters SET location='beizhili' WHERE name=?", (name,))
    content.characters[name].location = "beizhili"


def _set_full_transit(db, content, name: str, *, dest: str, start_turn: int, speed: float = 1.0):
    origin = "beizhili"
    r0 = MATRIX.travel_time(origin, dest)
    db.set_character_transit(
        name,
        location=origin,
        transit_to=dest,
        distance_remaining=r0,
        speed_factor=speed,
        start_turn=start_turn,
        content=content,
    )
    return r0


# ── 行止 apply 写启程账 ──────────────────────────────────────────────────────


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
        "SELECT transit_to, transit_start_turn, transit_distance_remaining, transit_speed_factor "
        "FROM characters WHERE name=?", (name,)
    ).fetchone()
    assert row["transit_to"] == DEST, "行止 后 transit_to 应被设置"
    assert row["transit_start_turn"] == state.turn, (
        f"行止 后 transit_start_turn 应等于当前回合 {state.turn}，实测 {row['transit_start_turn']}"
    )
    assert row["transit_distance_remaining"] == MATRIX.travel_time("beizhili", DEST)
    assert row["transit_speed_factor"] == 1.0


def test_行止_payload_cannot_write_arrival(game):
    """抵达是引擎倒数 tick 独占的事实，人物变更不得平行落位。"""
    db, state, content = game
    name = active_ming_character(db, content)
    _set_full_transit(db, content, name, dest=DEST, start_turn=99)

    result = issues.apply_score_extraction(
        db,
        state,
        {"人物变更": [{"origin_ref": "盘面自发", "name": name, "动作": "行止", "location": DEST, "transit_to": ""}]},
        content=content,
    )

    row = db.conn.execute(
        "SELECT transit_to, transit_start_turn FROM characters WHERE name=?", (name,)
    ).fetchone()
    assert row["transit_to"] == DEST
    assert row["transit_start_turn"] == 99
    assert result["applied_person_changes"][0]["category"] == "invalid_transition"


def test_行止_reemit_same_dest_preserves_start_turn(game):
    """同一 transit_to 被逐月 re-emit 时，transit_start_turn / remaining 不应被刷新。"""
    db, state, content = game
    name = active_ming_character(db, content)
    _set_departure_origin(db, content, name)

    state.turn = 3
    issues.apply_score_extraction(
        db, state,
        {"人物变更": [{"origin_ref": "盘面自发", "name": name, "动作": "行止", "transit_to": DEST}]},
        content=content,
    )
    before = db.conn.execute(
        "SELECT transit_start_turn, transit_distance_remaining, transit_speed_factor "
        "FROM characters WHERE name=?", (name,),
    ).fetchone()
    assert before["transit_start_turn"] == 3

    state.turn = 4
    issues.apply_score_extraction(
        db, state,
        {"人物变更": [{"origin_ref": "盘面自发", "name": name, "动作": "行止", "transit_to": DEST}]},
        content=content,
    )
    row = db.conn.execute(
        "SELECT transit_start_turn, transit_distance_remaining, transit_speed_factor "
        "FROM characters WHERE name=?", (name,),
    ).fetchone()
    assert row["transit_start_turn"] == 3
    assert row["transit_distance_remaining"] == before["transit_distance_remaining"]
    assert row["transit_speed_factor"] == before["transit_speed_factor"]


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


# ── tick 先于事件终态 ───────────────────────────────────────────────────────


def test_pre_settle_ticks_arrival_before_terminal_states(game):
    """tick_transit_arrivals 必须在 apply_event_terminal_states 之前跑。"""
    db, state, content = game
    issues.bind_content(content)
    name = active_ming_character(db, content)

    ev = Event(
        id="__test_transit_gate__", title="测试在途门控", kind="situation",
        summary="x", urgency=50, severity=50, credibility=50,
        interests=[], audiences=[],
        trigger_year=1, trigger_month=0,
        trigger_gate={
            f"character.{name}.location": "==liaodong",
            f"character.{name}.status": "==active",
        },
        person_core_subjects=[name],
    )
    content.events.append(ev)
    try:
        # 构造本 tick 必抵达：remaining 很小，且 start_turn < 当前 turn（次月起才减）
        state.turn = 5
        state.turn_phase = TurnPhase.REVIEWING.value
        db.set_character_transit(
            name,
            location="beizhili",
            transit_to="liaodong",
            distance_remaining=0.5,
            speed_factor=1.0,
            start_turn=4,
            content=content,
        )
        db.save_state(state)

        pre_settle(state, db, content=content)

        row = db.conn.execute(
            "SELECT location, transit_to FROM characters WHERE name=?", (name,),
        ).fetchone()
        assert row["location"] == "liaodong" and row["transit_to"] == "", (
            "倒数 tick 应已引擎抵达"
        )
        assert not db.has_event_terminal_state("__test_transit_gate__", "avoided"), (
            "在途赴门控地者抵达月事件不应在 tick 前被误判 avoided"
        )
    finally:
        content.events.remove(ev)


def test_tick_does_not_arrive_when_remaining_still_positive(game):
    db, state, content = game
    name = active_ming_character(db, content)
    t0 = state.turn
    r0 = _set_full_transit(db, content, name, dest=DEST, start_turn=t0)
    assert r0 > 1.0

    # 次月首减：启程当月不 tick
    state.turn = t0 + 1
    forced = tick_transit_arrivals(db, state, content)
    assert name not in [f["name"] for f in forced]
    row = db.conn.execute(
        "SELECT location, transit_to, transit_distance_remaining FROM characters WHERE name=?",
        (name,),
    ).fetchone()
    assert row["transit_to"] == DEST
    assert row["location"] == "beizhili"
    assert row["transit_distance_remaining"] == r0 - 1.0


# ── snapshot/restore ────────────────────────────────────────────────────────


def test_snapshot_restore_preserves_transit_start_turn(game):
    """_restore_person_write_state 回滚后 transit_start_turn 随 transit_to 一并还原。"""
    db, _state, content = game
    name = active_ming_character(db, content)

    db.conn.execute(
        "UPDATE characters SET transit_to=?, transit_start_turn=?, "
        "transit_distance_remaining=?, transit_speed_factor=? WHERE name=?",
        (DEST, 99, 2.1, 1.0, name),
    )
    db.conn.commit()

    snapshot = _snapshot_person_write_state(db, content)

    db.conn.execute(
        "UPDATE characters SET transit_start_turn=0 WHERE name=?", (name,)
    )
    db.conn.commit()
    assert db.conn.execute(
        "SELECT transit_start_turn FROM characters WHERE name=?", (name,)
    ).fetchone()["transit_start_turn"] == 0

    _restore_person_write_state(db, content, snapshot, commit=True)

    row = db.conn.execute(
        "SELECT transit_to, transit_start_turn FROM characters WHERE name=?", (name,)
    ).fetchone()
    assert row["transit_to"] == DEST
    assert row["transit_start_turn"] == 99
