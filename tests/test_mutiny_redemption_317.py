"""#317 — 连续满饷兑换军心上限，且进度跨财政路径与存档持久。"""
from __future__ import annotations

import sqlite3

import pytest

from ming_sim.db import GameDB
from ming_sim.flows import apply_fixed_period_flows

ARMY = "guanning"
PATHS = ("legacy", "substrate_hub")


def _configure(db, fiscal_path: str) -> None:
    value = 0 if fiscal_path == "legacy" else 1
    for key in ("__army_pay_source_cutover", "__fiscal_engine"):
        db.conn.execute(
            "INSERT INTO fiscal_config(key,value,kind,note) VALUES (?,?,'meta','test') "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
    db.conn.execute("UPDATE armies SET manpower=0")
    db.conn.execute(
        """UPDATE armies SET owner_power='ming', is_tusi=0, self_funded_pay=0,
           manpower=10000, salary_rate=1, province_pay_share=0, central_pay_share=1
           WHERE id=?""",
        (ARMY,),
    )
    db.conn.commit()


def _set_arrears(db, fiscal_path: str, arrears: float) -> None:
    central = arrears if fiscal_path == "substrate_hub" else 0
    db.conn.execute(
        "UPDATE armies SET arrears=?,province_pay_arrears=0,central_pay_arrears=? WHERE id=?",
        (arrears, central, ARMY),
    )
    db.conn.commit()


def _tick(db, state):
    state.metrics["国库"] = 10**9
    apply_fixed_period_flows(db, state)
    return db.conn.execute(
        """SELECT loyalty,mutiny_count,mutiny_probation,full_pay_streak,redemption_count
           FROM armies WHERE id=?""",
        (ARMY,),
    ).fetchone()


@pytest.mark.parametrize("fiscal_path", PATHS)
def test_twelve_consecutive_full_pay_months_redeem_once_and_raise_cap(game, fiscal_path):
    db, state, _ = game
    _configure(db, fiscal_path)
    db.conn.execute(
        """UPDATE armies SET loyalty=95,mutiny_count=2,mutiny_probation=2,
           full_pay_streak=11,redemption_count=0,is_mutinied=0 WHERE id=?""",
        (ARMY,),
    )
    db.conn.commit()
    _set_arrears(db, fiscal_path, 0)

    first = _tick(db, state)
    assert tuple(first[k] for k in (
        "loyalty", "mutiny_count", "mutiny_probation", "full_pay_streak", "redemption_count"
    )) == (70, 2, 1, 0, 1)

    second = _tick(db, state)
    assert tuple(second[k] for k in (
        "loyalty", "mutiny_probation", "full_pay_streak", "redemption_count"
    )) == (70, 0, 1, 1)

    for redemption_count, expected_cap in ((2, 80), (3, 90), (4, 100)):
        db.conn.execute(
            "UPDATE armies SET loyalty=100,full_pay_streak=11 WHERE id=?", (ARMY,)
        )
        db.conn.commit()
        redeemed = _tick(db, state)
        assert tuple(redeemed[k] for k in (
            "loyalty", "full_pay_streak", "redemption_count"
        )) == (expected_cap, 0, redemption_count)


@pytest.mark.parametrize("fiscal_path", PATHS)
def test_full_pay_streak_can_be_saved_in_peace_and_partial_pay_resets_it(game, fiscal_path):
    db, state, _ = game
    _configure(db, fiscal_path)
    db.conn.execute(
        "UPDATE armies SET loyalty=100,mutiny_count=0,full_pay_streak=10,redemption_count=0 WHERE id=?",
        (ARMY,),
    )
    db.conn.commit()

    _set_arrears(db, fiscal_path, 1)
    interrupted = _tick(db, state)
    assert tuple(interrupted[k] for k in ("full_pay_streak", "redemption_count")) == (0, 0)

    _set_arrears(db, fiscal_path, 0)
    resumed = _tick(db, state)
    assert tuple(resumed[k] for k in ("full_pay_streak", "redemption_count")) == (1, 0)


@pytest.mark.parametrize(
    ("redemption_count", "initial_loyalty", "expected_loyalty"),
    ((1, 60, 70), (0, 60, 60), (5, 100, 100)),
)
def test_army_delta_clamps_loyalty_to_dynamic_mutiny_cap(
    game, redemption_count, initial_loyalty, expected_loyalty
):
    db, state, _ = game
    db.conn.execute(
        """UPDATE armies SET loyalty=?,mutiny_count=2,redemption_count=?
           WHERE id=?""",
        (initial_loyalty, redemption_count, ARMY),
    )
    db.conn.commit()
    event = type("Event", (), {"id": "test", "title": "军心变更"})()

    db.apply_army_deltas(
        state, event, None, "测试", {ARMY: {"loyalty": 40}}
    )

    loyalty = db.conn.execute(
        "SELECT loyalty FROM armies WHERE id=?", (ARMY,)
    ).fetchone()["loyalty"]
    assert loyalty == expected_loyalty


@pytest.mark.parametrize("fiscal_path", PATHS)
def test_redemption_progress_migrates_and_survives_reopen(game, tmp_path, fiscal_path):
    db, state, content = game
    path = str(tmp_path / "old-save.db")
    copied = sqlite3.connect(path)
    db.conn.backup(copied)
    copied.execute("ALTER TABLE armies DROP COLUMN full_pay_streak")
    copied.execute("ALTER TABLE armies DROP COLUMN redemption_count")
    copied.close()

    migrated = GameDB(path, content)
    columns = {row["name"] for row in migrated.conn.execute("PRAGMA table_info(armies)")}
    assert {"full_pay_streak", "redemption_count"} <= columns
    defaults = migrated.conn.execute(
        "SELECT full_pay_streak,redemption_count FROM armies WHERE id=?", (ARMY,)
    ).fetchone()
    assert tuple(defaults) == (0, 0)
    migrated.conn.execute(
        "UPDATE armies SET full_pay_streak=11,redemption_count=1,mutiny_count=2,loyalty=95 WHERE id=?",
        (ARMY,),
    )
    migrated.conn.commit()
    migrated.close()

    reopened = GameDB(path, content)
    try:
        _configure(reopened, fiscal_path)
        _set_arrears(reopened, fiscal_path, 0)
        restored = _tick(reopened, state)
        assert tuple(restored[k] for k in (
            "loyalty", "full_pay_streak", "redemption_count"
        )) == (80, 0, 2)
    finally:
        reopened.close()
