# r7 · codex(v7)

结论：**spine 可锁，可开写引擎**。v7 不需要再回架构层；剩下只是把两条边界写成机器不变式/黄金样例，防实现者各自脑补。

1. **两个不沟通实现者能否写出同一 tick 引擎？**
能。⓪–⑪ 顺序、Stock/Flow 生命周期、`V_final` 级联、付款 waterfall、B 的债权/负债分型、0-cost action 不参与银两同比缩，已经足够约束主干。

唯一建议补成明文公式的是：

`省内可支 = 省库库银_post_action + 省内池_final + 拨付net_final + 清欠入库_final + 追赃入库_final`

这不是架构缺口，是防实现者误把 `起运池/火耗/C灰账/民欠B` 混进可支池。

2. **v7 实现规约闭账了吗？**
大体闭账。尤其这几处已经对了：

- `transfer_to actual=min(amount,source)` 防止凭空生成 Stock 来源。
- Stock 持久、Flow 每 tick 清零，够清楚。
- 下游只读 `V_final`，避免同一变量有人读 base、有人读 modified。
- `k` 只由银两成本触发，0-cost action 不被误伤。
- `B.负债` 与 `B.民欠旧赋债权` 分开，避免出现“官府偿还民欠”这种账义错误。
- `Paid/Due` 输出给 LLM 裁判，职责边界正确。

但 `transfer_to` 的 `efficiency` 要补一句硬约束：若 `efficiency < 1`，差额必须显式进 `loss/sink`，或规定守恒转移 `efficiency=1`、损耗另走漂没/损耗算子。否则它“不印钱”，但会静默烧钱，严格闭账上还有一个小洞。

3. **还有会逼回来改架构的隐藏问题吗？**
没有。剩下都是参数、f() 形状、seed、黄金 tick、clamp 边界，不是 spine 问题。

判词：**spine 可锁，可开写引擎**。开写前把“省内可支总公式”和“transfer_to efficiency 差额去 sink”写成测试不变式即可。
