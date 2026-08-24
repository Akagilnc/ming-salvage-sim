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

# cutover-on 饷源写缝字段（非 owner_power；owner 仍走 #318 唯一 adapter）
PAY_SOURCE_DENY_FIELDS = (
    "pay_source_region",
    "province_pay_share",
    "central_pay_share",
    "is_tusi",
    "self_funded_pay",
)

# 各组各自合法、可实际落库（arrears=0 时）；禁止复合 is_tusi/self_funded
# 与欠饷同批——那会触发既有整项校验拒收，遮蔽 latch 写缝回归。
PAY_SOURCE_LEGAL_DELTAS = (
    pytest.param(
        {"pay_source_region": "beizhili"},
        id="region",
    ),
    pytest.param(
        {"province_pay_share": 0.25, "central_pay_share": 0.75},
        id="shares",
    ),
    pytest.param(
        {"is_tusi": 1},
        id="is_tusi",
    ),
    pytest.param(
        {"self_funded_pay": 1},
        id="self_funded_pay",
    ),
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


def test_latched_loyalty_raw_positive_noop_when_legacy_flips_effect_sign(game):
    """#319 P2：latched loyalty 以 post-modifier 实际方向为准；legacy 将 +20 翻成 -1 不得降。"""
    db, state, _ = game
    _configure(db, "legacy")
    _set(db, "legacy", loyalty=30, arrears=5, latched=1, mutiny_count=1)
    # 21 × -5% → net_pct=-105；apply_legacy_pct(+20,-105) → -1
    for i in range(21):
        db.insert_legacy(
            state,
            name=f"loyalty-drag-{i}",
            modifiers={"armies": {ARMY: {"loyalty": -5}}},
        )

    db.apply_army_deltas(
        state, _event(), None, "测试", {ARMY: {"loyalty": 20}}
    )

    assert _row(db, "loyalty")["loyalty"] == 30
    assert db.conn.execute(
        "SELECT COUNT(*) FROM army_logs WHERE army_id=? AND field='loyalty'",
        (ARMY,),
    ).fetchone()[0] == 0


def test_latched_loyalty_legacy_flip_preflight_rejects_strategic_envelope(game):
    """#319 P2 预检同口径：legacy 翻负的 latched loyalty 不得靠 material 门半落兄弟结果。"""
    db, state, content = game
    issue_engine.bind_content(content)
    state.year = 1629
    state.period = 11
    _configure(db, "legacy")
    _set(db, "legacy", loyalty=30, arrears=5, latched=1, mutiny_count=1)
    for i in range(21):
        db.insert_legacy(
            state,
            name=f"jisi-loyalty-drag-{i}",
            modifiers={"armies": {ARMY: {"loyalty": -5}}},
        )
    db.conn.execute("UPDATE regions SET military_pressure = ? WHERE id = ?", (20, "beizhili"))
    before_loyalty = _row(db, "loyalty")["loyalty"]

    out = issue_engine.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "入塞被遏"},
            "region_delta": {
                "beizhili": {
                    "origin_ref": "盘面自发",
                    "military_pressure": 35,
                    "reason": "己巳之变软判敌逼京畿",
                }
            },
            "army_delta": {
                ARMY: {
                    "origin_ref": "盘面自发",
                    "loyalty": 20,
                    "reason": "己巳之变安抚哗变军",
                }
            },
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert not db.has_event_triggered("jisi_lubian")
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()["military_pressure"] == 20
    assert _row(db, "loyalty")["loyalty"] == before_loyalty


def test_latched_loyalty_at_mutiny_cap_preflight_rejects_strategic_envelope(game):
    """#319：loyalty 已贴 mutiny_loyalty_cap 时，正 delta 预检须拒整封，防兄弟结果半落。"""
    db, state, content = game
    issue_engine.bind_content(content)
    state.year = 1629
    state.period = 11
    _configure(db, "legacy")
    # mutiny_count=1, redemption_count=0 → cap=80；loyalty 已贴 cap
    _set(db, "legacy", loyalty=80, arrears=5, latched=1, mutiny_count=1)
    db.conn.execute(
        "UPDATE armies SET redemption_count=0 WHERE id=?", (ARMY,)
    )
    db.conn.commit()
    db.conn.execute("UPDATE regions SET military_pressure = ? WHERE id = ?", (20, "beizhili"))
    before_loyalty = _row(db, "loyalty")["loyalty"]
    assert before_loyalty == 80

    out = issue_engine.apply_score_extraction(
        db,
        state,
        {
            "new_issues": [{"origin_kind": "event_pool", "id": "jisi_lubian"}],
            "事件结局": {"jisi_lubian": "入塞被遏"},
            "region_delta": {
                "beizhili": {
                    "origin_ref": "盘面自发",
                    "military_pressure": 35,
                    "reason": "己巳之变软判敌逼京畿",
                }
            },
            "army_delta": {
                ARMY: {
                    "origin_ref": "盘面自发",
                    "loyalty": 5,
                    "reason": "己巳之变安抚哗变军",
                }
            },
        },
        content=content,
    )

    assert out["issue_summary"]["new_issues"][0]["rejected"] is True
    assert not db.has_event_triggered("jisi_lubian")
    assert db.conn.execute(
        "SELECT military_pressure FROM regions WHERE id = ?", ("beizhili",)
    ).fetchone()["military_pressure"] == 20
    assert _row(db, "loyalty")["loyalty"] == before_loyalty


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


@pytest.mark.parametrize("pay_delta", PAY_SOURCE_LEGAL_DELTAS)
def test_latched_cutover_denies_pay_source_fields(game, pay_delta):
    """cutover-on：latched 军各组合法饷源输入一律静默 no-op（写缝入口复用 latch 门）。"""
    db, state, _ = game
    _configure(db, "substrate_hub")
    # arrears=0：各组输入在无 latch 门时均可真实落库，避免校验假绿
    _set(db, "substrate_hub", loyalty=30, arrears=0, latched=1, mutiny_count=1)
    before = _snapshot(db, PAY_SOURCE_DENY_FIELDS)

    db.apply_army_deltas(
        state, _event(), None, "测试", {ARMY: dict(pay_delta)}
    )

    after = _snapshot(db, PAY_SOURCE_DENY_FIELDS)
    assert after == before


def test_latched_cutover_rejects_invalid_pay_source_share(game):
    """cutover-on + latched：畸形 share 须 invalid_enum 拒收留痕，不得被 latch 静默吞没。"""
    db, state, _ = game
    _configure(db, "substrate_hub")
    _set(db, "substrate_hub", loyalty=30, arrears=0, latched=1, mutiny_count=1)
    before = _snapshot(db, PAY_SOURCE_DENY_FIELDS)
    bad = {"province_pay_share": 0.3, "central_pay_share": 0.3}

    changes = db.apply_army_deltas(
        state, _event(), None, "测试", {ARMY: dict(bad)}
    )

    rejected = [
        c for c in changes
        if c.get("rejected") and c.get("category") == "invalid_enum"
    ]
    assert rejected, f"畸形 share 应 invalid_enum 拒收：{changes}"
    assert any("饷源比例和必须为 1" in str(c.get("reason") or "") for c in rejected)
    assert _snapshot(db, PAY_SOURCE_DENY_FIELDS) == before


def test_latched_cutover_rejects_unknown_pay_source_region(game):
    """cutover-on + latched：不存在 region 须 invalid_enum 拒收留痕，快照不变。"""
    db, state, _ = game
    _configure(db, "substrate_hub")
    _set(db, "substrate_hub", loyalty=30, arrears=0, latched=1, mutiny_count=1)
    before = _snapshot(db, PAY_SOURCE_DENY_FIELDS)
    bad = {"pay_source_region": "no_such_region_319"}

    changes = db.apply_army_deltas(
        state, _event(), None, "测试", {ARMY: dict(bad)}
    )

    rejected = [
        c for c in changes
        if c.get("rejected") and c.get("category") == "invalid_enum"
    ]
    assert rejected, f"不存在 region 应 invalid_enum 拒收：{changes}"
    assert any("未入库" in str(c.get("reason") or "") for c in rejected)
    assert _snapshot(db, PAY_SOURCE_DENY_FIELDS) == before


@pytest.mark.parametrize("pay_delta", PAY_SOURCE_LEGAL_DELTAS)
def test_latched_cutover_mixed_item_pay_source_deny_whitelist_apply(game, pay_delta):
    """混合 item：合法饷源半边不变；manpower 严格负 / loyalty 正仍按白名单落。"""
    db, state, _ = game
    _configure(db, "substrate_hub")
    _set(
        db,
        "substrate_hub",
        loyalty=30,
        arrears=0,
        latched=1,
        mutiny_count=1,
        manpower=10000,
    )
    before_pay = _snapshot(db, PAY_SOURCE_DENY_FIELDS)
    before_mp = _row(db, "manpower", "loyalty")

    db.apply_army_deltas(
        state,
        _event(),
        None,
        "测试",
        {
            ARMY: {
                **pay_delta,
                "manpower": -100,
                "loyalty": 5,
            }
        },
    )

    after_pay = _snapshot(db, PAY_SOURCE_DENY_FIELDS)
    after_mp = _row(db, "manpower", "loyalty")
    assert after_pay == before_pay
    assert after_mp["manpower"] == before_mp["manpower"] - 100
    assert after_mp["loyalty"] == before_mp["loyalty"] + 5


@pytest.mark.parametrize("pay_delta", PAY_SOURCE_LEGAL_DELTAS)
def test_non_latched_cutover_pay_source_fields_still_write(game, pay_delta):
    """对照：非 latched + cutover-on 四组合法饷源均可持久落库，防误伤生产路径。"""
    db, state, _ = game
    _configure(db, "substrate_hub")
    _set(
        db,
        "substrate_hub",
        loyalty=70,
        arrears=0,
        latched=0,
        mutiny_count=0,
        manpower=10000,
    )

    db.apply_army_deltas(
        state,
        _event(),
        None,
        "测试",
        {ARMY: dict(pay_delta)},
    )

    after = _row(db, *PAY_SOURCE_DENY_FIELDS)
    for key, expected in pay_delta.items():
        if key in ("province_pay_share", "central_pay_share"):
            assert float(after[key]) == pytest.approx(float(expected))
        elif key in ("is_tusi", "self_funded_pay"):
            assert int(after[key]) == int(expected)
            assert bool(after[key]) is bool(expected)
        else:
            assert after[key] == expected
