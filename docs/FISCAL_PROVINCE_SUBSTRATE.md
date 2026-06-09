# 省级财政基座 · 草表 v7(r6 返工 · 实现规约就位 · spine 已锁)

> r6 三家(codex/agy/grok)一致「spine 可锁,可开写引擎」。v7 把剩余**开发规约**转写进文档(非架构):① `transfer_to` 守恒算子(防凭空印钱)② Stock/Flow 变量清单 ③ 级联计算顺序 ④ 0-cost action 不被 k 缩 ⑤ 乘积项防负 ⑥ B 负债 vs 债权 ⑦ set 离散/非银资源/Paid-Due 输出。
> 评审 r1–r6(codex×6/agy×3/grok×3,r6 全员点头)。决策见 [ADR 0007](adr/0007-province-fiscal-substrate-ai-judged.md)。⚠️=待精验。样本=陕西。

## 0. 三本账 + 国库边界 + Stock/Flow 清单
- **A 月流**(每 tick 重置为 0) + **A-stock 省库库银**(跨期)· **B 欠账**(负债:军饷/官俸/宗禄欠;债权:民欠旧赋)· **C 灰账**(可追回:地方截留/中饱赃银;sink:漂没损失)。
- **国库 = 全局外部 hub**;省级只产「起运到京(→hub)/受拨付net(←hub)」;`拨付gross` 是 hub 给省级的**外部输入**;⑫ 国库入账为全局步骤。
- **Stock(跨期持久,r6/agy)**:省库库银 · B.军饷/官俸/宗禄欠 · B.民欠旧赋 · C.地方截留 · C.中饱赃银 · 民口 · 官民田 · 隐田 · 各软轴 · stock-类政策态。
- **Flow(每 tick 开头清零)**:正赋/三饷/火耗应派 · 实征 · 火耗实收 · 起运池 · 省内池 · 起运到京 · 拨付net · 清欠入库 · 追赃入库 · 省内可支 · 应付/实付 · 新增欠账 · 旧债偿还。
- **不变式**:`实征=起运池+省内池` · `应付=实付+欠账新增B` · `gross=net+中饱C` · `起运池=起运到京+漂没C` · `应征(正税=正赋+三饷)=实征+民欠新增B` · `省库库银结转=省内可支−本月支出−偿还B ≥0` · **全局守恒:任何 Stock→Flow 转移只走 §8 `transfer_to`,actual=min(amount,source)**。

## 1. 单位制(同 v4–v6)
年额÷12入月 · 月额万两/月 · stock 万两 · 税额(亩额 两/亩·年,非0-1)· 真率0-1 · action「银」`amount`=**每 tick 成本**(一次性=duration0扣一次;持续=每tick各扣)。

## 2. 月度结算顺序(省级 ⓪–⑪ + 全局 ⑫)
⓪ action phase(§6.1:modifier 衰减→resolve action→成本扣上月省库库银,§6.2 同比缩 k)· ① 年额折月 · ②③ 正赋/三饷应征 · ④ 火耗应派→民负担(未实收**不积欠**,§7注)· ⑤⑥ 负担率/逋赋率(灾→下限)· ⑦ 实征→A、火耗实收→C.地方截留、民欠→B · ⑧ `起运池=min(实征,定额)`、`省内池=max(0,实征−起运池)` · ⑨ 漂没→C.sink · ⑩ 拨付 gross(外部)扣、net→A、中饱→C.赃银 · ⑪ **付款+偿还+结转**(§6.5,省内可支见 §8 总公式)· ⑫(全局)国库入账。

## 3. 付款 waterfall
省内可支按优先级付,短缺即欠:**1 驻军饷→军饷欠** · **2 官俸/行政→官俸欠** · **3 宗禄→宗禄欠** · **4 赈济**(discretionary,不累欠)。民欠旧赋=官的债权,只能 **清欠**(`transfer_to` B.民欠→清欠入库)或 **蠲免**(B.民欠↓+民心↑,官不得钱);**无官偿还民欠**。

## 4–5. typed schema / reason_code(同 v6)
`action_id, inputs, effects[]{field_path,op:delta|set|scale|transfer_to,amount,unit,duration_months}, clamp_return{per_effect,reason_codes[],binding_constraints,blocking_vars}`。reason_code 枚举同 v6。

## 6. 执行归一化(算法层,同 v6 + r6 精修)
**6.1** action 在 ⓪ 月结前 resolve。
**6.2 成本 + 0-cost 不缩(r6/agy)**:`k = (Σ_{Cost>0}Cost ≤ Stock_start) ? 1 : Stock_start / Σ_{Cost>0}Cost`;**仅对 Cost>0 的 action 缩力度/effect ×k**,0-cost action 不受影响;`省库库银_post = Stock_start − Σ(k·Cost_i)`(`min(1,·)` 已含)。
**6.3 modifier 唯一公式 + 防负(r6/agy)**:`V_final = clamp( V_base × ∏ max(0,1+scale_i) + Σdelta_j, min, max )`;`set` 先覆盖 V_base;同 field 多 set 按 action 提交顺序后者覆盖前者。**衰减**:⓪ 前存续 modifier `duration−1`、减到0移出;`duration=-1`=永久不衰减;新 action 本 tick 计入初值 N。**离散 set 效果**:`k<1` 时不按 k 缩,直接**不触发**(只数值 delta 随 k 缩)。
**6.4 transfer_to(守恒,防凭空印钱,r6/agy)**:Stock→Flow/Stock 转移唯一算子 `{source,target,amount,efficiency}`:`actual=min(amount,source.value)`;`source−=actual`;`target+=actual×efficiency`。清欠/追赃/补饷全走它,**绝不写成两条独立 delta**。
**6.5 付款/偿还纯代数**:`Pool=省内可支`;优先级1→4 `Paid_i=min(Pool,Due_i)`,`Pool−=Paid_i`,`NewDebt_i=Due_i−Paid_i`;余 `S=Pool` 顺次偿**负债类**旧债(军饷欠>宗禄欠>官俸欠,**不含民欠债权**)`Repaid_i=min(S,B_i)`;`省库库银结转=S`;`B_i,new=B_i,old+NewDebt_i−Repaid_i`。

## 7. 状态/派生/死亡螺旋/铁律(同 v3–v6)
含死亡螺旋(AI耦合+灾→逋赋下限+按册派刚性)、5 铁律(ADR 0007)。**注**:火耗未实收不积欠(附加税,不作正税追讨);确认不做追缴火耗。

## 8. 实现规约附录(开发约定 · 写引擎前入开发文档 · r6 五点)
1. **`transfer_to` 守恒算子**(见 §6.4)—— 所有 Stock↔Flow 资金转移唯一通路,杜绝资金不守恒。
2. **Stock/Flow 变量清单**(见 §0)—— 引擎初始化时 Flow 全清零、Stock 持久;实现者据此不致一方累加一方清零。
3. **级联计算顺序** —— 严格按 ⓪–⑪;算出某变量即应用其 modifier 得 `V_final`,下游**只引用 V_final**(如 `起运池=min(实征_final,定额_final)`)。
4. **非银资源(人/权/政治槽)** —— 由 LLM 裁判/外部校验,引擎默认充足或只 clamp 特定 effect,**不整组同比缩**(同比缩只因银不足)。
5. **裁判输出** —— 每 tick 暴露只读 `Paid_i/Due_i`(尤其军饷、赈济)供 LLM 裁判评兵变/民变;引擎自身不判兵变。

## 待精验
各 f() 具体形(可占位线性/分段)· 损耗率/efficiency/同比缩/蠲免 数值边界 · 征收能力/士绅协作/粮价/运输/宗室口/驿卒 seed · 负担标准值校准。

## Sources
[1][西安府田亩](https://zhuanlan.zhihu.com/p/1917691584633369550) [2][三边京运](https://zhuanlan.zhihu.com/p/30177486035) [3][宗禄](https://zhuanlan.zhihu.com/p/508242610) [5][官俸薄](https://news.bjd.com.cn/2022/08/15/10134150.shtml) [6][裁驿](https://zhuanlan.zhihu.com/p/51748875) [7][三饷](https://zh.wikipedia.org/zh-hans/%E4%B8%89%E9%A4%89)
