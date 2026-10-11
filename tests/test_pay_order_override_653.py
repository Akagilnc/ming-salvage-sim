#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""#653 / ADR 0090 偿还序 override ＋ Due 折发系数＋阶级怨气喂判。

票面（冻结票面含 r1–r4 修正案）验收表 golden ①–⑦ ＋ r4 canonical region goldens
＋ 省级 tick／region_logs 符号域负向契约。
"""
from __future__ import annotations

import copy

from tests.conftest import settle_region_tick

import pytest

from ming_sim.fiscal_tick import settle_tick
from ming_sim.pay_order import (
    PayOrderKeyError,
    materialize_pay_order_decree,
    parse_override_key,
    restore_pay_order_override,
)



from tests.fiscal_test_utils import settle_province_via_batch as _settle_tick


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

# ═══════════════ F1.6 验收表 golden ①–⑦ ═══════════════

def test_golden1_pay_order_reversal_breakdown():
    """①「边饷居末、官俸优先」：省内池不足时军饷先欠、官俸足付；实付分账读 breakdown。"""
    st, p = _board(gross=0.0)  # 省内可支＝实征 10，祖制序下全被军饷吃光
    base = settle_tick(copy.deepcopy(st), copy.deepcopy(p), [])
    assert base.breakdown["实付分账"]["军饷"] == pytest.approx(10.0)
    assert base.breakdown["NewDebt"]["军饷欠"] == pytest.approx(8.0)
    assert base.breakdown["NewDebt"]["官俸欠"] == pytest.approx(3.0)

    p2 = dict(p)
    p2["due_order"] = ["官俸", "宗禄", "赈济", "军饷"]
    res = settle_tick(st, p2, [])
    paid = res.breakdown["实付分账"]
    assert paid["官俸"] == pytest.approx(3.0)       # 官俸足付
    assert paid["军饷"] == pytest.approx(1.93)      # 边饷居末只捡残池
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
    active = _settle_tick(db, "shaanxi")
    assert active.breakdown["haircut_宗禄"] > 0

    # 届满月：turn > until → 全部回落默认，与同输入无旨基线逐字节一致
    db.conn.execute("UPDATE game_state SET turn = ? WHERE id = 1", (turn + 1,))
    cur = _opening_settle(db, "shaanxi")  # active 月已推进后的开账
    expected_default = settle_tick(
        copy.deepcopy(cur["st"]), copy.deepcopy(cur["p"]), [],
    )
    expired = _settle_tick(db, "shaanxi")
    assert expired.new_st == expected_default.new_st
    assert expired.breakdown == expected_default.breakdown
    # 键与 provenance 保留不删
    assert "due_priority_军饷@shaanxi_until_turn" in db.get_fiscal_config()
    # 撤销路径归 test_real_revoke_decree_*（revoke_decree 真入口）；
    # 已退役 revoke_pay_order_decree API 不得复活。

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
    with pytest.raises(PayOrderKeyError):
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
    with pytest.raises(PayOrderKeyError):
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


def test_real_revoke_restores_override_same_month_with_active_commitment(game):
    """#1894：目标挂 active 承诺时撤旨当月即恢复 override，不再等下一场挽留坚持。

    偿还序案卷无判定面：顺颁即 closed，但 override 键仍在 fiscal_config 在位。
    「已结案」不等于「实效已退」——这道旨仍须能从**召对撤令入口**撤销，
    走完暂存 → 成案 → 颁布判决的整条真实链，不直接调数据库写口。
    """
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    until = db._current_settle_turn() + 3
    target = _override_dossier(db, state, [{
        "key": "due_priority_军饷@shaanxi", "value": 40, "until_turn": until,
    }])
    db.apply_dossier_promulgation(state, target, "promulgated")
    assert db.get_decree_dossier(target)["status"] == "closed"
    assert "due_priority_军饷@shaanxi" in db.get_fiscal_config()
    issue_id = db.insert_issue(
        state, kind="initiative", title="边饷次序之诺", origin_kind="decree",
        origin_ref=f"dossier:{target}", cancellable="decree",
        commitment_kind="until_stop", bar_value=10, stage_text="在办",
        ongoing_effects={}, end_turn=state.turn + 12,
    )

    # 召对真入口：撤令经既有准入暂存（closed 但在位的偿还序旨须被准入）
    staged = dispatch_declaration(
        db, state,
        {"commissions": [{
            "text": "撤回前旨",
            "revoke": {"target_kind": "issue", "target_id": str(issue_id)},
        }]},
        minister_name="",
    )
    assert not staged.commissions.rejected, staged.commissions.rejected
    pending = int(staged.commissions.applied[0]["id"])
    db.commit_pending_actions(state, content=content)
    revoke = int(db.conn.execute(
        "SELECT id FROM decree_dossiers WHERE pending_action_id=?", (pending,),
    ).fetchone()["id"])
    db.apply_dossier_promulgation(state, revoke, "promulgated")

    # 颁布当月即恢复 override，撤令无「先等一次挽留」的前置
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
    res = _settle_tick(db, "shaanxi")
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


# ═══════════════ F2.3 region_logs 符号域（真实省级 tick 入口）═══════════════

def test_f23_region_logs_flow_sign_domain_repaid_negative(game):
    """F2.3 符号域契约：短缺盘 NewDebt 与盈余盘 Repaid 同回合并存时，
    region_logs 留痕 NewDebt delta>0、Repaid delta<0（省级 tick 写口真源）。"""
    import json

    db, _state, _content = game
    _pin_shortfall_board(db, "shaanxi")
    debt_res = db._settle_province_tick_from_fiscal(
        "shaanxi",
        json.loads(str(db.conn.execute(
            "SELECT fiscal FROM regions WHERE id='shaanxi'"
        ).fetchone()["fiscal"])),
        [],
    )
    new_debt = debt_res.breakdown.get("NewDebt") or {}
    assert any(abs(float(new_debt.get(c, 0) or 0)) > 1e-9 for c in ("官俸欠", "宗禄欠")), \
        "短缺盘必须有实际新增欠流量，否则用例空转"

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
    repaid_res = db._settle_province_tick_from_fiscal("henan", fiscal, [])
    repaid = repaid_res.breakdown.get("Repaid") or {}
    assert any(abs(float(repaid.get(c, 0) or 0)) > 1e-9 for c in ("官俸欠", "宗禄欠")), \
        "盈余盘必须有实际偿还流量，否则用例空转"

    # 负向符号域读真实 region_logs 留痕（省级 tick 写口）
    turn = int(db.conn.execute("SELECT MAX(turn) FROM region_logs").fetchone()[0] or 0)
    rows = db.conn.execute(
        "SELECT field, delta FROM region_logs WHERE turn=? AND field IN "
        "('settle_官俸欠_NewDebt','settle_官俸欠_Repaid',"
        " 'settle_宗禄欠_NewDebt','settle_宗禄欠_Repaid')",
        (turn,),
    ).fetchall()
    repaid_rows = [r for r in rows if str(r["field"]).endswith("_Repaid")]
    debt_rows = [r for r in rows if str(r["field"]).endswith("_NewDebt")]
    assert repaid_rows and debt_rows
    assert all(float(r["delta"]) < 0 for r in repaid_rows), repaid_rows
    assert all(float(r["delta"]) > 0 for r in debt_rows), debt_rows


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
    revoke = db.create_decree_dossier(
        state, action_type="revoke_decree", decree_text="撤陕西旨",
        target_kind="dossier", target_id=str(local),
        payload={"revoke_target_dossier_id": local},
    )
    db.apply_dossier_promulgation(state, revoke, "promulgated")
    cfg = db.get_fiscal_config()
    assert "due_priority_军饷@shaanxi" not in cfg  # 省域形状退出，禁留 live 默认
    assert cfg["due_priority_军饷"] == 35  # 全国键仍在位


# ═══════════════ F1 颁布生命周期 E2E（ADR 0055 判后物化缝）═══════════════

# ═══════════════ F3 LLM 综合归因边界 ═══════════════

def test_apply_score_extraction_accepts_llm_direction_with_fiscal_loss(game):
    """F3.2：单一财政受损事实在案时，LLM 综合判断的正向 satisfaction 原样接收。"""
    from ming_sim.issues import apply_score_extraction

    db, state, _content = game
    db.conn.execute(
        "UPDATE armies SET province_pay_arrears = 12.0, "
        "arrears = 12.0 + central_pay_arrears WHERE id = 'shaanxi_army'"
    )
    db.conn.commit()
    applied = apply_score_extraction(
        db, state, {"class_delta": {"军户": {"satisfaction": 9}}}
    )
    assert applied["class_delta"]["军户"]["satisfaction"] == 9
    assert applied["class_delta_rejections"] == []

# ═══════════════ F1 颁布生命周期 E2E（ADR 0055 判后物化缝）═══════════════

def test_lifecycle_promulgated_materializes_and_next_settlement_reads(game):
    """顺颁：判决当回合落 config；本月已按旧序完成的结算不追溯、下一次结算读取。"""
    db, state, _content = game
    # 本月结算先按旧序完成（fixed flow 已结束的等价断言：旧序结果在案）
    before = _settle_tick(db, "shaanxi")
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
    after = _settle_tick(db, "shaanxi")
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


# ═══════════════ 拟旨 capture→成案（财政物化与下一次省 tick 分别由上方领域用例覆盖）═══

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

def test_manual_override_capture_stages_without_premature_materialization(game, monkeypatch):
    db, _state, _content = game
    entries = [{"key": "due_priority_军饷@shaanxi", "value": 40}]
    did = _capture_override_decree(game, monkeypatch, "今岁边饷居末", entries)
    assert db.get_decree_dossier(did)["status"] == "proposed"
    assert "due_priority_军饷@shaanxi" not in db.get_fiscal_config()

# ═══════════════ F2.3（owner 拍板 r5）：官俸欠/宗禄欠当回合流量持久留痕 ═══════════════

def test_claim_flow_logs_persisted_in_settle_bridge_and_restore_e2e(game):
    """省级结算桥同事务把 官俸欠/宗禄欠 当回合 NewDebt/Repaid 流量补记进 region_logs
    （复用现有结算留痕载体，零新表）；关闭重开 DB（restore）后留痕可恢复。"""
    from ming_sim.db import GameDB

    db, state, content = game
    _pin_shortfall_board(db, "shaanxi")
    result = _settle_tick(db, "shaanxi")
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
    # 批量生产桥会同推进其余明省（各自留痕）；本测试只核 shaanxi 的留痕。
    rows = db.conn.execute(
        "SELECT field, delta, turn, region_id, actor, origin_ref FROM region_logs "
        "WHERE field LIKE 'settle_%' AND region_id = 'shaanxi' ORDER BY id"
    ).fetchall()
    assert {(r["field"], float(r["delta"])) for r in rows} == expect_flows
    assert all(r["turn"] == state.turn and r["region_id"] == "shaanxi" for r in rows)
    assert all(r["actor"] == "户部" and r["origin_ref"] == "region:shaanxi:settle_tick"
               for r in rows)

    # restore E2E：关闭重开同一档文件，留痕随档恢复
    path = db.path
    db.close()
    db2 = GameDB(path, content)
    try:
        rows2 = db2.conn.execute(
            "SELECT field, delta, turn, region_id, actor, origin_ref FROM region_logs "
            "WHERE field LIKE 'settle_%' AND region_id = 'shaanxi' ORDER BY id"
        ).fetchall()
        assert {(r["field"], float(r["delta"])) for r in rows2} == expect_flows
    finally:
        db2.close()
