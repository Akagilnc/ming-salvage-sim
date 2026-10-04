# #1834 修内司回执：F9 / F12 / F3（续施工·实质审查收束）

依据：fix-packet + 冻结判词 `00-1834-judge-52809cdf3.json`；现行 #1834 / #1812；ADR 0143、0155；质量法 #13。
Owner 授权：保留既有工作树并在其上完成；禁止 amend/stash/reset/checkout 覆盖/clean/push/PR。
**未合并，不声称关票。**

## 证据纠错说明（本提交）

自验发现上一版 `report.md` **全部命令**误用 `CLAUDE_CODE_SHELL_PREFIX` / `CODEX_SHELL_PREFIX` 等非 owner 要求变量；且聚焦测试用 `AFFECTED=$(git diff --name-only HEAD -- 'tests/*.py')`——**提交后工作树干净时 AFFECTED 为空，`$AFFECTED` 展开会误跑全量**。

本提交：只纠证据与报告命令，**不改测试/生产行为**。所有复验已用 owner 七变量实际跑过（非仅文字替换）。

**Owner 要求的测试安全前缀（七 BIN）**：

```text
MING_SIM_AGY_BIN=/usr/bin/false
MING_SIM_CODEX_BIN=/usr/bin/false
MING_SIM_CLAUDE_BIN=/usr/bin/false
MING_SIM_CURSOR_BIN=/usr/bin/false
MING_SIM_KIMI_BIN=/usr/bin/false
MING_SIM_GROK_BIN=/usr/bin/false
MING_SIM_PI_BIN=/usr/bin/false
```

外加 `PYTHONDONTWRITEBYTECODE=1`、`PYTHONPATH=$PWD`、解释器 `../Ming_LLM/.venv/bin/python`。

### 旧命令留痕（不符合；已更正）

上一版曾写（**不符合**测试安全前缀；勿再跑）：

```sh
# NONCOMPLIANT TRACE — wrong vars (SHELL_PREFIX*) + post-commit empty AFFECTED risk
AFFECTED=$(git diff --name-only HEAD -- 'tests/*.py' | tr '\n' ' ')
env \
  CLAUDE_CODE_SHELL_PREFIX=/usr/bin/false \
  CODEX_SHELL_PREFIX=/usr/bin/false \
  AGY_SHELL_PREFIX=/usr/bin/false \
  HERMES_SHELL_PREFIX=/usr/bin/false \
  OPENCODE_SHELL_PREFIX=/usr/bin/false \
  CURSOR_SHELL_PREFIX=/usr/bin/false \
  AIDER_SHELL_PREFIX=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=$PWD \
  ../Ming_LLM/.venv/bin/python -m pytest -q $AFFECTED
```

枚举/探针上一版同样误用上述 `*_SHELL_PREFIX` 七变量——**已更正为 `MING_SIM_*_BIN`**，见下文完整命令。

## 本轮相对前轮缺口

前轮以 `classify_f3_disposition.py` 词表/短汉字(<16)/ASCII/全体 `.not.` 自动 KEEP，再以 `FIX=0` 宣称全仓完成——**不能代表逐条语义审查**，会漏自由正文子串（短汉、note 名字、归档字段等式、非权限负向等）。

本轮：

1. 对宽豁免组做实质逐条核上下文；删漏项自由正文机械依赖（不换非空/len/哨兵）。
2. **删除**本轮自建的自动分类/自动删码：`scripts/classify_f3_disposition.py`、`scripts/apply_f3_fix_deletes.py`（已获删除授权）。
3. 留下：真实枚举脚本、结构探针、冻结已核处置表 `f3_disposition.jsonl`（一行一条，含本轮 FIX 审计）。
4. **报告不以词表 FIX=0 证明完成**；完成判据=手审删除漏项 + 冻结表 + 受影响面复验。

## 三类根因（判词）

1. **F9** 案卷解码 `payload`（含裸 `loyalty`）进公共/世界材料。
2. **F12** `list_world_effect_history` 整行 `person_logs` 等审计转储进材料。
3. **F3** 人读自由正文机械依赖（`in`/`==`/`len`/非空/`toContain`/`toBe`；含对话/CLI/Web，不整体豁免）。

## 修法

- F9/F12 生产删除：已在 `fc08d7713`（本轮复核 STRUCT + 探针）。
- F3：手审后删除漏项（酿制段正文、邸报/报告锁、composed note、对话 content 锁、定性展示负向、票拟 label 列表等）。合法保留：原样传输（`extract_agent_text` / stream out / 写入→读回 body / `merge_founding_segment` 字节契约）、结构化枚举/身份、P7 固定 UI、来源权限/隔离负向、类型化错误标识。
- `ministerScrollLens`：去掉对话 content 等式，改验 `role`/`speaker`/`chat_turn_id` 结构（非自由正文）。

## 可执行全仓枚举（已用七 BIN 复跑）

```sh
env \
  MING_SIM_AGY_BIN=/usr/bin/false \
  MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false \
  MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false \
  MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=$PWD \
  ../Ming_LLM/.venv/bin/python evidence/1834-fixer-f9-f12-f3/scripts/enum_f9_material_payload.py \
  | tee evidence/1834-fixer-f9-f12-f3/enum_f9.txt

env \
  MING_SIM_AGY_BIN=/usr/bin/false \
  MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false \
  MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false \
  MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=$PWD \
  ../Ming_LLM/.venv/bin/python evidence/1834-fixer-f9-f12-f3/scripts/enum_f12_history_dump.py \
  | tee evidence/1834-fixer-f9-f12-f3/enum_f12.txt

env \
  MING_SIM_AGY_BIN=/usr/bin/false \
  MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false \
  MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false \
  MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=$PWD \
  ../Ming_LLM/.venv/bin/python evidence/1834-fixer-f9-f12-f3/scripts/enum_f3_free_text_asserts.py \
  | tee evidence/1834-fixer-f9-f12-f3/enum_f3.txt
```

复扫：`evidence/1834-fixer-f9-f12-f3/rescan.txt`
处置真源：`f3_disposition.jsonl`（现行 KEEP 候选 + 本轮 FIX 审计行）；`f3_fix_list.txt`（本轮手删清单）。

| 轴 | 结果 |
| --- | --- |
| F9 | `dossier.items_dump=PRESENT`；skip 含 payload/stigma/execution_signal；HIT=70 |
| F12 | audit dump loop=ABSENT；keeps=实况轨,issues,characters,relation_edge_events；HIT=142 |
| F3 | MATERIAL_BODY_POSITIVE=0；现行枚举 HIT=1911 KEEP；本轮手删 FIX 审计=68（非词表自动归零） |

## F3 处置（手审；无「词表完成」声称）

### FIX（本轮手删；见 `f3_fix_list.txt` / jsonl 中 `decision=FIX`）

含：关系酿制 `recent_segment`/`founding_segment` 字面锁、残留 textual_facts body 列表、请旨 `presented_context`、composed grant note（应解/实抵）、邸报/SSE report 字面、thinking/reasoning dump 自由子串、edge/criterion/context/summary 自由锁、Web 对话 content 等式与非权限对话负向、票拟 option label 列表、定性军牌文案负向等。删除方式=整条 Assert/expect，**不**换成非空/len/哨兵/测试专用生产出口。`ministerScrollLens` 以 role/speaker 结构断言承接过滤契约。

### KEEP（现行 1911；依据见 jsonl `basis`）

合法类：结构化枚举/身份、原样传输契约、P7 固定 UI、来源权限/隔离负向、类型化错误/技术诊断、材料路径成员、结构化存在性。归档字段等式仅在确有写入→读回/字节合并等真实契约时保留。

## 结构探针（非 pytest；三条全跑）

脚本：`evidence/1834-fixer-f9-f12-f3/scripts/probe_f9_f12_structural.py`

**上一版只保存了 `current`（见旧 `probe.txt`），遗漏 `--old` / `--old-f12`——本轮补回并分文件存证。**

| 运行 | 证据文件 | 结果 |
| --- | --- | --- |
| current | `probe-current.txt` | ALL_GREEN（各态 files=279）；exit 0 |
| `--old` | `probe-old.txt` | OLD_LOGIC_RED：machine keys `payload`/`stigma`/`execution_signal` 进材料；exit 2 |
| `--old-f12` | `probe-old-f12.txt` | F12_OLD_LOGIC_RED：`list_world_effect_history` dumps `person_logs`；exit 2 |

完整命令：

```sh
env \
  MING_SIM_AGY_BIN=/usr/bin/false \
  MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false \
  MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false \
  MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=$PWD \
  ../Ming_LLM/.venv/bin/python evidence/1834-fixer-f9-f12-f3/scripts/probe_f9_f12_structural.py
# → tee probe-current.txt

env \
  MING_SIM_AGY_BIN=/usr/bin/false \
  MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false \
  MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false \
  MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=$PWD \
  ../Ming_LLM/.venv/bin/python evidence/1834-fixer-f9-f12-f3/scripts/probe_f9_f12_structural.py --old
# → tee probe-old.txt

env \
  MING_SIM_AGY_BIN=/usr/bin/false \
  MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false \
  MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false \
  MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=$PWD \
  ../Ming_LLM/.venv/bin/python evidence/1834-fixer-f9-f12-f3/scripts/probe_f9_f12_structural.py --old-f12
# → tee probe-old-f12.txt
```

## 聚焦测试（完整可复现；固定 SHA，防空 AFFECTED）

**必须用固定区间** `89468d498..7ab5e8dea`，**不可** `git diff --name-only HEAD`（提交后为空会误跑全量）。先检查非空再跑：

```sh
AFFECTED=$(git diff --name-only 89468d498 7ab5e8dea -- 'tests/*.py')
# 本轮 COUNT=19；若为空必须 ABORT，禁止 pytest 无参
test -n "$AFFECTED" || { echo ABORT_EMPTY_AFFECTED; exit 1; }

env \
  MING_SIM_AGY_BIN=/usr/bin/false \
  MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false \
  MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false \
  MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=$PWD \
  ../Ming_LLM/.venv/bin/python -m pytest -q $AFFECTED
```

本轮实际 A 文件（19；`focused-files.txt`）：

```
tests/test_audience_translation_1838.py
tests/test_cli_backend.py
tests/test_deepseek_thinking_disable_1797.py
tests/test_due_review_621.py
tests/test_fiscal_levy_effect.py
tests/test_grant_reconciliation_567.py
tests/test_month_chain_1843.py
tests/test_month_chain_1847.py
tests/test_person_delta_adapter.py
tests/test_pihong_dossier_1490.py
tests/test_player_payload_1022.py
tests/test_qa_b3_409_ux.py
tests/test_qa_s2_copy_prompts_1356_1402.py
tests/test_relation_brew_636.py
tests/test_relation_read_640.py
tests/test_relation_seed_638.py
tests/test_scene_llm_1836.py
tests/test_style_temperament_641.py
tests/test_textual_facts_1828.py
```

结果（`focused-pytest.txt`）：**551 passed, 1 skipped**，real **50.92s**。未跑全量。

Web vitest（触及 `web/src/ministerScrollLens.test.ts` 等）：本机无 `web/node_modules`，未跑（`focused-vitest.txt`）。

### 同进程顺序污染（保留失败证据；不洗白）

```sh
env \
  MING_SIM_AGY_BIN=/usr/bin/false \
  MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false \
  MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false \
  MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=$PWD \
  ../Ming_LLM/.venv/bin/python -m pytest -q \
    tests/test_month_chain_1847.py::test_decree_continuation_keeps_forecast_and_lands_affair_effect \
    tests/test_breach_plea_623.py::test_revoke_forecast_translation_input_carries_original_and_continuing_dossier
```

实测（`pollution-pair.txt`）：**1 failed, 1 passed**（后者 `KeyError: 'request'`）。分进程各 **1 passed**。非本轮 F3 删文引入；**不洗白**。

## 复杂度 / 合法性

- 无新增来源账/摘要/模型调用/输出擦洗/生产出口。
- 邻票 **#1873** 不施工。
- 本提交仅证据/报告纠错，未改测试或生产代码。
- 自查二连 done。

## 剩余范围（仅授权外）

- **#1873** 邻票。
- 同进程顺序污染（上节）——另票/另修。
- Web vitest 需本机 `web/node_modules`。
- 分支未合并 → **不声称 #1834 关闭**。
- HEAD SHA：见本纠错提交后 `git rev-parse HEAD`。
