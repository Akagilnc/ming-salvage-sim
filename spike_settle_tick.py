#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性 spike v2(非引擎,throwaway)——v11→r11 返工:
修 §0.1 守恒(补 拨付gross/清欠 边界流;挪借/追赃为 CASH 内部转移不计边界)、
加 债务对账 + C 对账断言、还款 clamp,新增 G3 清丈 / G4 挪借火耗 / G5 漂没中饱拨付 / G6 超额补饷。

账户:
  CASH(真金,守恒):省库库银 / C_地方截留 / C_中饱 / C_漂没 / C_eff损耗
  CLAIM(债权债务,非现金):民欠旧赋(债权) / 军饷欠·官俸欠·宗禄欠(负债)
  BOUNDARY(系统边界,净流):民间(征收/清欠 source) / 京(拨付 source) / 受款方(起运+实付+偿欠 sink)
守恒主断言:Δ(ΣCASH) == CASH_in − CASH_out
  CASH_in  = 实征 + 火耗实收 + 清欠 + 拨付gross      (民间/京 交进系统的现金)
  CASH_out = 起运到京 + Σ实付 + Σ偿旧欠 + Σ补饷支付   (流向受款方的现金)
  注:挪借火耗(C→省库)/追赃(C→省库) 是 CASH 内部转移,ΣCASH 不变,不计边界。
"""
EPS = 1e-6

def run_tick(name, st, p, actions):
    print(f"\n{'='*64}\n{name}\n{'='*64}")
    cash = {k: float(st.get(k, 0)) for k in ['省库库银','C_地方截留','C_中饱','C_漂没','C_eff损耗']}
    claim = {k: float(st.get(k, 0)) for k in ['民欠旧赋','军饷欠','官俸欠','宗禄欠']}
    官民田 = float(st.get('官民田', 0)); 隐田 = float(st.get('隐田', 0))
    cash0 = sum(cash.values()); C0 = sum(v for k,v in cash.items() if k.startswith('C_'))
    claim0 = dict(claim)
    cash_in = cash_out = 0.0
    rec = dict(实征=0,火耗实收=0,清欠=0,拨付gross=0,起运到京=0,实付=0,偿旧欠=0,补饷支付=0,
               漂没=0,中饱=0,挪借=0,追赃=0,民欠新增=0,蠲免=0,NewDebt={'军饷欠':0,'官俸欠':0,'宗禄欠':0},
               Repaid={'军饷欠':0,'官俸欠':0,'宗禄欠':0},action还={'军饷欠':0})

    # ── ⓪ action phase ──
    Stock_start = cash['省库库银']
    ΣCost = sum(a.get('cost',0) for a in actions if a.get('cost',0) > 0)
    k = 1.0 if (ΣCost == 0 or ΣCost <= Stock_start) else Stock_start/ΣCost
    print(f"⓪ Stock_start={Stock_start:.2f} ΣCost={ΣCost:.2f} k={k:.4f}")
    for a in actions:
        t = a['type']; ec = a.get('cost',0)*k; amt = a.get('amount',0)*k
        if t == '补饷':                       # 现金支付:补发军饷欠(clamp 到欠额,余款不花)
            还 = min(ec, claim['军饷欠'])
            cash['省库库银'] -= 还; cash_out += 还; rec['补饷支付'] += 还
            claim['军饷欠'] -= 还; rec['action还']['军饷欠'] += 还
            print(f"  补饷 ec={ec:.2f} 实还军饷欠={还:.2f}(余款{ec-还:.2f}不花)")
        elif t == '清丈':                      # 挖隐田→官民田(改税基,本 tick 不动现金;可带小成本)
            if ec > 0: cash['省库库银'] -= ec; cash_out += ec; rec['补饷支付']  # 行政成本→受款方(吏)
            挖 = min(a['挖隐田']*k, 隐田); 隐田 -= 挖; 官民田 += 挖
            if ec > 0: cash_out += 0  # (ec 已计)
            print(f"  清丈 挖隐田={挖:.2f}→官民田 {官民田:.2f} 隐田 {隐田:.2f} 成本={ec:.2f}")
        elif t == '挪借火耗':                  # C_地方截留→省库(CASH 内部,ΣCASH 不变)
            mv = min(amt, cash['C_地方截留']); cash['C_地方截留'] -= mv; cash['省库库银'] += mv
            rec['挪借'] += mv; print(f"  挪借火耗 {mv:.2f}: C_地方截留→省库(内部)")
        elif t == '清欠':                      # 收旧民欠:民间补缴现金,债权减
            收 = min(amt, claim['民欠旧赋']); cash['省库库银'] += 收; cash_in += 收
            claim['民欠旧赋'] -= 收; rec['清欠'] += 收; print(f"  清欠 收回民欠={收:.2f}(民间现金入)")
        elif t == '蠲免':                      # 免旧民欠,无现金
            mj = min(amt, claim['民欠旧赋']); claim['民欠旧赋'] -= mj; rec['蠲免'] += mj
            print(f"  蠲免民欠={mj:.2f}")
    省库库银_post = cash['省库库银']

    # ── ②③ 应征(G3 清丈后 官民田 变,应征随之;其余直接给定)──
    正赋 = p.get('正赋应征', round(官民田 * p.get('正赋亩额',0)/12, 4))
    三饷 = p['三饷应征']; fh = p['火耗率']; bf = p['逋赋率']
    # ④⑦
    火耗应派 = 正赋*fh
    实征 = (正赋+三饷)*(1-bf); cash_in += 实征; rec['实征'] = 实征
    火耗实收 = 火耗应派*(1-bf); cash['C_地方截留'] += 火耗实收; cash_in += 火耗实收; rec['火耗实收'] = 火耗实收
    rec['民欠新增'] = (正赋+三饷)-实征; claim['民欠旧赋'] += rec['民欠新增']
    print(f"④⑦ 正赋{正赋:.2f} 火耗应派{火耗应派:.2f} 实征{实征:.2f} 火耗实收{火耗实收:.2f} 民欠+{rec['民欠新增']:.2f}")
    # ⑧⑨ 分池 + 漂没
    起运池 = min(实征, p['起运定额']); 省内池 = max(0.0, 实征-起运池)
    pm = p.get('漂没率',0.0); 起运到京 = 起运池*(1-pm); rec['漂没'] = 起运池-起运到京
    cash['C_漂没'] += rec['漂没']; cash_out += 起运到京; rec['起运到京'] = 起运到京
    # ⑩ 拨付 gross/net + 中饱
    g = p.get('拨付gross',0.0); zb = p.get('中饱率',0.0); net = g*(1-zb); rec['中饱'] = g-net
    cash['省库库银'] += net; cash['C_中饱'] += rec['中饱']; cash_in += g; rec['拨付gross'] = g
    print(f"⑧⑨⑩ 起运池{起运池:.2f} 省内池{省内池:.2f} 起运到京{起运到京:.2f} 漂没{rec['漂没']:.2f} 拨付g{g:.2f}(net{net:.2f}中饱{rec['中饱']:.2f})")
    # ⑪ 省内可支 → 付款 → 偿还 → 结转
    # 省库库银 此刻 = 省库库银_post(已含⓪的挪借/清欠/补饷)+ ⑩拨付net;再加本 tick 省内池
    省内可支 = cash['省库库银'] + 省内池
    Pool = 省内可支
    Due = p['Due']
    for h in ['军饷','官俸','宗禄','赈济']:
        d = Due.get(h,0.0); pay = min(Pool, d); Pool -= pay; cash_out += pay; rec['实付'] += pay
        nd = d-pay
        if h != '赈济' and nd > 0:
            ck = {'军饷':'军饷欠','官俸':'官俸欠','宗禄':'宗禄欠'}[h]; claim[ck] += nd; rec['NewDebt'][ck] += nd
    S = Pool
    for c in ['军饷欠','官俸欠','宗禄欠']:
        r = min(S, claim[c]); claim[c] -= r; S -= r; cash_out += r; rec['偿旧欠'] += r; rec['Repaid'][c] += r
    cash['省库库银'] = S  # 覆盖写(结转)
    print(f"⑪ 省内可支={省内可支:.2f} 实付{rec['实付']:.2f} 偿旧欠{rec['偿旧欠']:.2f} 结转省库={S:.2f}")

    # ── 守恒断言 ──
    cash1 = sum(cash.values()); Δcash = cash1-cash0
    净 = cash_in - cash_out
    ok_cash = abs(Δcash-净) < EPS
    print(f"\n[现金守恒] Δcash={Δcash:+.3f}  CASH_in−out={净:+.3f}(in {cash_in:.2f}/out {cash_out:.2f})  残差{Δcash-净:+.5f}  {'PASS' if ok_cash else 'FAIL'}")
    # 债务对账
    ok_debt = True
    for c in ['军饷欠','官俸欠','宗禄欠']:
        exp = claim0[c] + rec['NewDebt'][c] - rec['Repaid'][c] - rec['action还'].get(c,0)
        if abs(claim[c]-exp) > EPS: ok_debt = False; print(f"  [债务FAIL] {c} {claim[c]:.2f}≠{exp:.2f}")
    exp_my = claim0['民欠旧赋'] + rec['民欠新增'] - rec['清欠'] - rec['蠲免']
    if abs(claim['民欠旧赋']-exp_my) > EPS: ok_debt = False; print(f"  [债务FAIL] 民欠 {claim['民欠旧赋']:.2f}≠{exp_my:.2f}")
    print(f"[债务对账] {'PASS' if ok_debt else 'FAIL'}")
    # C 对账
    C1 = sum(v for k,v in cash.items() if k.startswith('C_'))
    expC = C0 + rec['火耗实收'] + rec['漂没'] + rec['中饱'] - rec['挪借'] - rec['追赃']
    ok_C = abs(C1-expC) < EPS
    print(f"[C 对账] C {C0:.2f}→{C1:.2f} 期望{expC:.2f}  {'PASS' if ok_C else 'FAIL'}")
    print(f"[末态] cash={{ {', '.join(f'{k}:{v:.2f}' for k,v in cash.items())} }}")
    print(f"[末态] claim={{ {', '.join(f'{k}:{v:.2f}' for k,v in claim.items())} }}  官民田={官民田:.0f} 隐田={隐田:.0f}")
    return ok_cash and ok_debt and ok_C


base = dict(正赋应征=60, 三饷应征=10, 火耗率=0.2, 逋赋率=0.3, 起运定额=40,
            漂没率=0.0, 拨付gross=0, 中饱率=0.0, Due=dict(军饷=45,官俸=8,宗禄=4,赈济=0))
def S(**kw): return dict(dict(省库库银=50,C_地方截留=0,C_中饱=0,C_漂没=0,C_eff损耗=0,
                              民欠旧赋=0,军饷欠=20,官俸欠=0,宗禄欠=0,官民田=3050,隐田=1600), **kw)

R = []
R.append(("G1 无action", run_tick("G1 无action(基线)", S(), base, [])))
R.append(("G2 补饷k=.33", run_tick("G2 补饷(银30,Stock10→k=.33)", S(省库库银=10,军饷欠=50), base,
                                   [dict(type='补饷',cost=30)])))
R.append(("G3 清丈", run_tick("G3 清丈(挖隐田300,本tick应现金中性)", S(),
                              dict(base,正赋应征=60), [dict(type='清丈',cost=2,挖隐田=300)])))
R.append(("G4 挪借火耗", run_tick("G4 挪借火耗(C_地方截留预置20,挪10→省库)", S(C_地方截留=20),
                                  base, [dict(type='挪借火耗',amount=10)])))
R.append(("G5 漂没中饱拨付", run_tick("G5 漂没.1+中饱.1+拨付gross30", S(),
                                     dict(base,漂没率=0.1,中饱率=0.1,拨付gross=30), [])))
R.append(("G6 超额补饷", run_tick("G6 补饷银30但军饷欠仅5(验clamp不超还)", S(省库库银=30,军饷欠=5),
                                  base, [dict(type='补饷',cost=30)])))
R.append(("G7 清欠", run_tick("G7 清欠(民欠旧赋预置15,清欠10)", S(民欠旧赋=15),
                              base, [dict(type='清欠',amount=10)])))

print(f"\n{'='*64}\n汇总:")
for n,ok in R: print(f"  {n:14s} {'PASS' if ok else 'FAIL'}")
print('='*64)
