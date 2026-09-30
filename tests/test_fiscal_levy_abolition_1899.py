"""#1899 新档罢赋罢饷作用于现役财政真源。

刀口：`issues._apply_fiscal_levy_targets` 的 set-to-target。此前罢辽饷／罢田赋只改
legacy 字段（fiscal_config 目录行 + regions.tax_per_turn / fiscal.liao_xiang），
现役 tick 读的 `settle.p` 不动，下月财政照旧征。本票让最后有效批语（罢/复）进
`settle.p`：辽饷分量归零、正赋应征归零；罢后又在历史升率节点批「准」= 重新开征
按新率征，不另要恢复旨；未罢者驳升率仍九厘基线。

覆盖票面「怎么验」：罢辽饷／罢田赋与未罢对照、罢后驳升率仍不征、未罢者驳升率
仍征九厘、罢后准升率下月按新率重征、中途恢复不重复扣征不被旧决定覆盖。
"""
import json
import math

import pytest

from ming_sim.issues import apply_historical_fiscal_rates
import ming_sim.issues as issues


def _settle(db, region_id="shaanxi"):
    row = db.conn.execute(
        "SELECT fiscal FROM regions WHERE id = ?", (region_id,),
    ).fetchone()
    return json.loads(str(row["fiscal"] or "{}"))["settle"]


def _at(game, year, period):
    db, state, content = game
    issues.bind_content(content)
    state.year = year
    state.period = period
    db.save_state(state)
    return db, state


def _abolish(db, stem, turn):
    """走真裁撤口（remove_fiscal_item）：删目录行 + 写 tombstone，与旨意落账同路。"""
    removed = db.remove_fiscal_item(
        f"{stem}_base", commit=False, turn=turn, origin_ref=f"edict:{turn}", reason="罢征",
    )
    assert removed is not None, stem
    return removed


def _mark_rise(db, state, label):
    db.mark_event_triggered(
        state, "liao_levy_rise_1631", source="test", terminal_reason=label, commit=False,
    )


def _reabolish_by_zeroing_rate(db, state):
    """第二道罢批语：辽饷_base 目录行已删，改以 fiscal_config_changes 把
    辽饷_rate 调回 0 表示停征（罢的另一落法），并留 changes 账供 turn 比对。"""
    origin = f"edict:{state.turn}"
    db.conn.execute(
        "INSERT INTO fiscal_config(key,value,kind,note) VALUES ('辽饷_rate',0,'rate','') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
    )
    db.conn.execute(
        "INSERT INTO fiscal_config_changes (turn, key, old_value, new_value, delta, origin_ref, reason) "
        "VALUES (?, '辽饷_rate', 100, 0, -100, ?, '再罢')",
        (state.turn, origin),
    )
    db.conn.commit()


def test_abolished_liao_levy_stops_collection_next_month(game):
    """罢辽饷 → 过月后 settle.p.三饷应征 的辽饷分量归零（起运随之回落）。"""
    db, state = _at(game, 1627, 10)
    before = _settle(db)
    liao_seed = before["p"]["三饷应征"]
    base_transport = before["_meta"].get("正赋起运基线")
    if base_transport is None:
        base_transport = before["p"]["起运定额"] - liao_seed
    assert liao_seed > 0

    _abolish(db, "辽饷", state.turn)
    apply_historical_fiscal_rates(state, db)

    after = _settle(db)
    assert after["p"]["三饷应征"] == 0.0
    assert after["p"]["起运定额"] == pytest.approx(base_transport)
    # 基线不被罢抹掉（P1：复征靠它，逐月重算不漂移）。
    assert after["_meta"]["辽饷九厘基线"] == pytest.approx(liao_seed)


def test_abolished_liao_levy_rejected_rise_stays_stopped(game):
    """罢辽饷后在历史升率节点驳回／留中 → 仍不征。"""
    db, state = _at(game, 1631, 1)
    _abolish(db, "辽饷", state.turn)
    _mark_rise(db, state, "已驳")

    apply_historical_fiscal_rates(state, db)

    assert _settle(db)["p"]["三饷应征"] == 0.0


def test_rejected_rise_without_abolition_keeps_nine_li_baseline(game):
    """未罢辽饷而驳升率 → 仍用九厘基线征（不误停征）。"""
    db, state = _at(game, 1631, 1)
    seed = _settle(db)["p"]["三饷应征"]
    _mark_rise(db, state, "已驳")

    apply_historical_fiscal_rates(state, db)

    assert _settle(db)["p"]["三饷应征"] == pytest.approx(seed)


def test_abolished_liao_levy_reopened_by_later_rise_approval_uses_new_rate(game):
    """罢辽饷 → 后在历史升率节点批「准」= 重新开征，按新率征，不另要恢复旨。

    三个时序必须分开验证（票面「怎么验」：两种决定中途恢复、互不覆盖）：
    罢→准（复征按新率）、准→罢（罢在后 = 不征）、罢→准→再罢（最后批语是罢）。
    """
    db, state = _at(game, 1631, 1)

    # ① 罢在前、准在后 → 重新开征，按新率。
    _abolish(db, "辽饷", state.turn)
    state.turn += 5
    state.year, state.period = 1631, 6
    db.save_state(state)
    _mark_rise(db, state, "已准")
    apply_historical_fiscal_rates(state, db)
    reopened = _settle(db)
    assert reopened["p"]["三饷应征"] == pytest.approx(
        reopened["_meta"]["辽饷九厘基线"] * 4.0 / 3.0
    )

    # ② 罢→准→再罢：最后有效批语是罢 → 又不征（旧复征不覆盖新罢）。
    # 再罢走 fiscal_config_changes 把值调回 0（罢的另一种落法）：辽饷_base 目录行
    # 早在①已被 remove_fiscal_item 删掉，无行可再 remove，故以调零表示第二道罢批语。
    state.turn += 5
    state.year, state.period = 1631, 11
    db.save_state(state)
    _reabolish_by_zeroing_rate(db, state)
    apply_historical_fiscal_rates(state, db)
    assert _settle(db)["p"]["三饷应征"] == 0.0


def test_rise_approved_before_abolition_keeps_abolition_in_force(game):
    """准升率在前、罢辽饷在后 → 最后批语是罢，下月不征（罢饷真正生效）。

    这是评审指出的缺腿：布尔实现会把「准」当成永久复征，令罢在此时序下失效。
    """
    db, state = _at(game, 1631, 1)
    _mark_rise(db, state, "已准")
    apply_historical_fiscal_rates(state, db)
    risen = _settle(db)["p"]["三饷应征"]
    assert risen > 0

    state.turn += 3
    state.year, state.period = 1631, 4
    db.save_state(state)
    _abolish(db, "辽饷", state.turn)

    apply_historical_fiscal_rates(state, db)

    assert _settle(db)["p"]["三饷应征"] == 0.0


def test_abolished_tian_fu_zeroes_regular_assessment_and_restores_on_recall(game):
    """罢田赋 → 正赋应征归零；复征（重立目录行）→ 回原基线，不重复扣征。"""
    db, state = _at(game, 1627, 10)
    before = _settle(db)["p"]["正赋应征"]
    assert before > 0

    _abolish(db, "田赋", state.turn)
    apply_historical_fiscal_rates(state, db)

    during = _settle(db)
    assert during["p"]["正赋应征"] == 0.0
    assert during["_meta"]["正赋应征基线"] == pytest.approx(before)

    # 复征 = 一道新批语（fiscal_config_creations 重立目录行），比罢晚 → 复征在位。
    state.turn += 1
    state.year, state.period = 1628, 1
    db.save_state(state)
    db.conn.execute(
        "INSERT INTO fiscal_config_creations (turn, key, value, kind, origin_ref, reason) "
        "VALUES (?, '田赋_rate', 68, 'rate', ?, '复征')",
        (state.turn, f"edict:{state.turn}"),
    )
    db.conn.execute(
        "INSERT INTO fiscal_config(key,value,kind,note) VALUES ('田赋_rate',68,'rate','') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
    )
    db.conn.commit()

    apply_historical_fiscal_rates(state, db)

    after = _settle(db)
    assert after["p"]["正赋应征"] == pytest.approx(before)
    assert "正赋应征基线" not in after["_meta"]


def test_abolition_is_idempotent_across_repeated_months(game):
    """持续罢征不因逐月重算被抹掉、不重复扣征（幂等 set-to-target）。"""
    db, state = _at(game, 1627, 10)
    _abolish(db, "辽饷", state.turn)
    _abolish(db, "田赋", state.turn)

    apply_historical_fiscal_rates(state, db)
    first = _settle(db)["p"]
    apply_historical_fiscal_rates(state, db)
    second_settle = _settle(db)
    second = second_settle["p"]

    assert first["三饷应征"] == second["三饷应征"] == 0.0
    assert first["正赋应征"] == second["正赋应征"] == 0.0
    assert math.isclose(
        second["起运定额"], second_settle["_meta"]["正赋起运基线"],
        rel_tol=1e-9, abs_tol=1e-9,
    )


def test_no_abolition_leaves_regular_assessment_untouched(game):
    """无罢/复批语时正赋应征逐字节不动（ADR 0020 落位 5 保集，不越界改真源）。"""
    db, state = _at(game, 1627, 10)
    before = _settle(db)["p"]["正赋应征"]

    apply_historical_fiscal_rates(state, db)

    assert _settle(db)["p"]["正赋应征"] == before
    assert "正赋应征基线" not in _settle(db)["_meta"]


def test_abolition_moves_real_settlement_accounts(game):
    """票面「怎么验」：过月核省税、起运与国库实账——真账随罢征回落，不止 p 变。"""
    from ming_sim.fiscal_tick import settle_tick

    db, state = _at(game, 1627, 10)
    apply_historical_fiscal_rates(state, db)
    before = _settle(db)
    base = settle_tick(before["st"], before["p"], []).breakdown

    _abolish(db, "辽饷", state.turn)
    _abolish(db, "田赋", state.turn)
    apply_historical_fiscal_rates(state, db)
    after = _settle(db)
    post = settle_tick(after["st"], after["p"], []).breakdown

    # 正赋 + 三饷双零 → 实征/起运/火耗全塌，民欠不再新增。
    assert post["实征"] == 0.0
    assert post["起运到京"] == 0.0
    assert post["火耗实收"] == 0.0
    assert post["民欠新增"] == 0.0
    assert base["实征"] > 0 and base["起运到京"] > 0


def test_abolition_handles_land_derived_regular_assessment(game):
    """正赋应征=None（亩额派生）时罢/复：基线存 None，复征回 None 而非 0。"""
    db, state = _at(game, 1627, 10)
    fiscal = json.loads(
        str(db.conn.execute("SELECT fiscal FROM regions WHERE id = 'shaanxi'").fetchone()["fiscal"])
    )
    fiscal["settle"]["p"]["正赋应征"] = None
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id = 'shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    db.conn.commit()

    _abolish(db, "田赋", state.turn)
    apply_historical_fiscal_rates(state, db)

    during = _settle(db)
    assert during["p"]["正赋应征"] == 0.0
    assert "正赋应征基线" in during["_meta"]
    assert during["_meta"]["正赋应征基线"] is None

    state.turn += 1
    state.year, state.period = 1628, 1
    db.save_state(state)
    db.conn.execute(
        "INSERT INTO fiscal_config_creations (turn, key, value, kind, origin_ref, reason) "
        "VALUES (?, '田赋_rate', 68, 'rate', ?, '复征')",
        (state.turn, f"edict:{state.turn}"),
    )
    db.conn.execute(
        "INSERT INTO fiscal_config(key,value,kind,note) VALUES ('田赋_rate',68,'rate','') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
    )
    db.conn.commit()

    apply_historical_fiscal_rates(state, db)

    restored = _settle(db)
    assert restored["p"]["正赋应征"] is None  # 回亩额派生，不是回 0
    assert "正赋应征基线" not in restored["_meta"]
