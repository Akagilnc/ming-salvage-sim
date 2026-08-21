#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""省级财政 settle_tick —— 由已验证 spike(`spike_settle_tick.py` v23.1，G1–G22 全 PASS、
~20 mutation 自验全咬）port 进引擎的真实实现（#66）。

省级月度复式记账，逐步：
  ⓪ action 相位（先收集 → 算 k 缩放 → 按 k 执行：补饷/清丈/营建/挪借火耗/追赃/清欠/蠲免）
  ②③④⑦ 应征/火耗/实征/民欠（三饷亦计火耗，分量另立；正赋可从官民田亩额派生）
  ⑧⑨ 分池（起运/省内）+ 漂没
  ⑩ 拨付 gross/net + 中饱
  ⑪ 省内可支 → 法定付款(军饷/官俸/宗禄/赈济) → 偿旧欠(waterfall) → 结转省库

账户：CASH{省库库银,C_地方截留,C_中饱,C_漂没,C_eff损耗} / CLAIM{民欠旧赋,军饷欠,官俸欠,宗禄欠}。

设计（ADR 0007 基座 / ADR 0008 契约）：
- **纯计算 + 自校**：4 个独立守恒 oracle（现金 / 债务 / C 分账 / 土地）每 tick 重算自校。
- **fail-loud**：坏输入（NaN/inf/负/非数/缺必填）→ `ValueError`；守恒破（= settlement 算错的 bug）
  → `FiscalConservationError`（ADR 0005「响亮失败不静默吞」）。
- **港口锁**：调用方（applier 适配器）必须 gate「无异常」才落库；FAIL tick 不得持久化（否则毒态
  钉进存档）。现金守恒断言是债务 oracle 的兜底，**不可删**（能污染省内可支的 bug 必破现金守恒）。
- **被动机制**：给定当前 config（各省率/额/Due）算当月后果；不决策时间线（三饷开征由事件驱动）。
"""
import math
from dataclasses import dataclass
from typing import Any, Dict, List

EPS = 1e-6
CASH_KEYS = ["省库库银", "C_地方截留", "C_中饱", "C_漂没", "C_eff损耗"]
CLAIM_KEYS = ["民欠旧赋", "军饷欠", "官俸欠", "宗禄欠"]
KNOWN_ACTIONS = {"补饷", "清丈", "挪借火耗", "追赃", "清欠", "蠲免", "营建"}
_DUE_KEYS = ("军饷", "官俸", "宗禄", "赈济")
_ARREARS_KEYS = ("军饷欠", "官俸欠", "宗禄欠")
_DEBT_OF_DUE = {"军饷": "军饷欠", "官俸": "官俸欠", "宗禄": "宗禄欠"}


def _resolve_order_param(p: Dict[str, Any], key: str, default: tuple) -> tuple:
    """#653 override 序参（p[key]）验形：缺省=祖制默认序；在位必须是合法排列，
    否则 ValueError（fail-loud）。返回定长 tuple 供结算与 oracle 同源消费。"""
    raw = p.get(key)
    if raw is None:
        return default
    if isinstance(raw, str) or not isinstance(raw, (list, tuple)):
        raise ValueError(f"param {key} 非 list/tuple")
    if len(raw) != len(default) or set(raw) != set(default) or len(set(raw)) != len(raw):
        raise ValueError(f"param {key} 须为 {default} 的完整无重复排列：{raw!r}")
    return tuple(raw)


def _resolve_haircut_param(p: Dict[str, Any]) -> Dict[str, int]:
    """#653 折发系数参（p["due_haircut_bp"]）：{科目: 万分数}，域 (0,10000]，越界 fail-loud。
    缺省/空 dict=无折（逐字节默认路径）。"""
    raw = p.get("due_haircut_bp")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError(f"param due_haircut_bp 非字典：{raw!r}")
    out: Dict[str, int] = {}
    for hk, bp in raw.items():
        if hk not in _DUE_KEYS:
            raise ValueError(f"due_haircut_bp 含未知科目 {hk}")
        if isinstance(bp, bool) or not isinstance(bp, int):
            raise ValueError(f"due_haircut_bp[{hk}] 非整数：{bp!r}")
        if not (0 < bp <= 10000):
            raise ValueError(f"due_haircut_bp[{hk}] 须在 (0,10000]：{bp}")
        if bp != 10000:
            out[hk] = bp
    return out


def _raw_due(p: Dict[str, Any], h: str) -> float:
    """原始 Due 读数（坏 Due 验形归既有 ValueError，此处防 AttributeError 逃逸隔离）。"""
    _due = p["Due"]
    if not isinstance(_due, dict):
        return 0.0
    return float(_due.get(h, 0.0))


def _effective_dues(p: Dict[str, Any]) -> Dict[str, float]:
    ""#653 折发改写 Due 应得额：floor(Due×bp/10000)；余数=免除额（不入 CLAIM 不积欠）。"""
    from .pay_order import haircut_due

    haircuts = _resolve_haircut_param(p)
    eff: Dict[str, float] = {}
    for h in _DUE_KEYS:
        d = _raw_due(p, h)
        bp = haircuts.get(h)
        if bp is None:
            eff[h] = d
        else:
            eff[h], _exempt = haircut_due(d, bp)
    return eff


class FiscalConservationError(AssertionError):
    """守恒 oracle 失败 = settlement 算错（bug）。fail-loud，调用方不得落库（港口锁）。"""


@dataclass
class FiscalTickResult:
    """settle_tick 产出：新省级财政末态 + 当 tick 流水分解（供邸报/裁判消费，§9）。"""
    new_st: Dict[str, float]
    breakdown: Dict[str, Any]


def settle_tick(
    st: Dict[str, Any], p: Dict[str, Any], actions: List[Dict[str, Any]]
) -> FiscalTickResult:
    """单省单月财政 tick。st=开账(CASH/CLAIM/官民田/隐田)，p=本月参数(率/额/Due)，
    actions=本月动作(玩家旨意/事件灌入)。返回新末态 + 流水分解；坏输入/守恒破一律 raise。"""
    # ── 容器型验形（最前置）：st/p 非 dict、actions 非 list/tuple → ValueError，否则下方
    #    `sk in st` / `rq in p` / `for a in actions` 抛 TypeError 逃逸调用方隔离（cmr R3 concur）──
    if not isinstance(st, dict):
        raise ValueError("st 非字典")
    if not isinstance(p, dict):
        raise ValueError("p 非字典")
    if not isinstance(actions, (list, tuple)):
        raise ValueError("actions 非 list/tuple")
    # ── 必填参数 presence（缺省不默认 0——火耗率缺省成 0 = 静默改经济学）──
    for rq in ("三饷应征", "火耗率", "逋赋率", "起运定额", "Due"):
        if rq not in p:
            raise ValueError(f"param {rq} 缺失")
    # ── 开账 stock 全面验形（前置于下方 float 构造：float([]) 等非数值会 TypeError 早于守门、
    #    逃逸调用方 (ValueError/守恒破) 隔离炸 pre_settle，cmr ship-pre R1/R2；CLAIM 也拦——
    #    负军饷欠→偿还环凭空生钱）──
    for sk in (*CASH_KEYS, *CLAIM_KEYS, "官民田", "隐田"):
        if sk in st and st[sk] is None:
            raise ValueError(f"开账 stock {sk} 为 None")
        _sraw = st.get(sk, 0)
        if isinstance(_sraw, bool) or not isinstance(_sraw, (int, float)):
            raise ValueError(f"开账 stock {sk} 非数值")
        if not math.isfinite(float(_sraw)):
            raise ValueError(f"开账 stock {sk} 非有限值(NaN/inf)")
        if float(_sraw) < 0:
            raise ValueError(f"开账 stock {sk} 为负")

    cash = {k: float(st.get(k, 0)) for k in CASH_KEYS}
    claim = {k: float(st.get(k, 0)) for k in CLAIM_KEYS}
    官民田 = float(st.get("官民田", 0))
    隐田 = float(st.get("隐田", 0))
    地0 = 官民田 + 隐田  # 土地守恒锚：清丈只重分类，总亩数不变
    cash0 = sum(cash.values())
    C0 = {k: cash[k] for k in CASH_KEYS if k.startswith("C_")}
    claim0 = dict(claim)
    cash_in = cash_out = 0.0
    # ── #653 偿还序 override ＋ Due 折发系数（ADR 0090）：缺省=祖制默认序、无折 ──
    due_order = _resolve_order_param(p, "due_order", _DUE_KEYS)
    arrears_order = _resolve_order_param(p, "arrears_order", _ARREARS_KEYS)
    _haircut_bp = _resolve_haircut_param(p)  # 验形 fail-loud；实际折算走 _effective_dues
    eff_due = _effective_dues(p)

    r: Dict[str, Any] = dict(
        实征=0, 火耗实收=0, 清欠=0, 拨付gross=0, 起运到京=0, 实付=0, 偿旧欠=0, 行政补饷=0,
        漂没=0, 中饱=0, 民欠新增=0, 蠲免=0, unmet_relief=0,
        NewDebt={"军饷欠": 0, "官俸欠": 0, "宗禄欠": 0},
        Repaid={"军饷欠": 0, "官俸欠": 0, "宗禄欠": 0},
        action还={"军饷欠": 0},
        # #653 流水分解新字段：per-科目实付分账（TSV 断言实付序）＋折发免除额
        实付分账={h: 0.0 for h in _DUE_KEYS},
        **{f"haircut_{h}": _raw_due(p, h) - eff_due[h] for h in _DUE_KEYS},
    )

    def xfer_internal(frm: str, to: str, amount: float, eff: float = 1.0) -> float:
        """CASH 内部 3-way 转移：source 减 = target 增 + C_eff损耗 增。"""
        actual = min(amount, cash[frm])
        cash[frm] -= actual
        got = actual * eff
        loss = actual * (1 - eff)
        cash[to] += got
        if loss > 0:
            cash["C_eff损耗"] += loss
        return actual

    # ── 输入校验 fail-loud（NaN/inf/非数/负/未知 action/越界 eff/语义违例）──
    for a in actions:
        if not isinstance(a, dict):  # 非 dict action（含「误传单 dict→迭代出 key 串」）→ ValueError，
            raise ValueError(f"action 非字典: {a!r}")  # 否则 a.get/a["type"] 抛 AttributeError 逃逸隔离（cmr R2 codex）
        if "type" not in a:
            raise ValueError(f"action 缺 type: {a}")
        if not isinstance(a["type"], str):  # 非 str type（如 list）unhashable → `not in SET` 抛 TypeError 逃逸（cmr R3 gemini）
            raise ValueError(f"action type 非字符串: {a}")
        for nf in ("cost", "amount", "挖隐田", "eff"):
            if nf not in a:
                continue  # 字段可选，缺省走默认值
            v = a[nf]
            if v is None:  # 显式 None（非缺省）→ ValueError；否则下方 < / 乘法对 None 抛 TypeError（cmr R2 codex）
                raise ValueError(f"{nf} 为 None: {a}")
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError(f"{nf} 非数值: {a}")
            if not math.isfinite(float(v)):
                raise ValueError(f"{nf} 非有限值(NaN/inf): {a}")
        if a["type"] not in KNOWN_ACTIONS:
            raise ValueError(f"unknown action: {a['type']}")
        if a.get("cost", 0) < 0 or a.get("amount", 0) < 0 or a.get("挖隐田", 0) < 0:
            raise ValueError(f"负 cost/amount/挖隐田: {a}")
        if not (0 <= a.get("eff", 1.0) <= 1):
            raise ValueError(f"eff 越界: {a}")
        if a["type"] == "补饷" and a.get("amount", 0) != 0:
            raise ValueError(f"补饷不接受 amount(cost即支付): {a}")
        if a["type"] in ("清欠", "蠲免", "追赃", "挪借火耗") and a.get("cost", 0) != 0:
            raise ValueError(f"{a['type']} 禁带 cost(征收/转移类，否则幽灵预算压 k): {a}")
        if a["type"] in ("清丈", "营建") and a.get("cost", 0) <= 0:
            raise ValueError(f"{a['type']} 必须 cost>0(行政成本类): {a}")
    for rk in ("火耗率", "逋赋率", "漂没率", "中饱率"):
        rv = p.get(rk, 0)
        if isinstance(rv, bool) or not isinstance(rv, (int, float)):
            raise ValueError(f"{rk} 非数值")
        if not (0 <= rv <= 1):
            raise ValueError(f"{rk} 越界")
    for pk in ("正赋应征", "三饷应征", "起运定额", "拨付gross", "正赋亩额"):
        v = p.get(pk)
        if v is not None:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                raise ValueError(f"param {pk} 非数值")
            if not math.isfinite(float(v)):
                raise ValueError(f"param {pk} 非有限值(NaN/inf)")
            if v < 0:
                raise ValueError(f"param {pk} 为负")
        elif pk in p and pk != "正赋应征":  # 仅 正赋应征 可 None=走亩额派生
            raise ValueError(f"param {pk} 为 None(仅 正赋应征 可 None)")
    # 正赋应征=None（启用亩额派生）时 正赋亩额 须 >0，否则 正赋 静默算成 0（违 fail-loud，PR#110 gemini）
    if p.get("正赋应征") is None and p.get("正赋亩额", 0) <= 0:
        raise ValueError("正赋应征=None(亩额派生) 须 正赋亩额>0")
    _due = p["Due"]  # presence 已在必填检查（line 62）；此处验形：Due 非 dict（None/list/数值）→
    if isinstance(_due, bool) or not isinstance(_due, dict):  # ValueError，否则下方 .items()/.get() 抛
        raise ValueError("Due 非字典")  # AttributeError 逃逸调用方隔离（flows 只 catch ValueError/守恒破）炸 pre_settle（cmr ship-pre P1）
    for hk, dv in _due.items():
        if hk not in _DUE_KEYS:
            raise ValueError(f"Due 含未知科目 {hk}")
        if isinstance(dv, bool) or not isinstance(dv, (int, float)):
            raise ValueError(f"Due[{hk}] 非数值")
        if not math.isfinite(float(dv)):
            raise ValueError(f"Due[{hk}] 非有限值(NaN/inf)")
        if dv < 0:
            raise ValueError(f"Due[{hk}] 为负")
    # ── ⓪ action 相位：先算 k（超预算按库存比例缩），再按 k 执行 ──
    Stock_start = cash["省库库银"]
    ΣCost = sum(a.get("cost", 0) for a in actions if a.get("cost", 0) > 0)
    k = 1.0 if (ΣCost == 0 or ΣCost <= Stock_start) else Stock_start / ΣCost
    for a in actions:
        has_cost = a.get("cost", 0) > 0
        ec = a.get("cost", 0) * k
        amt = a.get("amount", 0) * (k if has_cost else 1.0)  # 0-cost action 不缩（spec §6）
        t = a["type"]
        if t == "补饷":  # 现金支付补军饷欠（clamp 不超还）
            还 = min(ec, claim["军饷欠"])
            cash["省库库银"] -= 还
            cash_out += 还
            r["行政补饷"] += 还
            claim["军饷欠"] -= 还
            r["action还"]["军饷欠"] += 还
        elif t in ("清丈", "营建"):  # 行政成本→受款方（吏/工），带 effect
            if ec > 0:
                cash["省库库银"] -= ec
                cash_out += ec
                r["行政补饷"] += ec
            if t == "清丈":
                挖 = min(a.get("挖隐田", 0) * (k if has_cost else 1.0), 隐田)
                隐田 -= 挖
                官民田 += 挖
        elif t == "挪借火耗":  # C_地方截留→省库（CASH 内部，eff<1 入 C_eff损耗）
            xfer_internal("C_地方截留", "省库库银", amt, a.get("eff", 1.0))
        elif t == "追赃":  # C_中饱→省库（CASH 内部，eff<1 入 C_eff损耗）
            xfer_internal("C_中饱", "省库库银", amt, a.get("eff", 1.0))
        elif t == "清欠":  # 收旧民欠：民间现金入
            收 = min(amt, claim["民欠旧赋"])
            cash["省库库银"] += 收
            cash_in += 收
            claim["民欠旧赋"] -= 收
            r["清欠"] += 收
        elif t == "蠲免":
            mj = min(amt, claim["民欠旧赋"])
            claim["民欠旧赋"] -= mj
            r["蠲免"] += mj

    # ── ②③④⑦ 应征/火耗/实征/民欠 ──
    _zf = p.get("正赋应征")  # None 视为未设（走亩额派生），防 None*float TypeError
    正赋 = _zf if _zf is not None else round(官民田 * p.get("正赋亩额", 0) / 12, 4)
    三饷 = p["三饷应征"]
    fh = p["火耗率"]
    bf = p["逋赋率"]
    正赋火耗 = 正赋 * fh
    三饷火耗 = 三饷 * fh  # 三饷亦银征同有火耗（史实）；分量另立（spec §9）
    火耗应派 = 正赋火耗 + 三饷火耗
    r["正赋火耗"] = 正赋火耗
    r["三饷火耗"] = 三饷火耗  # 分量显式入 r（下游直接消费，不解析 stdout）
    r["实征"] = (正赋 + 三饷) * (1 - bf)
    cash_in += r["实征"]
    r["火耗实收"] = 火耗应派 * (1 - bf)
    cash["C_地方截留"] += r["火耗实收"]
    cash_in += r["火耗实收"]
    r["民欠新增"] = (正赋 + 三饷) - r["实征"]
    claim["民欠旧赋"] += r["民欠新增"]

    # ── ⑧⑨ 分池 + 漂没 ──
    起运池 = min(r["实征"], p["起运定额"])
    省内池 = max(0.0, r["实征"] - 起运池)
    pm = p.get("漂没率", 0.0)
    r["起运到京"] = 起运池 * (1 - pm)
    r["漂没"] = 起运池 - r["起运到京"]
    cash["C_漂没"] += r["漂没"]
    cash_out += r["起运到京"]

    # ── ⑩ 拨付 gross/net + 中饱 ──
    g = p.get("拨付gross", 0.0)
    zb = p.get("中饱率", 0.0)
    net = g * (1 - zb)
    r["中饱"] = g - net
    cash["省库库银"] += net
    cash["C_中饱"] += r["中饱"]
    cash_in += g
    r["拨付gross"] = g

    # ── ⑪ 省内可支 → 法定付款 → 偿旧欠 → 结转 ──
    省内可支 = cash["省库库银"] + 省内池
    if 省内可支 < -EPS:  # 防御层：入口拦 + k-clamp 后合法输入不可达
        raise ValueError(f"省内可支为负({省内可支})：省库实质透支，支付环禁入")
    Pool = max(0.0, 省内可支)  # k-clamp float 尘埃(~1e-16)清零，防 min(Pool,d)<0 静默造债
    for h in due_order:  # #653：override 在位时按旨序付款；缺省=祖制 _DUE_KEYS 序
        d = eff_due[h]  # #653：折后应得额入付（折减部分=免除，不入 CLAIM）
        pay = min(Pool, d)
        Pool -= pay
        cash_out += pay
        r["实付"] += pay
        r["实付分账"][h] += pay
        nd = d - pay
        if h == "赈济":
            r["unmet_relief"] = nd  # 赈济不积欠，但输出未满足给 LLM（§9）
        elif nd > 0:
            ck = _DEBT_OF_DUE[h]
            claim[ck] += nd
            r["NewDebt"][ck] += nd
    surplus = Pool
    for c in arrears_order:  # #653：override 在位时按旨序偿旧欠；缺省=祖制 waterfall 序
        rep = min(surplus, claim[c])
        claim[c] -= rep
        surplus -= rep
        cash_out += rep
        r["偿旧欠"] += rep
        r["Repaid"][c] += rep
    cash["省库库银"] = surplus

    # ── 守恒 oracle（4 类，独立重算，破即 raise）──
    _assert_conservation(
        st, p, actions, cash, claim, cash0, cash_in, cash_out, C0, claim0,
        官民田, 隐田, 地0, 省内可支, fh, bf, g, zb, k, 正赋, r,
    )

    new_st: Dict[str, float] = dict(cash)
    new_st.update(claim)
    new_st["官民田"] = 官民田
    new_st["隐田"] = 隐田
    new_st["unmet_relief"] = r["unmet_relief"]  # §9：输出给 LLM 裁判
    # 末态前置 finite 校验：有限但极大输入（如 正赋+三饷 溢出）会使派生值成 inf/nan，而守恒断言的
    # nan 比较恒 False、漏过 → 静默持久化毒态。非有限即 settlement 产出垃圾，fail-loud 不落库
    # （PR#110 coderabbit）。用 FiscalConservationError（调用方隔离捕获、港口锁不持久化）。
    for _k, _v in new_st.items():
        if not math.isfinite(float(_v)):
            raise FiscalConservationError(f"末态 {_k} 非有限值（派生溢出 inf/nan）：{_v}")
    return FiscalTickResult(new_st=new_st, breakdown=r)


def _assert_conservation(
    st, p, actions, cash, claim, cash0, cash_in, cash_out, C0, claim0,
    官民田, 隐田, 地0, 省内可支, fh, bf, g, zb, k, 正赋, r,
) -> None:
    """4 类独立守恒 oracle：现金 / 债务 per-account / C 分账 per-account / 土地。
    每个都从 st+params+actions 独立重放（不读 settlement 中间量），破即 fail-loud raise。"""
    # ── ① 现金守恒：Δ(ΣCASH) == in − out ──
    Δcash = sum(cash.values()) - cash0
    净 = cash_in - cash_out
    if abs(Δcash - 净) >= EPS:
        raise FiscalConservationError(
            f"现金守恒破：Δcash={Δcash:+.5f} ≠ in−out={净:+.5f}(残差{Δcash - 净:+.5e})"
        )
    # ── 独立重算 k / 土地 / 正赋（不读运行时同源量）──
    o_Stock = float(st.get("省库库银", 0))
    o_ΣCost = sum(a.get("cost", 0) for a in actions if a.get("cost", 0) > 0)
    o_k = 1.0 if (o_ΣCost == 0 or o_ΣCost <= o_Stock) else o_Stock / o_ΣCost
    官民田_o = float(st.get("官民田", 0))
    隐田_o = float(st.get("隐田", 0))
    for a in actions:
        if a["type"] == "清丈":
            _ak = o_k if a.get("cost", 0) > 0 else 1.0
            挖_o = min(a.get("挖隐田", 0) * _ak, 隐田_o)
            隐田_o -= 挖_o
            官民田_o += 挖_o
    _zf_o = p.get("正赋应征")
    正赋_o = _zf_o if _zf_o is not None else round(官民田_o * p.get("正赋亩额", 0) / 12, 4)
    三饷 = p["三饷应征"]
    # ── ② 债务 per-account 独立 oracle（#653：同源重放 override 序＋折后应得）──
    o_due_order = _resolve_order_param(p, "due_order", _DUE_KEYS)
    o_arrears_order = _resolve_order_param(p, "arrears_order", _ARREARS_KEYS)
    o_eff_due = _effective_dues(p)
    o_pool = max(0.0, 省内可支)
    o_paid = {}
    for h in o_due_order:
        d = o_eff_due[h]
        pay = min(o_pool, d)
        o_pool -= pay
        o_paid[h] = pay
    o_nd = {
        "军饷欠": o_eff_due.get("军饷", 0) - o_paid.get("军饷", 0),
        "官俸欠": o_eff_due.get("官俸", 0) - o_paid.get("官俸", 0),
        "宗禄欠": o_eff_due.get("宗禄", 0) - o_paid.get("宗禄", 0),
    }
    o_a还 = {"军饷欠": 0.0}
    for a in actions:
        if a["type"] == "补饷":
            o_a还["军饷欠"] += min(
                a.get("cost", 0) * (o_k if a.get("cost", 0) > 0 else 1.0),
                claim0["军饷欠"] - o_a还["军饷欠"],
            )
    o_S = o_pool
    o_rep = {}
    for c in o_arrears_order:
        bal = claim0[c] - o_a还.get(c, 0) + o_nd[c]
        x = min(o_S, bal)
        o_rep[c] = x
        o_S -= x
    for c in ("军饷欠", "官俸欠", "宗禄欠"):
        exp = claim0[c] - o_a还.get(c, 0) + o_nd[c] - o_rep[c]
        if abs(claim[c] - exp) > EPS:
            raise FiscalConservationError(f"债务对账破：{c} {claim[c]:.4f} ≠ oracle {exp:.4f}")
    o_my = claim0["民欠旧赋"]
    for a in actions:
        if a["type"] in ("清欠", "蠲免"):
            o_my -= min(a.get("amount", 0) * (o_k if a.get("cost", 0) > 0 else 1.0), o_my)
    o_my += (正赋_o + 三饷) * bf
    if abs(claim["民欠旧赋"] - o_my) > EPS:
        raise FiscalConservationError(f"债务对账破：民欠旧赋 {claim['民欠旧赋']:.4f} ≠ oracle {o_my:.4f}")
    # ── ③ C 分账 per-account 独立 oracle ──
    实征_o = (正赋_o + 三饷) * (1 - bf)
    正赋火耗_o = 正赋_o * fh
    三饷火耗_o = 三饷 * fh
    火耗应派_o = 正赋火耗_o + 三饷火耗_o  # 与 settlement 同分量式相加（防浮点序差）
    起运池_o = min(实征_o, p["起运定额"])
    pm = p.get("漂没率", 0.0)
    o_in = {"C_地方截留": 火耗应派_o * (1 - bf), "C_中饱": g * zb, "C_漂没": 起运池_o * pm, "C_eff损耗": 0.0}
    o_out = {ck: 0.0 for ck in C0}
    bal_dfjl, bal_zb = C0["C_地方截留"], C0["C_中饱"]
    for a in actions:
        ak = o_k if a.get("cost", 0) > 0 else 1.0
        if a["type"] == "挪借火耗":
            act = min(a.get("amount", 0) * ak, bal_dfjl)
            bal_dfjl -= act
            o_out["C_地方截留"] += act
            o_in["C_eff损耗"] += act * (1 - a.get("eff", 1.0))
        elif a["type"] == "追赃":
            act = min(a.get("amount", 0) * ak, bal_zb)
            bal_zb -= act
            o_out["C_中饱"] += act
            o_in["C_eff损耗"] += act * (1 - a.get("eff", 1.0))
    for ck in C0:
        exp = C0[ck] + o_in[ck] - o_out[ck]
        if abs(cash[ck] - exp) > EPS:
            raise FiscalConservationError(
                f"C 分账破：{ck} {cash[ck]:.4f} ≠ oracle {exp:.4f}"
                f"(old{C0[ck]:.2f}+in{o_in[ck]:.2f}-out{o_out[ck]:.2f})"
            )
    # ── ④ 土地守恒：清丈只重分类，总亩数不变 ──
    if abs((官民田 + 隐田) - 地0) >= 1e-3:
        raise FiscalConservationError(f"土地守恒破：官民田+隐田 {官民田 + 隐田:.4f} ≠ 初始 {地0:.4f}")
