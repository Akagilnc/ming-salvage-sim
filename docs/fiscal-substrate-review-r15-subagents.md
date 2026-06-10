# r15 · subagent(v15+spike,变异)

## opus 4.8 — 逮到第三层 tautology:k
- per-account(r13)、param 下沉(r14)堵死后,opus 注入 ~20 变异,逮到最后一个同源残留:**settlement 的 `k` 被三条 oracle 借用**。E2/E3(settlement k 砍半)→ cash 守恒 PASS、债务/C oracle 读同一污染 k 跟着算 → 三断言全 PASS 漏过。修:oracle 独立重算 `o_k`(从 st 开账快照+action costs)。已验 E2/E3 FAIL、G 全 PASS 零回归。
- 判:补 k 这刀即到底,可 port。

## sonnet 4.6 — o_pool 残留(C-oracle 兜底,非独立漏洞)
- 债务 oracle 的 `o_pool=省内可支`(运行时)对「C金额→省库」relabel 漏检,但被 C 分账 oracle 从 param 独立兜底(覆盖集互补)。建议注释这条依赖,prot 时勿单删 C oracle。
- 边界(k=0/多costed/追赃eff<1/多补饷/赈济Due>0)无误报。建议补 G12 赈济、G13 拨付+追赃。
- 判:可收敛/可 port,带标注。

## 处置(cycle 6,v16)
o_k 独立重算(3处替换),E2 自变异验 FAIL;o_pool 加注释;补 G12/G13。G1-G13 全 PASS。
