# #1834 修内司回执 · F16 自审修正（删新永久测试 + 退役残段 + 全员 loc）

**工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1834-w5`
**分支**：`ak-roles/1834-f16-f3-f3r-f17-ee3b5da31`
**基线**：`ee3b5da312c5832720d89aee707fe4c7669c5eb0`
**父 HEAD（自审开工）**：`285c0abb4`（stamp after aa7374f11）
**本轮 commit**：*(stamp after commit)*
**判词**：`evidence/1834-f16-f3-f3r-f17-fix/continued-ruling.json` + 用户续判（禁新增永久证明测试；退役残段不得宿主保留；F16 16 组须可核全员 loc）
**法源**：CLAUDE.md P6 / ADR 0142；判词 F16「自由文本零删改」；stdout 包装改写**不是**合法例外。

**共同测试前缀（七变量，实写）**：

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false
```

F3 / F17：保持已修；F17 维持合法撤销路线，本轮未新造任何证据/变异机制。

---

## 自审修正（相对 aa7374f11）

### 删除新永久证明测试（五条，不换形新增）

| 位置 | 条数 | 处置 |
| --- | --- | --- |
| `tests/test_cli_runner_error_typed_1299.py` | 4（+77 行） | **已删**：`test_run_cli_runner_preserves_llm_body_whitespace` / `test_run_cli_runner_whitespace_only_still_empty` / `test_write_decree_with_agno_preserves_whitespace` / `test_require_non_empty_text_preserves_whitespace` |
| `web/src/components/situation.test.tsx` | 1（+9 行） | **已删**：`preserves padded commitment progress text verbatim` |

原有独立契约保留（#1299 typed/banner；#671 extract whitespace；situation 既有 progress/fallback 等）。

合法保留：`tests/test_cli_backend.py` 既有运输断言已适应 raw（`test_run_codex_stdout_empty_fallback` → `STDOUT_BODY\n`）；既有空输出 negative `test_run_runner_empty_output_is_retryable_typed` 仍在。

### 退役残段删除（非宿主 KEEP）

全仓调用者核查：`_cli_recommendation_call` / `_cli_prompt` / `_cli_stream_safe_prefix` / `_CLI_RECOMMENDATION_*` = **仅定义、零调用**；`ToolFunction` 未导入 → 强行调用 NameError。  
`dd8c0f072` 已退役，merge `beff66c17` 误带回。本轮随改删除整簇，并收窄 `_fake_completion` 签名（去掉无用 `tool_calls`）。

### F16 处置表全员映射

- 权威：`f16_disposition_after_counterexample.tsv`（**16 grouped rows**）
- 全员 loc：`f16_disposition_member_locs.tsv`（广扫 **2241/2241** 每条映射到一组；无 many/various/otherwise）
- 方法：`f16_disposition_after_counterexample.METHOD.txt`
- `CLI_recommendation_envelope_cut`：**DELETED**（非 KEEP）

生产 FIX（aa7374f11 已落、本轮保留）：CLI runner 终文 / 拟诏 / llm_contract / json_field fallback / `_matched_prefix` / situation·closedIssues·edictModal 展示判空副本。

---

## 聚焦测试

### pytest

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
python3 -m pytest tests/test_cli_runner_error_typed_1299.py tests/test_cli_backend.py tests/test_cli_transport_1465.py -q --tb=line
```

完整输出：`pytest_focus.txt` — **117 passed**

### vitest

```bash
cd web && npx vitest run --environment jsdom src/components/situation.test.tsx
```

完整输出：`vitest_focus.txt` — **10 passed**

---

## 未结（诚实）

- 不声称 2241 候选外永无新形状；权威以本轮 disposition + member_locs 为准。
- F17：仍仅撤销申报，无新旧并排变异，无新造证据机制。
- 未跑全量；未 stash/amend/push/PR。
- 本轮**未新增**永久证明脚本或测试；不为证明修复造测试。

自查二连 done（再读 diff：五条新测试已删、荐人残段已删、2241 全员 loc 可核、既有 test_cli_backend raw/空输出保留）。
