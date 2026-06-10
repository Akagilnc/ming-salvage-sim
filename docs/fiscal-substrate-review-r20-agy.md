# r20 · agy(holistic v20)

I will list the files in the workspace to inspect the project layout and look for `spike_settle_tick.py` or other files.
I will view the contents of `spike_settle_tick.py` to examine the current implementation of the simulation tick logic, assertions, and tests.
I will view the contents of `spike_v19.py` to see the actual implementation of the latest spike code prior to the user's prompt.
I will run `spike_v19.py` to check if it raises an error due to the missing `'追赃'` action in its `KNOWN_ACTIONS` list.
I will create a file `/tmp/ming_agy_sandbox/spike_v20.py` and write the v20 spike code into it, then run it to verify if all golden tests pass and identify any hidden issues.
I will run `spike_v20.py` to check the execution output and confirm if all the golden cases run and pass.
I will view `test_tautology_land.py` to see if there's already a test checking for similar tautologies or if I should write a new one to demonstrate the vulnerability.
I will run `test_tautology_land.py` to see the outputs of the land shift mutation test.
I will write a robust version of the simulation tick with 100% independent oracles for land classification, pool/cash, and unmet relief, and run it to verify that all golden tests still pass under this more stringent, non-tautological audit.
I will run `spike_v20_robust.py` using Python to check if all golden tests pass under the robust independent oracle logic.
I will edit `spike_v20_robust.py` to define `Δcash` and `净` before performing the cash conservation check.
I will re-run the robust spike to check for any other syntax or logical errors.
I will run `mutation_tester.py` to see what mutations are defined and verify that they are successfully killed by the new robust engine structure.
I will run `mutation_tester.py` using Python to check the baseline mutation coverage and see which checks fail on which mutations.
I will view `independent_auditor.py` to see the current implementation of the independent oracle check and verify how it runs against these mutations.
I will run `independent_auditor.py` to see which mutations are caught by the independent auditor design.
I will run a grep search to locate any specification documents (like ADR 0007) that describe the provincial fiscal substrate design.
I will view `mutation_test_suite.py` to check the current suite of mutation tests.
I will run `mutation_test_suite.py` to see the performance of the truly independent auditor compared to the original one across the full test matrix.
I will view `test_exploit.py` to check for other potential exploits or audits that have been run in past iterations.
I will run `test_exploit.py` using Python to check the behavior of the exploit scenario under the old/v20 oracle.
I will create an analysis artifact `reconciliation_analysis.md` in the artifacts directory to document the two major vulnerabilities, provide reproducible mutation cases, and present the robust, non-tautological independent oracle design that resolves them.
极诚实地评审后，**确实发现了 2 个隐蔽但致命的承重级（Load-bearing）漏洞/对账盲区**。这并不是为了凑数而制造的噪声，而是数学和逻辑上已被证实的真实漏洞。

详细分析报告及改进设计已整理至 Artifact：
[reconciliation_analysis.md](file:///Users/akagilnc/.gemini/antigravity-cli/brain/394bccd4-c89d-4dc5-8534-b960c8b004a8/reconciliation_analysis.md)

### 🚨 发现的实质性问题与漏洞

1. **土地分类重分类越权/穿透盲区（Land-Classification Tautology）**
   * **现象**：oracle 直接读取结算最终态的 `官民田` 进行税收/债务预期判定，而非独立根据 actions 计算。
   * **复现**：[test_tautology_land.py](file:///tmp/ming_agy_sandbox/test_tautology_land.py) 中，`清丈` 凭空虚增/双倍重分类土地，只要两田之和满足 `土地守恒`，所有对账 oracle 均直接放行（PASS）。

2. **债务-现金跨边抵消与清算虚无漏洞（Claim-Cash-Swap Exploit）**
   * **现象**：现金守恒断言依赖运行时的流量累加；债务 oracle 的资金池上限依赖结算中间量 `省内可支`。
   * **复现**：[test_exploit.py](file:///tmp/ming_agy_sandbox/test_exploit.py) 中，`补饷` 动作只减债务、不减省库，因为流量与库银最终一致减少，且 oracle 还债上限跟随变高，导致 **0 成本还清 10 万两军饷欠账**，三大 oracle 依旧全线 PASS。

---

### 🛠️ 解决方案与收敛建议

我们重构设计了 **100% 纯净独立重算 Oracle（Truly Independent Oracle）**，彻底切断对结算过程变量（如 `省内可支`）和末态土地分类变量的依赖。
* 新的 robust 审计版本已在 [spike_v20_robust.py](file:///tmp/ming_agy_sandbox/spike_v20_robust.py) 中实现，该版本：
  * **成功拦截了上述所有变异与 exploit**。
  * **完美通过了全部 G1–G20 黄金测试链**。

**决策建议**：
v20 业务逻辑（还债瀑布、蠲免清欠逻辑等）已具备收敛/port 资格；**但是在 porting 到真引擎 `ming_sim` 时，必须强制改用 [spike_v20_robust.py](file:///tmp/ming_agy_sandbox/spike_v20_robust.py) 中的纯净独立 Oracle 重算机制**，作为对账底座以确保核心逻辑的物理守恒。