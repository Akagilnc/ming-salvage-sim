# r9 · 干净上下文 subagent(v9)

> opus 4.8 / sonnet 4.6 冷读 v9。2026-06-09。本轮 opus 挖到一个概念性的洞(守恒模型缺外部账户)。

## opus 4.8 — 还锁不住(2 处直接破守恒)
- **问题1+5(概念性,最重)**:§0 守恒律说「Stock 变动只走 transfer_to 且 source减=target增」,**但 tick 主链至少 4 处单边增 Stock**(火耗实收→C / 漂没→C / 中饱→C / 民欠→B)**无 source 减**;§6.5 偿还又是 B、S **双边减无 target 增**。**根因:三本账缺「账本外对手方」**(民间财富=征收 source;京营军/官/宗室=支付/偿还 sink;漂没/中饱 sink)。→ §6.6#1「三本账总额=拨付−起运」**按字面不可能通过**,当不了契约测试。**修法**:征收/火耗/漂没/中饱/偿还全改写成 `transfer_to` + 显式外部 source/sink 账户;或把守恒断言改成「受控转移守恒(Σsource减=Σtarget增+Σloss_sink增)」。
- 问题2:挪借火耗/追赃 transfer_to target=省库库银,⓪「当场变 stock」+ ⑪「结转=S」→ **双计**。修:追赃/挪借 target 走 Flow,stock 只由 ⑪ 派生。
- 问题3:`transfer_to.amount ×k 但 ΣCost 仅含银 amount` 自相矛盾(被缩项不进分母,按什么 k 缩?)。
- 问题4:§6.3 `set` 覆盖 V_base 是钱类 Stock 的后门(§0 只禁 scale 没禁 set)。

## sonnet 4.6 — 尚未锁住(4 歧义洞)
- `省库库银_post` 是否含 ⓪ transfer_to 的 target 增量?§6.2 公式只减不加 → 分叉。
- **k 缩适用范围**:「该 action 所有 effect ×k」会把非银字段(如 scale 逋赋率)也 ×k → 荒谬。必须明确哪些 effect 受 k。
- **transfer_to 的 source/target 类型约束缺失**:没约定只能是 Stock(或白名单 Flow)→ 可写出能跑但语义错、守恒断言还通过的代码。
- **§6.6 golden-tick 没有具体数字 = 不是契约测试,是测试意图。** 两实现者都「通过」文字断言但数字不同。必须给「初值X+几个action+逐步数字+最终断言」的真样例。
- + B_i,old 取⓪执行前/后未钉死。

## 横评:多声撞车
守恒模型缺外部账户(opus,概念性)· §6.6 golden 需具体数字(opus+sonnet)· k 缩范围(非银字段)(opus+sonnet)· 省库库银_post 含不含⓪transfer target / 双计(opus+sonnet)· transfer source/target 类型约束(sonnet)· B_i,old 时机(opus+sonnet)· set 钱类Stock 后门(opus)。
**两声仍判:不锁。但仍无需推翻三本账;守恒那条是「断言/不变式的定义」要改 + 显式外部 sink,不是 spine 结构推翻。**
