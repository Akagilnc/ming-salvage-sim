#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性 spike(非引擎代码,throwaway)——把 v10 草表的 settle_tick 用纯 dict 实现成
*复式记账*,跑 G1 + 带 action 的 G2,RUN 出守恒到底平不平。
目的:验证 opus 说「守恒只能跑才知道」——把 §6.6 的 `82=49+8.4+21+3.6` 换成
真·复式守恒(Δcash = 入 − 出),看它是不是 tautology、双扣/staging 有没有。

账户分两类:
  CASH(真金,跨账户守恒):省库库银 / C_地方截留 / C_中饱 / C_漂没 / C_eff损耗
  BOUNDARY(系统边界,记净流):民间(source,征收时流出现金) / 受款方(sink,起运+实付流入)
  CLAIM(债权债务,非现金 memo,单独对账):民欠旧赋 / 军饷欠 / 官俸欠 / 宗禄欠
"""

def run_tick(name, st, params, actions):
    print(f"\n{'='*60}\n{name}\n{'='*60}")
    cash = {k: float(st.get(k, 0)) for k in
            ['省库库银', 'C_地方截留', 'C_中饱', 'C_漂没', 'C_eff损耗']}
    claim = {k: float(st.get(k, 0)) for k in ['民欠旧赋', '军饷欠', '官俸欠', '宗禄欠']}
    民间流出 = 0.0   # 本 tick 民间实际交出的现金(实征+火耗实收)
    受款方流入 = 0.0 # 起运到京 + 实付 + 偿旧欠
    cash0 = sum(cash.values())

    def to_受款方(amt, tag):
        nonlocal 受款方流入
        受款方流入 += amt
        print(f"  → 受款方 {amt:8.3f}  ({tag})")

    # ── ⓪ action phase:成本只扣上月省库库银,不够同比缩 k ──
    Stock_start = cash['省库库银']
    ΣCost = sum(a['cost'] for a in actions if a['cost'] > 0)
    k = 1.0 if (ΣCost == 0 or ΣCost <= Stock_start) else Stock_start / ΣCost
    print(f"⓪ Stock_start={Stock_start:.2f}  ΣCost={ΣCost:.2f}  k={k:.4f}")
    for a in actions:
        eff_cost = a['cost'] * k
        if eff_cost > 0:
            cash['省库库银'] -= eff_cost          # 支出现金
            to_受款方(eff_cost, f"action[{a['id']}]银成本×k")
            # 若该 action 是补饷:同额减「军饷欠」债权(官把欠的发了)
            if a.get('pays') == '军饷欠':
                claim['军饷欠'] = max(0, claim['军饷欠'] - eff_cost)
                print(f"    军饷欠 −{eff_cost:.3f} → {claim['军饷欠']:.3f}")
    省库库银_post = cash['省库库银']

    # ── ②③ 应征 ──
    正赋 = params['正赋应征']; 三饷 = params['三饷应征']
    fh_rate = params['火耗率']; bf_rate = params['逋赋率']
    # ── ④ 火耗应派(进民负担,不进 cash) ──
    火耗应派 = 正赋 * fh_rate
    民负担 = 正赋 + 三饷 + 火耗应派
    # ── ⑦ 实征 / 火耗实收 / 民欠 ──
    实征 = (正赋 + 三饷) * (1 - bf_rate)
    火耗实收 = 火耗应派 * (1 - bf_rate)
    民欠新增 = (正赋 + 三饷) - 实征
    民间流出 += 实征 + 火耗实收      # 民间真正交出的现金
    cash['C_地方截留'] += 火耗实收     # 火耗实收落地方灰账
    claim['民欠旧赋'] += 民欠新增
    print(f"④⑦ 火耗应派={火耗应派:.2f} 民负担={民负担:.2f} | 实征={实征:.2f}→可支 "
          f"火耗实收={火耗实收:.2f}→C 民欠+{民欠新增:.2f}")
    # ── ⑧ 起运/省内分池 ──
    起运池 = min(实征, params['起运定额'])
    省内池 = max(0.0, 实征 - 起运池)
    # ── ⑨ 漂没 ──
    pm_rate = params.get('漂没率', 0.0)
    起运到京 = 起运池 * (1 - pm_rate)
    漂没 = 起运池 - 起运到京
    cash['C_漂没'] += 漂没
    to_受款方(起运到京, "起运到京")
    print(f"⑧⑨ 起运池={起运池:.2f} 省内池={省内池:.2f} 起运到京={起运到京:.2f} 漂没={漂没:.2f}→C")
    # ── ⑩ 拨付(外部入,测试默认 0) ──
    拨付net = params.get('拨付net', 0.0)
    # ── ⑪ 省内可支 → 付款 → 偿还 → 结转 ──
    省内可支 = 省库库银_post + 省内池 + 拨付net  # G1/G2 无清欠/追赃/挪借入库
    Pool = 省内可支
    Due = params['Due']  # {军饷,官俸,宗禄,赈济}
    Paid = {}
    for head in ['军饷', '官俸', '宗禄', '赈济']:
        d = Due.get(head, 0.0)
        p = min(Pool, d); Pool -= p; Paid[head] = p
        new_debt = d - p
        if head != '赈济' and new_debt > 0:
            claim[{'军饷':'军饷欠','官俸':'官俸欠','宗禄':'宗禄欠'}[head]] += new_debt
        to_受款方(p, f"实付{head}")
    # 偿旧欠(军饷欠>官俸欠>宗禄欠)
    S = Pool
    for c in ['军饷欠', '官俸欠', '宗禄欠']:
        rep = min(S, claim[c]); claim[c] -= rep; S -= rep
        if rep > 0:
            to_受款方(rep, f"偿{c}")
    省库库银结转 = S
    cash['省库库银'] = 省库库银结转  # 覆盖写(非累加)
    print(f"⑪ 省内可支={省内可支:.2f} 付={Paid} 结转(省库库银)={省库库银结转:.2f}")

    # ── 守恒检查(真·复式)──
    cash1 = sum(cash.values())
    Δcash = cash1 - cash0
    净流 = 民间流出 - 受款方流入
    print(f"\n[守恒] Δcash={Δcash:+.3f}  民间流出−受款方流入={净流:+.3f}  "
          f"残差={Δcash - 净流:+.4f}")
    ok_cash = abs(Δcash - 净流) < 1e-6
    print(f"[守恒] 现金双边平: {'PASS' if ok_cash else 'FAIL'}")
    # 草表 §6.6 那条「82 = 49+8.4+21+3.6」复验(应征侧分解,看是不是 tautology)
    lhs = 正赋 + 三饷 + 火耗应派
    rhs = 实征 + 火耗实收 + 民欠新增 + (火耗应派 - 火耗实收)
    print(f"[草表式] 民负担{lhs:.2f} =? 实征{实征:.2f}+火耗实收{火耗实收:.2f}"
          f"+民欠{民欠新增:.2f}+火耗未收{火耗应派-火耗实收:.2f} = {rhs:.2f}  "
          f"({'恒等-永真,测不出bug' if abs(lhs-rhs)<1e-9 else '不平!'})")
    print(f"[末态] cash={ {k:round(v,2) for k,v in cash.items()} }")
    print(f"[末态] claim={ {k:round(v,2) for k,v in claim.items()} }")
    return ok_cash


# ── G1:无 action(k=1),草表给定值 ──
G1_state = dict(省库库银=50, C_地方截留=0, C_中饱=0, C_漂没=0, C_eff损耗=0,
                民欠旧赋=0, 军饷欠=20, 官俸欠=0, 宗禄欠=0)
G1_params = dict(正赋应征=60, 三饷应征=10, 火耗率=0.2, 逋赋率=0.3, 起运定额=40,
                 漂没率=0.0, 拨付net=0, Due=dict(军饷=45, 官俸=8, 宗禄=4, 赈济=0))
ok1 = run_tick("G1(无 action,草表数字)", G1_state, G1_params, [])

# ── G2:补饷 action(银 30,Stock_start=10 → k=0.333),验 k 缩 + 不双扣 ──
G2_state = dict(省库库银=10, C_地方截留=0, C_中饱=0, C_漂没=0, C_eff损耗=0,
                民欠旧赋=0, 军饷欠=50, 官俸欠=0, 宗禄欠=0)
G2_params = dict(正赋应征=60, 三饷应征=10, 火耗率=0.2, 逋赋率=0.3, 起运定额=40,
                 漂没率=0.0, 拨付net=0, Due=dict(军饷=45, 官俸=8, 宗禄=4, 赈济=0))
G2_actions = [dict(id='补饷', cost=30, pays='军饷欠')]  # 银成本=补发军饷
ok2 = run_tick("G2(补饷 action,k=0.333)", G2_state, G2_params, G2_actions)

print(f"\n{'='*60}\n总判:G1 守恒 {'PASS' if ok1 else 'FAIL'} / G2 守恒 {'PASS' if ok2 else 'FAIL'}\n{'='*60}")
