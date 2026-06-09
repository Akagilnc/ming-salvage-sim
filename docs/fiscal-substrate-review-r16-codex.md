# r16 · codex(holistic v16)

总判：挑得出问题。v16 的设计方向对，已经足够像“省级财政基座”而不是经济沙盒；但还不能说“独立 oracle 到底”。现在差的不是再改玩法大方向，而是补两类独立审计，否则 port 成 golden test 会带着假安全感。

**v16 草表**
1. 三账模型总体成立。`CASH / BOUNDARY / CLAIM` 拆法是对的，尤其把火耗、漂没、中饱做成灰账，而不是直接塞进国库效率系数，符合“账本确定性 + LLM 软判”。

2. `C_地方截留` 不自动进入省内可支，这个设计我支持。它很好地制造“官绅肥、官衙穷、皇帝越查越发现钱不在账上”的张力，不是 bug。

3. 但 `省内池` 语义要再钉死。现在实征现金没有先落入某个 CASH 账户，而是以 Flow 形式进入 `省内池`，然后在 ⑪ 直接付款。算术能平，但 port 时很容易有人写成“实征先进省库，再分池”，然后双计。建议明写：`省内池` 是本 tick 实征的临时可支现金流，不是 stock。

4. `省库库银_new=S, 覆盖写` 是 spike 方便法，不能成为真引擎风格。真引擎可以派生 S，但必须有独立 `expected_省库库银_new` 断言。否则 action 阶段凭空省下的钱会被后续 waterfall 吸收掉。

5. 起运优先符合崇祯末世财政张力，但不要做成唯一宇宙法则。玩家应能下旨“缓起运、留饷陕西、截留京运”，机械效果是改 `起运定额/priority`，代价交给 LLM 判：京师缺饷、户部弹劾、地方暂缓兵变。

6. `k` 作为预算承诺系数可以保留，但 G6 暴露一个玩法语义：欠 5、补饷预算 30，只花 5；若同 tick 还有别的 action，剩余 25 是否允许转用？现在语义是“不转用，仍稀释别的预算”。这很官僚，也很晚明，但必须在 clamp reason 里明说，否则玩家会觉得钱被系统吞了。

7. 当前模型偏“有现金才办事”。这会压住一种很晚明、也很好玩的选择：开空票、赊欠营建、欠着募兵。建议 action 增加 funding mode：`cash_only` 和 `arrears_allowed`。后者把没付部分进 `官俸欠/军饷欠/行政欠`，LLM 判怨气和哗变。

8. `官俸欠` 建议改名或拆成 `官署行政欠/俸役欠`。史实上明代官俸薄、官员借贷和盘剥有现实基础，资料也提到初任官员困顿、京债、上任后“剥下/借库银”等现象；但地方行政运转缺口不等于狭义官员工资。([news.bjd.com.cn](https://news.bjd.com.cn/2022/08/15/10134150.shtml))

9. 三饷必须按时间线拆。崇祯初年不能把辽饷、剿饷、练饷都当已存在常量。辽饷源于万历末并在崇祯四年提高；剿饷是崇祯十年；练饷是崇祯十一年后。引擎字段可以叫 `三饷应征`，但 seed 应拆 `辽/剿/练` 三分量。([zh.wikipedia.org](https://zh.wikipedia.org/zh-hans/%E4%B8%89%E9%A4%89))

10. 宗禄作为 per-province 出血是对的，但别把全国宗禄简单放大成陕西主压死项。可打开资料里，天启后宗禄总额估算约占岁入 8.66%，问题更在地方集中、拖欠、轻视与结构性挤压。([zhuanlan.zhihu.com](https://zhuanlan.zhihu.com/p/508242610))

11. 赈济最后支付且不积欠，玩法上很狠，成立。但必须输出 `unmet_relief` 给 LLM。否则账上没有债，裁判可能看不见“灾民没拿到钱”。

12. `C_eff损耗` 要定义可追赃性。如果它表示运输/执行中的真实耗散或散入无名小吏，就应是低可追回灰账；如果只是 loss sink，别让普通追赃把它当完整现金池。

**spike**
1. 本地原样跑过，当前文件确实全 PASS。命令：`python3 spike_settle_tick.py | tail -n 40`。输出片段：`PASS G1...G13`，`全部 PASS`。

2. 但我现场做了一个内存变异：把“补饷”改成只扣 `军饷欠`，不扣 `省库库银`，也不记 `cash_out`。结果 G1-G13 仍全部 PASS。输出片段：`PASS G2 补饷k=.33`、`PASS G6 超额补饷`、`全部 PASS`。这是硬漏。

3. 根因：现金守恒仍读 settlement 自己累加的 `cash_in/cash_out`；债务 oracle 又读运行时 `省内可支`。`C oracle 兜底` 只能抓 C relabel，抓不到“债务清了但真钱没出去”。

4. 修法：oracle 不能只断 `ΣCASH` 和 per-C/per-CLAIM。还要从 `st+p+actions` 独立重算完整 action phase、征收、分池、拨付、waterfall，断言 `省库库银_new == oracle_S`，并把 `cash_in/cash_out` 当被测输出，而不是 oracle 输入。

5. 我还测了动态田亩税基漏洞：把清丈效果变异成 `官民田 += 挖*2`，并用 `正赋亩额` 动态算税，仍全 PASS，末态 `官民田=3600`。根因是 C oracle 用的是 action 后的 `官民田`，不是自己从期初 `官民田/隐田/actions` 重演出的 `o_官民田`。

6. G3 现在没抓住这个，是因为 base 里固定了 `正赋应征=60`，清丈并不真正影响本 tick 税基。G3 只能证明“清丈 cost 扣了”，不能证明“清丈 effect 正确”。

7. spike 缺输入校验。`eff > 1` 会让 target 增加超过 source 减少，凭空生钱；负 amount 也可能反向造账。真引擎必须 clamp/拒绝：`amount>=0`，`cost>=0`，`0<=eff<=1`，`0<=逋赋/漂没/中饱<=1`。

8. `KNOWN_ACTIONS` 没有 `赈济`，但 spec 说赈济 Due 来自 action amount。G12 是直接塞 params，不是 action 测试。port 前要补“赈济 action → Due_4 → 未付不成债但进 unmet_relief”。

9. recurring 还只是“每 tick 传同一个 action”。真引擎需要 recurring obligation ledger：起止、取消、停工、k=0 时本期 effect 是否为 0、欠工料是否成债。

10. 所以结论不是“推翻”，而是“差一轮收口”：v16 的玩法/语义 spine 可以继续，spike 不能作为最终 golden 直接 port。先补独立 `省库库银/state/action-effect oracle`、动态税基 G、赈济 action G、输入校验 G，再收敛。
