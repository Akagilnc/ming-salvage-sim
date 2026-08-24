"""#669：transit_semantics 纯 projector + payload/context 接线。

Seams under test:
- project_transit_semantics(db, state, matrix) 纯函数
- build_simulator_payload → 顶层键 transit_semantics
- build_simulator_context 自然透传（不改 context 拼装）

边界：零写口 / 零 cache / 零 guard / 零判官接线；裸账键名不入 payload/context。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from ming_sim.agents import build_simulator_context
from ming_sim.decree import reload_state_from_db
from ming_sim.distance import DistanceMatrix
from ming_sim.simulation import build_simulator_payload, project_transit_semantics
from tests.conftest import active_ming_character

ROOT = Path(__file__).resolve().parents[1]
MATRIX = DistanceMatrix.from_file(ROOT / "content/distance_matrix.json")

# 可辨识 remaining 样值：非合法 factor 标量 1.0/1.5/2.0，用于证明裸账未透传。
REMAINING_SENTINEL = 2.137

FORBIDDEN_KEYS = (
    "transit_distance_remaining",
    "transit_speed_factor",
    "total",
    "ETA",
    "eta",
)


def _oracle_T(d0: float, speed_factor: float) -> int:
    return max(1, math.ceil(d0 / speed_factor - 1e-9))


def _expected_semantic(factor: float, m: int, t: int) -> str:
    body = f"已在途 {m} 月，全程约 {t} 月"
    if factor == 1.0:
        return body
    if factor == 1.5:
        return f"〔行速语态：快马加鞭〕{body}"
    if factor == 2.0:
        return f"〔行速语态：星夜兼程〕{body}"
    raise AssertionError(f"unexpected factor {factor}")


def _put_in_transit(
    db,
    content,
    name: str,
    *,
    origin: str,
    dest: str,
    speed_factor: float = 1.0,
    start_turn: int,
    distance_remaining: float | None = None,
):
    r0 = (
        float(distance_remaining)
        if distance_remaining is not None
        else MATRIX.travel_time(origin, dest)
    )
    db.set_character_transit(
        name,
        location=origin,
        transit_to=dest,
        distance_remaining=r0,
        speed_factor=speed_factor,
        start_turn=start_turn,
        content=content,
    )
    return r0


def _active_ming_names(db, content, n: int) -> list[str]:
    names: list[str] = []
    for name, ch in content.characters.items():
        if getattr(ch, "power_id", "ming") != "ming":
            continue
        if getattr(ch, "office_type", "") == "后宫":
            continue
        if db.get_character_status(name)[0] == "active":
            names.append(name)
        if len(names) >= n:
            return names
    raise AssertionError(f"需要 {n} 个 active 大明大臣，仅得 {len(names)}")


def _stub_matrix(d0: float, origin: str = "beizhili", dest: str = "liaodong") -> DistanceMatrix:
    return DistanceMatrix({origin: {dest: d0, origin: 0.0}, dest: {origin: d0, dest: 0.0}})


# ── 纯函数：三速度档 + M=0 / 跨月 + D0∈{1.05, 2.1} ─────────────────────────


@pytest.mark.parametrize("speed_factor", [1.0, 1.5, 2.0])
@pytest.mark.parametrize(
    "d0,months_elapsed",
    [
        (2.1, 0),  # start==turn → M=0；真矩阵 beizhili→liaodong
        (2.1, 2),  # 跨月 M≥1
        (1.05, 0),  # stub D0=1.05
        (1.05, 1),
    ],
)
def test_project_transit_semantics_speed_and_months(game, speed_factor, d0, months_elapsed):
    db, state, content = game
    name = active_ming_character(db, content)
    origin, dest = "beizhili", "liaodong"
    # start_turn 须为正整数：把当前 turn 抬到足够大，再回推 M。
    state.turn = max(int(state.turn), 1) + months_elapsed
    start = state.turn - months_elapsed
    assert start >= 1
    matrix = MATRIX if d0 == 2.1 else _stub_matrix(d0, origin, dest)
    if d0 == 2.1:
        assert MATRIX.travel_time(origin, dest) == pytest.approx(2.1)
    _put_in_transit(
        db, content, name,
        origin=origin, dest=dest,
        speed_factor=speed_factor, start_turn=start,
        distance_remaining=REMAINING_SENTINEL if d0 != 2.1 else None,
    )

    rows = project_transit_semantics(db, state, matrix)

    t = _oracle_T(d0, speed_factor)
    assert rows == [{
        "name": name,
        "transit_to": dest,
        "semantic": _expected_semantic(speed_factor, months_elapsed, t),
    }]


def test_project_transit_semantics_empty_when_nobody_in_transit(game):
    db, state, _content = game
    assert project_transit_semantics(db, state, MATRIX) == []


def test_project_transit_semantics_stable_order_by_name_then_dest(game):
    db, state, content = game
    a, b = sorted(_active_ming_names(db, content, 2))
    t0 = state.turn
    # 插入逆序：先 b 后 a；dest 也交错，投影须 name ASC, transit_to ASC
    _put_in_transit(
        db, content, b, origin="beizhili", dest="liaodong",
        speed_factor=1.0, start_turn=t0,
    )
    _put_in_transit(
        db, content, a, origin="henan", dest="beizhili",
        speed_factor=1.0, start_turn=t0,
    )
    # 同名第二目的地不可并存（一人一途）；再加第三人验证 name 序
    names = _active_ming_names(db, content, 3)
    c = [n for n in names if n not in (a, b)][0]
    # 使 c 的 name 落在 a/b 之间或之外皆可——最终以排序为准
    _put_in_transit(
        db, content, c, origin="henan", dest="liaodong",
        speed_factor=1.5, start_turn=t0,
    )

    rows = project_transit_semantics(db, state, MATRIX)
    ordered = sorted(
        [
            (a, "beizhili"),
            (b, "liaodong"),
            (c, "liaodong"),
        ],
        key=lambda x: (x[0], x[1]),
    )
    assert [(r["name"], r["transit_to"]) for r in rows] == ordered
    assert all(set(r) == {"name", "transit_to", "semantic"} for r in rows)


# ── 损坏态：fail-loud，不跳行、不半行 ───────────────────────────────────────


def _corrupt_and_project(db, state, name: str, **fields):
    sets = ", ".join(f"{k}=?" for k in fields)
    db.conn.execute(
        f"UPDATE characters SET {sets} WHERE name=?",
        (*fields.values(), name),
    )
    db.conn.commit()
    return project_transit_semantics(db, state, MATRIX)


def test_corrupt_empty_location_fails_loud(game):
    db, state, content = game
    name = active_ming_character(db, content)
    _put_in_transit(
        db, content, name, origin="beizhili", dest="liaodong",
        speed_factor=1.0, start_turn=state.turn,
    )
    with pytest.raises((ValueError, KeyError)):
        _corrupt_and_project(db, state, name, location="")


@pytest.mark.parametrize("location", [" beizhili", "beizhili ", " "])
def test_corrupt_whitespace_location_fails_loud(game, location):
    """#669 r1：端点 raw 不 strip；空白损坏须 fail-loud，不得修成矩阵合法键。"""
    db, state, content = game
    name = active_ming_character(db, content)
    _put_in_transit(
        db, content, name, origin="beizhili", dest="liaodong",
        speed_factor=1.0, start_turn=state.turn,
    )
    with pytest.raises((ValueError, KeyError)):
        _corrupt_and_project(db, state, name, location=location)


@pytest.mark.parametrize("transit_to", ["liaodong ", " liaodong", " "])
def test_corrupt_whitespace_transit_to_fails_loud(game, transit_to):
    """#669 r1：端点 raw 不 strip；空白损坏须 fail-loud，不得修成矩阵合法键。"""
    db, state, content = game
    name = active_ming_character(db, content)
    _put_in_transit(
        db, content, name, origin="beizhili", dest="liaodong",
        speed_factor=1.0, start_turn=state.turn,
    )
    with pytest.raises((ValueError, KeyError)):
        _corrupt_and_project(db, state, name, transit_to=transit_to)


def test_corrupt_unknown_endpoint_fails_loud(game):
    db, state, content = game
    name = active_ming_character(db, content)
    _put_in_transit(
        db, content, name, origin="beizhili", dest="liaodong",
        speed_factor=1.0, start_turn=state.turn,
    )
    with pytest.raises(KeyError):
        _corrupt_and_project(db, state, name, transit_to="not_a_province")


@pytest.mark.parametrize("remaining", [None, 0.0, -1.0, float("nan"), float("inf")])
def test_corrupt_remaining_fails_loud(game, remaining):
    db, state, content = game
    name = active_ming_character(db, content)
    _put_in_transit(
        db, content, name, origin="beizhili", dest="liaodong",
        speed_factor=1.0, start_turn=state.turn,
    )
    with pytest.raises(ValueError):
        _corrupt_and_project(db, state, name, transit_distance_remaining=remaining)


@pytest.mark.parametrize("factor", [None, 0.0, 1.1, 3.0, 1.5000001])
def test_corrupt_factor_fails_loud(game, factor):
    db, state, content = game
    name = active_ming_character(db, content)
    _put_in_transit(
        db, content, name, origin="beizhili", dest="liaodong",
        speed_factor=1.0, start_turn=state.turn,
    )
    with pytest.raises(ValueError):
        _corrupt_and_project(db, state, name, transit_speed_factor=factor)


@pytest.mark.parametrize("start_turn", [0, -1, 1.7])
def test_corrupt_start_turn_non_positive_or_non_int_fails_loud(game, start_turn):
    db, state, content = game
    name = active_ming_character(db, content)
    _put_in_transit(
        db, content, name, origin="beizhili", dest="liaodong",
        speed_factor=1.0, start_turn=state.turn,
    )
    with pytest.raises((ValueError, TypeError)):
        _corrupt_and_project(db, state, name, transit_start_turn=start_turn)


def test_corrupt_future_start_turn_fails_loud(game):
    db, state, content = game
    name = active_ming_character(db, content)
    _put_in_transit(
        db, content, name, origin="beizhili", dest="liaodong",
        speed_factor=1.0, start_turn=state.turn,
    )
    with pytest.raises(ValueError):
        _corrupt_and_project(db, state, name, transit_start_turn=state.turn + 3)


# ── payload / context 接线 + restore + 结构哨兵 ─────────────────────────────


def _assert_no_forbidden_keys(obj, *, path: str = "") -> None:
    """结构哨兵：禁敏感键名；不把 data_note 叙述里的普通汉字当键扫描。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert k not in FORBIDDEN_KEYS, f"forbidden key at {path}.{k}"
            _assert_no_forbidden_keys(v, path=f"{path}.{k}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            _assert_no_forbidden_keys(item, path=f"{path}[{i}]")


def test_payload_and_context_wire_transit_semantics(game):
    db, state, content = game
    name = active_ming_character(db, content)
    origin, dest = "beizhili", "liaodong"
    d0 = MATRIX.travel_time(origin, dest)
    assert d0 == pytest.approx(2.1)
    _put_in_transit(
        db, content, name, origin=origin, dest=dest,
        speed_factor=1.5, start_turn=state.turn,
        distance_remaining=REMAINING_SENTINEL,
    )

    payload = build_simulator_payload(state, db, "", "")
    rows = payload["transit_semantics"]
    t = _oracle_T(d0, 1.5)
    assert rows == [{
        "name": name,
        "transit_to": dest,
        "semantic": _expected_semantic(1.5, 0, t),
    }]
    assert set(rows[0]) == {"name", "transit_to", "semantic"}
    assert "在途语义" in payload["data_note"]
    # #669 r1 / P4：transit_semantics 段只给正向事实指引，不新增反向禁令
    ts_idx = payload["data_note"].index("transit_semantics")
    next_field = payload["data_note"].find("faction_denunciation_facts", ts_idx)
    ts_clause = payload["data_note"][ts_idx:next_field if next_field >= 0 else None]
    assert "勿改" not in ts_clause
    assert "勿自算" not in ts_clause

    ctx = build_simulator_context(payload)
    assert rows[0]["semantic"] in ctx
    assert name in ctx
    assert dest in ctx
    _assert_no_forbidden_keys(payload)
    for key in FORBIDDEN_KEYS:
        # context 是渲染串：禁键名以 JSON 键形态出现（"key":）
        assert f'"{key}"' not in ctx
    # 可辨识 remaining 样值不得出现在 payload/context（证明裸账未透传）
    assert str(REMAINING_SENTINEL) not in ctx
    assert str(REMAINING_SENTINEL) not in json.dumps(
        payload.get("transit_semantics"), ensure_ascii=False,
    )


def test_restore_same_db_turn_same_projection(game):
    db, state, content = game
    name = active_ming_character(db, content)
    # start 为正：抬 turn 并落库，reload 后同 DB/turn
    state.turn = max(int(state.turn), 1) + 1
    db.save_state(state)
    start = state.turn - 1
    _put_in_transit(
        db, content, name, origin="beizhili", dest="liaodong",
        speed_factor=2.0, start_turn=start,
        distance_remaining=REMAINING_SENTINEL,
    )
    before = project_transit_semantics(db, state, MATRIX)
    payload_before = build_simulator_payload(state, db, "", "")["transit_semantics"]

    reload_state_from_db(db, state, content=content)
    after = project_transit_semantics(db, state, MATRIX)
    payload_after = build_simulator_payload(state, db, "", "")["transit_semantics"]

    assert after == before == payload_before == payload_after
    assert before[0]["semantic"] == _expected_semantic(
        2.0, 1, _oracle_T(2.1, 2.0),
    )
