from __future__ import annotations
from ming_sim.settlement.dossier import apply_dossier_promulgation, apply_dossier_verdicts
import copy
import math
import pytest
from ming_sim.fiscal_tick import settle_tick
from ming_sim.settlement import SettlementContext, settle_delta
from ming_sim.settlement.views import section
from ming_sim.pay_order import (
    PayOrderKeyError,
    materialize_pay_order_decree,
    parse_override_key,
    resolve_pay_order_overrides,
    restore_pay_order_override,
)
import json
from ming_sim.pay_order import PayOrderKeyError, restore_pay_order_override, materialize_pay_order_decree
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#653 / ADR 0090 偿还序 override ＋ Due 折发系数＋阶级怨气喂判。

票面（冻结票面含 r1–r4 修正案）验收表 golden ①–⑦ ＋ r4 canonical region goldens
＋ F2 六源纯投影 TSV 断言 ＋ F3 综合归因输入 / 零新增调用断言。
"""




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



def test_origin_ref_must_be_dossier_provenance(game):
    db, _state, _content = game
    with pytest.raises(ValueError):
        materialize_pay_order_decree(
            db, turn=1,
            entries=[{"key": "due_priority_军饷", "value": 40}],
            origin_ref="随手写的",
        )

# ═══════════════ r3/r4 读取优先级全序 goldens ═══════════════





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

    db, state, _content = game
    db.conn.execute(
        "UPDATE armies SET province_pay_arrears = 12.0 WHERE id = 'shaanxi_army'"
    )
    db.conn.commit()
    applied = settle_delta(state, db, {"class_delta": {"军户": {"satisfaction": 9}}}, SettlementContext())
    assert {k: v for k, v in applied.social_class.applied}["军户"]["satisfaction"] == 9
    assert section(applied, "class_delta").rejected == []

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
            origin_ref="dossier:99999",       # 案卷不存在
        )
    # 未过颁布门（proposed）的案卷禁物化
    did = _override_dossier(db, state, [{"key": "due_priority_军饷", "value": 40}])
    with pytest.raises(ValueError):
        materialize_pay_order_decree(
            db, turn=state.turn,
            entries=[{"key": "due_priority_军饷", "value": 40}],
            origin_ref=f"dossier:{did}",
        )

# ═══════════════ 中央侧折发消费者（flows 读端）═══════════════





# ═══════════════ F2 投影真源修正 goldens（judge r2 class②）═══════════════

# ═══════════════ 拟旨 capture→成案（财政物化与下一次省 tick 分别由上方领域用例覆盖）═══




# ═══════════════ F2.3（owner 拍板 r5）：官俸欠/宗禄欠当回合流量持久留痕 ═══════════════


def test_rejected_revoke_does_not_restore_override(game):
    """打回 revoke：owner seam 响亮拒绝，在位 override/期限/审计零变化。"""
    from dossier_test_helpers import rejected_verdict

    db, state, _content = game
    until = db.reign.current_settle_turn() + 2
    target = _override_dossier(db, state, [{
        "key": "due_priority_军饷@shaanxi", "value": 40, "until_turn": until,
    }])
    apply_dossier_promulgation(db, state, target, "promulgated")
    revoke = db.create_decree_dossier(
        state,
        action_type="revoke_decree",
        decree_text="撤回前旨",
        target_kind="dossier",
        target_id=str(target),
        payload={"revoke_target_dossier_id": target},
    )
    apply_dossier_verdicts(db, state, [rejected_verdict(revoke)])
    before_cfg = dict(db.fiscal_config.values())
    with pytest.raises(PayOrderKeyError):
        restore_pay_order_override(
            db,
            turn=db.reign.current_settle_turn(),
            target_dossier_id=target,
            revoke_dossier_id=revoke,
            reason="打回不得删 config",
        )
    cfg = db.fiscal_config.values()
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


def test_revoke_later_same_dim_decree_not_stomped(game):
    """Codex-11/revoke_shape_exit①：同维后旨在位时撤前旨，不改该键。"""
    db, state, _content = game
    first = _override_dossier(
        db, state, [{"key": "due_priority_军饷@shaanxi", "value": 40}],
        text="前旨边饷居末",
    )
    apply_dossier_promulgation(db, state, first, "promulgated")
    second = _override_dossier(
        db, state, [{"key": "due_priority_军饷@shaanxi", "value": 5}],
        text="后旨边饷最前",
    )
    apply_dossier_promulgation(db, state, second, "promulgated")
    assert db.fiscal_config.values()["due_priority_军饷@shaanxi"] == 5
    revoke = db.create_decree_dossier(
        state, action_type="revoke_decree", decree_text="撤回前旨",
        target_kind="dossier", target_id=str(first),
        payload={"revoke_target_dossier_id": first},
    )
    apply_dossier_promulgation(db, state, revoke, "promulgated")
    cfg = db.fiscal_config.values()
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


def test_lifecycle_rejected_decree_zero_config_write(game):
    """⑥打回：效果跟判决走——零 config 写入、零 provenance、结算照默认序。"""
    from dossier_test_helpers import rejected_verdict

    db, state, _content = game
    did = _override_dossier(db, state, [{"key": "due_priority_军饷", "value": 40}])
    before_cfg = db.fiscal_config.values()
    before_rows = db.conn.execute(
        "SELECT COUNT(*) c FROM fiscal_config_changes"
    ).fetchone()["c"]
    apply_dossier_verdicts(db, state, [rejected_verdict(did)])
    assert db.fiscal_config.values() == before_cfg          # 零写入
    assert db.conn.execute(
        "SELECT COUNT(*) c FROM fiscal_config_changes"
    ).fetchone()["c"] == before_rows                      # 零 provenance
    assert db.dossiers.get(did)["status"] == "proposed"  # 打回持有态


def test_stale_until_cleared_by_permanent_overwrite(game):
    """F1.4：有期限旨被后来的永久旨覆盖 → 遗留 _until_turn 清除，新旨不再到期。"""
    db, state, _content = game
    turn = db.reign.current_settle_turn()
    d1 = _override_dossier(db, state, [
        {"key": "due_priority_军饷", "value": 40, "until_turn": turn + 1},
    ])
    apply_dossier_promulgation(db, state, d1, "promulgated")
    assert "due_priority_军饷_until_turn" in db.fiscal_config.values()
    d2 = _override_dossier(db, state, [{"key": "due_priority_军饷", "value": 30}])
    apply_dossier_promulgation(db, state, d2, "promulgated")   # 永久旨覆写
    cfg = db.fiscal_config.values()
    assert "due_priority_军饷_until_turn" not in cfg       # stale until 已清
    assert cfg["due_priority_军饷"] == 30                  # 新永久旨在位
    # tombstone append-only 审计在案（复用既有表，不增表）
    tomb = db.conn.execute(
        "SELECT key, value, origin_ref FROM fiscal_config_tombstones "
        "WHERE key='due_priority_军饷_until_turn' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert tomb is not None and tomb["origin_ref"] == f"dossier:{d2}"
    # 跨过旧期限后新旨仍生效（修复前：旧 until 使新旨过期回落默认）
    res = resolve_pay_order_overrides(db.fiscal_config.values(), "shaanxi", turn + 2)
    assert res is not None
    assert res.due_order == ("官俸", "军饷", "宗禄", "赈济")  # 军饷序位30（与宗禄并列按基准 tie-break）


def test_revoke_provincial_falls_back_to_nationwide(game):
    """Codex-11/revoke_shape_exit②：全国+省域并存时撤省域后该省回落全国键。"""
    db, state, _content = game
    nation = _override_dossier(
        db, state, [{"key": "due_priority_军饷", "value": 35}],
        text="全国边饷居后",
    )
    apply_dossier_promulgation(db, state, nation, "promulgated")
    local = _override_dossier(
        db, state, [{"key": "due_priority_军饷@shaanxi", "value": 50}],
        text="陕西边饷居末",
    )
    apply_dossier_promulgation(db, state, local, "promulgated")
    turn = db.reign.current_settle_turn()
    before = resolve_pay_order_overrides(db.fiscal_config.values(), "shaanxi", turn)
    assert before is not None and before.due_order.index("军饷") == 3  # 省域50居末
    revoke = db.create_decree_dossier(
        state, action_type="revoke_decree", decree_text="撤陕西旨",
        target_kind="dossier", target_id=str(local),
        payload={"revoke_target_dossier_id": local},
    )
    apply_dossier_promulgation(db, state, revoke, "promulgated")
    cfg = db.fiscal_config.values()
    assert "due_priority_军饷@shaanxi" not in cfg  # 省域形状退出，禁留 live 默认
    assert cfg["due_priority_军饷"] == 35  # 全国键仍在位
    after = resolve_pay_order_overrides(cfg, "shaanxi", turn)
    assert after is not None
    # 回落全国键 value=35：军饷与宗禄(30)后、在赈济(40)前 → 官俸/宗禄/军饷/赈济
    assert after.due_order == ("官俸", "宗禄", "军饷", "赈济")
    # 对照：河南无省域键，同读全国键
    assert resolve_pay_order_overrides(cfg, "henan", turn).due_order == after.due_order
