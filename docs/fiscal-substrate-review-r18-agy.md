# r18 · agy(holistic v18)

本轮评审对 **明末崇祯「省级财政基座」v18** 规范及 **spike 仿真实现** 进行了深度审计。

### **整体评审结论**
> **「有关键断言漏洞，修复后可收敛/Port」**
> 经过变异分析与代码审计，发现 **spike 包含两个严重的“非独立 Oracle”断言漏洞**（即 Oracle 对账逻辑隐式依赖了 engine 执行中的中间状态/派生值，未能做到完全解耦）。这会导致特定类型的 bug/作弊（如在结算池中凭空印钱、非法双倍清丈土地）能够完美绕过 5 层断言。以下为您详述具体问题与修复设计。

---

## ===== v18 设计与史实评审 =====

### 1. 三饷时间线拆分（史实与 Seed 建议）
- **史实自洽**：v18 规范中提及“三饷按时间线拆”。在后续 port 进 `ming_sim` 时，必须确保 `三饷应征` 字段不是一个静态的开局常量。崇祯初年仅有辽饷（且崇祯四年加派）；崇祯十年杨嗣昌推行“十面张网”始征剿饷；崇祯十一年为防清军入关始征练饷。
- **Port 落地建议**：在 seed 初始化时，应根据游戏当前 tick 对应的历史年份，动态计算三饷对应的加派亩额，而不是直接读取一个固定比例。

### 2. `unmet_relief`（赈济未满足额）与 LLM 软判的闭环
- **设计自洽**：v18 规定“未付不积欠，但引擎须输出 `unmet_relief = Due_4 - 实付` 给 LLM”。由于这部分钱不计入 `CLAIM`（政府不欠死人钱），如果不做处理，该指标在 tick 结束后就清零了。
- **Port 落地建议**：在 port 层，必须将 `unmet_relief` 显式转换为下一 tick 的**流民增加率**、**民变爆发概率**或**士绅离心度**等高负面因子，不能仅作为文本输出，否则会破坏“只算代价”的铁律约束。

---

## ===== Spike 真实性与断言漏洞评审 =====

在对 `spike_settle_tick.py` 的对账逻辑进行静态审计时，发现了以下破坏“独立 Oracle”原则的漏网之鱼：

### 漏洞 1：`o_pool = 省内可支` 引入的债务对账“半同源”漏洞
*   **漏洞代码**：`spike_settle_tick.py` 第 100 行 / 规范中的债务对账段：
    ```python
    o_pool = 省内可支
    ```
*   **机制分析**：`省内可支` 是由 engine 运行期算出的中间变量（`cash['省库库银'] + 省内池`）。Oracle 直接读取了这个运行时变量，而没有从 `st`（初始省库）、`p`（参数）及 `actions` 完全自主重算。
*   **漏洞场景**：如果 engine 内部出现 bug，在计算 `省内池` 时发生溢出，或者作弊注入了额外的 `省内可支` 额度（例如“凭空印钱”来偿还债务）。
    此时，债务偿付 `r['Repaid']` 相应增加，`cash_out` 增加，`cash['省库库银']` 减少。由于 `ok_cash` 仅仅校验了 `Δcash == cash_in - cash_out` 的双边平衡，这笔假钱依然能通过现金守恒。而因为债务 Oracle 读了错误的 `o_pool`，它也会预期有更多债务被还掉。最终，**债务对账 (`ok_debt`) 和 现金对账 (`ok_cash`) 都会显示 PASS，bug 被完美漏过**。

### 漏洞 2：C 账 Oracle 引用 mutated `官民田` 导致的“状态泄露”漏洞
*   **漏洞代码**：`spike_settle_tick.py` 第 28 行与第 122 行：
    ```python
    官民田 = float(st.get('官民田',0))  # 运行时初始值
    # ... 在 Action 阶段被 engine 修改 ...
    官民田 += 挖
    # ... 在对账阶段 ...
    正赋_o = p.get('正赋应征', round(官民田*p.get('正赋亩额',0)/12,4))
    ```
*   **机制分析**：Oracle 中的 `正赋_o` 重算使用了 `官民田` 变量。然而，在执行 `清丈` 动作时，该变量已经被 engine 的结算逻辑直接改写了（发生了原地 Mutation）。
*   **漏洞场景**：若 engine 中的 `清丈` 逻辑存在 bug（例如清丈 100 万亩隐田，错误地给 `官民田` 加上了 200 万亩），虽然土地守恒 `ok_land` 会因为总和不符失败，但**如果 engine 巧妙地同时扣减了 200 万亩隐田**（即 `官民田 += 2*挖`, `隐田 -= 2*挖`），则土地守恒依然 PASS。由于 C 账 Oracle 读取了被篡改的 `官民田` 来计算预期火耗，它也会得出与 engine 一致的火耗值，导致 **C 分账对账 (`ok_C`) 依然 PASS**。

### 漏洞 3：Fail-Loud 输入/状态校验存在盲区
*   **状态非负校验缺失**：代码中仅校验了 Action 成本及比率的边界，但未校验输入状态 `st` 字典中各 stock 的非负性（如 `省库库银`、`C_地方截留`、`军饷欠` 等）。若传入负的 `省库库银`，将导致力度系数 `k` 计算为负数，使得行政成本变成“给省库发钱”的作弊器。
*   **参数非负校验缺失**：未对 `p['Due']` 各项、`p['起运定额']`、`p['拨付gross']` 进行 `>=0` 校验。负的 `Due` 同样会在 waterfall 阶段产生“负支付”，相当于凭空生钱。

---

## ===== 建议修复方案（可直接收敛至 Port 代码） =====

为了彻底堵死上述漏洞，Oracle 必须做到**绝对独立重构**，不从运行态读取任何变量，不共享任何可变变量。

### 修复方案：重构 Oracle 内部的沙盒状态模拟
在对账开始前，独立复制一份只读的初始数据，并在对账时内部模拟 Action 演变：

```python
# 1. 彻底解耦 Oracle 状态复制
o_provincial_cash = float(st.get('省库库银', 0))
o_C = {k: float(st.get(k, 0)) for k in CASH_KEYS if k.startswith('C_')}
o_claim = {k: float(st.get(k, 0)) for k in CLAIM_KEYS}
o_官民田 = float(st.get('官民田', 0))
o_隐田 = float(st.get('隐田', 0))

# 2. 独立重跑 Action 对 o_* 状态的影响
o_Stock_start = o_provincial_cash
o_ΣCost = sum(a.get('cost',0) for a in actions if a.get('cost',0) > 0)
o_k = 1.0 if (o_ΣCost == 0 or o_ΣCost <= o_Stock_start) else o_Stock_start / o_ΣCost

o_action_spend = 0.0
o_a还 = {'军饷欠': 0.0}

for a in actions:
    has_cost = a.get('cost', 0) > 0
    ec = a.get('cost', 0) * o_k
    amt = a.get('amount', 0) * (o_k if has_cost else 1.0)
    t = a['type']
    
    if t == '补饷':
        还 = min(ec, o_claim['军饷欠'])
        o_provincial_cash -= 还
        o_claim['军饷欠'] -= 还
        o_a还['军饷欠'] += 还
        o_action_spend += 还
    elif t in ('清丈', '营建'):
        o_provincial_cash -= ec
        o_action_spend += ec
        if t == '清丈':
            挖 = min(a.get('挖隐田', 0) * (o_k if has_cost else 1.0), o_隐田)
            o_隐田 -= 挖
            o_官民田 += 挖
    elif t == '挪借火耗':
        mv = min(amt, o_C['C_地方截留'])
        o_C['C_地方截留'] -= mv
        o_provincial_cash += mv * a.get('eff', 1.0)
        # 记录漂没/损耗等
    elif t == '追赃':
        mv = min(amt, o_C['C_中饱'])
        o_C['C_中饱'] -= mv
        o_provincial_cash += mv * a.get('eff', 1.0)
    elif t == '清欠':
        收 = min(amt, o_claim['民欠旧赋'])
        o_claim['民欠旧赋'] -= 收
        o_provincial_cash += 收
    elif t == '蠲免':
        o_claim['民欠旧赋'] -= min(amt, o_claim['民欠旧赋'])

# 3. 独立计算税收与分池
o_正赋 = p.get('正赋应征', round(o_官民田 * p.get('正赋亩额', 0.0) / 12, 4))
o_实征 = (o_正赋 + p['三饷应征']) * (1 - p['逋赋率'])
o_火耗实收 = (o_正赋 * p['火耗率']) * (1 - p['逋赋率'])
o_民欠新增 = (o_正赋 + p['三饷应征']) - o_实征

o_起运池 = min(o_实征, p['起运定额'])
o_省内池 = max(0.0, o_实征 - o_起运池)

# 4. 独立组装 o_pool，彻底斩断对运行期「省内可支」的读取
o_net = p.get('拨付gross', 0.0) * (1 - p.get('中饱率', 0.0))
o_省内可支 = (o_provincial_cash + o_net) + o_省内池

# 5. 基于 o_省内可支 独立跑 Waterfall，完成债务与 C 账的最终对账
# ... 此时可安全对比最终 cash[ck] == o_C[ck]，claim[c] == o_claim[c] ...
```

修复这两个 Oracle 状态漏洞并补齐非负校验后，明末崇祯「省级财政基座」v18 即可宣告**收敛完毕，推荐 Port 进主引擎 `ming_sim`**。