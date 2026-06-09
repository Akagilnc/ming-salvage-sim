# 省级财政基座 · 草表 v14(独立 oracle 对账 · 堵一致 relabel)

> **范围:仅锁单省 spine(陕西);跨省 hub deferred;`拨付net/gross` 为 tick 外部入参(测试默认 0)。**
> v14(r13 返工):**对账期望值全改「独立 oracle」**——从 tick 输入参数重算,不用落账时同源记的流水(r13/opus 实锤:同源流水式是 tautology,贪墨/军饷欠 一致 relabel 照样过)。C 侧 + 债务侧均上独立 oracle。
> spike 实测:**G1–G9 全 PASS;自变异实证——中饱→省库、火耗→省库、军饷新债→官俸欠 三种一致 relabel 现金守恒仍 PASS 但独立 oracle 当场 FAIL**([spike_settle_tick.py](../spike_settle_tick.py))。
> 评审 r1–r13(panel=codex/agy/opus/sonnet)。决策见 [ADR 0007](adr/0007-province-fiscal-substrate-ai-judged.md)。⚠️=待精验。

## 0. 账户模型(三类 · spike 口径)
- **CASH(真金,跨账户守恒,万两)**:`省库库银`(A-stock,跨期)· `C_地方截留`(火耗实收)· `C_中饱` · `C_漂没` · `C_eff损耗`。
- **BOUNDARY(系统边界,记净流,非引擎余额)**:`民间`(征收 source:实征+火耗实收 从此交出现金)· `受款方`(支付 sink:起运到京 + 实付 + 偿旧欠 流入)。
- **CLAIM(债权债务,非现金 memo)**:`B.民欠旧赋`(民欠官,债权)· `B.军饷欠/官俸欠/宗禄欠`(官欠受款方,负债)。
- **Flow(每 tick 清零)**:正赋/三饷/火耗应派 · 实征 · 火耗实收 · 起运池/省内池 · 起运到京 · 拨付net · 清欠/追赃/挪借入库 · 省内可支 · 应付/实付 · 新增欠账 · 偿还。
- **钱类 CASH/CLAIM stock 只经 `delta`/`transfer_to` 变动,禁 `set`、禁 `scale` modifier。**

## 0.1 守恒不变式(spike G1–G7 实测残差 0;含 r11 修正)
**主断言(现金双边平)**:
```
Δ(Σ CASH) == CASH_in − CASH_out
  CASH_in  = 实征 + 火耗实收 + 清欠 + 拨付gross        (民间补缴 / 京饷注入)
  CASH_out = 起运到京 + Σ实付(军饷/官俸/宗禄/赈济) + Σ偿旧欠 + Σ(补饷/行政 action 现金支付)
  注:挪借火耗 / 追赃(C↔省库)是 CASH 内部转移,ΣCASH 不变,不计边界流。
      拨付以 gross 入(net→省库、中饱→C_中饱,均留 ΣCASH 内)。
```
**断言用「独立 oracle」(r13/opus 关键:期望值必须从 tick 输入参数独立重算,不能用落账时同源记的流水——否则校验项与被校验项穿一条裤子=tautology,一致 relabel 照样过)**:
**C 灰账 per-account · 独立 oracle**:每个 C_ 子账户期望从 params 重算 —`C_中饱应得≡拨付gross×中饱率`、`C_漂没应得≡起运池×漂没率`、`C_地方截留应得≡火耗应派×(1−逋赋率)−挪借出`、`C_eff损耗应得≡Σ(transfer actual×(1−eff))`;断言 `实际落账==应得`。
**债务 per-account · 独立 oracle**:从 Due(param)+claim0+action入参 重跑 waterfall/偿还,固定科目映射(军饷→军饷欠…),断言每科目 `claim==重算值`。
> **自变异实证(spike)**:中饱→省库、火耗实收→省库、军饷新债→官俸欠 三种**一致 relabel**(落账+记账同步搬),现金/总量守恒全 PASS,但独立 oracle 的 per-account C / 债务 **当场 FAIL**。旧的「同源流水」式(v13)放过这些,独立 oracle 堵住。
**每笔 `transfer_to` 三方平**:`source减 = target增(actual×eff) + C_eff损耗增(actual×(1−eff))`(`actual=min(amount,source)`;BOUNDARY 账户 民间/京/受款方 **无余额 clamp**)。
> 旧式「三本账总额=拨付−起运」及 v11 漏 拨付net 的式子**均作废**:r11/opus 变异测试实锤 —— 旧式是 tautology(火耗应派≡火耗实收+火耗未收,永真),v11 式漏 拨付net(设 20 跑出残差+20)。现式 spike G1–G7 全 PASS。

## 1. 单位制 + cost_type(同 v10)
年额÷12·月额万两/月·stock万两·税额两/亩·年(非0-1)·真率0-1。action「银」amount=每tick成本,cost_type=one_time/recurring。

## 2. 月度结算顺序(省级 ⓪–⑪ + 全局 ⑫,同 v10)
⓪ Flow清零→modifier衰减→**收集本tick action→先算 k(`k=min(1,Stock_start/Σ_{cost>0}银Cost)`,Stock_start=上月结转)→再按 k 执行 action**(transfer 此时执行)。**0-cost action 的 amount 不受 k 缩**(spec §6);clamp 到 0 的成本仍占 ΣCost 分母(=预算承诺语义,守恒不破,非 bug)。`省库库银_post=Stock_start−Σ(k·银Cost)`。
①折月 ②③应征 ④火耗应派→民负担(未实收不积欠)⑤⑥负担率/逋赋率(灾→下限)⑦实征→可支、火耗实收→C、民欠→B ⑧`起运池=min(实征,定额)`/`省内池=max(0,实征−起运池)` ⑨漂没→C ⑩拨付gross扣/net→可支/中饱→C ⑪付款+偿还+结转(省库库银_new=S,覆盖写)⑫(全局)国库入账。

## 3. 付款 waterfall / 4–5. schema / 6. 执行归一化(同 v10)
1军饷>2官俸>3宗禄>4赈济(Due_4=action amount,NewDebt_4≡0);民欠=清欠/蠲免无官偿还;火耗实收进C需「挪借火耗」action 转出。
k=action力度系数(ΣCost仅含action银,Due不入;Cost>0 action其 delta/scale/transfer_to.amount 全×k;0-cost不缩)。modifier `V_final=clamp(V_base×∏max(0,1+scale)+Σdelta)`,V_base静态不复利,钱类Stock禁set/scale。transfer_to source/target 类型白名单(CASH/CLAIM/BOUNDARY 或指定 Flow)。
**现金 action 二选一**(防双扣):支付类(补饷/赈济)= 银 Cost 即该笔支付,不再另记 Due;行政成本类 = Cost 扣省库,另带 effect。(spike G2 已验补饷 k=0.333 无双扣。)

## 6.6 golden-tick(spike 实测 · G1–G9 全 PASS,三断言:现金守恒/债务对账/C per-account 对账)
见 [spike_settle_tick.py](../spike_settle_tick.py),已执行,残差均 0:
- **G1** 基线 · **G2** 补饷 k=0.333(死亡螺旋+无双扣)· **G3** 清丈(官民田3050→3350,当 tick 扣成本2)· **G4** 挪借火耗(C 内部转移)· **G5** 漂没.1+中饱.1+拨付30(漂没→C_漂没/中饱→C_中饱/net→省库)· **G6** 超额补饷 clamp(欠5补30只还5)· **G7** 清欠(民间补缴现金入)。
- **G8** 挪借 eff=0.8 → 激活 C_eff损耗(2→损耗账户),per-account 对账平。
- **G9** 三 tick 链(穷省+recurring 营建):死亡螺旋实显——军饷欠 30→97→133、火耗在 C_地方截留 累积 8.4→16.8→25.2(官绅肥/官衙穷),每 tick 三断言均 PASS。
- **自变异实证**:把 中饱 relabel 进省库 → 现金守恒仍 PASS、per-account C **当场 FAIL**(堵住 v12 的 relabel 隐形洞)。
- 仍待补:multi-action 多 costed action 共享 k 的 golden、recurring cost 的语义边界(当前穷省 k=0 即停)。

## 6.7 可执行 spike(golden 种子)
`spike_settle_tick.py` = 纯 dict 复式记账原型(非引擎、throwaway),实现 ⓪–⑪ + §0.1 守恒断言,跑 G1/G2 打印逐步流水 + 守恒 PASS/FAIL。**它就是将来真引擎 golden test 的种子**:port 进 `ming_sim` 时把 G1–Gn 转成 pytest 断言即可。

## 7–8. 状态/派生/螺旋/铁律/实现规约(同 v10)
死亡螺旋(AI耦合+灾→逋赋下限+按册派刚性,G2 已显现)、5 铁律见 ADR 0007;逋赋率 clamp(0,1)、民欠蠲免 max(0,·);实现规约五条 + §6.6/6.7。

## 待精验
各 f() 具体形 · G3–G5 golden 数字 · 数值边界 · 征收能力/士绅协作/粮价/运输/宗室口/驿卒 seed · 负担标准值校准。

## Sources
[1][西安府田亩](https://zhuanlan.zhihu.com/p/1917691584633369550) [2][三边京运](https://zhuanlan.zhihu.com/p/30177486035) [3][宗禄](https://zhuanlan.zhihu.com/p/508242610) [5][官俸薄](https://news.bjd.com.cn/2022/08/15/10134150.shtml) [6][裁驿](https://zhuanlan.zhihu.com/p/51748875) [7][三饷](https://zh.wikipedia.org/zh-hans/%E4%B8%89%E9%A4%89)
