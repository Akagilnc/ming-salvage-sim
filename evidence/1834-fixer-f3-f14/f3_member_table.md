# F3/F14 member table — 实读批次（非脚本词形）

依据：冻结判词 `1834-judge-768cb88e1.json`。
**撤消**：前版「1388 形状归类已结清」——regex/`context_dispose_needs.py` 不构成语义复核。

## 无过滤枚举真源（保留；机器只枚举）

| 集 | 数 | 文件 |
| --- | ---: | --- |
| Python `ast.Assert` | 13564 | `enum_f3_all_py_asserts.jsonl` |
| JS/TS expect/assert/check | 1602 | `enum_f3_js_expect_assert_check.jsonl` |
| no_assert 扫描 | 7 / 8 | `enum_f3_*_no_assert_tests.jsonl` |
| F14 阶段/关闭 token 候选 | 2323 | `f14_full_candidates.jsonl` |
| 旧 KEEP / FIX 指针 | 1911 / 68 | `f3_full_bidirectional_disposition.jsonl` / f9 `f3_disposition.jsonl` |
| 语义复核未读标记 | 1388 | `f3_semantic_keep_fix_review.jsonl` 中 `KEEP_NEEDS_CONTEXT_NOT_AUTO`（**状态=待实读，非已结清**） |

复现枚举：`scripts/enum_full_candidates.py`（无处置逻辑）。

## 共享语义判据（仅用于已实读成员）

| class_id | 含义 | 合法/非法 |
| --- | --- | --- |
| T_TRANSPARENT | 同测夹具种子 / 磁盘写入 / mock 回包 → 读回或呈现相等 | **KEEP / RESTORE** |
| T_DET_INPUT | 玩家/调用输入等于测试给定输入 | **KEEP / RESTORE** |
| T_STRUCT | DTO/身份/枚举/固定 UI 字段（P7 界面固定话语） | **KEEP / RESTORE** |
| T_NEG_FIXTURE | 否定夹具字节出现（密令隔离、撤回后不残留、P4 不裸数） | **KEEP**（不是「凡 negative 都 KEEP」） |
| T_NEG_GENERATED | 否定锁生成散文正文 | **DELETE**（与正向生成锁同非法） |
| T_GENERATED_LOCK | 无固定输入来源的生成正文相等/包含 | **DELETE** |
| T_EMPTY_SHELL | 删断言后无行为证明 | **DELETE 用例** |

禁止把「generated/fixture free prose」混成一律必删：固定输入的透明传输属 T_TRANSPARENT。

## 本轮删除成员来源 — 实读结果

对照 `52809cdf3` 删除前原文与夹具种子。

| 成员 | 删除前断言来源 | 实读判定 | 处置 |
| --- | --- | --- | --- |
| `staleGuard` 未切人响应/历史 | `resolve("甲的回话/历史")` → `toBe("甲：…")` | T_TRANSPARENT | **RESTORE** |
| `modals` history reduction | mock messages `公共卷仍保留` / `公共答复仍保留` | T_TRANSPARENT | **RESTORE** |
| `modals` chronological night | `nightScroll` 三句夹具 | T_TRANSPARENT | **RESTORE** |
| `situation` bar parentheses | `makeIssue().bar_*_meaning` | T_TRANSPARENT | **RESTORE** |
| `cli` normal reply | `_call_cli` 回包 → `_fake_completion` | T_TRANSPARENT | **RESTORE** |
| `audience_restore` replies | `ChatTurnResult(answer="臣重奏：剿为先。")` | T_TRANSPARENT | **RESTORE**（曾误留长度替代后删） |
| `decree` commitment CLI | `stage_text`「直到补齐」+ 进度「已第1月」 | T_TRANSPARENT / T_STRUCT | **RESTORE** |
| `ministerScrollLens` 全文件 content maps | 本地 `msg({content:…})` 夹具 | T_TRANSPARENT；negative 为 T_NEG_FIXTURE | **RESTORE**（撤 rolesSpeakers 结构替代） |
| `textual_facts` army/region/affair bodies | `append(body=…)` 回读 | T_TRANSPARENT | **RESTORE** |
| `fiscal_levy` presented_context / 请旨文 | 事件 context 种子 + HITL note | T_TRANSPARENT | **RESTORE** |
| `relation_brew` founding/recent | `brew_fn.outputs` / edge context | T_TRANSPARENT | **RESTORE** |
| `relation_read` prior contexts | `record_relation_edge_event(context=…)` | T_TRANSPARENT | **RESTORE** |
| `grant_reconciliation` note 应解/实抵 | execution note 夹具 + 确定性数字 | T_TRANSPARENT | **RESTORE** |
| `month_chain` recon note / 参劾 memorial | supply 夹具 | T_TRANSPARENT | **RESTORE** |
| `style_temperament` payload_summary | reason 夹具 | T_TRANSPARENT | **RESTORE** |
| `player_payload` decree/report/decisions | `_SettlementSession` 夹具 | T_TRANSPARENT | **RESTORE** |
| `decisionModal` 关宁/河工/拟批 | `decisions` 常量夹具 | T_TRANSPARENT / T_STRUCT | **RESTORE** |
| `due_review` origin/criterion | stages 夹具 | T_STRUCT | 上版已 RESTORE，本座复核仍 KEEP |
| `material_directory` / `scene_llm` 输入 | 磁盘字节 / `calls` 玩家输入 | T_TRANSPARENT / T_DET_INPUT | 上版已 RESTORE，复核 KEEP |
| `modals` thinking 身份 / periodLabel | 固定身份与月份字段 | T_STRUCT | 上版已 RESTORE，复核 KEEP |
| `drawers` `not.toContain("优秀"/裸两数)` | P4 不裸数；props 夹具 | T_NEG_FIXTURE | **KEEP**（非生成散文锁） |
| brew/gazette 等无独立夹具的生成锁（旧 FIX 中 brew 以外已删且确无种子） | — | T_GENERATED_LOCK | **维持删除**（本座未恢复） |

## 已实读 KEEP 样本（透明传输，非词形）

| 指针 | 输入来源 | 输出契约 | 判定 |
| --- | --- | --- | --- |
| `test_character_knowledge_489.py:479` | `record_public_knowledge_event(…, "该案已奉明发")` | `body ==` | T_TRANSPARENT KEEP |
| `test_public_sayings_1829.py:58` | `record_public_saying(…, "袁崇焕已死于宁远")` | `body ==` | T_TRANSPARENT KEEP |
| `test_declaration_dispatch_1835.py:79/528` | declaration / scene body 夹具（含空白） | `body ==` 原样 | T_TRANSPARENT KEEP |
| `test_history_decree_text_1843_reopen.py:28` | `save_resolve_context(decree_text=…)` | API `decree_text ==` | T_TRANSPARENT KEEP |
| `test_fiscal_levy_effect.py:1560` | `submit_hitl_choices(note=…)` | `emperor_note ==` | T_TRANSPARENT KEEP |

## 尚未实读范围（诚实剩余）

- `KEEP_NEEDS_CONTEXT_NOT_AUTO` 中除上表与本局已打开文件外的路径：**仍待逐文件实读**，不得声称 1388 结清。
- F14：`f14_full_candidates.jsonl` 全量候选保留；现行探针标签纠正与历史 stdout 不改写已成立；**不对 2323 声称语义结清**。

## F14 现行 vs 历史

| 事实 | 证据 |
| --- | --- |
| 历史 stdout `CLOSED_*` 不改写 | `evidence/1834-fixer-f9-f12-f3/probe*.txt` |
| 现行 `CALENDAR_ADVANCED_*` | `probe_f9_f12_structural.py`；本目录 `probe-current.txt` |
