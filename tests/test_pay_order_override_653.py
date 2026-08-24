#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#653 / ADR 0090 偿还序 override ＋ Due 折发系数＋阶级怨气喂判。

票面（冻结票面含 r1–r4 修正案）验收表 golden ①–⑦ ＋ r4 canonical region goldens
＋ F2 六源纯投影 TSV 断言 ＋ F3 综合归因输入 / 零新增调用断言。
"""
from __future__ import annotations

import copy
import math

import pytest

from ming_sim.fiscal_tick import settle_tick
from ming_sim.fiscal_fact_brief import (
    FACT_METRICS,
    build_fiscal_fact_brief,
    format_fiscal_fact_brief_tsv,
)
from ming_sim.pay_order import (
    DEFAULT_ARREARS_PRIORITY,
    DEFAULT_DUE_PRIORITY,
    PayOrderKeyError,
    materialize_pay_order_decree,
    parse_override_key,
    resolve_haircut_bp,
    resolve_pay_order_overrides,
    restore_pay_order_override,
    revoke_pay_order_decree,
)


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
    """r4：不新增 alias、不造虚拟 region——@SX 幻影 region fail-loud 拒**整道旨**
    （成案点先验拒入案卷；物化点与成案点共 prepare_pay_order_entries 同一验形）。"""
    db, state, _content = game
    entries = [
        {"key": "due_haircut_bp_军饷@shaanxi#province", "value": 8000},
        {"key": "due_haircut_bp_军饷@SX#province", "value": 9000},  # 幻影 region
    ]
    with pytest.raises(ValueError):
        _override_dossier(db, state, entries)
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
    他省省饷侧取 #province；两把 #province 键对中央侧零约束（饷源精确）。"""
    config = {
        "due_haircut_bp_军饷@shaanxi#province": 6000,
        "due_haircut_bp_军饷#province": 9000,
    }
    shaanxi = resolve_pay_order_overrides(config, "shaanxi", turn=1)
    henan = resolve_pay_order_overrides(config, "henan", turn=1)
    assert shaanxi.haircut_bp["军饷"] == 6000
    assert henan.haircut_bp["军饷"] == 9000
    # 中央侧不受影响：#province 键在任何省的 central 侧都无消费者
    assert resolve_haircut_bp(config, "军饷", "shaanxi", 1, "central") is None
    assert resolve_haircut_bp(config, "军饷", "henan", 1, "central") is None
    assert resolve_haircut_bp(config, "军饷", "", 1, "central") is None


def test_r3_central_side_scope_resolution():
    """r3 补充 golden（judge class②）：#central / 裸键在中央侧按全序独立取胜。"""
    both = {
        "due_haircut_bp_军饷@shaanxi#central": 6000,
        "due_haircut_bp_军饷#central": 9000,
    }
    assert resolve_haircut_bp(both, "军饷", "shaanxi", 1, "central") == 6000
    assert resolve_haircut_bp(both, "军饷", "liaodong", 1, "central") == 9000
    # @region 无源缀形同时辖两侧；@shaanxi 与 @shaanxi#central 并存 → 后者胜
    mixed = {"due_haircut_bp_军饷@shaanxi": 7000, "due_haircut_bp_军饷": 8000}
    assert resolve_haircut_bp(mixed, "军饷", "shaanxi", 1, "central") == 7000
    assert resolve_haircut_bp(mixed, "军饷", "shaanxi", 1, "province") == 7000
    assert resolve_haircut_bp(mixed, "军饷", "henan", 1, "central") == 8000
    # 中央侧到期 → 该形状退出格律，回落实胜出键
    expired = {
        "due_haircut_bp_军饷@shaanxi#central": 6000,
        "due_haircut_bp_军饷@shaanxi#central_until_turn": 12,
        "due_haircut_bp_军饷#central": 9000,
    }
    assert resolve_haircut_bp(expired, "军饷", "shaanxi", 12, "central") == 6000
    assert resolve_haircut_bp(expired, "军饷", "shaanxi", 13, "central") == 9000


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


def test_golden4_last_write_wins_with_two_provenance_rows(game):
    """④连下两道同维相冲旨：后旨生效；fiscal_config_changes 两行 provenance 可查。"""
    db, state, _content = game
    d1 = _override_dossier(
        db, state, [{"key": "due_priority_军饷", "value": 40}],
        text="首道：边饷居末",
    )
    db.apply_dossier_promulgation(state, d1, "promulgated")   # 判后物化缝
    d2 = _override_dossier(
        db, state, [{"key": "due_priority_军饷", "value": 10}],
        text="次道：边饷复先",
    )
    db.apply_dossier_promulgation(state, d2, "promulgated")
    assert db.get_fiscal_config()["due_priority_军饷"] == 10  # last-write-wins
    rows = db.conn.execute(
        "SELECT old_value, new_value, origin_ref FROM fiscal_config_changes "
        "WHERE key='due_priority_军饷' ORDER BY id"
    ).fetchall()
    assert len(rows) == 2
    assert [r["origin_ref"] for r in rows] == [f"dossier:{d1}", f"dossier:{d2}"]
    assert (rows[0]["old_value"], rows[0]["new_value"]) == (10, 40)
    assert (rows[1]["old_value"], rows[1]["new_value"]) == (40, 10)


def test_golden5_expiry_and_revoke_restore_byte_identical_default(game):
    """⑤期限届满月／撤销旨：全序与系数恢复默认，与无旨基线逐字节一致。"""
    db, state, _content = game
    turn = db._current_settle_turn()
    d21 = _override_dossier(db, state, [
        {"key": "due_priority_军饷@shaanxi", "value": 40, "until_turn": turn},
        {"key": "due_haircut_bp_宗禄@shaanxi", "value": 5000, "until_turn": turn},
    ])
    db.apply_dossier_promulgation(state, d21, "promulgated")   # 判后物化缝（带期限）
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

    # 撤销旨路径：在位永久旨撤销＝写回默认值的新旨（r2：old/new provenance 链即审计账）
    db.conn.execute("UPDATE game_state SET turn = ? WHERE id = 1", (turn,))
    d22 = _override_dossier(
        db, state, [{"key": "due_priority_官俸@shaanxi", "value": 10}],
        text="官俸优先旨",
    )
    db.apply_dossier_promulgation(state, d22, "promulgated")
    assert resolve_pay_order_overrides(db.get_fiscal_config(), "shaanxi", db._current_settle_turn()) is not None
    d23 = _override_dossier(
        db, state, [{"key": "due_priority_官俸@shaanxi", "value": DEFAULT_DUE_PRIORITY["官俸"]}],
        text="撤回前旨",
    )
    db.apply_dossier_promulgation(state, d23, "promulgated")   # 撤销旨本身先过颁布门
    revoke_pay_order_decree(
        db, turn=db._current_settle_turn(),
        keys=["due_priority_官俸@shaanxi"], origin_ref=f"dossier:{d23}", commit=True,
    )
    assert db.get_fiscal_config()["due_priority_官俸@shaanxi"] == DEFAULT_DUE_PRIORITY["官俸"]


def test_real_revoke_decree_restores_override_and_clears_expiry(game):
    """撤销使目标形状退出格律（删键），期限伴随键一并清除；读取回落祖制默认。"""
    db, state, _content = game
    target = _override_dossier(db, state, [{
        "key": "due_priority_军饷@shaanxi", "value": 40,
        "until_turn": db._current_settle_turn() + 2,
    }])
    db.apply_dossier_promulgation(state, target, "promulgated")
    revoke = db.create_decree_dossier(
        state,
        action_type="revoke_decree",
        decree_text="撤回前旨",
        target_kind="dossier",
        target_id=str(target),
        payload={"revoke_target_dossier_id": target},
    )
    db.apply_dossier_promulgation(state, revoke, "promulgated")
    cfg = db.get_fiscal_config()
    # 形状退出格律：键不在位（对齐到期 _live），禁留 live 默认值
    assert "due_priority_军饷@shaanxi" not in cfg
    assert "due_priority_军饷@shaanxi_until_turn" not in cfg
    assert resolve_pay_order_overrides(cfg, "shaanxi", db._current_settle_turn()) is None
    changes = db.conn.execute(
        "SELECT key, origin_ref FROM fiscal_config_changes WHERE origin_ref=? ORDER BY id",
        (f"dossier:{revoke}",),
    ).fetchall()
    assert [row["key"] for row in changes] == [
        "due_priority_军饷@shaanxi", "due_priority_军饷@shaanxi_until_turn",
    ]
    tomb = db.conn.execute(
        "SELECT key FROM fiscal_config_tombstones WHERE origin_ref=? ORDER BY id",
        (f"dossier:{revoke}",),
    ).fetchall()
    assert [row["key"] for row in tomb] == [
        "due_priority_军饷@shaanxi", "due_priority_军饷@shaanxi_until_turn",
    ]


def test_proposed_revoke_does_not_restore_override(game):
    """未颁 revoke：owner seam 响亮拒绝，在位 override/期限/审计零变化。"""
    db, state, _content = game
    until = db._current_settle_turn() + 2
    target = _override_dossier(db, state, [{
        "key": "due_priority_军饷@shaanxi", "value": 40, "until_turn": until,
    }])
    db.apply_dossier_promulgation(state, target, "promulgated")
    revoke = db.create_decree_dossier(
        state,
        action_type="revoke_decree",
        decree_text="撤回前旨",
        target_kind="dossier",
        target_id=str(target),
        payload={"revoke_target_dossier_id": target},
    )
    before_cfg = dict(db.get_fiscal_config())
    with pytest.raises(PayOrderKeyError, match="未过合法颁布门"):
        restore_pay_order_override(
            db,
            turn=db._current_settle_turn(),
            target_dossier_id=target,
            revoke_dossier_id=revoke,
            reason="未颁不得删 config",
        )
    cfg = db.get_fiscal_config()
    assert cfg["due_priority_军饷@shaanxi"] == 40
    assert cfg["due_priority_军饷@shaanxi_until_turn"] == until
    assert cfg["due_priority_军饷@shaanxi"] == before_cfg["due_priority_军饷@shaanxi"]
    assert cfg["due_priority_军饷@shaanxi_until_turn"] == before_cfg[
        "due_priority_军饷@shaanxi_until_turn"
    ]
    origin = f"dossier:{revoke}"
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM fiscal_config_tombstones WHERE origin_ref=?",
        (origin,),
    ).fetchone()["c"] == 0
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM fiscal_config_changes WHERE origin_ref=?",
        (origin,),
    ).fetchone()["c"] == 0


def test_rejected_revoke_does_not_restore_override(game):
    """打回 revoke：owner seam 响亮拒绝，在位 override/期限/审计零变化。"""
    from dossier_test_helpers import rejected_verdict

    db, state, _content = game
    until = db._current_settle_turn() + 2
    target = _override_dossier(db, state, [{
        "key": "due_priority_军饷@shaanxi", "value": 40, "until_turn": until,
    }])
    db.apply_dossier_promulgation(state, target, "promulgated")
    revoke = db.create_decree_dossier(
        state,
        action_type="revoke_decree",
        decree_text="撤回前旨",
        target_kind="dossier",
        target_id=str(target),
        payload={"revoke_target_dossier_id": target},
    )
    db.apply_dossier_verdicts(state, [rejected_verdict(revoke)])
    before_cfg = dict(db.get_fiscal_config())
    with pytest.raises(PayOrderKeyError, match="未过合法颁布门"):
        restore_pay_order_override(
            db,
            turn=db._current_settle_turn(),
            target_dossier_id=target,
            revoke_dossier_id=revoke,
            reason="打回不得删 config",
        )
    cfg = db.get_fiscal_config()
    assert cfg["due_priority_军饷@shaanxi"] == 40
    assert cfg["due_priority_军饷@shaanxi_until_turn"] == until
    assert cfg["due_priority_军饷@shaanxi"] == before_cfg["due_priority_军饷@shaanxi"]
    assert cfg["due_priority_军饷@shaanxi_until_turn"] == before_cfg[
        "due_priority_军饷@shaanxi_until_turn"
    ]
    origin = f"dossier:{revoke}"
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM fiscal_config_tombstones WHERE origin_ref=?",
        (origin,),
    ).fetchone()["c"] == 0
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM fiscal_config_changes WHERE origin_ref=?",
        (origin,),
    ).fetchone()["c"] == 0


def test_turn_region_summary_claim_audit_rows_do_not_consume_limit(game):
    db, state, _content = game
    _pin_shortfall_board(db, "shaanxi")
    # 零可用省银，令真实 settle 同时写出官俸欠与宗禄欠两家族。
    import json as _json
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = _json.loads(row["fiscal"])
    fiscal["settle"]["st"]["省库库银"] = 0
    fiscal["settle"]["p"].update(
        {"正赋应征": 0, "三饷应征": 0, "起运定额": 0, "拨付gross": 0}
    )
    db.conn.execute(
        "UPDATE regions SET fiscal=? WHERE id='shaanxi'",
        (_json.dumps(fiscal, ensure_ascii=False),),
    )
    db.settle_province_tick("shaanxi")
    claim_rows = db.conn.execute(
        "SELECT field, reason FROM region_logs WHERE turn=? AND region_id='shaanxi' "
        "AND field LIKE 'settle_%欠_%' ORDER BY id", (state.turn,),
    ).fetchall()
    assert {row["field"].split("_")[1] for row in claim_rows} >= {"官俸欠", "宗禄欠"}

    db.conn.execute(
        "INSERT INTO region_logs "
        "(turn,year,period,region_id,field,old_value,new_value,delta,reason) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (state.turn, state.year, state.period, "shaanxi",
         "unrest", "1", "2", 1, "民变事实"),
    )
    summary = db.turn_region_summary(state.turn, limit=1)
    assert "民变事实" in summary
    assert not any(row["reason"] in summary for row in claim_rows)


def test_deferred_real_revoke_restores_override_only_after_persist(game):
    from ming_sim.breach_plea import decode_plea_meta, finalize_persist

    db, state, _content = game
    until = db._current_settle_turn() + 3
    target = _override_dossier(db, state, [{
        "key": "due_priority_军饷@shaanxi", "value": 40, "until_turn": until,
    }])
    db.apply_dossier_promulgation(state, target, "promulgated")
    issue_id = db.insert_issue(
        state, kind="initiative", title="边饷次序之诺", origin_kind="decree",
        origin_ref=f"dossier:{target}", cancellable="decree",
        commitment_kind="until_stop", bar_value=10, stage_text="在办",
        ongoing_effects={}, end_turn=state.turn + 12,
    )
    revoke = db.create_decree_dossier(
        state, action_type="revoke_decree", decree_text="撤回前旨",
        target_kind="issue", target_id=str(issue_id),
        payload={"revoke_target_issue_id": issue_id, "revoke_target_dossier_id": target},
    )
    db.apply_dossier_promulgation(state, revoke, "promulgated")
    cfg = db.get_fiscal_config()
    assert cfg["due_priority_军饷@shaanxi"] == 40
    assert cfg["due_priority_军饷@shaanxi_until_turn"] == until
    todo = next(
        todo for todo in db.list_next_audience_todos(status="pending")
        if decode_plea_meta(todo.get("origin_context")).get("revoke_dossier_id") == revoke
    )
    result = finalize_persist(db, state, todo, commit=True)
    assert result["decision"] == "persist"
    cfg = db.get_fiscal_config()
    assert "due_priority_军饷@shaanxi" not in cfg
    assert "due_priority_军饷@shaanxi_until_turn" not in cfg
    origins = {row["origin_ref"] for row in db.conn.execute(
        "SELECT origin_ref FROM fiscal_config_changes "
        "WHERE key LIKE 'due_priority_军饷@shaanxi%' ORDER BY id DESC LIMIT 2"
    )}
    assert origins == {f"dossier:{revoke}"}


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
    did = _override_dossier(db, state, [
        {"key": "due_priority_军饷@shaanxi", "value": 40},
        {"key": "due_priority_官俸@shaanxi", "value": 10},
        {"key": "due_haircut_bp_军饷@shaanxi", "value": 5000},
    ])
    # 全生命周期：顺颁判决 → 判后物化（ADR 0055 缝）→ 结算读端
    db.apply_dossier_promulgation(state, did, "promulgated")
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
    [["军饷"], "官俸", "宗禄", "赈济"],  # unhashable 元素不得泄漏 TypeError
])
def test_due_order_bad_shapes_raise(bad):
    st, p = _board()
    p["due_order"] = bad
    with pytest.raises(ValueError):
        settle_tick(st, p, [])
    # oracle 路径对称：同样锁在 ValueError 域
    from ming_sim.fiscal_tick import _DUE_KEYS, _oracle_order
    with pytest.raises(ValueError):
        _oracle_order({"due_order": bad}, "due_order", _DUE_KEYS)


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

def test_f23_region_logs_flow_sign_domain_repaid_negative(game):
    """F2.3 ⑥段符号域契约（受损正/受益负）：waterfall 下单 tick 内 NewDebt
    （Pool 不足）与 Repaid（surplus>0）互斥，故同回合双省盘面——shaanxi 短缺盘
    产 NewDebt、henan 有 surplus 盘产 Repaid；投影按 turn 聚合两域符号一次咬死：
    Repaid 行 value<0 入受益符号域、NewDebt 行 value>0 受损域。
    db.py 留痕 Repaid delta=-amount（负），⑥段直接投影不再二次取反。"""
    db, _state, _content = game
    _pin_shortfall_board(db, "shaanxi")
    debt_res = db.settle_province_tick("shaanxi")
    new_debt = debt_res.breakdown.get("NewDebt") or {}
    assert any(abs(float(new_debt.get(c, 0) or 0)) > 1e-9 for c in ("官俸欠", "宗禄欠")), \
        "短缺盘必须有实际新增欠流量，否则用例空转"

    import json

    row = db.conn.execute(
        "SELECT fiscal FROM regions WHERE id='henan'"
    ).fetchone()
    fiscal = json.loads(str(row["fiscal"]))
    st, p = fiscal["settle"]["st"], fiscal["settle"]["p"]
    st["军饷欠"] = 0.0   # 清零：waterfall 偿旧欠按旨序，军饷欠在位会先吃光 surplus
    st["官俸欠"] = 2.0
    st["宗禄欠"] = 3.0
    p["拨付gross"] = 40.0   # 省内可支 >> Due → surplus 偿旧欠
    p["Due"] = {"军饷": 10.0, "官俸": 2.0, "宗禄": 3.0, "赈济": 1.0}
    db.conn.execute(
        "UPDATE regions SET fiscal=? WHERE id='henan'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    repaid_res = db.settle_province_tick("henan")
    repaid = repaid_res.breakdown.get("Repaid") or {}
    assert any(abs(float(repaid.get(c, 0) or 0)) > 1e-9 for c in ("官俸欠", "宗禄欠")), \
        "盈余盘必须有实际偿还流量，否则用例空转"

    entries = build_fiscal_fact_brief(db)
    flows = [e for e in entries if str(e["detail"]).startswith("省池_")]
    repaid_rows = [e for e in flows if str(e["detail"]).endswith("_Repaid")]
    debt_rows = [e for e in flows if str(e["detail"]).endswith("_NewDebt")]
    assert repaid_rows and debt_rows
    assert all(e["value"] < 0 for e in repaid_rows), repaid_rows
    assert all(e["value"] > 0 for e in debt_rows), debt_rows


def test_fiscal_fact_brief_pure_projection_deterministic_tsv(read_game):
    db, _state, _content = read_game
    e1 = build_fiscal_fact_brief(db)
    e2 = build_fiscal_fact_brief(db)
    assert e1 == e2  # 纯函数：两次调用逐字节一致
    for e in e1:
        assert set(e) == {
            "subject_kind", "subject_id", "region", "metric", "window_turns",
            "value", "origin_ref", "affected_class", "detail",
        }
        assert e["metric"] in FACT_METRICS
        assert str(e["origin_ref"]).strip()  # origin_ref 恒不空（judge class③）
        # 属地归因不变量：region 级=subject_id；army 级=pay_source_region 或空
        if e["subject_kind"] == "region":
            assert e["region"] == e["subject_id"]
    tsv = format_fiscal_fact_brief_tsv(e1)
    assert tsv.splitlines()[0] == (
        "subject_kind\tsubject_id\tregion\tmetric\twindow_turns\tvalue\taffected_class\tdetail"
    )
    assert format_fiscal_fact_brief_tsv(e2) == tsv


def test_fact_brief_levy_uses_civil_arrears_breakdown_relation(game):
    """正赋非零时，加派量=三饷应征−民欠新增，区别于三饷×(1−逋赋率)捷径。"""
    import json

    db, _state, _content = game
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = json.loads(row["fiscal"])
    fiscal["settle"]["p"].update({"正赋应征": 8.0, "三饷应征": 20.0, "逋赋率": 0.25})
    db.conn.execute("UPDATE regions SET fiscal=? WHERE id='shaanxi'", (json.dumps(fiscal, ensure_ascii=False),))
    levy = next(e for e in build_fiscal_fact_brief(db)
                if e["metric"] == "加派量" and e["subject_id"] == "shaanxi")
    assert levy["value"] == pytest.approx(13.0)  # 20 - (8+20)*.25
    assert levy["value"] != pytest.approx(15.0)  # 被废止的 20*(1-.25)
    assert levy["detail"] == "三饷加派净额"


def test_fact_brief_levy_derives_regular_assessment_like_settle_tick(game):
    """正赋未直设时复用亩额派生真源，不能把 None 静默当零。"""
    import json

    db, _state, _content = game
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = json.loads(row["fiscal"])
    fiscal["settle"]["st"]["官民田"] = 100.0
    fiscal["settle"]["p"].update({
        "正赋应征": None, "正赋亩额": 1.2, "三饷应征": 20.0, "逋赋率": 0.25,
    })
    db.conn.execute(
        "UPDATE regions SET fiscal=? WHERE id='shaanxi'",
        (json.dumps(fiscal, ensure_ascii=False),),
    )
    projected = next(
        e for e in build_fiscal_fact_brief(db)
        if e["metric"] == "加派量" and e["subject_id"] == "shaanxi"
    )
    settled = settle_tick(
        copy.deepcopy(fiscal["settle"]["st"]),
        copy.deepcopy(fiscal["settle"]["p"]),
        [],
    )
    assert settled.breakdown["民欠新增"] == pytest.approx(7.5)
    assert projected["value"] == pytest.approx(12.5)


def test_fact_brief_attributes_priority_displacement_to_dossier(game):
    """同一实付总额按祖制序重放，只报告因旨让位新增受损的对象、差额和案卷。"""
    db, state, content = game
    _pin_shortfall_board(db, "shaanxi")
    did = _override_dossier(db, state, [{"key": "due_priority_军饷@shaanxi", "value": 40}])
    db.apply_dossier_promulgation(state, did, "promulgated")
    db.settle_province_tick("shaanxi")
    displaced = [e for e in build_fiscal_fact_brief(db) if e["detail"].startswith("旨序让位_")]
    assert [(e["affected_class"], e["value"], e["origin_ref"]) for e in displaced] == [
        ("军户", pytest.approx(0.97), f"dossier:{did}"),
    ]
    from ming_sim.db import GameDB
    path = db.path
    db.conn.commit()
    db.close()
    restored = GameDB(path, content)
    try:
        assert [e for e in build_fiscal_fact_brief(restored)
                if e["detail"].startswith("旨序让位_")] == displaced
    finally:
        restored.close()


def test_revoke_later_same_dim_decree_not_stomped(game):
    """Codex-11/revoke_shape_exit①：同维后旨在位时撤前旨，不改该键。"""
    db, state, _content = game
    first = _override_dossier(
        db, state, [{"key": "due_priority_军饷@shaanxi", "value": 40}],
        text="前旨边饷居末",
    )
    db.apply_dossier_promulgation(state, first, "promulgated")
    second = _override_dossier(
        db, state, [{"key": "due_priority_军饷@shaanxi", "value": 5}],
        text="后旨边饷最前",
    )
    db.apply_dossier_promulgation(state, second, "promulgated")
    assert db.get_fiscal_config()["due_priority_军饷@shaanxi"] == 5
    revoke = db.create_decree_dossier(
        state, action_type="revoke_decree", decree_text="撤回前旨",
        target_kind="dossier", target_id=str(first),
        payload={"revoke_target_dossier_id": first},
    )
    db.apply_dossier_promulgation(state, revoke, "promulgated")
    cfg = db.get_fiscal_config()
    assert cfg["due_priority_军饷@shaanxi"] == 5  # 后旨 last-write 保全
    row = db.conn.execute(
        "SELECT origin_ref FROM fiscal_config WHERE key='due_priority_军饷@shaanxi'"
    ).fetchone()
    assert row["origin_ref"] == f"dossier:{second}"
    # 撤销未写任何该键 change
    stomps = db.conn.execute(
        "SELECT 1 FROM fiscal_config_changes WHERE origin_ref=? AND key='due_priority_军饷@shaanxi'",
        (f"dossier:{revoke}",),
    ).fetchone()
    assert stomps is None


def test_revoke_provincial_falls_back_to_nationwide(game):
    """Codex-11/revoke_shape_exit②：全国+省域并存时撤省域后该省回落全国键。"""
    db, state, _content = game
    nation = _override_dossier(
        db, state, [{"key": "due_priority_军饷", "value": 35}],
        text="全国边饷居后",
    )
    db.apply_dossier_promulgation(state, nation, "promulgated")
    local = _override_dossier(
        db, state, [{"key": "due_priority_军饷@shaanxi", "value": 50}],
        text="陕西边饷居末",
    )
    db.apply_dossier_promulgation(state, local, "promulgated")
    turn = db._current_settle_turn()
    before = resolve_pay_order_overrides(db.get_fiscal_config(), "shaanxi", turn)
    assert before is not None and before.due_order.index("军饷") == 3  # 省域50居末
    revoke = db.create_decree_dossier(
        state, action_type="revoke_decree", decree_text="撤陕西旨",
        target_kind="dossier", target_id=str(local),
        payload={"revoke_target_dossier_id": local},
    )
    db.apply_dossier_promulgation(state, revoke, "promulgated")
    cfg = db.get_fiscal_config()
    assert "due_priority_军饷@shaanxi" not in cfg  # 省域形状退出，禁留 live 默认
    assert cfg["due_priority_军饷"] == 35  # 全国键仍在位
    after = resolve_pay_order_overrides(cfg, "shaanxi", turn)
    assert after is not None
    # 回落全国键 value=35：军饷与宗禄(30)后、在赈济(40)前 → 官俸/宗禄/军饷/赈济
    assert after.due_order == ("官俸", "宗禄", "军饷", "赈济")
    # 对照：河南无省域键，同读全国键
    assert resolve_pay_order_overrides(cfg, "henan", turn).due_order == after.due_order


def test_fact_brief_attributes_arrears_order_displacement_to_dossier(game):
    """Codex-12：旧欠序让位反事实——只报因 arrears_priority 让位新增受损与案卷。"""
    import json as _json

    db, state, _content = game
    # 切断陕西军省源份额：Due.军饷/军饷欠 由 army 派生归零，瀑布只在官俸欠/宗禄欠间争 surplus。
    db.conn.execute(
        "UPDATE armies SET province_pay_share=0, province_pay_arrears=0, "
        "arrears=central_pay_arrears WHERE pay_source_region='shaanxi'"
    )
    # 省内可支≈实征10；Due=官俸3+宗禄4.07+赈济1=8.07 → surplus≈1.93
    # 默认旧欠序（军饷欠=0）先还官俸欠；旨把宗禄欠提到最前 → 官俸欠让位。
    st = {
        "省库库银": 0.0, "C_地方截留": 0.0, "C_中饱": 0.0, "C_漂没": 0.0,
        "C_eff损耗": 0.0, "民欠旧赋": 0.0, "军饷欠": 0.0, "官俸欠": 5.0,
        "宗禄欠": 5.0, "官民田": 100.0, "隐田": 50.0,
    }
    p = {
        "正赋应征": 8.0, "三饷应征": 2.0, "火耗率": 0.1, "逋赋率": 0.0,
        "起运定额": 0.0, "漂没率": 0.0, "中饱率": 0.0, "拨付gross": 0.0,
        "Due": {"军饷": 0.0, "官俸": 3.0, "宗禄": 4.07, "赈济": 1.0},
    }
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = _json.loads(row["fiscal"])
    fiscal["settle"]["st"] = st
    fiscal["settle"]["p"] = p
    db.conn.execute(
        "UPDATE regions SET fiscal=? WHERE id='shaanxi'",
        (_json.dumps(fiscal, ensure_ascii=False),),
    )
    db.conn.commit()
    did = _override_dossier(
        db, state, [{"key": "arrears_priority_宗禄欠@shaanxi", "value": 5}],
        text="旧欠先偿宗禄",
    )
    db.apply_dossier_promulgation(state, did, "promulgated")
    result = db.settle_province_tick("shaanxi")
    repaid = result.breakdown["Repaid"]
    assert repaid["宗禄欠"] == pytest.approx(1.93)
    assert repaid["官俸欠"] == pytest.approx(0.0)
    assert repaid["军饷欠"] == pytest.approx(0.0)
    displaced = [
        e for e in build_fiscal_fact_brief(db) if e["detail"].startswith("旧欠序让位_")
    ]
    assert [(e["detail"], e["affected_class"], e["value"], e["origin_ref"])
            for e in displaced] == [
        ("旧欠序让位_官俸欠", "官僚", pytest.approx(1.93), f"dossier:{did}"),
    ]
    # 无 due_order 改动时不得混入旨序让位条目
    assert not [
        e for e in build_fiscal_fact_brief(db) if e["detail"].startswith("旨序让位_")
    ]


def test_legacy_engine_pay_order_materialize_fails_loud_not_fulfilled(game):
    """Codex-10/legacy_no_consumer：legacy 引擎物化 fail-loud，案卷不得标 fulfilled。"""
    db, state, _content = game
    db.conn.execute(
        "INSERT INTO fiscal_config (key, value, kind, note) "
        "VALUES ('__fiscal_engine', 0, 'meta', 'test legacy engine') "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value, note=excluded.note"
    )
    db.conn.commit()
    assert db.fiscal_engine() == "legacy"
    did = _override_dossier(
        db, state, [{"key": "due_priority_军饷@shaanxi", "value": 40}],
    )
    with pytest.raises(ValueError, match="legacy"):
        db.apply_dossier_promulgation(state, did, "promulgated")
    assert "due_priority_军饷@shaanxi" not in db.get_fiscal_config()
    dossier = db.get_decree_dossier(did)
    assert dossier["status"] != "closed"
    assert str(dossier.get("execution_outcome") or "") != "fulfilled"


def test_fact_brief_priority_provenance_falls_back_to_nationwide_scope(game):
    """真实撤回局部胜出键后应回落全国键，并归因于真正造成让位的全国旨。"""
    db, state, _content = game
    _pin_shortfall_board(db, "shaanxi")
    nationwide = _override_dossier(
        db, state, [{"key": "due_priority_军饷", "value": 40}],
        text="全国边饷居末",
    )
    db.apply_dossier_promulgation(state, nationwide, "promulgated")
    local = _override_dossier(
        db, state, [{"key": "due_priority_军饷@shaanxi", "value": 39}],
        text="陕西局部边饷居后",
    )
    db.apply_dossier_promulgation(state, local, "promulgated")
    revoke = db.create_decree_dossier(
        state, action_type="revoke_decree", decree_text="撤陕西局部旨",
        target_kind="dossier", target_id=str(local),
        payload={"revoke_target_dossier_id": local},
    )
    db.apply_dossier_promulgation(state, revoke, "promulgated")
    assert "due_priority_军饷@shaanxi" not in db.get_fiscal_config()
    assert db.get_fiscal_config()["due_priority_军饷"] == 40
    db.settle_province_tick("shaanxi")

    displaced = [
        e for e in build_fiscal_fact_brief(db) if e["detail"] == "旨序让位_军饷"
    ]
    assert len(displaced) == 1
    assert displaced[0]["origin_ref"] == f"dossier:{nationwide}"
    assert displaced[0]["origin_ref"] != f"dossier:{local}"


def test_fact_brief_priority_provenance_prefers_winning_scoped_over_later_nationwide(game):
    """全国键先写、scoped 后写且两者皆能造成让位时，provenance 须收口胜出 scoped 键。"""
    db, state, _content = game
    _pin_shortfall_board(db, "shaanxi")
    nationwide = _override_dossier(
        db, state, [{"key": "due_priority_军饷", "value": 40}],
        text="全国边饷居末",
    )
    db.apply_dossier_promulgation(state, nationwide, "promulgated")
    scoped = _override_dossier(
        db, state, [{"key": "due_priority_军饷@shaanxi", "value": 40}],
        text="陕西边饷居末",
    )
    db.apply_dossier_promulgation(state, scoped, "promulgated")
    db.settle_province_tick("shaanxi")

    displaced = [
        e for e in build_fiscal_fact_brief(db) if e["detail"] == "旨序让位_军饷"
    ]
    assert len(displaced) == 1
    assert displaced[0]["origin_ref"] == f"dossier:{scoped}"
    assert displaced[0]["origin_ref"] != f"dossier:{nationwide}"


def test_fact_brief_arrears_provenance_prefers_winning_scoped_over_nationwide(game):
    """旧欠序：scoped 胜出时 provenance 不得被较晚/并存的全国键抢走。"""
    import json as _json

    db, state, _content = game
    db.conn.execute(
        "UPDATE armies SET province_pay_share=0, province_pay_arrears=0, "
        "arrears=central_pay_arrears WHERE pay_source_region='shaanxi'"
    )
    st = {
        "省库库银": 0.0, "C_地方截留": 0.0, "C_中饱": 0.0, "C_漂没": 0.0,
        "C_eff损耗": 0.0, "民欠旧赋": 0.0, "军饷欠": 0.0, "官俸欠": 5.0,
        "宗禄欠": 5.0, "官民田": 100.0, "隐田": 50.0,
    }
    p = {
        "正赋应征": 8.0, "三饷应征": 2.0, "火耗率": 0.1, "逋赋率": 0.0,
        "起运定额": 0.0, "漂没率": 0.0, "中饱率": 0.0, "拨付gross": 0.0,
        "Due": {"军饷": 0.0, "官俸": 3.0, "宗禄": 4.07, "赈济": 1.0},
    }
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = _json.loads(row["fiscal"])
    fiscal["settle"]["st"] = st
    fiscal["settle"]["p"] = p
    db.conn.execute(
        "UPDATE regions SET fiscal=? WHERE id='shaanxi'",
        (_json.dumps(fiscal, ensure_ascii=False),),
    )
    db.conn.commit()
    nationwide = _override_dossier(
        db, state, [{"key": "arrears_priority_宗禄欠", "value": 5}],
        text="全国旧欠先偿宗禄",
    )
    db.apply_dossier_promulgation(state, nationwide, "promulgated")
    scoped = _override_dossier(
        db, state, [{"key": "arrears_priority_宗禄欠@shaanxi", "value": 5}],
        text="陕西旧欠先偿宗禄",
    )
    db.apply_dossier_promulgation(state, scoped, "promulgated")
    db.settle_province_tick("shaanxi")
    displaced = [
        e for e in build_fiscal_fact_brief(db) if e["detail"] == "旧欠序让位_官俸欠"
    ]
    assert len(displaced) == 1
    assert displaced[0]["origin_ref"] == f"dossier:{scoped}"
    assert displaced[0]["origin_ref"] != f"dossier:{nationwide}"


def test_fact_brief_priority_provenance_ignores_later_noncausal_dossier(game):
    """后旨若不再改变实序，不得抢走先旨造成的让位 provenance。"""
    db, state, _content = game
    _pin_shortfall_board(db, "shaanxi")
    causal = _override_dossier(
        db, state, [{"key": "due_priority_军饷@shaanxi", "value": 40}],
        text="边饷居末",
    )
    db.apply_dossier_promulgation(state, causal, "promulgated")
    noncausal = _override_dossier(
        db, state, [{"key": "due_priority_官俸@shaanxi", "value": 19}],
        text="官俸微调但实序不变",
    )
    db.apply_dossier_promulgation(state, noncausal, "promulgated")
    db.settle_province_tick("shaanxi")

    displaced = [
        e for e in build_fiscal_fact_brief(db) if e["detail"] == "旨序让位_军饷"
    ]
    assert len(displaced) == 1
    assert displaced[0]["origin_ref"] == f"dossier:{causal}"
    assert displaced[0]["origin_ref"] != f"dossier:{noncausal}"


def test_fiscal_fact_brief_missing_settle_key_exits_dynamic_membership(game):
    """F2①：合法 fiscal dict 缺 settle key 是合法非成员，不产该省事实。"""
    db, _state, _content = game
    db.conn.execute("UPDATE regions SET fiscal='{}' WHERE id='henan'")
    entries = build_fiscal_fact_brief(db)
    assert not any(
        e["subject_kind"] == "region" and e["subject_id"] == "henan"
        for e in entries
    )


@pytest.mark.parametrize("bad_fiscal", [
    "[]",
    '{"settle": null}',
    '{"settle": []}',
    '{"settle": {"st": [], "p": {}}}',
    '{"settle": {"st": {}, "p": []}}',
])
def test_fiscal_fact_brief_present_but_malformed_fails_loud(game, bad_fiscal):
    """F2①：fiscal/settle key 已存在但容器或 st/p 畸形仍响亮失败。"""
    db, _state, _content = game
    db.conn.execute("UPDATE regions SET fiscal=? WHERE id='henan'", (bad_fiscal,))
    with pytest.raises(ValueError, match="fiscal_fact_brief"):
        build_fiscal_fact_brief(db)


def test_fiscal_fact_brief_bad_json_fails_loud(game):
    """F2①：坏 fiscal JSON 仍响亮失败（ADR 0005）。"""
    db, _state, _content = game
    db.conn.execute("UPDATE regions SET fiscal='{bad json' WHERE id='henan'")
    with pytest.raises(ValueError, match="fiscal_fact_brief"):
        build_fiscal_fact_brief(db)


def test_simulator_payload_accepts_recaptured_region_without_settle(game):
    """真实 payload：收复/legacy 明控省缺基座时合法出列，不阻断月末推演。"""
    from ming_sim.simulation import build_simulator_payload

    db, state, _content = game
    db.conn.execute(
        "UPDATE regions SET controlled_by='ming', fiscal='{}' WHERE id='taiwan'"
    )
    payload = build_simulator_payload(state, db, "", "")
    assert isinstance(payload["fiscal_fact_brief"], list)
    assert not any(
        e["subject_kind"] == "region" and e["subject_id"] == "taiwan"
        for e in payload["fiscal_fact_brief"]
    )


def test_fiscal_fact_brief_haircut_and_relief_facts(game):
    """折发受损事实（province/central 侧）与补发受益事实入投影（F4 资源事实）。"""
    db, state, _content = game
    did = _override_dossier(db, state, [
        {"key": "due_haircut_bp_军饷@shaanxi#central", "value": 5000},
    ])
    db.apply_dossier_promulgation(state, did, "promulgated")
    entries = build_fiscal_fact_brief(db)
    cut = [e for e in entries if str(e["detail"]).startswith("折发_")]
    assert any(
        e["subject_id"] == "shaanxi" and e["detail"] == "折发_军饷#central"
        and e["value"] > 0 and e["affected_class"] == "军户"
        and e["origin_ref"] == f"dossier:{did}"
        for e in cut
    )
    # 补发受益事实：economy_ledger purpose=补饷 行 → 负值（受益符号域）
    db.record_issue_economy_move(
        state, "国库", -30, "奉旨拨饷", "诏拨补饷三十万两",
        purpose="补饷", target_kind="army", target_id="shaanxi_army",
        origin_ref=f"dossier:{did}", commit=False,
    )
    db.conn.commit()
    entries2 = build_fiscal_fact_brief(db)
    relief = [
        e for e in entries2
        if e["subject_kind"] == "army" and e["subject_id"] == "shaanxi_army"
        and str(e["detail"]).startswith("补发_")
    ]
    assert relief and relief[0]["value"] < 0 and relief[0]["affected_class"] == "军户"
    assert relief[0]["origin_ref"] == f"dossier:{did}"


# ═══════════════ F3 LLM 综合归因边界 ═══════════════

def test_extraction_modules_unchanged_parallel():
    """F3 三断言之①：零新增 LLM 调用——模块清单与开工 head 动态一致，
    class_delta 仍由 internal 槽独占。"""
    from ming_sim.simulation import EXTRACTION_MODULES, MODULE_FIELDS
    baseline_modules = tuple(MODULE_FIELDS)
    assert EXTRACTION_MODULES == baseline_modules
    assert len(EXTRACTION_MODULES) == len(baseline_modules)
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


def test_apply_score_extraction_accepts_llm_direction_with_fiscal_loss(game):
    """F3.2：单一财政受损事实在案时，LLM 综合判断的正向 satisfaction 原样接收。"""
    from ming_sim.issues import apply_score_extraction

    db, state, _content = game
    db.conn.execute(
        "UPDATE armies SET province_pay_arrears = 12.0, "
        "arrears = 12.0 + central_pay_arrears WHERE id = 'shaanxi_army'"
    )
    db.conn.commit()
    assert build_fiscal_fact_brief(db)
    applied = apply_score_extraction(
        db, state, {"class_delta": {"军户": {"satisfaction": 9}}}
    )
    assert applied["class_delta"]["军户"]["satisfaction"] == 9
    assert applied["class_delta_rejections"] == []


# ═══════════════ F1 颁布生命周期 E2E（ADR 0055 判后物化缝）═══════════════

def test_lifecycle_promulgated_materializes_and_next_settlement_reads(game):
    """顺颁：判决当回合落 config；本月已按旧序完成的结算不追溯、下一次结算读取。"""
    db, state, _content = game
    turn = db._current_settle_turn()
    # 本月结算先按旧序完成（fixed flow 已结束的等价断言：旧序结果在案）
    before = db.settle_province_tick("shaanxi")
    assert before.breakdown["实付分账"]["军饷"] > 0

    entries = [{"key": "due_priority_军饷@shaanxi", "value": 40}]
    did = _override_dossier(db, state, entries)
    db.apply_dossier_promulgation(state, did, "promulgated")
    # 判后物化：config 在案 + provenance 指向案卷
    assert db.get_fiscal_config()["due_priority_军饷@shaanxi"] == 40
    row = db.conn.execute(
        "SELECT origin_ref FROM fiscal_config_changes WHERE key='due_priority_军饷@shaanxi'"
    ).fetchone()
    assert row["origin_ref"] == f"dossier:{did}"
    # 案卷顺颁即终局（无执行判定面）
    assert db.get_decree_dossier(did)["status"] == "closed"
    # 下一次结算读取新序（同 turn 重算即读新旨＝读端按当前在位键解析）
    after = db.settle_province_tick("shaanxi")
    assert after.breakdown["实付分账"]["军饷"] < before.breakdown["实付分账"]["军饷"]


def test_lifecycle_rejected_decree_zero_config_write(game):
    """⑥打回：效果跟判决走——零 config 写入、零 provenance、结算照默认序。"""
    from dossier_test_helpers import rejected_verdict

    db, state, _content = game
    did = _override_dossier(db, state, [{"key": "due_priority_军饷", "value": 40}])
    before_cfg = db.get_fiscal_config()
    before_rows = db.conn.execute(
        "SELECT COUNT(*) c FROM fiscal_config_changes"
    ).fetchone()["c"]
    db.apply_dossier_verdicts(state, [rejected_verdict(did)])
    assert db.get_fiscal_config() == before_cfg          # 零写入
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM fiscal_config_changes"
    ).fetchone()["c"] == before_rows                      # 零 provenance
    assert db.get_decree_dossier(did)["status"] == "proposed"  # 打回持有态


def test_lifecycle_force_promulgation_after_rejection(game):
    """强颁：中旨标记＋代价照 0055/0056 落，config 自下一次结算生效。"""
    from dossier_test_helpers import rejected_verdict

    db, state, _content = game
    did = _override_dossier(db, state, [{"key": "due_haircut_bp_宗禄", "value": 5000}])
    db.apply_dossier_verdicts(state, [rejected_verdict(did)])
    assert "due_haircut_bp_宗禄" not in db.get_fiscal_config()   # 打回零写
    db.apply_dossier_promulgation(state, did, "force_promulgated")
    assert db.get_fiscal_config()["due_haircut_bp_宗禄"] == 5000  # 强颁物化
    assert db.dossier_authorizes_effects(did)


def test_stale_until_cleared_by_permanent_overwrite(game):
    """F1.4：有期限旨被后来的永久旨覆盖 → 遗留 _until_turn 清除，新旨不再到期。"""
    db, state, _content = game
    turn = db._current_settle_turn()
    d1 = _override_dossier(db, state, [
        {"key": "due_priority_军饷", "value": 40, "until_turn": turn + 1},
    ])
    db.apply_dossier_promulgation(state, d1, "promulgated")
    assert "due_priority_军饷_until_turn" in db.get_fiscal_config()
    d2 = _override_dossier(db, state, [{"key": "due_priority_军饷", "value": 30}])
    db.apply_dossier_promulgation(state, d2, "promulgated")   # 永久旨覆写
    cfg = db.get_fiscal_config()
    assert "due_priority_军饷_until_turn" not in cfg       # stale until 已清
    assert cfg["due_priority_军饷"] == 30                  # 新永久旨在位
    # tombstone append-only 审计在案（复用既有表，不增表）
    tomb = db.conn.execute(
        "SELECT key, value, origin_ref FROM fiscal_config_tombstones "
        "WHERE key='due_priority_军饷_until_turn' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert tomb is not None and tomb["origin_ref"] == f"dossier:{d2}"
    # 跨过旧期限后新旨仍生效（修复前：旧 until 使新旨过期回落默认）
    res = resolve_pay_order_overrides(db.get_fiscal_config(), "shaanxi", turn + 2)
    assert res is not None
    assert res.due_order == ("官俸", "军饷", "宗禄", "赈济")  # 军饷序位30（与宗禄并列按基准 tie-break）


def test_staging_rejects_illegal_entries_fail_loud(game):
    """成案点先验：非法键形/幻影 region 收夜即响亮拒，不入案卷。"""
    db, state, _content = game
    with pytest.raises(ValueError):
        _override_dossier(db, state, [{"key": "due_priority_盐课", "value": 10}])
    with pytest.raises(ValueError):
        _override_dossier(db, state, [
            {"key": "due_haircut_bp_军饷@SX#province", "value": 5000},
        ])
    with pytest.raises(ValueError):
        _override_dossier(db, state, [{"key": "due_haircut_bp_宗禄", "value": 20000}])
    with pytest.raises(ValueError):
        _override_dossier(db, state, [])


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

def test_central_due_haircut_consumer(game):
    """中央份额 Due 折发读端：floor 折算、余数免除、地域/饷源精确、无折恒等。"""
    from ming_sim.flows import _central_dues_with_haircut, army_needed

    db, state, _content = game
    rows = db.conn.execute(
        "SELECT id, name, manpower, salary_rate, owner_power, pay_source_region, "
        "central_pay_share FROM armies WHERE central_pay_share > 0 ORDER BY rowid"
    ).fetchall()
    base_dues, base_exempt = _central_dues_with_haircut(db, state, rows)
    assert base_exempt == {}
    shaanxi_raw = army_needed(
        next(r for r in rows if r["id"] == "shaanxi_army"),
    ) * 0.35
    assert base_dues["shaanxi_army"] == pytest.approx(shaanxi_raw)

    did = _override_dossier(db, state, [
        {"key": "due_haircut_bp_军饷@shaanxi#central", "value": 5000},
        {"key": "due_haircut_bp_军饷#central", "value": 6000},
    ])
    db.apply_dossier_promulgation(state, did, "promulgated")
    dues, exempt = _central_dues_with_haircut(db, state, rows)
    # 陕西中央侧取 @shaanxi#central=5000：floor(2.1×0.5)=1.0，免除 1.1
    assert dues["shaanxi_army"] == pytest.approx(float(math.floor(shaanxi_raw * 0.5)))
    assert exempt["shaanxi_army"] == pytest.approx(shaanxi_raw - math.floor(shaanxi_raw * 0.5))
    # 他省中央侧取 #central=6000（京营 beizhili：need=ceil(85000*1/10000)=9，raw=9.0）
    jy_raw = army_needed(next(r for r in rows if r["id"] == "jingying")) * 1.0
    assert dues["jingying"] == pytest.approx(math.floor(jy_raw * 0.6))
    # 免除不入欠：欠发只按折后应得计（shortfall 上界即折后 due）


def test_pure_central_zero_haircut_due_clears_shortfall_counter(game):
    """#651×#653：纯中央军合法折发后 Due floor=0 须归零连续缺口计数，且不自动还旧欠。"""
    from ming_sim.flows import (
        _central_dues_with_haircut,
        apply_fixed_period_flows,
        army_needed,
    )

    db, state, _content = game
    assert db.is_substrate_hub_fiscal_engine_enabled()

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

    dues, _exempt = _central_dues_with_haircut(db, state, [army])
    raw_due = army_needed(army) * float(army["central_pay_share"] or 0)
    assert raw_due > 0
    assert dues["jingying"] == pytest.approx(0.0)

    apply_fixed_period_flows(db, state)

    after = db.conn.execute(
        "SELECT consecutive_pay_shortfall_months, central_pay_arrears, arrears "
        "FROM armies WHERE id = 'jingying'"
    ).fetchone()
    assert int(after["consecutive_pay_shortfall_months"] or 0) == 0
    # 中央旧欠不因零 Due 月自动偿还（ADR 0023 D7③ / #653 边界）
    assert float(after["central_pay_arrears"] or 0) == pytest.approx(old_central_arrears)
    assert float(after["arrears"] or 0) == pytest.approx(old_arrears)


def test_central_hub_tier_order_and_old_arrears_unchanged_by_haircut(game):
    """宪法边界 golden：hub tier 序/D9 合并 k 公式/中央旧欠不自动偿还均不被折发改写。"""
    import inspect

    from ming_sim.flows import _compute_substrate_hub_outbound

    src = inspect.getsource(_compute_substrate_hub_outbound)
    # D9 合并 k 分母仍是 Σ(京运补+中央军饷应付)，公式未被折发旁路
    assert "tier_due_total = jingyun_due_total + central_due_total" in src
    assert "k = (" in src
    # 中央旧欠无自动偿还位：中央路径只增欠（old_central_arrears + shortfall），无偿还分支
    from ming_sim import flows as flows_mod
    apply_src = inspect.getsource(flows_mod.apply_fixed_period_flows)
    assert "old_central_arrears + shortfall" in apply_src
    central_arrears_assignment = next(
        line for line in apply_src.splitlines()
        if "central_arrears = max(0.0, old_central_arrears + shortfall)" in line
    )
    assert "min(" not in central_arrears_assignment


# ═══════════════ 独立 oracle 宪制 mutation 自验 ═══════════════

def test_oracle_independent_of_shared_haircut_helper(monkeypatch):
    """mutation①破坏舍入：落账侧 floor 改 ceil → 独立 oracle 必红。"""
    import ming_sim.fiscal_tick as ft

    st, p = _board(gross=50.0)
    p["Due"] = {"军饷": 18.0, "官俸": 3.0, "宗禄": 101.0, "赈济": 1.0}
    p["due_haircut_bp"] = {"宗禄": 5000}

    def biased_effective(pp):
        raw = pp.get("due_haircut_bp") or {}
        out = {}
        for h in ft._DUE_KEYS:
            d = float(pp["Due"].get(h, 0.0))
            bp = raw.get(h)
            out[h] = float(math.ceil(d * bp / 10000)) if bp else d
        return out

    monkeypatch.setattr(ft, "_effective_dues", biased_effective)
    with pytest.raises(ft.FiscalConservationError):
        settle_tick(st, p, [])


def test_oracle_independent_of_shared_order_resolver(monkeypatch):
    """mutation②破坏优先序：落账侧序解析被劫持 → 独立 oracle 必红。
    盘面须让序真正改变分配：池不足（新债落点随序变）＋多账户旧欠。"""
    import ming_sim.fiscal_tick as ft

    st, p = _board(gross=0.0)  # 省内池 10 < Due 合计 26.07：付款序决定新债落点
    st["官俸欠"] = 5.0
    monkeypatch.setattr(
        ft, "_resolve_order_param",
        lambda pp, key, default: tuple(reversed(default)),
    )
    with pytest.raises(ft.FiscalConservationError):
        settle_tick(st, p, [])


def test_oracle_independent_of_debt_mapping(monkeypatch):
    """mutation③破坏映射：落账侧 Due→CLAIM 映射错位 → 独立 oracle 必红。"""
    import ming_sim.fiscal_tick as ft

    st, p = _board(gross=0.0)
    monkeypatch.setattr(
        ft, "_DEBT_OF_DUE", {"军饷": "官俸欠", "官俸": "官俸欠", "宗禄": "宗禄欠"},
    )
    with pytest.raises((ft.FiscalConservationError, ValueError)):
        settle_tick(st, p, [])


# ═══════════════ F2 投影真源修正 goldens（judge r2 class②）═══════════════

def test_fact_brief_per_source_windows_and_region_attribution(game):
    """分源欠饷月数＝ceil(分源现欠/月需)，province/central 各自独立成窗；
    army 级事实带属地 region（=pay_source_region）；零分母短路不计。"""
    from ming_sim.flows import army_needed

    db, _state, _content = game
    # xuan_da：need=ceil(65000×1.5/10000)=10；两源现欠钉成不同值 → 窗口必然不同
    db.conn.execute(
        "UPDATE armies SET province_pay_arrears=25.0, central_pay_arrears=12.0,"
        " arrears=37.0 WHERE id='xuan_da'"
    )
    # 零分母：manpower=0 → need=0，即便残留欠额也不计（0023 D6/D11）
    db.conn.execute(
        "UPDATE armies SET manpower=0, province_pay_arrears=5.0, arrears=5.0"
        " WHERE id='southwest_tusi'"
    )
    db.conn.commit()
    entries = build_fiscal_fact_brief(db)
    xuan = {
        e["detail"]: e for e in entries
        if e["subject_id"] == "xuan_da" and e["metric"] == "分源欠饷月数"
    }
    assert set(xuan) == {"province", "central"}
    assert xuan["province"]["window_turns"] == 3   # ceil(25/10)
    assert xuan["central"]["window_turns"] == 2    # ceil(12/10)
    assert xuan["province"]["value"] == pytest.approx(25.0)
    assert xuan["central"]["value"] == pytest.approx(12.0)
    for e in xuan.values():
        assert e["region"] == "shanxi"             # 属地随 pay_source_region 归因
        assert e["affected_class"] == "军户"
    # 零分母军不出窗
    assert not any(
        e["subject_id"] == "southwest_tusi" and e["metric"] == "分源欠饷月数"
        for e in entries
    )
    assert army_needed(db.conn.execute(
        "SELECT owner_power, manpower, salary_rate FROM armies WHERE id='southwest_tusi'"
    ).fetchone()) == 0


def test_fact_brief_zero_need_army_region_attribution_not_gated(game):
    """零需残军（manpower=0 携历史欠，0023 D6/D11）属地归因不被 need 门误删：
    月需=0 只短路欠饷月数计算（不做除法），army 仍入 region_of_army 册——
    其省源偿欠受益事实照常带 pay_source_region 归因，不落成无属地。"""
    from ming_sim.flows import army_needed

    db, state, _content = game
    turn = db._current_settle_turn()
    db.conn.execute(
        "UPDATE armies SET manpower=0, province_pay_arrears=5.0"
        " WHERE id='shaanxi_army'"
    )
    db.conn.execute(
        "INSERT INTO army_logs (turn, year, period, army_id, field, old_value,"
        " new_value, delta, reason, actor)"
        " VALUES (?, 1, 1, 'shaanxi_army', 'province_pay_arrears', '5.0',"
        " '2.0', -3.0, '按省份额欠余额占比偿还', '户部')",
        (turn,),
    )
    db.conn.commit()
    assert army_needed(db.conn.execute(
        "SELECT owner_power, manpower, salary_rate FROM armies WHERE id='shaanxi_army'"
    ).fetchone()) == 0
    entries = build_fiscal_fact_brief(db)
    # 零分母军不出欠饷月数窗
    assert not any(
        e["subject_id"] == "shaanxi_army" and e["metric"] == "分源欠饷月数"
        for e in entries
    )
    # 但属地归因在案：偿欠受益事实带 pay_source_region，非空串
    repaid = [
        e for e in entries
        if e["subject_id"] == "shaanxi_army" and e["detail"] == "省源偿欠"
    ]
    assert repaid and repaid[0]["value"] == pytest.approx(-3.0)
    assert repaid[0]["region"] == "shaanxi"


def test_fact_brief_central_haircut_floor_per_army_matches_real_accounting(game):
    """多军同省中央折发：投影复用 flows._central_dues_with_haircut 唯一读端——每军各自
    floor（账实同舍入），禁先聚省再舍入。beizhili 三军 raw=9.0/4.0/7.2、bp=5000：
    每军 floor 免除合计=5.0+2.0+4.2=11.2 ≠ 聚省后 floor 的 20.2×0.5→免除 10.1。"""
    from ming_sim.flows import _central_dues_with_haircut

    db, state, _content = game
    did = _override_dossier(
        db, state, [{"key": "due_haircut_bp_军饷#central", "value": 5000}],
    )
    db.apply_dossier_promulgation(state, did, "promulgated")
    rows = db.conn.execute(
        "SELECT id, name, manpower, salary_rate, owner_power, pay_source_region, "
        "central_pay_share FROM armies WHERE central_pay_share > 0 ORDER BY rowid"
    ).fetchall()
    _, exempts = _central_dues_with_haircut(db, state, rows)
    expected_bz = sum(
        exempts[r["id"]] for r in rows if r["pay_source_region"] == "beizhili"
    )
    assert expected_bz == pytest.approx(11.2)      # 每军 floor 后的免除合计
    entries = build_fiscal_fact_brief(db)
    cut = [
        e for e in entries
        if e["subject_id"] == "beizhili" and e["detail"] == "折发_军饷#central"
    ]
    assert len(cut) == 1
    assert cut[0]["value"] == pytest.approx(expected_bz)
    assert cut[0]["value"] != pytest.approx(10.1)  # 聚省再舍入的伪重建值必不相同
    assert cut[0]["origin_ref"] == f"dossier:{did}"


def test_fact_brief_unmet_relief_is_current_turn_damage(game):
    """赈济未敷（unmet_relief）＝settle_tick 落进 st 的当月流量 → 农民受损事实在案。"""
    import json as _json

    db, _state, _content = game
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = _json.loads(row["fiscal"])
    fiscal["settle"]["st"]["unmet_relief"] = 5.0
    db.conn.execute(
        "UPDATE regions SET fiscal=? WHERE id='shaanxi'",
        (_json.dumps(fiscal, ensure_ascii=False),),
    )
    db.conn.commit()
    entries = build_fiscal_fact_brief(db)
    unmet = [
        e for e in entries
        if e["subject_id"] == "shaanxi" and e["detail"] == "赈济未敷"
    ]
    assert unmet and unmet[0]["value"] == pytest.approx(5.0)
    assert unmet[0]["affected_class"] == "农民"
    assert unmet[0]["origin_ref"] == "region:shaanxi:settle.st.unmet_relief"


def test_fact_brief_province_auto_repaied_is_beneficiary_fact(game):
    """省池自动偿还（surplus waterfall）＝army_logs 当月负 delta → 军户受益事实（<0）。"""
    db, state, _content = game
    turn = db._current_settle_turn()
    db.conn.execute(
        "INSERT INTO army_logs (turn, year, period, army_id, field, old_value,"
        " new_value, delta, reason, actor)"
        " VALUES (?, 1, 1, 'shaanxi_army', 'province_pay_arrears', '16.25',"
        " '10.25', -6.0, '按省份额欠余额占比偿还', '户部')",
        (turn,),
    )
    db.conn.commit()
    entries = build_fiscal_fact_brief(db)
    repaid = [
        e for e in entries
        if e["subject_id"] == "shaanxi_army" and e["detail"] == "省源偿欠"
    ]
    assert repaid and repaid[0]["value"] == pytest.approx(-6.0)
    assert repaid[0]["region"] == "shaanxi"
    assert repaid[0]["origin_ref"].startswith("army_logs:")


def test_fact_brief_long_term_stock_not_fed_as_turn_damage(game):
    """回归钉死：长期 st 欠额存量（官俸欠/宗禄欠）不再生成受损事实——归因对象只准是
    本回合分量（上轮既禁旧行为）。"""
    import json as _json

    db, _state, _content = game
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id='shaanxi'").fetchone()
    fiscal = _json.loads(row["fiscal"])
    fiscal["settle"]["st"]["官俸欠"] = 50.0
    fiscal["settle"]["st"]["宗禄欠"] = 60.0
    db.conn.execute(
        "UPDATE regions SET fiscal=? WHERE id='shaanxi'",
        (_json.dumps(fiscal, ensure_ascii=False),),
    )
    db.conn.commit()
    entries = build_fiscal_fact_brief(db)
    assert not [e for e in entries if e["affected_class"] == "官僚"]
    assert not [e for e in entries if e["affected_class"] == "宗藩"]


# ═══════════════ 真实玩家生产入口 E2E（capture→成案→pre_settle/settle_with_delta）═══

def _pin_shortfall_board(db, region_id):
    """省内池不足盘面钉死（拨付gross=0 → hub 京运补 due=0，p 原样进 tick）：
    付款序决定新债落点，确定性可断言。"""
    import json as _json

    st = {
        "省库库银": 0.0, "C_地方截留": 0.0, "C_中饱": 0.0, "C_漂没": 0.0,
        "C_eff损耗": 0.0, "民欠旧赋": 0.0, "军饷欠": 20.0, "官俸欠": 0.0,
        "宗禄欠": 0.0, "官民田": 100.0, "隐田": 50.0,
    }
    p = {
        "正赋应征": 8.0, "三饷应征": 2.0, "火耗率": 0.1, "逋赋率": 0.0,
        "起运定额": 0.0, "漂没率": 0.0, "中饱率": 0.0, "拨付gross": 0.0,
        "Due": {"军饷": 18.0, "官俸": 3.0, "宗禄": 4.07, "赈济": 1.0},
    }
    row = db.conn.execute("SELECT fiscal FROM regions WHERE id=?", (region_id,)).fetchone()
    fiscal = _json.loads(row["fiscal"])
    fiscal["settle"]["st"] = st
    fiscal["settle"]["p"] = p
    db.conn.execute(
        "UPDATE regions SET fiscal=? WHERE id=?",
        (_json.dumps(fiscal, ensure_ascii=False), region_id),
    )
    db.conn.commit()


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
    dossier = db.get_dossier_for_directive(dv.id)
    assert dossier is not None
    assert dossier["action_type"] == "pay_order_override"
    return int(dossier["id"])


def test_lifecycle_e2e_capture_to_next_settlement_via_settle_with_delta(game, monkeypatch):
    """顺颁全链 E2E：拟旨 capture→草案→成案 staging→settle_with_delta 判决→结算尾段
    atomic 物化（本月已按旧序完成＝不追溯）→下一次真实 pre_settle 结算读取新序。
    陕西/河南同盘面对照：旨域外省份逐字节照旧（回归不破）。"""
    from ming_sim.decree import pre_settle, settle_with_delta

    db, state, content = game
    _pin_shortfall_board(db, "shaanxi")
    _pin_shortfall_board(db, "henan")
    opening = {
        rid: _opening_settle(db, rid) for rid in ("shaanxi", "henan")
    }
    did = _capture_override_decree(game, monkeypatch, "今岁边饷居末、官俸优先", [
        {"key": "due_priority_军饷@shaanxi", "value": 40},
        {"key": "due_priority_官俸@shaanxi", "value": 10},
    ])
    # 判决前零物化（案卷 staging 只验形、不写 config——禁旁路第二真源）
    assert "due_priority_军饷@shaanxi" not in db.get_fiscal_config()

    # 月 T：真实两括号编排（pre_settle 固定财政 + settle_with_delta 判决尾段物化）。
    # 饷率通道（apply_historical_fiscal_rates）在 tick 前重写 p 的三饷/起运并持久化，
    # 故纯函数期望用 pre_settle 后持久化的 p_eff（即 tick 实际消费的同份 p）。
    pre_settle(state, db, content=content)
    settle_with_delta(
        state, db, {}, before_turn=state.turn, content=content,
        dossier_verdicts=[{"dossier_id": did, "decision": "promulgated"}],
    )
    cfg = db.get_fiscal_config()
    assert cfg["due_priority_军饷@shaanxi"] == 40
    assert cfg["due_priority_官俸@shaanxi"] == 10
    row = db.conn.execute(
        "SELECT origin_ref FROM fiscal_config_changes "
        "WHERE key='due_priority_军饷@shaanxi' ORDER BY id LIMIT 1"
    ).fetchone()
    assert row["origin_ref"] == f"dossier:{did}"
    assert db.get_decree_dossier(did)["status"] == "closed"  # 颁布即终局

    # 月 T 本月已按旧序完成：陕西月末态＝无旨纯函数基线（当月不追溯）。
    # 军饷欠 CLAIM 在饷源 cutover 下由 per-army 双累加器对账拥有，除外后逐字节比对。
    p_eff_sx = copy.deepcopy(_opening_settle(db, "shaanxi")["p"])
    p_eff_hn = copy.deepcopy(_opening_settle(db, "henan")["p"])
    after_t = {rid: _opening_settle(db, rid) for rid in ("shaanxi", "henan")}
    month_t = settle_tick(copy.deepcopy(opening["shaanxi"]["st"]), p_eff_sx, [])
    def _minus_military_claim(st):
        return {k: v for k, v in st.items() if k != "军饷欠"}
    assert _minus_military_claim(after_t["shaanxi"]["st"]) == _minus_military_claim(month_t.new_st)
    sx_army_before = float(db.conn.execute(
        "SELECT province_pay_arrears FROM armies WHERE id='shaanxi_army'"
    ).fetchone()[0])

    # 月 T+1：下一次结算读取新序（真实 pre_settle 省级 tick；河南无旨照旧序对照）。
    # 陕西：官俸优先→宗禄足付（宗禄欠零增长）；河南旧序：宗禄继续被欠。
    pre_settle(state, db, content=content)
    settle_with_delta(state, db, {}, before_turn=state.turn, content=content)
    after_t1 = {rid: _opening_settle(db, rid) for rid in ("shaanxi", "henan")}
    p_new = dict(p_eff_sx)
    # 军饷序位40 与赈济默认40 并列 → 默认基准 tie-break（军饷先于赈济）
    p_new["due_order"] = ["官俸", "宗禄", "军饷", "赈济"]
    expect_sx = settle_tick(copy.deepcopy(after_t["shaanxi"]["st"]), p_new, [])
    expect_hn = settle_tick(copy.deepcopy(after_t["henan"]["st"]), p_eff_hn, [])
    assert _minus_military_claim(after_t1["shaanxi"]["st"]) == _minus_military_claim(expect_sx.new_st)
    assert _minus_military_claim(after_t1["henan"]["st"]) == _minus_military_claim(expect_hn.new_st)
    assert after_t1["shaanxi"]["st"] != after_t1["henan"]["st"]  # 旨效真实偏离对照省
    assert after_t1["shaanxi"]["st"]["宗禄欠"] == after_t["shaanxi"]["st"]["宗禄欠"]
    assert after_t1["henan"]["st"]["宗禄欠"] > after_t["henan"]["st"]["宗禄欠"]
    # 边饷居末：陕西军省份额积欠增加（对照省军饷照旧序优先支付）
    sx_army_after = float(db.conn.execute(
        "SELECT province_pay_arrears FROM armies WHERE id='shaanxi_army'"
    ).fetchone()[0])
    assert sx_army_after > sx_army_before


def test_lifecycle_e2e_rejected_then_force_via_settlement_pipeline(game, monkeypatch):
    """打回＋强颁走真实结算管线：settle_with_delta 内 rejected verdict 零 config 写入；
    同事务批红强颁（rescript action）→ 物化仍在本月结算之后 → 下一次结算才吃折发。"""
    from dossier_test_helpers import rejected_verdict

    from ming_sim.decree import pre_settle, settle_with_delta

    db, state, content = game
    _pin_shortfall_board(db, "shaanxi")
    opening = _opening_settle(db, "shaanxi")
    did = _capture_override_decree(game, monkeypatch, "今岁宗禄折半", [
        {"key": "due_haircut_bp_宗禄@shaanxi", "value": 5000},
    ])

    # 月 T：打回判决（零写入）＋同事务批红强颁（效果跟判决走）
    before_cfg = db.get_fiscal_config()
    before_rows = db.conn.execute(
        "SELECT COUNT(*) c FROM fiscal_config_changes"
    ).fetchone()["c"]
    pre_settle(state, db, content=content)
    settle_with_delta(
        state, db, {}, before_turn=state.turn, content=content,
        dossier_verdicts=[rejected_verdict(did)],
        dossier_rescript_actions=[{"dossier_id": did, "decision": "force_promulgated"}],
    )
    # 打回阶段零写入：全部 provenance 变化均来自强颁物化（无期限旨只有主键一行）
    rows = db.conn.execute("SELECT key FROM fiscal_config_changes").fetchall()
    assert {r["key"] for r in rows} == {"due_haircut_bp_宗禄@shaanxi"}
    cfg = db.get_fiscal_config()
    assert cfg["due_haircut_bp_宗禄@shaanxi"] == 5000       # 强颁物化
    assert cfg.get("due_haircut_bp_宗禄@shaanxi_until_turn") is None
    assert db.dossier_authorizes_effects(did)

    # 强颁发生在本月推演后：月 T 结算未吃折发（宗禄欠＝无折基线续延）。
    # 宗禄欠 CLAIM 不经 army 对账，可作纯函数字节断言。
    after_t = _opening_settle(db, "shaanxi")
    p_eff = copy.deepcopy(after_t["p"])
    month_t = settle_tick(copy.deepcopy(opening["st"]), p_eff, [])
    assert after_t["st"]["宗禄欠"] == month_t.new_st["宗禄欠"]

    # 月 T+1：折发生效——Due.宗禄 floor(4.07×5000/10000)=2.03 入付，折掉部分不入宗禄欠
    pre_settle(state, db, content=content)
    settle_with_delta(state, db, {}, before_turn=state.turn, content=content)
    after_t1 = _opening_settle(db, "shaanxi")
    p_half = dict(p_eff)
    p_half["due_haircut_bp"] = {"宗禄": 5000}
    expect = settle_tick(copy.deepcopy(after_t["st"]), p_half, [])
    assert after_t1["st"]["宗禄欠"] == expect.new_st["宗禄欠"]
    # 折半后宗禄应得减半：月末宗禄欠增量低于无折基线（免除不入欠的守恒方向）
    assert (after_t1["st"]["宗禄欠"] - after_t["st"]["宗禄欠"]) < (
        month_t.new_st["宗禄欠"] - opening["st"]["宗禄欠"]
    )


# ═══════════════ F2.3（owner 拍板 r5）：官俸欠/宗禄欠当回合流量持久留痕 ═══════════════

def test_claim_flow_logs_persisted_in_settle_bridge_and_restore_e2e(game):
    """省级结算桥同事务把 官俸欠/宗禄欠 当回合 NewDebt/Repaid 流量补记进 region_logs
    （复用现有结算留痕载体，零新表）；fiscal_fact_brief 补这两科目本回合分量；
    关闭重开 DB（restore）后投影逐字节可恢复。"""
    from ming_sim.db import GameDB

    db, state, content = game
    _pin_shortfall_board(db, "shaanxi")
    result = db.settle_province_tick("shaanxi")
    db.conn.commit()

    # 桥同事务落痕：行集＝breakdown 两科目非零流量（零流量不写行）；本盘面
    # 省内池不足、无 surplus → Repaid 全零不写，NewDebt 行在案。
    expect_flows = {
        (f"settle_{claim}_{flow}", float(source[claim]))
        for flow, source in (("NewDebt", result.breakdown["NewDebt"]),
                             ("Repaid", result.breakdown["Repaid"]))
        for claim in ("官俸欠", "宗禄欠") if abs(float(source[claim])) > 1e-9
    }
    assert expect_flows, "盘面应至少产生一笔非零官俸/宗禄欠流量"
    rows = db.conn.execute(
        "SELECT field, delta, turn, region_id, actor, origin_ref FROM region_logs "
        "WHERE field LIKE 'settle_%' ORDER BY id"
    ).fetchall()
    assert {(r["field"], float(r["delta"])) for r in rows} == expect_flows
    assert all(r["turn"] == state.turn and r["region_id"] == "shaanxi" for r in rows)
    assert all(r["actor"] == "户部" and r["origin_ref"] == "region:shaanxi:settle_tick"
               for r in rows)

    # 投影：两科目本回合分量进 fact brief（metric=欠禄额 族，detail 区分；
    # NewDebt>0 受损、Repaid<0 受益符号域）
    entries = [e for e in build_fiscal_fact_brief(db) if e["detail"].startswith("省池_")]
    assert {(e["detail"], e["value"]) for e in entries} == {
        (detail, float(value) if detail.endswith("_NewDebt") else -float(value))
        for detail, value in {
            f"省池_{claim}_{flow}": source[claim]
            for flow, source in (("NewDebt", result.breakdown["NewDebt"]),
                                 ("Repaid", result.breakdown["Repaid"]))
            for claim in ("官俸欠", "宗禄欠") if abs(float(source[claim])) > 1e-9
        }.items()
    }
    assert all(e["metric"] == "欠禄额" and e["affected_class"] in {"官僚", "宗藩"}
               and e["window_turns"] == 1 for e in entries)
    before_tsv = format_fiscal_fact_brief_tsv(
        [e for e in build_fiscal_fact_brief(db)],
    )

    # restore E2E：关闭重开同一档文件，留痕随档恢复、投影逐字节一致
    path = db.path
    db.close()
    db2 = GameDB(path, content)
    try:
        after_tsv = format_fiscal_fact_brief_tsv(
            [e for e in build_fiscal_fact_brief(db2)],
        )
        assert after_tsv == before_tsv
    finally:
        db2.close()
