# r19 · codex(holistic v19)

**v19**

不是完全挑不出。主设计、史实口径、玩法铁律、三债户全序、C 分账、unmet_relief、征收类禁 cost 这些我挑不出实质问题了；唯一还算实质的是：`负值 fail-loud` 的 spec 口径还不够全。

现在文字容易被理解成只校验 action `cost/amount` 和 rate，但 port 时还应明确所有非 rate 数量也必须 `>=0`：`正赋应征/三饷应征/正赋亩额/起运定额/拨付gross/Due.*`，以及期初 `CASH/CLAIM/官民田/隐田`。尤其 `拨付gross` 是 tick 外部入参，不能靠“上游别传坏值”。

结论：**v19 可收敛，但 port 前补这一条输入域校验。除此之外我挑不出实质问题。**

**spike**

当前 golden 和主要变异没漏：

`python3 spike_settle_tick.py` 输出片段：
```text
PASS  G18 三债户waterfall序(官俸>宗禄)
PASS  G19 三债户repay序
PASS  G9 三tick链
全部 PASS
```

我用当前源码做内存态变异，结果：
```text
中饱落省库: FAIL_CAUGHT
火耗落省库: FAIL_CAUGHT
军饷新债落官俸: FAIL_CAUGHT
起运不clamp: FAIL_CAUGHT
unmet漏算: FAIL_CAUGHT
```

但上面那个负输入口子在 spike 里可复现。校验代码只覆盖 action 与 rate：[spike_settle_tick.py](/Users/akagilnc/WorkSpace/Ming_LLM-tianmu/spike_settle_tick.py:51)，后面直接消费 `三饷应征/起运定额/拨付gross/Due`：[spike_settle_tick.py](/Users/akagilnc/WorkSpace/Ming_LLM-tianmu/spike_settle_tick.py:93)。

复现输出：
```text
negative_due: NO_RAISE ok=True 省库=40.0 民欠=21.0
negative_grant: NO_RAISE ok=True 省库=0.0 民欠=21.0
negative_sanxiang: NO_RAISE ok=True 省库=0.0 民欠=-12.0
negative_qiyun: NO_RAISE ok=True 省库=32.0 民欠=21.0
```

这不是架构级问题，是 port 前硬化项：补一层非 rate 数量/stock/due/quota 的非负校验即可。修完这条，我会判：**挑不出，可 port。**
