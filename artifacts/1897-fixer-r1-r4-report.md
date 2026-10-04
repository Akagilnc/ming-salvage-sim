# #1897 修内司 R1–R4 回执

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1897-w5`
- 分支：`ak-roles/issue-1897-r1-r4-fixer-20261005-053204`
- 底座 HEAD（施工前）：`64b899a0e1682b30bc74d18688380237773251ce`
- 本轮提交 SHA：`b99c0ef3dc30fa9de81ad7b47add9773fcabb90d`
- 派单：`.../01a1089b-50c9-7dac-ab41-8ba86b05e2c6@fixer/fix-packet.md`
- 冻结判词（末 payload 为准）：`01-1897-judge-64b899a0e.json` 的 `continue` 卷；先前 `sealed1` 收敛卷仅供参考
- 状态：已提交于本工作树分支；**未 push、未开 PR、未 merge**
- 网搜结论：结构化证据场景下，JSON/schema 解析失败与散文说明不得发明事实；最简现成方案是复用底座 `10e64fbef` 已有「只认 severity∈{轻,中,重}」判据 + c6 已有「dossier_progress 当月轨」读取，删除合并带回的旧账轨与退休替身，不新造兼容层

## 授权核验

- 用户明示「执行 #1897 修内司 apply 修复任务」「建新提交」→ 构成代码修改授权
- 沿用判词 R1–R4 类边界；未另立更窄边界；未新增兼容/恢复/账本层/证明性测试
- Event/Future 确定性握手用例按判词驳回删测处方予以保留
- 未改 Soul/宪法/宿主配置席位/全局规则；未 stash/amend/rewrite/push/开 PR

## 各类根因与处置

### R1：旧密令正文账轨仍参与现役接缝（P2）

**根因**：合并 `10e64fbef` 后，旧 `text_log_json` 账族与 `_has_secret_order_period_line` 读口回到现役；而写口已只写 `dossier_progress_json`。材料层因此永远读不到当月推进。

**修法**：
- `materials._write_secret_order_file` 改读订单上的 `dossier_progress`（当月非终值月报 origin）判定「本月已推进」，并重新附上 `_secret_order_memorials`
- 删除 db 旧正文账族（模块级 helper + 实例方法）与 schema 中的 `text_log_json`
- 去掉 `update_secret_order_by_id` 写前读废旧列

**全仓枚举命令**（施工前）：

```bash
rg -n --no-heading -g '*.py' \
  '_has_secret_order_period_line|_append_secret_order_line|_write_secret_order_body|_read_secret_order_body_before_write|_load_secret_order_body_row|_secret_order_body_log|_secret_order_period_recorded|_project_secret_order_bodies|_secret_order_kept_body|_secret_order_record_body|_SECRET_ORDER_BODY_COLUMNS|text_log_json'
```

**施工前完整成员表**：

| 符号 | 位置 |
|---|---|
| `_SECRET_ORDER_BODY_COLUMNS` | `ming_sim/db.py:873` |
| `_secret_order_kept_body` | `ming_sim/db.py:876`（定义）；`22452`（调用） |
| `_secret_order_record_body` | `ming_sim/db.py:882`（定义）；`907`,`937` |
| `_secret_order_body_log` | `ming_sim/db.py:890`（定义）；`22408`,`22418`,`22441` |
| `text_log_json` | `ming_sim/db.py:898`（读）；`1556`（schema） |
| `_secret_order_period_recorded` | `ming_sim/db.py:912`（定义）；`22417`,`22442` |
| `_project_secret_order_bodies` | `ming_sim/db.py:922`（定义，无生产消费者） |
| `_read_secret_order_body_before_write` | `ming_sim/db.py:22057`（调用）；`22404`（定义） |
| `_has_secret_order_period_line` | `ming_sim/db.py:22411`（定义）；`ming_sim/materials.py:785`（现役消费者） |
| `_load_secret_order_body_row` | `ming_sim/db.py:22422`（定义）；`22406`,`22414`,`22438` |
| `_append_secret_order_line` | `ming_sim/db.py:22429`（定义；内调已不存在的 `_write_secret_order_body`） |

**复扫（施工后）**：同上命令 → 无匹配（CLEARED）。

### R2：说明文字及解析失败被提升为真实罪证（P1）

**根因**：合并后 `seed_guilt_counts_as_debt` 变成「crime/severity 非精确『无』即有罪」，且 JSON 解析失败/非对象返回 True。说明散文承重，违反 ADR0142 / ADR0098 / 底座权威。

**修法**：恢复底座权威实现——只认 `severity ∈ {轻,中,重}`；crime 说明不承重；解析失败/非对象/空 → False。消费者 `live_investigation_fact_keys` 不变。

**全仓枚举命令**：

```bash
rg -n --no-heading -g '*.py' 'seed_guilt_counts_as_debt'
```

**成员表**：

| 位置 | 角色 |
|---|---|
| `ming_sim/covert_progress.py:152`（修后） | 定义（已恢复结构化判据） |
| `ming_sim/covert_progress.py:872` | 现役消费者（`live_investigation_fact_keys`） |
| `tests/test_secret_order_payoff_1504.py` | 结构化负向契约（保留并加强；删重复末定义） |

**复扫**：仅上表残留；谓词已为 severity 白名单。

### R3：退休领域机制及未消费替身未清退（P2）

**根因**：固定推进 / `progress|reason_code|used` 旧查案形状、`terminal_report_facade`、`latest_monthly_memorial` 等搬迁后无生产消费者，却随合并回到生产模块。

**修法**：优先删除，不补常量、不重接调用。

**全仓枚举命令**：

```bash
rg -n --no-heading -g '*.py' \
  'terminal_report_facade|latest_monthly_memorial|target_progress_units|read_substantiated_legal_reason_code|_substantiate_lane|advance_investigation_lanes|mark_investigation_fact_used|DEFAULT_SUBSTANTIATION|_TERMINAL_REPORT_FACADE'
```

**施工前完整成员表**：

| 符号 | 位置 | 处置 |
|---|---|---|
| `target_progress_units` | `covert_progress.py:153`；测试 import/断言 | 删定义与专属测 |
| `read_substantiated_legal_reason_code` | `covert_progress.py:1392`；测试 import | 删 |
| `_substantiate_lane` | `covert_progress.py:2176` 及内部调用 | 删 |
| `advance_investigation_lanes` | `covert_progress.py:2185` | 删 |
| `mark_investigation_fact_used` | `covert_progress.py:2220` | 删 |
| `DEFAULT_SUBSTANTIATION_REASON` | 仅被 `_substantiate_lane` 引用（未定义常量） | 随删 |
| `terminal_report_facade` | `decree_vocabulary.py:233`；`due_review.py:22` 悬空导入 | 删定义+导入 |
| `_TERMINAL_REPORT_FACADE_*` | `decree_vocabulary.py:215–222` | 随 facade 删 |
| `latest_monthly_memorial` | `supervision.py:242`（无消费者） | 删 |

**复扫**：同上命令 → CLEARED。  
`PERSON_LEGAL_REASON_CODES` 仍留在 `person_archive_contract.py`（领域词表真源；本轮退休消费者已尽删，未另造调用）。

### R4：测试覆盖、权威与成本失真（P2）

**根因**：payoff 三组同名定义末定义覆盖前定义（把「血债不得造罪」钉成绿灯）；另有 helper-only、退休机制专属、memorial_text 盯文与字段 spy。

**修法**：
- 删除 payoff 重复/helper-only/退休专属案（`actual_units_share`、重复 decide/seed_guilt/task_specific、`target_units_min_one`、`zero_target`）
- **保留**真实入口 `test_settle_due_close_follows_surviving_memorial_and_actual`
- **保留并加强**唯一的 `test_seed_guilt_structured_clean_vs_debt`（结构化负向契约）
- monthly：去掉 memorial_text 字符串锁与 `read_fields` spy；改断言结构化 turn/band + 材料载体存在
- execution_pressure：去掉 `payload["text"] == revised_text` 盯文，改非空结构化字段
- audience_reopen：去掉 `query in read_material` 盯文；保留载体存在与查访月报路径负向
- **保留** declaration landing 的 Event/Future 确定性握手用例（判词已驳回删测）

**全仓枚举命令**：

```bash
python3 - <<'PY'
import ast
from collections import defaultdict
from pathlib import Path
p=Path('tests/test_secret_order_payoff_1504.py')
tree=ast.parse(p.read_text())
locs=defaultdict(list)
for n in tree.body:
    if isinstance(n, ast.FunctionDef) and n.name.startswith('test_'):
        locs[n.name].append(n.lineno)
print([(k,v) for k,v in locs.items() if len(v)>1])
PY
rg -n 'memorial_text|read_fields|assert query in read_material|assert payload\["text"\] ==' \
  tests/test_secret_order_monthly_progress_566.py \
  tests/test_execution_pressure_654.py \
  tests/test_audience_translate_1837_reopen.py
```

**施工前重复定义成员**：

| 测试名 | 行号 |
|---|---|
| `test_seed_guilt_structured_clean_vs_debt` | 232 / 2765 |
| `test_decide_settlement_delivery_gap_bidirectional` | 242 / 2748 |
| `test_task_specific_contract_from_explicit_fields_not_tags` | 260 / 2811 |

**复扫**：AST 重名 → `none`；Event/Future 握手仍在 `tests/test_secret_order_declaration_landing_1897.py:119–152,306–334`。

## 判词 finding 逐条处置

| 来源 | 处置 |
|---|---|
| Completeness C1 / Correctness C1 → R1 | 已清退旧账轨与材料读口；复扫空 |
| Completeness C2 / Correctness C2 → R2 | 已恢复 severity 白名单；探针证实无罪者不入 truth_keys |
| Completeness C3 / Correctness C4 → R3 | 已删退休 helper/facade/未消费替身；复扫空 |
| Completeness C4 / Correctness C3 → R4 | 已删重复/helper/盯文/spy；保留必要结构化负向与 settle 真实入口案 |
| Correctness C5（删 Event/Future） | **驳回维持**：未删握手用例 |
| 事件结局三失败 | 按判词转 #1873，本片不恢复功能 |
| 名册 ValueError / #1873 | 未冒称本票修复 |

## 变异观察（临时真实入口；已清理）

环境前缀：七个 `MING_SIM_*_BIN=/usr/bin/false` + `PYTHONDONTWRITEBYTECODE=1`。  
探针脚本仅落 `/tmp/1897-fixer-r1-r4-probe/`，用后删除。

**R1 新逻辑**：

```json
{"r1": {"report_write": true, "canonical_report_turns": [1], "has_advanced_tag": true, "has_pending_tag": false, "text_log_column_present": false}}
```

**R1 装回旧 period_line 读口（恒 False）**：

```json
{"r1_old_reader": {"has_pending_tag": true}}
```

→ 旧红新绿。

**R2 新逻辑**：

```json
{"r2_predicate": {"clean_severity_none": false, "prose_blood": false, "bad_json": false, "non_object": false, "structured_mid": true},
 "r2_live_keys": [
   {"name": "吴三桂", "severity": "无", "name_in_keys": false},
   {"name": "温体仁", "severity": "无", "name_in_keys": false},
   {"name": "洪承畴", "severity": "无", "name_in_keys": false}
 ]}
```

**R2 装回旧散文造罪谓词**：

```json
{"r2_old_logic": {"prose_blood": true, "clean_severity_none": true,
 "targets": [{"name": "吴三桂", "name_in_keys": true}, {"name": "温体仁", "name_in_keys": true}, {"name": "洪承畴", "name_in_keys": true}]}}
```

→ 旧红新绿。未新增永久证明测试。

## 聚焦测试

```bash
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
  ../Ming_LLM/.venv/bin/python -m pytest \
  tests/test_secret_order_declaration_landing_1897.py \
  tests/test_secret_order_payoff_1504.py \
  tests/test_secret_order_monthly_progress_566.py \
  tests/test_secret_order_section_rejections.py \
  tests/test_execution_pressure_654.py \
  tests/test_audience_translate_1837_reopen.py \
  tests/test_declaration_dispatch_1835.py \
  tests/test_staged_assignment_identity_1890.py \
  tests/test_due_review_621.py \
  tests/test_dossier_reported_progress_619.py \
  tests/test_deformation_dual_rail_622.py \
  -q -p no:cacheprovider --basetemp=/private/tmp/1897-fixer-r1-r4-pytest --tb=line
```

实测输出：`263 passed in 6.79s`（`/usr/bin/time -p`：real 7.27 / user 4.85 / sys 1.74）。  
用例数少于判词底座的 266，因删除重复/helper/退休专属测。未跑全量。临时 basetemp 已删。

## 质量 / 合法性自检

- 净变更：`10 files changed, 40 insertions(+), 410 deletions(-)` — 以删除/复用权威为主
- 未新增兼容层、恢复协议、账本层、生产测试钩子、平行证明测试
- 未篡改 Soul/宪法；未改宿主配置
- 自查二连：同类型（旧账轨/散文承重/退休替身/测试失真）已整类扫完；引入面（材料读口、罪情入集、悬空导入、重名覆盖）已用探针+聚焦测核过
- diff-check：本轮修理 diff 无空白告警

## 剩余项

1. **须在新 HEAD `b99c0ef3d` 上全范围复审**（判词 `reviewGate`：R2 涉 P1，不能援引仅修 P2 的免候例外；需 reviewer 席无未结 P2+ finding 辅证）
2. 事件结局缺口、名册拒收等仍按 #1812/#1873 线索处置，不在本片冒称结清
3. 本提交仅存在于工作树分支，**尚未 merge**；完成态以 merge 事实为准
