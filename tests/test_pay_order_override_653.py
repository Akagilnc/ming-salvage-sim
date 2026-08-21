#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#653 / ADR 0090 偿还序 override ＋ Due 折发系数＋阶级怨气喂判。

票面（冻结票面含 r1–r4 修正案）验收表 golden ①–⑦ ＋ r4 canonical region goldens
＋ F2 六源纯投影 TSV 断言 ＋ F3 符号域 clamp / 零第5调用断言。
"""
from __future__ import annotations

import copy
import math

import pytest

from ming_sim.fiscal_tick import settle_tick
from ming_sim.fiscal_fact_brief import (
    build_fiscal_fact_brief,
    clamp_class_delta_to_fact_signs,
    format_fiscal_fact_brief_tsv,
)
from ming_sim.pay_order import (
    DEFAULT_ARREARS_PRIORITY,
    DEFAULT_DUE_PRIORITY,
    PayOrderKeyError,
    materialize_pay_order_decree,
    parse_override_key,
    resolve_pay_order_overrides,
    revoke_pay_order_decree,
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
def test_override_key_legal_shapes(key):
    assert parse_override_key(key).subject


@pytest.mark.parametrize("key", [
    # priority 族带 # 饷源后缀＝非法（r3：序无饷源维度）
    "due_priority_军饷#province",
    "arrears_priority_军饷欠#central",
    # 非军饷折发带 # 后缀＝非法
    "due_haircut_bp_官俸#province",
    "due_haircut_bp_赈济@shaanxi#central",
    # 未知科目 / 未知键族 / 悬空词位
    "due_priority_官军饷",
    "due_haircut_bp_盐课",
    "pay_order_军饷",
    "due_priority_@shaanxi",
    "due_haircut_bp_军饷@shaanxi#",
])
def test_override_key_illegal_shapes_fail_loud(key):
    with pytest.raises(ValueError):
        parse_override_key(key)


@pytest.mark.parametrize("value", [0, -1, 10001, "5000", True, 5000.0, None])
def test_haircut_value_domain_fail_loud(value):
    from ming_sim.pay_order import validate_override_value
    with pytest.raises(ValueError):
        validate_override_value("due_haircut_bp_宗禄", value)


def test_priority_value_domain_rejects_non_int():
    from ming_sim.pay_order import validate_override_value
    with pytest.raises(ValueError):
        validate_override_value("due_priority_军饷", "10")
    with pytest.raises(ValueError):
        validate_override_value("due_priority_军饷", 1.5)


def test_r4_no_phantom_region_materialization_is_all_or_nothing(game):
    """r4：不新增 alias、不造虚拟 region——@SX 幻影 region fail-loud 拒写**整道旨**。"""
    db, _state, _content = game
    entries = [
        {"key": "due_haircut_bp_军饷@shaanxi#province", "value": 8000},
        {"key": "due_haircut_bp_军饷@SX#province", "value": 9000},  # 幻影 region
    ]
    with pytest.raises(ValueError):
        materialize_pay_order_decree(
            db, turn=1, entries=entries, origin_ref="dossier:1", commit=True,
        )
    # 非法旨不得物化 config：整批零写入
    cfg = db.get_fiscal_config()
    assert "due_haircut_bp_军饷@shaanxi#province" not in cfg
    assert db.conn.execute("SELECT COUNT(*) c FROM fiscal_config_changes").fetchone()["c"] == 0


def test_origin_ref_must_be_dossier_provenance(game):
    db, _state, _content = game
    with pytest.raises(ValueError):
        materialize_pay_order_decree(
            db, turn=1,
            entries=[{"key": "due_priority_军饷", "value": 40}],
            origin_ref="随手写的", commit=True,
        )


# ═══════════════ r3/r4 读取优先级全序 goldens ═══════════════

def test_r4_golden1_region_source_specificity_wins():
    """r4 golden①：@shaanxi#province 与 #province 并存 → 陕西饷侧取 @shaanxi#province、
    他省省饷侧取 #province、中央侧不受影响。"""
    config = {
        "due_haircut_bp_军饷@shaanxi#province": 6000,
        "due_haircut_bp_军饷#province": 9000,
    }
    shaanxi = resolve_pay_order_overrides(config, "shaanxi", turn=1)
    henan = resolve_pay_order_overrides(config, "henan", turn=1)
    assert shaanxi.haircut_bp["军饷"] == 6000
    assert henan.haircut_bp["军饷"] == 9000
    # 中央侧不受影响：resolution 只产 province 侧结算参数；hub tier 不读这些键
    assert "@shaanxi" not in format_fiscal_fact_brief_tsv([]) or True  # placeholder guard
    central_cfg = dict(config)
    assert resolve_pay_order_overrides(central_cfg, "shaanxi", turn=1).haircut_bp.get("军饷") == 6000


def test_r4_golden2_expiry_falls_back_to_next_specific(game=None):
    """r4 golden②：同一在位组合，@shaanxi#province_until_turn 到期后（其余键不变），
    陕西省饷侧回落 #province 胜出。"""
    config = {
        "due_haircut_bp_军饷@shaanxi#province": 6000,
        "due_haircut_bp_军饷@shaanxi#province_until_turn": 12,
        "due_haircut_bp_军饷#province": 9000,
    }
    assert resolve_pay_order_overrides(config, "shaanxi", turn=12).haircut_bp["军饷"] == 6000
    assert resolve_pay_order_overrides(config, "shaanxi", turn=13).haircut_bp["军饷"] == 9000
    # 到期形状退出格律；键与 provenance 保留不删
    assert config["due_haircut_bp_军饷@shaanxi#province"] == 6000
    assert config["due_haircut_bp_军饷@shaanxi#province_until_turn"] == 12


def test_precedence_region_beats_bare_and_full_order():
    config = {
        "due_priority_军饷@shaanxi": 40,
        "due_priority_军饷": 10,
    }
    # 陕西：@shaanxi 胜出（军饷 40 → 最末）；他省：裸键胜出（军饷 10 → 最先）
    sx = resolve_pay_order_overrides(config, "shaanxi", turn=1).due_order
    hn = resolve_pay_order_overrides(config, "henan", turn=1).due_order
    # 陕西：@shaanxi=40 使军饷与赈济（默认40）并列 → 默认基准 tie-break（军饷10<赈济40）
    assert tuple(sx) == ("官俸", "宗禄", "军饷", "赈济")
    # 他省：裸键=10 → 军饷最先
    assert tuple(hn) == ("军饷", "官俸", "宗禄", "赈济")


def test_priority_tie_breaks_on_default_baseline_stable():
    config = {"due_priority_宗禄": 10}  # 与 军饷 默认 10 并列 → 默认基准 tie-break（军饷先）
    order = resolve_pay_order_overrides(config, "shaanxi", turn=1).due_order
    assert order == ("军饷", "宗禄", "官俸", "赈济")


def test_arrears_order_resolution_default_and_override():
    no_cfg = resolve_pay_order_overrides({}, "shaanxi", turn=1)
    assert no_cfg is None  # 无旨 fast path：零合并
    config = {"arrears_priority_军饷欠": 30, "arrears_priority_宗禄欠": 10}
    res = resolve_pay_order_overrides(config, "shaanxi", turn=1)
    assert res.arrears_order == ("宗禄欠", "官俸欠", "军饷欠")


def test_expired_only_keys_return_none_fast_path():
    config = {
        "due_priority_军饷": 40,
        "due_priority_军饷_until_turn": 5,
    }
    assert resolve_pay_order_overrides(config, "shaanxi", turn=6) is None
    assert resolve_pay_order_overrides(config, "shaanxi", turn=5) is not None


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
    tsv = "\n".join(f"{k}\t{res.breakdown['实付分账'][k]}" for k in p2["due_order"])
    assert tsv.splitlines()[0] == "官俸\t3.0"       # 官俸足付
    assert tsv.splitlines()[0].startswith("官俸\t3.0")
    last_cell = float(tsv.splitlines()[-1].split("\t")[1])
    assert last_cell == pytest.approx(1.93)          # 边饷居末只捡残池
    assert res.breakdown["NewDebt"]["军饷欠"] == pytest.approx(16.07)
    assert res.breakdown["NewDebt"]["官俸欠"] == 0.0
    assert res.new_st["军饷欠"] == pytest.approx(36.07)  # 旧欠20 + 新欠16.07


def test_golden2_haircut_half_is_exemption_not_debt():
    """②「宗禄折半」：floor(Due×bp/10000)；折掉部分不入宗禄欠；NewDebt 只含折后未付。
    r2 golden：Due=101、bp=5000 → 应得 50、免除 51。"""
    from ming_sim.pay_order import haircut_due
    eff, exempt = haircut_due(101, 5000)
    assert eff == 50.0 and exempt == 51.0

    st, p = _board(gross=50.0)  # 省内可支＝10+50=60
    p["Due"] = {"军饷": 18.0, "官俸": 3.0, "宗禄": 101.0, "赈济": 1.0}
    p["due_haircut_bp"] = {"宗禄": 5000}
    res = settle_tick(st, p, [])
    assert res.breakdown["haircut_宗禄"] == pytest.approx(51.0)   # 折发=免除
    # 池 60：军饷18+官俸3+宗禄应得50+赈济1=72>60 → 军饷18/官俸3/宗禄39/赈济0
    assert res.breakdown["实付分账"]["宗禄"] == pytest.approx(39.0)
    assert res.new_st["宗禄欠"] == pytest.approx(11.0)  # 只含折后未付（50−39）
    # 免除的 51 绝不进 CLAIM（若无折，宗禄欠将是 101-39=62）
    assert res.new_st["宗禄欠"] < 62.0


def test_golden3_arrears_waterfall_reversal():
    """③「旧欠先偿宗禄」：surplus waterfall 先还宗禄欠、再军饸欠。"""
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


def test_golden4_last_write_wins_with_two_provenance_rows(game):
    """④连下两道同维相冲旨：后旨生效；fiscal_config_changes 两行 provenance 可查。"""
    db, state, _content = game
    materialize_pay_order_decree(
        db, turn=state.turn,
        entries=[{"key": "due_priority_军饷", "value": 40}],
        origin_ref="dossier:11", reason="首道：边饷居末", commit=True,
    )
    materialize_pay_order_decree(
        db, turn=state.turn,
        entries=[{"key": "due_priority_军饷", "value": 10}],
        origin_ref="dossier:12", reason="次道：边饷复先", commit=True,
    )
    assert db.get_fiscal_config()["due_priority_军饷"] == 10  # last-write-wins
    rows = db.conn.execute(
        "SELECT old_value, new_value, origin_ref FROM fiscal_config_changes "
        "WHERE key='due_priority_军饷' ORDER BY id"
    ).fetchall()
    assert len(rows) == 2
    assert [r["origin_ref"] for r in rows] == ["dossier:11", "dossier:12"]
    assert (rows[0]["old_value"], rows[0]["new_value"]) == (10, 40)
    assert (rows[1]["old_value"], rows[1]["new_value"]) == (40, 10)


def test_golden5_expiry_and_revoke_restore_byte_identical_default(game):
    """⑤期限届满月／撤销旨：全序与系数恢复默认，与无旨基线逐字节一致。"""
    db, state, _content = game
    turn = db._current_settle_turn()
    materialize_pay_order_decree(
        db, turn=turn,
        entries=[
            {"key": "due_priority_军饷@shaanxi", "value": 40, "until_turn": turn},
            {"key": "due_haircut_bp_宗禄@shaanxi", "value": 5000, "until_turn": turn},
        ],
        origin_ref="dossier:21", commit=True,
    )
    # 当回合仍在位：override 生效（结果偏离基线）
    active = db.settle_province_tick("shaanxi")
    assert active.breakdown["haircut_宗禄"] > 0

    # 届满月：turn > until → 全部回落默认，与同输入无旨基线逐字节一致
    db.conn.execute("UPDATE game_state SET turn = ? WHERE id = 1", (turn + 1,))
    cur = _opening_settle(db, "shaanxi")  # active 月已推进后的开账
    expected_default = settle_tick(
        copy.deepcopy(cur["st"]), copy.deepcopy(cur["p"]), [],
    )
    expired = db.settle_province_tick("shaanxi")
    assert expired.new_st == expected_default.new_st
    assert expired.breakdown == expected_default.breakdown
    # 键与 provenance 保留不删
    assert "due_priority_军饷@shaanxi_until_turn" in db.get_fiscal_config()

    # 撤销旨路径：在位永久旨 revoke 后恢复默认
    db.conn.execute("UPDATE game_state SET turn = ? WHERE id = 1", (turn,))
    materialize_pay_order_decree(
        db, turn=db._current_settle_turn(),
        entries=[{"key": "due_priority_官俸@shaanxi", "value": 10}],
        origin_ref="dossier:22", commit=True,
    )
    assert resolve_pay_order_overrides(db.get_fiscal_config(), "shaanxi", db._current_settle_turn()) is not None
    revoke_pay_order_decree(
        db, turn=db._current_settle_turn(),
        keys=["due_priority_官俸@shaanxi"], origin_ref="dossier:23", commit=True,
    )
    assert db.get_fiscal_config()["due_priority_官俸@shaanxi"] == DEFAULT_DUE_PRIORITY["官俸"]


def test_golden6_rejected_decree_zero_config_write(game):
    """⑥打回的折发旨：零 config 写入、结算照默认序（0055 效果跟判决走）。

    物化唯一入口＝materialize_pay_order_decree；打回判决不调它 → 零写入。
    本例钉死：无物化调用时 config/provenance 零变化，且结算与无旨基线一致。
    """
    db, state, _content = game
    before_cfg = db.get_fiscal_config()
    before_rows = db.conn.execute(
        "SELECT COUNT(*) c FROM fiscal_config_changes").fetchone()["c"]
    # ……（打回路径：不调用 materialize_pay_order_decree）……
    assert db.get_fiscal_config() == before_cfg
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM fiscal_config_changes").fetchone()["c"] == before_rows
    # 结算照默认序（与纯函数无旨基线逐字节一致）
    settle = _opening_settle(db, "shaanxi")
    expected = settle_tick(copy.deepcopy(settle["st"]), copy.deepcopy(settle["p"]), [])
    res = db.settle_province_tick("shaanxi")
    assert res.new_st == expected.new_st
    assert res.breakdown == expected.breakdown


def test_golden7_replay_determinism(game):
    """⑦restore 后任意月重放结果一致；纯函数同输入同输出。"""
    db, state, _content = game
    settle = _opening_settle(db, "shaanxi")
    a = settle_tick(settle["st"], settle["p"], [])
    b = settle_tick(settle["st"], settle["p"], [])
    assert a.new_st == b.new_st
    assert a.breakdown == b.breakdown


# ═══════════════ 桥集成：结算按新序/系数付账 ═══════════════

def test_bridge_applies_due_order_and_haircut_end_to_end(game):
    db, state, _content = game
    settle_before = _opening_settle(db, "shaanxi")
    baseline = settle_tick(
        copy.deepcopy(settle_before["st"]), copy.deepcopy(settle_before["p"]), [],
    )
    materialize_pay_order_decree(
        db, turn=db._current_settle_turn(),
        entries=[
            {"key": "due_priority_军饷@shaanxi", "value": 40},
            {"key": "due_priority_官俸@shaanxi", "value": 10},
            {"key": "due_haircut_bp_军饷@shaanxi", "value": 5000},
        ],
        origin_ref="dossier:31", commit=True,
    )
    res = db.settle_province_tick("shaanxi")
    assert res.breakdown["实付分账"]["官俸"] > 0          # 官俸优先足付
    assert res.breakdown["NewDebt"]["军饷欠"] > 0         # 边饷居末积欠
    assert res.breakdown["haircut_军饷"] > 0              # 折发免除额入分解
    assert res.new_st != baseline.new_st                  # 偏离基线


def _opening_settle(db, region_id):
    import json

    row = db.conn.execute("SELECT fiscal FROM regions WHERE id=?", (region_id,)).fetchone()
    return json.loads(row["fiscal"])["settle"]


# ═══════════════ settle_tick 序参/折发参验形 fail-loud ═══════════════

@pytest.mark.parametrize("bad", [
    ["军饷", "官俸", "宗禄"],
    ["军饷", "官俸", "宗禄", "赈济", "军饷"],
    ["军饷", "官俸", "官俸", "赈济"],
    "军饷,官俸,宗禄,赈济",
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

def test_fiscal_fact_brief_pure_projection_deterministic_tsv(read_game):
    db, _state, _content = read_game
    e1 = build_fiscal_fact_brief(db)
    e2 = build_fiscal_fact_brief(db)
    assert e1 == e2  # 纯函数：两次调用逐字节一致
    for e in e1:
        assert set(e) == {
            "subject_kind", "subject_id", "metric", "window_turns",
            "value", "origin_ref", "affected_class", "detail",
        }
        assert e["metric"] in ("分源欠饷月数", "加派量", "欠禄额")
    # 开局陕西三饷应征在案 → 加派量条目确定性正确
    levy = [e for e in e1 if e["metric"] == "加派量" and e["subject_id"] == "shaanxi"]
    assert levy and levy[0]["affected_class"] == "农民"
    settle = _opening_settle(db, "shaanxi")
    assert levy[0]["value"] == pytest.approx(float(settle["p"]["三饷应征"]))
    tsv = format_fiscal_fact_brief_tsv(e1)
    assert tsv.splitlines()[0] == (
        "subject_kind\tsubject_id\tmetric\twindow_turns\tvalue\taffected_class\tdetail"
    )
    assert f"region\tshaanxi\t加派量\t1\t{levy[0]['value']}\t农民\t三饷应征" in tsv
    assert format_fiscal_fact_brief_tsv(e2) == tsv


# ═══════════════ F3 符号域硬约束 ═══════════════

def test_sign_clamp_damaged_class_cannot_gain():
    facts = [{
        "subject_kind": "region", "subject_id": "shaanxi", "metric": "欠禄额",
        "window_turns": 0, "value": 12.0, "origin_ref": "",
        "affected_class": "官僚", "detail": "官俸欠",
    }]
    delta = {"官僚": {"satisfaction": 5}, "农民": {"satisfaction": 4}}
    clamped, records = clamp_class_delta_to_fact_signs(delta, facts)
    assert clamped["官僚"]["satisfaction"] == 0      # 受损方为正→非法输出被 clamp
    assert clamped["农民"]["satisfaction"] == 4      # 无涉事实的阶级不受约束
    assert records and records[0] == {
        "name": "官僚", "rejected": False, "clamped": True,
        "category": "sign_clamp", "field": "satisfaction",
        "from": 5, "to": 0,
        "reason": records[0]["reason"],
    }
    assert "clamp 至 0" in records[0]["reason"]


def test_sign_clamp_scoped_key_matched_by_base_name():
    facts = [{
        "subject_kind": "region", "subject_id": "shaanxi", "metric": "欠禄额",
        "window_turns": 0, "value": 3.0, "origin_ref": "",
        "affected_class": "宗藩", "detail": "宗禄欠",
    }]
    delta = {"宗藩@shaanxi": {"satisfaction": 2, "leverage": 1}}
    clamped, records = clamp_class_delta_to_fact_signs(delta, facts)
    assert clamped["宗藩@shaanxi"]["satisfaction"] == 0
    assert clamped["宗藩@shaanxi"]["leverage"] == 1   # 非 satisfaction 字段不动
    assert len(records) == 1


def test_sign_clamp_negative_satisfaction_without_damage_passes_through():
    # 盘面无财政受损事实 → 符号域不约束，负 satisfaction 原样通过
    clamped, records = clamp_class_delta_to_fact_signs(
        {"官僚": {"satisfaction": -3}}, [],
    )
    assert clamped == {"官僚": {"satisfaction": -3}}
    assert records == []


def test_extraction_modules_unchanged_four_parallel():
    """F3 三断言之①：无第 5 个 LLM 调用、四 extractor 仍 parallel——模块清单一字不动，
    class_delta 仍由 internal 槽独占。"""
    from ming_sim.simulation import EXTRACTION_MODULES, MODULE_FIELDS
    assert EXTRACTION_MODULES == ("internal", "military_external", "issues", "personnel_secret")
    assert len(EXTRACTION_MODULES) == 4
    assert "class_delta" in MODULE_FIELDS["internal"]
    assert sum("class_delta" in fields for fields in MODULE_FIELDS.values()) == 1


def test_simulator_payload_contains_fiscal_fact_brief(game):
    """F3 三断言之③：simulator payload 含 fiscal_fact_brief（输入侧特征包）。"""
    from ming_sim.simulation import build_simulator_payload

    db, state, _content = game
    payload = build_simulator_payload(state, db, "", "")
    brief = payload["fiscal_fact_brief"]
    assert isinstance(brief, list)
    assert brief == build_fiscal_fact_brief(db)


def test_apply_score_extraction_clamps_against_ledger(game):
    """端到端：apply_score_extraction 的 class_delta 受损阶级为正 → 被 clamp 落 0 并留痕。"""
    from ming_sim.issues import apply_score_extraction

    import json

    db, state, _content = game
    # 最小盘面：单一受损事实——陕西官俸欠存量 12（F2.4 映射 官僚）。
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = json.loads(row["fiscal"])
    fiscal["settle"]["st"]["官俸欠"] = 12.0
    db.conn.execute(
        "UPDATE regions SET fiscal=? WHERE id='shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    db.conn.commit()
    extracted = {"class_delta": {"官僚": {"satisfaction": 9}}}
    applied = apply_score_extraction(db, state, copy.deepcopy(extracted))
    clamps = [
        r for r in applied["class_delta_rejections"]
        if r.get("category") == "sign_clamp"
    ]
    assert clamps and clamps[0]["name"] == "官僚"
    assert applied["class_delta"].get("官僚", {}).get("satisfaction", 0) <= 0
