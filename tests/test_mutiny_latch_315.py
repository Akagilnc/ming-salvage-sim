"""#315 — 四档哗变状态派生与 latch 滞回（ADR 0025 D3/D4）。

seam = 月末确定性结算 tick（apply_fixed_period_flows）。
oracle 逐月断言 (loyalty, is_mutinied, derive_army_mutiny_state)。
"""
from __future__ import annotations

import math

import pytest

from ming_sim.flows import (
    _next_mutiny_latch,
    apply_fixed_period_flows,
    derive_army_mutiny_state,
)
ARMY = "guanning"


def _setup(
    db,

    *,
    loyalty: int,
    arrears: float,
    latched: int = 0,
    is_tusi: int = 0,
    self_funded_pay: int = 0,
):
    db.conn.execute("UPDATE armies SET manpower=0")
    # 土司/自养不进军心 tick，双累加器与总欠必须为 0。明军走全中央饷源。
    exempt = bool(is_tusi or self_funded_pay)
    central_share = 0 if exempt else 1
    stored_arrears = 0 if exempt else arrears
    central_arrears = 0 if exempt else arrears
    db.conn.execute(
        "UPDATE armies SET owner_power='ming', is_tusi=?, self_funded_pay=?,\n           manpower=10000, salary_rate=1, loyalty=?, is_mutinied=?,\n           province_pay_share=0, central_pay_share=?,\n           province_pay_arrears=0, central_pay_arrears=? WHERE id=?",
        (is_tusi, self_funded_pay, loyalty, latched, central_share, central_arrears, ARMY,),
    )
    db.conn.commit()


def _set_arrears(db,  arrears: float):
    central_arrears = arrears
    db.conn.execute(
        'UPDATE armies SET  province_pay_arrears=0, central_pay_arrears=? WHERE id=?',
        (central_arrears, ARMY,),
    )
    db.conn.commit()


def _tick(db, state):
    state.metrics["国库"] = 10**9
    apply_fixed_period_flows(db, state)
    row = db.conn.execute(
        "SELECT loyalty, is_mutinied, arrears FROM armies WHERE id=?", (ARMY,)
    ).fetchone()
    return int(row["loyalty"]), int(row["is_mutinied"]), derive_army_mutiny_state(row)


def test_arrears_spiral_enters_mutiny_only_after_both_conditions(game):
    db, state, _ = game
    _setup(db, loyalty=22, arrears=3)

    assert _tick(db, state)[:3] == (17, 0, "鼓噪")  # <20 alone, only 3 months owed
    _set_arrears(db, 5)
    assert _tick(db, state)[:3] == (12, 1, "哗变")


def test_mutiny_stays_latched_while_loyalty_recovers_below_40(game):
    db, state, _ = game
    _setup(db, loyalty=20, arrears=0, latched=1)

    trajectory = [_tick(db, state) for _ in range(3)]
    assert trajectory == [
        (25, 1, "哗变"), (30, 1, "哗变"), (35, 1, "哗变")
    ]


def test_mutiny_exits_at_40_only_when_arrears_have_retired(game):
    db, state, _ = game
    _setup(db, loyalty=35, arrears=0, latched=1)

    assert _tick(db, state)[:3] == (40, 0, "不满")


def test_raised_loyalty_alone_does_not_release_latch(game):
    db, state, _ = game
    _setup(db, loyalty=45, arrears=5, latched=1)

    assert _tick(db, state)[:3] == (40, 1, "哗变")


@pytest.mark.parametrize(
    ("loyalty", "latched", "expected"),
    [
        (39, 0, "鼓噪"),
        (40, 0, "不满"),
        (59, 0, "不满"),
        (60, 0, "正常"),
        (40, 1, "哗变"),
        (60, 1, "哗变"),
    ],
)
def test_derive_mutiny_state_boundaries_and_latch(loyalty, latched, expected):
    army = {"loyalty": loyalty, "is_mutinied": latched}

    assert derive_army_mutiny_state(army) == expected


@pytest.mark.parametrize(
    ("exemption", "flags"),
    [("tusi", {"is_tusi": 1}), ("self_funded", {"self_funded_pay": 1})],
)
@pytest.mark.parametrize(
    ("loyalty", "arrears", "latched"),
    [(10, 5, 0), (45, 0, 1)],
    ids=("would-enter", "would-exit"),
)
def test_exempt_armies_preserve_mutiny_latch(
    game,  exemption, flags, loyalty, arrears, latched
):
    db, state, _ = game
    _setup(db, loyalty=loyalty, arrears=arrears, latched=latched, **flags)

    assert _tick(db, state)[1] == latched, exemption


def test_mutiny_latch_uses_strict_four_month_arrears_boundary():
    four_months = 4.0
    over_four_months = math.nextafter(four_months, math.inf)

    assert _next_mutiny_latch(loyalty=19, arrears=four_months, needed=1, current=0) == 0
    assert _next_mutiny_latch(loyalty=19, arrears=over_four_months, needed=1, current=0) == 1
    assert _next_mutiny_latch(loyalty=40, arrears=four_months, needed=1, current=1) == 0
    assert _next_mutiny_latch(loyalty=40, arrears=over_four_months, needed=1, current=1) == 1
