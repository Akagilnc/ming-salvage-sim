# r16 · agy(holistic v16)

I will start by analyzing the current workspace to see where the files and scripts reside, specifically checking if the spike script `spike_settle_tick.py` or other files exist.
I will examine the contents of [spike_settle_tick.py](file:///tmp/ming_agy_sandbox/spike_settle_tick.py) to compare it with the code snippet provided in the prompt.
I will read the contents of [independent_auditor.py](file:///tmp/ming_agy_sandbox/independent_auditor.py) to see if it contains the independent oracle version.
I will run the existing spike script to verify its current behavior and assertions.
I will write the new v16 spike code provided in the prompt to a file [spike_v16.py](file:///tmp/ming_agy_sandbox/spike_v16.py) and execute it to verify if the independent oracle and cases G1–G13 pass.
I will run the newly written v16 spike code to verify that all the cases G1–G13 are execution-correct and pass the assertions.
I will run the mutation test script [independent_auditor.py](file:///tmp/ming_agy_sandbox/independent_auditor.py) to check which checks fail on which mutations.
I will view the relevant lines of [spike_v16.py](file:///tmp/ming_agy_sandbox/spike_v16.py) to locate the exact target content for the replacement.
I will modify [spike_v16.py](file:///tmp/ming_agy_sandbox/spike_v16.py) to replace the runtime-dependent `o_pool = 省内可支` with a completely independent oracle calculation that traces starting states, actions, parameters, and taxes. This removes the "sonnet residue" vulnerability where a debt leak could go undetected if the C-account audit was disabled.
I will execute the modified spike code to ensure all G1–G13 test cases still pass under the fully independent `o_pool` oracle.
I will inspect the mutation test suite file [mutation_test_suite.py](file:///tmp/ming_agy_sandbox/mutation_test_suite.py) to see if there are other rules or edge cases that we should be aware of.
整体评审意见如下：

---

### 一、 v16 草表设计与语义评审（账户、机制、史实与玩法）

#### 1. 账户模型与“三道漏”的自洽性
* **优秀的守恒闭环**：使用 `C_eff损耗` 接收 transfer 的效率流失，使用 `C_漂没` 接收起运流失，使用 `C_中饱` 接收拨付扣减。这种将“损耗/贪墨”全部存入特定灰色账户的设计，在数学上完美维护了 $CASH$ 守恒（没有钱凭空消失），同时也为 LLM 裁判留下了极佳的度量指标——LLM 能够一眼看出本月贪官又肥了多少（`C_中饱` 增量），从而触发政治弹劾或官吏怠工。
* **起运（Qiyun）绝对优先的悲剧张力**：
  $$\text{起运池} = \min(\text{实征}, \text{起运定额})$$
  $$\text{省内池} = \max(0, \text{实征} - \text{起运池})$$
  这是极具历史厚重感且极佳的规则设计。朝廷的起运定额是刚性的，一旦遭遇大旱，实征骤减，首先被扣减至 $0$ 的就是省内截留（存留）。这会导致省内可支变成 $0$，兵饷发不出，直接触发李自成式的裁递变兵。这种“越保京城，地方越反”的死亡螺旋是崇祯朝悲剧张力的核心体现。

#### 2. 史实合理性（明末陕西背景）
* **宗禄（Prince Stipends）的吸血效应**：明末陕西藩王宗室林立（如西安的秦王、平凉的韩王等），宗禄开支庞大。设计中将宗禄排在官俸之后，属于 $1\text{军饷} > 2\text{官俸} > 3\text{宗禄} > 4\text{赈济}$ 的阶梯，极符合历史事实。即使省内有钱，也必须优先发兵饷和官僚俸禄，藩王往往只能拖欠（积欠 `宗禄欠`）。
* **火耗（Meltage Surcharge）的潜规则定位**：明代的火耗属于非正式税收（清代雍正朝才正式“火耗归公”），在 v16 中火耗不进省库，而是流入 `C_地方截留`（地方官绅的灰色小金库）。皇帝想用这笔钱，必须通过“挪借火耗”动作强制划拨，并承受行政阻力和效率损耗（`eff < 1`）。这非常真实，折射出中央与地方官僚集团的利益拉锯。

#### 3. 玩法与 LLM 裁判的结合
* **“前承诺锁定”导致的政策排挤（k-scaling）**：
  在阶段 ⓪，$\Sigma\text{Cost}$ 包含了所有 action 的名义成本。如果玩家发起了一个根据实际情况会被 clamp 的动作（例如，军饷仅欠 5 万两，但玩家下旨拨款 30 万两“补饷”），在阶段 ⓪ 依然会以 30 万两去争夺 $\Sigma\text{Cost}$ 的分母，导致其他行政动作的力度系数 $k$ 被整体拉低。
  * *史实/玩法解释*：这非常像明末的“预算锁死/官僚冗余”，资金一旦被某道圣旨锁死，即使最后没花完，其他部门也因为名义预算不足而停摆。
  * *LLM 结合点*：LLM 应当把这种 $k < 1$ 但最终省库却有盈余的怪相，翻译为“圣旨交架、官僚推诿、朝令夕改造成的行政效能打折”。
* **0-Cost 动作的作弊空间与 LLM 软判罚的对冲**：
  在引擎中，`蠲免`（免债）和 `清欠`（追赃/强征）属于 $0\text{-cost}$ 动作，不受 $k$ 的限制（即省库为 $0$ 时仍能以 $100\%$ 的 amount 执行）。
  * *作弊空间*：如果纯从数值角度看，玩家可以无限刷“清欠”动作强征民欠旧赋来凭空造钱。
  * *悲剧铁律对冲*：由于有“LLM 裁判”进行软判罚，强征会带来巨大的民愤。LLM 应当被明确告知：**“若清欠 amount 过大，或在灾年执行清欠，应直接判定民变爆发、叛军攻城。”** 这使得“不防作弊”在机制上被剧情张力完全化解。

---

### 二、 Spike 代码与 Spec 缺陷挑刺（可执行验证）

在分析 spike 代码并针对 G1–G13 进行变异测试时，我们发现了以下几个需要防范的“咬人”地方与 Spec 盲区：

#### 1. 独立 Oracle 对账的“期望值同源性残留”（Sonnet 遗留漏洞）- **已定位并修复**
* **问题**：在 v16 原始 spike 中，债务重算 oracle 的期初可用资金 `o_pool` 直接读取了结算运行时的中间量 `省内可支`：
  ```python
  o_pool = 省内可支  # 读取了运行时中间状态！
  ```
  如果 settlement 在计算 `省内池`、`起运池` 或 Action 阶段的 `省库库银` 扣减时出现 bug（例如，多扣了钱或者公式写错），这个污染会同步传导给 `o_pool`，导致独立 oracle 算出的预期债务与被污染的运行时状态一致，从而**漏过债务对账的校验**。
* **修复验证**：我们对 `spike_v16.py` 进行了升级，彻底移除了这一残留。现在 `o_pool` 的预期值完全从期初快照 $st$ 、参数 $p$ 和原始动作 $actions$ 的逻辑链独立重跑（代码已写入并全 PASS）。请在后续移植正式引擎时，确保采用此纯净版 Oracle 逻辑。

#### 2. Modifier 的持久化与 $k=0$ 时的衰减停工规约（Spec 盲区）
* **问题**：Spike 将 recurring 营建的动作成本由测试调用方在每一 tick 手动传入。但在实际引擎中，`recurring` 动作会被序列化为持久态 Modifier 存入 $st$。
* **潜在 Trap**：
  * 当省库没钱时（`Stock_start = 0` 导致 $k=0$ ），如果某个 recurring 动作是“维持精锐营防”，且本 tick 被 scaled 到了 $0$ 成本。
  * **Spec 需要锁定的语义**：该 recurring 状态是自动挂起（Suspended）、永久消失（Destroyed），还是在本 tick **不扣钱但强制累积为新的债务（如欠饷）**？
  * **建议规约**：普通工程营建在 $k=0$ 时自动“挂起，进度为 0”；而军事/俸禄类 recurring 必须由引擎强制转化为 `Due` 负债流入阶段 ⑪，否则无法体现“停饷即叛”的危机。

#### 3. 0-Cost 动作与极小微量 $cost$ 的不连续跳变（数值断层）
* **问题**：Spike 规定 `has_cost = a.get('cost',0) > 0`。
  * 若 action $A$ 的 $cost = 0$，其 amount 执行率为 $1.0$；
  * 若 action $A$ 的 $cost = 0.0001$，一旦省库没钱（$k=0$），其 amount 执行率直接跳变为 $0.0$。
* **防坑指南**：在正式引擎中，务必对 action schema 强制分类：要么是纯政策性（无现金成本，如 `蠲免`），在 schema 中明确声明 `cost` 不可定义；要么是行政性（有现金成本），在入参校验时强制 `cost >= 0.01`。防止因浮点数微小值导致 action 在 $100\%$ 和 $0\%$ 之间发生不连续的突变。

---

### 三、 评审结论

1. **挑刺结论**：**设计模型高度自洽，史实高度合理，完美服务于“LLM 裁判 + 刚性账本”的末世模拟张力。**
2. **Spike 状态**：G1-G13 **全 PASS**。我们已将 `o_pool` 对运行时的依赖彻底剥离，实现了纯净的独立 Oracle 校验（已在 [spike_v16.py](file:///tmp/ming_agy_sandbox/spike_v16.py) 中运行通过，可作为后续 `ming_sim` 真引擎的 Golden Test 种子）。
3. **收敛建议**：此版省级财政基座已完成全部对账闭环锤炼，**可以收敛并启动向真引擎的移植**。移植时请注意补全 recurring modifier 的持久化挂起/欠账规约。