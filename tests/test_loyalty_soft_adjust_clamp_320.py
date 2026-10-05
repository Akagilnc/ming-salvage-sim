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


def test_junxin_alias_also_soft_clamped(game):
    """可选薄覆盖：中文「军心」别名走同一 loyalty 分支，同受 ±15。"""
    db, state, _ = game
    _set_loyalty(db, loyalty=40)

    _apply(db, state, {"军心": 50})

    assert _loyalty(db) == 55


def test_canonical_and_alias_same_event_do_not_double_count_positive(game):
    """p2：同事件 {loyalty:50, 军心:50} 不得累计绕过；净软调 |Σδ|≤15 → 70+15=85。"""
    db, state, _ = game
    _set_loyalty(db, loyalty=70)

    changes = _apply(db, state, {"loyalty": 50, "军心": 50})

    assert _loyalty(db) == 85
    assert _loyalty(db) != 100
    loyalty_changes = [c for c in changes if c.get("field") == "loyalty" and not c.get("rejected")]
    assert len(loyalty_changes) == 1
    assert loyalty_changes[0]["delta"] == 15
    assert loyalty_changes[0]["old"] == 70
    assert loyalty_changes[0]["new"] == 85


def test_canonical_and_alias_same_event_do_not_double_count_negative(game):
    """p2 对称：同事件 {loyalty:-50, 军心:-50} 净软调 ≥ -15 → 70-15=55（非 40）。"""
    db, state, _ = game
    _set_loyalty(db, loyalty=70)

    changes = _apply(db, state, {"loyalty": -50, "军心": -50})

    assert _loyalty(db) == 55
    assert _loyalty(db) != 40
    loyalty_changes = [c for c in changes if c.get("field") == "loyalty" and not c.get("rejected")]
    assert len(loyalty_changes) == 1
    assert loyalty_changes[0]["delta"] == -15
    assert loyalty_changes[0]["old"] == 70
    assert loyalty_changes[0]["new"] == 55
