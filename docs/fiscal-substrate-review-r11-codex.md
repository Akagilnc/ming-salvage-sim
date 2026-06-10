# r11 · codex(v11+spike)

结论：v11 方向对，旧 tautology 废得对；但现在只能判 **G1/G2 现金守恒 spine 已锁住**，还不能判“完整省级财政 spine 可锁、两个实现者必写出同一引擎”。

**1. §0.1 守恒**
新式 `Δ(Σ CASH)=民间流出−受款方流入` 是真钱守恒，G1/G2 算得对。实跑：

```text
python3 spike_settle_tick.py
G1: Δcash=-41.600  民间流出−受款方流入=-41.600  残差=+0.0000 PASS
G2: Δcash=-1.600   民间流出−受款方流入=-1.600   残差=+0.0000 PASS
```

三条对账在 G1/G2 上自洽：现金平；债务平，G2 要把 action 补饷 10 明确算作 `Repaid_i`；C 灰账也平，都是 `C_old+火耗实收=8.4`。旧式 `82=49+8.4+21+3.6` 确实是征收侧恒等分解，和起运、付款、期初省库、结转都无关，废得对。

但 §0.1 现在不是全量通式。它只适用于 `拨付net=0`、无清欠/追赃/挪借外部入库的窄 tick。我临时把 G1 改成 `拨付net=10`，结果：

```text
G1 + 拨付net10 => FAIL
[守恒] Δcash=-41.600  民间流出−受款方流入=-51.600  残差=+10.0000
```

所以总式应升级成：`ΔΣCASH = 边界流入本省 − 边界流出本省`。`民间流出` 里至少要另列清欠实收；外部拨付也要列入边界流入。`C→可支` 这种内部挪借不进总现金边界式，只进 C 对账。

**2. spike ↔ spec 一致性**
对 G1/G2，spike 是忠实的：账户列表、火耗、逋赋、起运、省内池、付款 waterfall、G2 的 k 缩和防双扣都和文档数字一致。对应代码在 [spike_settle_tick.py](/Users/akagilnc/WorkSpace/Ming_LLM-tianmu/spike_settle_tick.py:31) 到 [spike_settle_tick.py](/Users/akagilnc/WorkSpace/Ming_LLM-tianmu/spike_settle_tick.py:100)。

但有几个不一致/假 PASS 风险：

- 文档 [docs/FISCAL_PROVINCE_SUBSTRATE.md](/Users/akagilnc/WorkSpace/Ming_LLM-tianmu/docs/FISCAL_PROVINCE_SUBSTRATE.md:33) 仍写 `transfer_to 立即执行→批量算k`，代码实际是先算 k 再执行 action。这里会让两个实现者分叉。
- §0.1 的 `受款方流入=起运+实付+偿旧欠` 没明说“支付类 action 也算偿旧欠/实付”。spike G2 把 action 补饷 10 加进受款方流入，否则 G2 不会平。
- spike 的 `PASS` 只断言现金，不断言债务/C。若 claim 更新写错但 cash 平，仍会 `PASS`。现在 G1/G2 的 claim 打印值是对的，但不是测试门。
- spike 不是完整 `⓪–⑪`：没实现清欠、追赃、挪借火耗、中饱、efficiency 损耗、通用 `transfer_to`、0-cost action、modifier、白名单 clamp。
- 所有正 cost action 都被代码当作 `受款方` 支付；但 spec 区分“支付类”和“行政成本类”。行政成本的 sink 需要另钉死。
- `claim['军饷欠']=max(0, old-eff_cost)` 若旧欠小于 eff_cost，会现金全付、债务只减到 0，超额部分语义未定义。

**3. spine 锁定度**
G1/G2 这条窄 spine 已经能锁：无 action baseline、补饷 action、k 缩、省库不双扣，这些比 v10 扎实很多。

完整 spine 还没锁。最大分叉点是：action staging/k 顺序、外部拨付/清欠类边界流、支付类 action 是否进入 `Σ实付/Σ偿旧欠`、C 内部挪借如何进入可支、行政成本 sink。照现在文字，两个实现者大概率能写出同一 G1/G2，但写不到同一完整 tick 引擎。

**4. 覆盖**
不够。G1/G2 是合格种子，不是完整 golden suite。优先补：

- G3 清丈：本 tick 不应凭空改 CASH，主要验田亩/税基/士绅阻力和下 tick 应征。
- G4 挪借火耗：`C_地方截留 -> 省内可支 -> 支付/结转`，同时断言总现金、C 对账、债务对账。
- G5 漂没/中饱/eff 损耗：漂没我临时测 `漂没率0.1` 现金仍 PASS；但中饱/eff 和拨付 gross/net 还没锁。
- 另加一个 `拨付net/gross != 0` golden；这是当前 §0.1 最直接的破口。
- 再加清欠/蠲免/追赃、旧欠小于补饷、multi-action k、0-cost action、source clamp 边界。

最终判词：**v11 可以作为“G1/G2 cash invariant 修正成功版”，但还不应宣布 spine 全锁。下一步不是大返工，是把 §0.1 改成通用边界式，并把 G3–G5/G6 写成真正断言 cash+B+C 的 golden。**
