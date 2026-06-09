# r9 · codex(v9)

结论：**v9 不是架构没锁，是还有两处文字级分叉没钉死；我现在不能判“两个实现者必写出同一 tick 引擎”。**补完下面两颗钉子后，可以判 **spine 可锁，可开写引擎**。

**1. Spine 现在锁得住吗**
主循环大体锁住了：Stock/Flow、A/B/C、k、Due waterfall、V_base 静态、C 灰账、火耗去向这些主干已经成型。

但两人会在这里分叉：

- **⓪ 里 `transfer_to` 与 k 的先后矛盾**  
  §2 写 `transfer_to` 在 resolve 时“立即执行”，但 §6.2 又写 `transfer_to.amount` 要随 k 缩。k 是“全部 action resolve 后”才算。  
  一个实现者会先执行未缩 transfer；另一个会先 staging、算 k、再执行缩后 transfer。结果必分叉。

- **`省库库银_post=Stock_start−Σ(k·银Cost)` 会吃掉 ⓪ transfer 对省库的影响**  
  例如“挪借火耗”是 `C.地方截留 → 省库库银`。若 ⓪ 已把钱转进省库，但随后 `省库库银_post` 又直接按 `Stock_start−Cost` 定义，本 tick 可支到底含不含这笔挪借，会分叉。  
  应钉死为类似：`A_after_0 = Stock_start + ⓪转入省库 - ⓪转出省库 - Σ(k·Cost)`，§6.5 用 `A_after_0`。

还有一个小分叉：**赈济 action 的 amount 到底是 Cost 还是 Due_4**。§1/§6.2 说 action 银是 Cost，⓪扣；§3 又说赈济 `Due_4=该 action amount`，waterfall 付。必须二选一或加字段区分，否则又会双扣/漏扣。

**2. r8 问题闭账了吗**
大部分闭了：

- Cost ↔ Due：军饷/官俸/宗禄闭了；赈济 Due_4 还需区分 Cost/Due 身份。
- transfer 随 k 缩：原则闭了，但被 ⓪“立即执行” wording 抵消，需要改成 staging 后执行。
- V_base 静态 / scale 不复利 / 钱类 Stock 禁 scale：闭了。
- Stock_start 取期初：闭了。
- 火耗实收进 C、不进省内可支：闭了。
- loss_sink 归 C Stock：闭了。
- 赈济不累欠：闭了。
- cost_type：方向闭了，但 recurring 的存续期最好明说和 modifier 同一套 duration 递减规则。

新引入的矛盾主要就是：**k 后缩放 vs transfer 先执行**，以及 **赈济 action amount 的身份**。

§6.6 现在还不够当“契约测试”。它更像覆盖清单，不是 golden fixture。还需要至少一组具体初始状态、action 输入、外部拨付输入、每一步期望输出。尤其第 1 条“总额变化 = 外部注入 − 起运到京”太粗，没处理税收外部流入、实付 Due、action Cost、B 负债/债权正负号，容易把正确实现测红。

**3. 有没有逼回来改架构的隐藏问题**
没有逼回架构的大问题。省级 spine 方向是对的，跨省 hub deferred 也没问题，f() 占位不影响账本主干。

但我不会现在直接说“可开写引擎”。我的判词是：

**spine 近可锁；补钉 ⓪ 执行顺序 / 省库 post 公式 / 赈济 amount 身份后，可锁，可开写引擎。**
