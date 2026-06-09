# r10 · codex(v10)

结论：**v10 方向对，r9 的概念洞大半补上了，但按当前文字还不能判“两个不沟通实现者必写出同一 tick 引擎”。不是架构要推翻，是还有几颗契约钉没钉死。**

**1. spine 锁得住吗？**

还差一步。最大残留分叉仍在 §2/§6.2：

`resolve新action(transfer_to 立即执行) → 批量算k` 和 `k 缩该 action 全部 effect/transfer_to.amount` 仍然冲突。一个实现者会先按原 amount 执行 transfer，另一个会 staging 后按 k 执行，结果不同。

而且 `省库库银_post=Stock_start−Σ(k·银Cost)` 仍没吸收 `transfer_to(省库→受款方)` 这类省库 source/target 变动。G2 里“补饷 cost 30 + transfer_to(省库→受款方)”会立刻暴露：这是 cost 扣一次、transfer 再扣一次，还是 cost 就是这笔 transfer？当前没锁。

建议最小修法：⓪ 改成“收集 action → 算 k → 依固定顺序执行缩后 cost/effects”；并明确现金 action 二选一：

- 若是支付军饷/赈济：走 Due 或 transfer_to，不再另记同额 Cost。
- 若 Cost 是行政成本：Cost 扣省库，transfer_to 是另一笔 effect。

**2. 守恒洞补上了吗？G1 对吗？**

外部边界账户这个方向是对的，已经补到了 r9 缺的核心东西：民间不是凭空 source，受款方/京师/军官宗室不是凭空 sink，损耗也要有去处。

但当前“边界流平”的总式还不够自洽。G1 里的边界式：

`82 = 49 + 8.4 + 21 + 3.6`

这个数字是对的，但它只是在验**征收侧**：正赋+三饷+火耗应派如何分成实征、火耗实收、民欠、火耗未收。它没有把起运到京 40、实付 57、偿旧欠 2、期初省库 50 放进同一个全 tick 守恒式里。

所以 G1 的逐步演算本身基本正确：

- 实征 49 对；
- 火耗实收 8.4 对；
- 民欠 21 对；
- 起运 40 / 省内池 9 对；
- 可支 59，付 45+8+4，余 2 偿军饷旧欠，军饷欠 18，省库结转 0，都对。

但它**还不够当完整契约测试**。它可以当 G1 smoke/golden，但完整契约至少还要补：

- 现金守恒：`A_start + A_in + external_in = A_end + 起运 + Paid + Repaid + other_out`
- 债务守恒：`B_old + NewDebt = B_new + Repaid`
- C 灰账守恒：`C_new = C_old + 火耗实收 + 漂没 + 中饱 + efficiency_loss`
- action/k golden：尤其 G2 必须填完整数字，证明不双扣、不漏扣。

另外，外部账户要明说：`民间/受款方` 是**无余额 clamp 的边界流账户**，不能套 `actual=min(amount, source.value)`；否则实现者会卡在 `民间.value` 不存在。

**3. 有没有逼回来改架构的隐藏问题？**

没有看到需要推翻三本账、Flow/Stock、waterfall、AI 软判 + 引擎算术的架构问题。剩下是契约文字和 golden fixture 的锁定问题，不是 spine 方向错。

我的判词：**spine 近可锁，但 v10 literal 还不能直接开写引擎。补完 action staging/k、省库 transfer/cost 身份、边界账户无余额语义、G2 完整数字后，可判“spine 可锁，可开写引擎”。**
