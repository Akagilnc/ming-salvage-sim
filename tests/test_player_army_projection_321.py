"""#321 — 玩家军心/士气/欠饷投影：复用 derive + qualitative/arrears helper，四链去 raw。"""
from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

import web_app
from ming_sim.db import (
    GameDB,
)
from ming_sim.flows import apply_fixed_period_flows

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


def _web_runtime(db, state, content):
    """轻壳 WebGame：走真实 state_payload / map_nodes（session 属性代理 db/state）。"""
    runtime = object.__new__(web_app.WebGame)
    runtime.session = SimpleNamespace(
        db=db,
        state=state,
        content=content,
        pending_count=lambda: 0,
        pending_decisions=lambda: [],
        victory=lambda: {"status": "ongoing", "summary": ""},
        previous_summary="",
        last_decree="",
        last_report="",
    )
    runtime.directive_rows = lambda: []
    runtime.issue_payloads = lambda: []
    runtime.legacies_payload = lambda: []
    runtime.closed_this_turn_payloads = lambda: []
    runtime.ending_payload = lambda: None
    runtime.budget_payload = lambda: {}
    runtime.public_character = lambda c: {"name": getattr(c, "name", "")}
    runtime.character_power_id = lambda c: "ming"
    runtime._month_open_snapshot = lambda: None
    runtime._display_metrics = lambda: dict(state.metrics)
    # 真实 map_nodes（army_payload 片段挂到节点）
    runtime.map_nodes = lambda: web_app.WebGame.map_nodes(runtime)
    runtime._theater_label = lambda tid: web_app.WebGame._theater_label(runtime, tid)
    return runtime


def _find_army_in_map_nodes(nodes, army_id: str = ARMY):
    for node in nodes:
        for army in node.get("armies") or []:
            if army.get("id") == army_id:
                return army
    raise AssertionError(f"map_nodes 未挂载军队 {army_id}")


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


@pytest.mark.parametrize("is_mutinied,loyalty,probation,expected", [
    (1, 100, 0, "哗变"), (1, 100, 1, "哗变"), (1, 95, 0, "哗变"), (1, 10, 3, "哗变"),
    (0, 39, 0, "鼓噪"), (0, 19, 0, "鼓噪"), (0, 30, 1, "鼓噪"),
    (0, 40, 0, "不满"), (0, 50, 1, "不满"), (0, 59, 0, "不满"),
    (0, 60, 1, "不满"), (0, 80, 2, "不满"), (0, 60, 0, "一般"), (0, 69, 0, "一般"),
    (0, 70, 0, "优秀"), (0, 79, 0, "优秀"), (0, 80, 0, "死忠"), (0, 100, 0, "死忠"),
])
def test_structured_situation_on_payload_and_map_nodes(game, is_mutinied, loyalty, probation, expected):
    """结构化 ABI：army_payload / state_payload.armies / map_nodes 携带 situation 三键。"""
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
    card = _payload_by_id(db)[ARMY]
    assert card["mutiny_tier"] == expected
    sit = card
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


def test_restore_five_columns_and_player_tier_survives_reopen(game, tmp_path):
    """AC6–9：五持久列跨 reopen；仅凭 DB load_state 接续 tick；tick 后逐字段 oracle。"""
    db, _state, content = game
    path = str(tmp_path / "restore-321-hub.db")
    copied = sqlite3.connect(path)
    db.conn.backup(copied)
    copied.close()

    opened = GameDB(path, content)
    try:
        _configure(opened)
        # 票面 literal：count=2 redemption=1 → cap=70；streak=7 → tick 后 8；probation 2→1
        _write_mutiny_fixture(
            opened,
            loyalty=95,
            arrears=0,
            is_mutinied=1,
            mutiny_count=2,
            mutiny_probation=2,
            full_pay_streak=7,
            redemption_count=1,
            morale=60,
        )
    finally:
        opened.close()

    reopened = GameDB(path, content)
    try:
        row = reopened.conn.execute(
            "SELECT * FROM armies WHERE id=?", (ARMY,)
        ).fetchone()
        assert tuple(
            row[k]
            for k in (
                "is_mutinied",
                "mutiny_count",
                "mutiny_probation",
                "full_pay_streak",
                "redemption_count",
            )
        ) == (1, 2, 2, 7, 1)
        assert int(row["loyalty"]) == 95
        assert float(row["arrears"]) == pytest.approx(0)
        assert int(row["manpower"]) == 10000
        card_before = _payload_by_id(reopened)[ARMY]
        assert card_before["mutiny_tier"] == "哗变"

        # P1：仅凭 DB 重建恢复态，再在恢复态上设测用国库并 tick
        restored_state = reopened.load_state()
        restored_state.metrics["国库"] = 10**9
        apply_fixed_period_flows(reopened, restored_state)
        after = reopened.conn.execute(
            "SELECT * FROM armies WHERE id=?", (ARMY,)
        ).fetchone()
        assert int(after["loyalty"]) == 70
        assert int(after["is_mutinied"]) == 0
        assert int(after["mutiny_count"]) == 2
        assert int(after["mutiny_probation"]) == 1
        assert int(after["full_pay_streak"]) == 8
        assert int(after["redemption_count"]) == 1
        assert float(after["arrears"]) == pytest.approx(0)
        assert int(after["manpower"]) == 10000
        assert _payload_by_id(reopened)[ARMY]["mutiny_tier"] == "不满"
    finally:
        reopened.close()


@pytest.mark.parametrize(
    "field",
    ("is_mutinied", "mutiny_count", "mutiny_probation", "full_pay_streak", "redemption_count"),
)
def test_apply_army_deltas_rejects_five_persistent_mutiny_columns(game, field):
    """AC10：五持久列对 extractor 唯一 allowlist 拒收，不新守门。"""
    db, state, _ = game
    before = db.conn.execute(
        f"SELECT {field} FROM armies WHERE id=?", (ARMY,)
    ).fetchone()[field]
    event = SimpleNamespace(id="test-321", title="非法写哗变列")
    changes = db.apply_army_deltas(
        state, event, None, "测试", {ARMY: {field: 1, "reason": "probe"}}
    )
    rejected = [c for c in changes if c.get("rejected")]
    assert rejected, f"{field} 应被拒收"
    assert all(c.get("category") == "invalid_enum" for c in rejected)
    after = db.conn.execute(
        f"SELECT {field} FROM armies WHERE id=?", (ARMY,)
    ).fetchone()[field]
    assert after == before
