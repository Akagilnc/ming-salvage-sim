# r15 · codex(v15+spike)

结论：v15 方向对，但还不能说 spine 锁住，也不建议直接 port 真引擎。可收敛，差最后一轮：冻结 raw `st/p/actions` 快照、补独立 cash/action oracle、债务 oracle 不再读 `省内可支` 局部变量、断言最终持久化 snapshot。

**v15 草表**

C-oracle 下沉到原始 param 这个方向是对的，已能抓住「火耗应派局部翻倍」「中饱落省库」「起运/漂没局部 relabel」「军饷新债落官俸欠」这类普通一致 relabel。

但草表还少一条硬规则：oracle 必须读 tick 入口冻结快照，不读任何运行期绑定变量，也不读可能被执行阶段原地改写过的 action dict。否则所谓“原始 param”会退化成 `fh/bf/pm/g/zb/actions` 这些共享对象。

还少独立 cash/action oracle。现在现金守恒右侧仍是运行期累加的 `cash_in/cash_out`，所以「清欠减 claim 但不入现金」「补饷减 claim 但不出现金」仍能三断言全 PASS。这个不是小洞，是 claim↔cash spine 级漏洞。

**spike**

实际基线：`python3 spike_settle_tick.py | tail -n 40` 输出 G1-G11 全 PASS，包括 G10 追赃、G11 多 costed action。

我跑了 inline mutation harness，边界正常 case 没误报：

```text
k=0+zero-cost清欠: PASS
多costed共享k: PASS
追赃eff<1: PASS
多补饷clamp: PASS
赈济Due>0: PASS
```

能抓住的 mutation：

```text
火耗应派局部翻倍: CAUGHT_FAIL
中饱落省库: CAUGHT_FAIL
军饷新债落官俸欠: CAUGHT_FAIL
eff损耗落省库: CAUGHT_FAIL
清欠执行amount翻倍但action不改: CAUGHT_FAIL
```

仍会漏、且三断言全 PASS 的 mutation：

```text
fh绑定被污染*2: LEAK_ALL_PASS
逋赋率绑定被污染/2: LEAK_ALL_PASS
漂没率绑定+0.1: LEAK_ALL_PASS
清欠减claim但无现金入库: LEAK_ALL_PASS
补饷减claim但无现金出库: LEAK_ALL_PASS
清欠原地改写action.amount: LEAK_ALL_PASS
挪借原地改写action.amount: LEAK_ALL_PASS
追赃原地改写action.eff: LEAK_ALL_PASS
债务o_pool幻增+cash_in同源: LEAK_ALL_PASS
断言后返回态C->省库每tick搬1: LEAK_ALL_PASS
```

关键代码点：C oracle 仍复用运行期 `fh/bf/pm/g/zb`，见 [spike_settle_tick.py](/Users/akagilnc/WorkSpace/Ming_LLM-tianmu/spike_settle_tick.py:87) 和 [spike_settle_tick.py](/Users/akagilnc/WorkSpace/Ming_LLM-tianmu/spike_settle_tick.py:142)。现金断言读运行期 `cash_in/cash_out`，见 [spike_settle_tick.py](/Users/akagilnc/WorkSpace/Ming_LLM-tianmu/spike_settle_tick.py:115)。债务 oracle 的 `o_pool = 省内可支` 残留仍在 [spike_settle_tick.py](/Users/akagilnc/WorkSpace/Ming_LLM-tianmu/spike_settle_tick.py:119)。返回态在断言后才组装，见 [spike_settle_tick.py](/Users/akagilnc/WorkSpace/Ming_LLM-tianmu/spike_settle_tick.py:165)。

最终判断：v15 可作为 v16 前夜，不能作为“已锁死”版本。下一轮补上“入口快照 + 独立重演 cash/action/waterfall + final snapshot 审计”后，我会愿意说单省 spine 可 port。当前只能说 C 分账和债务科目 relabel 这两块已明显收敛。
