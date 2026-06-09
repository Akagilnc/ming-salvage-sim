# r20 · codex(holistic v20)

**v20**

不能诚实说“挑不出”。主账本设计我挑不出新问题了：现金守恒、债务/C per-account、三债户全序、赈济输出、蠲免 vs 清欠都已收敛。剩下两条是实质硬化项：

1. **“负值 fail-loud”仍未全闭合。**  
当前 spike 只校验 action `cost/amount`、`eff`、四个 rate；但 `正赋应征/三饷应征/起运定额/拨付gross/Due.*`、期初 stock、`清丈.挖隐田` 仍可为负并静默结算。port 前 spec 应明确“所有非 rate 数量、stock、quota、due、action effect 数量均 `>=0`”。

2. **土地断言只守总量，不守明细重分类。**  
`官民田+隐田` 守恒只能防“凭空造地”，不能防“清丈挖错数但总量不变”。这会把错误 `官民田/隐田` 带到后续动态税基 tick。建议 port 时加土地 per-account oracle，或至少把 `官民田/隐田` 纳入末态硬期望。

**spike**

现有 golden 全绿：

```text
$ python3 spike_settle_tick.py | tail -n 30
PASS  G18 三债户waterfall序(官俸>宗禄)
PASS  G19 三债户repay序
PASS  G20 蠲免(民欠15免8,不入现金)
PASS  G9 三tick链
全部 PASS
```

但上面两条可复现。负输入缺口：

```text
negative_due: NO_RAISE ok=True
negative_grant: NO_RAISE ok=True
negative_sanxiang: NO_RAISE ok=True
negative_qiyun: NO_RAISE ok=True
negative_stock: NO_RAISE ok=True
negative_qingzhang_hidden_land: NO_RAISE ok=True 官民田=2750 隐田=1900
```

对应代码位置：校验只在 [spike_settle_tick.py](/Users/akagilnc/WorkSpace/Ming_LLM-tianmu/spike_settle_tick.py:54) 和 [spike_settle_tick.py](/Users/akagilnc/WorkSpace/Ming_LLM-tianmu/spike_settle_tick.py:60)，但后面直接消费 `三饷应征/起运定额/拨付gross/Due`： [spike_settle_tick.py](/Users/akagilnc/WorkSpace/Ming_LLM-tianmu/spike_settle_tick.py:94)。

土地明细缺口，我在临时内存里把清丈变异成“挖两倍但总田守恒”，固定正赋、无硬期望时全断言通过：

```text
ok=True 官民田=3650 隐田=1000 总田=4650
[现金守恒] PASS
[债务对账·独立oracle] PASS
[C 分账·独立oracle] PASS
[土地守恒] PASS
```

结论：**不是为凑而凑；还剩 2 个 port 前硬化项。修完后我会判“挑不出，可 port”。**当前我不建议直接宣布完全收敛。
