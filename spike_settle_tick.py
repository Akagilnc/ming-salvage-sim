#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性 spike v3(非引擎,throwaway)——r12 返工:
+ per-account 对账(每个 C_ 子账户单独 reconcile,堵「贪墨 relabel 进国库」隐形)
+ eff损耗(transfer 3-way:source减=target增+C_eff损耗;efficiency<1 落 C_eff损耗)
+ run_tick 返回末态(可串多 tick);recurring 目前由 driver 每 tick 重传 action 实现,引擎未读 cost_type(持久化是 port TODO)
+ 0-cost action 不受 k 缩(spec §6)+ unknown action fail-loud
golden:G1–G22(基线/补饷k/清丈/挪借/漂没中饱拨付/超额clamp/清欠/eff损耗/三tick死亡螺旋/
        追赃/多costed共享k/赈济/拨付追赃/动态税基/双债户偿还序/清丈枯竭土地守恒/赈济饿死unmet/
        三债户waterfall序/三债户repay序/蠲免/三饷火耗分量);5 层断言+输入校验 fail-loud,~20 mutation 自验全咬
v23:三饷计火耗(火耗应派=(正赋+三饷)×火耗率,分量另立;golden 手推重算 C_地方截留 8.4→9.8)

账户:CASH{省库库银,C_地方截留,C_中饱,C_漂没,C_eff损耗} / CLAIM{民欠旧赋,军饷欠,官俸欠,宗禄欠}
守恒(spike 实测):
  现金:Δ(ΣCASH)==CASH_in−CASH_out   in=实征+火耗实收+清欠+拨付gross  out=起运到京+Σ实付+Σ偿旧欠+Σ行政/补饷支付
       (挪借/追赃=CASH 内部转移,不计边界;eff损耗=CASH 内部,留 ΣCASH)
  债务:负债_new=old+NewDebt−Repaid−action还 ; 民欠_new=old+民欠新增−清欠−蠲免
  C 分账:每个 C_ 子账户 new==old+本账户in−本账户out(per-account,非只 ΣC)
"""
import math
EPS = 1e-6
CASH_KEYS = ['省库库银','C_地方截留','C_中饱','C_漂没','C_eff损耗']
CLAIM_KEYS = ['民欠旧赋','军饷欠','官俸欠','宗禄欠']
KNOWN_ACTIONS = {'补饷','清丈','挪借火耗','追赃','清欠','蠲免','营建'}

def run_tick(name, st, p, actions, expect=None):
    print(f"\n{'='*64}\n{name}\n{'='*64}")
    cash = {k: float(st.get(k,0)) for k in CASH_KEYS}
    claim = {k: float(st.get(k,0)) for k in CLAIM_KEYS}
    官民田 = float(st.get('官民田',0)); 隐田 = float(st.get('隐田',0))
    地0 = 官民田 + 隐田                                  # 土地守恒锚:清丈只重分类,总亩数不变
    cash0 = sum(cash.values()); C0 = {k: cash[k] for k in CASH_KEYS if k.startswith('C_')}
    claim0 = dict(claim)
    cash_in = cash_out = 0.0
    r = dict(实征=0,火耗实收=0,清欠=0,拨付gross=0,起运到京=0,实付=0,偿旧欠=0,行政补饷=0,
             漂没=0,中饱=0,民欠新增=0,蠲免=0,unmet_relief=0,
             NewDebt={'军饷欠':0,'官俸欠':0,'宗禄欠':0},Repaid={'军饷欠':0,'官俸欠':0,'宗禄欠':0},
             action还={'军饷欠':0})

    def xfer_internal(frm, to, amount, eff=1.0):
        """CASH 内部 3-way 转移:source减=target增+C_eff损耗增。frm/to 均 CASH。"""
        actual = min(amount, cash[frm]); cash[frm] -= actual
        got = actual*eff; loss = actual*(1-eff)
        cash[to] += got
        if loss > 0: cash['C_eff损耗'] += loss
        return actual

    # ── ⓪ action phase:先收集→算 k→按 k 执行(transfer 此时执行)──
    for a in actions:                                   # 输入校验 fail-loud(codex r16 / Fable:NaN/inf + 0-cost清丈)
        for nf in ('cost','amount','挖隐田','eff'):      # NaN/inf 入口拦截(nan<0=False 会穿过负值检查)
            v = a.get(nf)
            if v is not None and not math.isfinite(float(v)): raise ValueError(f"{nf} 非有限值(NaN/inf): {a}")
        if a['type'] not in KNOWN_ACTIONS: raise ValueError(f"unknown action: {a['type']}")
        if a.get('cost',0) < 0 or a.get('amount',0) < 0 or a.get('挖隐田',0) < 0: raise ValueError(f"负 cost/amount/挖隐田: {a}")
        if not (0 <= a.get('eff',1.0) <= 1): raise ValueError(f"eff 越界: {a}")
        if a['type'] == '补饷' and a.get('amount',0) != 0: raise ValueError(f"补饷不接受 amount(cost即支付): {a}")
        if a['type'] in ('清欠','蠲免','追赃','挪借火耗') and a.get('cost',0) != 0:
            raise ValueError(f"{a['type']} 禁带 cost(征收/转移类按 §9,否则幽灵预算压 k): {a}")
        if a['type'] in ('清丈','营建') and a.get('cost',0) <= 0:    # 行政成本类必须 cost>0(否则免费抬税基=违P3爽感)
            raise ValueError(f"{a['type']} 必须 cost>0(行政成本类): {a}")
    for rk in ('火耗率','逋赋率','漂没率','中饱率'):
        if not (0 <= p.get(rk,0) <= 1): raise ValueError(f"{rk} 越界")
    for pk in ('正赋应征','三饷应征','起运定额','拨付gross','正赋亩额'):  # param 量纲负值 fail-loud(r21/opus:负值穿透五层=凭空生钱)
        if p.get(pk,0) is not None and p.get(pk,0) < 0: raise ValueError(f"param {pk} 为负")
    for hk,dv in p.get('Due',{}).items():
        if dv < 0: raise ValueError(f"Due[{hk}] 为负")
    for sk in (*CASH_KEYS, *CLAIM_KEYS, '官民田', '隐田'):   # CLAIM 也拦(codex r4:负军饷欠→偿还环 rep<0 凭空生钱)
        if float(st.get(sk,0)) < 0: raise ValueError(f"开账 stock {sk} 为负")
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
        elif t == '追赃':                         # 追缴中饱赃银 C_中饱→省库(CASH 内部,eff<1 入 C_eff损耗)
            mv = xfer_internal('C_中饱','省库库银', amt, a.get('eff',1.0))
            print(f"  追赃 {mv:.2f}(eff={a.get('eff',1.0)})")
        elif t == '清欠':                         # 收旧民欠:民间现金入
            收 = min(amt, claim['民欠旧赋']); cash['省库库银'] += 收; cash_in += 收
            claim['民欠旧赋'] -= 收; r['清欠'] += 收; print(f"  清欠 {收:.2f}")
        elif t == '蠲免':
            mj = min(amt, claim['民欠旧赋']); claim['民欠旧赋'] -= mj; r['蠲免'] += mj
            print(f"  蠲免 {mj:.2f}")

    # ── ②③④⑦ 应征/火耗/实征/民欠 ──
    正赋 = p.get('正赋应征', round(官民田*p.get('正赋亩额',0)/12,4)); 三饷 = p['三饷应征']
    fh = p['火耗率']; bf = p['逋赋率']
    正赋火耗 = 正赋*fh; 三饷火耗 = 三饷*fh          # 三饷亦银征同有火耗(史实);另立分量(spec §9)
    火耗应派 = 正赋火耗 + 三饷火耗
    r['实征'] = (正赋+三饷)*(1-bf); cash_in += r['实征']
    r['火耗实收'] = 火耗应派*(1-bf); cash['C_地方截留'] += r['火耗实收']; cash_in += r['火耗实收']
    r['民欠新增'] = (正赋+三饷)-r['实征']; claim['民欠旧赋'] += r['民欠新增']
    print(f"④⑦ 正赋{正赋:.2f} 火耗应派{火耗应派:.2f}(正赋{正赋火耗:.2f}+三饷{三饷火耗:.2f}) 实征{r['实征']:.2f} 火耗实收{r['火耗实收']:.2f} 民欠+{r['民欠新增']:.2f}")
    # ── ⑧⑨ 分池+漂没 ──
    起运池 = min(r['实征'], p['起运定额']); 省内池 = max(0.0, r['实征']-起运池)
    pm = p.get('漂没率',0.0); r['起运到京'] = 起运池*(1-pm); r['漂没'] = 起运池-r['起运到京']
    cash['C_漂没'] += r['漂没']; cash_out += r['起运到京']
    # ── ⑩ 拨付 gross/net+中饱 ──
    g = p.get('拨付gross',0.0); zb = p.get('中饱率',0.0); net = g*(1-zb); r['中饱'] = g-net
    cash['省库库银'] += net; cash['C_中饱'] += r['中饱']; cash_in += g; r['拨付gross'] = g
    print(f"⑧⑨⑩ 起运池{起运池:.2f} 省内池{省内池:.2f} 起运到京{r['起运到京']:.2f} 漂没{r['漂没']:.2f} 拨付g{g:.2f}(net{net:.2f}中饱{r['中饱']:.2f})")
    # ── ⑪ 省内可支→付款→偿还→结转 ──
    省内可支 = cash['省库库银'] + 省内池; Pool = 省内可支
    for h in ['军饷','官俸','宗禄','赈济']:
        d = p['Due'].get(h,0.0); pay = min(Pool,d); Pool -= pay; cash_out += pay; r['实付'] += pay
        nd = d-pay
        if h == '赈济': r['unmet_relief'] = nd          # 赈济不积欠,但输出未满足给 LLM(§9)
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
    # 独立重算 k(r15/opus:settlement 的 k 是同源中间量,oracle 必须自算,否则 k 被污染时 cash/debt 一致偏移漏过)
    o_Stock = float(st.get('省库库银',0)); o_ΣCost = sum(a.get('cost',0) for a in actions if a.get('cost',0) > 0)
    o_k = 1.0 if (o_ΣCost == 0 or o_ΣCost <= o_Stock) else o_Stock/o_ΣCost
    # 债务 per-account · 独立 oracle(r13/opus:同 C,从 params/claim0/action入参 重跑,堵科目 relabel)
    # 注(r15/sonnet 残留):o_pool 读 省内可支(运行时),对「C金额→省库」类 relabel 依赖 C 分账 oracle 兜底;勿单独删 C oracle
    o_pool = 省内可支; o_paid = {}
    for h in ['军饷','官俸','宗禄','赈济']:
        d = p['Due'].get(h,0.0); pay = min(o_pool,d); o_pool -= pay; o_paid[h] = pay
    o_nd = {'军饷欠':p['Due'].get('军饷',0)-o_paid['军饷'], '官俸欠':p['Due'].get('官俸',0)-o_paid['官俸'], '宗禄欠':p['Due'].get('宗禄',0)-o_paid['宗禄']}
    o_a还 = {'军饷欠':0.0}                       # 补饷:min(cost×k, 军饷欠@⓪),独立重算
    for a in actions:
        if a['type'] == '补饷':
            o_a还['军饷欠'] += min(a.get('cost',0)*(o_k if a.get('cost',0)>0 else 1.0), claim0['军饷欠']-o_a还['军饷欠'])
    o_S = o_pool; o_rep = {}
    for c in ['军饷欠','官俸欠','宗禄欠']:
        bal = claim0[c] - o_a还.get(c,0) + o_nd[c]; x = min(o_S, bal); o_rep[c] = x; o_S -= x
    ok_debt = True
    for c in ['军饷欠','官俸欠','宗禄欠']:
        exp = claim0[c] - o_a还.get(c,0) + o_nd[c] - o_rep[c]
        if abs(claim[c]-exp) > EPS: ok_debt=False; print(f"  [债务FAIL]{c} {claim[c]:.2f}≠oracle{exp:.2f}")
    o_my = claim0['民欠旧赋']                    # 民欠:⓪清欠/蠲免(clamp 顺序)→⑦民欠新增(param)
    for a in actions:
        if a['type'] in ('清欠','蠲免'):
            o_my -= min(a.get('amount',0)*(o_k if a.get('cost',0)>0 else 1.0), o_my)
    o_my += (正赋+三饷)*bf
    if abs(claim['民欠旧赋']-o_my) > EPS: ok_debt=False; print(f"  [债务FAIL]民欠 {claim['民欠旧赋']:.2f}≠oracle{o_my:.2f}")
    print(f"[债务对账·独立oracle] {'PASS' if ok_debt else 'FAIL'}")
    # per-account C 对账 · 独立 oracle(r14/opus:下沉到原始 param 重算,不读 settlement 的 火耗应派/起运池 局部变量)
    正赋_o = p.get('正赋应征', round(官民田*p.get('正赋亩额',0)/12,4))
    实征_o = (正赋_o + p['三饷应征'])*(1-bf)
    火耗应派_o = (正赋_o + p['三饷应征']) * fh      # 正赋火耗+三饷火耗,两分量均从 param 独立重算
    起运池_o = min(实征_o, p['起运定额'])
    o_in = {'C_地方截留': 火耗应派_o*(1-bf), 'C_中饱': g*zb, 'C_漂没': 起运池_o*pm, 'C_eff损耗': 0.0}
    o_out = {ck: 0.0 for ck in C0}
    bal_dfjl, bal_zb = C0['C_地方截留'], C0['C_中饱']   # ⓪挪借/追赃 时的余额(火耗实收⑦/中饱⑩ 才加)
    for a in actions:
        ak = o_k if a.get('cost',0) > 0 else 1.0
        if a['type'] == '挪借火耗':
            act = min(a.get('amount',0)*ak, bal_dfjl); bal_dfjl -= act
            o_out['C_地方截留'] += act; o_in['C_eff损耗'] += act*(1-a.get('eff',1.0))
        elif a['type'] == '追赃':
            act = min(a.get('amount',0)*ak, bal_zb); bal_zb -= act
            o_out['C_中饱'] += act; o_in['C_eff损耗'] += act*(1-a.get('eff',1.0))
    ok_C = True
    for ck in C0:
        exp = C0[ck] + o_in[ck] - o_out[ck]
        if abs(cash[ck]-exp) > EPS: ok_C=False; print(f"  [C分账FAIL]{ck} {cash[ck]:.2f}≠oracle{exp:.2f}(old{C0[ck]:.2f}+应得in{o_in[ck]:.2f}-out{o_out[ck]:.2f})")
    print(f"[C 分账·独立oracle] {'PASS' if ok_C else 'FAIL'}")
    # 土地守恒(r17/opus:清丈只把隐田重分类为官民田,总亩数不变;防凭空造地=违铁律P3的「发展爽感」)
    ok_land = abs((官民田+隐田) - 地0) < 1e-3
    if not ok_land: print(f"  [土地守恒FAIL] 官民田+隐田 {官民田+隐田:.2f}≠初始{地0:.2f}")
    print(f"[土地守恒] {'PASS' if ok_land else 'FAIL'}  (unmet_relief={r['unmet_relief']:.2f})")
    print(f"[末态] cash={{ {', '.join(f'{k}:{v:.2f}' for k,v in cash.items())} }}")
    print(f"       claim={{ {', '.join(f'{k}:{v:.2f}' for k,v in claim.items())} }} 官民田={官民田:.0f}")
    # 第4类断言:末态 vs 硬编码期望常量(codex r16:真正独立的锚,堵「债清了钱没出」级 bug——
    # 此类 bug 让 settlement 自己的 cash_in/out 一致少记,前三断言漏过,但末态≠常量必 FAIL)
    end = {**{k:round(v,4) for k,v in cash.items()}, **{k:round(v,4) for k,v in claim.items()}, 'unmet_relief':round(r['unmet_relief'],4)}
    ok_exp = True
    if expect is not None:
        for kk,vv in expect.items():
            if abs(end.get(kk,1e99)-vv) > 1e-3: ok_exp=False; print(f"  [末态FAIL]{kk} {end.get(kk)}≠期望{vv}")
        print(f"[末态硬期望] {'PASS' if ok_exp else 'FAIL'}")
    else:
        print(f"[末态硬期望] (无 expect,捕获用)EXPECT={ {k:round(v,2) for k,v in end.items() if abs(v)>1e-9} }")
    new_st = dict(cash); new_st.update(claim); new_st['官民田']=官民田; new_st['隐田']=隐田
    new_st['unmet_relief']=r['unmet_relief']            # §9:输出给 LLM 裁判
    return (ok_cash and ok_debt and ok_C and ok_exp and ok_land), new_st


base = dict(正赋应征=60,三饷应征=10,火耗率=0.2,逋赋率=0.3,起运定额=40,漂没率=0.0,拨付gross=0,中饱率=0.0,
            Due=dict(军饷=45,官俸=8,宗禄=4,赈济=0))
def S(**kw): return dict(dict(省库库银=50,C_地方截留=0,C_中饱=0,C_漂没=0,C_eff损耗=0,
                              民欠旧赋=0,军饷欠=20,官俸欠=0,宗禄欠=0,官民田=3050,隐田=1600), **kw)
R = []
def go(name, st, p, acts, expect=None): ok,_ = run_tick(name, st, p, acts, expect); R.append((name, ok)); return _
def go_raise(name, st, p, acts):                     # 断言非法输入 fail-loud
    try: run_tick(name, st, p, acts); R.append((name, False)); print(f"  [应RAISE但没有]{name}")
    except ValueError as e: R.append((name, True)); print(f"\n{name}: RAISED ✓ ({e})")

go("G1 基线", S(), base, [], {'C_地方截留':9.8,'民欠旧赋':21,'军饷欠':18})
go("G2 补饷k=.33", S(省库库银=10,军饷欠=50), base, [dict(type='补饷',cost=30)], {'C_地方截留':9.8,'民欠旧赋':21,'军饷欠':76,'官俸欠':8,'宗禄欠':4})
go("G3 清丈(cost2,非现金中性:当tick扣2)", S(), base, [dict(type='清丈',cost=2,挖隐田=300)], {'C_地方截留':9.8,'民欠旧赋':21,'军饷欠':20})
go("G4 挪借火耗(C20,挪10)", S(C_地方截留=20), base, [dict(type='挪借火耗',amount=10)], {'C_地方截留':19.8,'民欠旧赋':21,'军饷欠':8})
go("G5 漂没.1中饱.1拨付30", S(), dict(base,漂没率=0.1,中饱率=0.1,拨付gross=30), [], {'省库库银':9,'C_地方截留':9.8,'C_中饱':3,'C_漂没':4,'民欠旧赋':21})
go("G6 超额补饷(欠5补30)", S(省库库银=30,军饷欠=5), base, [dict(type='补饷',cost=30)], {'C_地方截留':9.8,'民欠旧赋':21,'军饷欠':11,'官俸欠':8,'宗禄欠':4})
go("G7 清欠(民欠15清10)", S(民欠旧赋=15), base, [dict(type='清欠',amount=10)], {'C_地方截留':9.8,'民欠旧赋':26,'军饷欠':8})
go("G8 挪借eff=.8(激活C_eff损耗)", S(C_地方截留=20), base, [dict(type='挪借火耗',amount=10,eff=0.8)], {'C_地方截留':19.8,'C_eff损耗':2,'民欠旧赋':21,'军饷欠':10})
go("G10 追赃(C_中饱12,追8 eff=.9)", S(C_中饱=12), base, [dict(type='追赃',amount=8,eff=0.9)], {'C_地方截留':9.8,'C_中饱':4,'C_eff损耗':0.8,'民欠旧赋':21,'军饷欠':10.8})
go("G11 多costed(补饷20+营建20,Stock10→k=.25)", S(省库库银=10,军饷欠=50), base,
   [dict(type='补饷',cost=20), dict(type='营建',cost=20)], {'C_地方截留':9.8,'民欠旧赋':21,'军饷欠':81,'官俸欠':8,'宗禄欠':4})
go("G12 赈济Due>0", S(省库库银=80), dict(base, Due=dict(军饷=45,官俸=8,宗禄=4,赈济=15)), [], {'C_地方截留':9.8,'民欠旧赋':21,'军饷欠':3})
go("G13 拨付30+追赃(C_中饱10,追6)同tick", S(C_中饱=10), dict(base,拨付gross=30,中饱率=0.1),
   [dict(type='追赃',amount=6)], {'省库库银':15,'C_地方截留':9.8,'C_中饱':7,'民欠旧赋':21})
# G14 动态税基(codex r16:正赋从官民田派生,清丈本 tick 即抬税基;硬期望咬住「清丈effect算错」)
_p14 = {k:v for k,v in base.items() if k!='正赋应征'}; _p14['正赋亩额']=0.236
go("G14 动态税基(正赋亩额0.236+清丈+300)", dict(S(), 官民田=3050), _p14,
   [dict(type='清丈',cost=2,挖隐田=300)], {'C_地方截留':10.6237,'民欠旧赋':22.765,'军饷欠':15.8817})
# G15 双债户偿还优先级(军饷欠20+官俸欠20,余银只够还22→军饷先全清、官俸还2;堵偿还顺序 relabel)
go("G15 双债户偿还序(军饷>官俸)", S(省库库银=70,军饷欠=20,官俸欠=20), base, [],
   {'C_地方截留':9.8,'民欠旧赋':21,'军饷欠':0,'官俸欠':18,'宗禄欠':0})
# G16 土地守恒+清丈枯竭(隐田仅200,挖300被 clamp 到200;官民田+隐田 守恒;堵凭空造地=违铁律P3)
go("G16 清丈枯竭(隐田200挖300)", S(隐田=200), base, [dict(type='清丈',cost=2,挖隐田=300)],
   {'C_地方截留':9.8,'民欠旧赋':21,'军饷欠':20})
# G17 赈济饿死(穷省可支9,赈济Due15→实付9、unmet_relief6、不积欠;堵 unmet 不可见)
go("G17 赈济饿死(unmet_relief)", S(省库库银=0,军饷欠=0), dict(base,Due=dict(军饷=0,官俸=0,宗禄=0,赈济=15)),
   [], {'C_地方截留':9.8,'民欠旧赋':21,'军饷欠':0,'unmet_relief':6})
# G18 三债户 waterfall 边界(可支16,军饷10足额/官俸8部分→欠2/宗禄4→欠4;钉官俸↔宗禄序)
go("G18 三债户waterfall序(官俸>宗禄)", S(省库库银=16,军饷欠=0), dict(base,起运定额=50,Due=dict(军饷=10,官俸=8,宗禄=4,赈济=0)),
   [], {'C_地方截留':9.8,'民欠旧赋':21,'官俸欠':2,'宗禄欠':4})
# G19 三债户 repay 边界(余银13先还官俸欠10、再还宗禄欠3→7;钉偿还在第2、3债户间切分)
go("G19 三债户repay序", S(省库库银=70,军饷欠=0,官俸欠=10,宗禄欠=10), dict(base,起运定额=100),
   [], {'C_地方截留':9.8,'民欠旧赋':21,'官俸欠':0,'宗禄欠':7})
# G20 蠲免(免民欠8,不入现金;钉下游军饷欠=18 区分蠲免vs清欠——清欠会让现金多8→军饷欠掉到10)
go("G20 蠲免(民欠15免8,不入现金)", S(民欠旧赋=15), base, [dict(type='蠲免',amount=8)],
   {'C_地方截留':9.8,'民欠旧赋':28,'军饷欠':18})
# G22 三饷火耗分量(三饷30:火耗应派=(60+30)×.2=18,实收12.6;钉「三饷计火耗」——只派正赋则 C=8.4 必FAIL)
go("G22 三饷火耗分量(三饷30)", S(), dict(base,三饷应征=30), [],
   {'C_地方截留':12.6,'民欠旧赋':27,'军饷欠':4})
# G21 非法输入 fail-loud(负挖隐田=反向清丈缩税基,LLM 可达,五层抓不到只能 input 校验拦)
go_raise("G21 负挖隐田应RAISE", S(), base, [dict(type='清丈',cost=2,挖隐田=-100)])
go_raise("G21b unknown action应RAISE", S(), base, [dict(type='发射导弹',cost=5)])
go_raise("G21c 负Due应RAISE", S(), dict(base,Due=dict(军饷=-45,官俸=8,宗禄=4,赈济=0)), [])
go_raise("G21d 负起运定额应RAISE", S(), dict(base,起运定额=-40), [])
go_raise("G21e 负拨付gross应RAISE", S(), dict(base,拨付gross=-30), [])
go_raise("G21f 负开账省库应RAISE", S(省库库银=-10), base, [])
go_raise("G21g 0-cost清丈应RAISE(免费抬税基)", S(), base, [dict(type='清丈',cost=0,挖隐田=300)])
go_raise("G21h NaN cost应RAISE", S(), base, [dict(type='营建',cost=float('nan'))])
# G21i–l 负开账 CLAIM(codex r4:负军饷欠进偿还环 rep=min(S,负)<0 → S 反增=凭空生钱;守恒/oracle 同源负值全漏,只能入口拦)
go_raise("G21i 负开账军饷欠应RAISE", S(军饷欠=-5), base, [])
go_raise("G21j 负开账民欠旧赋应RAISE", S(民欠旧赋=-5), base, [])
go_raise("G21k 负开账官俸欠应RAISE", S(官俸欠=-5), base, [])
go_raise("G21l 负开账宗禄欠应RAISE", S(宗禄欠=-5), base, [])

# G9 三 tick 链:穷省(省库10)+ recurring 募兵(每 tick cost5),看死亡螺旋累积 + 每 tick 守恒 + 硬期望
print(f"\n{'#'*64}\n# G9 三 tick 链(穷省 recurring 募兵,死亡螺旋)\n{'#'*64}")
stt = S(省库库银=10, 军饷欠=30)
g9exp = [{'C_地方截留':9.8,'民欠旧赋':21,'军饷欠':61,'官俸欠':8,'宗禄欠':4},
         {'C_地方截留':19.6,'民欠旧赋':42,'军饷欠':97,'官俸欠':16,'宗禄欠':8},
         {'C_地方截留':29.4,'民欠旧赋':63,'军饷欠':133,'官俸欠':24,'宗禄欠':12}]
allok = True
for i in range(1,4):
    duep = dict(base, Due=dict(军饷=45,官俸=8,宗禄=4,赈济=0))
    ok, stt = run_tick(f"G9 tick{i}", stt, duep, [dict(type='营建',cost=5,cost_type='recurring')], g9exp[i-1])
    allok = allok and ok
R.append(("G9 三tick链", allok))

print(f"\n{'='*64}\n汇总:")
for n,ok in R: print(f"  {'PASS' if ok else 'FAIL':5s} {n}")
print(f"  全部 {'PASS' if all(o for _,o in R) else 'FAIL'}")
print('='*64)
