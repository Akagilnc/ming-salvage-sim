"""省级财政 settle_tick golden —— 由 spike_settle_tick.py v23.1 的 G1–G22 + G21 fail-loud + G9
三 tick 链原样 port 成 pytest。末态硬期望是真正独立的锚（堵「债清了钱没出」级 bug，前三守恒
断言一致少记时漏过，但末态≠常量必 FAIL）。settle_tick 自带 4 守恒 oracle，算错会先 raise。
"""
import math

import pytest

from ming_sim.fiscal_tick import FiscalConservationError, settle_tick

# ── 与 spike 同源 fixtures ──
base = dict(正赋应征=15, 三饷应征=2.5, 火耗率=0.18, 逋赋率=0.45, 起运定额=3.5, 漂没率=0.0,
            拨付gross=4, 中饱率=0.0, Due=dict(军饷=18, 官俸=3, 宗禄=6, 赈济=0))


def S(**kw):
    return dict(dict(省库库银=50, C_地方截留=0, C_中饱=0, C_漂没=0, C_eff损耗=0,
                     民欠旧赋=0, 军饷欠=20, 官俸欠=0, 宗禄欠=0, 官民田=3050, 隐田=1600), **kw)


_p14 = {k: v for k, v in base.items() if k != "正赋应征"}
_p14["正赋亩额"] = 0.236


def _assert_end(st, p, actions, expect):
    res = settle_tick(st, p, actions)
    for kk, vv in expect.items():
        got = res.new_st.get(kk)
        assert got is not None and math.isclose(got, vv, rel_tol=1e-6, abs_tol=1e-3), \
            f"末态 {kk}={got} ≠ 期望 {vv}"
    return res


# ── G1–G22 末态硬期望 golden ──
GOLDEN = [
    ("G1 基线", S(), base, [], {"省库库银": 13.125, "C_地方截留": 1.7325, "民欠旧赋": 7.875, "军饷欠": 0}),
    ("G2 补饷k=.33", S(省库库银=10, 军饷欠=50), base, [dict(type="补饷", cost=30)],
     {"省库库银": 0, "C_地方截留": 1.7325, "民欠旧赋": 7.875, "军饷欠": 47.875, "官俸欠": 3, "宗禄欠": 6}),
    ("G3 清丈cost2", S(), base, [dict(type="清丈", cost=2, 挖隐田=300)],
     {"省库库银": 11.125, "C_地方截留": 1.7325, "民欠旧赋": 7.875, "军饷欠": 0, "官民田": 3350}),
    ("G4 挪借火耗", S(C_地方截留=20), base, [dict(type="挪借火耗", amount=10)],
     {"省库库银": 23.125, "C_地方截留": 11.7325, "民欠旧赋": 7.875, "军饷欠": 0}),
    ("G5 漂没中饱拨付", S(), dict(base, 漂没率=0.1, 中饱率=0.1, 拨付gross=30), [],
     {"省库库银": 36.125, "C_地方截留": 1.7325, "C_中饱": 3, "C_漂没": 0.35, "民欠旧赋": 7.875}),
    ("G6 超额补饷", S(省库库银=30, 军饷欠=5), base, [dict(type="补饷", cost=30)],
     {"省库库银": 8.125, "C_地方截留": 1.7325, "民欠旧赋": 7.875, "军饷欠": 0, "官俸欠": 0, "宗禄欠": 0}),
    ("G7 清欠", S(民欠旧赋=15), base, [dict(type="清欠", amount=10)],
     {"省库库银": 23.125, "C_地方截留": 1.7325, "民欠旧赋": 12.875, "军饷欠": 0}),
    ("G8 挪借eff=.8", S(C_地方截留=20), base, [dict(type="挪借火耗", amount=10, eff=0.8)],
     {"省库库银": 21.125, "C_地方截留": 11.7325, "C_eff损耗": 2, "民欠旧赋": 7.875, "军饷欠": 0}),
    ("G10 追赃", S(C_中饱=12), base, [dict(type="追赃", amount=8, eff=0.9)],
     {"省库库银": 20.325, "C_地方截留": 1.7325, "C_中饱": 4, "C_eff损耗": 0.8, "民欠旧赋": 7.875, "军饷欠": 0}),
    ("G11 多costed", S(省库库银=10, 军饷欠=50), base,
     [dict(type="补饷", cost=20), dict(type="营建", cost=20)],
     {"省库库银": 0, "C_地方截留": 1.7325, "民欠旧赋": 7.875, "军饷欠": 52.875, "官俸欠": 3, "宗禄欠": 6}),
    ("G12 赈济Due>0", S(省库库银=80), dict(base, Due=dict(军饷=18, 官俸=3, 宗禄=6, 赈济=15)), [],
     {"省库库银": 28.125, "C_地方截留": 1.7325, "民欠旧赋": 7.875, "军饷欠": 0}),
    ("G13 拨付+追赃同tick", S(C_中饱=10), dict(base, 拨付gross=30, 中饱率=0.1),
     [dict(type="追赃", amount=6)],
     {"省库库银": 42.125, "C_地方截留": 1.7325, "C_中饱": 7, "民欠旧赋": 7.875}),
    ("G14 动态税基", dict(S(), 官民田=3050), _p14, [dict(type="清丈", cost=2, 挖隐田=300)],
     {"省库库银": 39.1108, "C_地方截留": 6.7699, "民欠旧赋": 30.7725, "军饷欠": 0, "官民田": 3350}),
    ("G14b 正赋应征=None", dict(S(), 官民田=3050), dict(_p14, 正赋应征=None),
     [dict(type="清丈", cost=2, 挖隐田=300)],
     {"省库库银": 39.1108, "C_地方截留": 6.7699, "民欠旧赋": 30.7725, "军饷欠": 0, "官民田": 3350}),
    ("G14c k=0.5 清丈", dict(S(省库库银=1), 官民田=3050), _p14, [dict(type="清丈", cost=2, 挖隐田=300)],
     {"省库库银": 0, "C_地方截留": 6.4779, "民欠旧赋": 29.445, "军饷欠": 10.5117,
      "官俸欠": 0, "宗禄欠": 0, "官民田": 3200}),
    ("G15 双债户偿还序", S(省库库银=70, 军饷欠=20, 官俸欠=20), base, [],
     {"省库库银": 13.125, "C_地方截留": 1.7325, "民欠旧赋": 7.875, "军饷欠": 0, "官俸欠": 0, "宗禄欠": 0}),
    ("G16 清丈枯竭", S(隐田=200), base, [dict(type="清丈", cost=2, 挖隐田=300)],
     {"省库库银": 11.125, "C_地方截留": 1.7325, "民欠旧赋": 7.875, "军饷欠": 0, "官民田": 3250}),
    ("G17 赈济饿死", S(省库库银=0, 军饷欠=0), dict(base, Due=dict(军饷=0, 官俸=0, 宗禄=0, 赈济=15)), [],
     {"省库库银": 0, "C_地方截留": 1.7325, "民欠旧赋": 7.875, "军饷欠": 0, "unmet_relief": 4.875}),
    ("G18 三债户waterfall序", S(省库库银=16, 军饷欠=0),
     dict(base, 起运定额=50, Due=dict(军饷=10, 官俸=8, 宗禄=4, 赈济=0)), [],
     {"省库库银": 0, "C_地方截留": 1.7325, "民欠旧赋": 7.875, "官俸欠": 0, "宗禄欠": 2}),
    ("G19 三债户repay序", S(省库库银=70, 军饷欠=0, 官俸欠=10, 宗禄欠=10), dict(base, 起运定额=100), [],
     {"省库库银": 27, "C_地方截留": 1.7325, "民欠旧赋": 7.875, "官俸欠": 0, "宗禄欠": 0}),
    ("G20 蠲免", S(民欠旧赋=15), base, [dict(type="蠲免", amount=8)],
     {"省库库银": 13.125, "C_地方截留": 1.7325, "民欠旧赋": 14.875, "军饷欠": 0}),
    ("G22 三饷火耗分量", S(), dict(base, 三饷应征=7.5), [],
     {"省库库银": 15.875, "C_地方截留": 2.2275, "民欠旧赋": 10.125, "军饷欠": 0}),
    ("G22b 三饷=0退化", S(), dict(base, 三饷应征=0), [],
     {"省库库银": 11.75, "C_地方截留": 1.485, "民欠旧赋": 6.75, "军饷欠": 0, "官俸欠": 0, "宗禄欠": 0}),
]


@pytest.mark.parametrize("name,st,p,actions,expect", GOLDEN, ids=[g[0] for g in GOLDEN])
def test_fiscal_golden(name, st, p, actions, expect):
    _assert_end(st, p, actions, expect)


# ── G21 非法输入 fail-loud（msg=期望错误子串，防别的守门碰巧兜住）──
RAISE_CASES = [
    ("G21 负挖隐田", S(), base, [dict(type="清丈", cost=2, 挖隐田=-100)], "负 cost/amount/挖隐田"),
    ("G21b unknown action", S(), base, [dict(type="发射导弹", cost=5)], "unknown action"),
    ("G21c 负Due", S(), dict(base, Due=dict(军饷=-45, 官俸=8, 宗禄=4, 赈济=0)), [], "Due[军饷] 为负"),
    ("G21d 负起运定额", S(), dict(base, 起运定额=-40), [], "param 起运定额 为负"),
    ("G21e 负拨付gross", S(), dict(base, 拨付gross=-30), [], "param 拨付gross 为负"),
    ("G21f 负开账省库", S(省库库银=-10), base, [], "开账 stock 省库库银 为负"),
    ("G21g 0-cost清丈", S(), base, [dict(type="清丈", cost=0, 挖隐田=300)], "必须 cost>0"),
    ("G21h NaN cost", S(), base, [dict(type="营建", cost=float("nan"))], "非有限值"),
    ("G21i 负开账军饷欠", S(军饷欠=-5), base, [], "开账 stock 军饷欠 为负"),
    ("G21j 负开账民欠旧赋", S(民欠旧赋=-5), base, [], "开账 stock 民欠旧赋 为负"),
    ("G21k 负开账官俸欠", S(官俸欠=-5), base, [], "开账 stock 官俸欠 为负"),
    ("G21l 负开账宗禄欠", S(宗禄欠=-5), base, [], "开账 stock 宗禄欠 为负"),
    ("G21m NaN Due", S(), dict(base, Due=dict(军饷=float("nan"), 官俸=8, 宗禄=4, 赈济=0)), [], "Due[军饷] 非有限值"),
    ("G21n NaN 开账军饷欠", S(军饷欠=float("nan")), base, [], "开账 stock 军饷欠 非有限值"),
    ("G21o inf 起运定额", S(), dict(base, 起运定额=float("inf")), [], "param 起运定额 非有限值"),
    ("G21p None 三饷应征", S(), dict(base, 三饷应征=None), [], "param 三饷应征 为 None"),
    ("G21q Due拼错科目", S(), dict(base, Due=dict(军饷x=45, 官俸=8, 宗禄=4, 赈济=0)), [], "Due 含未知科目"),
    ("G21r action缺type", S(), base, [dict(cost=5)], "action 缺 type"),
    ("G21s 字符串cost", S(), base, [dict(type="营建", cost="5")], "cost 非数值"),
    ("G21t 缺火耗率", S(), {k: v for k, v in base.items() if k != "火耗率"}, [], "param 火耗率 缺失"),
    ("G21u None开账省库", S(省库库银=None), base, [], "开账 stock 省库库银 为 None"),
    ("G21v 字符串火耗率", S(), dict(base, 火耗率="0.2"), [], "火耗率 非数值"),
    ("G21w bool拨付gross", S(), dict(base, 拨付gross=True), [], "param 拨付gross 非数值"),
    # cmr ship-pre R1（codex+gemini concur P1）：Due 非字典曾 .items()/.get() 抛 AttributeError，
    # 逃逸 flows 的 (ValueError, FiscalConservationError) 隔离 → 炸 pre_settle 固定财政（F4）。
    # 验形归 ValueError，使坏 Due 走港口锁+隔离而非 AttributeError 逃逸。
    ("G21x Due=None", S(), dict(base, Due=None), [], "Due 非字典"),
    ("G21y Due=list", S(), dict(base, Due=[]), [], "Due 非字典"),
    ("G21z Due=数值", S(), dict(base, Due=5), [], "Due 非字典"),
    # cmr ship-pre R2（codex concur P1/P2）：同类 type-escape 的其它面——开账 stock 非数值
    # （float([]) TypeError 早于守门）、action 非 dict / action 字段显式 None（later compare/mul
    # TypeError），都曾逃逸 flows 隔离炸 pre_settle。全面前置验形归 ValueError。
    ("G21A1 stock非数值", S(省库库银=[]), base, [], "开账 stock 省库库银 非数值"),
    ("G21A2 action非dict", S(), base, [5], "action 非字典"),
    ("G21A3 action字段None", S(), base, [dict(type="营建", cost=None)], "cost 为 None"),
    # cmr ship-pre R3（codex×2+gemini concur）：补全输入「容器型」验形——actions/st/p 非期望容器
    # 或 action type 非 str 时，曾在 `for a in actions`/`sk in st`/`rq in p`/`type not in SET`
    # 抛 TypeError 而非 ValueError，逃逸隔离。至此全部外部输入「验形归 ValueError 早于 type-敏感操作」。
    ("G21B1 actions非list", S(), base, 5, "actions 非 list/tuple"),
    ("G21B2 st非字典", 5, base, [], "st 非字典"),
    ("G21B3 p非字典", S(), 5, [], "p 非字典"),
    ("G21B4 action type非str", S(), base, [dict(type=["清丈"], cost=2)], "action type 非字符串"),
    # 线上 PR#110 R1（gemini medium）：正赋应征=None（亩额派生）但 正赋亩额 缺省/0 → 正赋 静默
    # 算成 0，违 fail-loud。须 正赋亩额>0，否则 ValueError。
    ("G21C1 None正赋缺亩额", S(), dict(base, 正赋应征=None), [], "正赋亩额>0"),
    ("G21C2 None正赋亩额0", S(), dict(base, 正赋应征=None, 正赋亩额=0), [], "正赋亩额>0"),
]


@pytest.mark.parametrize("name,st,p,actions,msg", RAISE_CASES, ids=[c[0] for c in RAISE_CASES])
def test_fiscal_fail_loud(name, st, p, actions, msg):
    with pytest.raises(ValueError) as exc:
        settle_tick(st, p, actions)
    assert msg in str(exc.value), f"{name}: 守门消息不含「{msg}」：{exc.value}"


# ── G9 三 tick 链：穷省 recurring 募兵，死亡螺旋累积 + 每 tick 守恒 + 硬期望 ──
def test_fiscal_g9_three_tick_death_spiral():
    st = S(省库库银=10, 军饷欠=30)
    g9exp = [
        {"省库库银": 0, "C_地方截留": 1.7325, "民欠旧赋": 7.875, "军饷欠": 32.875, "官俸欠": 3, "宗禄欠": 6},
        {"省库库银": 0, "C_地方截留": 3.465, "民欠旧赋": 15.75, "军饷欠": 40.75, "官俸欠": 6, "宗禄欠": 12},
        {"省库库银": 0, "C_地方截留": 5.1975, "民欠旧赋": 23.625, "军饷欠": 48.625, "官俸欠": 9, "宗禄欠": 18},
    ]
    for i in range(3):
        duep = dict(base, Due=dict(军饷=18, 官俸=3, 宗禄=6, 赈济=0))
        res = _assert_end(st, duep, [dict(type="营建", cost=5)], g9exp[i])
        st = res.new_st


def test_fiscal_nonfinite_derived_fails_loud():
    # 线上 PR#110（coderabbit major）：有限但极大输入（正赋+三饷 → inf）派生 inf/nan；守恒断言因
    # nan 比较恒 False 漏过 → 静默持久化毒态。末态 finite 校验 → FiscalConservationError（被隔离不落库）。
    with pytest.raises(FiscalConservationError):
        settle_tick(S(), dict(base, 正赋应征=1e308, 三饷应征=1e308), [])


def test_conservation_error_is_distinct_type():
    # 守恒破是 settlement bug（fail-loud），与坏输入 ValueError 区分；正常 tick 不抛
    assert issubclass(FiscalConservationError, AssertionError)
    res = settle_tick(S(), base, [])
    assert math.isfinite(res.new_st["省库库银"])
