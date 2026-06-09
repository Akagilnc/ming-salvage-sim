# 省级财政基座 · 草表 v11(spike 执行验证 · 守恒断言改实测式)

> **范围:仅锁单省 spine(陕西);跨省 hub deferred;`拨付net/gross` 为 tick 外部入参(测试默认 0)。**
> v11:把一次性 spike([spike_settle_tick.py](../spike_settle_tick.py))**执行验证过**的结论写进文档 ——
> ① §6.6 守恒断言从 tautology(`82=...`)换成 **spike 跑平的真复式式**(Δcash = 民间流出 − 受款方流入)
> ② 账户口径按 spike 三类(CASH / BOUNDARY / CLAIM)钉死 ③ 新增 §6.7 引 spike 当 golden 种子。
> spike 实测:**G1 + G2(含 action+k=0.333)守恒残差均 = 0,PASS**;并实锤旧 §6.6「82=...」永真测不出 bug。
> 评审 r1–r10(panel=codex/agy/opus/sonnet)。决策见 [ADR 0007](adr/0007-province-fiscal-substrate-ai-judged.md)。⚠️=待精验。

## 0. 账户模型(三类 · spike 口径)
- **CASH(真金,跨账户守恒,万两)**:`省库库银`(A-stock,跨期)· `C_地方截留`(火耗实收)· `C_中饱` · `C_漂没` · `C_eff损耗`。
- **BOUNDARY(系统边界,记净流,非引擎余额)**:`民间`(征收 source:实征+火耗实收 从此交出现金)· `受款方`(支付 sink:起运到京 + 实付 + 偿旧欠 流入)。
- **CLAIM(债权债务,非现金 memo)**:`B.民欠旧赋`(民欠官,债权)· `B.军饷欠/官俸欠/宗禄欠`(官欠受款方,负债)。
- **Flow(每 tick 清零)**:正赋/三饷/火耗应派 · 实征 · 火耗实收 · 起运池/省内池 · 起运到京 · 拨付net · 清欠/追赃/挪借入库 · 省内可支 · 应付/实付 · 新增欠账 · 偿还。
- **钱类 CASH/CLAIM stock 只经 `delta`/`transfer_to` 变动,禁 `set`、禁 `scale` modifier。**

## 0.1 守恒不变式(spike 实测式,取代旧 tautology)
**主断言(现金双边平,spike G1/G2 残差 0)**:
```
Δ(Σ CASH) == 民间流出 − 受款方流入
  其中 民间流出 = 实征 + 火耗实收
       受款方流入 = 起运到京 + Σ实付(军饷/官俸/宗禄/赈济) + Σ偿旧欠
```
**债务对账**:`B.负债_new = B.负债_old + NewDebt_i − Repaid_i`;`B.民欠_new = B.民欠_old + 民欠新增 − 清欠 − 蠲免`。
**C 灰账对账**:`C_new = C_old + 火耗实收 + 漂没 + 中饱 + eff损耗 − (追赃+挪借)`。
**每笔 `transfer_to` 三方平**:`source减 = target增 + loss_sink增`(`actual=min(amount,source)`;BOUNDARY 账户 民间/受款方 **无余额 clamp**)。
> 旧式「三本账总额=拨付−起运」**作废**:spike 证它退化成 `民负担 ≡ 实征+火耗实收+民欠+火耗未收`(因 火耗应派≡火耗实收+火耗未收),永真、测不出 bug。

## 1. 单位制 + cost_type(同 v10)
年额÷12·月额万两/月·stock万两·税额两/亩·年(非0-1)·真率0-1。action「银」amount=每tick成本,cost_type=one_time/recurring。

## 2. 月度结算顺序(省级 ⓪–⑪ + 全局 ⑫,同 v10)
⓪ Flow清零→modifier衰减→resolve新action(transfer_to 立即执行,清欠/追赃/挪借 target 走 Flow 入库)→批量算k→`省库库银_post=Stock_start−Σ(k·银Cost)`(Stock_start=⓪执行前=上月结转)。
①折月 ②③应征 ④火耗应派→民负担(未实收不积欠)⑤⑥负担率/逋赋率(灾→下限)⑦实征→可支、火耗实收→C、民欠→B ⑧`起运池=min(实征,定额)`/`省内池=max(0,实征−起运池)` ⑨漂没→C ⑩拨付gross扣/net→可支/中饱→C ⑪付款+偿还+结转(省库库银_new=S,覆盖写)⑫(全局)国库入账。

## 3. 付款 waterfall / 4–5. schema / 6. 执行归一化(同 v10)
1军饷>2官俸>3宗禄>4赈济(Due_4=action amount,NewDebt_4≡0);民欠=清欠/蠲免无官偿还;火耗实收进C需「挪借火耗」action 转出。
k=action力度系数(ΣCost仅含action银,Due不入;Cost>0 action其 delta/scale/transfer_to.amount 全×k;0-cost不缩)。modifier `V_final=clamp(V_base×∏max(0,1+scale)+Σdelta)`,V_base静态不复利,钱类Stock禁set/scale。transfer_to source/target 类型白名单(CASH/CLAIM/BOUNDARY 或指定 Flow)。
**现金 action 二选一**(防双扣):支付类(补饷/赈济)= 银 Cost 即该笔支付,不再另记 Due;行政成本类 = Cost 扣省库,另带 effect。(spike G2 已验补饷 k=0.333 无双扣。)

## 6.6 golden-tick(spike 实测,带数字)
见 [spike_settle_tick.py](../spike_settle_tick.py),已执行 PASS:
- **G1**(无 action,k=1):Stock_start=50、正赋60/三饷10、火耗率0.2、逋赋率0.3、起运定额40、Due 军饷45/官俸8/宗禄4、军饷欠_old20 → 实征49/火耗实收8.4/民欠+21/起运到京40/省内池9/可支59/付45·8·4/偿军饷欠2→军饷欠18/结转0。**守恒残差0。**
- **G2**(补饷 action,银30、Stock_start=10→k=0.333):eff_cost10→受款方+军饷欠−10→40;省库耗光→可支9→军饷只付9→军饷欠40+36=76、官俸欠+8、宗禄欠+4(穷省欠饷暴涨=死亡螺旋)。**守恒残差0,无双扣。**
- 待补 golden:G3 清丈(隐田↓官民田↑+士绅阻力)、G4 挪借火耗(C→可支)、G5 漂没/中饱(efficiency<1 入 C)。

## 6.7 可执行 spike(golden 种子)
`spike_settle_tick.py` = 纯 dict 复式记账原型(非引擎、throwaway),实现 ⓪–⑪ + §0.1 守恒断言,跑 G1/G2 打印逐步流水 + 守恒 PASS/FAIL。**它就是将来真引擎 golden test 的种子**:port 进 `ming_sim` 时把 G1–Gn 转成 pytest 断言即可。

## 7–8. 状态/派生/螺旋/铁律/实现规约(同 v10)
死亡螺旋(AI耦合+灾→逋赋下限+按册派刚性,G2 已显现)、5 铁律见 ADR 0007;逋赋率 clamp(0,1)、民欠蠲免 max(0,·);实现规约五条 + §6.6/6.7。

## 待精验
各 f() 具体形 · G3–G5 golden 数字 · 数值边界 · 征收能力/士绅协作/粮价/运输/宗室口/驿卒 seed · 负担标准值校准。

## Sources
[1][西安府田亩](https://zhuanlan.zhihu.com/p/1917691584633369550) [2][三边京运](https://zhuanlan.zhihu.com/p/30177486035) [3][宗禄](https://zhuanlan.zhihu.com/p/508242610) [5][官俸薄](https://news.bjd.com.cn/2022/08/15/10134150.shtml) [6][裁驿](https://zhuanlan.zhihu.com/p/51748875) [7][三饷](https://zh.wikipedia.org/zh-hans/%E4%B8%89%E9%A4%89)
