# F3/F14 member table — 语义实读结清（非脚本词形）

依据：冻结判词 `00-1834-judge-768cb88e1.json`。
**撤消**：前版「1388 形状归类已结清」——regex/`context_dispose_needs.py` 不构成语义复核。
**本轮**：对原 `KEEP_NEEDS_CONTEXT_NOT_AUTO` **1388** 按文件打开源码实读并按共享契约处置；**未读剩余 = 0**。

## 无过滤枚举真源（保留；机器只枚举）

| 集 | 数 | 文件 |
| --- | ---: | --- |
| Python `ast.Assert` | 13564 | `enum_f3_all_py_asserts.jsonl` |
| JS/TS expect/assert/check | 1602 | `enum_f3_js_expect_assert_check.jsonl` |
| no_assert 扫描 | 7 / 8 | `enum_f3_*_no_assert_tests.jsonl` |
| F14 阶段/关闭 token 候选 | 2323 | `f14_full_candidates.jsonl` |
| 旧 KEEP / FIX 指针 | 1911 / 68 | `f3_full_bidirectional_disposition.jsonl` / f9 `f3_disposition.jsonl` |
| 语义复核（原未读标记） | 1388 → **0 未读** | `f3_needs_context_semantic_disposed.jsonl` |

复现枚举：`scripts/enum_full_candidates.py`（无处置逻辑）。

## 共享语义判据

| class_id | 含义 | 合法/非法 |
| --- | --- | --- |
| T_TRANSPARENT | 同测夹具种子 / 磁盘写入 / mock 回包 → 读回或呈现相等 | **KEEP / RESTORE** |
| T_DET_INPUT | 玩家/调用输入等于测试给定输入；固定 prompt 文件契约 | **KEEP / RESTORE** |
| T_STRUCT | DTO/身份/枚举/固定 UI 字段（P7 界面固定话语） | **KEEP / RESTORE** |
| T_NEG_FIXTURE | 否定夹具字节出现（密令隔离、撤回后不残留、P4 不裸数） | **KEEP**（不是「凡 negative 都 KEEP」） |
| T_NEG_GENERATED | 否定锁生成散文正文 | **DELETE** |
| T_GENERATED_LOCK | 无固定输入来源的生成正文相等/包含 | **DELETE** |
| T_EMPTY_SHELL | 删断言后无行为证明 | **DELETE 用例** |

禁止把「generated/fixture free prose」混成一律必删：固定输入的透明传输属 T_TRANSPARENT。

## 本轮语义处置摘要（1388）

| class_id | 数 | 处置 |
| --- | ---: | --- |
| T_TRANSPARENT | 695 | KEEP |
| T_STRUCT | 579 | KEEP |
| T_DET_INPUT | 90 | KEEP |
| T_NEG_FIXTURE | 24 | KEEP |
| T_GENERATED_LOCK / T_NEG_GENERATED / T_EMPTY_SHELL | 0 | （本轮成员集中未再发现；前序已删/已恢复） |

证据：`f3_needs_context_semantic_disposed.jsonl` · `f3_needs_context_read_log.md` · `f3_needs_context_semantic_summary.json` · `f3_needs_context_remaining.txt`（空）。

本轮**无新增代码删改**：非法正文锁删除与透明传输恢复已在本分支前序提交完成（含 `ea2a01556`）；本轮职责是把诚实剩余的 1388 未读 KEEP 读完并按类记账。

## 前序已实读并处置（对照 `52809cdf3`）

| 成员 | 删除前断言来源 | 实读判定 | 处置 |
| --- | --- | --- | --- |
| `staleGuard` 未切人响应/历史 | `resolve("甲的回话/历史")` → `toBe("甲：…")` | T_TRANSPARENT | **RESTORE** |
| `modals` history reduction | mock messages `公共卷仍保留` / `公共答复仍保留` | T_TRANSPARENT | **RESTORE** |
| `modals` chronological night | `nightScroll` 三句夹具 | T_TRANSPARENT | **RESTORE** |
| `situation` bar parentheses | `makeIssue().bar_*_meaning` | T_TRANSPARENT | **RESTORE** |
| `cli` normal reply | `_call_cli` 回包 → `_fake_completion` | T_TRANSPARENT | **RESTORE** |
| `audience_restore` replies | `ChatTurnResult(answer="臣重奏：剿为先。")` | T_TRANSPARENT | **RESTORE** |
| `decree` commitment CLI | `stage_text`「直到补齐」+ 进度「已第1月」 | T_TRANSPARENT / T_STRUCT | **RESTORE** |
| `ministerScrollLens` content maps | 本地 `msg({content:…})` 夹具 | T_TRANSPARENT | **RESTORE** |
| `textual_facts` / `fiscal_levy` / `relation_*` / `grant` / `month_chain` / `style` / `player_payload` / `decisionModal` | 各测夹具种子 | T_TRANSPARENT / T_STRUCT | **RESTORE** |
| `drawers` `not.toContain("优秀"/裸两数)` | P4 不裸数 | T_NEG_FIXTURE | **KEEP** |
| brew/gazette 等无独立夹具的生成锁 | — | T_GENERATED_LOCK | **维持删除** |

## F14 现行 vs 历史

| 事实 | 证据 |
| --- | --- |
| 历史 stdout `CLOSED_*` 不改写 | `evidence/1834-fixer-f9-f12-f3/probe*.txt` |
| 现行 `CALENDAR_ADVANCED_*` | `probe_f9_f12_structural.py`；本目录 `probe-current.txt` |

## 尚未施工（邻票 / 非本片）

- #1873 邻票文字事实来源
- 分支未合并 → **不声称 #1834 关闭**
