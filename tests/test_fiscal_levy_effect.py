import json
import math

import pytest

from ming_sim.decree import pre_settle
from ming_sim.exceptions import SettlementAbort
from ming_sim.issues import apply_historical_fiscal_rates
import ming_sim.issues as issues


def _settle_payload(db, region_id):
    row = db.conn.execute(
        "SELECT fiscal FROM regions WHERE id = ?",
        (region_id,),
    ).fetchone()
    return json.loads(str(row["fiscal"] or "{}"))["settle"]


def test_liao_levy_rise_triggers_and_updates_shadow_settle_before_fiscal_tick(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)

    before = _settle_payload(db, "shaanxi")
    seed_liao = before["p"]["三饷应征"]
    seed_transport = before["p"]["起运定额"]
    base_transport = max(0.0, seed_transport - seed_liao)
    target_liao = seed_liao * 4.0 / 3.0

    pre_settle(state, db, content=content)

    row = db.conn.execute(
        "SELECT terminal_state, terminal_reason, source FROM event_triggers WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone()
    assert dict(row) == {
        "terminal_state": "triggered",
        "terminal_reason": "已准",
        "source": "fiscal_levy_shadow",
    }

    after = _settle_payload(db, "shaanxi")
    assert math.isclose(after["p"]["三饷应征"], target_liao, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(
        after["p"]["起运定额"],
        base_transport + target_liao,
        rel_tol=1e-9,
        abs_tol=1e-9,
    )
    assert math.isclose(
        after["st"]["C_地方截留"],
        (after["p"]["正赋应征"] + target_liao)
        * after["p"]["火耗率"]
        * (1 - after["p"]["逋赋率"]),
        rel_tol=1e-9,
        abs_tol=1e-9,
    )


def test_lian_levy_start_triggers_and_updates_shadow_settle_before_fiscal_tick(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1639
    state.period = 1
    db.save_state(state)

    before = _settle_payload(db, "shaanxi")
    seed_liao = before["p"]["三饷应征"]
    seed_transport = before["p"]["起运定额"]
    base_transport = max(0.0, seed_transport - seed_liao)
    target_liao = seed_liao * 4.0 / 3.0
    target_lian = seed_liao * 73.0 / 52.0
    target_sanxiang = target_liao + target_lian

    pre_settle(state, db, content=content)

    row = db.conn.execute(
        "SELECT terminal_state, terminal_reason, source FROM event_triggers WHERE event_id=?",
        ("lian_levy_start_1639",),
    ).fetchone()
    assert dict(row) == {
        "terminal_state": "triggered",
        "terminal_reason": "已准",
        "source": "fiscal_levy_shadow",
    }

    after = _settle_payload(db, "shaanxi")
    assert math.isclose(after["p"]["三饷应征"], target_sanxiang, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(
        after["p"]["起运定额"],
        base_transport + target_sanxiang,
        rel_tol=1e-9,
        abs_tol=1e-9,
    )
    assert math.isclose(
        after["st"]["C_地方截留"],
        (after["p"]["正赋应征"] + target_sanxiang)
        * after["p"]["火耗率"]
        * (1 - after["p"]["逋赋率"]),
        rel_tol=1e-9,
        abs_tol=1e-9,
    )


def test_fiscal_levy_existing_terminal_reason_is_whitelist_validated(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    before = _settle_payload(db, "shaanxi")
    db.conn.execute(
        """
        INSERT INTO event_triggers
            (event_id, turn, year, period, source, terminal_state, terminal_reason)
        VALUES (?, ?, ?, ?, 'test', 'triggered', ?)
        """,
        ("liao_levy_rise_1631", state.turn, state.year, state.period, "乱写"),
    )
    db.conn.commit()

    with pytest.raises(SettlementAbort, match="饷率事件 liao_levy_rise_1631 结局标签无法归一"):
        apply_historical_fiscal_rates(state, db)

    after = _settle_payload(db, "shaanxi")
    assert after["p"] == before["p"]


def test_liao_levy_targets_all_seeded_settles_without_compounding_or_clobbering_p(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)

    before_by_region = {}
    for row in db.conn.execute("SELECT id, fiscal FROM regions ORDER BY id").fetchall():
        fiscal = json.loads(str(row["fiscal"] or "{}"))
        settle = fiscal.get("settle") if isinstance(fiscal, dict) else None
        if isinstance(settle, dict) and isinstance(settle.get("p"), dict):
            before_by_region[str(row["id"])] = dict(settle["p"])
    assert len(before_by_region) >= 17

    apply_historical_fiscal_rates(state, db)
    first_by_region = {}
    for region_id, before_p in before_by_region.items():
        after = _settle_payload(db, region_id)
        first_by_region[region_id] = dict(after["p"])
        meta = after["_meta"]
        expected_liao = meta["辽饷九厘基线"] * 4.0 / 3.0
        expected_transport = meta["正赋起运基线"] + expected_liao
        assert math.isclose(after["p"]["三饷应征"], expected_liao, rel_tol=1e-9, abs_tol=1e-9)
        assert math.isclose(after["p"]["起运定额"], expected_transport, rel_tol=1e-9, abs_tol=1e-9)
        assert after["p"]["起运定额"] >= after["p"]["三饷应征"]
        assert after["p"]["起运定额"] >= 0

        preserved_keys = set(before_p) - {"三饷应征", "起运定额"}
        for key in preserved_keys:
            assert after["p"][key] == before_p[key]

    apply_historical_fiscal_rates(state, db)
    for region_id, first_p in first_by_region.items():
        assert _settle_payload(db, region_id)["p"] == first_p


def test_lian_levy_targets_all_seeded_settles_without_compounding_or_clobbering_p(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1639
    state.period = 1
    db.save_state(state)

    before_by_region = {}
    for row in db.conn.execute("SELECT id, fiscal FROM regions ORDER BY id").fetchall():
        fiscal = json.loads(str(row["fiscal"] or "{}"))
        settle = fiscal.get("settle") if isinstance(fiscal, dict) else None
        if isinstance(settle, dict) and isinstance(settle.get("p"), dict):
            before_by_region[str(row["id"])] = dict(settle["p"])
    assert len(before_by_region) >= 17

    applied = apply_historical_fiscal_rates(state, db)
    assert "lian_levy_start_1639" in [item["id"] for item in applied]
    first_by_region = {}
    for region_id, before_p in before_by_region.items():
        after = _settle_payload(db, region_id)
        first_by_region[region_id] = dict(after["p"])
        meta = after["_meta"]
        seed_liao = meta["辽饷九厘基线"]
        expected_sanxiang = seed_liao * 4.0 / 3.0 + seed_liao * 73.0 / 52.0
        expected_transport = meta["正赋起运基线"] + expected_sanxiang
        assert math.isclose(after["p"]["三饷应征"], expected_sanxiang, rel_tol=1e-9, abs_tol=1e-9)
        assert math.isclose(after["p"]["起运定额"], expected_transport, rel_tol=1e-9, abs_tol=1e-9)
        assert after["p"]["起运定额"] >= after["p"]["三饷应征"]
        assert after["p"]["起运定额"] >= 0

        preserved_keys = set(before_p) - {"三饷应征", "起运定额"}
        for key in preserved_keys:
            assert after["p"][key] == before_p[key]

    apply_historical_fiscal_rates(state, db)
    for region_id, first_p in first_by_region.items():
        assert _settle_payload(db, region_id)["p"] == first_p


def test_lian_levy_gate_waits_until_1639_and_needs_no_stop_event(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1638
    state.period = 12
    db.save_state(state)

    before = _settle_payload(db, "shaanxi")
    seed_liao = before["p"]["三饷应征"]
    apply_historical_fiscal_rates(state, db)
    assert db.conn.execute(
        "SELECT 1 FROM event_triggers WHERE event_id=?",
        ("lian_levy_start_1639",),
    ).fetchone() is None
    assert math.isclose(
        _settle_payload(db, "shaanxi")["p"]["三饷应征"],
        seed_liao * 4.0 / 3.0,
        rel_tol=1e-9,
        abs_tol=1e-9,
    )

    state.year = 1639
    state.period = 1
    db.save_state(state)
    applied = apply_historical_fiscal_rates(state, db)
    assert [item["id"] for item in applied] == ["lian_levy_start_1639"]

    terminalized = issues.apply_event_terminal_states(state, db)
    assert all(item["id"] != "lian_levy_start_1639" for item in terminalized)
    assert db.conn.execute(
        "SELECT COUNT(*) FROM event_triggers WHERE event_id=?",
        ("lian_levy_start_1639",),
    ).fetchone()[0] == 1


def test_fiscal_levy_gate_waits_until_1631_and_generic_terminal_pass_skips_it(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1630
    state.period = 12
    db.save_state(state)

    before = _settle_payload(db, "shaanxi")
    apply_historical_fiscal_rates(state, db)
    assert db.conn.execute(
        "SELECT 1 FROM event_triggers WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone() is None
    assert _settle_payload(db, "shaanxi")["p"] == before["p"]

    state.year = 1631
    state.period = 1
    db.save_state(state)
    applied = apply_historical_fiscal_rates(state, db)
    assert [item["id"] for item in applied] == ["liao_levy_rise_1631"]

    terminalized = issues.apply_event_terminal_states(state, db)
    assert all(item["id"] != "liao_levy_rise_1631" for item in terminalized)
    assert db.conn.execute(
        "SELECT COUNT(*) FROM event_triggers WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone()[0] == 1
