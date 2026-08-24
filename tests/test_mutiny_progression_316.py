"""#316 — 月末真实结算入口持久推进哗变次数、军心上限与察看期。"""
from __future__ import annotations

import sqlite3

import pytest

from ming_sim.db import GameDB
from ming_sim.flows import apply_fixed_period_flows, derive_army_mutiny_state

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


def _set(db, fiscal_path: str, *, loyalty: int, arrears: float, latched: int) -> None:
    central = arrears if fiscal_path == "substrate_hub" else 0
    db.conn.execute(
        """UPDATE armies SET loyalty=?, arrears=?, is_mutinied=?,
           province_pay_arrears=0, central_pay_arrears=? WHERE id=?""",
        (loyalty, arrears, latched, central, ARMY),
    )
    db.conn.commit()


def _tick(db, state):
    state.metrics["国库"] = 10**9
    apply_fixed_period_flows(db, state)
    return db.conn.execute(
        """SELECT loyalty,is_mutinied,mutiny_count,mutiny_probation,owner_power
           FROM armies WHERE id=?""",
        (ARMY,),
    ).fetchone()


@pytest.mark.parametrize("fiscal_path", PATHS)
def test_repeated_mutiny_persists_count_cap_and_probation(game, fiscal_path):
    db, state, _ = game
    _configure(db, fiscal_path)

    _set(db, fiscal_path, loyalty=19, arrears=5, latched=0)
    first = _tick(db, state)
    assert tuple(first[k] for k in ("loyalty", "is_mutinied", "mutiny_count", "mutiny_probation")) == (14, 1, 1, 0)

    # 持续入闩不重计；高军心也先受第一振 cap=80，再解闩。
    _set(db, fiscal_path, loyalty=95, arrears=0, latched=1)
    released = _tick(db, state)
    assert tuple(released[k] for k in ("loyalty", "is_mutinied", "mutiny_count")) == (80, 0, 1)

    _set(db, fiscal_path, loyalty=19, arrears=5, latched=0)
    second = _tick(db, state)
    assert tuple(second[k] for k in ("is_mutinied", "mutiny_count", "mutiny_probation")) == (1, 2, 3)

    # 入闩期间即使满饷也不消耗察看期；解闩时第二振 cap=60，满饷才递减。
    _set(db, fiscal_path, loyalty=20, arrears=0, latched=1)
    assert _tick(db, state)["mutiny_probation"] == 3

    # 同 tick 解闩但仍非满饷时，察看期不得提前消耗。
    _set(db, fiscal_path, loyalty=60, arrears=1, latched=1)
    partial_release = _tick(db, state)
    assert tuple(partial_release[k] for k in ("loyalty", "is_mutinied", "mutiny_probation")) == (60, 0, 3)

    _set(db, fiscal_path, loyalty=95, arrears=0, latched=1)
    probation = _tick(db, state)
    assert tuple(probation[k] for k in ("loyalty", "is_mutinied", "mutiny_count", "mutiny_probation")) == (60, 0, 2, 2)
    assert derive_army_mutiny_state(probation) == "不满"

    # 解闩后的非满饷月不减；连续满饷归零后且 loyalty>=60 才恢复正常。
    _set(db, fiscal_path, loyalty=60, arrears=1, latched=0)
    partial_pay = _tick(db, state)
    assert tuple(partial_pay[k] for k in ("loyalty", "is_mutinied", "mutiny_probation")) == (60, 0, 2)
    assert derive_army_mutiny_state(partial_pay) == "不满"
    _set(db, fiscal_path, loyalty=55, arrears=0, latched=0)
    full_pay_1 = _tick(db, state)
    assert tuple(full_pay_1[k] for k in ("loyalty", "mutiny_probation")) == (60, 1)
    assert derive_army_mutiny_state(full_pay_1) == "不满"
    _set(db, fiscal_path, loyalty=55, arrears=0, latched=0)
    full_pay_2 = _tick(db, state)
    assert tuple(full_pay_2[k] for k in ("loyalty", "mutiny_probation")) == (60, 0)
    assert derive_army_mutiny_state(full_pay_2) == "正常"

    # 察看期重入是第三振 → #318 同事务经 adapter 转流寇（清 latch）。
    _set(db, fiscal_path, loyalty=19, arrears=5, latched=0)
    third = _tick(db, state)
    assert tuple(third[k] for k in ("is_mutinied", "mutiny_count", "mutiny_probation", "owner_power")) == (0, 3, 0, "bandits")


@pytest.mark.parametrize("fiscal_path", PATHS)
def test_mutiny_count_is_capped_at_three(game, fiscal_path):
    db, state, _ = game
    _configure(db, fiscal_path)
    db.conn.execute(
        "UPDATE armies SET mutiny_count=3, mutiny_probation=0 WHERE id=?", (ARMY,)
    )
    _set(db, fiscal_path, loyalty=19, arrears=5, latched=0)

    row = _tick(db, state)

    assert row["mutiny_count"] == 3
    assert row["loyalty"] == 14  # third-strike cap remains 60, no extra penalty
    # count 已达 3 再进闩：#318 转流寇，不叠第四振
    assert row["owner_power"] == "bandits"
    assert row["is_mutinied"] == 0


@pytest.mark.parametrize("fiscal_path", PATHS)
def test_old_save_migrates_and_mutiny_progress_survives_reopen(game, tmp_path, fiscal_path):
    db, state, content = game
    path = str(tmp_path / "old-save.db")
    copied = sqlite3.connect(path)
    db.conn.backup(copied)
    copied.execute("ALTER TABLE armies DROP COLUMN mutiny_count")
    copied.execute("ALTER TABLE armies DROP COLUMN mutiny_probation")
    copied.close()

    migrated = GameDB(path, content)
    columns = {row["name"] for row in migrated.conn.execute("PRAGMA table_info(armies)")}
    assert {"mutiny_count", "mutiny_probation"} <= columns
    defaults = migrated.conn.execute(
        "SELECT mutiny_count,mutiny_probation FROM armies WHERE id=?", (ARMY,)
    ).fetchone()
    assert tuple(defaults) == (0, 0)
    migrated.conn.execute(
        "UPDATE armies SET loyalty=95,is_mutinied=1,mutiny_count=2,mutiny_probation=2 WHERE id=?",
        (ARMY,),
    )
    migrated.conn.commit()
    migrated.close()

    reopened = GameDB(path, content)
    try:
        _configure(reopened, fiscal_path)
        _set(reopened, fiscal_path, loyalty=95, arrears=0, latched=1)
        restored = _tick(reopened, state)
        assert tuple(restored[k] for k in ("loyalty", "is_mutinied", "mutiny_count", "mutiny_probation")) == (60, 0, 2, 1)
        assert derive_army_mutiny_state(restored) == "不满"

        _set(reopened, fiscal_path, loyalty=55, arrears=0, latched=0)
        recovered = _tick(reopened, state)
        assert tuple(recovered[k] for k in ("loyalty", "is_mutinied", "mutiny_count", "mutiny_probation")) == (60, 0, 2, 0)
        assert derive_army_mutiny_state(recovered) == "正常"
    finally:
        reopened.close()
