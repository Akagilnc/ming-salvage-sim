import json
import math

import pytest

from ming_sim.decree import pre_settle
from ming_sim.exceptions import SettlementAbort
from ming_sim.flows import army_needed
from ming_sim.issues import apply_historical_fiscal_rates
import ming_sim.issues as issues
from ming_sim.models import Event
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


def _settled_land_by_region(db):
    land_by_region = {}
    for region_id in _settled_region_ids(db):
        settle = _settle_payload(db, region_id)
        land_by_region[region_id] = max(0.0, float(settle["st"].get("官民田") or 0.0))
    return land_by_region


def _expected_land_share_levy(settle, national_monthly, total_land):
    land = max(0.0, float(settle["st"].get("官民田") or 0.0))
    if total_land <= 0:
        return 0.0
    return national_monthly * land / total_land


def test_shaanxi_primary_source_liao_seed_keeps_opening_transport_cap(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1627
    state.period = 10
    db.save_state(state)

    apply_historical_fiscal_rates(state, db)

    settle = _settle_payload(db, "shaanxi")
    meta = settle["_meta"]
    expected_liao = 2929.20151 * 0.009 / 12.0

    assert math.isclose(settle["p"]["三饷应征"], expected_liao, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(meta["辽饷九厘基线"], expected_liao, rel_tol=1e-9, abs_tol=1e-9)
    assert meta["正赋起运基线"] == 0
    assert math.isclose(
        settle["p"]["起运定额"],
        meta["正赋起运基线"] + expected_liao,
        rel_tol=1e-9,
        abs_tol=1e-9,
    )


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


def test_liao_levy_rise_triggers_on_no_edict_advance_before_fiscal_tick(game, monkeypatch):
    """#1274：无旨完整结算 pre_settle 内历史饷率事件仍在 fiscal tick 前触发。"""
    import ming_sim.decree as decree_mod
    import ming_sim.memories as memories
    from ming_sim.session import GameSession

    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    before = _settle_payload(db, "shaanxi")
    seed_liao = before["p"]["三饷应征"]
    target_liao = seed_liao * 4.0 / 3.0

    monkeypatch.setattr(decree_mod, "create_season_simulator_agent", lambda *a, **k: None)
    monkeypatch.setattr(
        decree_mod, "simulate_season_with_payload",
        lambda *a, **k: ("饷率测邸报。", k.get("simulator_payload") or {}),
    )
    monkeypatch.setattr(decree_mod, "create_json_sanitizer_agent", lambda *a, **k: None)
    monkeypatch.setattr(decree_mod, "create_score_extractor_module_agent", lambda *a, **k: object())
    monkeypatch.setattr(decree_mod, "extract_scores_by_modules_with_agno", lambda *a, **k: ({}, "o", "i"))
    monkeypatch.setattr(decree_mod, "create_chapter_memory_agent", lambda *a, **k: None)
    monkeypatch.setattr(memories, "run_agent_text", lambda *a, **k: '{"body":"月记","tags":[]}')

    sess = GameSession.__new__(GameSession)
    sess.db, sess.state, sess.content = db, state, content
    sess.registry = sess.llm_config = sess.agno_db = None
    sess.deaths_this_turn, sess.debuts_this_turn = [], []
    sess.last_decree = sess.last_report = ""
    sess._decree_draft_fingerprint = ()
    sess._scene_registry = sess._beat_generator = None
    sess.auto_save = lambda *a, **k: None
    sess.advance_without_decree()

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


def test_fiscal_levy_shadow_skips_malformed_region_fiscal_without_blocking_fiscal_levy_pass(game, monkeypatch):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    before_huguang = _settle_payload(db, "huguang")["p"]["三饷应征"]
    msgs = []
    monkeypatch.setattr(issues, "tlog", lambda msg: msgs.append(msg))
    db.conn.execute("UPDATE regions SET fiscal = ? WHERE id = ?", ("{bad", "shaanxi"))
    db.conn.commit()

    apply_historical_fiscal_rates(state, db)

    assert any("[fiscal-levy] shaanxi fiscal 解析失败" in msg for msg in msgs)
    huguang = _settle_payload(db, "huguang")
    assert huguang["p"]["三饷应征"] > before_huguang


@pytest.mark.parametrize(
    "bad_field,expected_log",
    [
        ("_meta", "shaanxi.settle._meta 非字典"),
        ("land", "shaanxi.settle.st.官民田 非数值"),
    ],
)
def test_fiscal_levy_shadow_skips_bad_settle_shape_without_blocking_other_regions(
    game, monkeypatch, bad_field, expected_log
):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    before_huguang = _settle_payload(db, "huguang")["p"]["三饷应征"]
    fiscal = json.loads(
        str(db.conn.execute("SELECT fiscal FROM regions WHERE id = ?", ("shaanxi",)).fetchone()["fiscal"])
    )
    if bad_field == "_meta":
        fiscal["settle"]["_meta"] = ["bad"]
    else:
        fiscal["settle"]["st"]["官民田"] = []
    msgs = []
    monkeypatch.setattr(issues, "tlog", lambda msg: msgs.append(msg))
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id = ?",
        (json.dumps(fiscal, ensure_ascii=False), "shaanxi"),
    )
    db.conn.commit()

    apply_historical_fiscal_rates(state, db)

    assert any("[fiscal-levy] shaanxi settle 解析失败" in msg and expected_log in msg for msg in msgs)
    huguang = _settle_payload(db, "huguang")
    assert huguang["p"]["三饷应征"] > before_huguang


def test_fiscal_levy_rewrites_nonnumeric_current_targets_from_meta(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    fiscal = json.loads(
        str(db.conn.execute("SELECT fiscal FROM regions WHERE id = ?", ("shaanxi",)).fetchone()["fiscal"])
    )
    fiscal["settle"]["p"]["三饷应征"] = "待重算"
    fiscal["settle"]["p"]["起运定额"] = "待重算"
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id = ?",
        (json.dumps(fiscal, ensure_ascii=False), "shaanxi"),
    )
    db.conn.commit()

    apply_historical_fiscal_rates(state, db)

    settle = _settle_payload(db, "shaanxi")
    expected_sanxiang = settle["_meta"]["辽饷九厘基线"] * 4.0 / 3.0
    assert math.isclose(settle["p"]["三饷应征"], expected_sanxiang, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(
        settle["p"]["起运定额"],
        settle["_meta"]["正赋起运基线"] + expected_sanxiang,
        rel_tol=1e-9,
        abs_tol=1e-9,
    )


def test_fiscal_levy_bad_region_does_not_redistribute_jiao_lian_targets(game, monkeypatch):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1637
    state.period = 1
    db.save_state(state)

    total_land = _settle_land_sum(db)
    huguang_before = _settle_payload(db, "huguang")
    expected_jiao = _expected_land_share_levy(huguang_before, JIAO_NATIONAL_MONTHLY, total_land)
    expected_lian = _expected_land_share_levy(huguang_before, LIAN_NATIONAL_MONTHLY, total_land)
    expected_liao = huguang_before["p"]["三饷应征"] * 4.0 / 3.0

    apply_historical_fiscal_rates(state, db)
    state.year = 1639
    state.period = 1
    db.save_state(state)

    fiscal = json.loads(
        str(db.conn.execute("SELECT fiscal FROM regions WHERE id = ?", ("shaanxi",)).fetchone()["fiscal"])
    )
    fiscal["settle"]["st"]["官民田"] = []
    msgs = []
    monkeypatch.setattr(issues, "tlog", lambda msg: msgs.append(msg))
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id = ?",
        (json.dumps(fiscal, ensure_ascii=False), "shaanxi"),
    )
    db.conn.commit()

    apply_historical_fiscal_rates(state, db)

    assert any("[fiscal-levy] shaanxi settle 解析失败" in msg for msg in msgs)
    huguang = _settle_payload(db, "huguang")
    assert math.isclose(huguang["_meta"]["剿饷基线"], expected_jiao, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(huguang["_meta"]["练饷基线"], expected_lian, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(
        huguang["p"]["三饷应征"],
        expected_liao + expected_jiao + expected_lian,
        rel_tol=1e-9,
        abs_tol=1e-9,
    )


def test_fiscal_levy_memorial_uses_stable_denominator_when_lost_region_breaks_later(
    game, monkeypatch
):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1637
    state.period = 1
    db.save_state(state)

    land_by_region = _settled_land_by_region(db)
    db.conn.execute(
        "UPDATE regions SET controlled_by = ? WHERE id = ?",
        ("houjin", "henan"),
    )
    db.conn.commit()
    expected_ming_land = sum(
        land
        for region_id, land in land_by_region.items()
        if region_id != "henan"
    )
    expected_added = JIAO_NATIONAL_MONTHLY * expected_ming_land / sum(land_by_region.values())

    pre_settle(state, db, content=content)
    fiscal = json.loads(
        str(db.conn.execute("SELECT fiscal FROM regions WHERE id = ?", ("henan",)).fetchone()["fiscal"])
    )
    fiscal["settle"]["st"]["官民田"] = []
    msgs = []
    monkeypatch.setattr(issues, "tlog", lambda msg: msgs.append(msg))
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id = ?",
        (json.dumps(fiscal, ensure_ascii=False), "henan"),
    )
    db.conn.commit()

    payload = build_simulator_payload(state, db, "准户部议，开剿饷。", "")

    assert any("[fiscal-levy] henan settle 解析失败" in msg for msg in msgs)
    estimate = next(
        item
        for item in payload["fiscal_levy_memorial_estimates"]
        if item["event_id"] == "jiao_levy_start_1637"
    )
    assert estimate["national_added_wanliang"]["midpoint"] == round(expected_added, 1)


@pytest.mark.parametrize("bad_shape", ["land", "p", "st", "settle"])
def test_fiscal_levy_incomplete_first_pass_does_not_freeze_zero_share_seed(
    game, monkeypatch, bad_shape
):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1637
    state.period = 1
    db.save_state(state)

    total_land = _settle_land_sum(db)
    huguang_before = _settle_payload(db, "huguang")
    expected_jiao = _expected_land_share_levy(huguang_before, JIAO_NATIONAL_MONTHLY, total_land)
    expected_liao = huguang_before["p"]["三饷应征"] * 4.0 / 3.0
    original_shaanxi_fiscal = str(
        db.conn.execute("SELECT fiscal FROM regions WHERE id = ?", ("shaanxi",)).fetchone()["fiscal"]
    )
    fiscal = json.loads(original_shaanxi_fiscal)
    if bad_shape == "land":
        fiscal["settle"]["st"]["官民田"] = []
    elif bad_shape == "p":
        fiscal["settle"]["p"] = []
    elif bad_shape == "st":
        fiscal["settle"]["st"] = []
    else:
        fiscal["settle"] = []
    monkeypatch.setattr(issues, "tlog", lambda msg: None)
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id = ?",
        (json.dumps(fiscal, ensure_ascii=False), "shaanxi"),
    )
    db.conn.commit()

    apply_historical_fiscal_rates(state, db)

    incomplete = _settle_payload(db, "huguang")
    assert "剿饷基线" not in incomplete["_meta"]
    assert math.isclose(incomplete["p"]["三饷应征"], expected_liao, rel_tol=1e-9, abs_tol=1e-9)

    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id = ?",
        (original_shaanxi_fiscal, "shaanxi"),
    )
    db.conn.commit()
    apply_historical_fiscal_rates(state, db)

    restored = _settle_payload(db, "huguang")
    assert math.isclose(restored["_meta"]["剿饷基线"], expected_jiao, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(restored["p"]["三饷应征"], expected_liao + expected_jiao, rel_tol=1e-9, abs_tol=1e-9)


def test_fiscal_levy_memorial_suppresses_share_estimate_without_complete_denominator(
    game, monkeypatch
):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1637
    state.period = 1
    db.save_state(state)
    db.conn.execute(
        "UPDATE regions SET controlled_by = ? WHERE id = ?",
        ("houjin", "henan"),
    )
    db.conn.commit()
    db.mark_event_triggered(
        state,
        "jiao_levy_start_1637",
        source="test",
        terminal_reason="已准",
    )
    fiscal = json.loads(
        str(db.conn.execute("SELECT fiscal FROM regions WHERE id = ?", ("henan",)).fetchone()["fiscal"])
    )
    fiscal["settle"]["st"] = []
    msgs = []
    monkeypatch.setattr(issues, "tlog", lambda msg: msgs.append(msg))
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id = ?",
        (json.dumps(fiscal, ensure_ascii=False), "henan"),
    )
    db.conn.commit()

    payload = build_simulator_payload(state, db, "准户部议，开剿饷。", "")

    assert any("[fiscal-levy] henan settle 解析失败" in msg for msg in msgs)
    estimate_ids = {item["event_id"] for item in payload["fiscal_levy_memorial_estimates"]}
    assert "jiao_levy_start_1637" not in estimate_ids


@pytest.mark.parametrize("bad_meta_key", ["剿饷基线", "练饷基线", "饷率田亩分母基线"])
def test_fiscal_levy_bad_share_meta_does_not_crash_or_redistribute_first_pass(
    game, monkeypatch, bad_meta_key
):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1637
    state.period = 1
    db.save_state(state)
    huguang_before = _settle_payload(db, "huguang")
    expected_liao = huguang_before["p"]["三饷应征"] * 4.0 / 3.0
    original_shaanxi_fiscal = str(
        db.conn.execute("SELECT fiscal FROM regions WHERE id = ?", ("shaanxi",)).fetchone()["fiscal"]
    )
    fiscal = json.loads(original_shaanxi_fiscal)
    fiscal["settle"].setdefault("_meta", {})[bad_meta_key] = []
    msgs = []
    monkeypatch.setattr(issues, "tlog", lambda msg: msgs.append(msg))
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id = ?",
        (json.dumps(fiscal, ensure_ascii=False), "shaanxi"),
    )
    db.conn.commit()

    apply_historical_fiscal_rates(state, db)

    assert any("[fiscal-levy] shaanxi settle 解析失败" in msg and bad_meta_key in msg for msg in msgs)
    incomplete = _settle_payload(db, "huguang")
    assert "剿饷基线" not in incomplete["_meta"]
    assert math.isclose(incomplete["p"]["三饷应征"], expected_liao, rel_tol=1e-9, abs_tol=1e-9)

    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id = ?",
        (original_shaanxi_fiscal, "shaanxi"),
    )
    db.conn.commit()
    apply_historical_fiscal_rates(state, db)

    restored = _settle_payload(db, "huguang")
    assert "剿饷基线" in restored["_meta"]
    assert restored["p"]["三饷应征"] > expected_liao


def test_fiscal_levy_memorial_estimates_skip_malformed_region_fiscal(game, monkeypatch):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    msgs = []
    monkeypatch.setattr(issues, "tlog", lambda msg: msgs.append(msg))

    pre_settle(state, db, content=content)
    db.conn.execute("UPDATE regions SET fiscal = ? WHERE id = ?", ("[]", "shaanxi"))
    db.conn.commit()
    payload = build_simulator_payload(state, db, "准户部议，加辽饷以济边军。", "")

    assert any("[fiscal-levy] shaanxi fiscal 非字典" in msg for msg in msgs)
    estimate_ids = {item["event_id"] for item in payload["fiscal_levy_memorial_estimates"]}
    assert "liao_levy_rise_1631" in estimate_ids


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


def test_fiscal_levy_memorial_excludes_self_funded_tusi_from_army_gap(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    db.mark_event_triggered(
        state,
        "liao_levy_rise_1631",
        source="test",
        terminal_reason="已准",
    )
    db.conn.execute("UPDATE armies SET arrears = 0 WHERE owner_power = 'ming'")
    db.conn.execute(
        """
        UPDATE armies
        SET arrears = 100, is_tusi = 1, self_funded_pay = 1
        WHERE id = 'southwest_tusi'
        """
    )
    db.conn.commit()

    expected_monthly_due = sum(
        float(army_needed(row))
        for row in db.conn.execute(
            """
            SELECT *
            FROM armies
            WHERE owner_power = 'ming' AND is_tusi = 0 AND self_funded_pay = 0
            """
        ).fetchall()
    )

    payload = build_simulator_payload(state, db, "准户部议，加辽饷以济边军。", "")

    estimate = payload["fiscal_levy_memorial_estimates"][0]
    assert estimate["army_gap_basis"] == "本月应发军饷"
    assert estimate["national_army_gap_wanliang"]["unit"] == "万两/月"
    assert estimate["national_army_gap_wanliang"]["midpoint"] == round(expected_monthly_due, 1)


def test_fiscal_levy_expired_pending_choice_is_terminalized(game):
    db, state, content = game
    issues.bind_content(content)
    event_id = "__test_expired_pending_fiscal_levy__"
    ev = Event(
        id=event_id,
        title="测试过期饷率事件",
        kind="财政",
        category="fiscal_levy",
        summary="x",
        urgency=50,
        severity=50,
        credibility=50,
        interests=[],
        audiences=[],
        trigger_year=1637,
        trigger_month=1,
        trigger_end_year=1637,
        trigger_end_month=1,
        terminal_reason_labels=["已准", "已驳"],
        default_terminal_reason="已准",
    )
    content.events.append(ev)
    try:
        state.year = 1637
        state.period = 2
        db.save_state(state)
        db.record_event_decision_choice(
            state,
            event_id,
            {"label": "已准"},
        )

        applied = apply_historical_fiscal_rates(state, db)

        row = db.conn.execute(
            "SELECT terminal_state, terminal_reason FROM event_triggers WHERE event_id=?",
            (event_id,),
        ).fetchone()
        assert row["terminal_state"] == "expired"
        assert row["terminal_reason"] == "已准"
        assert {"id": event_id, "title": ev.title, "terminal_state": "expired"} in applied
    finally:
        content.events.remove(ev)


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


def test_fiscal_levy_pending_choice_waits_for_event_window(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1638
    state.period = 12
    db.save_state(state)
    before = _settle_payload(db, "shaanxi")
    db.record_event_decision_choice(
        state,
        "lian_levy_start_1639",
        {"label": "已准"},
    )

    apply_historical_fiscal_rates(state, db)

    row = db.conn.execute(
        "SELECT terminal_state, terminal_reason FROM event_triggers WHERE event_id=?",
        ("lian_levy_start_1639",),
    ).fetchone()
    assert dict(row) == {"terminal_state": "", "terminal_reason": "已准"}
    after = _settle_payload(db, "shaanxi")
    expected_sanxiang = after["_meta"]["辽饷九厘基线"] * 4.0 / 3.0 + after["_meta"]["剿饷基线"]
    assert math.isclose(after["p"]["三饷应征"], expected_sanxiang, rel_tol=1e-9, abs_tol=1e-9)
    assert before["p"]["三饷应征"] != after["p"]["三饷应征"]

    state.year = 1639
    state.period = 1
    db.save_state(state)
    apply_historical_fiscal_rates(state, db)

    row = db.conn.execute(
        "SELECT terminal_state, terminal_reason FROM event_triggers WHERE event_id=?",
        ("lian_levy_start_1639",),
    ).fetchone()
    assert dict(row) == {"terminal_state": "triggered", "terminal_reason": "已准"}


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


def test_liao_levy_rewrites_numeric_string_targets_to_canonical_numbers(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)

    apply_historical_fiscal_rates(state, db)
    stale = _settle_payload(db, "shaanxi")
    expected_sanxiang = stale["p"]["三饷应征"]
    expected_transport = stale["p"]["起运定额"]
    stale["p"]["三饷应征"] = str(expected_sanxiang)
    stale["p"]["起运定额"] = str(expected_transport)
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id = ?", ("shaanxi",)).fetchone()
    fiscal = json.loads(str(row["fiscal"] or "{}"))
    fiscal["settle"] = stale
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id = ?",
        (json.dumps(fiscal, ensure_ascii=False), "shaanxi"),
    )
    db.conn.commit()

    apply_historical_fiscal_rates(state, db)

    after = _settle_payload(db, "shaanxi")
    assert isinstance(after["p"]["三饷应征"], float)
    assert isinstance(after["p"]["起运定额"], float)
    assert math.isclose(
        after["p"]["三饷应征"],
        expected_sanxiang,
        rel_tol=1e-9,
        abs_tol=1e-9,
    )
    assert math.isclose(
        after["p"]["起运定额"],
        expected_transport,
        rel_tol=1e-9,
        abs_tol=1e-9,
    )


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


def test_levy_retreat_recomputes_transport_without_active_rate_change(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1640
    state.period = 1
    db.save_state(state)
    db.mark_event_triggered(state, "liao_levy_rise_1631", source="test", terminal_reason="已驳", commit=False)
    db.mark_event_triggered(state, "jiao_levy_start_1637", source="test", terminal_reason="已准", commit=False)
    db.mark_event_triggered(state, "jiao_levy_stop_1640", source="test", terminal_reason="已停", commit=False)
    db.mark_event_triggered(state, "lian_levy_start_1639", source="test", terminal_reason="已驳", commit=False)
    stale = _settle_payload(db, "shaanxi")
    base_transport = stale["_meta"]["正赋起运基线"]
    liao_seed = stale["_meta"]["辽饷九厘基线"]
    stale_jiao = 9.0
    stale["p"]["三饷应征"] = liao_seed + stale_jiao
    stale["p"]["起运定额"] = base_transport + liao_seed + stale_jiao
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id = ?", ("shaanxi",)).fetchone()
    fiscal = json.loads(str(row["fiscal"] or "{}"))
    fiscal["settle"] = stale
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id = ?",
        (json.dumps(fiscal, ensure_ascii=False), "shaanxi"),
    )
    db.conn.commit()

    apply_historical_fiscal_rates(state, db)

    after = _settle_payload(db, "shaanxi")
    assert math.isclose(after["p"]["三饷应征"], liao_seed, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(after["p"]["起运定额"], base_transport + liao_seed, rel_tol=1e-9, abs_tol=1e-9)


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
