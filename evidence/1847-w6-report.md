# #1847 w6 修内司交卷 — N11/N12 未结清续修

- worktree: `/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- branch: `ak-roles/1847-fixer-w6-n11-n12`
- base HEAD（开工）: `f6b35e13d`
- 判词真源: `evidence/1847-w6-verdict.json`
- 既结保留: N6 / N13；0055 负向闸；`commitment_kind`；结构化 `stop_condition` JSON
- 禁令遵守: 未 amend / push / PR / stash / kill；未改席位；未动 `node_modules/`；临时物仅 `/tmp/1847-w6/`

## 本轮处置（处方对齐判词）

| 类 | 动作 |
|---|---|
| N11 | 删除 `ming_sim/db.py` 孤儿读端：`_COMMITMENT_STOP_CONDITION_RE`、`_is_commitment_stop_condition`、及 `advance_issue` 中对应 `or` 子句。无 `commitment_kind` 且无 JSON `stop_condition` 的案件按普通案件在 bar≥100 结案。不恢复旧闸/旧专属测。 |
| N12 | `legacy_modifiers` 内联四项 → `GATE_METRIC_KEYS`；`fiscal_tick` NewDebt/Repaid/oracle 三元组 → `_ARREARS_KEYS`（=`ARREARS_SUBJECTS`）。无新枚举/护栏/适配层。 |

## 可核枚举命令（全仓；判词样本≠白名单）

谓词：**N11**=同一退役机制的读/写/常量是否仍有一半存活（不只 legacy 字样）；**N12**=与已收敛真源同形的内联闭集字面量。

```bash
# N11：退役符号 + loyalty 散文闸形状（排除 evidence/node_modules）
rg -n --glob '!evidence/**' --glob '!node_modules/**' \
  '_COMMITMENT_STOP_CONDITION_RE|_is_commitment_stop_condition|_legacy_commitment_stop_gate|_LEGACY_ACCOUNT_KEYS|_infer_tag|_warm_keychain|_guess_caller_tag|ming_sim_caller_tag|PERSON_LEGACY_ALLEGIANCE|__leverage_offsets_rank_rules_562' \
  ming_sim/ scripts/ web/src/ web_app.py main.py launcher.py tests/

rg -n --glob '!evidence/**' --glob '!node_modules/**' \
  'character\.[^.\s\"'\'']+\.loyalty\s*(?:>=|>)\s*\d+' \
  ming_sim/ scripts/ web/src/ web_app.py main.py launcher.py tests/

# N12：与 GATE_METRIC_KEYS / ARREARS_SUBJECTS 同形内联
rg -n --glob '!evidence/**' --glob '!node_modules/**' \
  '\(\"国库\",\s*\"内库\",\s*\"民心\",\s*\"皇威\"\)|\[\"国库\",\s*\"内库\",\s*\"民心\",\s*\"皇威\"\]' \
  ming_sim/ scripts/ web/src/ web_app.py tests/

rg -n --glob '!evidence/**' --glob '!node_modules/**' \
  '\(\"军饷欠\",\s*\"官俸欠\",\s*\"宗禄欠\"\)|\[\"军饷欠\",\s*\"官俸欠\",\s*\"宗禄欠\"\]' \
  ming_sim/ scripts/ tests/

# 反例配对（必须同时成立）
rg -n '_COMMITMENT_STOP_CONDITION_RE|_is_commitment_stop_condition|_legacy_commitment_stop_gate' ming_sim/   # expect empty
rg -n 'def _commitment_stop_gate|def _validate_commitment_stop_condition' ming_sim/issues.py                 # expect present
rg -n 'for acc in GATE_METRIC_KEYS' ming_sim/db.py                                                          # expect present
rg -n 'NewDebt=\{c: 0 for c in _ARREARS_KEYS\}|for c in _ARREARS_KEYS' ming_sim/fiscal_tick.py              # expect present
rg -n '\(\"国库\", \"内库\", \"民心\", \"皇威\"\)' ming_sim/db.py                                             # expect empty
rg -n '\(\"军饷欠\", \"官俸欠\", \"宗禄欠\"\)' ming_sim/fiscal_tick.py                                       # expect empty
```

扫描辅助（系统临时目录，非仓内重复 TSV）：`/tmp/1847-w6/enum_n11_n12.py`

## N11 全成员紧凑表（配对谓词）

| file | line | member | disposition |
|---|---:|---|---|
| ming_sim/db.py | (was 110) | `_COMMITMENT_STOP_CONDITION_RE` | **DELETED_this_round** |
| ming_sim/db.py | (was 467) | `_is_commitment_stop_condition` | **DELETED_this_round** |
| ming_sim/db.py | (was 19943) | `or _is_commitment_stop_condition(resolve_condition)` | **DELETED_this_round** |
| ming_sim/issues.py | 517–528 | `_commitment_stop_gate` JSON-only | KEEP_live_stop_condition_json |
| ming_sim/issues.py | 378+ | `_validate_commitment_stop_condition` | KEEP_live_stop_condition_json |
| ming_sim/issues.py | 371+ | `commitment_kind` normalize/require | KEEP_live_commitment_kind |
| ming_sim/issues.py | 3340 | comment mentions `_LEGACY_ACCOUNT_KEYS` | KEEP_comment_history |
| tests/test_person_delta_adapter.py | 159 | `pairing_warnings not in applied` | KEEP_negative_contract |
| tests/test_commitment_display_348.py | 126,174 | loyalty DSL in display fixture | KEEP_test_display_fixture |
| tests/test_decree_commitment_schema_136.py | 203 | prose as stop_condition schema sample | KEEP_test_schema_fixture |
| tests/test_decree_commitment_creation_136.py | 622,650,1111 | schema/negative `_has_stop_condition` | KEEP_test_negative_contract |
| tests/test_web_issue_condition_display.py | 40–86 | display formatter samples | KEEP_test_display_fixture |

**N11 residual deletable under pairing predicate: 0**（退役符号生产代码全空）。

## N12 全成员紧凑表（同规则内联）

### GATE 四项（真源 `constants.GATE_METRIC_KEYS`）

| file | line | disposition |
|---|---:|---|
| ming_sim/constants.py | 311 | KEEP_single_source_def |
| ming_sim/db.py | legacy_modifiers init+loop | **CONVERGED_this_round** → `GATE_METRIC_KEYS` |
| ming_sim/issues.py | 3340 | CONVERGED_prior → `GATE_METRIC_KEYS` |
| ming_sim/models.py | 263 | KEEP_out_of_scope（判词：不要求全仓四项一律收拢） |
| web_app.py | 338 | KEEP_out_of_scope |
| web/src/format.ts | 240 | KEEP_out_of_scope |
| ming_sim/constants.py | 47 | KEEP_subset `BUILDING_OUTPUT_METRICS`（含 `""`） |
| scripts/agy_turn_probe.py | 85 | KEEP_probe_extra_keys |
| tests/* / web test fixtures | — | KEEP_test_fixture |

### ARREARS 三项（真源 `pay_order.ARREARS_SUBJECTS`）

| file | line | disposition |
|---|---:|---|
| ming_sim/pay_order.py | 35 | KEEP_single_source_def |
| ming_sim/pay_order.py | 37 | KEEP_map_priority（值映射≠第二份闭集） |
| ming_sim/fiscal_tick.py | 225–226,481 | **CONVERGED_this_round** → `_ARREARS_KEYS` |
| ming_sim/fiscal_tick.py | 13 | KEEP_docstring_prose |
| ming_sim/fiscal_tick.py | 31 | KEEP_superset `CLAIM_KEYS`（含民欠旧赋） |
| ming_sim/fiscal_tick.py | 35 | KEEP_map `_DEBT_OF_DUE` |
| ming_sim/fiscal_fact_brief.py | 311 | KEEP_map_class_label |
| tests fixtures | — | KEEP_test_fixture |

**N12 residual under判词边界（仅要求上述配对内联）: 0**。

## 反例配对核查

| 检查 | 结果 |
|---|---|
| 孤儿正则/函数生产残留 | 空 |
| JSON `stop_condition` / `commitment_kind` 合法路径 | 仍在 `issues.py` |
| `db.legacy_modifiers` 读 `GATE_METRIC_KEYS` | 是 |
| `fiscal_tick` NewDebt/Repaid/oracle 读 `_ARREARS_KEYS` | 是 |
| `db.py` 内联四元组 | 空 |
| `fiscal_tick.py` 可执行内联三元组 | 空 |

## 变异探针（临时；旧红现绿；已删临时测）

真实入口：`GameDB.advance_issue`（`delta_bar` 钳 ±50；`bar_value=50` +50 →100）。  
形状：`resolve_condition="character.毛文龙.loyalty >= 65"`，无 `commitment_kind`、无 JSON `stop_condition`。  
不恢复旧 `commitment_resolve` 写端/专属测。

| 相 | 结果 | 时长 |
|---|---|---|
| GREEN（当前修复） | `1 passed` | real **2.55s** |
| RED（临时注入 orphan `fullmatch` or 子句） | `1 failed` `assert 'active' == 'resolved'` | real **1.21s** |
| GREEN（backup 还原修复） | `1 passed` | real **1.17s** |

原始输出：`/tmp/1847-w6/mutation-{green,red,green2}.txt`（系统临时目录）。

## 聚焦测试（七前缀）

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest \
  tests/test_cli_backend.py \
  tests/test_new_issues_section_rejections.py \
  tests/test_office_rank_562.py \
  tests/test_decree_commitment_settlement_229.py \
  tests/test_fiscal_tick.py \
  tests/test_person_delta_adapter.py \
  -q --basetemp=/tmp/1847-w6/pytest-focused
```

**353 passed in 5.05s**（real **5.56s**）→ `/tmp/1847-w6/focused-pytest.txt`

未跑全量；未调真实模型。

## 提交

- commit: `e49928cb62df359f2df78fc2f9a2f0712758ed2b`
- files: `ming_sim/db.py`, `ming_sim/fiscal_tick.py`, `evidence/1847-w6-verdict.json`, `evidence/1847-w6-report.md`

## 自查二连 done

- 同类：N11 按读/写/常量配对扫，不只 legacy 字样；N12 只收判词点名的同形内联，未造新枚举。
- 引入 bug：`git checkout --` 曾误擦未提交修复 → 已用 `/tmp` backup 回写并复核；探针注意 `delta_bar`±50 钳制，避免假红。
