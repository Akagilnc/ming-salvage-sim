# r15 · agy(v15+spike)

I will start by analyzing the directory structure of the current workspace to understand the codebase.
I will view the `spike_settle_tick.py` file to understand the logic of the spike simulation and its implementation of G1–G11.
I will view the contents of `independent_auditor.py` to examine the current implementation of the auditor.
I will view the `mutation_tester.py` file.
I will view the `mutation_test_suite.py` file to see the mutation tests.
I will run `mutation_test_suite.py` to see the current outputs of the original auditor and the truly independent auditor under various mutation injections and boundary scenarios.
I will write the spike code provided in the user prompt to a temporary file `spike_v15.py` and run it to verify that G1–G11 all pass as stated, and to use it for further mutation analysis.
I will run `spike_v15.py` to verify if all G1-G11 cases pass under the new oracle.
I will create a script `test_exploit.py` to test if we can inject a mutation that fakes cash during `补饷` but bypasses all three assertions of the new v15 spike.
I will run `test_exploit.py` to see if our exploit mutation actually bypasses the assertions.
# 明末崇祯「省级财政基座」v15 与 Spike 深度评审报告

经过对 `spike_v15.py` 的执行验证、基于 `mutation_test_suite.py` 注入变异的对照测试，以及对 `test_exploit.py` 的实证漏洞验证，现提交以下评审结论。

---

## 1. 独立 Oracle 同源残留审计 (Exploit 实证)

### 📌 结论：v15 的 Oracle 仍存在同源残留，有 4 类一致变异可被全 PASS 漏过

虽然 v15 下沉了部分重算逻辑，但由于对账口径仍依赖于 Simulation（引擎）落账过程中的中间局部/日志变量，造成了「同源残留」。

#### 残留一：`ok_cash` 依赖 Simulation 内部的 `cash_in` 与 `cash_out`
*   **同源机制**：断言使用 `Δcash == cash_in - cash_out`，而 `cash_in` / `cash_out` 是引擎在模拟期间累加的日志。
*   **漏过路径**：如果变异在 Action 阶段减少了债务，但**既未减省库，也未在 `cash_out` 中记录该笔开支**，则 `Δcash` (0) 与 `cash_in - cash_out` (0) 依然完美相等。

#### 残留二：债务 Oracle 的 `o_pool` 直接读取 `省内可支`
*   **同源机制**：债务对账的初始资金池使用了引擎的 `o_pool = 省内可支`（已包含 Action 阶段虚增的现金）。
*   **漏过路径**：在 Action 阶段虚假补饷（扣债不扣钱），导致结转到 step ⑪ 的 `省库库银` 虚高。此时 `o_pool` 也同样虚高，债务 Oracle 会在该虚高资金池上运行 waterfall，从而得出「剩余债务已清零」的预期，导致债务校验通过。

#### 漏洞实证 (`test_exploit.py`)
我们在本地编写并运行了 `test_exploit.py`，成功实现了 **`claim ↔ cash` 补饷只扣债不减省库** 的变异注入。结果显示：
*   **虚增现金**：系统平白无故凭空虚增了 $10$ 万两真金白银（最终省库 $49.00$ 对比正常的 $39.00$）。
*   **断言结果**：`ok_cash`、`ok_debt`、`ok_C` 三断言**全部 PASS**！

#### 漏过变异矩阵 (v15 漏过 vs 真正独立 Oracle 拦截)
根据 `mutation_test_suite.py` 运行结果，以下 4 类变异在 v15 Oracle 下均会漏过：
1.  **`claim_cash_swap_repay_no_cash` (补饷只扣债不减省库)**: v15 Oracle 漏过 (PASS) $\rightarrow$ 独立 Oracle 拦截 (FAIL)。
2.  **`claim_cash_swap_cash_no_repay` (补饷只减省库不扣债)**: v15 Oracle 漏过 (PASS) $\rightarrow$ 独立 Oracle 拦截 (FAIL)。
3.  **`consistent_fake_clear_debt` (清欠收15且一致log15, 破坏入参amt=10)**: v15 Oracle 漏过 (PASS) $\rightarrow$ 独立 Oracle 拦截 (FAIL)。
4.  **`land_update_mismatch` (清丈增地 double 导致动态税虚增)**: v15 Oracle 漏过 (PASS) $\rightarrow$ 独立 Oracle 拦截 (FAIL)（由于 v15 C-Oracle 的 `正赋_o` 读了已被引擎篡改的 `官民田`）。

---

## 2. Oracle 自身 Boundary & 误报漏报评估

### 📌 结论：存在 1 处误报 (False Alarm) 漏洞，其余边界安全

#### 1. 挪借/追赃多 Action 的效率覆盖 Bug (误报)
*   **现象**：在同一 tick 内存有多个 `挪借火耗` 或 `追赃` Action，且它们的 `eff`（折损效率）不同。
*   **问题**：Oracle 仅维护了单一的 `exp_action_borrow_fire_eff = a.get('eff', 1.0)`，导致后面的 Action 覆盖了前面的效率设定。
*   **结果**：计算出的期望 `C_eff损耗` 偏离引擎实际损耗，导致 **正常 case 被误报 FAIL**。
*   **修复**：在 Oracle 的 Action 遍历中，每次遇到 `挪借` / `追赃` 应直接累加 `loss = actual * (1 - eff)` 到 `o_in['C_eff损耗']`，而非通过全局效率参数在事后重算。

#### 2. 其他边界情况测试 (PASS，无误报)
*   **`k = 0`**：当 `Stock_start = 0` 且有 costed action 时，`k` 缩水至 `0`。引擎不扣钱，Oracle 也不期望扣钱，且 0-cost action 不受影响，对账安全。
*   **多 Costed 共享 `k`**：多 Action 按比例缩减安全。
*   **追赃 `eff < 1`**：C-Oracle 对赃款和漂没的折损进行了正确的分账与消耗审计。
*   **赈济 `Due > 0`**：未足额支付的赈济款在 step ⑪ waterfall 中消耗 Pool 却不积欠，由于 `nd` 被 `if h != '赈济'` 正确过滤，账目与债务 Oracle 完美对齐。

---

## 3. Spine 锁得住吗？ (可收敛 / 可 port 实现)

### 📌 结论：完全「可收敛 / 可 port 实现」，只差以下关键步骤

陕西单省 Spine 在 G1–G11 表现出极好的数值稳定性与逻辑闭环，死亡螺旋与分池规则运行正常，完全可以移植进 `ming_sim`，但必须执行以下升级以彻底锁定：

1.  **升级为真正的独立 Oracle (Truly Independent Auditor)**：
    *   **彻底断奶**：Oracle **严禁读取** 引擎模拟后的任何流变量 (`cash_in`, `cash_out`, `Pool`, `S`, `k`, `官民田`)。
    *   **自建 Waterfall**：Oracle 必须使用入参 `st` (Initial State)、`p` (Params) 和 `actions` (Actions) 从零重算 `exp_k`、`exp_官民田`、`exp_S_可支` 并执行独立的 Waterfall 流程。
    *   **双边断言**：除了校验 `C_` 和 `CLAIM`，还需断言 `cash['省库库银'] == exp_S`，彻底堵死省库现金的非法截留。
2.  **修复多 Action 效率覆盖缺陷**：改用逐笔累加折损的方式计算 `C_eff损耗`。
3.  **Port 规划**：
    *   直接将 `mutation_test_suite.py` 中的 `audit_truly_independent` 逻辑作为 `ming_sim` 的独立 Auditor。
    *   将 G1–G11 的边界条件与多 tick 循环转化为 `pytest` 测试套件，作为引擎的核心 Golden Test 护城河。