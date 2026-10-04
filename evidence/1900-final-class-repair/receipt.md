# #1900 修内司回执：PENDING_* 逐项语义裁决 + 类修（本局）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1900-w5`
- 分支：`ak-roles/1900-j18-j6-final-class-repair`
- 判词真源：`~/.ak-roles/.../02-1900-judge-bb448254c.json` **末份** continue（payloads[2]）
- 禁令：无 stash / amend / rewrite / push / PR；未改 Soul/宪法/外部配置

## 1. 未结类别处置

| 类 | 级别 | 本局 |
|---|---|---|
| **J18** | P2 | 复扫专用账本/双载体/护送实况假断：**生产路径 0 命中**（仅退役说明与史档）。成员表维持 KEEP_LIVE*。 |
| **J6** | P2 | **PENDING_STUB_DEFAULT 308 / PENDING_OTHER_DEFAULT 188 / PENDING_WEB_UI_DEFAULT 129 已逐项语义审清零**；类修注入 match 措辞锁、power_band oracle、罐头子串锁。 |

## 2. 枚举命令（可复现）

### J18
```bash
rg -n --glob '!evidence/**' --glob '!.baseline/**' \
  'escort_pending_targets|escort_sources|dossier_escort_outcomes|_resolve_covert|_grant_escort_presence|clamp_grant_arrival|_escort_identity|_reader_may_cite|grant_route_reader|is_grant_allocation_dossier|_write_dossier_payload_key|_GRANT_ESCORT_RELATIONS|护送实况|软判提案|软判读账' \
  ming_sim web_app.py tests docs --glob '*.py' --glob '*.md'
```

### J6
```bash
# 权威表：j6-full-disposition.json / j6-web-members.json
rg -n --glob 'tests/**/*.py' 'pytest\.raises\([^)]*match\s*='
rg -n --glob 'tests/**/*.py' '== power_band\(|routed:|track_auto_close|seen\.get\("write_gate"'
rg -n --glob 'web/src/**/*.{ts,tsx}' 'vi\.spyOn|toHaveBeenCalled|mockImplementation'
```

## 3. 成员表与处置

- Python 618：见 [`j6-full-members.md`](j6-full-members.md) / [`j6-full-disposition.json`](j6-full-disposition.json)；**PENDING_*=0**
- Web 145（含 16 第三方排除）：[`j6-web-members.json`](j6-web-members.json)；自有 129 已审；**PENDING_*=0**
- J18：[`j18-full-members.md`](j18-full-members.md)

裁决判据（逐项）：stub 是否替被测行为；断言是否外部契约结构化可见；是否生成文/helper/内部路径机械依赖；必要负向复用真实入口。

## 4. 代码侧类修（不按样本限界）

| 修法 | 范围 |
|---|---|
| 删 `match=` 注入/诊断措辞锁 | 27+ 文件；保留异常类型与 DB/状态副作用 |
| `power_band` oracle → 定性字面量 | `test_promulgation_judge_561.py` |
| 罐头回话子串 → 全文相等 | `test_cli_runner_error_typed_1299.py` |

## 5. 聚焦测试（七 BIN=/usr/bin/false）

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
python3 -m pytest \
  tests/test_cli_runner_error_typed_1299.py \
  tests/test_promulgation_judge_561.py \
  tests/test_close_issues_section_rejections.py \
  tests/test_new_issues_section_rejections.py \
  tests/test_advances_section_rejections.py \
  tests/test_relation_brew_636.py \
  tests/test_state_reload.py \
  tests/test_rejection_wiring.py \
  tests/test_override_breach_costs_564.py \
  tests/test_executor_routing_721.py \
  tests/test_power_section_rejections.py \
  tests/test_qa_t1_extraction_dual_source_1353.py \
  tests/test_pre_settle_transaction.py \
  tests/test_fiscal_substrate_bridge.py \
  tests/test_month_chain_1847.py \
  tests/test_empire_modifier_income_only_341.py \
  tests/test_audience_translate_1837.py \
  -q --tb=line
# → 499 passed, 2 skipped
```

## 6. 必要变异

| 变异 | 结果 |
|---|---|
| 收入实入改为 1 | `test_income_still_modified_by_legacy` **failed**（88≠1）；恢复 passed |
| `build_night_said_so_far` 忽略 until | cutoff 案 **failed**（后轮泄漏入账）；恢复 passed |

日志：`mutations-round2.log` / `focused-wide.log`

## 7. 自查二连

- 同类型：注入 match 措辞锁、power_band 实现 oracle、罐头子串已整类扫清；PENDING 默认戳记已废。
- 引入 bug：聚焦 499 绿；变异咬合；未改 Soul/配置。
- J6 表内 PENDING=0；不另索全量/合并前真模型。

## 8. Commits

- 本轮施工提交 SHA：见 stdout / `git rev-parse HEAD`（提交后回填）

## 9. 子代理回执跟进（成立项已修）

核对 [batch-a](2c0c1040-b513-47ec-bd35-96cd09967297) / [batch-b](90923d5b-445a-4640-8a7c-ca59c9d0c951) / [web](6d7cba2c-19a3-4c7f-9e2f-cd542eff7a97) 的 FIX 指控后：

| 项 | 处置 |
|---|---|
| verify_llm smoke「输出 ok」锁 | 成立 → 改 tag/config/渠道路由断言 |
| rescript `title in msg` | 成立 → `options_len`/`options_type` 结构化 token |
| useSettlementFlow 仅 call-count | 成立 → harness 接 MechanicalTailFailure，断言 error_pack_path |
| clichat「臣遵旨」子串 | 上轮已改全文相等，维持 |

聚焦：上述 Python 8 passed；`web` vitest useSettlementFlow 14 passed。

