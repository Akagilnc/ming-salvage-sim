# r8 · 干净上下文 subagent(v8)

> opus 4.8 / sonnet 4.6 冷读 v8。2026-06-09。又是最深的两声。

## opus 4.8 — 还不能锁(3 硬分叉 + 1 守恒矛盾)
- **A(最重)**:`省内池`(Flow)→`省库库银结转`(Stock)绕过 `transfer_to`,违反 §0「Stock↔Flow 只走 transfer_to」铁律;且 省内池 归类 Flow(每tick清零)但其余额滚进 stock = 分类与生命周期矛盾。
- **B**:`Cost 集合`(§6.2 算 k)vs `Due 集合`(§6.5 军饷/官俸/宗禄 waterfall)**是否相交未钉死** → 若刚性支付也进 ΣCost = k 缩 + waterfall 欠 双重克扣。
- **C**:§6.3「V_base×∏」(每tick从base重算)vs §8.3「算出即应用、下游引用V_final」(滚动复利)**自相矛盾** → scale 是否复利,多 tick 数值发散。
- + D/E:`transfer_to.amount`/`set 值` 是否随 k 缩(§6.2 只点了 delta+scale,漏了)· G:`拨付net` 是外部输入但 省内可支 依赖它,单省 spine 闭不了环,要声明注入接口 · H:B_i 偿还吃掉本月新欠 → LLM 看到的兵变信号失真。

## sonnet 4.6 — 尚未完全锁死(3 must-fix)
- **transfer_to 执行时机**(⓪ 立即执行 vs ⑪ 统一)+ `Stock_start` 取哪一刻 → k 分叉。
- **loss_sink Stock vs Flow**:§0 把「漂没损失」列 Flow、「C.损耗sink」列 Stock = 同一物理量双重定义打架。
- **火耗实收去向**:§0 说火耗实收→C,但 §6.5 省内可支没有火耗项;若火耗历史上补地方财政则省内可支低估 = 守恒漏洞。
- + B_i,old 钉死⓪开头值 · k 以期初还是期末可支(可能逼改架构)· scale×k 代入公式未写明 · 赈济 Due_4 取值时机。

## codex/agy(CLI)对照:均判「可锁 + 补钉子」
codex:transfer_to validator(efficiency 0-1)· k 缩含 transfer_to.amount · action 银只扣一次(不双扣)。
agy:① cost_type one_time/recurring ② **Stock 禁挂 scale modifier**(防 stock 被放大印钱)③ transfer_to.amount ×k ④ 赈济 NewDebt_4≡0 · 火耗→省内可支需 action 转(符合历史,声明即可)。

## 横评:多声撞车(高置信真项)
transfer_to.amount ×k(4声)· Cost vs Due 互斥/银只扣一次(3声)· V_base static+Stock禁挂scale(opus+agy)· transfer时机+Stock_start(opus+sonnet)· 火耗实收→省内可支(agy+sonnet)· loss_sink Stock/Flow(sonnet)· 省内池→stock结转bypass(opus)· cost_type/赈济(agy)· k期初vs期末(sonnet)· 拨付net注入声明(opus)。
**全部 4 声一致:无架构返工,皆 spec 精度(各加1-2句钉死)。**
