import json
import math

import pytest

from ming_sim.decree import pre_settle
from ming_sim.exceptions import SettlementAbort
from ming_sim.issues import apply_historical_fiscal_rates
import ming_sim.issues as issues
from ming_sim.simulation import build_simulator_payload


JIAO_NATIONAL_MONTHLY = 280.0 / 12.0
LIAN_NATIONAL_MONTHLY = 730.0 / 12.0


def _settle_payload(db, region_id):
    row = db.conn.execute(
        "SELECT fiscal FROM regions WHERE id = ?",
        (region_id,),
    ).fetchone()
    return json.loads(str(row["fiscal"] or "{}"))["settle"]


def _settled_region_ids(db):
    ids = []
    for row in db.conn.execute("SELECT id, fiscal FROM regions ORDER BY id").fetchall():
        fiscal = json.loads(str(row["fiscal"] or "{}"))
        settle = fiscal.get("settle") if isinstance(fiscal, dict) else None
        if isinstance(settle, dict) and isinstance(settle.get("p"), dict):
            ids.append(str(row["id"]))
    return ids


def _settle_land_sum(db):
    total = 0.0
    for region_id in _settled_region_ids(db):
        settle = _settle_payload(db, region_id)
        total += max(0.0, float(settle["st"].get("官民田") or 0.0))
    return total


def _expected_land_share_levy(settle, national_monthly, total_land):
    land = max(0.0, float(settle["st"].get("官民田") or 0.0))
    if total_land <= 0:
        return 0.0
    return national_monthly * land / total_land


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


@pytest.mark.parametrize(
    "year,expected_event_ids,expect_jiao_in_force,expect_lian_in_force",
    [
        (1631, {"liao_levy_rise_1631"}, False, False),
        (1637, {"liao_levy_rise_1631", "jiao_levy_start_1637"}, True, False),
        (1639, {"liao_levy_rise_1631", "jiao_levy_start_1637", "lian_levy_start_1639"}, True, True),
        (
            1640,
            {
                "liao_levy_rise_1631",
                "jiao_levy_start_1637",
                "lian_levy_start_1639",
                "jiao_levy_stop_1640",
            },
            False,
            True,
        ),
    ],
)
def test_fiscal_levy_shadow_capstone_golden_all_seeded_provinces(
    game, year, expected_event_ids, expect_jiao_in_force, expect_lian_in_force
):
    db, state, content = game
    issues.bind_content(content)
    state.year = year
    state.period = 1
    db.save_state(state)
    region_ids = _settled_region_ids(db)
    assert len(region_ids) == 17

    pre_settle(state, db, content=content)

    triggered_ids = {
        str(row["event_id"])
        for row in db.conn.execute(
            "SELECT event_id FROM event_triggers WHERE turn=? AND terminal_state='triggered'",
            (state.turn,),
        ).fetchall()
    }
    assert expected_event_ids <= triggered_ids
    if year == 1640:
        assert db.conn.execute(
            "SELECT terminal_reason FROM event_triggers WHERE event_id=?",
            ("jiao_levy_stop_1640",),
        ).fetchone()["terminal_reason"] == "已停"

    for region_id in region_ids:
        settle = _settle_payload(db, region_id)
        meta = settle["_meta"]
        seed_liao = meta["辽饷九厘基线"]
        expected_sanxiang = seed_liao * 4.0 / 3.0
        if expect_jiao_in_force:
            expected_sanxiang += meta["剿饷基线"]
        if expect_lian_in_force:
            expected_sanxiang += meta["练饷基线"]
        assert math.isclose(
            settle["p"]["三饷应征"],
            expected_sanxiang,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ), region_id
        assert math.isclose(
            settle["p"]["起运定额"],
            meta["正赋起运基线"] + expected_sanxiang,
            rel_tol=1e-9,
            abs_tol=1e-9,
        ), region_id
        assert settle["p"]["起运定额"] >= settle["p"]["三饷应征"]
        assert settle["p"]["起运定额"] >= 0


def test_liao_levy_memorial_estimate_payload_is_diegetic_national_scope(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)

    pre_settle(state, db, content=content)

    payload = build_simulator_payload(state, db, "准户部议，加辽饷以济边军。", "")
    estimates = payload["fiscal_levy_memorial_estimates"]
    assert len(estimates) == 1
    estimate = estimates[0]

    assert estimate["event_id"] == "liao_levy_rise_1631"
    assert estimate["scope"] == "国总口径"
    assert estimate["national_added_wanliang"]["unit"] == "万两/月"
    assert (
        estimate["national_added_wanliang"]["lower"]
        <= estimate["national_added_wanliang"]["midpoint"]
        <= estimate["national_added_wanliang"]["upper"]
    )
    assert "万两" in estimate["national_added_wanliang"]["text"]
    assert "可补军费" in estimate["army_gap_coverage_text"]

    rendered = json.dumps(estimates, ensure_ascii=False)
    for forbidden in ("4/3", "7/13", "73/52", "rate", "参数", "loyalty", "ability"):
        assert forbidden not in rendered


def test_fiscal_levy_memorial_estimate_skips_rejected_positive_levy(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    db.mark_event_triggered(
        state,
        "liao_levy_rise_1631",
        source="test",
        terminal_reason="已驳",
    )

    payload = build_simulator_payload(state, db, "驳回加辽饷之议。", "")

    assert payload["fiscal_levy_memorial_estimates"] == []


def test_liao_levy_memorial_estimate_uses_collectible_ming_controlled_revenue(game):
    db, state, content = game
    issues.bind_content(content)
    lost_region_id = "henan"
    db.conn.execute(
        "UPDATE regions SET controlled_by = ? WHERE id = ?",
        ("houjin", lost_region_id),
    )
    db.conn.commit()
    state.year = 1631
    state.period = 1
    db.save_state(state)

    pre_settle(state, db, content=content)

    expected_collectible = 0.0
    expected_nominal = 0.0
    for row in db.conn.execute("SELECT id, controlled_by, fiscal FROM regions ORDER BY id").fetchall():
        fiscal = json.loads(str(row["fiscal"] or "{}"))
        settle = fiscal.get("settle") if isinstance(fiscal, dict) else None
        meta = settle.get("_meta") if isinstance(settle, dict) else None
        if not isinstance(meta, dict) or "辽饷九厘基线" not in meta:
            continue
        liao_rise = float(meta["辽饷九厘基线"]) * (4.0 / 3.0 - 1.0)
        expected_nominal += liao_rise
        if str(row["controlled_by"]) == "ming":
            expected_collectible += liao_rise
    assert expected_collectible < expected_nominal

    payload = build_simulator_payload(state, db, "准户部议，加辽饷以济边军。", "")
    estimate = payload["fiscal_levy_memorial_estimates"][0]
    assert estimate["national_added_wanliang"]["midpoint"] == round(expected_collectible, 1)
    assert estimate["national_added_wanliang"]["midpoint"] != round(expected_nominal, 1)


def test_fiscal_levy_memorial_labels_cumulative_army_arrears_as_wanliang_not_monthly(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)

    pre_settle(state, db, content=content)
    db.conn.execute("UPDATE armies SET arrears = 100 WHERE owner_power = 'ming'")
    db.conn.commit()

    payload = build_simulator_payload(state, db, "准户部议，加辽饷以济边军。", "")
    estimate = payload["fiscal_levy_memorial_estimates"][0]
    assert estimate["army_gap_basis"] == "全军累计欠饷"
    assert estimate["national_army_gap_wanliang"]["unit"] == "万两"
    assert estimate["national_army_gap_wanliang"]["text"].endswith("万两")
    assert not estimate["national_army_gap_wanliang"]["text"].endswith("万两/月")


def test_fiscal_levy_memorial_prompt_contract_is_positive_p4():
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "content/prompts/season_simulator.md").read_text(
        encoding="utf-8"
    )
    assert "fiscal_levy_memorial_estimates" in text
    assert "以奏疏口吻" in text
    assert "国总万两量级加征估算" in text
    assert "可补军费" in text


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
    total_land = _settle_land_sum(db)
    target_liao = seed_liao * 4.0 / 3.0
    target_jiao = _expected_land_share_levy(before, JIAO_NATIONAL_MONTHLY, total_land)
    target_lian = _expected_land_share_levy(before, LIAN_NATIONAL_MONTHLY, total_land)
    target_sanxiang = target_liao + target_jiao + target_lian

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


def test_fiscal_levy_choice_row_rejection_controls_same_tick_effect(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    before = _settle_payload(db, "shaanxi")
    db.record_event_decision_choice(
        state,
        "liao_levy_rise_1631",
        {"label": "已驳"},
    )

    apply_historical_fiscal_rates(state, db)

    row = db.conn.execute(
        "SELECT terminal_state, terminal_reason FROM event_triggers WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone()
    assert dict(row) == {"terminal_state": "triggered", "terminal_reason": "已驳"}
    after = _settle_payload(db, "shaanxi")
    assert after["p"] == before["p"]


def test_fiscal_levy_choice_resubmission_uses_latest_pending_label(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    before = _settle_payload(db, "shaanxi")
    db.record_event_decision_choice(
        state,
        "liao_levy_rise_1631",
        {"label": "已准"},
    )
    db.record_event_decision_choice(
        state,
        "liao_levy_rise_1631",
        {"label": "已驳"},
    )

    apply_historical_fiscal_rates(state, db)

    row = db.conn.execute(
        "SELECT terminal_state, terminal_reason FROM event_triggers WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone()
    assert dict(row) == {"terminal_state": "triggered", "terminal_reason": "已驳"}
    after = _settle_payload(db, "shaanxi")
    assert after["p"] == before["p"]


def test_fiscal_levy_pending_choice_label_is_canonicalized_for_db_consumers(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    db.record_event_decision_choice(
        state,
        "liao_levy_rise_1631",
        {"label": "已 准"},
    )

    apply_historical_fiscal_rates(state, db)

    row = db.conn.execute(
        "SELECT terminal_state, terminal_reason FROM event_triggers WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone()
    assert dict(row) == {"terminal_state": "triggered", "terminal_reason": "已准"}
    payload = build_simulator_payload(state, db, "准户部议，加辽饷以济边军。", "")
    estimate_ids = {item["event_id"] for item in payload["fiscal_levy_memorial_estimates"]}
    assert "liao_levy_rise_1631" in estimate_ids


def test_fiscal_levy_pending_stop_choice_keeps_jiao_in_force_same_tick(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1640
    state.period = 1
    db.save_state(state)
    db.mark_event_triggered(state, "jiao_levy_start_1637", source="test", terminal_reason="已准")
    db.record_event_decision_choice(
        state,
        "jiao_levy_stop_1640",
        {"label": "仍征"},
    )

    apply_historical_fiscal_rates(state, db)

    row = db.conn.execute(
        "SELECT terminal_state, terminal_reason FROM event_triggers WHERE event_id=?",
        ("jiao_levy_stop_1640",),
    ).fetchone()
    assert dict(row) == {"terminal_state": "triggered", "terminal_reason": "仍征"}
    settle = _settle_payload(db, "shaanxi")
    expected_liao = settle["_meta"]["辽饷九厘基线"] * 4.0 / 3.0
    expected_jiao = settle["_meta"]["剿饷基线"]
    expected_lian = settle["_meta"]["练饷基线"]
    assert math.isclose(
        settle["p"]["三饷应征"],
        expected_liao + expected_jiao + expected_lian,
        rel_tol=1e-9,
        abs_tol=1e-9,
    )


def test_fiscal_levy_memorial_small_fractional_arrears_range_is_ordered(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)

    pre_settle(state, db, content=content)
    db.conn.execute("UPDATE armies SET arrears = 0 WHERE owner_power = 'ming'")
    db.conn.execute(
        "UPDATE armies SET arrears = 0.6 WHERE id = (SELECT id FROM armies WHERE owner_power = 'ming' LIMIT 1)"
    )
    db.conn.commit()

    payload = build_simulator_payload(state, db, "准户部议，加辽饷以济边军。", "")
    estimate = payload["fiscal_levy_memorial_estimates"][0]
    gap_range = estimate["national_army_gap_wanliang"]
    assert gap_range["lower"] <= gap_range["midpoint"] <= gap_range["upper"]


def test_fiscal_levy_memorial_suppresses_jiao_start_when_stopped_same_tick(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1640
    state.period = 1
    db.save_state(state)

    pre_settle(state, db, content=content)

    payload = build_simulator_payload(state, db, "准停剿饷。", "")
    estimate_ids = {item["event_id"] for item in payload["fiscal_levy_memorial_estimates"]}
    assert "jiao_levy_start_1637" not in estimate_ids
    assert "jiao_levy_stop_1640" not in estimate_ids
    assert {"liao_levy_rise_1631", "lian_levy_start_1639"} <= estimate_ids


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


def test_jiao_levy_rises_then_stops_and_keeps_base_transport(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1637
    state.period = 1
    db.save_state(state)

    before = _settle_payload(db, "shaanxi")
    seed_liao = before["p"]["三饷应征"]
    seed_transport = before["p"]["起运定额"]
    base_transport = max(0.0, seed_transport - seed_liao)

    apply_historical_fiscal_rates(state, db)

    after_rise = _settle_payload(db, "shaanxi")
    meta = after_rise["_meta"]
    expected_liao = meta["辽饷九厘基线"] * 4.0 / 3.0
    expected_jiao = meta["剿饷基线"]
    assert db.conn.execute(
        "SELECT terminal_reason FROM event_triggers WHERE event_id=?",
        ("jiao_levy_start_1637",),
    ).fetchone()["terminal_reason"] == "已准"
    assert math.isclose(after_rise["p"]["三饷应征"], expected_liao + expected_jiao, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(after_rise["p"]["起运定额"], base_transport + expected_liao + expected_jiao, rel_tol=1e-9, abs_tol=1e-9)

    state.year = 1640
    state.period = 1
    db.save_state(state)
    apply_historical_fiscal_rates(state, db)

    after_stop = _settle_payload(db, "shaanxi")
    expected_lian = after_stop["_meta"]["练饷基线"]
    assert db.conn.execute(
        "SELECT terminal_reason FROM event_triggers WHERE event_id=?",
        ("jiao_levy_stop_1640",),
    ).fetchone()["terminal_reason"] == "已停"
    assert math.isclose(after_stop["p"]["三饷应征"], expected_liao + expected_lian, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(after_stop["p"]["起运定额"], base_transport + expected_liao + expected_lian, rel_tol=1e-9, abs_tol=1e-9)
    assert after_stop["p"]["起运定额"] >= after_stop["p"]["三饷应征"]
    assert after_stop["p"]["起运定额"] > 0


def test_jiao_levy_stop_rejected_keeps_levy_in_force(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1640
    state.period = 1
    db.save_state(state)
    db.mark_event_triggered(state, "jiao_levy_start_1637", source="test", terminal_reason="已准", commit=False)
    db.mark_event_triggered(state, "jiao_levy_stop_1640", source="test", terminal_reason="仍征", commit=False)
    db.conn.commit()

    apply_historical_fiscal_rates(state, db)

    settle = _settle_payload(db, "shaanxi")
    expected_liao = settle["_meta"]["辽饷九厘基线"] * 4.0 / 3.0
    expected_jiao = settle["_meta"]["剿饷基线"]
    expected_lian = settle["_meta"]["练饷基线"]
    assert math.isclose(settle["p"]["三饷应征"], expected_liao + expected_jiao + expected_lian, rel_tol=1e-9, abs_tol=1e-9)


def test_jiao_stop_is_obsolete_when_start_was_rejected(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1640
    state.period = 1
    db.save_state(state)
    db.mark_event_triggered(state, "jiao_levy_start_1637", source="test", terminal_reason="已驳")

    terminalized = issues.apply_event_terminal_states(state, db)

    assert any(item["id"] == "jiao_levy_stop_1640" and item["terminal_state"] == "obsolete" for item in terminalized)
    row = db.conn.execute(
        "SELECT terminal_state FROM event_triggers WHERE event_id=?",
        ("jiao_levy_stop_1640",),
    ).fetchone()
    assert row["terminal_state"] == "obsolete"


def test_jiao_stop_definition_missing_fails_loud(game, monkeypatch):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1637
    state.period = 1
    db.save_state(state)
    event_by_id = dict(content.event_by_id)
    event_by_id.pop("jiao_levy_stop_1640", None)
    monkeypatch.setattr(content, "event_by_id", event_by_id)

    with pytest.raises(SettlementAbort, match="缺停征链 jiao_levy_stop_1640"):
        apply_historical_fiscal_rates(state, db)


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
        expected_sanxiang = seed_liao * 4.0 / 3.0 + meta["剿饷基线"] + meta["练饷基线"]
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


def test_fiscal_levy_components_are_land_share_calibrated_and_marked_provisional(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1639
    state.period = 1
    db.save_state(state)
    total_land = _settle_land_sum(db)

    apply_historical_fiscal_rates(state, db)

    required_provisional = {"辽饷九厘基线", "剿饷基线", "练饷基线", "正赋起运基线"}
    for region_id in _settled_region_ids(db):
        settle = _settle_payload(db, region_id)
        meta = settle["_meta"]
        assert math.isclose(
            meta["剿饷基线"],
            _expected_land_share_levy(settle, JIAO_NATIONAL_MONTHLY, total_land),
            rel_tol=1e-9,
            abs_tol=1e-9,
        ), region_id
        assert math.isclose(
            meta["练饷基线"],
            _expected_land_share_levy(settle, LIAN_NATIONAL_MONTHLY, total_land),
            rel_tol=1e-9,
            abs_tol=1e-9,
        ), region_id
        assert required_provisional <= set(meta.get("provisional", [])), region_id


def test_lost_seeded_province_keeps_current_levy_rate_and_uses_it_on_restore(game):
    db, state, content = game
    issues.bind_content(content)
    region_id = "henan"
    db.conn.execute(
        "UPDATE regions SET controlled_by = ? WHERE id = ?",
        ("houjin", region_id),
    )
    db.conn.commit()
    state.year = 1639
    state.period = 1
    db.save_state(state)

    lost_before = _settle_payload(db, region_id)
    lost_opening_st = dict(lost_before["st"])
    stale_sanxiang = lost_before["p"]["三饷应征"]

    apply_historical_fiscal_rates(state, db)

    lost_after_rate = _settle_payload(db, region_id)
    meta = lost_after_rate["_meta"]
    expected_sanxiang = (
        meta["辽饷九厘基线"] * 4.0 / 3.0
        + meta["剿饷基线"]
        + meta["练饷基线"]
    )
    assert lost_after_rate["p"]["三饷应征"] != stale_sanxiang
    assert math.isclose(
        lost_after_rate["p"]["三饷应征"],
        expected_sanxiang,
        rel_tol=1e-9,
        abs_tol=1e-9,
    )
    assert math.isclose(
        lost_after_rate["p"]["起运定额"],
        meta["正赋起运基线"] + expected_sanxiang,
        rel_tol=1e-9,
        abs_tol=1e-9,
    )

    lost_tick_outcomes = db.settle_ming_province_substrate_ticks()
    assert region_id not in {item.region_id for item in lost_tick_outcomes}
    assert _settle_payload(db, region_id)["st"] == lost_opening_st

    db.conn.execute(
        "UPDATE regions SET controlled_by = ? WHERE id = ?",
        ("ming", region_id),
    )
    db.conn.commit()
    restored_tick_outcomes = db.settle_ming_province_substrate_ticks()
    restored = next(item for item in restored_tick_outcomes if item.region_id == region_id)
    assert restored.error is None
    assert restored.result is not None
    assert math.isclose(
        restored.result.breakdown["三饷火耗"],
        expected_sanxiang * lost_after_rate["p"]["火耗率"],
        rel_tol=1e-9,
        abs_tol=1e-9,
    )


def test_lian_levy_gate_waits_until_1639_and_needs_no_stop_event(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1638
    state.period = 12
    db.save_state(state)

    apply_historical_fiscal_rates(state, db)
    assert db.conn.execute(
        "SELECT 1 FROM event_triggers WHERE event_id=?",
        ("lian_levy_start_1639",),
    ).fetchone() is None
    after = _settle_payload(db, "shaanxi")
    expected_sanxiang = after["_meta"]["辽饷九厘基线"] * 4.0 / 3.0 + after["_meta"]["剿饷基线"]
    assert math.isclose(
        after["p"]["三饷应征"],
        expected_sanxiang,
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
