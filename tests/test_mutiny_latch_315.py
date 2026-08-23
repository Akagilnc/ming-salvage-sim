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
from ming_sim.simulation import _extractor_context_payload, build_simulator_payload

ARMY = "guanning"
PATHS = ("legacy", "substrate_hub")


def _configure_fiscal_path(db, fiscal_path: str):
    value = 0 if fiscal_path == "legacy" else 1
    for key in ("__army_pay_source_cutover", "__fiscal_engine"):
        db.conn.execute(
            "INSERT INTO fiscal_config(key,value,kind,note) VALUES (?,?,'meta','test') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def _setup(db, fiscal_path: str, *, loyalty: int, arrears: float, latched: int = 0):
    _configure_fiscal_path(db, fiscal_path)
    db.conn.execute("UPDATE armies SET manpower=0")
    # hub 走全中央饷源；总欠与分源欠同步，确保结算确实从 hub 真源重算 latch。
    central_arrears = arrears if fiscal_path == "substrate_hub" else 0
    db.conn.execute(
        """UPDATE armies SET owner_power='ming', is_tusi=0, self_funded_pay=0,
           manpower=10000, salary_rate=1, loyalty=?, arrears=?, is_mutinied=?,
           province_pay_share=0, central_pay_share=1,
           province_pay_arrears=0, central_pay_arrears=? WHERE id=?""",
        (loyalty, arrears, latched, central_arrears, ARMY),
    )
    db.conn.commit()


def _set_arrears(db, fiscal_path: str, arrears: float):
    central_arrears = arrears if fiscal_path == "substrate_hub" else 0
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


@pytest.mark.parametrize("fiscal_path", PATHS)
def test_arrears_spiral_enters_mutiny_only_after_both_conditions(game, fiscal_path):
    db, state, _ = game
    _setup(db, fiscal_path, loyalty=22, arrears=3)

    assert _tick(db, state)[:3] == (17, 0, "鼓噪")  # <20 alone, only 3 months owed
    _set_arrears(db, fiscal_path, 5)
    assert _tick(db, state)[:3] == (12, 1, "哗变")


@pytest.mark.parametrize("fiscal_path", PATHS)
def test_mutiny_stays_latched_while_loyalty_recovers_below_40(game, fiscal_path):
    db, state, _ = game
    _setup(db, fiscal_path, loyalty=20, arrears=0, latched=1)

    trajectory = [_tick(db, state) for _ in range(3)]
    assert trajectory == [
        (25, 1, "哗变"), (30, 1, "哗变"), (35, 1, "哗变")
    ]


@pytest.mark.parametrize("fiscal_path", PATHS)
def test_mutiny_exits_at_40_only_when_arrears_have_retired(game, fiscal_path):
    db, state, _ = game
    _setup(db, fiscal_path, loyalty=35, arrears=0, latched=1)

    assert _tick(db, state)[:3] == (40, 0, "不满")


@pytest.mark.parametrize("fiscal_path", PATHS)
def test_raised_loyalty_alone_does_not_release_latch(game, fiscal_path):
    db, state, _ = game
    _setup(db, fiscal_path, loyalty=45, arrears=5, latched=1)

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


def _projected_army(payload, expected_name):
    armies = payload["armies"]
    id_index = armies["cols"].index("id") if "id" in armies["cols"] else None
    name_index = armies["cols"].index("name")
    for values in armies["rows"]:
        if (id_index is not None and values[id_index] == ARMY) or values[name_index] == expected_name:
            return dict(zip(armies["cols"], values))
    raise AssertionError(f"army {ARMY!r} not projected")


@pytest.mark.parametrize("fiscal_path", PATHS)
@pytest.mark.parametrize(
    ("loyalty", "arrears", "expected_state"),
    [(22, 3, "鼓噪"), (17, 5, "哗变")],
)
def test_tick_projects_derived_mutiny_state_to_both_consumers(
    game, fiscal_path, loyalty, arrears, expected_state
):
    db, state, _ = game
    _setup(db, fiscal_path, loyalty=loyalty, arrears=arrears)
    expected_name = db.conn.execute(
        "SELECT name FROM armies WHERE id=?", (ARMY,)
    ).fetchone()["name"]
    _tick(db, state)

    payloads = (
        build_simulator_payload(state, db, "", ""),
        _extractor_context_payload(db, state, "", ""),
    )
    for payload in payloads:
        army = _projected_army(payload, expected_name)
        assert army["mutiny_state"] == expected_state
        assert "is_mutinied" not in army


def test_mutiny_latch_uses_strict_four_month_arrears_boundary():
    four_months = 4.0
    over_four_months = math.nextafter(four_months, math.inf)

    assert _next_mutiny_latch(loyalty=19, arrears=four_months, needed=1, current=0) == 0
    assert _next_mutiny_latch(loyalty=19, arrears=over_four_months, needed=1, current=0) == 1
    assert _next_mutiny_latch(loyalty=40, arrears=four_months, needed=1, current=1) == 0
    assert _next_mutiny_latch(loyalty=40, arrears=over_four_months, needed=1, current=1) == 1
