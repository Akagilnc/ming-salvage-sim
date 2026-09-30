"""#1899 新档罢赋罢饷作用于现役财政真源。

刀口：`issues._apply_fiscal_levy_targets` 的 set-to-target。此前罢辽饷／罢田赋只改
目录字段（`fiscal_config` 目录行 + `regions.tax_per_turn` / `fiscal.liao_xiang`），
现役 tick 读的 `settle.p` 不动，下月财政照旧征。本票让最后有效批语（罢/复）进
`settle.p`：辽饷分量归零、正赋应征归零；罢后又在历史升率节点批「准」= 重新开征
按新率征，不另要恢复旨；未罢者驳升率仍九厘基线。

覆盖票面「怎么验」：罢辽饷／罢田赋与未罢对照、罢后驳升率仍不征、未罢者驳升率
仍征九厘、罢后准升率下月按新率重征、中途恢复不重复扣征不被旧决定覆盖。

**入口纪律**（#1899 F7）：一律走真实写口，不手工 INSERT 目录／决定账——罢走
`db.remove_fiscal_item`，罢（调零落法）走 `issues._write_fiscal_config_change`，
复征走 `db.create_fiscal_item`，批红走 `db.record_event_decision_choice` +
`db.mark_event_triggered`。实账断言落在**持久化的 economy_ledger**（过月
`apply_fixed_period_flows` 真落库后的国库流水），不只核 `settle_tick` 的纯函数分解。
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


def _at(game, year, period, turn):
    db, state, content = game
    issues.bind_content(content)
    state.year, state.period, state.turn = year, period, turn
    db.save_state(state)
    return db, state


def _abolish(db, stem, turn, *, origin=None):
    """真实裁撤写口（`remove_fiscal_item`）：删目录行 + 写 tombstone。"""
    removed = db.remove_fiscal_item(
        f"{stem}_base", commit=False, turn=turn,
        origin_ref=origin or f"edict:{turn}", reason="罢征",
    )
    assert removed is not None, stem
    db.conn.commit()
    return removed


def _abolish_by_zeroing_rate(db, stem, turn):
    """罢的第二种落法：目录行留着但把 rate 调零（`_write_fiscal_config_change` 真写口）。

    这是生产上「减半／全罢」的调率路径：base 保留 seed 值、rate 归零，实收恒 0。
    """
    key = f"{stem}_rate"
    old = db.get_fiscal_config().get(key)
    assert old is not None, key
    issues._write_fiscal_config_change(
        db, turn=turn, key=key, old_value=int(old), new_value=0,
        origin_ref=f"edict:{turn}", reason="罢征（调零）",
    )
    db.conn.commit()


def _restore_catalog(db, stem, turn, value=68, origin=None):
    """真实复征写口（`create_fiscal_item`）：重立 base+rate 目录行。"""
    created = db.create_fiscal_item(
        stem, "国库", "income", stem, value,
        note="复征", origin_ref=origin or f"edict:{turn}", turn=turn, commit=False,
    )
    db.conn.commit()
    assert created is not None, stem
    return created


def _emperor_approves_rise(db, state, label="已准"):
    """真实批红写口：先写 choice（皇帝亲裁），再落终态「已准」。"""
    db.record_event_decision_choice(
        state, "liao_levy_rise_1631", {"label": label, "key": "opt_yes"},
        source="hitl_decision", commit=False,
    )
    db.mark_event_triggered(
        state, "liao_levy_rise_1631", source="hitl_decision",
        terminal_reason=label, commit=False,
    )
    db.conn.commit()


def _all_regions_settle_p(db):
    out = {}
    for row in db.conn.execute("SELECT id, fiscal FROM regions ORDER BY id").fetchall():
        fiscal = json.loads(str(row["fiscal"] or "{}"))
        settle = fiscal.get("settle")
        if isinstance(settle, dict) and isinstance(settle.get("p"), dict):
            out[str(row["id"])] = settle["p"]
    return out


# ── 罢赋罢饷作用于现役真源 ────────────────────────────────────────────────

def test_abolished_liao_levy_stops_collection_next_month(game):
    """罢辽饷 → 过月后 settle.p.三饷应征 的辽饷分量归零（起运随之回落）。"""
    db, state = _at(game, 1627, 10, 1)
    before = _settle(db)
    liao_seed = before["p"]["三饷应征"]
    base_transport = before["_meta"].get("正赋起运基线")
    if base_transport is None:
        base_transport = before["p"]["起运定额"] - liao_seed
    assert liao_seed > 0

    _abolish(db, "辽饷", 1)
    apply_historical_fiscal_rates(state, db)

    after = _settle(db)
    assert after["p"]["三饷应征"] == 0.0
    assert after["p"]["起运定额"] == pytest.approx(base_transport)
    # 基线不被罢抹掉（P1：复征靠它，逐月重算不漂移）。
    assert after["_meta"]["辽饷九厘基线"] == pytest.approx(liao_seed)


def test_abolished_liao_levy_by_zeroing_rate_is_not_vetoed_by_base_residue(game):
    """F1：调零落法的罢征**不被同组 base 残值否决**（真调零写口，base 仍为 seed 值）。

    罢走调零时 `辽饷_rate` 归零而 `辽饷_base` 留着 43。旧实现拿「组内任一键为正」
    当在征证据，把这道有效罢征整个否决，下月照旧征 2.1969。dynamic 赋饷实收 ∝
    base×rate，rate 归零即实收恒 0，罢成立。
    """
    db, state = _at(game, 1631, 1, 10)
    _abolish_by_zeroing_rate(db, "辽饷", 10)
    residue = db.get_fiscal_config().get("辽饷_base")
    assert residue and residue > 0, "base 残值确实还在——这正是 F1 的触发条件"

    apply_historical_fiscal_rates(state, db)

    assert _settle(db)["p"]["三饷应征"] == 0.0
    # 全部已 seed settle 的省，辽饷分量都归零（不止抽查一省）。
    for region_id, p in _all_regions_settle_p(db).items():
        assert p["三饷应征"] == 0.0, region_id


def test_abolished_liao_levy_rejected_rise_stays_stopped(game):
    """罢辽饷后在历史升率节点驳回／留中 → 仍不征。"""
    db, state = _at(game, 1631, 1, 10)
    _abolish(db, "辽饷", 10)
    _emperor_approves_rise(db, state, label="已驳")

    apply_historical_fiscal_rates(state, db)

    assert _settle(db)["p"]["三饷应征"] == 0.0


def test_rejected_rise_without_abolition_keeps_nine_li_baseline(game):
    """未罢辽饷而驳升率 → 仍用九厘基线征（不误停征）。"""
    db, state = _at(game, 1631, 1, 10)
    seed = _settle(db)["p"]["三饷应征"]
    _emperor_approves_rise(db, state, label="已驳")

    apply_historical_fiscal_rates(state, db)

    assert _settle(db)["p"]["三饷应征"] == pytest.approx(seed)


def test_abolished_liao_levy_reopened_by_later_rise_approval_uses_new_rate(game):
    """罢辽饷 → 后在历史升率节点批「准」= 重新开征，按新率征，不另要恢复旨。

    三个时序必须分开验证（票面「怎么验」：两种决定中途恢复、互不覆盖）：
    罢→准（复征按新率）、准→罢（罢在后 = 不征）、罢→准→再罢（最后批语是罢）。
    """
    db, state = _at(game, 1631, 1, 10)

    # ① 罢在前、准在后 → 重新开征，按新率。
    _abolish(db, "辽饷", 10)
    db, state = _at(game, 1631, 6, 15)
    _emperor_approves_rise(db, state)
    apply_historical_fiscal_rates(state, db)
    reopened = _settle(db)
    assert reopened["p"]["三饷应征"] == pytest.approx(
        reopened["_meta"]["辽饷九厘基线"] * 4.0 / 3.0
    )

    # ② 罢→准→再罢：最后有效批语是罢 → 又不征（旧复征不覆盖新罢）。
    # 再罢走真裁撤写口：①的复征已把目录行重立回去，故此处确有行可 remove。
    db, state = _at(game, 1631, 11, 20)
    _abolish(db, "辽饷", 20)
    apply_historical_fiscal_rates(state, db)
    assert _settle(db)["p"]["三饷应征"] == 0.0

    # ③ 持续罢征不被逐月重算抹掉：再过一月仍不征。
    db, state = _at(game, 1631, 12, 21)
    apply_historical_fiscal_rates(state, db)
    assert _settle(db)["p"]["三饷应征"] == 0.0


def test_rise_approved_before_abolition_keeps_abolition_in_force(game):
    """准升率在前、罢辽饷在后 → 最后批语是罢，下月不征（罢饷真正生效）。

    这是评审指出的缺腿：布尔实现会把「准」当成永久复征，令罢在此时序下失效。
    """
    db, state = _at(game, 1631, 1, 10)
    _emperor_approves_rise(db, state)
    apply_historical_fiscal_rates(state, db)
    risen = _settle(db)["p"]["三饷应征"]
    assert risen > 0

    db, state = _at(game, 1631, 4, 13)
    _abolish(db, "辽饷", 13)
    apply_historical_fiscal_rates(state, db)

    assert _settle(db)["p"]["三饷应征"] == 0.0


def test_reabolition_after_approval_keeps_both_write_ports_working(game):
    """F4：罢→准→再罢，后续决定的**真写口**都通（不再 missing_ref），且真落罢。

    旧实现里「准」只改 `settle.p`、从不重立目录行，于是再罢时 `remove_fiscal_item`
    与调零两条写口都返回 missing_ref——后续决定根本写不进去，现役照旧征。
    """
    db, state = _at(game, 1631, 1, 10)
    _abolish(db, "辽饷", 10)
    apply_historical_fiscal_rates(state, db)
    assert _settle(db)["p"]["三饷应征"] == 0.0

    db, state = _at(game, 1631, 6, 15)
    _emperor_approves_rise(db, state)
    apply_historical_fiscal_rates(state, db)
    assert _settle(db)["p"]["三饷应征"] > 0, "准后应恢复征收"

    # 再罢：真写口必须有行可 remove（复征已重立目录行）。
    db, state = _at(game, 1631, 11, 20)
    removed = db.remove_fiscal_item(
        "辽饷_base", commit=False, turn=20, origin_ref="edict:20", reason="再罢",
    )
    db.conn.commit()
    assert removed is not None, "复征后应仍有目录行可裁撤"

    apply_historical_fiscal_rates(state, db)
    assert _settle(db)["p"]["三饷应征"] == 0.0


def test_auto_rise_stub_does_not_reinstate_abolished_levy(game):
    """F6：自动落账桩（无 choice_json 的「已准」）不得被当成皇帝的复征决定。

    `run_fiscal_levy_pass` 有一条自动路径，会在没有请旨、没有 choice 的情况下按
    `default_terminal_reason` 把升率事件标成「已准」。若消费者拿它去重新开征一道
    已罢的辽饷，就等于「什么时候变成自动加了？」——凭空复征。
    """
    db, state = _at(game, 1631, 1, 10)
    _abolish(db, "辽饷", 10)
    apply_historical_fiscal_rates(state, db)
    assert _settle(db)["p"]["三饷应征"] == 0.0

    # 纯自动桩：只有终态，没有 choice_json。
    db, state = _at(game, 1631, 6, 15)
    db.mark_event_triggered(
        state, "liao_levy_rise_1631", source="fiscal_levy_shadow",
        terminal_reason="已准", commit=False,
    )
    db.conn.commit()
    row = db.conn.execute(
        "SELECT choice_json FROM event_triggers WHERE event_id = 'liao_levy_rise_1631'"
    ).fetchone()
    assert not str(row["choice_json"] or "").strip(), "本用例前提：桩无 choice"

    apply_historical_fiscal_rates(state, db)

    assert _settle(db)["p"]["三饷应征"] == 0.0, "自动桩不得凭空复征"


# ── 罢田赋作用于现役真源 + 复征闭环 ───────────────────────────────────────

def test_abolished_tian_fu_zeroes_regular_assessment_and_restores_on_recall(game):
    """罢田赋 → 正赋应征归零；复征（重立目录行）→ 回原基线，不重复扣征。"""
    db, state = _at(game, 1627, 10, 1)
    before = _settle(db)["p"]["正赋应征"]
    assert before > 0

    _abolish(db, "田赋", 1)
    apply_historical_fiscal_rates(state, db)

    during = _settle(db)
    assert during["p"]["正赋应征"] == 0.0
    assert during["_meta"]["正赋应征基线"] == pytest.approx(before)

    # 复征 = 一道新批语（真重立写口），比罢晚 → 复征在位。
    db, state = _at(game, 1628, 1, 2)
    _restore_catalog(db, "田赋", 2, value=68)
    apply_historical_fiscal_rates(state, db)

    after = _settle(db)
    assert after["p"]["正赋应征"] == pytest.approx(before)
    assert "正赋应征基线" not in after["_meta"]


def test_recall_does_not_stack_a_second_income_row(game):
    """F5：复征同一税项**不叠加第二条收入**（真重立写口 + 真实预算行遍历）。

    旧实现把重立行一律落 `budget_role='fixed'`，`flows.iter_budget_items` 便把它当
    独立中央收入再记一条，与省级那条同一税项两条收入（全局硬规 #12/#14 单一机制）。
    """
    from ming_sim.flows import compute_budget_lines

    db, state = _at(game, 1627, 10, 1)
    apply_historical_fiscal_rates(state, db)
    before = _settle(db)["p"]["正赋应征"]

    _abolish(db, "田赋", 1)
    apply_historical_fiscal_rates(state, db)
    db, state = _at(game, 1628, 1, 2)
    _restore_catalog(db, "田赋", 2, value=68)
    apply_historical_fiscal_rates(state, db)

    # 复征后正赋应征回原基线（省级那条恢复）。
    assert _settle(db)["p"]["正赋应征"] == pytest.approx(before)

    # 目录行回到 seed 声明的 dynamic 角色，不得成为中央 fixed 收入行。
    rows = db.conn.execute(
        "SELECT key, budget_role, account, direction FROM fiscal_config WHERE key LIKE '田赋%'"
    ).fetchall()
    assert rows, "复征应重立目录行"
    for r in rows:
        assert r["budget_role"] == "dynamic", dict(r)
        assert not str(r["account"] or ""), dict(r)
        assert not str(r["direction"] or ""), dict(r)

    # 预算行遍历不得为该税项再生成一条中央收入。
    budget = compute_budget_lines(db, state)
    for account in ("国库", "内库"):
        for item in budget[account]["income"]:
            assert "田赋" not in str(item["name"]), f"重复收入行 {account}/{item['name']}"


def test_abolition_is_idempotent_across_repeated_months(game):
    """持续罢征不因逐月重算被抹掉、不重复扣征（幂等 set-to-target）。"""
    db, state = _at(game, 1627, 10, 1)
    _abolish(db, "辽饷", 1)
    _abolish(db, "田赋", 1)

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
    db, state = _at(game, 1627, 10, 1)
    before = _settle(db)["p"]["正赋应征"]

    apply_historical_fiscal_rates(state, db)

    assert _settle(db)["p"]["正赋应征"] == before
    assert "正赋应征基线" not in _settle(db)["_meta"]


def test_abolition_handles_land_derived_regular_assessment(game):
    """正赋应征=None（亩额派生）时罢/复：基线存 None，复征回 None 而非 0。"""
    db, state = _at(game, 1627, 10, 1)
    fiscal = json.loads(
        str(db.conn.execute("SELECT fiscal FROM regions WHERE id = 'shaanxi'").fetchone()["fiscal"])
    )
    fiscal["settle"]["p"]["正赋应征"] = None
    db.conn.execute(
        "UPDATE regions SET fiscal = ? WHERE id = 'shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    db.conn.commit()

    _abolish(db, "田赋", 1)
    apply_historical_fiscal_rates(state, db)

    during = _settle(db)
    assert during["p"]["正赋应征"] == 0.0
    assert "正赋应征基线" in during["_meta"]
    assert during["_meta"]["正赋应征基线"] is None

    db, state = _at(game, 1628, 1, 2)
    _restore_catalog(db, "田赋", 2, value=68)
    apply_historical_fiscal_rates(state, db)

    restored = _settle(db)
    assert restored["p"]["正赋应征"] is None  # 回亩额派生，不是回 0
    assert "正赋应征基线" not in restored["_meta"]


# ── 票面「怎么验」：过月核省税、起运与国库实账 ────────────────────────────

def test_abolition_moves_real_persisted_treasury_ledger(game):
    """真实过月落账：罢征后国库**持久化流水**真回落（不只核 settle_tick 纯函数）。

    走 `apply_fixed_period_flows` 真落 economy_ledger，断言新档（substrate_hub）下
    省级正赋＋三饷经「月省级起运入京」入国库的流水真随罢征塌陷、复征后重新入账——
    写入／读取／恢复闭环（ship-pre DoD）。开局初始账册按 turn 排除，只看月度流水。
    """
    from ming_sim.flows import apply_fixed_period_flows

    def month_remittance(db, turn):
        row = db.conn.execute(
            "SELECT COALESCE(SUM(delta), 0) AS total FROM economy_ledger "
            "WHERE account = '国库' AND purpose IS NULL AND turn = ? "
            "AND reason LIKE '%起运入京%'",
            (turn,),
        ).fetchone()
        return float(row["total"] or 0)

    def settle_for_turn(db, turn):
        apply_historical_fiscal_rates(state, db)
        db.save_state(state)
        apply_fixed_period_flows(db, state)
        return month_remittance(db, turn)

    db, state = _at(game, 1627, 10, 1)
    baseline = settle_for_turn(db, 1)
    assert baseline > 0, "未罢时起运入京应有流水"

    _abolish(db, "辽饷", 2)
    _abolish(db, "田赋", 2)
    db, state = _at(game, 1627, 11, 2)
    abolished = settle_for_turn(db, 2)
    assert abolished == 0.0, "双罢后国库不应再有起运入账"

    # 恢复：真重立写口 + 复征 → 国库重新入账（且不重复：一条月链只记一次）。
    _restore_catalog(db, "田赋", 3, value=68)
    _restore_catalog(db, "辽饷", 3, value=43)
    db, state = _at(game, 1627, 12, 3)
    restored = settle_for_turn(db, 3)
    assert restored > 0, "复征后国库应重新入账"
    assert restored == pytest.approx(baseline, rel=0.2)
