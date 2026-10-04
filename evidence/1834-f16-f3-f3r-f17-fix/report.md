# #1834 修内司回执 · F16 / F3 / F3-R / F17（末判 ee3b5da31）

**工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1834-w5`  
**分支**：`ak-roles/1834-f16-f3-f3r-f17-ee3b5da31`  
**基线**：`ee3b5da312c5832720d89aee707fe4c7669c5eb0`  
**判词真源**：`attachments/02-1834-judge-ee3b5da31.json` 末份 payload（四类未结）

**共同测试前缀（七变量，实写）**：

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false
```

官方方向检索：Python `str.strip` 删除首尾空白（docs.python.org）；LLM 回归应断言属性/语义而非入口外裁字。裁决仍以本仓真实入口为准。

---

## 1. F16「自由正文搬运仍改写原文」

### 类定义（判词 + 票面，未收窄）

供料及其写入路径中，对自由正文做 strip / 切片 / 改写后再落库或供出；机器键规范化与局部判空副本不禁。

### 枚举命令

```bash
# 广扫（切片/strip/replace）
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
bash -c '{
  rg -n "\[:\d+\]" ming_sim --glob "*.py"
  rg -n "strip\(\)\[:|\.strip\(\)\[" ming_sim --glob "*.py"
  rg -n "\.strip\(\)" ming_sim --glob "*.py"
  rg -n "\.replace\(|re\.sub\(|\.lstrip\(|\.rstrip\(" ming_sim --glob "*.py"
}' > evidence/1834-f16-f3-f3r-f17-fix/enum_f16_all_candidates.txt

# 供料写路径 AST：dict/assign 自由正文键带 strip
# → enum_f16_supply_path.tsv（施工前）/ enum_f16_supply_path_after.tsv（施工后）
```

### 根因

长度裁剪已删，但多处仍把 LLM/声明自由正文 `.strip()` 后写入 stages / 请旨 / 事务名起因 / 到期复核材料，局部判空与落库未分离。

### 成员表（FIX）

| 成员 | 处置 |
| --- | --- |
| `staged_commitment.normalize_commitment_stages` criterion/origin | 存 raw；判空用副本 |
| `staged_commitment` 到期拨帑 title/criterion/origin | 同上 |
| `settlement_payload.parse_decision_blocks` title/label/context/hint | 存 raw；判空/绑定键用 strip 副本 |
| `month_chain._question_as_decision` / `_answer_from_row` | 自由正文 raw |
| `affair` 声明 attach=new 与 `AffairStore.open` name/origin | 材料盘面真源 raw |
| `due_review` criterion/origin_context | raw |
| `issues` 弹劾候选 decree_text/execution_note | raw |
| `db` initiative body、secret title、station、purpose、reconciliation note、credit context、appointment reason | 自由正文 raw；target_id/assignee 等机器键仍 strip |

### KEEP（有依据；非本类未修自由正文改写）

| 候选 | 保留依据 |
| --- | --- |
| stages JSON 外壳 `text=raw.strip()` | 机读 JSON 信封判空，非段内正文 |
| `bind_decision_options` label strip 作键 | 选项绑定机器键 |
| event_id/origin_ref/station_region/controlled_by/assignee/name 查找 | 机器键/身份 |
| materials `current_root` path strip | 路径身份，非供料正文 |
| region/army/building change-log `reason[:80]`、power `reason[:120]` | 仅日志载体；盘面自由字段已去 strip（上轮 KEEP 口径） |
| breach_plea `decode_plea_meta` strip | 机读 `_META_PREFIX` 协议头 |
| CLI/input/`shutil.which` 等 | 非材料写入 |
| 人物名 strip 查库 | 身份键 |

施工后仍见 strip 的 FREE 键多数属上表 KEEP；未对 log-only 长度切片另开机制。

---

## 2. F3「测试清理再次误删独立契约」

### 类定义

本票测试清理把**独立检查**误判为冗余删除；不是要求保全旧功能。

### 枚举命令

```bash
git show 1e9b6d1b1 -- tests/ | rg '^\-.*assert'
# 逐项对照删除后剩余断言的对象/蕴含（见下表）
```

### 成员表

| 删除点（1e9b6d1b1） | 语义 | 处置 |
| --- | --- | --- |
| `test_promulgation_judge_561` `许誉卿 in gatekeepers` | before==after **不蕴含**成员存在 | **RESTORE** |
| `臣遵旨 in text` | 已由全文 `==` 蕴含 | KEEP_DELETED（真重复） |
| `dossier in TARGET_KINDS` | 全集 `==` 蕴含 | KEEP_DELETED |
| 机构名/大臣 not in ids | `ids == ["毕自严"]` 蕴含 | KEEP_DELETED |
| `rejected not in item` | `item == {...}` 蕴含 | KEEP_DELETED |
| origin `\|round:` substring | 全串 `==` 蕴含 | KEEP_DELETED |
| `trail_write not in order` | `order == ["barrier_start"]` 蕴含 | KEEP_DELETED |
| `幽灵指标 not in` | `metrics == fresh` 蕴含 | KEEP_DELETED |

---

## 3. F3-R「语义复核被自动 KEEP 代替，真重复仍留存」

### 类定义

同主体弱断言已被强断言逻辑蕴含则删弱；时序检查点不算重复。禁止用候选形状自动 KEEP 冒充逐项语义。

### 枚举命令

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
../Ming_LLM/.venv/bin/python evidence/1834-f16-f3-f3r-f17-fix/scripts/enum_f3r_ast.py

MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
../Ming_LLM/.venv/bin/python evidence/1834-f16-f3-f3r-f17-fix/scripts/dispose_f3r_semantic.py
```

落盘：`enum_f3r_py_all_candidates.txt`（332）、`enum_f3r_js_all_candidates.txt`（55）、`enum_f3r_disposition.tsv`（389；KEEP 387 + ENUM_ARTIFACT 2）。旧 `dispose_f3r_candidates.py` 形状自动 KEEP **已撤销**（见 `F17_F3R_REVOCATION.txt`）。

### 本轮删除的真重复（逐项语义）

| 文件 | 弱断言 | 依据 |
| --- | --- | --- |
| `test_qa_h1_seed_data` | `"旧部" not in` after `== "毛文龙"` | 字面蕴含 |
| `test_execution_joint_liability_565` | not-in after dict/set `==` | 容器蕴含 |
| `test_authority_ledger_611` | bare/payload not-in after list/`==` | 蕴含 |
| `test_mutiny_actual_residence_659` | region not-in after set `==` | 蕴含 |
| `test_executor_routing_721` | `"陈新甲" not in` after `== ["毕自严"]` | 蕴含 |
| `test_rescript_heal_isolation_1801` | heal tag not-in after `tags == [...]` | 蕴含 |
| `test_office_rank_562` | 革职/原 前缀 | 字面蕴含 |
| `test_pihong_dossier_1490` | 伪造标题 / 另旨·中旨 | 字面蕴含 |
| `test_promulgation_judge_561` | fresh-authorization not-in | 列表 `==` 蕴含 |
| `test_qa_t1_extraction_dual_source_1353` | stale id not-in | set `==` 蕴含 |
| `test_impeachment_surge_655` | delegator not-in participants | 列表 `==` 蕴含 |
| `test_opening_gazette_delete_1356` | 标记 `in kept` after `kept == real` | 蕴含 |

### KEEP 样例（非形状自动）

| 候选 | 依据 |
| --- | --- |
| `test_month_chain_1847` empty feed vs post-resume | **不同时点** |
| `test_audience_translate_1837` noise not-in after shape `==` | 相等不蕴含键集 |
| `许誉卿 in` then before==after | **F3 独立契约**（相等不蕴含成员） |
| DUPLICATE_ASSERT 有 intervening call | 阶段/突变检查点 |
| LEN_THEN_EQ | 不同主体 |
| JS waitFor / distinct property | 异步或不同属性 |

---

## 4. F17「所谓真实入口变异并未装回旧生产逻辑」

### 根因

旧 `mutation_old_red.py` 入口外裁短结果、预裁 `reason[:240]`、比较局部裁字；`probe_four_class.py` 用源码字段名措辞冒充未改写。

### 撤销证明清单（历史输出保留不改写）

| 失效证据 | 说明 |
| --- | --- |
| `evidence/1834-four-class-fix/mutation_old_red.py` + `.json` | 未装回旧生产逻辑 |
| `probe_four_class.py` `free_prose_no_strip` | 源码措辞证明 |
| `report.md` F16/F3-R「未结：无」 | 失实结清（已附 REVOKED 段） |
| `dispose_f3r_candidates.py` 410 KEEP | 形状自动 KEEP |

### 本轮真实变异

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
../Ming_LLM/.venv/bin/python evidence/1834-f16-f3-f3r-f17-fix/scripts/mutation_real_old_red.py
# → mutation_old_red.json：method=replace_production_symbol_with_old_implementation
#    F15 clean=false；F16 staged/decision preserved=false；verdict=true；exit=0

MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
../Ming_LLM/.venv/bin/python evidence/1834-f16-f3-f3r-f17-fix/scripts/probe_new_green.py
# → probe_new_green.json：staged/json/decision context+hint preserved=true；ok=true
```

方法：进程内把 `normalize_commitment_stages` / `parse_decision_blocks` / `affair_ids_for_dossiers` **替换为旧实现**；输入完整 `"\n  逐项核实边饷。  \n"`，不预裁、不入口外后裁。

---

## 聚焦测试（不全量）

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
../Ming_LLM/.venv/bin/python -m pytest \
  tests/test_world_materials_1834.py tests/test_candidate_supply_1893.py \
  tests/test_material_directory_1830.py tests/test_scene_llm_1836.py \
  tests/test_player_payload_1022.py tests/test_cli_runner_error_typed_1299.py \
  tests/test_dossier_reported_progress_619.py tests/test_staged_assignment_identity_1890.py \
  tests/test_promulgation_judge_561.py tests/test_qa_h1_seed_data.py \
  tests/test_execution_joint_liability_565.py tests/test_authority_ledger_611.py \
  tests/test_mutiny_actual_residence_659.py tests/test_executor_routing_721.py \
  tests/test_rescript_heal_isolation_1801.py tests/test_office_rank_562.py \
  tests/test_opening_gazette_delete_1356.py tests/test_pihong_dossier_1490.py \
  tests/test_impeachment_surge_655.py tests/test_qa_t1_extraction_dual_source_1353.py \
  tests/test_due_review_621.py \
  -q -p no:cacheprovider --basetemp=/tmp/1834-fixer-f16-f3-pytest
```

**实测**：`305 passed in 37.80s`（`real 38.45`）→ `pytest_focus.txt`  
复检（affair open 后）：`95 passed in 6.38s` → `pytest_recheck.txt`

邻票 `test_commitment_progress_contexts_are_structured` NameError 依判词交 #1873，不夹入。

---

## 自审复检

- 未新增机制 / 永久证明测试 / 分类层；优先删弱断言与去 strip。
- 未 stash/amend/push/PR；未改 AGENTS/CLAUDE/ADR 法源。
- 历史 evidence 输出保留；以撤销说明标失效。
- F16 不宣称「全仓一切 strip 已绝」——机器键/判空/路径/日志 KEEP 有表；供料写路径点名类与同类自由正文已修。
- F3-R 不宣称形状扫描即全清；处置表逐行带对象/时点/蕴含依据，真重复已删。

## 未结范围（诚实）

- log-only `reason[:80]/[:120]` 长度切片未拆（明确不进材料盘面）。
- `covert_progress` / 部分 issues 人物名查找 strip 仍作身份键。
- #1873 NameError 测试红不阻本片。
- 不以「成员表为空」冒充全清；以类定义 + 枚举 + 逐项语义为准。

自查二连 done。
