# 省级财政基座 · 草表 v9(r8 四声返工 · 加 golden-tick 样例)

> **范围:仅锁单省 spine(样本=陕西);跨省 hub 拨付分配 deferred。`拨付net/gross` 为 tick 外部入参注入(测试默认 0)。**
> v9 收 r8 多声撞车:Cost↔Due 互斥 · transfer_to.amount 随 k 缩 · V_base 静态/Stock 禁挂 scale · transfer 执行时机+Stock_start 快照 · loss_sink/C 归 Stock · 火耗实收去向声明 · cost_type · 赈济不累欠 · k 取期初 · golden-tick 样例(§6.6)。
> 评审 r1–r8(grok 已下课;panel=codex/agy/opus/sonnet)。决策见 [ADR 0007](adr/0007-province-fiscal-substrate-ai-judged.md)。⚠️=待精验。

## 0. 三本账 + 国库边界 + Stock/Flow + 不变式
- **A 月流**(每 tick 清零)+ **A-stock 省库库银**(跨期)· **B**(负债:军饷/官俸/宗禄欠;债权:民欠旧赋)· **C 灰账(全部 Stock,跨期累积)**:地方截留(火耗实收)· 中饱赃银 · 漂没损失 · efficiency 损耗。
- **国库=全局外部 hub**;省级只产「起运到京/受拨付net」;`拨付net/gross`=外部入参注入;⑫ 全局步骤。
- **Stock(跨期持久,不清零)**:省库库银 · B 全 · C 全 · 民口/官民田/隐田 · 各软轴 · stock 政策态。**禁止对「钱类 Stock」(省库库银/B/C)挂 `scale` modifier**(防放大印钱);钱类 Stock 只能经 `delta` 或 `transfer_to` 变动(r8/agy)。
- **Flow(每 tick 开头清零)**:正赋/三饷/火耗应派 · 实征 · 火耗实收(本 tick 量,落账去 C)· 起运池 · 省内池 · 起运到京 · 拨付net · 清欠入库 · 追赃入库 · 省内可支 · 应付/实付 · 新增欠账 · 旧债偿还。
- **不变式**:`实征=起运池+省内池` · `应付=实付+欠账新增B` · `gross=net+中饱C` · `起运池=起运到京+漂没C` · `应征(正税=正赋+三饷)=实征+民欠新增B`(火耗不在正税应征内,不积欠)· **守恒**:Stock↔Flow/Stock 转移**只走 `transfer_to`**,且 `source减=target增+loss_sink增`;**例外**:⑪ 末「省内可支余额→省库库银结转」是同账户(A-stock)结转,非跨账户转移,直接赋值(`结转=S`)。

## 1. 单位制 + action 成本类型
年额÷12入月·月额万两/月·stock万两·税额(亩额 两/亩·年,非0-1)·真率0-1。
action「银」`amount`=每 tick 成本,带 `cost_type`:`one_time`(仅 resolve 当 tick 计入 ΣCost)/ `recurring`(存续期每 tick 计入 ΣCost)。

## 2. 月度结算顺序(省级 ⓪–⑪ + 全局 ⑫)
⓪ **tick 开头(钉死序)**:Flow 全清零 → 存续 modifier `duration−1`(减0移出;`-1`=永久)→ resolve 本 tick 新 action(modifier 初值=`duration_months`,本 tick 即第1个 tick;**`transfer_to` effect 在此立即执行**:source/target stock 当场变动,清欠/追赃入库 Flow 当场写入)→ **全部 action resolve 后批量算 k**(§6.2),`省库库银_post=Stock_start−Σ(k·银Cost)`。
① 年额折月 · ②③ 正赋/三饷应征 · ④ 火耗应派→民负担(不积欠)· ⑤⑥ 负担率/逋赋率(灾→下限)· ⑦ 实征=应征×(1−逋赋率)→A、火耗实收=火耗应派×(1−逋赋率)→**C.地方截留**、民欠→B · ⑧ `起运池=min(实征,定额)`/`省内池=max(0,实征−起运池)` · ⑨ 漂没→C · ⑩ 拨付 gross(外部)扣、net→A、中饱→C · ⑪ 付款+偿还+结转(§6.5)· ⑫(全局)国库入账。

## 3. 付款 waterfall
省内可支按优先级付,短缺即欠:**1 驻军饷→军饷欠 · 2 官俸/行政→官俸欠 · 3 宗禄→宗禄欠 · 4 赈济**(discretionary,`Due_4`=该 action amount,引擎不自动生成,**不累欠:NewDebt_4≡0**)。民欠旧赋=债权,只能 **清欠**(`transfer_to` B.民欠→清欠入库)或 **蠲免**(B.民欠 delta `max(0,·)`+民心);**无官偿还民欠**。
**火耗实收进 C.地方截留,默认不进省内可支**(史实:官绅肥/官衙穷);要用于俸饷须经 action「挪借火耗」`transfer_to`(C.地方截留→省库库银)。

## 4–5. typed schema / reason_code(同前)
`effects[]{field_path,op:delta|set|scale|transfer_to,amount,unit,duration_months}`。reason_code 枚举同 v6。

## 6. 执行归一化(算法层)
**6.1 ⓪ 时序**:见 §2 ⓪。
**6.2 k + Cost↔Due 互斥(r8 核心)**:`ΣCost` **仅含 action 提交的「银」amount**(按 cost_type);**引擎自动的 Due(军饷/官俸/宗禄/赈济)不属于 Cost、不参与 k**,只在 §6.5 处理;action 的银只在 ⓪ 扣一次,绝不在 waterfall 再扣。`Stock_start`=tick 开头(Flow 清零后、任何 action 执行前)的省库库银 = 上月结转值。`k=(Σ_{Cost>0}≤Stock_start)?1:Stock_start/Σ_{Cost>0}`;**仅 Cost>0 的 action**,其 `delta.amount`/`scale.amount`/`transfer_to.amount` 全 ×k;0-cost action 不受 k。
**6.3 modifier 公式(r8 精修)**:`V_final=clamp(V_base×∏max(0,1+scale_i)+Σdelta_j,min,max)`。**`V_base`=该 field 静态基准,永不被 `V_final` 覆盖;每 tick 用当前全部存续 modifier 从 base 重算;scale 不复利;V_final 仅供本 tick 下游读取**(删除「算出即应用、下游引用 V_final」的旧歧义措辞——下游引用的是本 tick 重算的 V_final,但 base 不变)。`set` 先覆盖 V_base;同 field 多 set 按提交顺序后者覆盖。离散 set:仅当该 action `Cost>0 且 k<1` 时不触发,0-cost/足额照常。
**6.4 transfer_to(三方守恒)**:`{source,target,amount,efficiency(默认1.0,∈[0,1]),loss_sink(efficiency<1 必填)}`:`actual=min(amount,source.value)`;`source−=actual`;`target+=actual×efficiency`;`loss_sink+=actual×(1−efficiency)`。校验 `amount≥0`、`efficiency∈[0,1]`。
**6.5 付款/偿还纯代数**:`省内可支 = 省库库银_post + 省内池 + 拨付net + 清欠入库 + 追赃入库`(唯一定义)。`Pool=省内可支`;优先级1→4 `Paid_i=min(Pool,Due_i)`,`Pool−=Paid_i`,`NewDebt_i=Due_i−Paid_i`(i∈{1,2,3};i=4 恒0)。余 `S=Pool` 顺次偿负债类(**统一序:军饷欠>官俸欠>宗禄欠**):`B_tmp=B_i,old+NewDebt_i`(`B_i,old`=tick 开头值)、`Repaid_i=min(S,B_tmp)`、`B_i,new=B_tmp−Repaid_i`、`S−=Repaid_i`。`省库库银结转=S`。

## 6.6 golden-tick 测试样例(契约/单元测试,引擎必过)
1. **守恒**:每 tick 末断言三本账总额变化 = 外部注入(拨付)− 起运到京 + 0;C 仅增不减(除追赃/挪借 action)。
2. **transfer 守恒**:`source减==target增+loss_sink增`;source 不足时 `actual=source`,三方仍平。
3. **k 缩**:Cost>0 且 Stock_start<ΣCost → delta/scale/transfer_to.amount 全 ×k;0-cost action 不变;离散 set 不触发。
4. **modifier**:scale duration=3 跑 4 tick,第4tick 自动回 base(不复利);钱类 Stock 挂 scale 应被引擎拒绝。
5. **Cost/Due 不双扣**:补饷 action(银 Cost)在 ⓪ 扣一次,waterfall 不再扣;军饷 Due 不进 ΣCost。
6. **偿还**:同 tick 新欠可被同 tick 盈余偿;赈济短缺 NewDebt_4==0。
7. **火耗**:火耗实收进 C.地方截留,省内可支不含它;挪借火耗 action 后才进省库。
8. **Stock_start**:= 上月结转,不受本 tick 拨付影响(k 以期初为准)。

## 7. 状态/派生/死亡螺旋/铁律(同前)
死亡螺旋(AI耦合+灾→逋赋下限+按册派刚性)、5 铁律见 ADR 0007。clamp:逋赋率 clamp(0,1)、民欠蠲免 max(0,·)。

## 8. 实现规约附录(同 v8 五条)+ §6.6 golden tests

## 待精验
各 f() 具体形(占位线性/分段)· 数值边界(损耗率/efficiency/同比缩/蠲免/赈济)· 征收能力/士绅协作/粮价/运输/宗室口/驿卒 seed · 负担标准值校准。

## Sources
[1][西安府田亩](https://zhuanlan.zhihu.com/p/1917691584633369550) [2][三边京运](https://zhuanlan.zhihu.com/p/30177486035) [3][宗禄](https://zhuanlan.zhihu.com/p/508242610) [5][官俸薄](https://news.bjd.com.cn/2022/08/15/10134150.shtml) [6][裁驿](https://zhuanlan.zhihu.com/p/51748875) [7][三饷](https://zh.wikipedia.org/zh-hans/%E4%B8%89%E9%A4%89)
