# 省级财政基座 · 草表 v4(codex r3 返工 · 锁 spine)

> v4 修 r3 的 4 硬点 + 隐藏 spine:① 三本账 ledger 分层 ② 火耗应派/实收拆 ③ 付款 waterfall 表 ④ 中央拨付 gross/net ⑤ typed action/clamp schema。
> 评审:[r1](fiscal-substrate-review-r1-codex.md)·[r2](fiscal-substrate-review-r2-codex.md)·[r3](fiscal-substrate-review-r3-codex.md)。决策见 [ADR 0007](adr/0007-province-fiscal-substrate-ai-judged.md)。⚠️=待精验。样本=陕西。

## 0. 三本账 ledger(r3 隐藏 spine · 引擎绕不开 · 每笔钱落且只落一本)
- **A 官方月流(flow,万两/月)**:正赋实征 · 三饷实征 · 起运到京 · 省内各支出 · 中央拨付(gross)· 国库入账。
- **B 欠账 stock(累积,万两)**:军饷欠 · 宗禄欠 · 官俸欠 · 民欠旧赋。
- **C 灰账/损耗(stock/sink,万两)**:地方截留(火耗实收)· 漂没损失 · 中饱赃银。

**账本不变式(每 tick 必平,作为引擎断言/契约测试)**
- 征收:`应征 = 实征(A) + 民欠新增(B)`
- 付款:`应付 = 实付(A) + 欠账新增(B)`
- 解运:`起运池 = 起运到京(A) + 漂没损失(C)`
- 拨付:`拨付gross(A出) = 到手net(A入) + 中饱赃银(C)`
- 火耗:`火耗应派 = 火耗实收(C) + 火耗欠(随逋赋,不单列,计入民侧未收)`

## 1. 单位制(同 v3 + action「银」标生命周期)
年额量(两/亩·年、万石/年)入月账前 ÷12 / 经`粮价`折银 · 月额量 万两/月 · stock 万两 · 税额(`正赋亩额`/`三饷亩额`,两/亩·年,**非0-1**)· 真率(火耗/逋赋/漂没/中饱率,0-1)。
action 里「银」必标 `duration_months`:0=一次性 · 1=持续/月 · N=临时N月。

## 2. 月度结算顺序(唯一口径 · 火耗应派/实收拆 · gross/net 修)
| # | 步骤 | 公式 → 落哪本账 |
|---|---|---|
| ① | 年额折月 | 两/亩·年、万石/年 在此 ÷12 / 折银 |
| ② | 正赋应征 | 官民田×`正赋亩额`÷12 (万两/月) |
| ③ | 三饷应征 | 官民田×`三饷亩额`÷12 |
| ④ | **火耗应派** | 正赋应征×`火耗率` → **进民负担(⑤),不进国库** |
| ⑤ | 民人均负担/负担率 | (正赋+三饷应征+火耗应派)÷民口÷负担标准值 |
| ⑥ | 逋赋率 | f(灾,负担率,民变,征收能力);灾→下限 |
| ⑦ | **实征 / 火耗实收 / 民欠** | 实征=(正赋+三饷)×(1−逋赋率) **→A**;火耗实收=火耗应派×(1−逋赋率) **→C.地方截留**;民欠=应征−实征 **→B.民欠旧赋** |
| ⑧ | **存留/起运分配** | 实征 → 见 §3 付款 waterfall(先留起运定额,余省内按优先级;短缺累 B) |
| ⑨ | **漂没(解运口)** | 起运到京=起运池×(1−`漂没率`) **→A**;差额 **→C.漂没损失**。只吃起运池 |
| ⑩ | **中央拨付(gross/net)** | 国库扣 **gross**(A出);地方收 **net=gross×(1−`中饱率`)**(A入);差额 **→C.中饱赃银** |
| ⑪ | 欠账偿还 | 有拨饷旨意/余款 → 按 §3 偿还优先级:先抵本月缺口,余抵 B 本金 |
| ⑫ | 国库入账 | Σ起运到京 − Σ拨付gross − 中央定额支出 |

## 3. 付款 waterfall 表(r3 fix 2)
实征 → 先扣 `起运定额`(中央/边饷 earmark)入起运池;**余额=省内池**,按下表优先级付,短缺即欠:

| 优先级 | 预算头 | due 公式 | 资金池 | 欠→stock | 偿还优先级 |
|---|---|---|---|---|---|
| 0 | 起运定额(中央/边饷) | 国家级定额 | 起运池 | (中央侧另计) | — |
| 1 | 本省驻军饷 | Σ驻军 maintenance | 省内池 | 军饷欠 | 1(欠饷→兵变) |
| 2 | 官俸/行政运转 | 官俸法定+行政缺口部分 | 省内池 | 官俸欠 | 3 |
| 3 | 宗禄 | 宗禄账面×实发率 | 省内池 | 宗禄欠 | 4 |
| 4 | 赈济/其他 | 旨意额 | 省内池 | (不累欠,直接缩) | 2(民生优先补) |

## 4. typed action / clamp schema(r3 fix 4)
```
action_id     : enum
inputs        : { 目标省, 力度: low|mid|high, 资源: {银:{amount, duration_months}, 人:吏id|数, 权:bool, 政治槽:国策|密令} }
effects[]     : { field_path, op: delta|set|scale, amount, unit, duration_months }   ← 一个 action 多条;白名单内
clamp_return  : { per_effect: [{field_path, requested, applied}], reason_codes[](primary 在前), binding_constraints[], blocking_vars[] }
```
生命周期由 `duration_months` 表达:押解(临时N月)/养廉银(持续/月)/赈灾(一次性)三类不再混。

| action_id | effects 白名单(field_path 方向) | reason_codes |
|---|---|---|
| `qing_zhang` | 隐田↓·官民田↑·士绅阻力↑·民心↓(临)·银-(一次)·逋赋↑(临) | GENTRY_RESISTANCE/LOW_ADMIN_CAPACITY/INSUFFICIENT_FUNDS |
| `tai_guanfeng` | 官俸法定↑(持续)·行政缺口↓·火耗率↓·官俸欠↓ | INSUFFICIENT_FUNDS/NO_BUDGET_HEADROOM |
| `zhuanyuan_yajie` | 漂没率↓(临)·银-(一次/持续) | TRANSPORT_BOTTLENECK |
| `xue_fan` | 宗禄↓(持续)·宗室满意度↓ | CLAN_RESISTANCE |
| `jia_sanxiang` | 三饷亩额±·(派生:民负担↑→逼反) | AI_DILEMMA |
| (其余 整肃吏治/清账追赃/裁驿/蠲免 同形,见 v3) | | |

## 5. reason_code 枚举(+ r3 补)
clamp_return.reason_codes[] 取自:`INSUFFICIENT_FUNDS·DISASTER_FLOOR·LOW_ADMIN_CAPACITY·GENTRY_RESISTANCE·TRANSPORT_BOTTLENECK·CLAN_RESISTANCE·MUTINY_RISK·NO_BUDGET_HEADROOM·REBOUND·APPLIED(全额落地)·AI_DILEMMA(无引擎硬约束,后果交 AI 软判)`。多约束同触发→数组,**主因在前**。

## 6. 状态 / 派生 / 死亡螺旋 / 铁律(同 v3)
一级状态(基数/人口分层/软轴/出血/三本账 stock/政策态/标准值)、二级派生(火耗率/逋赋率/漂没率/中饱率/负担率/local_balance/兵变压力/流寇压力)、死亡螺旋(AI耦合+灾→逋赋下限+按册派刚性)、5 铁律 —— 均同 [v3 §4-6](#) 与 [ADR 0007]。陕西 seed 同前(⚠️ 待精验项不变)。

## 待精验
各 f() 具体形(可占位线性/分段)· 偿还细则边界 · 征收能力/士绅协作/粮价/运输/宗室口/驿卒 seed · 负担标准值校准。

## Sources
[1][西安府田亩](https://zhuanlan.zhihu.com/p/1917691584633369550) [2][三边京运](https://zhuanlan.zhihu.com/p/30177486035) [3][宗禄](https://zhuanlan.zhihu.com/p/508242610) [5][官俸薄](https://news.bjd.com.cn/2022/08/15/10134150.shtml) [6][裁驿](https://zhuanlan.zhihu.com/p/51748875) [7][三饷](https://zh.wikipedia.org/zh-hans/%E4%B8%89%E9%A4%89)
