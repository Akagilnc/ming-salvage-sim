# r18 · codex(holistic v18)

**v18**

主设计、玩法铁律、史实方向我挑不出结构性问题；“省级真钱账本 + LLM 软判”可以收敛。但还有一个 spec 文字矛盾：

`补饷 cost` 不能同时要求 `≤ 当前军饷欠`，又保留 G6“欠 5 补 30，超额部分不花”。建议锁成一句：`补饷 nominal cost 可超过当前欠额，但实际支付 = min(k*cost, 当前军饷欠)，余款不转用、不落账`。否则 port 时有人会按 `cost<=欠额` 做 fail-loud，直接把 G6 语义杀掉。

史实侧没发现新硬伤：三饷不能开局全量常量是对的；剿饷崇祯十年、练饷崇祯十一至十二年这个方向与资料一致。辽饷“崇祯三/四年增”的具体口径 port 前再锚正式资料即可。参考：[三餉](https://zh.wikipedia.org/wiki/%E4%B8%89%E9%A4%89)、[三饷加派](https://m.canet.com.cn/view-617391-1.html)。

**spike**

不能说“挑不出”。原始 golden 确实全绿：

`python3 spike_settle_tick.py | tail -n 90`  
输出片段：`PASS G1...G17`、`PASS G9 三tick链`、`全部 PASS`。

但还有 3 个 port 前真实缺口：

1. costed `清欠/挪借火耗/追赃/蠲免` 仍然“进 k 分母但不真扣成本”，也不 fail-loud。  
   代码只在 `补饷/清丈/营建` 扣 `ec`，转移/征收类分支没有扣款：[spike_settle_tick.py](/Users/akagilnc/WorkSpace/Ming_LLM-tianmu/spike_settle_tick.py:67)。  
   我跑 `清欠 amount=10 cost=5`，输出 `ΣCost=5.00 k=1.0000`、`清欠 10.00`、三层断言 `PASS`、`RESULT True`。这正是 v18 §9 禁的路径。

2. `赈济 action -> Due_4 -> unmet_relief` 没有被 spike 接通。  
   G17 是直接塞 `p['Due']['赈济']=15`，不是 action 路径；`KNOWN_ACTIONS` 没有 `赈济`：[spike_settle_tick.py](/Users/akagilnc/WorkSpace/Ming_LLM-tianmu/spike_settle_tick.py:193)。  
   我跑 `dict(type='赈济', amount=15)`，输出：`RAISE ValueError unknown action: 赈济`。

3. 低实征时的 `起运池=min(实征, 起运定额)` 还没有 golden 实例化。  
   我把实现变异成“永远按定额起运”，现有 G1–G17 仍 `全部 PASS`；原因是现有 case 都是 `实征 >= 起运定额`。需要补一个 `实征 < 起运定额` 的 hard expect。

所以结论是：**v18 设计基本可收敛；spike 还不能原样 port。** 修掉补饷文字矛盾、costed 征收/转移 action、赈济 action path、低实征起运 golden 后，我才会说“挑不出问题，可 port”。
