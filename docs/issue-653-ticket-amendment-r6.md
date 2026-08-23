# #653 票面修正案 r6（2026-08-22 票庭 r6，run 01a02d61-71b0…@judge fix_now 两单）

> 本文件为 GitHub issue #653 庭裁修正案 r6 的仓内审计副本（apply 腿 run 结算载体）。票面正文以 https://github.com/Akagilnc/ming-salvage-sim/issues/653 为准。均为票面文本级修复、零范围变更；本节修订 r1 案 F3.1/F3.2 相应措辞并显式废止 F1.6 一残留短语。

## 庭裁修正案 r6（2026-08-22 票庭 r6，run 01a02d61-71b0…@judge fix_now 两单，均为票面文本级修复、零范围变更；本节修订 r1 案 F3.1/F3.2 相应措辞并显式废止 F1.6 一残留短语）

**修法一（F3 extractor 计数断言过期 → 改写为相对不变式）**：#633 S2 relations extractor（commit 02ad830f）已在 r1 基线（53cd4f71）之后合入，head 上 `EXTRACTION_MODULES` 为五模块（ming_sim/simulation.py）、tests/test_parallel_extractors.py 早已用动态计数断言。r1 案 F3.1「四模块并行一字不动；禁止第 5 个 LLM 调用（验收须断言 EXTRACTION_MODULES==4…）」与 F3.2 断言①「无第 5 个调用、四 extractor」按字面不可满足且诱导破 0082 与本票 F4——现修订为：

- **F3.1 extractor 槽（r6 修订版）**：阶级 satisfaction 变动仍**只**由既有 `internal` extractor 的 `class_delta` 槽产出（`MODULE_FIELDS['internal']` 已独占 `class_delta`）；生产 `extract_scores_by_modules_with_agno(..., parallel=True)` 编排一字不动。**本片零新增 LLM 调用**：extractor 模块集合须与开工时 head **逐字一致**（验收以动态计数断言 `len(EXTRACTION_MODULES)` 与模块名集合比对，**禁硬编码任何常数**，循 #656 dynamic N+1 先例 215c685f），既有全部 extractor 仍 parallel=True。
- **F3.2 验收三断言①（r6 修订版）**：零新增 LLM 调用、extractor 模块集合与开工 head 动态计数逐字一致、既有全部 extractor 仍 parallel=True；②③原文不动。

**修法二（F1.6 残留冲突条款显式废止）**：r1 案 F1.6「省池与中央 hub 共同服从旨意」句中「全国 override 进 hub tier」一语**废止**——hub tier（京运补＋中央军饷）依 r2 双池两序**恒最先且不可 override**（0023 D9 合并 k 分母不变）；同句「0023 D9 合并 k 分母与 hub outbound 守恒不变式不动」照旧保留。F1.6 验收表无需改动（表内本无 hub override 案例）；F1.0–F1.5 及 r2–r5 全部不动。

## 庭裁修正案 r7（最新 owner 裁决：撤销财政方向票面限制）

F3.2 已按最新裁决直接改写为「LLM 综合归因与可断言边界」：`fiscal_fact_brief` 继续作为账本事实输入，但最终 `class_delta.satisfaction` 由既有 internal extractor 结合财政、事件、任免等同回合事实判断。仅含单一财政受损事实的最小盘面仍须证明事实包进入 internal extractor，但不再断言输出方向。

r1 F3.2 中以财政受损/受益强制净值方向、把方向不符视为错误并二次处理的条款，以及验收②对应断言，全部废止；冻结验收映射已同步改写。实现不得扩 `class_delta` schema，不得拆增财政/其它分量，不得新增 LLM 调用或为财政方向增加 retry/clamp。F3.1 的事实包、r6 动态 extractor 不变式及 P4 定性叙事边界保持不变。

## 庭裁修正案 r8（动态成员缺 `settle` key 口径校正）

F2① 的省级事实投影成员与 ADR 0019 一致：仅投影「明控且已有 `settle` key」的省。合法 fiscal dict 完全缺少 `settle` key（包括收复台湾/建州及 legacy 存档形状）是合法非成员，直接出列，不得阻断 simulator payload。`settle` key 已存在但值非 dict，或其 `st`/`p` 非 dict，仍属坏结构并按 ADR 0005 响亮失败；坏 fiscal JSON 与非 dict fiscal 同样响亮失败。旧契约中“缺 settle 基座必须失败”的过宽措辞废止。
