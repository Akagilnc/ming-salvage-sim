"""#315 — 四档军心派生与哗变 latch 滞回（ADR 0025 D3/D4）。

seam = 月末确定性结算 tick（apply_fixed_period_flows）。
oracle 逐月断言 (loyalty, is_mutinied, derive_army_morale_state)。
"""
from __future__ import annotations

from ming_sim.flows import apply_fixed_period_flows, derive_army_morale_state

ARMY = "guanning"


def _legacy(db):
    for key in ("__army_pay_source_cutover", "__fiscal_engine"):
        db.conn.execute(
            "INSERT INTO fiscal_config(key,value,kind,note) VALUES (?,0,'meta','test') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key,),
        )


def _setup(db, *, loyalty: int, arrears: float, latched: int = 0):
    db.conn.execute("UPDATE armies SET manpower=0")
    db.conn.execute(
        """UPDATE armies SET owner_power='ming', is_tusi=0, self_funded_pay=0,
           manpower=10000, salary_rate=1, loyalty=?, arrears=?, is_mutinied=? WHERE id=?""",
        (loyalty, arrears, latched, ARMY),
    )
    db.conn.commit()


def _tick(db, state):
    state.metrics["国库"] = 10**9
    apply_fixed_period_flows(db, state)
    row = db.conn.execute(
        "SELECT loyalty, is_mutinied, arrears FROM armies WHERE id=?", (ARMY,)
    ).fetchone()
    return int(row["loyalty"]), int(row["is_mutinied"]), derive_army_morale_state(row)


def test_arrears_spiral_enters_mutiny_only_after_both_conditions(game):
    db, state, _ = game
    _legacy(db)
    _setup(db, loyalty=22, arrears=3)

    assert _tick(db, state)[:3] == (17, 0, "鼓噪")  # <20 alone, only 3 months owed
    db.conn.execute("UPDATE armies SET arrears=5 WHERE id=?", (ARMY,))
    db.conn.commit()
    assert _tick(db, state)[:3] == (12, 1, "哗变")


def test_mutiny_stays_latched_while_loyalty_recovers_below_40(game):
    db, state, _ = game
    _legacy(db)
    _setup(db, loyalty=20, arrears=0, latched=1)

    trajectory = [_tick(db, state) for _ in range(3)]
    assert [(loyalty, latch, band) for loyalty, latch, band in trajectory] == [
        (25, 1, "哗变"), (30, 1, "哗变"), (35, 1, "哗变")
    ]


def test_mutiny_exits_at_40_only_when_arrears_have_retired(game):
    db, state, _ = game
    _legacy(db)
    _setup(db, loyalty=35, arrears=0, latched=1)

    assert _tick(db, state)[:3] == (40, 0, "不满")


def test_raised_loyalty_alone_does_not_release_latch(game):
    db, state, _ = game
    _legacy(db)
    _setup(db, loyalty=40, arrears=5, latched=1)

    assert _tick(db, state)[:3] == (35, 1, "哗变")
