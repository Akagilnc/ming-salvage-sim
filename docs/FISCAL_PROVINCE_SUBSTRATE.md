# 省级财政基座 · 草表 v10(r9 返工 · 守恒含外部边界 · 带数字 golden-tick)

> **范围:仅锁单省 spine(陕西);跨省 hub 拨付 deferred;`拨付net/gross` 为 tick 外部入参(测试默认 0)。**
> v10 收 r9:① **守恒模型补外部边界账户**(民间/受款方/损耗 sink),征收/支付/损耗全是边界 transfer,守恒重定义 ② golden-tick 给**具体数字** ③ k = action 力度系数、缩该 action 全部 effect ④ 挪借/追赃 transfer target 走 **Flow**(不直写省库库银,杜绝双计)⑤ transfer source/target 类型白名单 ⑥ 钱类 Stock 禁 set/scale。
> 评审 r1–r9(panel=codex/agy/opus/sonnet)。决策见 [ADR 0007](adr/0007-province-fiscal-substrate-ai-judged.md)。⚠️=待精验。

## 0. 账户模型(内部三本账 + 外部边界)
**内部账户(引擎管理)**:
- **A 月流**(每 tick 清零)+ **A-stock 省库库银**(跨期)。
- **B**(负债:军饷/官俸/宗禄欠;债权:民欠旧赋)。
- **C 灰账(全 Stock,跨期累积)**:地方截留(火耗实收)/中饱赃银/漂没损失/efficiency 损耗。
**外部边界账户(非引擎 stock,只记边界流)**:
- **民间**(征收 source:正赋/三饷/火耗 从此流出)· **受款方**(支付 sink:起运到京、军饷/官俸/宗禄/赈济 实付 流向此)· **损耗 sink**(=C 内的漂没/中饱/efficiency,已在内部 C)。

**守恒(重定义,r9/opus)**:不再用「三本账总额=拨付−起运」。改为两条可测断言:
1. **每笔 `transfer_to` 三方平**:`source减 = target增 + loss_sink增`。
2. **边界流平**:每 tick `Σ(民间流出=正赋+三饷+火耗应派) = A/B/C 内部增量 + 受款方流入 + 损耗`;即**内部账户净增 = 民间流入 − 受款方流出 − 期末未实现(民欠等)**。征收/支付/偿还都视作与边界账户的转移,显式标注方向。

**Stock(不清零)**:省库库银·B·C·民口/官民田/隐田·软轴·stock政策态。**钱类 Stock(省库库银/B/C)只能经 `delta` 或 `transfer_to` 变动,禁 `set`、禁 `scale` modifier**(r9)。
**Flow(每 tick 清零)**:正赋/三饷/火耗应派·实征·火耗实收·起运池·省内池·起运到京·拨付net·**清欠入库/追赃入库/挪借入库**·省内可支·应付/实付·新增欠账·旧债偿还。

## 1. 单位制 + cost_type(同 v9)
年额÷12·月额万两/月·stock万两·税额两/亩·年(非0-1)·真率0-1。action「银」amount=每tick成本,cost_type=one_time/recurring。

## 2. 月度结算顺序(同 v9,挪借/追赃 target 改 Flow)
⓪ Flow清零→modifier `duration−1`→resolve新action(`transfer_to` 立即执行;**清欠/追赃/挪借的 target 是 Flow 入库,不是省库库银 stock**)→批量算k→`省库库银_post=Stock_start−Σ(k·银Cost)`(`Stock_start`=⓪执行前=上月结转)。
①折月 ②③应征 ④火耗应派→民负担 ⑤⑥负担率/逋赋率 ⑦实征→A、火耗实收→C、民欠→B ⑧起运/省内分池 ⑨漂没→C ⑩拨付gross扣/net→A/中饱→C ⑪付款+偿还+结转 ⑫(全局)国库入账。

## 3. 付款 waterfall(同 v9)
1军饷→军饷欠·2官俸→官俸欠·3宗禄→宗禄欠·4赈济(Due_4=action amount,NewDebt_4≡0)。民欠=债权,清欠/蠲免;无官偿还民欠。**火耗实收进C,默认不进省内可支;挪借火耗 action:`transfer_to(C.地方截留→挪借入库 Flow)`,挪借入库计入 §6.5 省内可支。**

## 4–5. typed schema / reason_code(同 v9)
`transfer_to{source,target,amount,efficiency(默认1,∈[0,1]),loss_sink}`;**source/target 类型白名单:Stock(省库库银/B/C/民间/受款方)或指定 Flow(清欠入库/追赃入库/挪借入库)**(r9/sonnet)。

## 6. 执行归一化(同 v9 + r9 精修)
**6.2 k = action 力度系数**:`ΣCost`仅含 action 银 amount;Due 不入。`k=(Σ_{Cost>0}≤Stock_start)?1:Stock_start/Σ_{Cost>0}`。**k 缩「该 Cost>0 action 自身的全部 effect」(delta/scale/transfer_to.amount)—— 即该 action 以 k 力度执行**;0-cost action 与引擎 Due 不受 k。(澄清 r9:非银字段 effect 也随 k,因为它是「这个 action 半价就半力度」,语义一致。)
**6.3 modifier**:`V_final=clamp(V_base×∏max(0,1+scale_i)+Σdelta_j,min,max)`;V_base 静态、每tick从base重算、scale不复利;`set` 改 V_base(持久写入,非 V_final)、**钱类 Stock 禁 set**;离散 set:该 action Cost>0 且 k<1 时不触发。
**6.4 transfer_to**:`actual=min(amount,source.value)`;`source−=actual`;`target+=actual×efficiency`;`loss_sink+=actual×(1−efficiency)`;校验 amount≥0、efficiency∈[0,1]、source/target 在白名单。
**6.5 付款/偿还**:`省内可支=省库库银_post+省内池+拨付net+清欠入库+追赃入库+挪借入库`。`Pool=省内可支`;1→4 `Paid_i=min(Pool,Due_i)`,`Pool−=Paid_i`,`NewDebt_i=Due_i−Paid_i`(i∈{1,2,3};i=4恒0)。余`S=Pool` 偿负债(军饷欠>官俸欠>宗禄欠):`B_i,old`=⓪resolve后值,`B_tmp=B_i,old+NewDebt_i`,`Repaid_i=min(S,B_tmp)`,`B_i,new=B_tmp−Repaid_i`,`S−=Repaid_i`。`省库库银结转=S`(同 A-stock 内沉淀,非跨账户 transfer)。

## 6.6 golden-tick(带具体数字 · 契约测试 · 引擎必复现)
**样例 G1(单省单 tick,陕西简化值,万两)**:
输入:`Stock_start=50`;`拨付net=0`;官民田折月正赋应征=60、三饷应征=10;`火耗率=0.2`、`逋赋率=0.3`;起运定额=40;Due=军饷45/官俸8/宗禄4/赈济0;军饷欠_old=20;无 action。
- ④ 火耗应派=60×0.2=12(进民负担)。⑤ 民负担含 82。
- ⑦ 实征=(60+10)×(1−0.3)=49 →A;火耗实收=12×0.7=8.4→C.地方截留;民欠=70−49=21→B.民欠。
- ⑧ 起运池=min(49,40)=40;省内池=49−40=9。
- ⑨ 漂没(率0)→起运到京=40,C.漂没损失+0。
- ⑪ 省内可支=省库库银_post(50,无 action)+省内池9+拨付net0+0+0+0=59。付款:军饷 Paid=min(59,45)=45,Pool=14;官俸 Paid=min(14,8)=8,Pool=6;宗禄 Paid=min(6,4)=4,Pool=2;赈济0。NewDebt 全0。余 S=2 偿军饷欠:Repaid=min(2,20+0)=2,军饷欠_new=18,S=0。**省库库银结转=0**。
- **断言**:省库库银_new=0;军饷欠=18;C.地方截留+8.4;B.民欠+21;起运到京=40;每笔 transfer 三方平;边界:民间流出(60+10+12=82)= 实征49+火耗实收8.4(入内部)+ 民欠21(未实现,记B)+ 火耗未收3.6(蒸发/不积欠,记边界损耗)→ 82=49+8.4+21+3.6 ✓。
**样例 G2**:加一个 action「补饷」(银 cost 30、one_time、`transfer_to(省库→受款方军饷)`),`Stock_start=10` → k=10/30=0.33,实扣 3.3... 钉死 k 缩与 Due 不双扣(详见实现待补完整数字)。⚠️ G2 具体数字待精填。

## 7–8. 状态/派生/螺旋/铁律/实现规约(同 v9)
死亡螺旋、5铁律见 ADR 0007;逋赋率 clamp(0,1)、民欠蠲免 max(0,·);实现规约五条 + §6.6。

## 待精验
各 f() 具体形 · G2 等更多 golden 数字 · 数值边界 · 征收能力/士绅协作/粮价/运输/宗室口/驿卒 seed · 负担标准值校准。

## Sources
[1][西安府田亩](https://zhuanlan.zhihu.com/p/1917691584633369550) [2][三边京运](https://zhuanlan.zhihu.com/p/30177486035) [3][宗禄](https://zhuanlan.zhihu.com/p/508242610) [5][官俸薄](https://news.bjd.com.cn/2022/08/15/10134150.shtml) [6][裁驿](https://zhuanlan.zhihu.com/p/51748875) [7][三饷](https://zh.wikipedia.org/zh-hans/%E4%B8%89%E9%A4%89)
