"""#321 — 玩家军心/士气/欠饷投影：复用 derive + qualitative/arrears helper，四链去 raw。"""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

import web_app
from ming_sim.db import (
    GameDB,
    _player_army_situation,
    mutiny_loyalty_cap,
)
from ming_sim.army_pay import derive_army_mutiny_state
from ming_sim.flows import apply_fixed_period_flows
from ming_sim.knowledge import build_character_knowledge
from ming_sim.materials import list_materials, prepare_character_materials, read_material
ARMY = "guanning"


_RAW_KEYS = frozenset({"morale", "loyalty", "arrears"})
_SIT_KEYS = frozenset({"mutiny_tier", "morale_text", "arrears_text"})
_MUTINY_ORDINAL_KEYS = frozenset(
    {
        "is_mutinied",
        "mutiny_count",
        "mutiny_probation",
        "full_pay_streak",
        "redemption_count",
        "mutiny_status",
        "mutiny_level",
        "mutiny_state",
    }
)

# 六档真值表（票面 latch / 边界 / probation；含全部明确边界样本）
_TIER_CASES = (
    # (is_mutinied, loyalty, probation, expected_tier)
    (1, 100, 0, "哗变"),  # latch L=100
    (1, 100, 1, "哗变"),  # latch 盖过 probation
    (1, 95, 0, "哗变"),
    (1, 10, 3, "哗变"),
    (0, 39, 0, "鼓噪"),
    (0, 19, 0, "鼓噪"),  # L<20 未闩 → 鼓噪，非哗变
    (0, 30, 1, "鼓噪"),  # probation 不覆盖低档
    (0, 40, 0, "不满"),
    (0, 50, 1, "不满"),  # probation 不覆盖中低档
    (0, 59, 0, "不满"),
    (0, 60, 1, "不满"),  # probation 只挡回正常
    (0, 80, 2, "不满"),
    (0, 60, 0, "一般"),
    (0, 69, 0, "一般"),
    (0, 70, 0, "优秀"),
    (0, 79, 0, "优秀"),
    (0, 80, 0, "死忠"),
    (0, 100, 0, "死忠"),
)

_TIER_IDS = [
    f"L{loyalty}-latch{latch}-p{prob}-{tier}"
    for latch, loyalty, prob, tier in _TIER_CASES
]



@pytest.mark.parametrize(
    "is_mutinied,loyalty,probation,expected",
    _TIER_CASES,
    ids=_TIER_IDS,
)
def test_player_army_situation_six_tier_truth_table(
    is_mutinied, loyalty, probation, expected
):
    row = _row(is_mutinied=is_mutinied, loyalty=loyalty, mutiny_probation=probation)
    sit = _player_army_situation(row, monthly_pay=10)
    assert sit["mutiny_tier"] == expected
    assert isinstance(sit["morale_text"], str)
    assert isinstance(sit["arrears_text"], str)


def _configure(db) -> None:
    db.conn.execute("UPDATE armies SET manpower=0")
    db.conn.execute(
        """UPDATE armies SET owner_power='ming', is_tusi=0, self_funded_pay=0,
           manpower=10000, salary_rate=1, province_pay_share=0, central_pay_share=1,
           pay_source_region='liaodong', province_pay_arrears=0, central_pay_arrears=0
           WHERE id=?""",
        (ARMY,),
    )
    db.conn.commit()


def _write_mutiny_fixture(
    db,
    *,
    loyalty: int,
    arrears: float,
    is_mutinied: int,
    mutiny_count: int,
    mutiny_probation: int,
    full_pay_streak: int,
    redemption_count: int,
    morale: int = 55,
) -> None:
    central = arrears  # active hub source-split seed
    db.conn.execute(
        """UPDATE armies SET loyalty=?, arrears=?, is_mutinied=?,
           mutiny_count=?, mutiny_probation=?, full_pay_streak=?, redemption_count=?,
           morale=?, province_pay_arrears=0, central_pay_arrears=?,
           manpower=10000, owner_power='ming'
           WHERE id=?""",
        (
            loyalty,
            arrears,
            is_mutinied,
            mutiny_count,
            mutiny_probation,
            full_pay_streak,
            redemption_count,
            morale,
            central,
            ARMY,
        ),
    )
    db.conn.commit()


def _payload_by_id(db):
    return {p["id"]: p for p in db.army_payload()}






def _assert_structured_situation(card: dict, sit: dict, label: str) -> None:
    assert _SIT_KEYS <= set(card.keys()), f"{label} 缺 situation 三键: {sorted(card)}"
    assert _RAW_KEYS.isdisjoint(card.keys()), f"{label} 泄漏 raw 轴: {sorted(_RAW_KEYS & set(card.keys()))}"
    assert _MUTINY_ORDINAL_KEYS.isdisjoint(card.keys()), (
        f"{label} 泄漏 mutiny ordinal/五持久列: {sorted(_MUTINY_ORDINAL_KEYS & set(card.keys()))}"
    )
    assert card["mutiny_tier"] == sit["mutiny_tier"], f"{label}.mutiny_tier"
    assert card["morale_text"] == sit["morale_text"], f"{label}.morale_text"
    assert isinstance(card["mutiny_tier"], str)
    assert isinstance(card["morale_text"], str)
    assert isinstance(card["arrears_text"], str)


def test_structured_situation_on_payload_and_map_nodes(game):
    """结构化 ABI：army_payload / state_payload.armies / map_nodes 携带 situation 三键。"""
    # 代表：latch=0, L=55, p=0 → 不满；arrears>0（精确小数 12.5）
    is_mutinied, loyalty, probation, expected = 0, 55, 0, "不满"
    db, state, content = game
    _configure(db)
    arrears = 12.5
    _write_mutiny_fixture(
        db,
        loyalty=loyalty,
        arrears=arrears,
        is_mutinied=is_mutinied,
        mutiny_count=0,
        mutiny_probation=probation,
        full_pay_streak=0,
        redemption_count=0,
        morale=52,
    )
    db.conn.execute(
        """UPDATE armies SET supply=100, training=100, morale=100, loyalty=100,
           arrears=0, province_pay_arrears=0, central_pay_arrears=0,
           is_mutinied=0, mutiny_probation=0
           WHERE id != ?""",
        (ARMY,),
    )
    db.conn.execute(
        "UPDATE armies SET supply=1, training=1 WHERE id=?",
        (ARMY,),
    )
    db.conn.commit()
    row = db.conn.execute("SELECT * FROM armies WHERE id=?", (ARMY,)).fetchone()
    sit = _player_army_situation(row, db._army_pay(row))
    assert sit["mutiny_tier"] == expected

    card = _payload_by_id(db)[ARMY]
    _assert_structured_situation(card, sit, "army_payload")

    runtime = _web_runtime(db, state, content)
    payload = web_app.WebGame.state_payload(runtime)
    armies = {a["id"]: a for a in (payload.get("armies") or [])}
    assert ARMY in armies
    _assert_structured_situation(armies[ARMY], sit, "state_payload.armies")

    map_army = _find_army_in_map_nodes(payload.get("map_nodes") or [])
    _assert_structured_situation(map_army, sit, "map_nodes.armies")
    map_army2 = _find_army_in_map_nodes(runtime.map_nodes())
    _assert_structured_situation(map_army2, sit, "WebGame.map_nodes")
