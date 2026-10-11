"""#318 — 第3振转流寇 + owner_power 唯一写口 + 空来源受限（ADR 0025 D5/D7）。

seam = 月末确定性结算 tick（apply_fixed_period_flows）
     + apply_army_deltas / transition_army_owner_power 唯一 adapter。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from ming_sim.flows import apply_fixed_period_flows
from tests.army_pay_helpers import configure_guanning_army

ARMY = "guanning"
BANDIT_POWERS = frozenset({"bandits", "bandit_li_zicheng"})


def _set(
    db,
    *,
    loyalty: int,
    arrears: float,
    latched: int,
    mutiny_count: int | None = None,
    mutiny_probation: int | None = None,
    manpower: int | None = None,
) -> None:
    central = arrears  # active hub source-split seed
    db.conn.execute(
        """UPDATE armies SET loyalty=?, arrears=?, is_mutinied=?,
           province_pay_arrears=0, central_pay_arrears=? WHERE id=?""",
        (loyalty, arrears, latched, central, ARMY),
    )
    if mutiny_count is not None:
        db.conn.execute(
            "UPDATE armies SET mutiny_count=? WHERE id=?", (mutiny_count, ARMY)
        )
    if mutiny_probation is not None:
        db.conn.execute(
            "UPDATE armies SET mutiny_probation=? WHERE id=?", (mutiny_probation, ARMY)
        )
    if manpower is not None:
        db.conn.execute(
            "UPDATE armies SET manpower=? WHERE id=?", (manpower, ARMY)
        )
    db.conn.commit()


def _tick(db, state):
    state.metrics["国库"] = 10**9
    apply_fixed_period_flows(db, state)
    return db.conn.execute(
        """SELECT loyalty,is_mutinied,mutiny_count,mutiny_probation,owner_power,
                  arrears,province_pay_arrears,central_pay_arrears,
                  pay_source_region,province_pay_share,central_pay_share
           FROM armies WHERE id=?""",
        (ARMY,),
    ).fetchone()


def _logs(db, fields: tuple[str, ...]):
    placeholders = ",".join("?" * len(fields))
    return db.conn.execute(
        f"""SELECT id, field, old_value, new_value, delta, reason
            FROM army_logs
            WHERE army_id=? AND field IN ({placeholders})
            ORDER BY id""",
        (ARMY, *fields),
    ).fetchall()


def test_third_strike_transfers_to_bandit_via_adapter(game):
    db, state, _ = game
    configure_guanning_army(db)
    # count 已 2：再 0→1 进闩即第 3 振
    _set(
        db, loyalty=19, arrears=5, latched=0,
        mutiny_count=2, mutiny_probation=0,
    )
    before_arrears = float(
        db.conn.execute("SELECT arrears FROM armies WHERE id=?", (ARMY,)).fetchone()[
            "arrears"
        ]
    )
    assert before_arrears > 0

    row = _tick(db, state)

    assert row["mutiny_count"] == 3
    assert row["is_mutinied"] == 0  # 清 latch 先于/同于改 owner
    assert row["mutiny_probation"] == 0
    assert row["owner_power"] in BANDIT_POWERS
    assert float(row["arrears"]) == pytest.approx(0)
    assert float(row["province_pay_arrears"]) == pytest.approx(0)
    assert float(row["central_pay_arrears"]) == pytest.approx(0)
    assert row["pay_source_region"] in ("", None)
    assert float(row["province_pay_share"] or 0) == pytest.approx(0)
    assert float(row["central_pay_share"] or 0) == pytest.approx(0)

    logs = _logs(db, ("arrears", "is_mutinied", "owner_power", "mutiny_count"))
    writeoff = next(
        (
            log
            for log in logs
            if log["field"] == "arrears"
            and float(log["old_value"]) > 0
            and float(log["new_value"]) == 0
            and float(log["delta"]) < 0
        ),
        None,
    )
    latch_clear = next(
        (
            log
            for log in logs
            if log["field"] == "is_mutinied"
            and str(log["old_value"]) in {"1", "True"}
            and str(log["new_value"]) in {"0", "False"}
        ),
        None,
    )
    # 第三振：可能从未把 latch 写成 1 即清；允许「清 latch」日志缺省，但 owner 必有
    owner_log = next((log for log in logs if log["field"] == "owner_power"), None)
    count_log = next(
        (
            log
            for log in logs
            if log["field"] == "mutiny_count" and int(float(log["new_value"])) == 3
        ),
        None,
    )
    assert writeoff is not None
    assert owner_log is not None
    assert count_log is not None
    assert owner_log["new_value"] in BANDIT_POWERS
    # 核销先于 owner；清 latch 若有则亦先于 owner（id 不可等，不写被包含区间 OR）。
    assert writeoff["id"] < owner_log["id"]
    if latch_clear is not None:
        assert latch_clear["id"] < owner_log["id"]


def test_third_strike_does_not_repeat_while_already_bandit(game):
    db, state, _ = game
    configure_guanning_army(db)
    _set(
        db, loyalty=19, arrears=5, latched=0,
        mutiny_count=2, mutiny_probation=0,
    )
    first = _tick(db, state)
    assert first["owner_power"] in BANDIT_POWERS
    owner_after = first["owner_power"]

    # 再 tick：非明军不走军心/哗变，不得重复转移或回 ming
    second = _tick(db, state)
    assert second["owner_power"] == owner_after
    assert second["mutiny_count"] == 3
    owner_logs = [
        log for log in _logs(db, ("owner_power",)) if log["field"] == "owner_power"
    ]
    assert len(owner_logs) == 1


def test_zero_manpower_latched_clears_before_continue_no_third_strike(game):
    db, state, _ = game
    configure_guanning_army(db)
    _set(
        db, loyalty=10, arrears=9, latched=1,
        mutiny_count=2, mutiny_probation=3, manpower=0,
    )

    row = _tick(db, state)

    assert row["is_mutinied"] == 0
    assert row["mutiny_count"] == 2  # 不误触第三振
    assert row["owner_power"] == "ming"
    assert row["mutiny_probation"] == 3  # 只清 latch
    logs = [
        log
        for log in _logs(db, ("is_mutinied",))
        if str(log["new_value"]) in {"0", "False"}
    ]
    assert logs, "零兵清闩须写 army_logs 审计"


def test_empty_source_delta_cannot_defect_latched_first_or_second_strike(game):
    """DB adapter 事实契约（apply_army_deltas）：空来源不得改 latched 军归属。"""
    db, state, _ = game
    configure_guanning_army(db)
    for count in (1, 2):
        _set(
            db, loyalty=15, arrears=6, latched=1,
            mutiny_count=count, mutiny_probation=0 if count == 1 else 3,
        )
        db.conn.execute(
            "UPDATE armies SET owner_power='ming', pay_source_region='liaodong',"
            " province_pay_share=0, central_pay_share=1 WHERE id=?",
            (ARMY,),
        )
        db.conn.commit()
        before = db.conn.execute(
            "SELECT owner_power,is_mutinied,arrears,mutiny_count FROM armies WHERE id=?",
            (ARMY,),
        ).fetchone()

        changes = db.apply_army_deltas(
            state,
            SimpleNamespace(id="season", title="空来源归属"),
            None,
            "测试",
            {ARMY: {"owner_power": "houjin", "reason": "投敌"}},
            commit=False,
        )

        after = db.conn.execute(
            "SELECT owner_power,is_mutinied,arrears,mutiny_count FROM armies WHERE id=?",
            (ARMY,),
        ).fetchone()
        assert dict(after) == dict(before)
        assert after["owner_power"] == "ming"
        assert after["is_mutinied"] == 1
        # 拒收或 no-op：不得出现成功的 owner 变更
        assert not any(
            c.get("field") == "owner_power" and not c.get("rejected") for c in changes
        )


def test_non_latched_generic_owner_change_still_works_via_adapter(game):
    db, state, _ = game
    configure_guanning_army(db)
    _set(db, loyalty=70, arrears=3, latched=0, mutiny_count=0)
    db.conn.execute(
        """UPDATE armies SET pay_source_region='liaodong',
           province_pay_share=0, central_pay_share=1,
           province_pay_arrears=0, central_pay_arrears=3, arrears=3 WHERE id=?""",
        (ARMY,),
    )
    db.conn.commit()

    changes = db.apply_army_deltas(
        state,
        SimpleNamespace(id="season", title="陷没"),
        None,
        "测试",
        {ARMY: {"owner_power": "houjin", "reason": "城破易主"}},
        commit=False,
    )

    row = db.conn.execute("SELECT * FROM armies WHERE id=?", (ARMY,)).fetchone()
    assert not any(c.get("rejected") for c in changes)
    assert row["owner_power"] == "houjin"
    assert row["is_mutinied"] == 0
    assert float(row["arrears"]) == pytest.approx(0)
    logs = _logs(db, ("arrears", "owner_power"))
    writeoff = next(
        (
            log for log in logs
            if log["field"] == "arrears"
            and float(log["old_value"]) > 0
            and float(log["new_value"]) == 0
            and float(log["delta"]) < 0
        ),
        None,
    )
    owner_log = next((log for log in logs if log["field"] == "owner_power"), None)
    assert writeoff is not None and owner_log is not None
    assert writeoff["id"] < owner_log["id"]
