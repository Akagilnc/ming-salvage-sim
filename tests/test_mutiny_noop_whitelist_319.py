"""#319 — latched 军字段-效果 deny-by-default 白名单（ADR 0025 D4①）。

seam = apply_army_deltas 内字段效果门（与 #318 owner adapter 同缝）；
     + economy_moves 真钱补饷跨相位 oracle；
     + apply_score_extraction 集成对照（证明无需第二门）。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from ming_sim.flows import _apply_economy_list, apply_fixed_period_flows
from ming_sim import issues as issue_engine

ARMY = "guanning"
PATHS = ("legacy", "substrate_hub")
SPONTANEOUS = "盘面自发"

DENY_SNAPSHOT_FIELDS = (
    "station",
    "commander",
    "status",
    "equipment",
    "firearm_equipment",
    "cannon_equipment",
    "training",
    "troop_type",
    "morale",
    "supply",
    "manpower",
)


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
           manpower=10000, salary_rate=1, province_pay_share=0, central_pay_share=1,
           pay_source_region='liaodong', province_pay_arrears=0, central_pay_arrears=0
           WHERE id=?""",
        (ARMY,),
    )
    db.conn.commit()


def _set(
    db,
    fiscal_path: str,
    *,
    loyalty: int,
    arrears: float,
    latched: int,
    mutiny_count: int | None = None,
    manpower: int | None = None,
) -> None:
    central = arrears if fiscal_path == "substrate_hub" else 0
    db.conn.execute(
        """UPDATE armies SET loyalty=?, arrears=?, is_mutinied=?,
           province_pay_arrears=0, central_pay_arrears=? WHERE id=?""",
        (loyalty, arrears, latched, central, ARMY),
    )
    if mutiny_count is not None:
        db.conn.execute(
            "UPDATE armies SET mutiny_count=? WHERE id=?", (mutiny_count, ARMY)
        )
    if manpower is not None:
        db.conn.execute(
            "UPDATE armies SET manpower=? WHERE id=?", (manpower, ARMY)
        )
    db.conn.commit()


def _event(title: str = "哗变字段门"):
    return SimpleNamespace(id="test-319", title=title)


def _row(db, *fields: str):
    cols = ", ".join(fields) if fields else "*"
    return db.conn.execute(
        f"SELECT {cols} FROM armies WHERE id=?", (ARMY,)
    ).fetchone()


def _snapshot(db, fields=DENY_SNAPSHOT_FIELDS):
    row = _row(db, *fields)
    return {f: row[f] for f in fields}


def test_latched_denies_dispatch_armament_status_and_positive_manpower(game):
    db, state, _ = game
    _configure(db, "legacy")
    _set(db, "legacy", loyalty=30, arrears=5, latched=1, mutiny_count=1)
    before = _snapshot(db)

    db.apply_army_deltas(
        state,
        _event(),
        None,
        "测试",
        {
            ARMY: {
                "station": "新驻地",
                "commander": "新统帅",
                "status": "已整编",
                "equipment": 5,
                "firearm_equipment": 5,
                "cannon_equipment": 1,
                "training": 5,
                "troop_type": "新兵种",
                "morale": 5,
                "supply": 5,
                "manpower": 100,
            }
        },
    )

    after = _snapshot(db)
    assert after == before


def test_latched_manpower_strict_negative_applies_zero_and_positive_noop(game):
    db, state, _ = game
    _configure(db, "legacy")
    _set(
        db, "legacy", loyalty=30, arrears=5, latched=1, mutiny_count=1, manpower=10000
    )

    db.apply_army_deltas(
        state, _event(), None, "测试", {ARMY: {"manpower": -300}}
    )
    assert _row(db, "manpower")["manpower"] == 9700

    db.apply_army_deltas(
        state, _event(), None, "测试", {ARMY: {"manpower": 0}}
    )
    assert _row(db, "manpower")["manpower"] == 9700

    db.apply_army_deltas(
        state, _event(), None, "测试", {ARMY: {"manpower": 200}}
    )
    assert _row(db, "manpower")["manpower"] == 9700


def test_latched_loyalty_positive_applies_negative_noop(game):
    db, state, _ = game
    _configure(db, "legacy")
    # mutiny_count=1 → cap=80；从 30 +15 → 45
    _set(db, "legacy", loyalty=30, arrears=5, latched=1, mutiny_count=1)

    db.apply_army_deltas(
        state, _event(), None, "测试", {ARMY: {"loyalty": 15}}
    )
    assert _row(db, "loyalty")["loyalty"] == 45

    db.apply_army_deltas(
        state, _event(), None, "测试", {ARMY: {"loyalty": -10}}
    )
    assert _row(db, "loyalty")["loyalty"] == 45


def test_latched_mixed_item_allows_and_denies_per_field(game):
    db, state, _ = game
    _configure(db, "legacy")
    _set(
        db, "legacy", loyalty=30, arrears=5, latched=1, mutiny_count=1, manpower=10000
    )
    before = _snapshot(db, ("station", "status", "manpower", "loyalty"))

    db.apply_army_deltas(
        state,
        _event(),
        None,
        "测试",
        {
            ARMY: {
                "manpower": -100,
                "station": "新驻地",
                "status": "已整编",
                "loyalty": 5,
            }
        },
    )

    after = _row(db, "station", "status", "manpower", "loyalty")
    assert after["manpower"] == before["manpower"] - 100
    assert after["loyalty"] == before["loyalty"] + 5
    assert after["station"] == before["station"]
    assert after["status"] == before["status"]


def test_latched_chinese_aliases_same_rules(game):
    db, state, _ = game
    _configure(db, "legacy")
    _set(
        db, "legacy", loyalty=30, arrears=5, latched=1, mutiny_count=1, manpower=10000
    )
    before = _snapshot(db, ("station", "status", "manpower", "loyalty"))

    db.apply_army_deltas(
        state,
        _event(),
        None,
        "测试",
        {
            ARMY: {
                "兵力": -100,
                "驻地": "新驻地",
                "状态": "已整编",
                "军心": 5,
            }
        },
    )

    after = _row(db, "station", "status", "manpower", "loyalty")
    assert after["manpower"] == before["manpower"] - 100
    assert after["loyalty"] == before["loyalty"] + 5
    assert after["station"] == before["station"]
    assert after["status"] == before["status"]


def test_non_latched_army_writes_all_legal_fields(game):
    db, state, _ = game
    _configure(db, "legacy")
    _set(
        db, "legacy", loyalty=70, arrears=0, latched=0, mutiny_count=0, manpower=10000
    )
    before = _snapshot(
        db, ("station", "status", "manpower", "loyalty", "equipment", "training")
    )

    db.apply_army_deltas(
        state,
        _event(),
        None,
        "测试",
        {
            ARMY: {
                "station": "新驻地",
                "status": "已整编",
                "manpower": 100,
                "loyalty": -5,
                "equipment": 3,
                "training": 2,
            }
        },
    )

    after = _row(
        db, "station", "status", "manpower", "loyalty", "equipment", "training"
    )
    assert after["station"] == "新驻地"
    assert after["status"] == "已整编"
    assert after["manpower"] == before["manpower"] + 100
    assert after["loyalty"] == before["loyalty"] - 5
    assert after["equipment"] == before["equipment"] + 3
    assert after["training"] == before["training"] + 2


@pytest.mark.parametrize("fiscal_path", PATHS)
def test_pay_clear_via_economy_moves_next_tick_loyalty_plus_5(game, fiscal_path):
    db, state, _ = game
    _configure(db, fiscal_path)
    _set(db, fiscal_path, loyalty=30, arrears=8, latched=1, mutiny_count=1)
    before_loyalty = _row(db, "loyalty")["loyalty"]
    assert float(_row(db, "arrears")["arrears"]) > 0

    state.metrics["国库"] = 10**9
    applied = _apply_economy_list(
        db,
        state,
        [{
            "account": "国库",
            "delta": -8,
            "category": "补饷",
            "reason": "诏拨清欠",
            "purpose": "补饷",
            "target_kind": "army",
            "target_id": ARMY,
        }],
        commit=True,
    )
    assert any(m.get("applied") for m in applied if isinstance(m, dict))

    mid = _row(db, "arrears", "loyalty", "is_mutinied")
    assert float(mid["arrears"]) == pytest.approx(0)
    assert mid["loyalty"] == before_loyalty  # 补饷当次不得即时改 loyalty
    assert mid["is_mutinied"] == 1

    state.metrics["国库"] = 10**9
    apply_fixed_period_flows(db, state)
    after = _row(db, "loyalty", "arrears")
    assert float(after["arrears"]) == pytest.approx(0)
    assert after["loyalty"] == before_loyalty + 5


def test_apply_score_extraction_respects_latched_field_gate(game):
    db, state, content = game
    _configure(db, "legacy")
    _set(
        db, "legacy", loyalty=30, arrears=5, latched=1, mutiny_count=1, manpower=10000
    )
    before = _snapshot(db, ("station", "status", "manpower", "loyalty"))

    issue_engine.apply_score_extraction(
        db,
        state,
        {
            "army_delta": {
                ARMY: {
                    "manpower": -100,
                    "station": "新驻地",
                    "status": "已整编",
                    "loyalty": 5,
                    "origin_ref": SPONTANEOUS,
                }
            }
        },
        content=content,
    )

    after = _row(db, "station", "status", "manpower", "loyalty")
    assert after["manpower"] == before["manpower"] - 100
    assert after["loyalty"] == before["loyalty"] + 5
    assert after["station"] == before["station"]
    assert after["status"] == before["status"]
