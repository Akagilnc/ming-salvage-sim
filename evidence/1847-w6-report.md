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
| N12 | 同规则 legacy modifiers 账目键读端 → `GATE_METRIC_KEYS`：`db.legacy_modifiers`、`web_app._humanize_legacy_effect`、`models._legacy_effect_has_work`；`fiscal_tick` NewDebt/Repaid/oracle 三元组 → `_ARREARS_KEYS`（=`ARREARS_SUBJECTS`）。无新枚举/护栏/适配层。判词「不要求全仓四项一律收拢」≠同规则另一读端豁免。 |

## 可核枚举命令（全仓；判词样本≠白名单）

谓词：**N11**=同一退役机制的读/写/常量是否仍有一半存活（不只 legacy 字样）；**N12**=与已收敛真源同形的内联闭集字面量（同规则全类，不只点名文件）。

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
rg -n 'for account in GATE_METRIC_KEYS' web_app.py                                                          # expect present
rg -n 'for key in GATE_METRIC_KEYS' ming_sim/models.py                                                      # expect present
rg -n 'NewDebt=\{c: 0 for c in _ARREARS_KEYS\}|for c in _ARREARS_KEYS' ming_sim/fiscal_tick.py              # expect present
rg -n '\(\"国库\", \"内库\", \"民心\", \"皇威\"\)' ming_sim/db.py web_app.py ming_sim/models.py               # expect empty
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

按类配对谓词：**读同一份 legacy modifiers 顶层账目键**（聚合 / work 判定 / humanize）。判词「不要求全仓四项一律收拢」只排除异类字面量，不豁免同规则另一读端。

| file | line | disposition | 依据 |
|---|---:|---|---|
| ming_sim/constants.py | 311 | KEEP_single_source_def | 真源定义 |
| ming_sim/db.py | legacy_modifiers init+loop | **CONVERGED_prior** → `GATE_METRIC_KEYS` | 判词点名同规则写读 |
| ming_sim/issues.py | 3340 | CONVERGED_prior → `GATE_METRIC_KEYS` | 同真源循环 |
| web_app.py | 338 `_humanize_legacy_effect` | **CONVERGED_this_round** → `GATE_METRIC_KEYS` | 同份 modifiers 账目键读端；先前误标 KEEP_out_of_scope（「判词只点 db」）已纠正 |
| ming_sim/models.py | 263 `_legacy_effect_has_work` | **CONVERGED_this_round** → `GATE_METRIC_KEYS` | 同份 modifiers 非零判定；同规则 work 读端，非异类消费者 |
| web/src/format.ts | 240 `formatLegacyEffect` | KEEP_schema_ui_order | **非「未点名」**：TS 侧无既有 `GATE_METRIC_KEYS`；新建 TS 常量/跨语言适配层违 N12「不新造枚举/适配层」。`LegacyEffect`（`types.ts:218`）已 schema 钉四可选字段；此处数组=typed 字段展示迭代序。主路径 `effect_text` 已由 `web_app` 真源收敛；本函数为 UI fallback |
| ming_sim/constants.py | 47 | KEEP_subset `BUILDING_OUTPUT_METRICS`（含 `""`） | 建筑产出超集，非 legacy modifiers 读端 |
| scripts/agy_turn_probe.py | 85 | KEEP_probe_extra_keys | probe 另含兵force/军心，非同规则 |
| tests/test_qa_u2_liaodong_buildings.py | 87 | KEEP_test_fixture | 建筑 metric 成员检测，非 legacy modifiers |
| tests/* 其它 fixtures | — | KEEP_test_fixture | 异类 |

### ARREARS 三项（真源 `pay_order.ARREARS_SUBJECTS`）

| file | line | disposition |
|---|---:|---|
| ming_sim/pay_order.py | 35 | KEEP_single_source_def |
| ming_sim/pay_order.py | 37 | KEEP_map_priority（值映射≠第二份闭集） |
| ming_sim/fiscal_tick.py | 225–226,481 | **CONVERGED_prior** → `_ARREARS_KEYS` |
| ming_sim/fiscal_tick.py | 13 | KEEP_docstring_prose |
| ming_sim/fiscal_tick.py | 31 | KEEP_superset `CLAIM_KEYS`（含民欠旧赋） |
| ming_sim/fiscal_tick.py | 35 | KEEP_map `_DEBT_OF_DUE` |
| ming_sim/fiscal_fact_brief.py | 311 | KEEP_map_class_label |
| tests fixtures | — | KEEP_test_fixture |

**N12 residual under同规则配对（legacy modifiers 账目键 / arrears 三元组可执行内联）: 0**。

## 反例配对核查

| 检查 | 结果 |
|---|---|
| 孤儿正则/函数生产残留 | 空 |
| JSON `stop_condition` / `commitment_kind` 合法路径 | 仍在 `issues.py` |
| `db.legacy_modifiers` 读 `GATE_METRIC_KEYS` | 是 |
| `web_app._humanize_legacy_effect` 读 `GATE_METRIC_KEYS` | 是 |
| `models._legacy_effect_has_work` 读 `GATE_METRIC_KEYS` | 是 |
| `fiscal_tick` NewDebt/Repaid/oracle 读 `_ARREARS_KEYS` | 是 |
| `db.py` / `web_app.py` / `models.py` 内联四元组 | 空 |
| `fiscal_tick.py` 可执行内联三元组 | 空 |

## 变异探针（临时；旧红现绿；精确 edit，不用 checkout 覆盖）

### N11 orphan gate（既有）

真实入口：`GameDB.advance_issue`（`delta_bar` 钳 ±50；`bar_value=50` +50 →100）。
形状：`resolve_condition="character.毛文龙.loyalty >= 65"`，无 `commitment_kind`、无 JSON `stop_condition`。
不恢复旧 `commitment_resolve` 写端/专属测。

| 相 | 结果 | 时长 |
|---|---|---|
| GREEN（当前修复） | `1 passed` | real **2.55s** |
| RED（临时注入 orphan `fullmatch` or 子句） | `1 failed` `assert 'active' == 'resolved'` | real **1.21s** |
| GREEN（backup 还原修复） | `1 passed` | real **1.17s** |

原始输出：`/tmp/1847-w6/mutation-{green,red,green2}.txt`（系统临时目录）。

### N12 web humanize 读端（本轮补精确命令）

入口：`web_app._humanize_legacy_effect`；输入 `{"国库":10,"内库":-2,"民心":5,"皇威":-3}`；monkeypatch `GATE_METRIC_KEYS=("民心",)` 时期望只出 `民心+5%`。
临时物仅 `/tmp`；变异用精确字符串替换（**不用** `git checkout` 擦工作树）。

```bash
# GREEN
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest \
  tests/test_legacy_gate_metric_keys_read_n12.py::test_humanize_legacy_effect_follows_gate_metric_keys \
  -q --basetemp=/tmp/1847-w6/pytest-n12-mut-green
# → 1 passed

# RED：把 web_app.py 中
#   for account in GATE_METRIC_KEYS:  # #14 same source as db.legacy_modifiers
# 精确换成
#   for account in ("国库", "内库", "民心", "皇威"):  # TEMP_MUTATION_N12
# 再跑同上命令
# → 1 failed：assert '国库+10%、内库-2%、民心+5%、皇威-3%' == '民心+5%'

# GREEN2：精确还原 GATE_METRIC_KEYS 行后重跑
# → 1 passed
```

| 相 | 结果 | 输出 |
|---|---|---|
| GREEN | `1 passed` | `/tmp/1847-w6/mutation-n12-web-green.txt` |
| RED（内联四元组） | `1 failed` 期望仅民心、实际四项全出 | `/tmp/1847-w6/mutation-n12-web-red.txt` |
| GREEN2（精确还原） | `1 passed` | `/tmp/1847-w6/mutation-n12-web-green2.txt` |

自查撤回上述永久测试准入主张：`tests/test_legacy_gate_metric_keys_read_n12.py` 新增了只测内部 helper、mock 常量并锁呈现措辞的证明性测试，违反本票不新增证明性测试及测试契约边界，已随独立纠正提交删除，不换形重造。上述变异与364 passed仅记录删除前的实跑历史；不作为新外部入口契约证明。N11真实 `GameDB.advance_issue` 旧红现绿证明及既有聚焦测试结果保留。

## 聚焦测试（七前缀 + Web 读取触及面）

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
  tests/test_legacy_gate_metric_keys_read_n12.py \
  tests/test_web_issue_condition_display.py \
  -q --basetemp=/tmp/1847-w6/pytest-focused-w6b
```

**364 passed in 17.23s** → `/tmp/1847-w6/focused-pytest-w6b.txt`

web tsc：`cd web && npx tsc --noEmit` → exit 0 → `/tmp/1847-w6/tsc.txt`

未跑全量；未调真实模型；未改配置。

## 提交

- prior code fix (N11 + db/fiscal N12): `e49928cb62df359f2df78fc2f9a2f0712758ed2b`
- this round code+report (web/models GATE 读端 + 报告自查纠正): see `git rev-parse HEAD` after commit on `ak-roles/1847-fixer-w6-n11-n12`
- production files: `web_app.py`, `ming_sim/models.py`；报告 `evidence/1847-w6-report.md`。新增 helper 证明测试已由后续独立自查提交删除，无生产行为变更，未为删除重复跑聚焦批次。

## 自查二连 done

- 同类：N11 按读/写/常量配对扫，不只 legacy 字样；**N12 同规则全类收口**（legacy modifiers 账目键读端：db + web_app + models），**不是「只收判词点名内联」**——判词边界「不全仓四项一律收拢」≠同规则另一读端豁免。`format.ts` 以「无既有 TS 真源 + 禁新枚举/适配 + schema typed 展示序」保留，依据不是 not named。
- 引入 bug：本腿早期曾用 `git checkout --` 误擦未提交修复 → 已用 `/tmp` backup 回写并复核（历史如实保留）；**本轮变异起改为精确 edit / 临时进程替换，不再 checkout 覆盖工作树产物**。探针注意 `delta_bar`±50 钳制，避免假红。
