# #1847 修内司报告：N6 / N7 / N9

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- 分支：`ak-roles/1847-fixer-n6-n7-n9`（自 `ak-roles/1847-n4-n6` @ `6d042ddd9`）
- 派单：`01a0fac7-790d-75dd-a718-efb512b4d331@fixer`
- 末份最终裁定：`01-1847-judge-6d042ddd9.json`（撤回 N8 功能门槛；只送修 N6/N7/N9）
- 先前判词仍有效未撤销样本：`00-…-sealed1.json` 的 N6/N7（N8/X1/X2 按末份处置）
- **不宣称**全局功能闭环或已 merge

## 官方文档（动手前）

| 问题 | 文档 | 简单修法 |
|---|---|---|
| N7 stderr 冒充正文 | [Python subprocess](https://docs.python.org/3/library/subprocess.html)：stdout/stderr 分管；合并须显式 `stderr=STDOUT` | 正文只取 stdout；空输出走既有失败 |
| N7 Codex | [Codex non-interactive](https://learn.chatgpt.com/docs/non-interactive-mode)：progress→stderr，final→stdout | 删除 banner/`OpenAI Codex v` 切割兜底 |
| N6 trim | [MDN String.prototype.trim](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/String/trim)：trim 会去掉两端空白 | 自由文本运输不 strip/截断；判空可读 strip |

## 根因类定义（末份 + 票面，未收窄）

1. **N6 原文运输仍有删改**：适用自由文本运输接缝上的 strip/截断/裁剪。不含机械身份、枚举、形式语言、仅判空读取。
2. **N7 stderr 日志冒充模型正文**：stdout 空时用 stderr/banner 充正文，或把空输出洗成成功。
3. **N9 退役批红私有闭包**：本票删生产调用后残留的 `parse_rescript_capability_pair` / `decision_has_rescript_capability` / `bind_decisions_to_candidate_events` 及专属测试/重导出。保留现役决策解析、选项绑定、0055 负向闸与仍有生产调用的共享码。

跨票不施工：**N8**（#1873）、**X1/X2**（#1826/#1873）。

## 全仓枚举命令

```bash
# N6：自由文本条件运输的 strip / [:N]
rg -n 'resolve_condition|fail_condition|_issue_condition_text' -g'*.py' \
  | rg '\.strip\(\)|\[:\s*[0-9]+\]|_issue_condition_text'

# 更宽的赋值/kwargs 截断（改前）
python3 - <<'PY'
# 见本 run 临时目录扫描脚本：字段名 ∩ (assign strip | [:N]) 于 ming_sim/**
PY

# N7
rg -n 'OpenAI Codex v|stdout_text \+ stderr' -g'*.py'

# N9
rg -n 'parse_rescript_capability_pair|decision_has_rescript_capability|bind_decisions_to_candidate_events|RESCRIPT_CAPABILITY_DECISIONS|prepare_rescript_prewrite' -g'*.py'
```

## 候选成员分类表（改前 → 处置）

### N6

| 成员 | 分类 | 保留/修改依据 |
|---|---|---|
| `ming_sim/issues.py:_issue_condition_text` 对 str `.strip()` | **修** | 自然语言条件（seed_events 等）运输删空白；违 P6/0142 |
| `issues.py` `resolve_condition[:300]` / `fail_condition…[:300]` | **修** | 写入端截断自由文本 |
| `materials.py` `_visible_affair_lines` 对 resolve/fail `.strip()` | **修** | 供料再删空白；判词取证链 |
| `issues.py:507/517` `commitment_condition_role` / `_legacy_commitment_stop_gate` 内 `.strip()` | **保留** | 形式语言 regex 匹配前的局部规范化，不写回运输 |
| `db.py:468` stop/resolve formal fullmatch 前 `.strip()` | **保留** | 形式语言判据 |
| `issues.py` / `materials.py` `if not ….strip()` 判空后 fallback/是否出栏 | **保留（判空）** | 末份 boundary：仅作判空；不把 strip 结果当运输值 |
| 标题/职官/target_id/account 等 `.strip()` | **保留** | 机械身份 / 枚举 |
| `tlog`/`print`/`RuntimeError` 的 `[:N]` | **保留** | 诊断展示，非账本/供料运输 |
| `flows.py` population reason `.strip()` | **保留** | 枚举键匹配 |
| `issues.py:5485` close reason `.strip().lower()` | **保留** | 枚举 |
| `sanitize_sqlite_text` | **保留** | 仅 surrogate 转义，非语义裁剪 |

### N7

| 成员 | 分类 | 依据 |
|---|---|---|
| `cli_backend.py` stdout 空时 `(stdout+stderr).split("OpenAI Codex v")` | **修/删** | 日志冒充正文 |
| `test_cli_backend.py::test_run_codex_stdout_empty_fallback` | **退役改负向闸** | 原测试锁违法成功行为 |
| `test_run_runner_empty_output_is_retryable_typed` | **保留** | 现役结构化空输出失败契约 |
| agy auth 路径读 `stdout+stderr` 仅进 `provider_message` | **保留** | 失败诊断，不交正文 |
| `docs/raw/06_harness_scripts/agg.py` banner split | **保留（非生产）** | raw harness，非游戏运输 |
| 其它测试用 stderr=noise 且 stdout 非空 | **保留** | 验证 stdout 正文，非 fallback |

### N9

| 成员 | 分类 | 依据 |
|---|---|---|
| `settlement_payload.parse_rescript_capability_pair` | **删** | 无生产调用 |
| `settlement_payload.decision_has_rescript_capability` | **删** | 仅旧 bind 闭包 |
| `settlement_payload.bind_decisions_to_candidate_events` | **删** | `prepare_rescript_prewrite` 已删后无生产调用 |
| `RESCRIPT_CAPABILITY_DECISIONS` | **删** | 仅上列闭包使用 |
| `decree.py` 对该 bind 的 re-export | **删** | 旧公共面 |
| `tests/test_decision_event_binding_389.py` | **删** | 专属旧路径 |
| `test_pihong_dossier_1490.py` 顶部三则 bind/capability helper 测 | **删** | 专属旧路径；其余中旨/0055 等保留 |
| `bind_decision_options` / `parse_decision_blocks` / `_DECISION_RE` | **保留** | `month_chain` 等仍生产调用 |
| 现役 0055 / month_chain_1847 负向闸 | **保留** | 末份 boundary |

## 改后同谓词复扫

- N6 运输 strip/[:300]：**清净**；剩余仅形式语言匹配与判空 `.strip()`（上表保留行）。
- N7 生产 `OpenAI Codex v` 切割：**无**。
- N9 四符号 + `prepare_rescript_prewrite`：**NONE**。

## 逐 finding 处置

| ID | 处置 |
|---|---|
| N6（末份+sealed1） | 已修：条件运输零 strip、去 `[:300]`、供料原样；判空/形式语言保留 |
| N7（末份+sealed1） | 已修：删 stderr 兜底；非法成功测试改负向闸；保留 `llm_empty_output` |
| N9（末份） | 已删退役闭包与专属测试；未重接旧路；未补 N8 |
| N8 | **不施工**（末份撤回本票送修） |
| X1/X2 | **跨票**保持 |

## 代码改动摘要

- `issues.py`：`_issue_condition_text` 原样；写入不去 `[:300]`；fallback 用 `.strip()` 仅判空
- `materials.py`：条件字段原样；出栏判空可读 strip
- `cli_backend.py`：删 banner 兜底
- `settlement_payload.py`：删 N9 闭包（约 −126 行）
- `decree.py`：去 bind re-export
- 测试：改 N7 负向闸；删 `test_decision_event_binding_389.py`；删 pihong 旧 helper 三测

生产净量（本修理 diff）：`8 files, +24 / −239`（含测试删）。

## 聚焦测试

前缀：七个 `MING_SIM_*_BIN=/usr/bin/false` + `MING_SIM_TRACE_PATH`/`--basetemp` → `/tmp/ming1847-fixer.*`

```text
tests/test_month_chain_1847.py
tests/test_pihong_dossier_1490.py
tests/test_month_chain_1843.py
tests/test_month_call_recovery_1846.py
tests/test_cli_backend.py
tests/test_rescript_choices_563.py
tests/test_llm_channel_config.py::test_scene_and_rescript_entries_pass_default_headers_at_transport
tests/test_new_issues_section_rejections.py::test_new_issue_whitespace_resolve_condition_falls_back_to_stop_condition
→ 203 passed in 12.96s (real 14.14s)
```

`web`：`npx tsc -p . --noEmit` → exit 0，无输出。

未跑全量；未做真实模型游戏验收。

## 变异证据（临时旧逻辑红 / 恢复绿）

| 类 | 命令要点 | 红 | 绿 | 时长 |
|---|---|---|---|---|
| N7 | 临时恢复 stderr `split("OpenAI Codex v")`；`pytest …::test_run_codex_stderr_banner_does_not_become_body` | 1 failed（DID NOT RAISE） | 1 passed | ~0.99s / ~0.95s |
| N6 | 临时恢复 strip+`[:300]`+materials strip；真入口 `apply_issue_tracker_output` + `_visible_affair_lines`（临时 harness，已删） | 1 failed（空白被剥，len=200） | 1 passed | ~1.05s / ~1.04s |
| N9 | `from ming_sim.settlement_payload import bind_decisions_to_candidate_events` | ImportError | （保持删除） | — |

## 测试删改契约

- 删：旧 bind 专属文件与 pihong helper 三测（N9）
- 改：N7 非法成功锁 → 负向闸（stderr banner 仍 `llm_empty_output`）
- 不新增功能证明测试；保留现役 0055/空输出等闸

## 质量合法性自查

- 删简优先，无新机制/护栏/重试层
- 未恢复六动作、未补 N8、未碰 X1/X2
- 未 stash/amend/push/开 PR/全量
- 自建物仅在本工作树与 `/tmp/ming1847-fixer.*`；临时 harness 已删
- 自查二连：同类根因全仓枚举后复扫清；未引入平行运输层

## commitSha / 剩余跨票

- **修理 commitSha**：`00e2d9a44828cd369e9624e8c263f85ebd5934bf`
- **报告注记 commitSha / HEAD**：`b72cf7ecb155a5bad8d6e073b6e561ace98ae121`
- **剩余跨票**：N8→#1873；X1→#1826；X2→#1873/#1826；前端文书页与功能接缝不在本修理范围
