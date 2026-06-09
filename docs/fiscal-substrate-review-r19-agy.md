# r19 · agy(holistic v19)

I will start by analyzing the current workspace to see if there are files related to the `v19` spec or the `spike` implementation that I should inspect. I will use the `list_dir` tool to examine the workspace.
I will view the contents of the current `spike_settle_tick.py` file to inspect the exact implementation of the spike and see how it matches the description in the prompt. I will use the `view_file` tool.
I will view the `independent_auditor.py` file to understand what it does and check if there are any insights there. I will use the `view_file` tool.
I will view `mutation_test_suite.py` to see what mutations are defined and tested, and how the system verifies itself. I will use the `view_file` tool.
I will view the contents of `mutation_tester.py` to see what else it defines. I will use the `view_file` tool.
I will execute the mutation test suite to verify the current codebase's integrity and see how the assertions catch mutations. I will use the `run_command` tool.
I will write the spike code provided in the prompt to a new file `spike_v19.py` in the sandbox directory to run and test it. I will use the `write_to_file` tool.
I will execute the spike v19 script to see if all tests (G1 through G19, including the three-tick chain for G9) pass and to inspect its output. I will use the `run_command` tool.
I will create a test script `test_tautology_land.py` to verify if a mutation that shifts a wrong amount of land (but conserves the sum of land) is caught by the internal inline assertions of the spike when no external `expect` dict is provided. I will use the `write_to_file` tool.
I will write the test script `test_tautology_land.py` to `/tmp/ming_agy_sandbox/test_tautology_land.py` without including the `ArtifactMetadata`, as it is a temporary scratch script in the sandbox. I will use the `write_to_file` tool.
I will execute the newly created `test_tautology_land.py` script to see if all assertions pass despite the land mutation. I will use the `run_command` tool.
I will correct the print statement on line 152 of `test_tautology_land.py` using the `replace_file_content` tool.
I will execute the corrected test script. I will use the `run_command` tool.
诚实地判断：**确实发现了一个非常隐蔽但属于实质性漏洞（Tautology/自循环校验）的问题。** 这个漏洞会导致：如果引擎在执行清丈等 action 时更新土地数据出错（例如多算或少算转换了的隐田，但保证土地总量守恒），**Spike 的 inline 独立断言仍然会全部 PASS。**

这不属于“为凑而凑”的细节噪声，而是由于断言中局部变量在审计前被污染，从而形成了“用错误的状态校验错误的状态”的自循环（Tautology）。

以下是具体文字评审：

---

### 一、 核心问题：土地与税基校验的「自循环（Tautology）」漏洞

#### 1. 问题复现与机制分析
在 `spike_v19.py` 中，第 ⓪ 步 action 执行时，清丈会修改局部变量 `官民田` 和 `隐田`：
```python
if t == '清丈':
    挖 = min(a.get('挖隐田',0)*(k if has_cost else 1.0), 隐田); 隐田 -= 挖; 官民田 += 挖
```
随后，在独立 oracle 校验中，计算期望的正赋 `正赋_o` 和民欠 `o_my` 时：
```python
# C 分账 oracle
正赋_o = p.get('正赋应征', round(官民田*p.get('正赋亩额',0)/12,4))
# ...
# 债务 oracle
o_my += (正赋+三饷)*bf
```
**致命点在于**：上述 `正赋_o` 与 `o_my` 直接读取了**已经被 mutated（可能已损坏）的局部变量 `官民田` 和 `正赋`**。

我们编写并运行了变异测试（`test_tautology_land.py`）：
* **变异注入**：清丈时将隐田转为官民田的额度翻倍（`mut_挖 = 2 * 挖`），但保持总量守恒（`隐田 -= mut_挖; 官民田 += mut_挖`）。
* **测试结果**：
  * 「土地总量守恒」断言通过（因为总和不变）。
  * **「债务对账·独立 oracle」与「C 分账·独立 oracle」全部 PASS！**
  * 原因是：结算（settlement）计算出的错误正赋，与独立 oracle 使用被污染的 `官民田` 计算出的错误 `正赋_o` **完全一致**。

如果不传入硬编码的 `expect` 常量（通常用于多 tick 或动态博弈测试中），这个实质性的引擎 bug 将会被 inline 断言**完全放过**。

---

### 二、 其他边缘漏洞与优化空间

#### 1. `o_pool = 省内可支` 导致的 runtime 变量依赖
在 `spike_v19.py` 内部注释中提到了 `o_pool = 省内可支` 是 `r15/sonnet` 残留：
```python
# 注(r15/sonnet 残留):o_pool 读 省内可支(运行时),对「C金额→省库」类 relabel 依赖 C 分账 oracle 兜底;勿单独删 C oracle
o_pool = 省内可支
```
这导致债务对账 oracle **依然依赖了结算过程中的中间量**。一旦 `省内可支` 本身计算出错（例如转移支付时损耗未扣），债务 oracle 就会被连带污染。

#### 2. `unmet_relief` 缺失 inline 断言
虽然 `unmet_relief` 作为重要的未付赈济输出给了 LLM，但 inline 审计中**完全没有任何断言**去核对 `r['unmet_relief']` 的期望值（应当为 `p['Due'].get('赈济',0) - o_paid['赈济']`），如果结算引擎因 Bug 漏报或多报饿死人数，断言依然为真。

---

### 三、 Spike 代码优化与修复方案

为了让 `run_tick` 内部的独立 oracle 达到 100% 的独立对账安全性，应当在 `run_tick` 的独立 oracle 区域进行如下修复：

1. **独立重建 `o_官民田` 与 `o_隐田`** 并进行独立对比校验。
2. **彻底脱离 `省内可支` 局部变量**，完全从初始 `st` 和 inputs 重构 `o_pool`。
3. **补齐 `unmet_relief` 的断言**。

#### 修复后的独立 oracle 断言部分代码：

```python
    # ── 1. 独立重构土地 ──
    o_官民田 = float(st.get('官民田',0))
    o_隐田 = float(st.get('隐田',0))
    for a in actions:
        if a['type'] == '清丈':
            has_cost = a.get('cost',0) > 0
            挖 = min(a.get('挖隐田',0)*(o_k if has_cost else 1.0), o_隐田)
            o_隐田 -= 挖
            o_官民田 += 挖
            
    ok_land_acct = (abs(官民田 - o_官民田) < EPS) and (abs(隐田 - o_隐田) < EPS)
    if not ok_land_acct:
        print(f"  [土地明细FAIL] 官民田{官民田}≠o_{o_官民田} 或 隐田{隐田}≠o_{o_隐田}")

    # ── 2. 独立重构税基 ──
    正赋_o = p.get('正赋应征', round(o_官民田*p.get('正赋亩额',0)/12,4))
    实征_o = (正赋_o + p['三饷应征'])*(1-bf)
    火耗应派_o = 正赋_o * fh
    起运池_o = min(实征_o, p['起运定额'])
    省内池_o = max(0.0, 实征_o - 起运池_o)
    net_o = p.get('拨付gross',0.0)*(1-p.get('中饱率',0.0))

    # ── 3. 独立重构 Action 阶段的现金流变动 ──
    o_action_spend_cash = 0.0
    o_a还 = {'军饷欠':0.0}
    curr_junqian = claim0['军饷欠']
    curr_my = claim0['民欠旧赋']
    o_borrowed_cash_net = 0.0
    o_action_clear_debt = 0.0
    
    bal_dfjl_o = C0['C_地方截留']
    bal_zb_o = C0['C_中饱']
    
    for a in actions:
        ak = o_k if a.get('cost',0) > 0 else 1.0
        amt = a.get('amount',0) * ak
        t = a['type']
        if t == '补饷':
            ec = a.get('cost',0) * o_k
            还 = min(ec, curr_junqian)
            curr_junqian -= 还
            o_a还['军饷欠'] += 还
            o_action_spend_cash += 还
        elif t in ('清丈', '营建'):
            ec = a.get('cost',0) * o_k
            o_action_spend_cash += ec
        elif t == '挪借火耗':
            act = min(amt, bal_dfjl_o)
            bal_dfjl_o -= act
            o_borrowed_cash_net += act * a.get('eff',1.0)
        elif t == '追赃':
            act = min(amt, bal_zb_o)
            bal_zb_o -= act
            o_borrowed_cash_net += act * a.get('eff',1.0)
        elif t == '清欠':
            收 = min(amt, curr_my)
            curr_my -= 收
            o_action_clear_debt += 收
        elif t == '蠲免':
            mj = min(amt, curr_my)
            curr_my -= mj

    # ── 4. 独立重构省内可支 Pool ──
    o_S_start = float(st.get('省库库银',0))
    o_pool = o_S_start - o_action_spend_cash + o_borrowed_cash_net + o_action_clear_debt + net_o + 省内池_o
    
    o_paid = {}
    temp_pool = o_pool
    for h in ['军饷','官俸','宗禄','赈济']:
        d = p['Due'].get(h,0.0)
        pay = min(temp_pool, d)
        temp_pool -= pay
        o_paid[h] = pay

    # ── 5. 补齐 unmet_relief 校验 ──
    o_unmet_relief = p['Due'].get('赈济',0.0) - o_paid['赈济']
    ok_unmet = abs(r['unmet_relief'] - o_unmet_relief) < EPS
    if not ok_unmet:
        print(f"  [赈济未满足FAIL] unmet_relief {r['unmet_relief']:.2f}≠oracle{o_unmet_relief:.2f}")

    o_nd = {'军饷欠':p['Due'].get('军饷',0)-o_paid['军饷'], '官俸欠':p['Due'].get('官俸',0)-o_paid['官俸'], '宗禄欠':p['Due'].get('宗禄',0)-o_paid['宗禄']}
    o_S = temp_pool
    o_rep = {}
    for c in ['军饷欠','官俸欠','宗禄欠']:
        bal = claim0[c] - o_a还.get(c,0) + o_nd[c]
        x = min(o_S, bal)
        o_rep[c] = x
        o_S -= x

    # ── 6. 独立民欠重算 ──
    o_my = claim0['民欠旧赋']
    for a in actions:
        if a['type'] in ('清欠','蠲免'):
            o_my -= min(a.get('amount',0)*(o_k if a.get('cost',0)>0 else 1.0), o_my)
    o_my += (正赋_o + 三饷) * bf  # 使用独立的正赋_o
```

---

### 四、 评审结论
1. **v19 设计规范（Spec）**：逻辑完整度已经极高，水密性闭环非常漂亮，水费/欠饷全序、折月/分池顺序以及 0-cost 预算扣减的时序逻辑无历史/玩法冲突。
2. **Spike 实现**：当前 `spike_v19.py` 内部因为部分 oracle 读了被污染的局部变量和运行时变量，存在自循环对账漏洞，未能百分百达到「从开账+输入参数独立重跑」的无漏洞口径。
3. **收敛建议**：在将 Spike 移植（port）至正式 `ming_sim` pytest 引擎前，**引入上述修复代码**。完成该补丁后，即可宣布该省级财政基座完全实现「无死角覆盖自变异测试」，可以直接启动 port 流程。