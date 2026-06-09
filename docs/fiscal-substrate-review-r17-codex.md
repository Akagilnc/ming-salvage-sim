# r17 · codex(holistic v17)

结论：**v17 正文挑不出结构性问题，设计可收敛；但 spike 还挑得出 2 个真实 port 前缺口，所以我不能说“完全可 port”。**

**v17 评审**

v17 的财政 spine 本身我挑不出大问题：CASH / BOUNDARY / CLAIM 三分、火耗/漂没/中饱/C_eff 的叙事分账、死亡螺旋交给 LLM 软判、补饷 clamp 后“不转用”的官僚语义，都自洽。三饷拆时间线这个方向也对；我额外抽查资料，剿饷崇祯十年、练饷在崇祯十一到十二年间议征/落地，v17 “不能开局全量常量”的判断成立。([zh.wikipedia.org](https://zh.wikipedia.org/wiki/%E4%B8%89%E9%A4%89?utm_source=openai)) ([szzy.7lue.cn](https://szzy.7lue.cn/read/fd49474ea4b458f2d0c9cc879fd1d534/32aefc80705c31cf66a1e6228461e7d3.md?utm_source=openai))

正文唯一小处是表述别过头：开头说 oracle “绝不读 settlement 中间量”，但 spike 仍有 `o_pool = 省内可支`，正文后面也承认这是残留。这个不是新设计漏洞，只是 port 时别把它当“完全独立 oracle”复制。

**spike 评审**

我跑了当前文件：

`python3 spike_settle_tick.py | tail -n 80`

输出片段：`PASS G1...G14`、`PASS G9 三tick链`、`全部 PASS`。补饷不扣钱、清丈 effect ×2、k 砍半、火耗/中饱 relabel、军饷欠 relabel 这些变异都被咬住了。

但还有两个真实问题：

1. **costed 清欠/挪借/追赃/蠲免会“进 k 分母但不真扣成本”。**  
   spec 明写这些 action 若带 `cost`，必须真从省库扣，或直接禁带 cost：[docs/FISCAL_PROVINCE_SUBSTRATE.md](/Users/akagilnc/WorkSpace/Ming_LLM-tianmu/docs/FISCAL_PROVINCE_SUBSTRATE.md:60)。但 spike 只在 `清丈/营建/补饷` 分支扣 `ec`；`挪借火耗/追赃/清欠/蠲免` 分支不扣：[spike_settle_tick.py](/Users/akagilnc/WorkSpace/Ming_LLM-tianmu/spike_settle_tick.py:75)。  
   我现场跑 `清欠 cost=5 amount=10 民欠=15`，输出 `ΣCost=5.00 k=1.0000`、`清欠 10.00`、`ok=True`，没有任何行政成本扣款。这正是 §9 禁止的“cost 只缩力度不落账”。

2. **赈济 action 口径没被 spike 覆盖。**  
   spec 说 `Due_4=action amount`，并且未付输出 `unmet_relief`；但 spike 的 `KNOWN_ACTIONS` 没有 `赈济`，G12 只是直接塞 `Due=dict(...赈济=15)`：[spike_settle_tick.py](/Users/akagilnc/WorkSpace/Ming_LLM-tianmu/spike_settle_tick.py:203)。我测 `dict(type='赈济', cost=1, amount=1)`，结果是 `ValueError: unknown action: 赈济`。所以 port-facing 的“赈济 action → Due_4 → unmet_relief”还没被 golden 锁住。

还有一个小覆盖缺口：现有 G1–G14 都是 `实征 >= 起运定额`，所以把 `起运池` 错写成固定定额时，现有 golden 仍 `全部 PASS`。自造低实征 case 后会 FAIL，但 golden 本身没覆盖。建议补一个“实征 < 起运定额”的低征收锚。

所以最终判断：**v17 可收敛；spike 不建议原样 port。补上 costed 征收/转移类 action 的 fail-loud 或真扣成本、赈济 action/unmet_relief golden、低实征起运 clamp golden 后，就可以 port。**
