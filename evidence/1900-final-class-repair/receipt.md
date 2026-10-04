# #1900 修内司回执：末判 J18/J6 — NEEDS_READ 清桶 + 违法类整修（诚实未结）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1900-w5`
- 分支：`ak-roles/1900-j18-j6-final-class-repair`
- 判词真源：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a108b9-3e6e-7ba3-b4af-52e9a2b219d2@fixer/attachments/02-1900-judge-bb448254c.json` **末份** `continue` payload（payloads[2]）
- 票面：`gh issue view 1900` / `1812`
- 禁令：无 stash / amend / rewrite / push / PR；未改 Soul/宪法/外部配置

**本轮纠正**：上一份回执在 `NEEDS_READ_PROSE:49` / `NEEDS_READ:3` 仍在表内时宣称缺陷残留 0，且以 `KEEP_BOUNDARY_STUB`/`KEEP_OTHER` 默认戳记冒充语义裁决——**不成立**。本轮逐项读完原 52 未审项，清掉全部 `NEEDS_*`；发现的违法文字锁 / `internal` 标记锁整类修；**不把 PENDING 默认桶假归零**。

---

## 1. 未结类别（末判施工边界）

| 类 | 级别 | 状态 |
|---|---|---|
| **J18** | P2 | 先前复扫 DELETE 死 helper 已落；本轮未新开 J18 代码改动。现役押解契约仍在成员表。 |
| **J6** | P2 | **未结**。已清 `NEEDS_*` 并修违法实例；`PENDING_STUB_DEFAULT:308` + `PENDING_OTHER_DEFAULT:188` + web `PENDING_WEB_UI_DEFAULT:129` 仍待逐项语义审。 |

---

## 2. 枚举可复现性

### 2.1 J18

```bash
# AST 全仓（产出 j18-full-members.json；权威表保留）
# 谓词：escort|护送|护行|暗护|押解|grant_arrival|reconciliation|双载体|专用…|payload_declares|…

rg -n --glob '!evidence/**' --glob '!.baseline/**' \
  'escort_pending_targets|escort_sources|dossier_escort_outcomes|_resolve_covert|_grant_escort_presence|clamp_grant_arrival|_escort_identity|_reader_may_cite|grant_route_reader|is_grant_allocation_dossier|_write_dossier_payload_key|_GRANT_ESCORT_RELATIONS|护送实况|list_open_grant_reconciliations|软判提案|软判读账' \
  ming_sim web_app.py tests docs --glob '*.py' --glob '*.md'
```

权威：[`j18-full-members.md`](j18-full-members.md) / [`j18-full-members.json`](j18-full-members.json)  
本局已删窄枚举重复拷贝 `j18-members.json`。

### 2.2 J6

```bash
# AST：tests/**/*.py 每个 test_* 扫 monkeypatch.setattr / call_oracle / marker /
# direction / OperationalError|中文 in / translate_fn=lambda / helper 命名
# 原始候选：j6-ast-candidates.json
# 权威处置：j6-full-disposition.json

rg -n --glob 'tests/**/*.py' \
  'apply_legacy_pct\(|grant_arrival_bounds\(|_has_meta_flag\(|routed:|track_auto_close|seen\.get\("write_gate"\)|assert any\(.*第一问|assert all\(.*后轮问|internal.*=.*substrate_hub|直到补齐.*=.*in'

rg -n --glob 'web/src/**/*.{ts,tsx}' 'vi\.spyOn|toHaveBeenCalled|mockImplementation'
# node_modules 命中仅作 EXCLUDE_THIRD_PARTY，不算自有测试处置
```

权威：[`j6-full-members.md`](j6-full-members.md) / [`j6-full-disposition.json`](j6-full-disposition.json)  
本局已删重复拷贝：`j6-focus.json`、`j6-members.json`。

---

## 3. 本轮代码侧整类修

| 类 | 改动 |
|---|---|
| CLI/显示措辞锁 | `test_commitment_progress_contexts_are_structured`：删 `capsys`「直到补齐」；改结构化 `months_elapsed`/`paid_total`/`remaining_arrears` |
| 诊断/注入文案锁 | relation/faction brew：`pytest.raises(OperationalError)` 去掉 `match=`；person_delta 删 `simulated … in reason` |
| 原文子串弱锁 | commitment ack：`resolution_summary == narrative`（全文，非「圣裁处理」子串） |
| 内部标记锁 | substrate hub：公开预算名 `{起运,盐税,商税,太仓亏空}` + ledger 精确额；案名改为 `test_substrate_hub_display_name_collision_books_user_fiscal_exact` |

复扫上述谓词在 `tests/**`：**0 命中**（`internal==substrate_hub` / `直到补齐 in` / `match=…不可写` / `simulated … in changes`）。

末判点名伪证（power_band/`routed`/`_has_meta_flag`/auto_close spy/night_said 正文锁/金额方向退化）维持已清。

---

## 4. 聚焦验证（七 BIN=/usr/bin/false；不全量）

完整命令：

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
python3 -m pytest \
  tests/test_decree_commitment_settlement_229.py::test_commitment_progress_contexts_are_structured \
  tests/test_decree_commitment_settlement_229.py::test_due_one_shot_commitment_ack_closes_review_loop_without_effects \
  tests/test_fiscal_substrate_bridge.py::test_substrate_hub_display_name_collision_books_user_fiscal_exact \
  tests/test_fiscal_substrate_bridge.py::test_fixed_flows_substrate_hub_books_split_treasury_income_and_central_losses \
  tests/test_fiscal_substrate_bridge.py::test_budget_lines_read_persisted_substrate_hub_income_source \
  tests/test_person_delta_adapter.py::test_apply_score_extraction_rolls_back_derived_release_when_office_write_fails \
  tests/test_person_delta_adapter.py::test_derived_release_rejection_keeps_prior_person_change_in_atomic_batch \
  tests/test_person_delta_adapter.py::test_derived_release_restores_when_post_office_helper_raises \
  tests/test_relation_brew_636.py::test_prepare_claim_db_error_propagates_loudly \
  tests/test_relation_brew_636.py::test_apply_db_error_propagates_loudly_not_disguised_as_llm_failure \
  tests/test_relation_brew_636.py::test_mark_failure_after_llm_failure_propagates_loudly \
  tests/test_faction_brew_637.py::test_faction_claim_db_error_propagates_loudly \
  tests/test_faction_brew_637.py::test_faction_apply_db_error_propagates_loudly_not_disguised \
  -q --tb=short
# → 13 passed

MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
python3 -m pytest \
  tests/test_decree_commitment_settlement_229.py \
  tests/test_fiscal_substrate_bridge.py \
  tests/test_person_delta_adapter.py \
  tests/test_relation_brew_636.py \
  tests/test_faction_brew_637.py \
  -q --tb=line
# → 351 passed, 1 skipped；real ~18.95s
```

日志：`focused-named.log` / `focused-files.log`（本地；可能 gitignore）。

不为证明新造测试。

---

## 5. 自查二连

- 同类型：CLI 措辞锁、`match=` 注入文案、`internal` 标记、reason 注入子串已整类扫清。
- 引入 bug：聚焦 13 + 触及文件 351 绿；未改 Soul/配置。
- **不宣称 J6 结清**。

---

## 6. 实际未结（禁止假归零）

| 桶 | 计数 | 含义 |
|---|---:|---|
| `PENDING_STUB_DEFAULT` | 308 | 先前「边界 stub」默认戳记，**非**本轮逐项语义裁决 |
| `PENDING_OTHER_DEFAULT` | 188 | 先前「未命中谓词」默认戳记，**非**本轮逐项语义裁决 |
| `PENDING_WEB_UI_DEFAULT` | 129 | 自有 web mock 行，未逐项审 |
| `EXCLUDE_THIRD_PARTY` | 16 | node_modules；排除说明 only |
| `NEEDS_READ*` | **0** | 原 52 已逐项落 KEEP_*/FIX_* |

J6 整类 **未结**。下一刀须对 PENDING_* 逐项读上下文并给独立外部契约依据，不得再默认 KEEP。

---

## 7. Commits

- 本轮提交 SHA：见 commit 后回填
- 标题：`ak-roles: fix(#1900): adjudicate J6 NEEDS_READ bucket and drop illegal locks`
