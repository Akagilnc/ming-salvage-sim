# r8 · codex(v8)

**结论：spine 可锁，可开写引擎。**

但若目标是“两个不沟通实现者写出逐 tick 完全同构结果”，我会在开写前再补一个很小的 §6.6「实现钉子 / golden tests」，不是回架构，只是防边缘解释分叉。

**1. spine 锁得住吗？**

锁得住。v8 已经把主循环钉成确定性账本：

⓪ 清 Flow → modifier 衰减 → resolve 新 action → 批量算 `k` → 扣 `省库库银_post` → ①–⑪ 线性结算 → ⑫ 全局入账。

只要 `f()` 视为外部确定性占位函数，账本 spine 已经够两个实现者写同一 tick 引擎。

还差的不是架构，是三条实现钉子：

- `transfer_to` 要校验 `amount >= 0`、`0 <= efficiency <= 1`；`efficiency < 1` 必须有 `loss_sink`。否则 `efficiency > 1` 会产生负 sink / 变相印钱。
- Cost 被 `k` 缩时，所有该 action 的连续数值效果都应缩，包括 `delta.amount`、`scale.amount`、`transfer_to.amount`，以及由该 action 提交的可支出额度；离散 `set` 仍按 v8 规则触发/不触发。
- action 的“银”只能入账一次：要么是 ⓪ 执行成本，要么进入 §6.5 的 `Due_i` / `transfer_to` 支付，不要同一笔赈济/补饷既在 ⓪ 扣 Cost、又在 waterfall 里再扣一次。

**2. r7 硬伤闭账了吗？**

闭了。

- `省内可支`：闭账。公式唯一化了，且用 `省库库银_post`，避免把 ⓪ 成本漏进可支池。
- `transfer_to/loss_sink`：主体闭账。差额不蒸发；只需加上 `efficiency` 范围 validator。
- ⓪ 时序：闭账。新 modifier 本 tick 生效、旧 modifier 先衰减，分歧消失。
- 离散 `set`：闭账。`0-cost` 不被 `k<1` 误伤，只有付费且被缩的 action 才 suppress 离散 set。
- `B_i` 偿还：逻辑闭账。实现时建议写成：`B_tmp = B_old + NewDebt; Repaid = min(S, B_tmp); B_new = B_tmp - Repaid`。不要按字面先对 `B_old` 做 `B_i -= Repaid`，否则会出现中间负数歧义。

**3. 有没有隐藏架构问题？**

没有会逼回来改架构的隐藏问题。

剩下是实现层 validator / golden tick，不是 spine 返工。尤其要测这几类样例：半额 `k` 下的 `transfer_to` 缩放、`efficiency<1` 入 sink、`0-cost set` 照常触发、同 tick 新欠可被同 tick 盈余偿还、赈济/补饷不双扣。

判词：**spine 可锁，可开写引擎。**
