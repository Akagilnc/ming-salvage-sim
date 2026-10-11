#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#653 / ADR 0090 偿还序 override ＋ Due 折发系数＋阶级怨气喂判。

票面（冻结票面含 r1–r4 修正案）验收表 golden ①–⑦ ＋ r4 canonical region goldens
＋ F2 六源纯投影 TSV 断言 ＋ F3 综合归因输入 / 零新增调用断言。
"""
from __future__ import annotations

import copy
import json

import pytest

from ming_sim.fiscal_tick import settle_tick
from ming_sim.pay_order import PayOrderKeyError, restore_pay_order_override, materialize_pay_order_decree

def _override_dossier(db, state, entries, *, text="偿还序/折发旨") -> int:
    """成案一道 pay_order_override 案卷（F1.2：旨意不是面板、每道旨一张案卷）。"""
    return db.create_decree_dossier(
        state,
        action_type="pay_order_override",
        decree_text=text,
        target_kind="fiscal_config",
        target_id="pay_order",
        payload={"entries": entries},
    )

# ── 共用最小盘面：省内池不足，四科目 Due 齐备 ──
def _board(gross: float = 0.0):
    st = {
        "省库库银": 0.0, "C_地方截留": 0.0, "C_中饱": 0.0, "C_漂没": 0.0, "C_eff损耗": 0.0,
        "民欠旧赋": 0.0, "军饷欠": 20.0, "官俸欠": 0.0, "宗禄欠": 0.0,
        "官民田": 100.0, "隐田": 50.0,
    }
    p = {
        "正赋应征": 8.0, "三饷应征": 2.0, "火耗率": 0.1, "逋赋率": 0.0,
        "起运定额": 0.0, "漂没率": 0.0, "中饱率": 0.0, "拨付gross": gross,
        "Due": {"军饷": 18.0, "官俸": 3.0, "宗禄": 4.07, "赈济": 1.0},
    }
    return st, p

# ═══════════════ r3/r4 键形白名单与值域 ═══════════════

@pytest.mark.parametrize("key", [
    "due_priority_军饷",
    "due_priority_官俸@shaanxi",
    "arrears_priority_宗禄欠@shaanxi",
    "due_haircut_bp_军饷",
    "due_haircut_bp_军饷@shaanxi",
    "due_haircut_bp_军饷#province",
    "due_haircut_bp_军饷@shaanxi#province",
    "due_haircut_bp_军饷@shaanxi#central",
    "due_haircut_bp_宗禄@shaanxi",
])
def test_override_key_legal_shapes(game, key):
    db, state, _ = game
    value = 5000 if key.startswith("due_haircut_bp_") else 10
    did = _override_dossier(db, state, [{"key": key, "value": value}])
    db.apply_dossier_promulgation(state, did, "promulgated")
    assert db.fiscal_config.values()[key] == value


def test_origin_ref_must_be_dossier_provenance(game):
    db, _state, _content = game
    with pytest.raises(ValueError):
        materialize_pay_order_decree(
            db, turn=1,
            entries=[{"key": "due_priority_军饷", "value": 40}],
            origin_ref="随手写的", commit=True,
        )

# ═══════════════ r3/r4 读取优先级全序 goldens ═══════════════

@pytest.mark.parametrize("turn,expected", [(12, 10), (13, 16)])
def test_r4_golden1_region_source_specificity_wins(game, turn, expected):
    """地方优先和到期回落由真实省账结算后的各军欠饷证明，省键不改中央应发。"""
    db, state, _ = game
    entries = [
        {"key": "due_haircut_bp_军饷@shaanxi#province", "value": 6000, "until_turn": 12},
        {"key": "due_haircut_bp_军饷#province", "value": 9000},
    ]
    did = _override_dossier(db, state, entries)
    db.apply_dossier_promulgation(state, did, "promulgated")
    db.conn.execute("UPDATE armies SET manpower=0, province_pay_arrears=0, central_pay_arrears=0")
    for army, region in [("guanning", "shaanxi"), ("jingying", "henan")]:
        db.conn.execute(
            "UPDATE armies SET manpower=10000,salary_rate=18,province_pay_share=1,"
            "central_pay_share=0,pay_source_region=?,self_funded_pay=0,is_tusi=0 WHERE id=?",
            (region, army),
        )
        st, p = _board()
        p.update({"正赋应征": 0, "三饷应征": 0})
        db.regions.update(region, {"fiscal": json.dumps({"settle": {"st": st, "p": p}})})
    state.turn = turn
    db.reign.save_game_state(state)
    db.conn.commit()
    db.settle_ming_province_substrate_ticks()
    assert db.conn.execute("SELECT province_pay_arrears FROM armies WHERE id='guanning'").fetchone()[0] == expected
    assert db.conn.execute("SELECT province_pay_arrears FROM armies WHERE id='jingying'").fetchone()[0] == 16
    assert db.fiscal_config.values()["due_haircut_bp_军饷@shaanxi#province_until_turn"] == 12


def test_priority_tie_breaks_on_default_baseline_stable(game):
    """同优先级仍先付军饷：真实省账无余银付宗禄。"""
    db, state, _ = game
    did = _override_dossier(db, state, [{"key": "due_priority_宗禄", "value": 10}])
    db.apply_dossier_promulgation(state, did, "promulgated")
    db.conn.execute("UPDATE armies SET manpower=0,province_pay_arrears=0,central_pay_arrears=0")
    db.conn.execute(
        "UPDATE armies SET manpower=10000,salary_rate=18,province_pay_share=1,"
        "central_pay_share=0,pay_source_region='shaanxi',self_funded_pay=0,is_tusi=0 WHERE id='guanning'"
    )
    st, p = _board()
    db.regions.update("shaanxi", {"fiscal": json.dumps({"settle": {"st": st, "p": p}})})
    db.conn.commit()
    db.settle_ming_province_substrate_ticks()
    assert db.conn.execute("SELECT province_pay_arrears FROM armies WHERE id='guanning'").fetchone()[0] == pytest.approx(8)
    stored = json.loads(db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()[0])["settle"]["st"]
    assert stored["宗禄欠"] == pytest.approx(4.07)


# ═══════════════ F1.6 验收表 golden ①–⑦ ═══════════════

def test_golden1_pay_order_reversal_breakdown_tsv():
    """①「边饷居末、官俸优先」：省内池不足时军饷先欠、官俸足付；实付分账可 TSV 断言。"""
    st, p = _board(gross=0.0)  # 省内可支＝实征 10，祖制序下全被军饷吃光
    base = settle_tick(copy.deepcopy(st), copy.deepcopy(p), [])
    assert base.breakdown["实付分账"]["军饷"] == pytest.approx(10.0)
    assert base.breakdown["NewDebt"]["军饷欠"] == pytest.approx(8.0)
    assert base.breakdown["NewDebt"]["官俸欠"] == pytest.approx(3.0)

    p2 = dict(p)
    p2["due_order"] = ["官俸", "宗禄", "赈济", "军饷"]
    res = settle_tick(st, p2, [])
    assert res.breakdown["NewDebt"]["军饷欠"] == pytest.approx(16.07)
    assert res.breakdown["NewDebt"]["官俸欠"] == 0.0
    assert res.new_st["军饷欠"] == pytest.approx(36.07)  # 旧欠20 + 新欠16.07

def test_golden2_haircut_half_is_exemption_not_debt():
    """②「宗禄折半」：floor(Due×bp/10000)；折掉部分不入宗禄欠；NewDebt 只含折后未付。
    r2 golden：Due=101、bp=5000 → 应得 50、免除 51。"""
    st, p = _board(gross=50.0)  # 省内可支＝10+50=60
    p["Due"] = {"军饷": 18.0, "官俸": 3.0, "宗禄": 101.0, "赈济": 1.0}
    p["due_haircut_bp"] = {"宗禄": 5000}
    res = settle_tick(st, p, [])
    assert res.breakdown["haircut_宗禄"] == pytest.approx(51.0)   # 折发=免除
    # 池 60：军饷18+官俸3+宗禄应得50+赈济1=72>60 → 军饷18/官俸3/宗禄39/赈济0
    assert res.breakdown["实付分账"]["宗禄"] == pytest.approx(39.0)
    assert res.new_st["宗禄欠"] == pytest.approx(11.0)  # 只含折后未付（50−39）

def test_golden3_arrears_waterfall_reversal():
    """③「旧欠先偿宗禄」：surplus waterfall 先还宗禄欠、再军饷欠。"""
    st, p = _board(gross=20.0)  # 省内可支30；Due 合计26.07 → surplus≈3.93
    st["宗禄欠"] = 7.0
    p2 = dict(p)
    p2["arrears_order"] = ["宗禄欠", "官俸欠", "军饷欠"]
    res = settle_tick(st, p2, [])
    assert res.breakdown["Repaid"]["宗禄欠"] == pytest.approx(3.93)
    assert res.breakdown["Repaid"]["军饷欠"] == 0.0
    assert res.new_st["宗禄欠"] == pytest.approx(3.07)
    # 对照：默认序下同样余额全还军饷欠
    res_def = settle_tick(copy.deepcopy(st), copy.deepcopy(p), [])
    assert res_def.breakdown["Repaid"]["军饷欠"] == pytest.approx(3.93)
    assert res_def.breakdown["Repaid"]["宗禄欠"] == 0.0


# ═══════════════ 桥集成：结算按新序/系数付账 ═══════════════


# ═══════════════ settle_tick 序参/折发参验形 fail-loud ═══════════════

@pytest.mark.parametrize("bad", [
    ["军饷", "官俸", "宗禄"],
    ["军饷", "官俸", "宗禄", "赈济", "军饷"],
    ["军饷", "官俸", "官俸", "赈济"],
    "军饷,官俸,宗禄,赈济",
    [["军饷"], "官俸", "宗禄", "赈济"],  # unhashable 元素不得泄漏 TypeError
])
def test_due_order_bad_shapes_raise(bad):
    st, p = _board()
    p["due_order"] = bad
    with pytest.raises(ValueError):
        settle_tick(st, p, [])

def test_haircut_param_bad_values_raise():
    st, p = _board()
    p["due_haircut_bp"] = {"宗禄": 0}
    with pytest.raises(ValueError):
        settle_tick(st, p, [])
    p["due_haircut_bp"] = {"宗禄": 10001}
    with pytest.raises(ValueError):
        settle_tick(st, p, [])
    p["due_haircut_bp"] = {"宗禄": 5000.0}
    with pytest.raises(ValueError):
        settle_tick(st, p, [])
    p["due_haircut_bp"] = {"土司": 5000}
    with pytest.raises(ValueError):
        settle_tick(st, p, [])

# ═══════════════ F2 六源纯投影 ═══════════════


# ═══════════════ F3 LLM 综合归因边界 ═══════════════

def test_apply_score_extraction_accepts_llm_direction_with_fiscal_loss(game):
    """F3.2：单一财政受损事实在案时，LLM 综合判断的正向 satisfaction 原样接收。"""
    from ming_sim.issues import apply_score_extraction

    db, state, _content = game
    db.conn.execute(
        "UPDATE armies SET province_pay_arrears = 12.0 WHERE id = 'shaanxi_army'"
    )
    db.conn.execute("UPDATE classes SET satisfaction=50 WHERE name='军户' AND region_id=''")
    db.conn.commit()
    applied = apply_score_extraction(
        db, state, {"class_delta": {"军户": {"satisfaction": 9}}}
    )
    assert applied["class_delta"]["军户"]["satisfaction"] == 9
    assert applied["class_delta_rejections"] == []

    assert db.conn.execute(
        "SELECT satisfaction FROM classes WHERE name='军户' AND region_id=''",
    ).fetchone()["satisfaction"] == 59

# ═══════════════ F1 颁布生命周期 E2E（ADR 0055 判后物化缝）═══════════════


def test_staging_rejects_illegal_entries_fail_loud(game):
    """成案点先验：非法键形/幻影 region 收夜即响亮拒，不入案卷。"""
    db, state, _content = game
    bad_entries = [
        [{"key": key, "value": 10}] for key in [
            "due_priority_军饷#province", "arrears_priority_军饷欠#central",
            "due_haircut_bp_官俸#province", "due_haircut_bp_赈济@shaanxi#central",
            "due_priority_官军饷", "due_haircut_bp_盐课", "pay_order_军饷",
            "due_priority_@shaanxi", "due_haircut_bp_军饷@shaanxi#",
            "due_priority_盐课", "due_haircut_bp_军饷@SX#province",
        ]
    ] + [
        [{"key": "due_haircut_bp_宗禄", "value": value}]
        for value in [0, -1, 10001, 20000, "5000", True, 5000.0, None]
    ] + [
        [{"key": "due_priority_军饷", "value": value}] for value in ["10", 1.5]
    ] + [[], [
        {"key": "due_haircut_bp_军饷@shaanxi#province", "value": 8000},
        {"key": "due_haircut_bp_军饷@SX#province", "value": 9000},
    ]]
    for entries in bad_entries:
        with pytest.raises(ValueError):
            _override_dossier(db, state, entries)
    assert db.conn.execute("SELECT COUNT(*) FROM decree_dossiers").fetchone()[0] == 0
    assert 'due_haircut_bp_军饷@shaanxi#province' not in db.fiscal_config.values()
    assert db.conn.execute('SELECT COUNT(*) FROM fiscal_config_changes').fetchone()[0] == 0

def test_materialize_requires_real_promulgated_dossier(game):
    """物化入口资格校验：案卷必须真实存在、action_type 合法且已过颁布门。"""
    db, state, _content = game
    with pytest.raises(ValueError):
        materialize_pay_order_decree(
            db, turn=1,
            entries=[{"key": "due_priority_军饷", "value": 40}],
            origin_ref="dossier:99999", commit=True,      # 案卷不存在
        )
    # 未过颁布门（proposed）的案卷禁物化
    did = _override_dossier(db, state, [{"key": "due_priority_军饷", "value": 40}])
    with pytest.raises(ValueError):
        materialize_pay_order_decree(
            db, turn=state.turn,
            entries=[{"key": "due_priority_军饷", "value": 40}],
            origin_ref=f"dossier:{did}", commit=True,
        )

# ═══════════════ 中央侧折发消费者（flows 读端）═══════════════

@pytest.mark.parametrize("entries, expected", [
    ([], (2.1, 9.0)),
    ([{"key": "due_haircut_bp_军饷@shaanxi#central", "value": 5000},
      {"key": "due_haircut_bp_军饷#central", "value": 6000}], (1.0, 5.0)),
    ([{"key": "due_haircut_bp_军饷#province", "value": 5000}], (2.1, 9.0)),
])
def test_central_due_haircut_consumer(game, entries, expected):
    """成案/颁布至实际财政落账：折后未付才成为中央新欠，省饷配置不影响中央。"""
    from ming_sim.flows import apply_fixed_period_flows

    db, state, _content = game
    before = dict(db.conn.execute(
        "SELECT id, central_pay_arrears FROM armies WHERE id IN ('shaanxi_army', 'jingying')"
    ).fetchall())
    if entries:
        did = _override_dossier(db, state, entries)
        db.apply_dossier_promulgation(state, did, "promulgated")
    state.metrics["国库"] = 0
    db.reign.save_game_state(state)
    apply_fixed_period_flows(db, state)
    after = dict(db.conn.execute(
        "SELECT id, central_pay_arrears FROM armies WHERE id IN ('shaanxi_army', 'jingying')"
    ).fetchall())
    for army_id, due in zip(("shaanxi_army", "jingying"), expected):
        assert after[army_id] - before[army_id] == pytest.approx(due)


def test_pure_central_zero_haircut_due_clears_shortfall_counter(game):
    """#651×#653：纯中央军合法折发后 Due floor=0 须归零连续缺口计数，且不自动还旧欠。"""
    from ming_sim.flows import apply_fixed_period_flows

    db, state, _content = game

    army = db.conn.execute(
        "SELECT id, manpower, salary_rate, owner_power, central_pay_share, "
        "province_pay_share, pay_source_region, central_pay_arrears, arrears "
        "FROM armies WHERE id = 'jingying'"
    ).fetchone()
    assert float(army["province_pay_share"] or 0) <= 0
    assert float(army["central_pay_share"] or 0) > 0
    old_central_arrears = float(army["central_pay_arrears"] or 0)
    assert old_central_arrears > 0
    old_arrears = float(army["arrears"] or 0)
    assert old_arrears > 0

    db.conn.execute(
        "UPDATE armies SET consecutive_pay_shortfall_months = 3 WHERE id = 'jingying'"
    )
    db.conn.commit()

    did = _override_dossier(
        db, state, [{"key": "due_haircut_bp_军饷#central", "value": 1}],
    )
    db.apply_dossier_promulgation(state, did, "promulgated")

    apply_fixed_period_flows(db, state)

    after = db.conn.execute(
        "SELECT consecutive_pay_shortfall_months, central_pay_arrears, arrears "
        "FROM armies WHERE id = 'jingying'"
    ).fetchone()
    assert int(after["consecutive_pay_shortfall_months"] or 0) == 0
    # 中央旧欠不因零 Due 月自动偿还（ADR 0023 D7③ / #653 边界）
    assert float(after["central_pay_arrears"] or 0) == pytest.approx(old_central_arrears)
    assert float(after["arrears"] or 0) == pytest.approx(old_arrears)


# ═══════════════ F2 投影真源修正 goldens（judge r2 class②）═══════════════

# ═══════════════ 拟旨 capture→成案（财政物化与下一次省 tick 分别由上方领域用例覆盖）═══


def _capture_override_decree(game, monkeypatch, text, entries):
    """真实手工拟诏 capture seam（mock LLM 抽取）→ 草案落库 → 结束边界成案 staging。
    全程禁手工 create_decree_dossier 旁路。"""
    import json as _json

    import ming_sim.cli_backend as cli_backend
    from ming_sim.session import GameSession

    db, state, content = game
    # #653 capture 合同与 extraction 同源：account/pay_order；属地写在 entries 键名。
    # 合入 #654 后 region 须显式 locality_scope=single，不得靠缺省暗升。
    response = {
        "拟旨意图": "拟旨",
        "动作类型": "pay_order_override",
        "目标类型": "account",
        "目标ID": "pay_order",
        "entries": entries,
    }

    def backend(prompt, *_a, **_k):
        return (_json.dumps(response, ensure_ascii=False), 1)

    monkeypatch.setattr(cli_backend, "_run_backend_for_config", backend)
    payload = cli_backend.capture_manual_directive_payload(
        text, None, db=db, content=content,
    )
    assert payload["dossier_action_type"] == "pay_order_override"
    assert payload["target_kind"] == "account"
    assert payload["entries"] == entries
    session = GameSession.__new__(GameSession)
    session.db = db
    session.state = state
    dv = session.add_directive(text, dossier_payload=payload)
    db.ensure_dossiers_for_draft_directives(state)
    dossier = db.dossiers.get_for_directive(dv.id)
    assert dossier is not None
    assert dossier["action_type"] == "pay_order_override"
    return int(dossier["id"])


# ═══════════════ F2.3（owner 拍板 r5）：官俸欠/宗禄欠当回合流量持久留痕 ═══════════════


@pytest.mark.parametrize("rejected", [False, True])
def test_rejected_revoke_does_not_restore_override(game, rejected):
    from dossier_test_helpers import rejected_verdict
    db, state, _content = game
    until = int(state.turn) + 2
    target = _override_dossier(db, state, [{'key': 'due_priority_军饷@shaanxi', 'value': 40, 'until_turn': until}])
    db.apply_dossier_promulgation(state, target, 'promulgated')
    revoke = db.create_decree_dossier(state, action_type='revoke_decree', decree_text='撤回前旨', target_kind='dossier', target_id=str(target), payload={'revoke_target_dossier_id': target})
    if rejected:
        db.apply_dossier_verdicts(state, [rejected_verdict(revoke)])
    before_cfg = dict(db.fiscal_config.values())
    with pytest.raises(PayOrderKeyError):
        restore_pay_order_override(db, turn=int(state.turn), target_dossier_id=target, revoke_dossier_id=revoke, reason='打回不得删 config')
    cfg = db.fiscal_config.values()
    assert cfg == before_cfg
    assert cfg["due_priority_军饷@shaanxi"] == 40
    assert cfg["due_priority_军饷@shaanxi_until_turn"] == until
    origin = f'dossier:{revoke}'
    assert db.conn.execute('SELECT COUNT(*) c FROM fiscal_config_tombstones WHERE origin_ref=?', (origin,)).fetchone()['c'] == 0
    assert db.conn.execute('SELECT COUNT(*) c FROM fiscal_config_changes WHERE origin_ref=?', (origin,)).fetchone()['c'] == 0


def test_revoke_later_same_dim_decree_not_stomped(game):
    db, state, _content = game
    first = _override_dossier(db, state, [{'key': 'due_priority_军饷@shaanxi', 'value': 40}], text='前旨边饷居末')
    db.apply_dossier_promulgation(state, first, 'promulgated')
    second = _override_dossier(db, state, [{'key': 'due_priority_军饷@shaanxi', 'value': 5}], text='后旨边饷最前')
    db.apply_dossier_promulgation(state, second, 'promulgated')
    assert db.fiscal_config.values()['due_priority_军饷@shaanxi'] == 5
    revoke = db.create_decree_dossier(state, action_type='revoke_decree', decree_text='撤回前旨', target_kind='dossier', target_id=str(first), payload={'revoke_target_dossier_id': first})
    db.apply_dossier_promulgation(state, revoke, 'promulgated')
    cfg = db.fiscal_config.values()
    assert cfg['due_priority_军饷@shaanxi'] == 5
    row = db.conn.execute("SELECT origin_ref FROM fiscal_config WHERE key='due_priority_军饷@shaanxi'").fetchone()
    assert row['origin_ref'] == f'dossier:{second}'
    stomps = db.conn.execute("SELECT 1 FROM fiscal_config_changes WHERE origin_ref=? AND key='due_priority_军饷@shaanxi'", (f'dossier:{revoke}',)).fetchone()
    assert stomps is None


def test_lifecycle_rejected_decree_zero_config_write(game, monkeypatch):
    from dossier_test_helpers import rejected_verdict
    db, state, _content = game
    before_cfg = db.fiscal_config.values()
    before_rows = db.conn.execute('SELECT COUNT(*) c FROM fiscal_config_changes').fetchone()['c']
    did = _capture_override_decree(game, monkeypatch, '今岁边饷居末', [{'key': 'due_priority_军饷', 'value': 40}])
    assert db.fiscal_config.values() == before_cfg
    assert db.conn.execute('SELECT COUNT(*) c FROM fiscal_config_changes').fetchone()['c'] == before_rows
    assert db.dossiers.get(did)["status"] == "proposed"
    db.apply_dossier_verdicts(state, [rejected_verdict(did)])
    assert db.fiscal_config.values() == before_cfg
    assert db.conn.execute('SELECT COUNT(*) c FROM fiscal_config_changes').fetchone()['c'] == before_rows
    assert db.dossiers.get(did)['status'] == 'proposed'


def test_stale_until_cleared_by_permanent_overwrite(game):
    """F1.4：有期限旨被后来的永久旨覆盖 → 遗留 _until_turn 清除，新旨不再到期。"""
    db, state, _content = game
    turn = int(state.turn)
    d1 = _override_dossier(db, state, [{'key': 'due_priority_军饷', 'value': 40, 'until_turn': turn + 1}])
    db.apply_dossier_promulgation(state, d1, 'promulgated')
    assert 'due_priority_军饷_until_turn' in db.fiscal_config.values()
    d2 = _override_dossier(db, state, [{'key': 'due_priority_军饷', 'value': 30}])
    db.apply_dossier_promulgation(state, d2, 'promulgated')
    cfg = db.fiscal_config.values()
    assert 'due_priority_军饷_until_turn' not in cfg
    assert cfg['due_priority_军饷'] == 30
    tomb = db.conn.execute("SELECT key, value, origin_ref FROM fiscal_config_tombstones WHERE key='due_priority_军饷_until_turn' ORDER BY id DESC LIMIT 1").fetchone()
    assert tomb is not None and tomb['origin_ref'] == f'dossier:{d2}'


def test_revoke_provincial_falls_back_to_nationwide(game):
    """Codex-11/revoke_shape_exit②：全国+省域并存时撤省域后该省回落全国键。"""
    db, state, _content = game
    nation = _override_dossier(db, state, [{'key': 'due_priority_军饷', 'value': 35}], text='全国边饷居后')
    db.apply_dossier_promulgation(state, nation, 'promulgated')
    local = _override_dossier(db, state, [{'key': 'due_priority_军饷@shaanxi', 'value': 50}], text='陕西边饷居末')
    db.apply_dossier_promulgation(state, local, 'promulgated')
    revoke = db.create_decree_dossier(state, action_type='revoke_decree', decree_text='撤陕西旨', target_kind='dossier', target_id=str(local), payload={'revoke_target_dossier_id': local})
    db.apply_dossier_promulgation(state, revoke, 'promulgated')
    cfg = db.fiscal_config.values()
    assert 'due_priority_军饷@shaanxi' not in cfg
    assert cfg['due_priority_军饷'] == 35
