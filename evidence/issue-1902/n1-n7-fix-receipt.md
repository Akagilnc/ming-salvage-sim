# #1902 修内司 N1–N7 回执（自验纠偏）

- 分支：`ak-roles/1902-n1-n7-fixer-ccbdf378a`
- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5`
- 底座 HEAD（开工）：`ccbdf378a`
- 本轮提交：63dfe0d0cb79f8b6855448f70d10cd37d0446152
- 判词真源：末份 `03-1902-judge-ccbdf378a.json` payload（N1–N7）
- N6 完整成员表：`evidence/issue-1902/n6-ast-member-table.tsv`（+ 摘要 `n6-ast-member-table.md`）
- 枚举原始输出：`evidence/issue-1902/n1-n7-enum.out`
- 临时目录：`/tmp/ming1902-n1n7-selfverify/`（探针/变异；不入库永久扫描器）

七 BIN 前缀：

```bash
with_bins() {
  env \
    MING_SIM_AGY_BIN=/usr/bin/false \
    MING_SIM_CODEX_BIN=/usr/bin/false \
    MING_SIM_CLAUDE_BIN=/usr/bin/false \
    MING_SIM_CURSOR_BIN=/usr/bin/false \
    MING_SIM_KIMI_BIN=/usr/bin/false \
    MING_SIM_GROK_BIN=/usr/bin/false \
    MING_SIM_PI_BIN=/usr/bin/false \
    PYTHONDONTWRITEBYTECODE=1 \
    "$@"
}
```

---

## 本轮纠偏要点（相对上次回执不合格项）

1. **N6**：废弃「词面谓词扫 222 文件即覆盖」；改用 Python `ast` 枚举全部测试函数/断言（含 pytest.raises、mock `assert_*`、Web `it`/`expect`），**逐函数**语义裁定并落完整 TSV（3292 行含 1 条已删函数记录），不以总数代替成员表。
2. **N1**：核查 `_log` 实现 = `_VERBOSE` 门控 `print`，**不**走 `logger`；不得自称「公开 degrade / 无须真落痕」。首抽 call/transport 失败改为复用既有 `cli_runner_unavailable`（与 `secret_extract` 同形），真因进 `provider_message` + `__cause__`。
3. **N1 变异**：对**正确契约**断言；旧 wash 下该断言 FAIL（证明），旧行为泛化坍塌仅标 **OBSERVE**，不再误标 `*_RED_ASSERT_PASS`。
4. **N4**：按形状扫 `getattr/hasattr/or auto_close` 生命周期缺方法兼容（不止 `getattr(close)`）；生产入口命中 0。

---

## N6 AST 枚举命令（可重放；产出完整成员表）

```bash
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5
TMP=/tmp/ming1902-n1n7-selfverify
# 1) 枚举全部测试函数 → $TMP/n6_ast_enum.jsonl
# 2) 语义裁定 → evidence/issue-1902/n6-ast-member-table.tsv
# 完整脚本见本轮施工记录；重放后 TSV 须列全候选而非仅计数。
python3 -c "import pathlib; print(sum(1 for _ in pathlib.Path('evidence/issue-1902/n6-ast-member-table.tsv').read_text().splitlines()[1:]), 'candidates')"
# → 3292
```

处置×桶计数见 `n6-ast-member-table.md`。非「保留」成员 11 条（修 8 / 删 3）全列于该 MD；其余 3281 条在 TSV 逐行保留理由。

**不得**声称「扫描 222 文件」= 覆盖非契约措辞 / 内部·重复·失效证明全类。

565 merge 夹具「追加备注甲」：**保留**为自身构造输入原文透传；**不是**「删除呈现证明」。

---

## 成员表（N1–N5 / N7；N6 见 AST TSV）

### N1 — **结清**（有代码依据）

| 成员 | 处置 | 理由 / 依据 |
|---|---|---|
| 解析失败 / 缺「拟旨意图」/ 非法枚举 → `draft_action=无` | **修** | 改 `ValueError` 真因分句（`cli_backend.py` extract） |
| 首抽 LLM `Exception` → `_log` + 返回「无」 | **修** | `_log` 仅 VERBOSE print，非真落痕；改 `cli_runner_unavailable(..., backend="draft_intent")`（同 `secret_extract` 3549 行契约） |
| `resubmit` 泛化「未返回拟旨意图」 | **保留** | 仅承接模型明确合法「无」；非法产物不再落到此句 |
| `acting_appointment` / 合法「无」短路 | **保留** | 票面 boundary：非解析失败洗「无」 |

### N2 — **结清**

| 成员 | 处置 | 理由 |
|---|---|---|
| Web 入口自造生效 `LLMConfig` | **修** | 只走 `llm_config_from_runtime` |
| `_advanced_llm_config_for_verify` | **修** | `for_role(config, "simulator")` |
| 共核 / 闸脚本构造 | **保留** | 权威实现或非运行档路径 |

### N3 — **结清**

| 成员 | 处置 | 理由 |
|---|---|---|
| `WebGame.reply_retries(殿上)` 中断集 | **修** | `session.pending_audience_reply_retries()` |
| post_reply 夜筛 / 非殿上适配 | **保留** | boundary：适配非再造中断身份 |

### N4 — **结清**（形状核查）

| 成员 | 处置 | 理由 |
|---|---|---|
| 入口 `getattr/hasattr` 缺方法→同步收夜/`auto_close` | **修** | 直调 `schedule/close_night_after_chat_if_needed`；形状复扫 0 |
| `_auto_close_open_night_gate_free` / `auto_close_open_night` | **保留** | 过月屏障真路径，非缺方法替身 |

### N5 — **结清**

| 成员 | 处置 | 理由 |
|---|---|---|
| 多旨/补充合并/候选指认 + 退役 kwargs 槽 | **删** | 枚举 `n5_dead_mode_sites=[]`；传入即 `TypeError` |
| 单旨补交/heal | **保留** | 现役消费者 |

### N6 — **结清**（AST 全量；见 TSV）

非保留样本（完整非保留表见 `n6-ast-member-table.md`）：

| 成员 | 处置 | 桶 |
|---|---|---|
| dossiers category / error_pack 结构 / chat provider_message / due_review 双字段 / pollError | **修** | 必要结构及来源契约弱化 |
| dossiers 不足额/应拨实拨词面；非空 note 残留 | **删/修** | 非契约诊断措辞 |
| llm_channel 常量 identity；modals 不代笔题名 | **删/修** | 内部及无依据证明 |
| 565 merge 透传；行为 identity；P7 chrome | **保留** | 见 TSV 理由 |

### N7 — **结清**

| 成员 | 处置 | 理由 |
|---|---|---|
| `issue-1901-w4-1838-merge.md` 硬换行差分 | **撤销** | `git diff 10e64fbef -- …` 空 |

---

## 变异证据（观察 vs 证明分开标注）

### N1 洗「无」— 正确契约

```bash
with_bins env PYTHONPATH=. python3 /tmp/ming1902-n1n7-selfverify/mutations/n1_wash_mutation.py
```

```text
N1_OBSERVE_OLD_WASH_COLLAPSE ... generic ...   # 观察，非红证明
N1_OBSERVE_ONLY: old wash collapses all to generic (not mutation-red proof)
N1_MUTATION_RED_ASSERT_FAIL_AS_EXPECTED: RED_OLD_WASH: expected needle '无法解析' in '结算补交重写未返回拟旨意图'
N1_MUTATION_RED_PROOF: correct contract failed under old wash
N1_RESTORE_GREEN_RESULTS [('无法解析', ...), ('拟旨意图', ...), ('非法', ...)]
N1_RESTORE_GREEN_ASSERT_PASS
```

### N1 首抽异常真落痕

```bash
with_bins env PYTHONPATH=. python3 /tmp/ming1902-n1n7-selfverify/mutations/n1_first_draw_trace.py
```

```text
N1_LOG_IMPL_OBSERVE: _log is VERBOSE-gated print; logger exists but _log does not use it
N1_FIRST_DRAW_GREEN: LLMUnavailable llm_cli_draft_intent draft_intent_probe_boom RuntimeError
N1_FIRST_DRAW_RED_ASSERT_FAIL_AS_EXPECTED: old degrade returned without LLMUnavailable
N1_FIRST_DRAW_RED_PROOF: correct contract failed under old silent degrade
N1_FIRST_DRAW_ASSERT_PASS
```

### N2 / N3 / N4 / N5 / N7

```bash
with_bins env PYTHONPATH=. python3 /tmp/ming1902-n1n7-selfverify/mutations/n2_projection.py
with_bins env PYTHONPATH=. python3 /tmp/ming1902-n1n7-selfverify/mutations/n3_semantics.py
with_bins env PYTHONPATH=. python3 /tmp/ming1902-n1n7-selfverify/mutations/n4_lifecycle_shape.py
with_bins env PYTHONPATH=. python3 /tmp/ming1902-n1n7-selfverify/mutations/n5_no_sink.py
git diff 10e64fbef -- docs/evidence/issue-1901-w4-1838-merge.md   # 空
```

```text
N2_MUTATION_RED_ASSERT_FAIL_AS_EXPECTED / N2_RESTORE_GREEN_ASSERT_PASS
N3_SEMANTICS_ASSERT_PASS
N4_LIFECYCLE_SHAPE_HITS [] / N4_LIFECYCLE_SHAPE_ASSERT_PASS
N5_NO_SINK_ASSERT_PASS
N7_EMPTY
```

---

## 聚焦测试（七 BIN；未跑全量）

```bash
with_bins env PYTHONPATH=. python3 -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/ming1902-n1n7-selfverify/focus2 \
  tests/test_draft_admission_resubmit_1769.py \
  tests/test_decree_dossiers_571.py \
  tests/test_pay_order_override_extraction_653.py \
  tests/test_error_pack.py \
  tests/test_chat_stream_failpaths_393.py \
  tests/test_due_review_621.py \
  tests/test_llm_channel_config.py \
  tests/test_web_llm_runtime_config.py \
  tests/test_cli_entry_1902.py \
  tests/test_web_entry_1902.py \
  tests/test_audience_restore_505.py \
  tests/test_structured_decree_contract_1624.py \
  tests/test_execution_joint_liability_565.py \
  tests/test_pihong_dossier_1490.py::test_658_typed_target_and_backing_reject_bad_shapes \
  tests/test_rescript_option_field_heal_1746.py::test_first_draw_parse_failure_heals_then_degrades
# → 345 passed in 10.22s

cd web && with_bins npm test -- --cache=false \
  src/useSettlementFlow.test.tsx src/components/modals.test.tsx
# → 2 files / 76 passed；Duration 1.06s
```

不为 finding 新增平行证明测试；不新增永久扫描机制。

---

## 结清总表

| 类 | 状态 | 依据 |
|---|---|---|
| N1 | **结清** | 真因分句 + `cli_runner_unavailable`；变异对正确契约红/绿 |
| N2 | **结清** | 共核投影；变异红/绿 |
| N3 | **结清** | 中断集共核 |
| N4 | **结清** | 形状复扫 0 缺方法降级 |
| N5 | **结清** | 死模式/kwargs 枚举空 |
| N6 | **结清** | AST 3292 候选完整 TSV + 类内删/修落地 |
| N7 | **结清** | 无关差分空 |

合法保留项均附代码/契约理由；无依据不称结清。

自查二连 done。
