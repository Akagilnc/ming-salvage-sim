"""#346 transit-aging 兜底：≤2月强制到任 + transit_start_turn 计时。

覆盖：
1. 在途 ≥2 月 → force_transit_arrivals 强制到任（location=transit_to, transit_to=''）
2. 在途 0 月（刚启程）→ 不强制
3. 在途 1 月 → 不强制
4. legacy 旧数据：transit_to 有值但 transit_start_turn=0 → 强制（保守兜底）
5. 强制到任后 content 内存镜像同步
6. 行止 apply 写 transit_to 时同步写 transit_start_turn
"""

from __future__ import annotations

import ming_sim.issues as issues
from ming_sim.decree import force_transit_arrivals
from tests.conftest import active_ming_character

DEST = "liaodong"


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

    issues.apply_score_extraction(
        db,
        state,
        {"人物变更": [{"name": name, "动作": "行止", "transit_to": DEST}]},
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
        {"人物变更": [{"name": name, "动作": "行止", "location": DEST, "transit_to": ""}]},
        content=content,
    )

    row = db.conn.execute(
        "SELECT transit_to, transit_start_turn FROM characters WHERE name=?", (name,)
    ).fetchone()
    assert row["transit_to"] == "", "抵达后 transit_to 应被清空"
    assert row["transit_start_turn"] == 0, "抵达后 transit_start_turn 应清零"
