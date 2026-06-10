# r14 · codex(v14+spike)

**结论**

v14 的方向是对的：C 分账和债务科目的独立 oracle 已经能堵住大部分一致 relabel。  
但 spine 还不能说“锁住了”。现在漏的是更底层的 **cash/action oracle**：只要把现金腿和 `cash_in/cash_out` 这条同源流水一起错掉，现有三断言仍会全 PASS。

我没有改仓库文件。当前真实状态：`git status --short --branch` 输出 `## probe/tianmu-fiscal...origin/main [ahead 26]`，另有既存未跟踪 `?? mutate_probe.py`，未触碰。

**v14 草表评审**

C 侧、债务侧从 params / claim0 / action 入参重算，是正确修法。mutation 里 `C中饱->省库`、`C漂没->C_eff损耗`、`火耗实收->省库`、`eff损耗->省库` 都被抓住；低库银导致真实新债时，`军饷新债->官俸欠` 也被抓住。

但 v14 仍少写一条硬约束：现金总账右边也必须独立 oracle，不能用 settlement 过程中累加出来的 `cash_in/cash_out`。否则“清欠只减 claim 不入现金”“补饷只减欠账不出现金”“行政成本不扣现金”这种 claim↔cash 互窜仍能自洽。

还差一个持久化边界：G9 链上如果在断言之后、返回/写库之前每 tick 把 `C_地方截留` 搬 1 到 `省库库银`，每 tick 仍 PASS，下一 tick 会把错账当 old state 接着滚。所以 oracle 必须校验“最终将被持久化的 snapshot”，断言后不能再改。

**spike 代码评审**

基线确认：`python3 spike_settle_tick.py | tail -n 16` 显示 G1-G9 全部 PASS。

变异摘要，临时 inline Python 注入：

```text
C中饱->省库: CAUGHT
C漂没->C_eff损耗: CAUGHT
火耗实收->省库: CAUGHT
eff损耗->省库: CAUGHT
军饷新债->官俸欠 low-pool: CAUGHT
新债->C中饱现金 low-pool: CAUGHT

清欠减claim但不入现金: ALL_PASS
清欠入现金仅一半: ALL_PASS
补饷减claim但不出现金: ALL_PASS
行政成本不扣现金: ALL_PASS

post-assert cumulative relabel tick1/tick2/tick3: PASS
```

根因在 [spike_settle_tick.py](/Users/akagilnc/WorkSpace/Ming_LLM-tianmu/spike_settle_tick.py:112)：现金断言用的是运行期累加的 `cash_in/cash_out`，而不是从 tick 输入重算。债务 oracle 又从实际 `省内可支` 开始重跑 waterfall（[spike_settle_tick.py](/Users/akagilnc/WorkSpace/Ming_LLM-tianmu/spike_settle_tick.py:116)），所以现金腿错了以后，债务 oracle 会跟着错池子走。

边界正常样例没看到误报：

```text
multi-cost k<1: PASS
k=0 + zero-cost 清欠: PASS
挪借clamp+eff: PASS
清欠/蠲免 sequential clamp: PASS
multi-补饷 k<1 clamp: PASS
```

但 `逋赋率=1.2` 也 PASS，说明 spike 没做 v14 草表声称的 rate clamp；如果上游保证入参已 clamp，可以接受，否则这里还没锁。另一个实现缺口：草表和 C oracle 提到 `追赃`，但 `KNOWN_ACTIONS` 没有它，实际跑 `追赃` 是 `ValueError: unknown action: 追赃`。

**判定**

可以收敛的是：C 分账独立 oracle、债务科目独立 oracle 这两块。  
不能收敛的是：整个省级财政 spine。

下一轮最小补洞：加一个独立 cash/action oracle，从 `Stock_start + params + action入参 + claim0/C0` 重算现金入出、action 现金腿、`省内可支`、waterfall，并对“清欠 claim 减少 == 现金入库”“补饷 claim 减少 == 现金出库”“行政成本 == 现金出库”“最终返回/写库 snapshot == 被断言 snapshot”逐条断言。然后补 `追赃` golden 和 rate clamp golden。
