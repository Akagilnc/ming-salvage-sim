# #1834 修内司回执：F3 / F14（提交前枚举谓词纠偏）

依据：fix-packet + 冻结判词 `00-1834-judge-768cb88e1.json`（vault: `1834-judge-768cb88e1.json`）；全局 #13 / 质量法；P7 射程。
禁止 amend/rewrite/push/PR/stash。**未合并，不声称关票。**

## 本提交相对上版回执的纠偏

上版虽写「全仓双向」，但机械枚举仍复用 `enum_f3_free_text_asserts.py`：
1. **`is_prose` 按长度/CJK/文件名过滤**，且只扫 `tests/` + `web/**/*.test.*` → **违背「用户谓词不得收窄」**；
2. **F14 固定八个样本标签**且限 `evidence`/`scripts` → 同样收窄；
3. **`OLD_KEEP_BIDIR` 仅 `STILL_PRESENT` + 复制 `old_basis`** → 不足语义核查。

本提交：**不改正生产类、不新增平行生产机制**；临时脚本工作副本在 `tmp/1834-fixer-f3-f14-enum-expand/`（gitignore）；冻结复现脚本在 `evidence/1834-fixer-f3-f14/scripts/`；冻结成员输出在 `evidence/1834-fixer-f3-f14/`。**不改写历史执行输出。**

## 未结两类（判词边界）

1. **F3**：正文断言清理误删合法契约，并留下无效测试。须全仓机械枚举现存同类，并对照旧 disposition KEEP/FIX 双向复查。
2. **F14**：探针阶段标签冒称事务已关闭。纠正现行脚本标签与证据解释；不改写历史执行输出。

## 互联网现成方式（动手前）

pytest assert / bytes 相等：确定性夹具用 `assert actual == expected`；无断言空测不算测试。优先恢复/删除既有契约，不新造平行机制。

## F3 扩大后的机械候选（真源）

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

| 机械集 | 成员数 | 证据 |
| --- | ---: | --- |
| Python `ast.Assert`（git ls-files，**无**文字/名字过滤） | **13564** | `enum_f3_all_py_asserts.jsonl` |
| 旧窄 free-text enum（废作范围真源） | 1923 | `enum_f3_current.txt` + `enum_predicate_correction.txt` |
| JS/TS expect/assert/check（测试/探针） | **1602** | `enum_f3_js_expect_assert_check.jsonl` |
| Python 无 assert 测试 | 7 | `enum_f3_py_no_assert_tests.jsonl` |
| JS 无断言测试 | 8 | `enum_f3_js_no_assert_tests.jsonl` |
| 旧 disposition KEEP/FIX | 1911 / 68 | 语义复核表 |
| 已恢复合法契约（仍在） | 12 | hand + file verify |
| 已删空壳（仍 gone） | 7 | hand + file verify |

**规范成员表**：`f3_member_table.md`
**规模摘要**：`enum_scale_summary.json`
**不伪称**：13564 是机器枚举规模，不是「已逐条语义阅读」。

### OLD KEEP 语义复核（拒 still-present）

```sh
...同上七 BIN... \
  ../Ming_LLM/.venv/bin/python evidence/1834-fixer-f3-f14/scripts/semantic_keep_review.py
```

| 层 | 数 | 说明 |
| --- | ---: | --- |
| 形状门 KEEP_SEMANTIC_OK | 376 | 落入调用输入/固定 UI/错误码/输送/结构字段族 |
| NEEDS_CONTEXT_NOT_AUTO | 1388 | 形状信号不足；**明确未**逐条人类确认 |
| 旗标子集人工 | 51 | `f3_hand_flagged_disposition.jsonl`：按真正输入/固定界面/错误码/透明输送/结构字段给出合法保留依据；**无**发现须再删的生成散文锁 |
| LEN 启发式命中 | 3 | 人工改判为结构化字段真值（非正文长度替代） |
| presence 假阴 | 2 | `剿抚孰先？` 多行 assert — 仍为确定性输入契约 |
| 旧 KEEP 已删 1 | 1 | `extract_agent_text('臣领旨。')` 随空壳区删除；不恢复 |

旧 FIX：自由正文删除仍成立（presence 假阳 19 已排除）；误分类恢复 2 条仍在。

**本轮无生产/测试代码修改** — 旗标人工后无需再修行为。

## F14 阶段/关闭声明（全仓扩大）

谓词含：`CLOSED`/`closed`/`close`/`关闭`/`关库`/`恢复`/`开放`/`declare_closed`/`affair_status=closed` 及八标签等 — **不限**八标签与 `evidence`/`scripts`。

| 处置 | 数 | 说明 |
| --- | ---: | --- |
| 全仓 token 命中 | **2323** | `f14_full_candidates.jsonl` |
| GENERIC_CLOSE_TOKEN | 1232 | widened 噪声（普通 close 词）；非探针阶段标签 |
| RESTORE_OR_OPEN_PROSE_MENTION | 753 | 「恢复/开放」叙述命中 |
| CLOSE_DECLARATION_OR_STATUS_QUERY | 269 | 关闭声明/affair_status 查询候选 |
| 八标签子集 | 68 | 对照用 |
| HISTORICAL_OUTPUT_UNCHANGED | 4 | 旧 probe `CLOSED_*`：**不改写** |
| live 脚本 `CLOSED_WORLD/PUBLIC` | **0** | 现行为 `CALENDAR_ADVANCED_*` |

范围说明：`f14_enum_scope.txt`。上版八标签 `f14_stage_labels.jsonl`（70）保留为历史窄扫，**不作范围真源**。

## 聚焦测试（七 BIN；非全量）

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
  ../Ming_LLM/.venv/bin/python -m pytest -q \
    tests/test_scene_llm_1836.py \
    tests/test_material_directory_1830.py \
    tests/test_due_review_621.py \
    tests/test_audience_restore_505.py \
    tests/test_cli_runner_error_typed_1299.py \
    tests/test_decree_commitment_settlement_229.py \
    -p no:cacheprovider --basetemp=/tmp/1834-fixer-f3-f14-enum-expand/pytest-focus
```

结果见 `focused-pytest.txt`（本轮复跑写入）。

Web vitest：本轮**无 web 行为改动**；不强制重跑。上版 `focused-vitest.txt` 仍为历史记录。

## 探针

`probe-current.txt`（本目录）：须见 `OPEN_*` / `CALENDAR_ADVANCED_*` / `RESTORE_*`；不得出现新的 live `CLOSED_*`。
历史 `evidence/1834-fixer-f9-f12-f3/probe*.txt` 中的 `CLOSED_*`：**不改写**。

## 复杂度 / 合法性

- 无新增来源账、摘要、模型调用、输出擦洗、生产出口、平行枚举生产机制。
- 邻票 #1873 不施工。
- 不重开已结生产类（F9/F12 等）。
- 自查二连 done。

## 剩余范围

- #1873 邻票文字事实来源缺口。
- 同进程顺序污染（前轮已记）— 另票。
- `KEEP_NEEDS_CONTEXT_NOT_AUTO` 1388：形状不足项，若台院要更深人工，另派；本回执不伪装已读。
- 分支未合并 → **不声称 #1834 关闭**。
