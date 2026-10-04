"""#315 — 四档哗变状态派生与 latch 滞回（ADR 0025 D3/D4）。

seam = 月末确定性结算 tick（apply_fixed_period_flows）。
oracle 逐月断言 (loyalty, is_mutinied, derive_army_mutiny_state)。
"""
from __future__ import annotations

import math

import pytest

from ming_sim.army_pay import derive_army_mutiny_state
from ming_sim.flows import apply_fixed_period_flows
ARMY = "guanning"


def _configure(db):
    value = 1  # active substrate_hub cutover
    for key in ("__army_pay_source_cutover", "__fiscal_engine"):
        db.conn.execute(
            "INSERT INTO fiscal_config(key,value,kind,note) VALUES (?,?,'meta','test') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def _setup(
    db,
    *,
    loyalty: int,
    arrears: float,
    latched: int = 0,
    is_tusi: int = 0,
    self_funded_pay: int = 0,
):
    _configure(db)
    db.conn.execute("UPDATE armies SET manpower=0")
    if is_tusi or self_funded_pay:
        # 现役 cutover 守恒：豁免军份额/欠饷须全 0；本案只验 latch 不被 tick 改写。
        db.conn.execute(
            """UPDATE armies SET owner_power='ming', is_tusi=?, self_funded_pay=?,
               manpower=10000, salary_rate=1, loyalty=?, arrears=0, is_mutinied=?,
               pay_source_region='', province_pay_share=0, central_pay_share=0,
               province_pay_arrears=0, central_pay_arrears=0 WHERE id=?""",
            (is_tusi, self_funded_pay, loyalty, latched, ARMY),
        )
    else:
        # hub 走全中央饷源；总欠与分源欠同步，确保结算确实从 hub 真源重算 latch。
        central_arrears = arrears  # active hub source-split seed
        db.conn.execute(
            """UPDATE armies SET owner_power='ming', is_tusi=0, self_funded_pay=0,
               manpower=10000, salary_rate=1, loyalty=?, arrears=?, is_mutinied=?,
               province_pay_share=0, central_pay_share=1,
               province_pay_arrears=0, central_pay_arrears=? WHERE id=?""",
            (loyalty, arrears, latched, central_arrears, ARMY),
        )
    db.conn.commit()


def _set_arrears(db, arrears: float):
    central_arrears = arrears  # active hub source-split seed
    db.conn.execute(
        "UPDATE armies SET arrears=?, province_pay_arrears=0, central_pay_arrears=? WHERE id=?",
        (arrears, central_arrears, ARMY),
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
    game, exemption, flags, loyalty, arrears, latched
):
    db, state, _ = game
    _setup(db, loyalty=loyalty, arrears=arrears, latched=latched, **flags)

    assert _tick(db, state)[1] == latched, exemption


def test_mutiny_latch_enters_only_beyond_four_months_arrears(game):
    """入闩侧：欠饷恰好四月不入闩，逾四月即入闩——经真实 tick 落库断言。"""
    db, state, _ = game
    four_months = 4.0

    _setup(db, loyalty=19, arrears=four_months, latched=0)
    assert _tick(db, state)[1] == 0

    _set_arrears(db, math.nextafter(four_months, math.inf))
    assert _tick(db, state)[1] == 1


def test_mutiny_latch_exits_only_within_four_months_arrears(game):
    """解闩侧：欠饷退到四月内即解闩，逾四月仍闩——经真实 tick 落库断言。"""
    db, state, _ = game
    four_months = 4.0

    _setup(db, loyalty=45, arrears=four_months, latched=1)
    assert _tick(db, state)[1] == 0


def test_mutiny_latch_holds_beyond_four_months_arrears(game):
    """解闩侧负例：已闩军欠饷逾四月，即便 loyalty 回到 40 也不解闩。"""
    db, state, _ = game
    four_months = 4.0

    _setup(db, loyalty=45, arrears=math.nextafter(four_months, math.inf), latched=1)
    assert _tick(db, state)[1] == 1
