# r12 · codex(v12+spike)

结论先放前面：v12 把 r11 的主洞补上了，但还不能说 §0.1 “完整闭账”，也还不能说 spine 已锁。现在是“主方向对，G1–G7 真能跑平，但 spike 还有假 PASS 通道”。

我实查了当前仓库与代码：

```text
pwd && git status --short --branch
/Users/akagilnc/WorkSpace/Ming_LLM-tianmu
## probe/tianmu-fiscal...origin/main [ahead 23]

python3 spike_settle_tick.py
G1–G7: 现金守恒 PASS / 债务对账 PASS / C 对账 PASS
```

**1. v12 草表**

拨付口径这次对了：`拨付gross` 应作为省级边界流入，`net` 入省库，`gross-net` 入 `C_中饱`，两者都留在 `ΣCASH` 内。清欠作为民间补缴现金，也应是边界流入。挪借火耗是 `C_地方截留 -> 省库`，属于 CASH 内部转移，不进边界式，这也对。

但 §0.1 还漏一个边界流：**行政成本类 action 的外支**。文档 [docs/FISCAL_PROVINCE_SUBSTRATE.md](/Users/akagilnc/WorkSpace/Ming_LLM-tianmu/docs/FISCAL_PROVINCE_SUBSTRATE.md:20) 的 `CASH_out` 只列了起运、实付、偿旧欠、补饷支付；可是 G3 清丈在代码里 `cost=2`，实际从省库流出给吏役/办差人，代码也把它加进了 `cash_out`：[spike_settle_tick.py](/Users/akagilnc/WorkSpace/Ming_LLM-tianmu/spike_settle_tick.py:44)。所以文字公式照抄会漏这 2 万两。建议改成：

```text
CASH_out = 起运到京
         + Σ净实付给受款方
         + Σ净偿旧欠
         + Σ支付类action实际付款
         + Σ行政/工程/办差等外部成本实际付款
```

追赃口径要加限定：如果追的是已经记在 `C_中饱/C_漂没/C_地方截留` 里的灰账，确实是 CASH 内部转移；如果是“新查出、此前未入 C 账”的赃银，那是边界流入，不能套内部转移。

`efficiency<1` 未来激活时也要钉死：受款方流入必须记 **net**，损耗进 `C_eff损耗`；不要把名义拨款当受款方流入，否则守恒会破。

**2. spike G1–G7**

G1–G7 的三断言确实 PASS，尤其 G5 已覆盖 `拨付gross30 / 中饱3 / net27`，G7 覆盖清欠，r11 的 gross/清欠洞基本补上了。

但有三个假 PASS 风险：

第一，现金断言用的是代码里的 `cash_in/cash_out` 累加器，不是从 spec 字段重算。G3 就暴露了这个问题：输出里 `起运40 + 实付57 + 偿旧欠0 + 补饷0 = 97`，但断言里的 `out=99`，差的 2 是清丈行政成本。代码 PASS，文字公式 FAIL。

第二，未知 action 静默 no-op。实测：

```text
M1 unknown 追赃 action
[现金守恒] ... PASS
[债务对账] PASS
[C 对账] PASS
```

也就是说现在传 `dict(type='追赃', amount=10)` 会被忽略但仍 PASS。这里必须 `else: raise AssertionError("unknown action")`，并补追赃 golden。

第三，multi-action 下 0-cost action 被 k 误缩。文档写 `0-cost不缩`，但代码 [spike_settle_tick.py](/Users/akagilnc/WorkSpace/Ming_LLM-tianmu/spike_settle_tick.py:37) 对所有 `amount` 都乘了 `k`。实测 `补饷 cost30` + `清欠 amount12`、省库只有 10 时：

```text
k=0.3333
清欠 收回民欠=4.00
```

这应当是 12，不该缩成 4。守恒仍 PASS，但语义错。

另外 G6 “余25不花”也要改字眼：代码只是“不用于偿旧军饷欠”，但那 25 留在省库，并在同 tick 继续支付当月 Due。若这正是设计，写清楚；若不是，代码要隔离 action earmark。

**3. spine 是否锁住**

还没锁住。两个实现者照 v12 + spike，大概率能写出同一个 G1/G2/G5/G7，但写不出同一个完整 tick 引擎。

差的不是大返工，是几颗钉子：

- §0.1 改成“边界交易总和”公式，并显式列 `行政成本/其他外部成本`。
- `CASH_out` 断言从 `rec` 字段重算，不只信 `cash_out` 累加器。
- unknown action 必须 fail loud。
- 修 0-cost action 不受 k 缩放。
- 补 `追赃`、`efficiency<1`、multi-action、recurring 跨 tick golden。
- 锁定清欠/追赃/挪借到底是 stock 直转还是 Flow 入库；现在文档说 `transfer_to 立即执行→批量算k`，代码实际先算 k 再执行 action，这会让实现分叉。

判词：v12 是正确方向上的一大步，r11 的主漏洞已补；但“完整守恒断言”和“spine 已锁”还差一轮。下一轮重点别再扩故事，先把 spike 变成能抓这些 mutation 的账本测试。
