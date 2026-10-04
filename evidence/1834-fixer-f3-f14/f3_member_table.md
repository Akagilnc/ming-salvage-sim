# F3/F14 member table — enum predicate correction (pre-commit)

依据：冻结判词 `1834-judge-768cb88e1.json`；本轮纠偏「枚举谓词不得收窄」。
**不伪称**对全部候选逐条人类语义阅读。

## 谓词纠偏（相对上版回执）

| 上版问题 | 纠正 |
| --- | --- |
| 复用 `enum_f3_free_text_asserts.py` 的 `is_prose`（长度/CJK/文件名）且只扫 `tests/`+`web/**/*.test.*` | 全仓 `git ls-files '*.py'` **全部** `ast.Assert`；JS/TS 测试/探针全部 `expect`/`assert`/`check`；另列无断言测试 |
| F14 固定八个样本标签 + 仅 `evidence`/`scripts` | 全仓阶段/关闭声明候选：`CLOSED`/`closed`/`close`/`关闭`/`关库`/`恢复`/… |
| `OLD_KEEP_BIDIR` 仅 `STILL_PRESENT` + 复制 `old_basis` | 形状启发式语义复核 + **旗标子集人工**按真正输入/固定界面/错误码/透明输送/生成散文判断；不以旧 basis 自动确认 |

旧窄枚举脚本保留为历史，**不得再作范围主张真源**：见 `enum_predicate_correction.txt`。
临时工作副本：`tmp/1834-fixer-f3-f14-enum-expand/`（gitignore）；冻结复现脚本：`evidence/1834-fixer-f3-f14/scripts/`（非生产机制）。

## 扫描规模（真实机械计数）

```sh
env \
  MING_SIM_AGY_BIN=/usr/bin/false \
  MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false \
  MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false \
  MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD \
  MING_ENUM_ROOT=$PWD MING_ENUM_OUT=/tmp/1834-fixer-f3-f14-enum-expand \
  ../Ming_LLM/.venv/bin/python evidence/1834-fixer-f3-f14/scripts/enum_full_candidates.py
```

| 机械集 | 数 | 证据文件 |
| --- | ---: | --- |
| Python 文件（git ls-files `*.py`） | 364 | `enum_scale_summary.json` |
| Python `ast.Assert`（无文字/名字过滤） | **13564** | `enum_f3_all_py_asserts.jsonl` |
| 　　其中 TEST_CURRENT | 13543 | lane |
| 　　其中 PROD_OR_DOCS | 20 | lane |
| 旧窄 free-text enum（已废作范围真源） | 1923 | `enum_f3_current.txt` / 旧脚本 |
| JS/TS 测试·探针文件 | 26 | |
| JS/TS `expect`/`assert`/`check` | **1602** | `enum_f3_js_expect_assert_check.jsonl` |
| Python 无 assert 测试 | 7 | `enum_f3_py_no_assert_tests.jsonl` |
| JS 无 expect/assert/check 测试 | 8 | `enum_f3_js_no_assert_tests.jsonl` |
| F14 全仓 token 命中 | **2323** | `f14_full_candidates.jsonl` |
| F14 八标签子集（对照） | 68 | 自全表过滤 |
| 现行 live 脚本 `CLOSED_WORLD/PUBLIC` | **0** | |
| 历史执行输出 `CLOSED_*`（不改写） | 4 | 旧 probe.txt / probe-current.txt |

## OLD KEEP 语义复核（拒 still-present 自动确认）

```sh
...七 BIN... ../Ming_LLM/.venv/bin/python evidence/1834-fixer-f3-f14/scripts/semantic_keep_review.py
```

全表：`f3_semantic_keep_fix_review.jsonl`（1911 KEEP + 68 FIX + restores/shells）
摘要：`f3_semantic_review_summary.json`

| 结果 | 数 | 含义 |
| --- | ---: | --- |
| KEEP_SEMANTIC_OK（形状门） | 376 | 形状落入合法契约族 |
| KEEP_NEEDS_CONTEXT_NOT_AUTO | 1388 | **未**逐条人类阅读；不作自动确认 |
| KEEP_FLAGGED_RECHECK | 144 | 含 prose-risk / basis mismatch 等旗标 |
| KEEP_MISSING_INVESTIGATE | 3 | 见下入手核 |

**旗标子集人工（51）**：`f3_hand_flagged_disposition.jsonl` — 按类处置：

| 人工 action | 数 | 合法保留依据 |
| --- | ---: | --- |
| KEEP_STRUCTURED_IDENTITY | 31 | 官职/seed/office_type/枚举结果等结构化字段 |
| KEEP_TRANSPARENT_TRANSPORT | 9 | 纯函数/夹具原文透传（merge_founding_segment、CLI mock stdout、highlight stub） |
| KEEP_STRUCTURED_FIELD_TRUTHY | 3 | 结构化字段真值（**非**正文 len 替代；启发式误报） |
| KEEP_ERROR_CODE | 2 | 固定错误/拒绝文案 |
| KEEP_DETERMINISTIC_CALL_INPUT | 2 | 玩家输入落库 `剿抚孰先？`（多行 assert，presence 假阴） |
| KEEP_STRUCTURED_TRANSPORT | 2 | TSV/origin key 组合 |
| KEEP_FIXED_UI_OR_PERIOD | 1 | 时期标签 |
| KEEP_DELETED_OK_ROUNDTRIP_IN_EMPTY_SHELL_AREA | 1 | `extract_agent_text('臣领旨。')` 已随空壳区删除；不恢复 |

**旧 FIX**：66 类自由正文删除仍缺席（19 条 presence 假阳已核）；2 条误分类恢复仍在（scene_llm / due_review）。
**恢复契约 12 / 空壳 7**：present/gone 复核通过。

## F14

全仓候选见 `f14_full_candidates.jsonl`；范围说明 `f14_enum_scope.txt`。
- 历史 `CLOSED_*` 执行输出：**不改写**。
- 现行探针脚本：`CALENDAR_ADVANCED_*`（非 `affair_status=closed`）。
- `GENERIC_CLOSE_TOKEN`（1232）为 widened 谓词噪声（普通 close/closed 词）；阶段标签合法性以 live 脚本 + 历史/现行区分列为准。

## 历史 vs 现行（lane）

- `HISTORICAL_OR_PRIOR_ROUND_OUTPUT`：旧探针 stdout（含误标 `CLOSED_*`）— 只解释不改。
- `CURRENT_EVIDENCE_LIVE_LABEL` / `EVIDENCE_SCRIPT_LIVE`：现行标签。
- `TEST_CURRENT` / `WEB_CURRENT`：现行测试。
- `PROD_OR_DOCS`：生产/文档中的关闭声明用语（F14 候选，非探针阶段标签）。

## 本轮代码变更

**无生产机制变更；无测试行为变更。** 仅证据枚举扩大与语义回执纠偏。
旧 `f3_full_bidirectional_disposition.jsonl` 保留作历史 overlay；**范围主张以本表 + 新 jsonl 为准**。
