"""#320 — extractor loyalty 软调全路径 ±15 钳（无豁免）。

验收（落库 seam：apply_army_deltas）：
① 正/负大增量被钳 ±15，触底再 clamp 到 0
② 动态 mutiny_loyalty_cap 仍是硬顶（先 ±15 再 cap）
③ 确定性 tick ±5 不受 ±15 影响（走 flows 另一路）
④ 单次叙事不能把 loyalty 瞬间拉满
⑤ 伪造 id / 自由文本锚点 / strategic_foreign 不得充当豁免
"""
from __future__ import annotations

import pytest

from ming_sim.flows import apply_fixed_period_flows

ARMY = "guanning"


def _event(event_id: object = "test", title: str = "军心变更"):
    return type("Event", (), {"id": event_id, "title": title})()


def _set_loyalty(db, *, loyalty: int, mutiny_count: int = 0, redemption_count: int = 0) -> None:
    db.conn.execute(
        """UPDATE armies SET loyalty=?, mutiny_count=?, redemption_count=?,
           is_mutinied=0, mutiny_probation=0 WHERE id=?""",
        (loyalty, mutiny_count, redemption_count, ARMY),
    )
    db.conn.commit()


def _loyalty(db) -> int:
    return int(
        db.conn.execute("SELECT loyalty FROM armies WHERE id=?", (ARMY,)).fetchone()["loyalty"]
    )


def _apply(db, state, delta: dict, *, event=None, origin_ref: str = ""):
    return db.apply_army_deltas(
        state,
        event or _event(),
        None,
        "测试",
        {ARMY: delta},
        origin_ref=origin_ref,
    )


def test_positive_large_delta_clamped_to_plus_15(game):
    """①a generic 软调 +50 → 净 +15。"""
    db, state, _ = game
    _set_loyalty(db, loyalty=40)

    changes = _apply(db, state, {"loyalty": 50})

    assert _loyalty(db) == 55
    loyalty_changes = [c for c in changes if c.get("field") == "loyalty" and not c.get("rejected")]
    assert loyalty_changes and loyalty_changes[0]["delta"] == 15
    assert loyalty_changes[0]["old"] == 40
    assert loyalty_changes[0]["new"] == 55


@pytest.mark.parametrize('loyalty, mutiny_count, delta, expected', [(40, 0, {"loyalty": -50}, 25), (5, 0, {"loyalty": -50}, 0), (50, 2, {"loyalty": 50}, 60), (40, 0, {"军心": 50}, 55)])
def test_negative_large_delta_clamped_to_minus_15(game, loyalty, mutiny_count, delta, expected):
    db, state, _ = game
    _set_loyalty(db, loyalty=loyalty, mutiny_count=mutiny_count, redemption_count=0)

    _apply(db, state, delta)

    assert _loyalty(db) == expected


def test_deterministic_tick_plus_five_unaffected_by_soft_clamp(game):
    """③ tick 满饷 +5 走 flows 直写，不被 ±15 改写。"""
    db, state, _ = game
    db.conn.execute(
        """UPDATE armies SET manpower=0"""
    )
    db.conn.execute(
        "UPDATE armies SET owner_power='ming', is_tusi=0, self_funded_pay=0,\n           manpower=10000, salary_rate=1, province_pay_share=0, central_pay_share=1, province_pay_arrears=0, central_pay_arrears=0,\n           loyalty=40, mutiny_count=0, redemption_count=0, is_mutinied=0,\n           mutiny_probation=0, full_pay_streak=0 WHERE id=?",
        (ARMY,),
    )
    db.conn.commit()

    state.metrics["国库"] = 10**9
    apply_fixed_period_flows(db, state)

    assert _loyalty(db) == 45


@pytest.mark.parametrize(
    "kwargs",
    [
        {"event": _event(event_id="forged-trusted-event-id"), "delta": {"loyalty": 50}},
        {
            "event": _event(),
            "delta": {"loyalty": 50, "reason": "安抚诏：strategic_foreign 特赦"},
            "origin_ref": "free-text-anchor://forged",
        },
        {
            "event": _event(title="strategic_foreign 豁免叙事"),
            "delta": {"loyalty": 50, "origin_ref": "strategic_foreign"},
            "origin_ref": "strategic_foreign",
        },
    ],
    ids=["forged_event_id", "free_text_reason_origin", "strategic_foreign_label"],
)
def test_fake_exemption_markers_do_not_bypass_soft_clamp(game, kwargs):
    """⑤ 伪豁免标记一律仍受 ±15。"""
    db, state, _ = game
    _set_loyalty(db, loyalty=40)

    _apply(
        db,
        state,
        kwargs["delta"],
        event=kwargs.get("event"),
        origin_ref=kwargs.get("origin_ref", ""),
    )

    assert _loyalty(db) == 55


@pytest.mark.parametrize('value, expected, actual_delta', [(50, 85, 15), (-50, 55, -15)])
def test_canonical_and_alias_same_event_do_not_double_count_positive(game, value, expected, actual_delta):
    db, state, _ = game
    _set_loyalty(db, loyalty=70)

    changes = _apply(db, state, {"loyalty": value, "军心": value})

    assert _loyalty(db) == expected
    loyalty_changes = [c for c in changes if c.get("field") == "loyalty" and not c.get("rejected")]
    assert len(loyalty_changes) == 1
    assert loyalty_changes[0]["delta"] == actual_delta
    assert loyalty_changes[0]["old"] == 70
    assert loyalty_changes[0]["new"] == expected
