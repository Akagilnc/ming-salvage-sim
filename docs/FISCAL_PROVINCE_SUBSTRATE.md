# 省级财政基座 · 草表 v8(r7 五声返工 · 补死主梁公式 · 锁 spine)

> **范围声明:本版仅锁「单省」spine(样本=陕西);跨省 hub 拨付分配/各省定额差异化 = 下一层,deferred。**
> v8 修 r7 多声硬伤:① 写出「省内可支」总公式(v7 漏抄,4 声捕到)② `transfer_to` 加 `loss_sink`+efficiency 默认 1(防凭空销钱/黑洞)③ ⓪ 时序钉死 ④ 离散 set 规则限定 ⑤ B_i 偿还取值 ⑥ scale 随 k 缩 ⑦ clamp 补丁。
> 评审 r1–r7(grok r7 后下课;下轮 panel = codex/agy/opus/sonnet)。决策见 [ADR 0007](adr/0007-province-fiscal-substrate-ai-judged.md)。⚠️=待精验。

## 0. 三本账 + 国库边界 + Stock/Flow + 不变式
- **A 月流**(每 tick 清零)+ **A-stock 省库库银**(跨期)· **B**(负债:军饷/官俸/宗禄欠;债权:民欠旧赋)· **C**(可追回:地方截留/中饱赃银;sink:漂没损失 + **efficiency 损耗**)。
- **国库=全局外部 hub**;省级只产「起运到京/受拨付net」;`拨付gross`=外部输入;⑫ 全局步骤。
- **Stock**:省库库银·B(全)·C.地方截留·C.中饱赃银·**C.损耗sink**·民口·官民田·隐田·软轴·stock政策态。
- **Flow(每 tick 清零)**:正赋/三饷/火耗应派·实征·火耗实收·起运池·省内池·起运到京·拨付net·清欠入库·追赃入库·**省内可支**·应付/实付·新增欠账·旧债偿还。
- **不变式**:`实征=起运池+省内池` · `应付=实付+欠账新增B` · `gross=net+中饱C` · `起运池=起运到京+漂没C` · `应征(正税=正赋+三饷)=实征+民欠新增B` · **全局守恒**:任何 Stock↔Flow 转移只走 `transfer_to`,且 `source减=target增+loss_sink增`(三者守恒)· `省库库银结转 = 省内可支 − 本月实付 − 偿还B ≥0`。

## 1. 单位制(同前)
年额÷12入月·月额万两/月·stock万两·税额(亩额 两/亩·年,非0-1)·真率0-1·action「银」amount=每tick成本。

## 2. 月度结算顺序(省级 ⓪–⑪ + 全局 ⑫)
⓪ **tick 开头(§6.1 钉死顺序)**:Flow 全清零 → 存续 modifier `duration−1`(减0移出) → resolve 本 tick 新 action(modifier 初值=其 `duration_months`,本 tick 即第 1 个 tick 生效) → **全部 action resolve 后批量算 k**(§6.2)、扣上月省库库银 → 得 `省库库银_post`。
① 年额折月 · ②③ 正赋/三饷应征 · ④ 火耗应派→民负担(不积欠)· ⑤⑥ 负担率/逋赋率(灾→下限)· ⑦ 实征=应征×(1−逋赋率)→A、火耗实收=火耗应派×(1−逋赋率)→C、民欠→B · ⑧ `起运池=min(实征,定额)`/`省内池=max(0,实征−起运池)` · ⑨ 漂没→C.sink · ⑩ 拨付 gross(外部)扣、net→A、中饱→C · ⑪ 付款+偿还+结转(§6.5)· ⑫(全局)国库入账。

## 3. 付款 waterfall
省内可支按优先级付,短缺即欠:**1 驻军饷→军饷欠 · 2 官俸/行政→官俸欠 · 3 宗禄→宗禄欠 · 4 赈济**(discretionary,`Due_4`=该 action 提交的 amount,引擎不自动生成;不累欠)。民欠旧赋=债权,只能 **清欠**(`transfer_to` B.民欠→清欠入库)或 **蠲免**(B.民欠 delta,`max(0,·)`,+民心,官不得钱);**无官偿还民欠**。

## 4–5. typed schema / reason_code(同 v6)
`effects[]{field_path,op:delta|set|scale|transfer_to,amount,unit,duration_months}`;`transfer_to` 见 §6.4。reason_code 枚举同 v6。

## 6. 执行归一化(算法层 · 引擎照此)
**6.1 ⓪ 时序**:见 §2 ⓪(清零→衰减→resolve→批量 k)。**两实现者按此必同。**
**6.2 成本 + k(0-cost 不缩)**:`k=(Σ_{Cost>0}Cost ≤ Stock_start)?1:Stock_start/Σ_{Cost>0}Cost`;**仅 Cost>0 的 action** 力度、其数值 effect(delta)、**及其 scale modifier 的 amount** 都 ×k;0-cost action 完全不受 k 影响。`省库库银_post=Stock_start−Σ(k·Cost_i)`。
**6.3 modifier 公式 + 防负 + 离散**:`V_final=clamp(V_base×∏max(0,1+scale_i)+Σdelta_j, min, max)`;`set` 先覆盖 V_base;同 field 多 set 按提交顺序后者覆盖前者。**离散 set 效果**:仅当**该 action 因银不足被缩(Cost>0 且 k<1)**时不触发;**0-cost 或足额 action 的离散 set 照常触发**。衰减见 §2 ⓪;`duration=-1`=永久不衰减。
**6.4 transfer_to(守恒,三方平)**:`{source,target,amount,efficiency(默认1.0),loss_sink(efficiency<1时必填)}`:`actual=min(amount,source.value)`;`source−=actual`;`target+=actual×efficiency`;`loss_sink+=actual×(1−efficiency)`。**三者守恒,差额不蒸发。** 清欠/追赃/补饷全走它。
**6.5 付款/偿还纯代数**:`省内可支 = 省库库银_post + 省内池 + 拨付net + 清欠入库 + 追赃入库`(主梁公式,v7 漏抄,此为唯一定义)。`Pool=省内可支`;优先级 1→4 `Paid_i=min(Pool,Due_i)`,`Pool−=Paid_i`,`NewDebt_i=Due_i−Paid_i`;余 `S=Pool` 顺次偿**负债类**旧债(**统一顺序:军饷欠>官俸欠>宗禄欠**,与付款同序,消除倒置歧义),`Repaid_i=min(S, B_i,old+NewDebt_i)`(同 tick 取含本月新欠的值),`B_i−=Repaid_i`,`S−=Repaid_i`;`省库库银结转=S`;`B_i,new=B_i,old+NewDebt_i−Repaid_i`。

## 7. 状态/派生/死亡螺旋/铁律(同前)
死亡螺旋(AI耦合+灾→逋赋下限+按册派刚性)、5 铁律见 ADR 0007。**clamp 补丁**:`B.民欠旧赋` 调减 `max(0,·)`;`逋赋率`等比例 `clamp(0,1)` 防实征算负。火耗未实收不积欠(确认)。

## 8. 实现规约附录(开发约定)
1. `transfer_to` 守恒(§6.4,带 loss_sink)= Stock↔Flow 唯一通路。
2. Stock/Flow 清单(§0)。
3. 级联顺序:按 ⓪–⑪;算出即应用 modifier 得 `V_final`,下游只引用 `V_final`。
4. 非银资源(人/权/政治槽):LLM 裁判/外部校验,引擎默认充足或只 clamp 特定 effect,不整组缩。
5. 裁判输出:每 tick 暴露只读 `Paid_i/Due_i`(尤其军饷、赈济)供 LLM 判兵变/民变。

## 待精验
各 f() 具体形(占位线性/分段)· 损耗率/efficiency/同比缩/蠲免/赈济 数值边界 · 征收能力/士绅协作/粮价/运输/宗室口/驿卒 seed · 负担标准值校准。

## Sources
[1][西安府田亩](https://zhuanlan.zhihu.com/p/1917691584633369550) [2][三边京运](https://zhuanlan.zhihu.com/p/30177486035) [3][宗禄](https://zhuanlan.zhihu.com/p/508242610) [5][官俸薄](https://news.bjd.com.cn/2022/08/15/10134150.shtml) [6][裁驿](https://zhuanlan.zhihu.com/p/51748875) [7][三饷](https://zh.wikipedia.org/zh-hans/%E4%B8%89%E9%A4%89)
