import json
import math

import pytest

from ming_sim.decree import pre_settle
from ming_sim.exceptions import SettlementAbort
from ming_sim.army_pay import army_needed
from ming_sim.issues import apply_historical_fiscal_rates
import ming_sim.issues as issues
from ming_sim.models import Event


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


def _emperor_decides(db, state, *event_labels):
    """三饷结局只由皇帝亲裁落（#1892 退役 shadow 自动已准桩）。

    真实写口＝亲笔准驳经 #1815 单一语义写口
    （:func:`ming_sim.issues.apply_petition_event_outcome`）置定事件终态；原始选项
    标签不得旁路代批，故此处不再调 record_event_decision_choice 让饷率通道代批。
    传 (event_id, label) 对，label 取事件自声明的封闭结局标签集。

    **窗口外的事项一律不置结局**：当年还没到点上疏，皇帝无从亲裁，其时也不该有
    结局（旧 staged 路径把这类行暂存到 window 之后才消费，等于替皇帝预批一疏）。
    跳过而非兜底写账，测试据此按年断言哪几项在征。
    """
    from ming_sim.issues import _event_window_open, _fiscal_levy_event_by_id

    for event_id, label in event_labels:
        event = _fiscal_levy_event_by_id(event_id)
        if event is None or not _event_window_open(event, state):
            continue
        issues.apply_petition_event_outcome(state, db, event_id, label)


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


def test_liao_levy_rise_approved_by_emperor_updates_settle_before_fiscal_tick(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    _emperor_decides(db, state, ("liao_levy_rise_1631", "已准"))

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
    assert dict(row)["terminal_state"] == "triggered"
    assert dict(row)["terminal_reason"] == "已准"
    assert dict(row)["source"] == "petition_verdict"

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


def test_liao_levy_rise_approved_lands_on_no_edict_advance_before_fiscal_tick(game, monkeypatch):
    """#1274：无旨完整结算 pre_settle 内历史饷率事件仍在 fiscal tick 前触发。"""
    import ming_sim.month_chain as month_chain
    from ming_sim.session import GameSession

    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    before = _settle_payload(db, "shaanxi")
    seed_liao = before["p"]["三饷应征"]
    target_liao = seed_liao * 4.0 / 3.0
    _emperor_decides(db, state, ("liao_levy_rise_1631", "已准"))

    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: "")

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
    assert dict(row)["terminal_state"] == "triggered"
    assert dict(row)["terminal_reason"] == "已准"
    assert dict(row)["source"] == "petition_verdict"
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
def test_fiscal_levy_capstone_golden_all_seeded_provinces(
    game, year, expected_event_ids, expect_jiao_in_force, expect_lian_in_force
):
    db, state, content = game
    issues.bind_content(content)
    state.year = year
    state.period = 1
    db.save_state(state)
    _emperor_decides(
        db, state,
        ("liao_levy_rise_1631", "已准"),
        ("jiao_levy_start_1637", "已准"),
        ("lian_levy_start_1639", "已准"),
        ("jiao_levy_stop_1640", "已停"),
    )
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








def test_fiscal_levy_skips_malformed_region_fiscal_without_blocking_fiscal_levy_pass(game, monkeypatch):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    _emperor_decides(db, state, ("liao_levy_rise_1631", "已准"))
    before_huguang = _settle_payload(db, "huguang")["p"]["三饷应征"]
    msgs = []
    monkeypatch.setattr(issues, "tlog", lambda msg: msgs.append(msg))
    db.conn.execute("UPDATE regions SET fiscal = ? WHERE id = ?", ("{bad", "shaanxi"))
    db.conn.commit()

    apply_historical_fiscal_rates(state, db)

    assert msgs
    huguang = _settle_payload(db, "huguang")
    assert huguang["p"]["三饷应征"] > before_huguang


@pytest.mark.parametrize(
    "bad_field,expected_log",
    [
        ("_meta", "shaanxi.settle._meta 非字典"),
        ("land", "shaanxi.settle.st.官民田 非数值"),
    ],
)
def test_fiscal_levy_skips_bad_settle_shape_without_blocking_other_regions(
    game, monkeypatch, bad_field, expected_log
):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    _emperor_decides(db, state, ("liao_levy_rise_1631", "已准"))
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
    _emperor_decides(db, state, ("liao_levy_rise_1631", "已准"))
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
    _emperor_decides(
        db, state,
        ("liao_levy_rise_1631", "已准"),
        ("jiao_levy_start_1637", "已准"),
    )

    total_land = _settle_land_sum(db)
    huguang_before = _settle_payload(db, "huguang")
    expected_jiao = _expected_land_share_levy(huguang_before, JIAO_NATIONAL_MONTHLY, total_land)
    expected_lian = _expected_land_share_levy(huguang_before, LIAN_NATIONAL_MONTHLY, total_land)
    expected_liao = huguang_before["p"]["三饷应征"] * 4.0 / 3.0

    apply_historical_fiscal_rates(state, db)
    state.year = 1639
    state.period = 1
    db.save_state(state)
    # 练饷 1639 才到点上疏：此时亲裁，1637 那一年它本不该有结局。
    _emperor_decides(db, state, ("lian_levy_start_1639", "已准"))

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

    assert msgs
    huguang = _settle_payload(db, "huguang")
    assert math.isclose(huguang["_meta"]["剿饷基线"], expected_jiao, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(huguang["_meta"]["练饷基线"], expected_lian, rel_tol=1e-9, abs_tol=1e-9)
    assert math.isclose(
        huguang["p"]["三饷应征"],
        expected_liao + expected_jiao + expected_lian,
        rel_tol=1e-9,
        abs_tol=1e-9,
    )




@pytest.mark.parametrize("bad_shape", ["land", "p", "st", "settle"])
def test_fiscal_levy_incomplete_first_pass_does_not_freeze_zero_share_seed(
    game, monkeypatch, bad_shape
):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1637
    state.period = 1
    db.save_state(state)
    _emperor_decides(
        db, state,
        ("liao_levy_rise_1631", "已准"),
        ("jiao_levy_start_1637", "已准"),
    )

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




@pytest.mark.parametrize("bad_meta_key", ["剿饷基线", "练饷基线", "饷率田亩分母基线"])
def test_fiscal_levy_bad_share_meta_does_not_crash_or_redistribute_first_pass(
    game, monkeypatch, bad_meta_key
):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1637
    state.period = 1
    db.save_state(state)
    _emperor_decides(
        db, state,
        ("liao_levy_rise_1631", "已准"),
        ("jiao_levy_start_1637", "已准"),
    )
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

    assert msgs
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






def test_fiscal_levy_is_not_auto_approved_without_emperor_decision(game):
    """#1892 J5：三饷是皇帝亲裁——引擎不代批红，无裁决不记「已准」、不变征收额。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    before = _settle_payload(db, "shaanxi")["p"]

    apply_historical_fiscal_rates(state, db)

    assert db.conn.execute(
        "SELECT 1 FROM event_triggers WHERE event_id=?", ("liao_levy_rise_1631",),
    ).fetchone() is None
    assert _settle_payload(db, "shaanxi")["p"]["三饷应征"] == before["三饷应征"]

    # 亲裁「准」后同通道才落终态并按新额征收。
    _emperor_decides(db, state, ("liao_levy_rise_1631", "已准"))
    apply_historical_fiscal_rates(state, db)

    row = db.conn.execute(
        "SELECT terminal_state, terminal_reason FROM event_triggers WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone()
    assert dict(row) == {"terminal_state": "triggered", "terminal_reason": "已准"}
    assert math.isclose(
        _settle_payload(db, "shaanxi")["p"]["三饷应征"],
        before["三饷应征"] * 4.0 / 3.0,
        rel_tol=1e-9, abs_tol=1e-9,
    )


def test_fiscal_levy_events_are_not_in_model_candidate_pool(game):
    """#1892 J5：三饷不在人物候选里交世界段模型代批。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)

    candidate_ids = {ev.id for ev in issues.gather_candidate_events(state, db)}

    assert "liao_levy_rise_1631" not in candidate_ids
    assert "jiao_levy_start_1637" not in candidate_ids
    assert "lian_levy_start_1639" not in candidate_ids
    # 排除的不是整个候选池：同期合资格的人物事件仍在池中。
    assert "jisi_lubian" in candidate_ids


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


def test_lian_levy_start_approved_updates_settle_before_fiscal_tick(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1639
    state.period = 1
    db.save_state(state)
    _emperor_decides(
        db, state,
        ("liao_levy_rise_1631", "已准"),
        ("jiao_levy_start_1637", "已准"),
        ("lian_levy_start_1639", "已准"),
    )

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
    assert dict(row)["terminal_state"] == "triggered"
    assert dict(row)["terminal_reason"] == "已准"
    assert dict(row)["source"] == "petition_verdict"

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

    with pytest.raises(SettlementAbort):
        apply_historical_fiscal_rates(state, db)

    after = _settle_payload(db, "shaanxi")
    assert after["p"] == before["p"]


def test_fiscal_levy_emperor_rejection_lands_outcome_without_levy(game):
    """亲裁「已驳」：终态经语义写口落定，饷额不变（驳则不征）。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    before = _settle_payload(db, "shaanxi")

    _emperor_decides(db, state, ("liao_levy_rise_1631", "已驳"))
    apply_historical_fiscal_rates(state, db)

    row = db.conn.execute(
        "SELECT terminal_state, terminal_reason FROM event_triggers WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone()
    assert dict(row) == {"terminal_state": "triggered", "terminal_reason": "已驳"}
    after = _settle_payload(db, "shaanxi")
    assert after["p"] == before["p"]


def test_fiscal_levy_outcome_is_written_once_and_first_verdict_wins(game):
    """一事件一裁断（ADR 0115:3）：结局一经语义写口落定即不可翻。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    before = _settle_payload(db, "shaanxi")

    _emperor_decides(db, state, ("liao_levy_rise_1631", "已驳"))
    repeat = issues.apply_petition_event_outcome(state, db, "liao_levy_rise_1631", "已准")
    apply_historical_fiscal_rates(state, db)

    assert repeat["terminal_reason"] == "已驳"
    row = db.conn.execute(
        "SELECT terminal_state, terminal_reason FROM event_triggers WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone()
    assert dict(row) == {"terminal_state": "triggered", "terminal_reason": "已驳"}
    assert _settle_payload(db, "shaanxi")["p"] == before["p"]


def test_fiscal_levy_outcome_label_outside_closed_set_aborts(game):
    """结局标签不在事件自声明的封闭集内 → 响亮失败，不兜底写未支撑值（ADR 0014）。"""
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)

    with pytest.raises(SettlementAbort, match="结局标签无法归一"):
        issues.apply_petition_event_outcome(state, db, "liao_levy_rise_1631", "留中")
    assert db.conn.execute(
        "SELECT 1 FROM event_triggers WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone() is None




def test_fiscal_levy_pending_stop_choice_keeps_jiao_in_force_same_tick(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1640
    state.period = 1
    db.save_state(state)
    _emperor_decides(
        db, state,
        ("liao_levy_rise_1631", "已准"),
        ("lian_levy_start_1639", "已准"),
    )
    db.mark_event_triggered(state, "jiao_levy_start_1637", source="test", terminal_reason="已准")
    _emperor_decides(db, state, ("jiao_levy_stop_1640", "仍征"))

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
    _emperor_decides(
        db, state,
        ("liao_levy_rise_1631", "已准"),
        ("jiao_levy_start_1637", "已准"),
    )
    before = _settle_payload(db, "shaanxi")
    # 练饷 1639 才到点：1638 年它不在可呈窗口内，无从亲裁，语义写口响亮拒绝——
    # 旧 staged 路径会把这类答复暂存到窗口之后消费，等于替皇帝预批一疏。
    with pytest.raises(SettlementAbort, match="不在可呈窗口内"):
        issues.apply_petition_event_outcome(state, db, "lian_levy_start_1639", "已准")
    apply_historical_fiscal_rates(state, db)

    assert db.conn.execute(
        "SELECT 1 FROM event_triggers WHERE event_id=?",
        ("lian_levy_start_1639",),
    ).fetchone() is None
    after = _settle_payload(db, "shaanxi")
    expected_sanxiang = after["_meta"]["辽饷九厘基线"] * 4.0 / 3.0 + after["_meta"]["剿饷基线"]
    assert math.isclose(after["p"]["三饷应征"], expected_sanxiang, rel_tol=1e-9, abs_tol=1e-9)
    assert before["p"]["三饷应征"] != after["p"]["三饷应征"]

    state.year = 1639
    state.period = 1
    db.save_state(state)
    _emperor_decides(db, state, ("lian_levy_start_1639", "已准"))
    apply_historical_fiscal_rates(state, db)

    row = db.conn.execute(
        "SELECT terminal_state, terminal_reason FROM event_triggers WHERE event_id=?",
        ("lian_levy_start_1639",),
    ).fetchone()
    assert dict(row) == {"terminal_state": "triggered", "terminal_reason": "已准"}






def test_liao_levy_targets_all_seeded_settles_without_compounding_or_clobbering_p(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    _emperor_decides(db, state, ("liao_levy_rise_1631", "已准"))

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
    # 剿饷开征 1637 到点上疏；练饷（1639）与剿饷议停（1640）当年尚未到点，无从亲裁。
    _emperor_decides(
        db, state,
        ("liao_levy_rise_1631", "已准"),
        ("jiao_levy_start_1637", "已准"),
    )

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
    # 1640：剿饷议停与练饷开征各自到点上疏，此时亲裁。
    _emperor_decides(
        db, state,
        ("lian_levy_start_1639", "已准"),
        ("jiao_levy_stop_1640", "已停"),
    )
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
    _emperor_decides(
        db, state,
        ("liao_levy_rise_1631", "已准"),
        ("lian_levy_start_1639", "已准"),
    )
    db.mark_event_triggered(state, "jiao_levy_start_1637", source="test", terminal_reason="已准")
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

    with pytest.raises(SettlementAbort):
        apply_historical_fiscal_rates(state, db)


def test_lian_levy_targets_all_seeded_settles_without_compounding_or_clobbering_p(game):
    db, state, content = game
    issues.bind_content(content)
    state.year = 1639
    state.period = 1
    db.save_state(state)
    _emperor_decides(
        db, state,
        ("liao_levy_rise_1631", "已准"),
        ("jiao_levy_start_1637", "已准"),
        ("lian_levy_start_1639", "已准"),
    )

    before_by_region = {}
    for row in db.conn.execute("SELECT id, fiscal FROM regions ORDER BY id").fetchall():
        fiscal = json.loads(str(row["fiscal"] or "{}"))
        settle = fiscal.get("settle") if isinstance(fiscal, dict) else None
        if isinstance(settle, dict) and isinstance(settle.get("p"), dict):
            before_by_region[str(row["id"])] = dict(settle["p"])
    assert len(before_by_region) >= 17

    apply_historical_fiscal_rates(state, db)
    # 亲裁经语义写口落定终态后，饷率通道只据终态账落征收（不再自行置结局，
    # 故此处断言事件账终态，而非通道自身的 applied 清单）。
    assert dict(db.conn.execute(
        "SELECT terminal_state, terminal_reason FROM event_triggers WHERE event_id=?",
        ("lian_levy_start_1639",),
    ).fetchone()) == {"terminal_state": "triggered", "terminal_reason": "已准"}
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
    _emperor_decides(
        db, state,
        ("liao_levy_rise_1631", "已准"),
        ("jiao_levy_start_1637", "已准"),
        ("lian_levy_start_1639", "已准"),
    )

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
    _emperor_decides(
        db, state,
        ("liao_levy_rise_1631", "已准"),
        ("jiao_levy_start_1637", "已准"),
    )

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
    # 练饷此刻才到点：此前无任何行，此时亲裁才落终态（窗口外无从亲裁）。
    assert db.conn.execute(
        "SELECT 1 FROM event_triggers WHERE event_id=?",
        ("lian_levy_start_1639",),
    ).fetchone() is None
    _emperor_decides(db, state, ("lian_levy_start_1639", "已准"))
    apply_historical_fiscal_rates(state, db)
    assert dict(db.conn.execute(
        "SELECT terminal_state, terminal_reason FROM event_triggers WHERE event_id=?",
        ("lian_levy_start_1639",),
    ).fetchone()) == {"terminal_state": "triggered", "terminal_reason": "已准"}

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
    _emperor_decides(db, state, ("liao_levy_rise_1631", "已准"))
    apply_historical_fiscal_rates(state, db)
    # 结局由亲裁语义写口落定；饷率通道只据终态账落征收，故断言事件账而非 applied 清单。
    assert dict(db.conn.execute(
        "SELECT terminal_state, terminal_reason FROM event_triggers WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone()) == {"terminal_state": "triggered", "terminal_reason": "已准"}

    terminalized = issues.apply_event_terminal_states(state, db)
    assert all(item["id"] != "liao_levy_rise_1631" for item in terminalized)
    assert db.conn.execute(
        "SELECT COUNT(*) FROM event_triggers WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone()[0] == 1


_CONTINUATION_SEGMENT = "world-continuation-segment"


def _install_liao_month_stubs(monkeypatch, *, world_text: str, translate):
    import ming_sim.month_chain as month_chain
    import ming_sim.month_translate as month_translate
    from tests.test_month_chain_1843 import _forbid_extractor

    _forbid_extractor(monkeypatch)
    monkeypatch.setattr(month_chain, "run_world_segment_text", lambda *a, **k: world_text)
    monkeypatch.setattr(month_chain, "run_gazette_text", lambda *a, **k: ("邸报", "本月已过。"))
    monkeypatch.setattr(month_translate, "translate_month_segment", translate)
    monkeypatch.setattr(
        month_chain, "_run_world_continuation_text",
        lambda *a, **k: _CONTINUATION_SEGMENT,
    )
    monkeypatch.setattr("ming_sim.mechanical_tail._run_tail_body", lambda *a, **k: "done")


def _liao_world_question() -> str:
    block = {
        "title": "辽饷升至一分二厘",
        "context": "边饷急迫，请旨定夺。",
        "event_id": "liao_levy_rise_1631",
        "options": [
            {"label": "加派", "hint": "从户部所请"},
            {"label": "不加", "hint": "维持九厘"},
        ],
    }
    return "户部奏辽饷加派。<<DECISION>>" + json.dumps(block, ensure_ascii=False) + "<<END>>"


def _henan_relief_world_question() -> str:
    block = {
        "title": "河南赈灾",
        "context": "河南旱，请发仓粮。",
        "options": [
            {"label": "发仓粮", "hint": "开仓"},
            {"label": "不发", "hint": "另议"},
        ],
    }
    return "河南巡抚奏赈。<<DECISION>>" + json.dumps(block, ensure_ascii=False) + "<<END>>"


def test_fiscal_levy_petition_reaches_emperor_desk_and_lands_only_after_choice(game, monkeypatch):
    """到点三饷经世界段上疏、案头亲裁、语义写口当回合落终态，次月 pre_settle 才改三饷。"""
    import ming_sim.month_chain as month_chain
    from ming_sim.models import LLMConfig
    from tests.month_chain_helpers import make_light_session

    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    before = _settle_payload(db, "shaanxi")["p"]
    seen = []

    def translate(*_a, **kwargs):
        segment = str(kwargs.get("segment") or "")
        seen.append(segment)
        if segment == _CONTINUATION_SEGMENT:
            return {"effects": [{
                "event_id": "liao_levy_rise_1631",
                "事件结局": {"liao_levy_rise_1631": "已准"},
            }]}
        return {"effects": {}}

    _install_liao_month_stubs(
        monkeypatch, world_text=_liao_world_question(), translate=translate,
    )
    session = make_light_session(db, state, content)
    session.llm_config = LLMConfig(
        api_key="sk-test", base_url="https://example.invalid", model="test",
    )
    paused = session.resolve_turn(allow_empty_decree=True)
    assert paused.awaiting is True
    row = next(
        item for item in session.pending_decisions()
        if str(item.get("event_id") or "").startswith("world-question:")
    )
    assert row["event_id"] != "liao_levy_rise_1631"
    chain = month_chain._load_chain(db, int(state.turn))
    assert chain["world_question_event_bindings"][row["event_id"]] == "liao_levy_rise_1631"
    assert db.event_terminal_state("liao_levy_rise_1631") is None
    assert _settle_payload(db, "shaanxi")["p"] == before

    closed_turn = int(state.turn)
    session.submit_hitl_choices(
        [{
            "decision_key": row["decision_key"],
            "label": "加派",
            "hint": "从户部所请",
        }],
        write_gate=session._write_gate,
    )
    assert int(state.turn) != closed_turn
    assert _CONTINUATION_SEGMENT in seen
    led = db.conn.execute(
        "SELECT terminal_state, terminal_reason FROM event_triggers WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone()
    assert dict(led) == {"terminal_state": "triggered", "terminal_reason": "已准"}
    assert month_chain._load_chain(db, closed_turn).get("world_continued") is True
    assert _settle_payload(db, "shaanxi")["p"]["三饷应征"] == before["三饷应征"]

    session.resolve_turn(allow_empty_decree=True)
    assert math.isclose(
        _settle_payload(db, "shaanxi")["p"]["三饷应征"],
        before["三饷应征"] * 4.0 / 3.0,
        rel_tol=1e-9,
        abs_tol=1e-9,
    )


def test_unpresented_fiscal_levy_declaration_leaves_terminal_empty(game, monkeypatch):
    """到期未呈的三饷事项，世界段转译声明结局后终态仍空。"""
    from ming_sim.models import LLMConfig
    from tests.month_chain_helpers import make_light_session

    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)

    def translate(*_a, **_k):
        return {"effects": [{
            "event_id": "liao_levy_rise_1631",
            "事件结局": {"liao_levy_rise_1631": "已准"},
        }]}

    _install_liao_month_stubs(
        monkeypatch, world_text=_liao_world_question(), translate=translate,
    )
    session = make_light_session(db, state, content)
    session.llm_config = LLMConfig(
        api_key="sk-test", base_url="https://example.invalid", model="test",
    )
    session.resolve_turn(allow_empty_decree=True)
    assert not db.event_terminal_state("liao_levy_rise_1631")
    assert [
        row for row in db.list_event_petition_records()
        if row.get("event_id") == "liao_levy_rise_1631"
    ] == []


def test_non_event_world_question_is_not_bound_to_the_only_due_levy(game, monkeypatch):
    """到期事项只剩一件，也不能把没带该身份的请旨配成它的奏疏。"""
    import ming_sim.month_chain as month_chain
    from ming_sim.models import LLMConfig
    from tests.month_chain_helpers import make_light_session

    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)

    _install_liao_month_stubs(
        monkeypatch,
        world_text=_henan_relief_world_question(),
        translate=lambda *_a, **_k: {"effects": {}},
    )
    session = make_light_session(db, state, content)
    session.llm_config = LLMConfig(
        api_key="sk-test", base_url="https://example.invalid", model="test",
    )
    paused = session.resolve_turn(allow_empty_decree=True)
    assert paused.awaiting is True
    row = next(
        item for item in session.pending_decisions()
        if str(item.get("event_id") or "").startswith("world-question:")
    )
    assert row["title"] == "河南赈灾"
    chain = month_chain._load_chain(db, int(state.turn))
    assert "liao_levy_rise_1631" not in chain["world_question_event_bindings"].values()

    session.submit_hitl_choices(
        [{
            "decision_key": row["decision_key"],
            "label": "发仓粮",
            "hint": "开仓",
        }],
        write_gate=session._write_gate,
    )
    assert db.event_terminal_state("liao_levy_rise_1631") is None
    assert [
        record for record in db.list_event_petition_records()
        if record.get("event_id") == "liao_levy_rise_1631"
        or str((record.get("petition") or {}).get("title") or "") == "河南赈灾"
    ] == []


def test_rejected_levy_identity_does_not_write_a_terminal_from_a_sibling_envelope(game):
    """混合批次里被拒的三饷信封不得把身份留给同批无归属结局。合法项照落。"""
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    before = int(state.metrics["民心"])

    result = dispatch_declaration(db, state, {"effects": [
        {
            "event_id": "liao_levy_rise_1631",
            "事件结局": {"liao_levy_rise_1631": "已准"},
        },
        {
            "事件结局": {"liao_levy_rise_1631": "已准"},
            "metric_delta": {"民心": 1},
        },
    ]})

    assert any(item.category == "event_rejected" for item in result.effects.rejected)
    assert db.event_terminal_state("liao_levy_rise_1631") is None
    assert [
        record for record in db.list_event_petition_records()
        if record.get("event_id") == "liao_levy_rise_1631"
    ] == []
    report = result.effects.applied[0]
    assert report["metric_delta"]["民心"] != 0
    assert state.metrics["民心"] == before + report["metric_delta"]["民心"]


def test_fiscal_levy_held_petition_is_supplied_to_next_world_segment(game, monkeypatch):
    """留中走案头：不写终态，已呈原文与原批语进入后续世界材料。"""
    from pathlib import Path

    from ming_sim import materials as materials_mod
    from ming_sim.models import LLMConfig
    from tests.month_chain_helpers import make_light_session

    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)
    before = _settle_payload(db, "shaanxi")

    def translate(*_a, **_k):
        return {"effects": {}}

    _install_liao_month_stubs(
        monkeypatch, world_text=_liao_world_question(), translate=translate,
    )
    session = make_light_session(db, state, content)
    session.llm_config = LLMConfig(
        api_key="sk-test", base_url="https://example.invalid", model="test",
    )
    session.resolve_turn(allow_empty_decree=True)
    row = next(
        item for item in session.pending_decisions()
        if str(item.get("event_id") or "").startswith("world-question:")
    )
    closed_turn = int(state.turn)
    session.submit_hitl_choices(
        [{"decision_key": row["decision_key"], "note": "姑候户部再核"}],
        write_gate=session._write_gate,
    )
    assert int(state.turn) != closed_turn
    led = db.conn.execute(
        "SELECT terminal_state, terminal_reason FROM event_triggers WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone()
    assert dict(led)["terminal_state"] == ""
    assert dict(led)["terminal_reason"] == ""
    assert _settle_payload(db, "shaanxi")["p"] == before["p"]

    petitions = materials_mod._world_fiscal_levy_petitions(db, state)
    item = next(entry for entry in petitions if entry["id"] == "liao_levy_rise_1631")
    presented = item["presented"]
    assert presented["presented_context"] == "边饷急迫，请旨定夺。"
    assert presented["emperor_note"] == "姑候户部再核"
    assert presented["held"] is True
    assert "liao_levy_rise_1631" in {
        ev.id for ev in issues.gather_fiscal_levy_petitions(state, db)
    }

    prepared = materials_mod.prepare_world_materials(db, state)
    try:
        petition_dir = Path(prepared.root) / materials_mod._PETITION_DIR
        text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in petition_dir.glob("*.txt")
            if path.name != "INDEX.txt"
        )
        assert "边饷急迫，请旨定夺。" in text
        assert "姑候户部再核" in text
    finally:
        materials_mod.release_material_tree(prepared.root)


def _present_liao_petition(db, state):
    state.year = 1631
    state.period = 1
    db.save_state(state)
    db.record_event_petition_answer(
        state, "liao_levy_rise_1631", {},
        {"title": "辽饷", "context": "请旨", "options": ["已准", "已驳"]},
    )


def _liao_terminal(db):
    row = db.conn.execute(
        "SELECT terminal_state, terminal_reason FROM event_triggers WHERE event_id=?",
        ("liao_levy_rise_1631",),
    ).fetchone()
    return dict(row) if row is not None else None


def test_same_batch_keeps_the_first_event_outcome(game):
    """同批先已驳、后已准：留下第一次裁定，后写不覆盖，也不另造拒收。"""
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    issues.bind_content(content)
    _present_liao_petition(db, state)
    result = dispatch_declaration(db, state, {"effects": [
        {
            "event_id": "liao_levy_rise_1631",
            "事件结局": {"liao_levy_rise_1631": "已驳"},
        },
        {
            "event_id": "liao_levy_rise_1631",
            "事件结局": {"liao_levy_rise_1631": "已准"},
        },
    ]})
    assert result.effects.rejected == []
    assert _liao_terminal(db) == {"terminal_state": "triggered", "terminal_reason": "已驳"}


def _outcome_rejection_rows(db):
    return [
        dict(row) for row in db.conn.execute(
            "SELECT section, category, reason, item_json FROM rejection_reports"
        ).fetchall()
    ]


def test_unbound_envelope_does_not_overwrite_the_first_event_outcome(game):
    """归属非法的结局不写入、留下结构化拒收；合法兄弟效果与首次裁定仍在。"""
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    issues.bind_content(content)
    _present_liao_petition(db, state)
    db.record_event_petition_answer(
        state, "jiao_levy_start_1637", {},
        {"title": "剿饷", "context": "请旨", "options": ["已准", "已驳"]},
    )
    before = int(state.metrics["民心"])
    cross = dispatch_declaration(db, state, {"effects": [{
        "event_id": "jiao_levy_start_1637",
        "事件结局": {"liao_levy_rise_1631": "已准"},
        "metric_delta": {"民心": 1},
    }]})
    assert len(cross.effects.rejected) == 1
    assert cross.effects.rejected[0].category == "invalid_state"
    assert cross.effects.rejected[0].item["事件结局"] == {"liao_levy_rise_1631": "已准"}
    assert _liao_terminal(db) == {"terminal_state": "", "terminal_reason": ""}
    assert state.metrics["民心"] == before + 1
    assert any(
        row["section"] == "effects" and row["category"] == "invalid_state"
        for row in _outcome_rejection_rows(db)
    )

    result = dispatch_declaration(db, state, {"effects": [
        {
            "event_id": "liao_levy_rise_1631",
            "事件结局": {"liao_levy_rise_1631": "已驳"},
        },
        {
            "事件结局": {"liao_levy_rise_1631": "已准"},
            "metric_delta": {"民心": 1},
        },
    ]})
    assert len(result.effects.rejected) == 1
    assert result.effects.rejected[0].item["event_id"] == ""
    assert result.effects.rejected[0].item["事件结局"] == {"liao_levy_rise_1631": "已准"}
    assert _liao_terminal(db) == {"terminal_state": "triggered", "terminal_reason": "已驳"}
    report = result.effects.applied[0]
    assert state.metrics["民心"] == before + 1 + report["metric_delta"]["民心"]
    assert len(_outcome_rejection_rows(db)) == 2


def test_later_illegal_outcome_does_not_discard_the_first_ruling(game):
    """后一封非法标签不得把同事件已成立的第一次裁定整组打掉。"""
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    issues.bind_content(content)
    _present_liao_petition(db, state)
    result = dispatch_declaration(db, state, {"effects": [
        {
            "event_id": "liao_levy_rise_1631",
            "事件结局": {"liao_levy_rise_1631": "已驳"},
        },
        {
            "event_id": "liao_levy_rise_1631",
            "事件结局": {"liao_levy_rise_1631": "乱写"},
        },
    ]})
    assert result.effects.rejected == []
    assert _liao_terminal(db) == {"terminal_state": "triggered", "terminal_reason": "已驳"}


def test_independent_petition_outcome_commits_for_another_connection(game):
    """独立调用默认提交；第二条连接读得到终态。commit=False 则不落盘。"""
    import sqlite3

    db, state, content = game
    issues.bind_content(content)
    state.year = 1631
    state.period = 1
    db.save_state(state)

    held = issues.apply_petition_event_outcome(
        state, db, "liao_levy_rise_1631", "已准", commit=False,
    )
    assert held["settled"] is True
    other = sqlite3.connect(db.path)
    try:
        absent = other.execute(
            "SELECT terminal_reason FROM event_triggers WHERE event_id=?",
            ("liao_levy_rise_1631",),
        ).fetchone()
    finally:
        other.close()
    assert absent is None or not str(absent[0] or "").strip()
    db.conn.rollback()

    settled = issues.apply_petition_event_outcome(state, db, "liao_levy_rise_1631", "已准")
    assert settled["settled"] is True
    assert settled["terminal_reason"] == "已准"
    other = sqlite3.connect(db.path)
    try:
        row = other.execute(
            "SELECT terminal_state, terminal_reason FROM event_triggers WHERE event_id=?",
            ("liao_levy_rise_1631",),
        ).fetchone()
    finally:
        other.close()
    assert tuple(row) == ("triggered", "已准")
