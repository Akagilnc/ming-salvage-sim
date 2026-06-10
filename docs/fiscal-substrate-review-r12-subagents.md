# r12 · 干净上下文 subagent(v12 + spike,变异测试)

> opus 4.8(14变异)/ sonnet 4.6(8变异)冷读 v12 + **亲跑 spike 注入 bug**。2026-06-09。

## 共同确认:守恒 mass-balance 这层 v12 真修对了
拨付net 洞堵上(变异验证),挪借/追赃归 CASH 内部口径对,8–14 变异在 spike 走到的路径上全被抓,无第二个边界漏项,无假 PASS。

## 新硬伤(收敛,全可修,无架构问题)
1. **per-account 对账缺失(opus T12,最重)**:三断言只锁「总量 mass 平」,不锁「钱落哪个子账户」。opus 把 中饱 relabel 进省库(net=g,中饱=0)→ 三断言全 PASS。**省库↔C_中饱↔C_漂没 任意 relabel 隐形 —— 而贪墨vs国库正是本游戏核心张力轴。** 须加第4类断言:每个 C_ 子账户单独 reconcile。
2. **C 对账公式漏 `+eff损耗`(opus T2 + sonnet BLIND1)**:`expC` 无 eff损耗 项,但账户声明了。opus 注入 省库→C_eff损耗 → C 对账 FAIL(13.4≠8.4)。eff损耗 一激活公式就崩。须补项 + 定义其现金来源 + 加 G8。
3. **recurring/跨 tick 没建模(opus T6)**:`run_tick` 返回 bool 不返回末态,无法 tick1→tick2;cost_type recurring 被忽略。死亡螺旋是跨 tick 现象,单 tick golden 证明不了时间轴守恒。
4. **spec §0.1 CASH_out 漏行政成本项(sonnet)**:spike 清丈 cost 走了 `cash_out+=ec`,但 spec 公式没列;实现者照 spec 写会漏登记。
5. **0-cost action 被误缩 + ghost cost 稀释(opus T10 + sonnet BLIND2)**:spike 对所有 action `amt*=k`,含 0-cost 挪借/清欠(spec §6 说 0-cost 不缩);且 clamp 到 0 的补饷仍占 k 分母,过度压缩别的 action。spec↔spike 冲突 + 设计题(k稀释是否预期/要不要两阶段)。
6. dead code:line44 `rec['补饷支付']` 漏 `+=`(no-op)、line46 `cash_out+=0`、省库库银_post 赋值后没读 + 注释误导;G3「现金中性」注释错(cost=2,Δcash≠0,中性只指税基)。

## 判定
两声:守恒边界 v12 对了,但**断言只到「总量平」没到「分账对」** + eff损耗/追赃悬空 + recurring 跨 tick 缺。spine 差三步:per-account 对账 + 跨 tick 状态返回 + 接线悬空对账项(+ spec 补行政成本/0-cost k)。
