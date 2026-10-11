from __future__ import annotations
from ming_sim.applier import Provenance
import sqlite3
from types import SimpleNamespace
import pytest
import web_app
from ming_sim.db import (
    GameDB,
    mutiny_loyalty_cap,
)
from ming_sim.army_pay import derive_army_mutiny_state
from ming_sim.flows import apply_fixed_period_flows
from ming_sim.db import GameDB
"""#321 — 玩家军情结构化投影：真实载荷与地图节点不暴露 raw 军情。"""




ARMY = "guanning"


_RAW_KEYS = frozenset({
    "morale", "loyalty", "arrears",
    "province_pay_arrears", "central_pay_arrears",
})
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
        """UPDATE armies SET loyalty=?, is_mutinied=?,
           mutiny_count=?, mutiny_probation=?, full_pay_streak=?, redemption_count=?,
           morale=?, province_pay_arrears=0, central_pay_arrears=?,
           manpower=10000, owner_power='ming'
           WHERE id=?""",
        (
            loyalty,
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


def _assert_structured_situation(card: dict, label: str, *, expected_tier: str | None = None) -> None:
    """真实出口结构化契约：三键在场、raw/ordinal 缺席、类型合法；档名可与独立期望比。"""
    assert _SIT_KEYS <= set(card.keys()), f"{label} 缺 situation 三键: {sorted(card)}"
    assert _RAW_KEYS.isdisjoint(card.keys()), f"{label} 泄漏 raw 轴: {sorted(_RAW_KEYS & set(card.keys()))}"
    assert _MUTINY_ORDINAL_KEYS.isdisjoint(card.keys()), (
        f"{label} 泄漏 mutiny ordinal/五持久列: {sorted(_MUTINY_ORDINAL_KEYS & set(card.keys()))}"
    )
    assert isinstance(card["mutiny_tier"], str) and card["mutiny_tier"].strip()
    assert isinstance(card["morale_text"], str) and card["morale_text"].strip()
    assert isinstance(card["arrears_text"], str) and card["arrears_text"].strip()
    if expected_tier is not None:
        assert card["mutiny_tier"] == expected_tier, f"{label}.mutiny_tier"






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
    changes, changes_rejections = db.apply_army_deltas(
        state, event, None, "测试", {ARMY: {field: 1, "reason": "probe"}}
    , source=Provenance.system_simulation)
    assert changes_rejections, f"{field} 应被拒收"
    assert all(c.category == "invalid_enum" for c in changes_rejections)
    after = db.conn.execute(
        f"SELECT {field} FROM armies WHERE id=?", (ARMY,)
    ).fetchone()[field]
    assert after == before
