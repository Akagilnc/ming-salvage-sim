# 探针 driver 复用引擎结算核，不自行复刻结算脊柱

Status: accepted

探针 step1 由对话里的 LLM（我）自产邸报叙事 + 稀疏 delta，需要**绕过引擎自带的 extractor** 跑确定性结算。`ming_sim/decree.py` 的结算脊柱夹着两个 LLM 步分两段：前括号（`resolve_directives` 头：固定财政 tick → `auto_trigger_seed_issues`）和后括号（`_settle_after_narrative` 尾：`apply_score_extraction` → turn_logs → 章节记忆 → inertia → `clear_gated_legacies` → 结局判定 → `next_period`）。

我们决定：**从 decree.py 抽出可复用的纯确定性结算核**（`pre_settle` + `settle_with_delta(state, db, extracted, …)`），真实游戏流程（extractor 产出 delta 后调）和探针 `driver.py`（注入自产 delta）**共用同一段代码结算**；driver 不另写一套脊柱。

## Considered Options

- **driver 自行复刻脊柱**（CLAUDE.md 原"driver 照此复刻 SETTLEMENT_FLOW"）：隔离、对现有路径零风险，但**两套结算脊柱会漂移**——与本项目一路在治的"DB↔叙事漂移 / 静默不一致"同源病。**否决**。
- **薄包装 `_settle_after_narrative`**：该函数内部会调 extractor LLM 从邸报抽 delta，driver 调它等于重跑 extractor、丢掉"我自产 delta"的意义。**不可行**。
- **抽出确定性核、双方复用**：一次 behavior-preserving 重构（decree.py 是 codex 安全区，channel 分支未动它），单一真相源、零漂移，并给 issue #13/#4 一个干净的 TDD 测试缝（`settle_with_delta(自产delta)` 后断言 DB）。**采纳**。

## Consequences

- decree.py 做行为不变的 extract-method：真实流程改成 `pre_settle → simulator → extractor → settle_with_delta`。
- 前半段再抽共享 `prepare_resolve_front_half`（pre_settle + ready=0 占位，含 transit_arrivals handoff）；引擎 `resolve_directives` 与探针 driver 同 seam（#668）。
- `driver.py` 显式两阶段 CLI/Python：`prepare` → `[我产叙事+delta]` → `settle --delta` → `dump`（另保留 `state`）。禁止一站式「先收 narrative 再首次跑前半段」；未 prepare 的 settle 响亮失败。
- **CLAUDE.md「结算编排骨架」里"driver 照此复刻"一句作废**，改述为"driver 复用 `settle_with_delta`，与真实流程同核"。实现时同步改 CLAUDE.md / SETTLEMENT_FLOW.md。
- 结算脊柱从此只有一份；探针不会和生产结算悄悄分叉。
- 先做这条（抽核 + driver），#4 城防炮即可经此核 TDD 验证，确立实现顺序。
