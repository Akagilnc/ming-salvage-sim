# 省级财政基座 · 草表 v6(r5 返工 · 执行归一化到算法级 · 锁 spine)

> v6 把 r5(codex+agy)给的落锁公式转写进文档:① 一条总现金流公式 ② action 成本扣上月省库库银 + 同比缩 k(断循环依赖)③ modifier 唯一叠加公式 + 衰减时点 ④ C→A/清欠落账 ⑤ 付款/偿还纯代数 ⑥ 资金 vs 非资金 clamp ⑦ 拨付gross 声明为外部输入。
> 评审 r1–r5(codex×5/agy×2/grok×2)。决策见 [ADR 0007](adr/0007-province-fiscal-substrate-ai-judged.md)。⚠️=待精验。样本=陕西。

## 0. 三本账 + 省库库银 + 国库边界 + 不变式
- **A 月流** + **A-stock 省库库银**(跨期结余)· **B 欠账**(军饷/宗禄/官俸欠 · 民欠旧赋)· **C 灰账**:可追回(地方截留=火耗实收 · 中饱赃银)/ sink(漂没损失)。
- **国库 = 全局外部 hub**;省级只产「起运到京(→hub)」「受拨付net(←hub)」;`拨付gross[t,省]` 是 hub **预先给省级的外部输入**(非省级算,断 ⑩/⑫ 循环);⑫ 国库入账是全局步骤。
- **不变式(每 tick 断言)**:`实征=起运池+省内池` · `应付=实付+欠账新增B` · `gross=net+中饱C` · `起运池=起运到京+漂没C` · `应征=实征+民欠新增B`(旧欠回收**不**进本月应征)· 现金流见 §6 总公式,末了 `省库库银结转 = 省内可支 − 本月支出 − 偿还B ≥ 0`。

## 1. 单位制(同 v4/v5)
年额量÷12入月 · 月额万两/月 · stock 万两 · 税额(亩额,两/亩·年,非0-1)· 真率0-1 · action「银」标 duration_months。

## 2. 月度结算顺序(省级 ⓪–⑪ + 全局 ⑫)
| # | 步骤 | 公式 → 落账 |
|---|---|---|
| ⓪ | **action phase**(见 §6.1) | modifier 衰减(§6.3)→ resolve 本 tick action;**成本只扣「上月省库库银」**,不够则同比缩 k(§6.2);得 `省库库银_post` |
| ① | 年额折月 | ÷12 / 折银 |
| ②③ | 正赋/三饷应征 | 官民田×亩额÷12 |
| ④ | 火耗应派 | 正赋应征×火耗率 → 民负担(⑤),不进 A;**未实收部分不积欠**(火耗是附加税,不作正税追讨——见 §7 注) |
| ⑤⑥ | 负担率 / 逋赋率 | (正赋+三饷+火耗应派)÷民口÷标准值;逋赋率=f(灾,负担率,民变,征收能力),灾→下限 |
| ⑦ | 实征/火耗实收/民欠 | 实征=(正赋+三饷)×(1−逋赋率)→A;火耗实收=火耗应派×(1−逋赋率)→C.地方截留;民欠=应征−实征→B.民欠旧赋 |
| ⑧ | 起运/省内分池 | `起运池=min(实征,起运定额)`;`省内池=max(0,实征−起运池)`;起运短解→国库global少进 |
| ⑨ | 漂没 | 起运到京=起运池×(1−漂没率)→A;差额→C.漂没损失(sink) |
| ⑩ | 拨付 gross/net | 国库扣 gross(外部输入);地方收 net=gross×(1−中饱率)→A;差额→C.中饱赃银(可追回) |
| ⑪ | **付款+偿还+结转**(见 §6.4–6.5) | `省内可支 = 省内池 + 省库库银_post + 拨付net + 清欠入库 + 追赃入库`,按 §6.5 代数付款/偿还,末了结转 |
| ⑫ | (全局)国库入账 | Σ起运到京 − Σ拨付gross − 中央定额支出 |

## 3. 付款 waterfall(民欠=清欠/蠲免,不在付款表)
省内可支按优先级付,短缺即欠:**1 驻军饷→军饷欠** · **2 官俸/行政→官俸欠** · **3 宗禄→宗禄欠** · **4 赈济/其他**(discretionary,不累欠,不够直接缩)。
民欠旧赋是官的应收:只能**清欠**(`民欠↓ + A.清欠入库↑`)或**蠲免**(`民欠↓ + 民心↑`,官不得钱);**无「官偿还民欠」**。

## 4. typed action/clamp schema + 原子性
```
action_id, inputs{目标,力度,资源{银{amount,duration_months},人,权,政治槽}}
effects[]{ field_path, op:delta|set|scale, amount, unit, duration_months }
clamp_return{ per_effect[{field_path,requested,applied}], reason_codes[](主因前), binding_constraints[], blocking_vars[] }
```
**原子性两档**(codex r5 收口):
- **资金不足(前置)**:整 action 按可付比例缩力度 k,所有 effect ×k(§6.2)。
- **非资金 clamp**(GENTRY_RESISTANCE/LOW_ADMIN_CAPACITY 等):**只 clamp 受限的那条 effect,不拖累整组**(其余 effect 照常)。

## 5. reason_code 枚举
`INSUFFICIENT_FUNDS·DISASTER_FLOOR·LOW_ADMIN_CAPACITY·GENTRY_RESISTANCE·TRANSPORT_BOTTLENECK·CLAN_RESISTANCE·MUTINY_RISK·NO_BUDGET_HEADROOM·REBOUND·APPLIED·AI_DILEMMA`;多约束→数组,主因前。

## 6. 执行归一化(算法层 · 引擎照此 · 两实现者必同 tick)
**6.1 action phase**:在 ⓪、月结①前 resolve;本月各步用 resolve 后状态。
**6.2 action 成本 + 断循环依赖**:tick 开头可用 = `上月省库库银 Stock_start`(已知,**不依赖本月实征**)。若 `ΣCost > Stock_start`,则 `k = Stock_start/ΣCost`,所有 action 力度与 effect ×k,实扣 `k·ΣCost`;`省库库银_post = max(0, Stock_start − ΣCost)`。
**6.3 modifier 唯一叠加公式**:任意属性 V,只读基线 `V_base`,激活 modifier:
`V_final = clamp( V_base × ∏(1+scale_i) + Σ(delta_j), min, max )`;`set` 覆盖型先令 `V_base = amount` 再乘加。**禁** imperative 改值+反向回滚。
**衰减时点**:⓪ 结算前所有存续 modifier `duration−1`,减到 0 立即移出栈;新 resolved action modifier 本 tick 计入,初值 N(本月即第 1 个 tick)。
**6.4 C→A 追赃 / 清欠入库**:清账追赃:`C.地方截留|中饱赃银 −X` → `追赃入库 += X×(1−损耗率)`(本月一次性流入省内可支,**不重跑起运分池**)。清欠:`B.民欠旧赋 −Y` → `清欠入库 += Y`(旧欠回收,不进本月应征)。
**6.5 付款/偿还纯代数**:`Pool=省内可支`;按优先级 1→4:`Paid_i=min(Pool,Due_i)`,`Pool−=Paid_i`,`NewDebt_i=Due_i−Paid_i`。付完若余 `S=Pool>0`,顺次偿旧债(军饷欠>宗禄欠>官俸欠):`Repaid_i=min(S,B_i)`,`B_i−=Repaid_i`,`S−=Repaid_i`。`省库库银结转=S`;`B_i,new=B_i,old+NewDebt_i−Repaid_i`。

## 7. 状态/派生/死亡螺旋/铁律(同 v3–v5)
一级状态(基数/人口分层/软轴/出血/三本账 stock+省库库银/政策态/标准值)、二级派生(各率/负担率/local_balance/兵变压力/流寇压力)、死亡螺旋(AI耦合+灾→逋赋下限+按册派刚性)、5 铁律见 ADR 0007。
**注(agy r5)**:火耗未实收部分不进 B、直接消失 —— 史实合理(附加税,百姓不交官府无法作正税追剿)。**本设计确认火耗不做积欠追讨**;若将来要「追缴火耗」需另加 stock,但当前不做、不算缺口。

## 待精验
各 f() 具体形(可占位线性/分段)· 损耗率/清欠/蠲免/同比缩 数值边界 · 征收能力/士绅协作/粮价/运输/宗室口/驿卒 seed · 负担标准值校准。

## Sources
[1][西安府田亩](https://zhuanlan.zhihu.com/p/1917691584633369550) [2][三边京运](https://zhuanlan.zhihu.com/p/30177486035) [3][宗禄](https://zhuanlan.zhihu.com/p/508242610) [5][官俸薄](https://news.bjd.com.cn/2022/08/15/10134150.shtml) [6][裁驿](https://zhuanlan.zhihu.com/p/51748875) [7][三饷](https://zh.wikipedia.org/zh-hans/%E4%B8%89%E9%A4%89)
