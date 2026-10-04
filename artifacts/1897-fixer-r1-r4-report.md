# #1897 修内司 R1–R4 回执（整类自检修订）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1897-w5`
- 分支：`ak-roles/issue-1897-r1-r4-fixer-20261005-053204`
- 底座 HEAD（施工前）：`64b899a0e1682b30bc74d18688380237773251ce`
- 代码提交：
  - `b99c0ef3dc30fa9de81ad7b47add9773fcabb90d` — 初清 R1–R4
  - `496d5a959aebdc6ce2743b7d209162fe18b6492e` — 自检：删 helper-only 罪情测、改真实 `create_secret_order` 负向契约；删孤儿 `parse_covert_exec_selections`
- 本报告提交：见 `git rev-parse HEAD`（本文件入仓后）
- 派单：`.../01a1089b-50c9-7dac-ab41-8ba86b05e2c6@fixer/fix-packet.md`
- 冻结判词：`attachments/01-1897-judge-64b899a0e.json` 末 payload（`continue`）；先前 `converged` 卷仅供参考，不得沿用为当前放行
- 状态：已提交于本工作树分支；**未 push、未开 PR、未 merge**
- **未声称 reviewer 放行**；R2 涉 P1，须在新 HEAD 上全范围复审（判词 `reviewGate`）

## 授权核验

- 派单与用户明示整类修复自检 → 构成代码修改授权
- 类边界取判词 R1–R4 全文，未另立更窄谓词；点名仅为样本
- Event/Future 确定性握手用例按判词 Correctness C5 驳回删测处方 → **保留**
- 未改 Soul/宪法/宿主配置；未 stash/amend/rewrite/push/开 PR
- 权威引用：#1897 现行正文、#1812 重构验收、CLAUDE.md P6、ADR0142/0098、判词 `continue` 卷。不引用网搜结论作立法；不引用劳动 prompt 冒充 owner 原话

## 前次回执缺陷（本轮纠正）

| 问题 | 纠正 |
|---|---|
| R2 只搜 `seed_guilt_counts_as_debt` 符号 | 扩搜 guilt/crime/severity/truth_keys/fact_lane/罪情及解析失败路径；成员表含定义、消费者、content 校验、开案写口 |
| R3 只点名退休符号 | 对 `covert_progress` 全定义做消费者机械枚举；另扫 progress/reason_code/used 旧形状与 facade；保留项逐条写理由 |
| R4 AST 只扫 payoff 且盯文只 3 文件 | 授权相关 27 个测试文件 AST：重名、helper-only、自由文本锁、内部 spy；非白名单点名 |
| helper-only `seed_guilt` 测「保留并加强」 | **删除**；改真实 `create_secret_order`→`live_investigation_fact_keys`/`fact_lanes` 结构化契约 |
| R1 变异用恒 False 替身 | 临时装回读 `text_log_json` 的旧 period_line 实现；与 `list_dossier_progress` 结构化结果对照 |
| R2 live keys 未走真实开案 | 探针经 `create_secret_order` 读案卷 `fact_lanes` 与 truth_keys |
| 名册记「仍未修」 | 判词 continue 已认定名册拒收/existing_id 有当前用例辅证，不得沿用旧卷宗称未修；事件结局缺口仍转 #1873 |
| `git diff --check` 记不存在问题 | 实测仅 `artifacts/1897-fixer-r1-r4-report.md:104/165/224` trailing whitespace；本轮删尾空格并以新 commit 记录 |

## R1：旧密令正文账轨仍参与现役接缝（P2）

**类定义**：密令记录及其读取、更新接缝上的重复可写真源 / 旧正文账轨。

**根因（相对 64b899a0e）**：`text_log_json` 账族与 `_has_secret_order_period_line` 读口在现役；写口已只写 `dossier_progress_json`，材料层永远读不到当月推进。

**修法**：材料改读订单 `dossier_progress`（当月非终值月报 origin）；删除 db 旧正文账族与 schema 列；`update_secret_order_by_id` 不再写前读废旧列。

### 全仓枚举命令

```bash
rg -n --no-heading -g '*.py' \
  'text_log_json|_has_secret_order_period_line|_append_secret_order_line|_write_secret_order_body|_read_secret_order_body_before_write|_load_secret_order_body_row|_secret_order_body_log|_secret_order_period_recorded|_project_secret_order_bodies|_secret_order_kept_body|_secret_order_record_body|_SECRET_ORDER_BODY_COLUMNS'

# 读/更新接缝对照（权威载体，非旧账）
rg -n --no-heading -g '*.py' \
  'update_secret_order_by_id|update_secret_order_progress|get_active_secret_orders_for_minister|_write_secret_order_file|dossier_progress_json|list_dossier_progress|_note_secret_order_report'
```

### 施工前完整成员表（64b899a0e）

| 成员 | 位置 | 处置 |
|---|---|---|
| `_SECRET_ORDER_BODY_COLUMNS` | `ming_sim/db.py:873` | 删 |
| `_secret_order_kept_body` | `db.py:876` 定义；`22452` 调用 | 删 |
| `_secret_order_record_body` | `db.py:882`；`907`,`937` | 删 |
| `_secret_order_body_log` | `db.py:890`；`22408`,`22418`,`22441` | 删 |
| `text_log_json` | `db.py:898` 读；`1556` schema | 删列与读写 |
| `_secret_order_period_recorded` | `db.py:912`；`22417`,`22442` | 删 |
| `_project_secret_order_bodies` | `db.py:922`（无生产消费者） | 删 |
| `_read_secret_order_body_before_write` | `db.py:22057` 调用；`22404` 定义 | 删 |
| `_has_secret_order_period_line` | `db.py:22411`；`materials.py:785` 现役消费者 | 删定义；材料改 dossier_progress |
| `_load_secret_order_body_row` | `db.py:22422`；`22406`,`22414`,`22438` | 删 |
| `_append_secret_order_line` | `db.py:22429`（内调已不存在的 `_write_secret_order_body`） | 删 |

### 复扫（HEAD）

同上首条命令于 `*.py` → **无匹配（CLEARED）**。

### 保留（非旧账轨）

| 成员 | 保留理由 |
|---|---|
| `secret_orders.dossier_progress_json` / `list_dossier_progress` / `record_dossier_progress` | #566/#883 权威月报轨 |
| `secret_order_briefs.body` / `update_secret_order_by_id` 的 title/content | 密令要旨原文存取，非 progress 双真源 |
| `_write_secret_order_file` 生成的「本月已推进」标签 | UI 呈现串；判定轴是 dossier_progress 结构化字段，不是正文账 |

### 验证层级

1. 静态：全仓 rg 旧符号清空
2. 聚焦测：monthly_progress / declaration landing 等（见下）
3. 临时真实入口探针（已清理）：`create_secret_order` → `update_secret_order_progress` → `list_dossier_progress` 结构化 `advanced_struct=true`；装回旧 `text_log_json` period_line 后 `old_text_log_period_line=false`、`divergence=true`。证明轴为结构化字段，不用自由文本 tag 作唯一判据

## R2：说明文字及解析失败被提升为真实罪证（P1）

**类定义**：结构化罪情→实证集合→开案 lane；散文/坏形状不得造罪。

**根因**：合并后 `seed_guilt_counts_as_debt` 变为 crime/severity 非精确「无」即有罪，且 JSON 失败/非对象返回 True。

**修法**：恢复 `10e64fbef` 权威——仅 `severity ∈ {轻,中,重}`；crime 不承重；解析失败/非对象/空 → False。

### 全仓枚举命令

```bash
rg -n --no-heading -g '*.py' \
  'seed_guilt_counts_as_debt|seed_guilt|live_investigation_fact_keys|fact_lanes|FACT_LANES_KEY|truth_keys|罪情|severity|_DEBT_SEVERITIES|seed_investigation_fact_lanes'

# 解析失败 / 散文造罪形态
rg -n --no-heading -g 'ming_sim/*.py' \
  'json\.loads\(.*seed_guilt|except.*seed_guilt|crime\s*==|severity\s*==|return True'
```

### 完整成员表与处置

| 成员 | 角色 | 处置 |
|---|---|---|
| `seed_guilt_counts_as_debt` | 唯一入罪谓词 | **已恢复** severity 白名单 |
| `_DEBT_SEVERITIES` | 白名单 | 保留 |
| `live_investigation_fact_keys` | 实证集合读口 | 保留（消费谓词） |
| `seed_investigation_fact_lanes` / `_write_fact_lanes` | 开案铺 lane | 保留（经 create_secret_order） |
| `db.create_secret_order` → seed lanes | 开案写口 | 保留 |
| `content.py` seed_guilt 校验 | 设定装载：severity∈{无,轻,中,重} | **保留**（装载契约，不造运行时散文罪） |
| `_seed_guilt_storage_value` | 存储规范化 | **保留** |
| `qualitative.disaster_severity_band` 等 | 他域 severity | **保留**（非罪情→开案链） |
| helper-only `test_seed_guilt_structured_clean_vs_debt` | 失真测 | **删除** |
| `test_create_secret_order_fact_lanes_follow_structured_severity_only` | 真实入口负向 | **新增** |

### 验证层级

1. 谓词静态：`return severity in _DEBT_SEVERITIES`
2. 永久测：真实 `_issue`/`create_secret_order` 后断言 `target in live_investigation_fact_keys` 与 `target in fact_lanes`
3. 临时探针：吴三桂/温体仁/洪承畴 severity=无 → create 后 `name_in_truth_keys=false`、`name_in_fact_lanes=false`；装回旧散文谓词后对「查无实据/severity=无」create → 二者均 true

## R3：退休领域机制及未消费替身未清退（P2）

**类定义**：搬迁后被替代代码及其附属物（密令成案/进展域），优先删除，不补常量、不重接调用。

### 全仓枚举命令

```bash
# 判词点名 + 旧形状
rg -n --no-heading -g '*.py' \
  'terminal_report_facade|latest_monthly_memorial|target_progress_units|read_substantiated_legal_reason_code|_substantiate_lane|advance_investigation_lanes|mark_investigation_fact_used|DEFAULT_SUBSTANTIATION|_TERMINAL_REPORT_FACADE|parse_covert_exec_selections|密令执行态'

# 模块全定义消费者（机械）
python3 - <<'PY'
# 见本轮执行：对 ming_sim/covert_progress.py 顶层 def/assign 做全仓引用计数
# 输出 ORPHAN_OR_TEST_ONLY / NO_PROD_CONSUMER 供逐项裁定
PY
```

### 成员表

| 成员 | 施工前 | 处置 | 依据 |
|---|---|---|---|
| `target_progress_units` | 定义+测试 | **删** | 判词：仅供测试；现役 `_write_fact_lanes` 不持久化 |
| `read_substantiated_legal_reason_code` / `_substantiate_lane` / `advance_investigation_lanes` / `mark_investigation_fact_used` | 旧 progress/reason_code/used 形状 | **删** | 判词；#1896 后 mastered 轨取代 |
| `terminal_report_facade` + `_TERMINAL_REPORT_FACADE_*` | decree_vocabulary + due_review 悬空导入 | **删** | 无生产消费者；固定奏报模板退休 |
| `latest_monthly_memorial` | supervision 无消费者 | **删** | 孤儿 |
| `parse_covert_exec_selections`（含别名 `密令执行态`） | 零引用 | **删**（本轮自检） | 月链/declaration 已直读 `covert_exec_selections` 产物 |
| `build_secret_covert_effect_briefs` | 仅测试消费 | **保留** | #883 internal 档房私密输入契约；非 progress/used 旧形状；真实入口测仍用于发令月排除 |
| `contract_axes_direction` | 零引用工具 | **保留** | typed contract 轴/方向工具，非搬迁替代的进展机制 |
| `globally_used_fact_keys` | 现役 | **保留** | #1896 按 `mastered` 去重，不是旧 `used` 字段 |
| `PERSON_LEGAL_REASON_CODES` / `characters.reason_code` / 中旨 `legal_reason_code` | 他域 | **保留** | 人物档案/判决词表，非密令查案旧清算轨 |
| `tests/... "密令执行态缺失"` 标题串 | month_chain 用例标题 | **保留** | 自由标题，不是解析别名入口 |

### 复扫

退休点名符号 + `parse_covert_exec_selections` → py 无匹配。`密令执行态` 仅残留测试标题字符串（见上，保留）。

## R4：测试覆盖、权威与成本失真（P2）

**类定义**：授权改动对应的测试体系——删重复/失效 helper/盯文/内部结构断言；保留必要真实入口结构化负向；Event/Future 握手不删。

### 全仓枚举命令

```bash
python3 - <<'PY'
# 授权相关 27 文件（secret/covert/dossier/declaration/due_review/execution_pressure/
# audience_reopen/monthly/deformation/world_materials/fiscal 等）AST：
# 1) 同文件 test_ 重名  2) helper-only（调用退休/谓词 helper 且无真实入口）
# 3) 自由文本锁  4) 内部 spy
PY
```

### 成员表与处置

| 成员 | 处置 |
|---|---|
| payoff 三组同名（232/2765、242/2748、260/2811） | **已删**末覆盖定义；AST 复扫 dups=`none` |
| `actual_units_share` / 重复 decide/task_specific / `target_units_min_one` / `zero_target` | **已删**（helper/退休专属） |
| helper-only `test_seed_guilt_structured_clean_vs_debt` | **已删**；改 `test_create_secret_order_fact_lanes_follow_structured_severity_only` |
| monthly `memorial_text` 字符串锁 + `read_fields` spy | **已去**；改结构化 turn/band + 材料载体路径存在 |
| execution_pressure `payload["text"] == revised_text` | **已去**；改非空结构化字段 |
| audience_reopen `query in read_material` | **已去**；保留载体路径与查访月报负向 |
| declaration_dispatch `payload["text"] ==` 原文 | **保留**：#1897 正文原样转运契约（结构化字段等值，非盯生成散文） |
| `execution_side_read_fields` 用例 | **保留**：公开读口，非退休 helper spy |
| Event/Future 握手（declaration_landing:119–155、306+） | **保留**：判词 C5 驳回删测 |
| `test_settle_due_close_follows_surviving_memorial_and_actual` | **保留**：真实入口结案契约 |

### 复扫

授权 27 文件：within-file duplicates=`none`；helper-only=`none`。

## 判词 finding 对照

| 来源 | 处置 |
|---|---|
| C1→R1 | 旧账轨清空；材料读 dossier_progress；探针 divergence 证实 |
| C2→R2 | severity 白名单；真实 create 负向契约；探针旧谓词装回造罪 |
| C3/C4→R3 | 退休机制删除；孤儿 parse 本轮删；正当契约保留并表列理由 |
| C4/C3→R4 | 重复/helper/盯文/spy 清；握手保留；helper-only 罪情测已换真实入口 |
| C5 删 Event/Future | **驳回维持** |
| 事件结局三失败 | 按判词转 #1873，本片不恢复 |
| 名册拒收 | 不沿用旧卷称未修；不冒称本片新修 |

## 变异观察（临时；已清理）

环境前缀：七个 `MING_SIM_*_BIN=/usr/bin/false` + `PYTHONDONTWRITEBYTECODE=1`。
探针仅 `/tmp/1897-fixer-selfcheck-probe*`，用后删除。

精简复现（R1 结构化 vs 旧 text_log 读口）：

```bash
env MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
  ../Ming_LLM/.venv/bin/python - <<'PY'
# GameContent.load + bind_content + seed_static_data + sync_opening_legacies
# create_secret_order → update_secret_order_progress → list_dossier_progress
# advanced_struct from origin/turn；临时 MethodType 装回读 text_log_json 的旧 period_line
PY
```

**R1 当前（结构化）**：`progress_update_ok=true`，`list_dossier_progress` turns=`[1]`，`advanced_struct=true`，`text_log_column_present=false`

**R1 装回旧 text_log period_line**：`old_text_log_period_line=false`，`divergence=true`（不是恒 False 空替身；实现读废列）

**R2 当前（真实 create）**：吴三桂/温体仁/洪承畴 severity=无 → `name_in_truth_keys=false`，`name_in_fact_lanes=false`

**R2 装回旧散文谓词后 create**：`查无实据`+`severity=无` → truth_keys 与 fact_lanes 均 true；`prose_blood_predicate=true`

未新增永久证明测试。

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
  -q -p no:cacheprovider --basetemp=/private/tmp/1897-fixer-r1-r4-pytest2 --tb=line
```

实测（自检修后）：`263 passed in 5.71s`（`/usr/bin/time -p`：real 6.14 / user 4.34 / sys 1.40）。
未跑全量。basetemp 已删。

## 质量 / 合法性自检

- 以删除/复用权威为主；未新增兼容层、恢复协议、账本层、生产测试钩子、平行证明测试
- 自查二连：同类型整类扫完；引入面（材料读口、罪情入集、孤儿 parse、真实入口测）已核
- `git diff --check 64b899a0e HEAD`：曾仅报告本报告 104/165/224 trailing whitespace → 本文件重写去尾空格

## 剩余项 / 依法阻断

1. **须在新 HEAD 上全范围复审**（R2=P1；`reviewGate` 要求本轮 reviewer 席无未结 P2+ 辅证）。**本回执不声称已获 reviewer 放行。**
2. 事件结局功能缺口按 #1812/#1873 线索，不在本片冒称结清
3. 提交仅在工作树分支，**尚未 merge**
