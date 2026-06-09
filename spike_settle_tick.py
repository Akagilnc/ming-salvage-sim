#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性 spike v3(非引擎,throwaway)——r12 返工:
+ per-account 对账(每个 C_ 子账户单独 reconcile,堵「贪墨 relabel 进国库」隐形)
+ eff损耗(transfer 3-way:source减=target增+C_eff损耗;efficiency<1 落 C_eff损耗)
+ run_tick 返回末态(可串多 tick)+ recurring cost(跨 tick 每期扣)
+ 0-cost action 不受 k 缩(spec §6)+ unknown action fail-loud
golden:G1 基线 / G2 补饷k / G3 清丈 / G4 挪借 / G5 漂没中饱拨付 / G6 超额补饷clamp /
        G7 清欠 / G8 挪借eff<1(激活C_eff损耗) / G9 三tick链(死亡螺旋+recurring)

账户:CASH{省库库银,C_地方截留,C_中饱,C_漂没,C_eff损耗} / CLAIM{民欠旧赋,军饷欠,官俸欠,宗禄欠}
守恒(spike 实测):
  现金:Δ(ΣCASH)==CASH_in−CASH_out   in=实征+火耗实收+清欠+拨付gross  out=起运到京+Σ实付+Σ偿旧欠+Σ行政/补饷支付
       (挪借/追赃=CASH 内部转移,不计边界;eff损耗=CASH 内部,留 ΣCASH)
  债务:负债_new=old+NewDebt−Repaid−action还 ; 民欠_new=old+民欠新增−清欠−蠲免
  C 分账:每个 C_ 子账户 new==old+本账户in−本账户out(per-account,非只 ΣC)
"""
EPS = 1e-6
CASH_KEYS = ['省库库银','C_地方截留','C_中饱','C_漂没','C_eff损耗']
CLAIM_KEYS = ['民欠旧赋','军饷欠','官俸欠','宗禄欠']
KNOWN_ACTIONS = {'补饷','清丈','挪借火耗','清欠','蠲免','营建'}

def run_tick(name, st, p, actions):
    print(f"\n{'='*64}\n{name}\n{'='*64}")
    cash = {k: float(st.get(k,0)) for k in CASH_KEYS}
    claim = {k: float(st.get(k,0)) for k in CLAIM_KEYS}
    官民田 = float(st.get('官民田',0)); 隐田 = float(st.get('隐田',0))
    cash0 = sum(cash.values()); C0 = {k: cash[k] for k in CASH_KEYS if k.startswith('C_')}
    claim0 = dict(claim)
    cash_in = cash_out = 0.0
    # per-account C 流水
    Cin = {k:0.0 for k in C0}; Cout = {k:0.0 for k in C0}
    r = dict(实征=0,火耗实收=0,清欠=0,拨付gross=0,起运到京=0,实付=0,偿旧欠=0,行政补饷=0,
             漂没=0,中饱=0,民欠新增=0,蠲免=0,
             NewDebt={'军饷欠':0,'官俸欠':0,'宗禄欠':0},Repaid={'军饷欠':0,'官俸欠':0,'宗禄欠':0},
             action还={'军饷欠':0})

    def xfer_internal(frm, to, amount, eff=1.0):
        """CASH 内部 3-way 转移:source减=target增+C_eff损耗增。frm/to 均 CASH。"""
        actual = min(amount, cash[frm]); cash[frm] -= actual
        got = actual*eff; loss = actual*(1-eff)
        cash[to] += got
        if loss > 0: cash['C_eff损耗'] += loss; Cin['C_eff损耗'] += loss
        if frm in Cout: Cout[frm] += actual
        if to in Cin: Cin[to] += got
        return actual

    # ── ⓪ action phase:先收集→算 k→按 k 执行(transfer 此时执行)──
    for a in actions:
        if a['type'] not in KNOWN_ACTIONS:
            raise ValueError(f"unknown action: {a['type']}")
    Stock_start = cash['省库库银']
    ΣCost = sum(a.get('cost',0) for a in actions if a.get('cost',0) > 0)
    k = 1.0 if (ΣCost == 0 or ΣCost <= Stock_start) else Stock_start/ΣCost
    print(f"⓪ Stock_start={Stock_start:.2f} ΣCost={ΣCost:.2f} k={k:.4f}")
    for a in actions:
        has_cost = a.get('cost',0) > 0
        ec = a.get('cost',0)*k
        amt = a.get('amount',0) * (k if has_cost else 1.0)   # 0-cost action 不缩(spec §6)
        t = a['type']
        if t in ('补饷',):                       # 现金支付补军饷欠(clamp 不超还)
            还 = min(ec, claim['军饷欠']); cash['省库库银'] -= 还; cash_out += 还; r['行政补饷'] += 还
            claim['军饷欠'] -= 还; r['action还']['军饷欠'] += 还
            print(f"  补饷 ec={ec:.2f} 实还={还:.2f}(余{ec-还:.2f}不花)")
        elif t in ('清丈','营建'):                # 行政成本→受款方(吏/工),带 effect
            if ec > 0: cash['省库库银'] -= ec; cash_out += ec; r['行政补饷'] += ec
            if t == '清丈':
                挖 = min(a.get('挖隐田',0)*(k if has_cost else 1.0), 隐田); 隐田 -= 挖; 官民田 += 挖
                print(f"  清丈 挖隐田={挖:.2f}→官民田{官民田:.2f} 成本={ec:.2f}")
            else: print(f"  营建 成本={ec:.2f}")
        elif t == '挪借火耗':                     # C_地方截留→省库(CASH 内部,eff<1 入 C_eff损耗)
            mv = xfer_internal('C_地方截留','省库库银', amt, a.get('eff',1.0))
            print(f"  挪借火耗 {mv:.2f}(eff={a.get('eff',1.0)})")
        elif t == '清欠':                         # 收旧民欠:民间现金入
            收 = min(amt, claim['民欠旧赋']); cash['省库库银'] += 收; cash_in += 收
            claim['民欠旧赋'] -= 收; r['清欠'] += 收; print(f"  清欠 {收:.2f}")
        elif t == '蠲免':
            mj = min(amt, claim['民欠旧赋']); claim['民欠旧赋'] -= mj; r['蠲免'] += mj
            print(f"  蠲免 {mj:.2f}")

    # ── ②③④⑦ 应征/火耗/实征/民欠 ──
    正赋 = p.get('正赋应征', round(官民田*p.get('正赋亩额',0)/12,4)); 三饷 = p['三饷应征']
    fh = p['火耗率']; bf = p['逋赋率']
    火耗应派 = 正赋*fh
    r['实征'] = (正赋+三饷)*(1-bf); cash_in += r['实征']
    r['火耗实收'] = 火耗应派*(1-bf); cash['C_地方截留'] += r['火耗实收']; Cin['C_地方截留'] += r['火耗实收']; cash_in += r['火耗实收']
    r['民欠新增'] = (正赋+三饷)-r['实征']; claim['民欠旧赋'] += r['民欠新增']
    print(f"④⑦ 正赋{正赋:.2f} 火耗应派{火耗应派:.2f} 实征{r['实征']:.2f} 火耗实收{r['火耗实收']:.2f} 民欠+{r['民欠新增']:.2f}")
    # ── ⑧⑨ 分池+漂没 ──
    起运池 = min(r['实征'], p['起运定额']); 省内池 = max(0.0, r['实征']-起运池)
    pm = p.get('漂没率',0.0); r['起运到京'] = 起运池*(1-pm); r['漂没'] = 起运池-r['起运到京']
    cash['C_漂没'] += r['漂没']; Cin['C_漂没'] += r['漂没']; cash_out += r['起运到京']
    # ── ⑩ 拨付 gross/net+中饱 ──
    g = p.get('拨付gross',0.0); zb = p.get('中饱率',0.0); net = g*(1-zb); r['中饱'] = g-net
    cash['省库库银'] += net; cash['C_中饱'] += r['中饱']; Cin['C_中饱'] += r['中饱']; cash_in += g; r['拨付gross'] = g
    print(f"⑧⑨⑩ 起运池{起运池:.2f} 省内池{省内池:.2f} 起运到京{r['起运到京']:.2f} 漂没{r['漂没']:.2f} 拨付g{g:.2f}(net{net:.2f}中饱{r['中饱']:.2f})")
    # ── ⑪ 省内可支→付款→偿还→结转 ──
    省内可支 = cash['省库库银'] + 省内池; Pool = 省内可支
    for h in ['军饷','官俸','宗禄','赈济']:
        d = p['Due'].get(h,0.0); pay = min(Pool,d); Pool -= pay; cash_out += pay; r['实付'] += pay
        nd = d-pay
        if h != '赈济' and nd > 0:
            ck = {'军饷':'军饷欠','官俸':'官俸欠','宗禄':'宗禄欠'}[h]; claim[ck] += nd; r['NewDebt'][ck] += nd
    S = Pool
    for c in ['军饷欠','官俸欠','宗禄欠']:
        rep = min(S, claim[c]); claim[c] -= rep; S -= rep; cash_out += rep; r['偿旧欠'] += rep; r['Repaid'][c] += rep
    cash['省库库银'] = S
    print(f"⑪ 省内可支{省内可支:.2f} 实付{r['实付']:.2f} 偿旧欠{r['偿旧欠']:.2f} 结转省库={S:.2f}")

    # ── 三类断言 ──
    Δcash = sum(cash.values())-cash0; 净 = cash_in-cash_out
    ok_cash = abs(Δcash-净) < EPS
    print(f"[现金守恒] Δcash={Δcash:+.3f} in−out={净:+.3f}(in{cash_in:.2f}/out{cash_out:.2f}) 残差{Δcash-净:+.5f} {'PASS' if ok_cash else 'FAIL'}")
    ok_debt = True
    for c in ['军饷欠','官俸欠','宗禄欠']:
        exp = claim0[c]+r['NewDebt'][c]-r['Repaid'][c]-r['action还'].get(c,0)
        if abs(claim[c]-exp) > EPS: ok_debt=False; print(f"  [债务FAIL]{c} {claim[c]:.2f}≠{exp:.2f}")
    exp_my = claim0['民欠旧赋']+r['民欠新增']-r['清欠']-r['蠲免']
    if abs(claim['民欠旧赋']-exp_my) > EPS: ok_debt=False; print(f"  [债务FAIL]民欠 {claim['民欠旧赋']:.2f}≠{exp_my:.2f}")
    print(f"[债务对账] {'PASS' if ok_debt else 'FAIL'}")
    # per-account C 对账(堵 relabel)
    ok_C = True
    for ck in C0:
        exp = C0[ck]+Cin[ck]-Cout[ck]
        if abs(cash[ck]-exp) > EPS: ok_C=False; print(f"  [C分账FAIL]{ck} {cash[ck]:.2f}≠{exp:.2f}(old{C0[ck]:.2f}+in{Cin[ck]:.2f}-out{Cout[ck]:.2f})")
    print(f"[C 分账] {'PASS(per-account)' if ok_C else 'FAIL'}")
    print(f"[末态] cash={{ {', '.join(f'{k}:{v:.2f}' for k,v in cash.items())} }}")
    print(f"       claim={{ {', '.join(f'{k}:{v:.2f}' for k,v in claim.items())} }} 官民田={官民田:.0f}")

    new_st = dict(cash); new_st.update(claim); new_st['官民田']=官民田; new_st['隐田']=隐田
    return (ok_cash and ok_debt and ok_C), new_st


base = dict(正赋应征=60,三饷应征=10,火耗率=0.2,逋赋率=0.3,起运定额=40,漂没率=0.0,拨付gross=0,中饱率=0.0,
            Due=dict(军饷=45,官俸=8,宗禄=4,赈济=0))
def S(**kw): return dict(dict(省库库银=50,C_地方截留=0,C_中饱=0,C_漂没=0,C_eff损耗=0,
                              民欠旧赋=0,军饷欠=20,官俸欠=0,宗禄欠=0,官民田=3050,隐田=1600), **kw)
R = []
def go(name, st, p, acts): ok,_ = run_tick(name, st, p, acts); R.append((name, ok)); return _

go("G1 基线", S(), base, [])
go("G2 补饷k=.33", S(省库库银=10,军饷欠=50), base, [dict(type='补饷',cost=30)])
go("G3 清丈(cost2,非现金中性:当tick扣2)", S(), base, [dict(type='清丈',cost=2,挖隐田=300)])
go("G4 挪借火耗(C20,挪10)", S(C_地方截留=20), base, [dict(type='挪借火耗',amount=10)])
go("G5 漂没.1中饱.1拨付30", S(), dict(base,漂没率=0.1,中饱率=0.1,拨付gross=30), [])
go("G6 超额补饷(欠5补30)", S(省库库银=30,军饷欠=5), base, [dict(type='补饷',cost=30)])
go("G7 清欠(民欠15清10)", S(民欠旧赋=15), base, [dict(type='清欠',amount=10)])
go("G8 挪借eff=.8(激活C_eff损耗)", S(C_地方截留=20), base, [dict(type='挪借火耗',amount=10,eff=0.8)])

# G9 三 tick 链:穷省(省库10)+ recurring 募兵(每 tick cost5),看死亡螺旋累积 + 每 tick 守恒
print(f"\n{'#'*64}\n# G9 三 tick 链(穷省 recurring 募兵,死亡螺旋)\n{'#'*64}")
stt = S(省库库银=10, 军饷欠=30)
allok = True
for i in range(1,4):
    duep = dict(base, Due=dict(军饷=45,官俸=8,宗禄=4,赈济=0))
    ok, stt = run_tick(f"G9 tick{i}", stt, duep, [dict(type='营建',cost=5,cost_type='recurring')])
    allok = allok and ok
R.append(("G9 三tick链", allok))

print(f"\n{'='*64}\n汇总:")
for n,ok in R: print(f"  {'PASS' if ok else 'FAIL':5s} {n}")
print(f"  全部 {'PASS' if all(o for _,o in R) else 'FAIL'}")
print('='*64)
