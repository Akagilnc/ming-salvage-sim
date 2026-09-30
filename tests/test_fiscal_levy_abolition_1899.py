"""#1899 新档罢赋罢饷作用于现役财政真源。

刀口：`issues._apply_fiscal_levy_targets` 的 set-to-target。此前罢辽饷／罢田赋只改
目录字段（`fiscal_config` 目录行 + `regions.tax_per_turn` / `fiscal.liao_xiang`），
现役 tick 读的 `settle.p` 不动，下月财政照旧征。本票让最后有效批语（罢/复）进
`settle.p`：辽饷分量归零、正赋应征归零；罢后又在历史升率节点批「准」= 重新开征
按新率征，不另要恢复旨；未罢者驳升率仍九厘基线。

**入口纪律**（#1899 R5）：一律走真实生产入口，不手工 INSERT 目录／决定账、不调
applier 私有写口、不手补终态——
  · 罢 → `dispatch_declaration`（applier 真通道，走 delta 契约的 `fiscal_removes`
    删项 / `fiscal_changes` 调零两条真写口，origin 用契约收的「盘面自发」）；
  · 批红 → `record_event_decision_choice`（案头真写口，只写 choice；**晋级与终态
    交由 `pre_settle` 的真实 pass**，不手工 mark_event_triggered 绕过晋级）；
  · 消费 → `pre_settle`（月链前半段，内含 `apply_historical_fiscal_rates`），
    与生产同一入口、同一事务形状。
实账断言落在**持久化的 economy_ledger**（过月 `apply_fixed_period_flows` 真落库后
的国库流水），不只核 `settle_tick` 的纯函数分解。断言在外部可见的结构化结果上
（`regions.fiscal.settle.p` / `economy_ledger` / `event_triggers`），不盯显示名与
reason 措辞。
"""
import json
import math

import pytest

from ming_sim.declaration_dispatch import dispatch_declaration
from ming_sim import decree as decree_mod
from ming_sim.issues import apply_historical_fiscal_rates

RISE_EVENT_ID = "liao_levy_rise_1631"


def _settle(db, region_id="shaanxi"):
    row = db.conn.execute(
        "SELECT fiscal FROM regions WHERE id = ?", (region_id,),
    ).fetchone()
    return json.loads(str(row["fiscal"] or "{}"))["settle"]


def _at(game, year, period, turn):
    db, state, content = game
    from ming_sim import issues as issues_mod
    issues_mod.bind_content(content)
    state.year, state.period, state.turn = year, period, turn
    db.save_state(state)
    return db, state


def _goto(state, turn):
    """把 state 推进到指定回合。写口（罢/批红）都以 state.turn 记账，不推进则
    所有步骤都记在同一回合上，测的就不是「跨回合先后」而是「同 turn」了。"""
    state.turn = int(turn)
    return state


def _abolish(db, state, turn, stem="辽饷", *, zeroing=False):
    """真实 applier 通道落罢：删项（`fiscal_removes`）或调零（`fiscal_changes`）。

    两条都是生产上罢赋罢饷的真写口，origin 用 delta 契约收的「盘面自发」。
    """
    _goto(state, turn)
    if zeroing:
        item = {"key": f"{stem}_rate", "delta": -100,
                "origin_ref": "盘面自发", "reason": "罢征"}
        field = "fiscal_changes"
    else:
        item = {"key": f"{stem}_rate", "origin_ref": "盘面自发", "reason": "罢征"}
        field = "fiscal_removes"
    dispatch_declaration(db, state, {"effects": [{field: [item]}]})
    db.conn.commit()


def _emperor_rates_rise(db, state, turn, label="已准"):
    """真实批红写口：只写 choice（pending）。晋级与消费交给 `pre_settle`。"""
    _goto(state, turn)
    db.record_event_decision_choice(
        state, RISE_EVENT_ID, {"label": label}, source="hitl_decision", commit=False,
    )
    db.conn.commit()


def _settle_month(game, turn):
    """真实消费入口：`pre_settle`（月链前半段）。"""
    db, state, content = game
    _goto(state, turn)
    state.turn_phase = ""
    decree_mod.pre_settle(state, db, content=content)
    db.conn.commit()
    return db, state


def _all_regions_settle_p(db):
    out = {}
    for row in db.conn.execute("SELECT id, fiscal FROM regions ORDER BY id").fetchall():
        fiscal = json.loads(str(row["fiscal"] or "{}"))
        settle = fiscal.get("settle")
        if isinstance(settle, dict) and isinstance(settle.get("p"), dict):
            out[str(row["id"])] = settle["p"]
    return out


def _rate_row(db, key):
    return db.conn.execute(
        "SELECT value FROM fiscal_config WHERE key = ?", (key,),
    ).fetchone()


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

    _abolish(db, state, 1)
    apply_historical_fiscal_rates(state, db)

    after = _settle(db)
    assert after["p"]["三饷应征"] == 0.0
    assert after["p"]["起运定额"] == pytest.approx(base_transport)
    # 基线不被罢抹掉（P1：复征靠它，逐月重算不漂移）。
    assert after["_meta"]["辽饷九厘基线"] == pytest.approx(liao_seed)


def test_abolished_liao_levy_by_zeroing_rate_stops_collection(game):
    """调零落法的罢征同样归零（真 applier 通道，`辽饷_rate`→0 而 base 留着 seed 值）。

    罢走调零时同组 `辽饷_base` 仍是 43，「组内任一键为正 ⇒ 不算罢」会把这道有效
    罢征整个否决，下月照旧征。dynamic 赋饷实收 ∝ base×rate，rate 归零即实收恒 0，
    罢成立。
    """
    db, state = _at(game, 1631, 1, 10)
    _abolish(db, state, 10, zeroing=True)
    assert _rate_row(db, "辽饷_rate")["value"] == 0
    assert _rate_row(db, "辽饷_base")["value"] > 0, "base 残值确实还在"

    apply_historical_fiscal_rates(state, db)

    assert _settle(db)["p"]["三饷应征"] == 0.0
    # 全部已 seed settle 的省都归零（不止抽查一省）。
    for region_id, p in _all_regions_settle_p(db).items():
        assert p["三饷应征"] == 0.0, region_id


def test_abolished_liao_levy_rejected_rise_stays_stopped(game):
    """罢辽饷后在历史升率节点驳回 → 仍不征（驳不自行恢复）。"""
    db, state = _at(game, 1631, 1, 10)
    _abolish(db, state, 10)
    _emperor_rates_rise(db, state, 12, label="已驳")
    db, state = _settle_month(game, 13)

    assert _settle(db)["p"]["三饷应征"] == 0.0


def test_rejected_rise_without_abolition_keeps_nine_li_baseline(game):
    """未罢辽饷而驳升率 → 仍用九厘基线征（不误停征）。"""
    db, state = _at(game, 1631, 1, 10)
    seed = _settle(db)["p"]["三饷应征"]
    _emperor_rates_rise(db, state, 12, label="已驳")
    db, state = _settle_month(game, 13)

    assert _settle(db)["p"]["三饷应征"] == pytest.approx(seed)


# ── 复征贯通全部两种罢征写口（R1）─────────────────────────────────────────

@pytest.mark.parametrize("zeroing", [False, True], ids=["abolish_by_removal", "abolish_by_zeroing"])
def test_rise_approval_reinstates_through_every_abolition_write_port(game, zeroing):
    """R1：罢（**两种真写口**）→ 后批「准」= 重新开征，按新率征，不另要恢复旨。

    罢征有两条真写口、目录形状不同：删项（整组不在册）与调零（行在册、键值归零）。
    复征此前只走 `create_fiscal_item`，它对「行仍在册」返回 None —— 调零落法的罢征
    于是永不复征，这道「准」被静默丢弃、下月照旧征。本例钉死**两口都通**，且复征
    后 rate 回到该键自己的 seed 值（100，不是同 stem 的 base 值 43）。
    """
    db, state = _at(game, 1631, 1, 10)
    _abolish(db, state, 10, zeroing=zeroing)
    db, state = _settle_month(game, 11)
    assert _settle(db)["p"]["三饷应征"] == 0.0, "罢后应先停征"

    db, state = _at(game, 1631, 6, 15)
    _emperor_rates_rise(db, state, 15)
    db, state = _settle_month(game, 16)

    reopened = _settle(db)
    assert reopened["p"]["三饷应征"] == pytest.approx(
        reopened["_meta"]["辽饷九厘基线"] * 4.0 / 3.0
    ), "复征后按新率（一分二厘）征"
    assert _rate_row(db, "辽饷_rate")["value"] == 100


# ── 批语先后：真实月链顺序，非固定优先（R2）───────────────────────────────

def test_same_turn_abolition_then_approval_reinstates(game):
    """R2：同 turn 先罢后准 → **复征**（票面「以您最后一次的批语为准」）。

    月链真实顺序是 pre_settle → 逐旨／世界段 → 批红（docs/SETTLEMENT_FLOW.md
    第 1–2 段）：罢的目录写口在同一 turn 的**更前**一段落，批红在其后，故同 turn
    内罢先准后，「准」才是更后出的那道批语。此前代码写 `>=` 把同 turn 判给罢，
    是与月链顺序相反的假规则——亲跑同 turn 先罢后准，下一 tick 首次应征仍为 0。
    """
    db, state = _at(game, 1631, 1, 15)
    _abolish(db, state, 15)
    _emperor_rates_rise(db, state, 15)
    db, state = _settle_month(game, 16)

    assert _settle(db)["p"]["三饷应征"] > 0, "同 turn 更后出的「准」应复征"


def test_later_turn_abolition_after_approval_keeps_abolition(game):
    """准在前、罢辽饷在**更晚的回合** → 最后批语是罢，下月不征（罢饷真正生效）。

    这是评审指出的缺腿：布尔实现会把「准」当成永久复征，令罢在此时序下失效。
    """
    db, state = _at(game, 1631, 1, 10)
    _emperor_rates_rise(db, state, 10)
    db, state = _settle_month(game, 11)
    assert _settle(db)["p"]["三饷应征"] > 0

    db, state = _at(game, 1631, 4, 13)
    _abolish(db, state, 13)
    db, state = _settle_month(game, 14)

    assert _settle(db)["p"]["三饷应征"] == 0.0


# ── 首次消费与再次进入一致，不重放旧准（R3）───────────────────────────────

def test_first_consumption_matches_reentry_after_abolition_then_approval(game):
    """R3：罢→准后，**首次消费**与**再次进入**结果必须一致（幂等 set-to-target）。

    事件的待落行晋级为 triggered 时曾被改写成晋级回合，于是同一道「准」在首次消费
    与隔月重算读出两个不同的 turn：首次判「不是最后一道批语」不复征，隔月又判
    「是」凭空复征——重入不一致 + 重放旧准。
    """
    db, state = _at(game, 1631, 1, 15)
    _abolish(db, state, 15)
    _emperor_rates_rise(db, state, 15)

    db, state = _settle_month(game, 16)
    first = _settle(db)["p"]["三饷应征"]
    db, state = _settle_month(game, 17)
    second = _settle(db)["p"]["三饷应征"]
    db, state = _settle_month(game, 18)
    third = _settle(db)["p"]["三饷应征"]

    assert first > 0, "罢→准后首次消费即应复征"
    assert first == second == third, "重入不得改判（更不能凭空复征）"


def test_approval_then_later_abolition_is_not_resurrected_by_reentry(game):
    """R3 反向：同 turn 准→后罢，下月与隔月都保持不征（旧准不重放）。"""
    db, state = _at(game, 1631, 1, 15)
    _emperor_rates_rise(db, state, 15)
    db, state = _settle_month(game, 16)

    _abolish(db, state, 16)
    db, state = _settle_month(game, 17)
    assert _settle(db)["p"]["三饷应征"] == 0.0
    db, state = _settle_month(game, 18)
    assert _settle(db)["p"]["三饷应征"] == 0.0, "隔月重算不得被旧准顶掉后出的罢"


def test_reabolition_after_reinstatement_keeps_both_write_ports_working(game):
    """罢→准→再罢：后续决定的**真写口**都通（不再 missing_ref），且真落罢。"""
    db, state = _at(game, 1631, 1, 10)
    _abolish(db, state, 10)
    db, state = _settle_month(game, 11)
    assert _settle(db)["p"]["三饷应征"] == 0.0

    db, state = _at(game, 1631, 6, 15)
    _emperor_rates_rise(db, state, 15)
    db, state = _settle_month(game, 16)
    assert _settle(db)["p"]["三饷应征"] > 0, "准后应恢复征收"

    # 再罢：真 applier 通道必须有行可裁撤（复征已把目录恢复）。
    _abolish(db, state, 20)
    db, state = _settle_month(game, 21)
    assert _settle(db)["p"]["三饷应征"] == 0.0
    # 持续罢征不被下一月的重算抹掉。
    db, state = _settle_month(game, 22)
    assert _settle(db)["p"]["三饷应征"] == 0.0


# ── 自动结局残值不冒充皇帝批准（R4）───────────────────────────────────────

def test_emperor_rejection_overrides_automatic_baseline_stub(game):
    """R4：自动基线桩先落「已准」，皇帝随后亲批「已驳」→ 真批语接管，不复征。

    桩落的只是史实默认值，不是皇帝的裁断。此前终态 reason 一律保留桩残值，于是
    事件账同时留下 terminal_reason=已准 与 choice.label=已驳，残值冒充批准，
    消费者照残值重新开征一道已罢的辽饷。断言落在事件账这一外部可见结构上。
    """
    db, state = _at(game, 1631, 1, 10)
    db.mark_event_triggered(
        state, RISE_EVENT_ID, source="fiscal_levy_shadow",
        terminal_reason="已准", commit=False,
    )
    db.conn.commit()

    _abolish(db, state, 12)
    db, state = _settle_month(game, 13)
    assert _settle(db)["p"]["三饷应征"] == 0.0

    _emperor_rates_rise(db, state, 14, label="已驳")
    row = db.conn.execute(
        "SELECT terminal_reason, choice_json FROM event_triggers WHERE event_id = ?",
        (RISE_EVENT_ID,),
    ).fetchone()
    assert json.loads(row["choice_json"])["label"] == "已驳"

    db, state = _settle_month(game, 15)

    assert _settle(db)["p"]["三饷应征"] == 0.0, "驳回后不得凭空复征"
    row = db.conn.execute(
        "SELECT terminal_reason FROM event_triggers WHERE event_id = ?", (RISE_EVENT_ID,),
    ).fetchone()
    assert row["terminal_reason"] == "已驳", "桩残值不得冒充皇帝批准"


def test_automatic_stub_without_choice_does_not_reinstate(game):
    """纯自动桩（无 choice_json）不得被当成皇帝的复征决定。

    `run_fiscal_levy_pass` 有一条自动路径，会在没有请旨、没有 choice 的情况下按
    `default_terminal_reason` 把升率事件标成「已准」。若消费者拿它去重新开征一道
    已罢的辽饷，就等于「什么时候变成自动加了？」——凭空复征。
    """
    db, state = _at(game, 1631, 1, 10)
    _abolish(db, state, 10)
    db, state = _settle_month(game, 11)
    assert _settle(db)["p"]["三饷应征"] == 0.0

    db, state = _at(game, 1631, 6, 15)
    db.mark_event_triggered(
        state, RISE_EVENT_ID, source="fiscal_levy_shadow",
        terminal_reason="已准", commit=False,
    )
    db.conn.commit()
    row = db.conn.execute(
        "SELECT choice_json FROM event_triggers WHERE event_id = ?", (RISE_EVENT_ID,),
    ).fetchone()
    assert not str(row["choice_json"] or "").strip(), "本用例前提：桩无 choice"

    db, state = _settle_month(game, 16)

    assert _settle(db)["p"]["三饷应征"] == 0.0, "自动桩不得凭空复征"


# ── 罢田赋作用于现役真源 ────────────────────────────────────────────────

def test_abolished_tian_fu_zeroes_regular_assessment(game):
    """罢田赋 → 正赋应征归零；复征（真重立写口）→ 回原基线，不重复扣征。"""
    from ming_sim.flows import compute_budget_lines

    db, state = _at(game, 1627, 10, 1)
    before = _settle(db)["p"]["正赋应征"]
    assert before > 0

    _abolish(db, state, 1, stem="田赋")
    apply_historical_fiscal_rates(state, db)

    during = _settle(db)
    assert during["p"]["正赋应征"] == 0.0
    assert during["_meta"]["正赋应征基线"] == pytest.approx(before)

    # 复征 = 一道新批语（真重立写口），比罢晚 → 复征在位。
    db, state = _at(game, 1628, 1, 2)
    dispatch_declaration(db, state, {"effects": [{"fiscal_creates": [{
        "key": "田赋", "account": "国库", "direction": "income",
        "init_value": 68, "display": "田赋",
        "origin_ref": "盘面自发", "reason": "复征",
    }]}]})
    db.conn.commit()
    apply_historical_fiscal_rates(state, db)

    after = _settle(db)
    assert after["p"]["正赋应征"] == pytest.approx(before)
    assert "正赋应征基线" not in after["_meta"]

    # 复征同一税项**不叠加第二条收入**：目录行回 seed 声明的 dynamic 角色，
    # 不得成为中央 fixed 收入行被预算遍历再记一条（全局硬规 #12/#14 单一机制）。
    rows = db.conn.execute(
        "SELECT key, budget_role, account, direction FROM fiscal_config WHERE key LIKE '田赋%'"
    ).fetchall()
    assert rows, "复征应重立目录行"
    for r in rows:
        assert r["budget_role"] == "dynamic", dict(r)
        assert not str(r["account"] or ""), dict(r)
        assert not str(r["direction"] or ""), dict(r)

    budget = compute_budget_lines(db, state)
    for account in ("国库", "内库"):
        for item in budget[account]["income"]:
            assert not str(item["name"]).startswith("田赋"), f"重复收入行 {account}/{item['name']}"


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

    _abolish(db, state, 1, stem="田赋")
    apply_historical_fiscal_rates(state, db)

    during = _settle(db)
    assert during["p"]["正赋应征"] == 0.0
    assert during["_meta"]["正赋应征基线"] is None

    db, state = _at(game, 1628, 1, 2)
    dispatch_declaration(db, state, {"effects": [{"fiscal_creates": [{
        "key": "田赋", "account": "国库", "direction": "income",
        "init_value": 68, "display": "田赋",
        "origin_ref": "盘面自发", "reason": "复征",
    }]}]})
    db.conn.commit()
    apply_historical_fiscal_rates(state, db)

    restored = _settle(db)
    assert restored["p"]["正赋应征"] is None  # 回亩额派生，不是回 0
    assert "正赋应征基线" not in restored["_meta"]


def test_abolition_is_idempotent_across_repeated_months(game):
    """持续罢征不因逐月重算被抹掉、不重复扣征（幂等 set-to-target）。"""
    db, state = _at(game, 1627, 10, 1)
    _abolish(db, state, 1, stem="辽饷")
    _abolish(db, state, 1, stem="田赋")

    apply_historical_fiscal_rates(state, db)
    first = dict(_settle(db)["p"])
    db, state = _settle_month(game, 11)
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


# ── 票面「怎么验」：过月核省税、起运与国库实账 ────────────────────────────

def test_abolition_moves_real_persisted_treasury_ledger(game):
    """真实过月落账：罢征后国库**持久化流水**真回落（不只核 settle_tick 纯函数）。

    走 `pre_settle` + `apply_fixed_period_flows` 真落 economy_ledger，断言新档
    （substrate_hub）下省级正赋＋三饷经「月省级起运入京」入国库的流水真随罢征塌陷、
    复征后重新入账——写入／读取／恢复闭环（ship-pre DoD）。开局初始账册按 turn 排除，
    只看月度流水。
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

    def settle_for_turn(game, turn):
        db, state = _settle_month(game, turn)
        db.save_state(state)
        apply_fixed_period_flows(db, state)
        return month_remittance(db, turn)

    db, state = _at(game, 1627, 10, 1)
    baseline = settle_for_turn(game, 1)
    assert baseline > 0, "未罢时起运入京应有流水"

    _abolish(db, state, 2, stem="辽饷")
    _abolish(db, state, 2, stem="田赋")
    db, state = _at(game, 1627, 11, 2)
    abolished = settle_for_turn(game, 2)
    assert abolished == 0.0, "双罢后国库不应再有起运入账"

    # 恢复：真重立写口 + 复征 → 国库重新入账（且不重复：一条月链只记一次）。
    for stem, value in (("田赋", 68), ("辽饷", 43)):
        dispatch_declaration(db, state, {"effects": [{"fiscal_creates": [{
            "key": stem, "account": "国库", "direction": "income",
            "init_value": value, "display": stem,
            "origin_ref": "盘面自发", "reason": "复征",
        }]}]})
    db.conn.commit()
    db, state = _at(game, 1627, 12, 3)
    restored = settle_for_turn(game, 3)
    assert restored > 0, "复征后国库应重新入账"
    assert restored == pytest.approx(baseline, rel=0.2)