# 省级财政基座 · 草表 v5(r4 双声返工 · 执行契约就位 · 锁 spine 尝试)

> v5 修 r4(codex+agy 并集):① 省库库银 stock(跨期结余,agy)② 国库=全局外部 hub 边界(agy)③ 执行契约附录(codex)④ 民欠改「清欠/蠲免」、删错误的「偿还民欠」(codex+agy 真 bug)⑤ C 拆可追回/sink ⑥ 多 effect 原子性 + duration=modifier 栈。
> 评审:[r1](fiscal-substrate-review-r1-codex.md)~[r4](fiscal-substrate-review-r4-codex.md)(codex×4 / agy×1 / grok×1)。决策见 [ADR 0007](adr/0007-province-fiscal-substrate-ai-judged.md)。⚠️=待精验。样本=陕西。

## 0. 三本账 + 省库库银 + 国库边界(spine 核)
- **A 官方月流**(万两/月):正赋实征·三饷实征·起运到京·省内支出·拨付(gross)·拨付到手(net)。
- **A-stock 省库库银**(新,agy):本省跨期现银池;当月结余结转下月,**支持积谷防饥/跨期平准**。
- **B 欠账 stock**:军饷欠·宗禄欠·官俸欠·民欠旧赋。
- **C 灰账**:① **可追回**(地方截留=火耗实收·中饱赃银 → 清账追赃可 `C→A`)② **纯 sink**(漂没损失=运损,追不回)。
- **国库边界(新,agy)**:本基座是**省级**;`国库` = **全局单例外部 hub**,不由本省引擎计算。本省只产两个接口流:**起运到京(→hub)**、**受拨付(←hub)**。`国库入账=Σ各省起运−Σ拨付−中央定额支出` 是**全局步骤**(所有省 per-province 跑完后再算),**不是省级 tick 的一步**。

**账本不变式(每 tick 引擎断言)**
- `实征 = 起运池 + 省内池`
- `省内池 + 上月省库库银 + 拨付net = 省内支出 + 偿还B + 本月省库库银结转`(结转 ≥0)
- `应付 = 实付(A) + 欠账新增(B)` · `gross = net + 中饱(C)` · `起运池 = 起运到京 + 漂没(C)`
- `应征 = 实征 + 民欠新增(B)`

## 1. 单位制(同 v4)
年额量 ÷12 入月 · 月额量 万两/月 · stock 万两 · 税额(正赋/三饷亩额,两/亩·年,非0-1)· 真率(火耗/逋赋/漂没/中饱,0-1)· action「银」标 duration_months。

## 2. 月度结算顺序(省级 ①-⑪ + 全局 ⑫)
| # | 步骤 | 公式 → 落账 |
|---|---|---|
| ⓪ | **action phase** | 本 tick 的 action 在此 resolve(见 §6.1);后续步骤用 resolve 后状态 |
| ① | 年额折月 | 两/亩·年、万石/年 ÷12 / 折银 |
| ② ③ | 正赋/三饷应征 | 官民田×亩额÷12 |
| ④ | 火耗应派 | 正赋应征×火耗率 → 进民负担(⑤),不进 A |
| ⑤ | 人均负担/负担率 | (正赋+三饷+火耗应派)÷民口÷标准值 |
| ⑥ | 逋赋率 | f(灾,负担率,民变,征收能力);灾→下限 |
| ⑦ | 实征/火耗实收/民欠 | 实征=(正赋+三饷)×(1−逋赋率)**→A**;火耗实收=火耗应派×(1−逋赋率)**→C.地方截留**;民欠=应征−实征**→B.民欠旧赋** |
| ⑧ | 起运/省内分池 | `起运池=min(实征,起运定额)`;`省内池=max(0,实征−起运池)`;起运短解→国库 global 少进(省内不变负) |
| ⑨ | 漂没 | 起运到京=起运池×(1−漂没率)**→A**;差额**→C.漂没损失(sink)** |
| ⑩ | 中央拨付 gross/net | 国库扣 **gross**;地方收 **net=gross×(1−中饱率)→A**;差额**→C.中饱赃银(可追回)** |
| ⑪ | **省内付款 + 偿还 + 结转** | 省内可支=省内池+**上月省库库银**+拨付net;按 §3 付款,短缺累 B;有余按 §6.4 偿还 B;末了**结余→省库库银结转** |
| ⑫ | **(全局)国库入账** | Σ起运到京 − Σ拨付gross − 中央定额支出 |

## 3. 付款 waterfall(民欠改清欠/蠲免)
省内可支按优先级付,短缺即欠:

| 优先级 | 预算头 | 资金 | 欠→stock | 备注 |
|---|---|---|---|---|
| 1 | 驻军饷 | Σ驻军 maintenance | 军饷欠 | 欠→兵变压力 |
| 2 | 官俸/行政 | 官俸法定+行政缺口 | 官俸欠 | |
| 3 | 宗禄 | 账面×实发率 | 宗禄欠 | |
| 4 | 赈济/其他 | 旨意额(discretionary flow,非债务) | 不累欠 | 不够直接缩 |

**民欠旧赋不在付款表里**(它是官的应收,不是官的应付):只能 **清欠**(action:民欠↓→实征↑,官收回)或 **蠲免**(action:民欠↓+民心↑,官不得钱)。**无「官偿还民欠」**。
偿还 B(军饷/官俸/宗禄欠)优先级:军饷欠 > 宗禄欠 > 官俸欠(先抵本月缺口,余抵本金)。

## 4. typed action/clamp schema + 原子性
```
action_id, inputs{目标,力度,资源{银{amount,duration_months},人,权,政治槽}}
effects[]{ field_path, op:delta|set|scale, amount, unit, duration_months }   ← 白名单内
clamp_return{ per_effect[{field_path,requested,applied}], reason_codes[](主因在前), binding_constraints[], blocking_vars[] }
```
**原子性(§6.3)**:代价(银)是前置;付不起 → **整 action 按可付比例缩力度,所有 effect 同比缩**,不白嫖。

## 5. reason_code 枚举
`INSUFFICIENT_FUNDS·DISASTER_FLOOR·LOW_ADMIN_CAPACITY·GENTRY_RESISTANCE·TRANSPORT_BOTTLENECK·CLAN_RESISTANCE·MUTINY_RISK·NO_BUDGET_HEADROOM·REBOUND·APPLIED·AI_DILEMMA`;多约束→数组主因在前。

## 6. 执行契约附录(codex 要的;引擎照此,两实现者同结果)
1. **action phase**:action 在 tick 开头(月结①前)resolve;本月用 resolve 后状态。
2. **duration_months 语义 + modifier 栈**:`0`=一次性(立即,不留 modifier);`N>0`=本月起 N 个 tick 临时 modifier;`ongoing`=持续 until 撤销。**所有 op 走「只读基线 + 动态 modifier 栈」**:每 tick 计算前重累加未过期 modifiers 到只读基线;**禁** imperative「改值+定时反向操作」(防多效应交织精度漂移/崩)。
3. **多 effect 原子性**:见 §4(同比缩,不白嫖)。
4. **B 入账时点**:设 `current_due_gap` 临时池,tick 末净额入 B(消除「先入 B 再冲销」中间事件歧义)。
5. **C 可追回**:地方截留/中饱赃银 recoverable(清账追赃 `C→A`);漂没损失 sink。
6. **起运不足**:`起运池=min(实征,定额)`,省内池非负,短解记国库 global 少进。

## 7. 状态 / 派生 / 死亡螺旋 / 5 铁律(同 v3/v4,不变)
一级状态(基数/人口分层/软轴/出血/三本账 stock + 省库库银/政策态/标准值)、二级派生(火耗率/逋赋率/漂没率/中饱率/负担率/local_balance/兵变压力/流寇压力)、死亡螺旋(AI耦合+灾→逋赋下限+按册派刚性)、5 铁律见 ADR 0007。陕西 seed 同前。

## 待精验
各 f() 具体形(可占位线性/分段)· 偿还/清欠/蠲免 数值边界 · 征收能力/士绅协作/粮价/运输/宗室口/驿卒 seed · 负担标准值校准。

## Sources
[1][西安府田亩](https://zhuanlan.zhihu.com/p/1917691584633369550) [2][三边京运](https://zhuanlan.zhihu.com/p/30177486035) [3][宗禄](https://zhuanlan.zhihu.com/p/508242610) [5][官俸薄](https://news.bjd.com.cn/2022/08/15/10134150.shtml) [6][裁驿](https://zhuanlan.zhihu.com/p/51748875) [7][三饷](https://zh.wikipedia.org/zh-hans/%E4%B8%89%E9%A4%89)
