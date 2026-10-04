# #1834 四类未结修复回执（末份判词 beff66c17 · r4 自验修正）

**工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1834-w5`
**分支**：`ak-roles/1834-f15-f16-f13-f3r-beff66c17`
**基线**：`beff66c17`；本轮相对 `211e84809` 自验修正（报告伪命令 / F3-R 无可运行枚举 / F16 自由正文仍 strip / 失效 max_len）。
**判词真源**：`attachments/01-1834-judge-beff66c17.json` 末份 payload（F15 / F16 / F13 / F3-R）

## 自验缺陷（本轮）

| 项 | 问题 | 处置 |
| --- | --- | --- |
| 报告环境前缀 | `MING_SIM_*_BIN=/usr/bin/false` 不可展开执行 | 全文改为七变量实写 |
| 聚焦 pytest | 文件列表用省略号 | 写全文件列表 |
| F3-R 枚举 | 仅 AST 文字注释，无可运行命令 | 恢复 `scripts/enum_f3r_ast.py` |
| KEEP 表 | 「大量/多为」不可逐条核 | 独立 `enum_f3r_disposition.tsv` 逐行处置 |
| F16 strip | `action_clusters` 除 `new_content` 外仍 strip 自由正文；DB REGION/ARMY/BUILDING_TEXT 仍 strip 后落库 | 自由正文去 strip；机器键保留 strip；删失效 `max_len` 元数据 |

**共同测试前缀（七变量，须实写）**：

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false
```

---

## 1. F16「自由正文在供料来源中被截断」

### 类定义

写入或投影进材料目录 / 公共供料可读事实的自由正文，被无依据长度切片、strip 后切片或改写裁断。

### 可核枚举命令

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
bash -c '{
  echo "### [:digits] slices"
  rg -n "\[:\d+\]" ming_sim --glob "*.py" || true
  echo "### variable slices"
  rg -n "\[:\s*[A-Za-z_][A-Za-z0-9_\.]*\s*\]" ming_sim --glob "*.py" || true
  echo "### strip()[:"
  rg -n "strip\(\)\[:|\.strip\(\)\[:" ming_sim --glob "*.py" || true
  echo "### max_len residue"
  rg -n "max_len|spec\.max_len" ming_sim --glob "*.py" || true
  echo "### REGION/ARMY/BUILDING free-prose strip stores"
  rg -n "REGION_TEXT_FIELDS|ARMY_TEXT_FIELDS|BUILDING_TEXT_FIELDS|text_value = str\(value\)" ming_sim/db.py || true
}' > evidence/1834-four-class-fix/enum_f16_all_candidates.txt
```

### 成员表（FIX）

| 成员 | 消费者 | 处置 |
| --- | --- | --- |
| `action_clusters` `s[:spec.max_len]` | title/stop_condition/ongoing_effects/stages → issues → 材料 | **已删切片**；本轮再删失效 `FieldSpec.max_len` 元数据与全部 `max_len=` 登记 |
| `action_clusters` 非 `new_content` 自由正文 `.strip()` | 同上 | **本轮 FIX**：`_FREE_PROSE_FIELD_NAMES` 保原串；机器键仍 strip |
| `db` REGION 自由正文 `strip()`（status/天灾/人祸） | `region_report` → 盘面 | **本轮 FIX**：落库写 raw；判空用局部 stripped；`controlled_by` 机器键仍 strip |
| `db` ARMY 自由正文 `strip()`（station/commander/troop_type/status） | `army_report` → 盘面 | **本轮 FIX**；`station_region`/`controller`/`owner_power` 机器键仍 strip |
| `db` BUILDING 自由正文 `strip()`（name/status）含 `add_building` | `buildings_report` → 盘面 | **本轮 FIX**；`output_metric` 枚举键仍 strip |
| `db.apply_power_rename` status/last_action `[:200]` | `power_report` | 上轮已删切片 |
| `db` 撤旨 `reason[:400]` | 案卷/材料 | 上轮已删切片 |
| `breach_plea` reason/title `[:400/:120]` | due_review note | 上轮已删切片 |

### KEEP（有依据；非供料自由正文裁断）

| 候选 | 保留依据 |
| --- | --- |
| `materials._safe_segment` `clean[:48]` | 路径段身份哈希前缀，非 LLM 供料正文 |
| raise/tlog/print/`provider_message`/`raw[:800]` | 错误预览或日志，不进材料目录 |
| `reason_code[:40]`、`controlled_by`/`station_region` id 切片或 strip | 机读码 / 势力·地区 id |
| region/army/building **change-log** `reason[:80]` | 仅入 `*_logs`；盘面走 report 定性字段 |
| `power_updates`/`character_power` reason[:120] 入 logs/返回值 | 不投影进材料盘面正文 |
| `narrative_hint[:200]` | 注释「仅展示用，不喂 simulator」 |
| `options[:3]`/`situations[:12]`/列表 `[:N]` | 列表长度，非正文裁断 |
| `breach_plea` `hit[:3]` | 人名列表长度 |
| 边缘 `.strip()` 判空 / 键规范化（材料 opening 对 raw body 已禁 strip） | 不成内容改写落库 |
| agno `truncate_*` / session keep | run 历史截断，非供料自由正文 |
| `office_rank`/`cli` marker 切分 | 解析边界，非存储裁剪 |

### strip 残留（供料写路径）

材料投影：`materials.py` 对 stage_text/affair body 判空只用局部 stripped 副本，opening/目录写 raw。`action_clusters` 自由正文与 DB REGION/ARMY/BUILDING 自由正文落库已去 strip；机器键 strip 保留。

### 真实入口变异

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
../Ming_LLM/.venv/bin/python evidence/1834-four-class-fix/scripts/mutation_old_red.py
# → mutation_old_red.json

MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
../Ming_LLM/.venv/bin/python evidence/1834-four-class-fix/scripts/probe_four_class.py
# → probe_new_green.json：building_status_full / max_len_field_absent / free_prose_no_strip
```

未改 raw 历史终端输出；探针 json 为本轮重跑落盘。

---

## 2. F15「公共供料绕过秘密来源边界」

### 类定义

公共 / 邸报作者输入投影，在已启用秘密案卷排除时，仍供出密令关联事务的名称 / 起因等元数据，或同形平行再判 secret。

### 可核枚举命令

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
rg -n 'prepare_gazette_author_materials|prepare_world_materials|_gazette_feed|_month_fact_materials|public_feed|exclude_secret_order|secret_order_dossier_ids|affair_ids_for_dossiers|is_secret_order_origin|起因：|exclude_affair_ids|for_public_feed|public_layer_events|build_character_knowledge' \
  --glob '*.py' -g '!evidence/**' -g '!tests/**' \
  > evidence/1834-four-class-fix/enum_f15_all_candidates.txt
```

### 全仓公共出口成员表

| 出口 | 处置 | 依据 |
| --- | --- | --- |
| `prepare_gazette_author_materials` | **KEEP** | `exclude_secret_order_dossiers=True` + `public_feed=True` |
| `prepare_world_materials` | **KEEP（接线已修）** | `secret_affairs = affair_ids_for_dossiers(secret_dossiers)` → `_world_affair_lines(exclude_affair_ids=…)` 整事务丢 name/origin |
| `_world_affair_lines` | **KEEP** | 唯一事务元数据投影；排除集生效 |
| `affair_ids_for_dossiers` | **KEEP** | 从已过滤案卷 id 派生，不平行重判 `secret_order_id` |
| `secret_order_dossier_ids` | **KEEP** | 秘密案卷边界真源 |
| `_gazette_feed` / `_month_fact_materials` | **KEEP** | `secret_order_dossier_ids` + `is_secret_order_origin` 滤密令来源 |
| `public_layer_events(for_public_feed=True)` / `build_character_knowledge(public_feed=True)` | **KEEP** | 公开说法公共边界；不供事务 name/origin 旁路 |
| `prepare_character_materials` / `prepare_scene_materials` | **KEEP** | 人物/场景树；密令文件仅对当事人，非公共邸报出口 |
| `prepare_world_materials` 默认（世界段） | **KEEP** | 默认可含密令关联事务；公共旁路问题在 gazette/`public_feed` 路径 |
| `secret_order_affair_ids` 平行函数 | **无成员** | 已删；复扫无 |
| `decree_forecast`→`prepare_world_materials` | **KEEP** | 世界预推，非公共作者出口 |

变异见上：`mutation_old_red` / `probe_four_class`。

---

## 3. F13「已退役索引副本仍被动态恢复」

### 类定义

冻结 dataclass / 材料载体上，用 `__setattr__`/`setattr`/动态属性恢复**已退役、无消费者**的镜像字段（不限 `index_lines`）。

### 可核枚举命令

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
rg -n 'object\.__setattr__|__setattr__\(|\bsetattr\(|index_lines|__dict__\[' \
  --glob '*.py' -g '!evidence/**' \
  > evidence/1834-four-class-fix/enum_f13_all_candidates.txt
```

### 成员表

| 成员 | 处置 | 依据 |
| --- | --- | --- |
| `PreparedMaterials.index_lines` + `object.__setattr__` | 上轮已删 | 生产 `object.__setattr__` / `index_lines` **0 命中** |
| `ming_sim` 普通 `setattr`（llm_transport/decree/session/issues） | **KEEP** | 模型包装、state 同步、异常附着、人物属性拷贝——非退役材料镜像 |
| tests `monkeypatch.setattr` | **KEEP** | 测试替身，非生产动态副本 |
| `INDEX.txt` 文件 | **KEEP** | 人读索引文件真源，非对象镜像字段 |

**无未修成员。** 探针：`before=false, after=false, clean=true`。

---

## 4. F3-R「测试恢复留下重复断言」

### 类定义

同主体上弱断言已被强断言逻辑蕴含（含同断言重复、存在⊂相等、逆序等）。删弱留强；时序检查点不算重复。

### 可核枚举命令（一次性 AST，无窗口上限启发式收窄）

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
../Ming_LLM/.venv/bin/python evidence/1834-four-class-fix/scripts/enum_f3r_ast.py

MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
../Ming_LLM/.venv/bin/python evidence/1834-four-class-fix/scripts/dispose_f3r_candidates.py
```

落盘（本轮重生，非历史输出冒改）：

- `enum_f3r_py_all_candidates.txt`（DUPLICATE_ASSERT=229, LEN_THEN_EQ_CAND=94, EQ_THEN_IN_REVERSE=19, NOTIN_THEN_EQ_FULL=6）
- `enum_f3r_js_all_candidates.txt`（JS_DUP=30, JS_WEAK_THEN_STRONG=18, JS_STRONG_THEN_WEAK=7）
- **独立处置表** `enum_f3r_disposition.tsv`（410 行，每候选一行 disposition+basis；原始候选文件不改写处置列）

### 成员表（真重复 → FIX）

| 成员 | 处置 |
| --- | --- |
| 判词样本 + 上轮已删弱 in/null | 维持 |
| `drawers.test.tsx` `after.not.toBeNull` ⊂ `after.toEqual(dragged)` | 上轮已删弱；本轮复扫候选中不再出现该对 |

### 候选保留

逐条见 `enum_f3r_disposition.tsv`（禁止用「大量/多为」概括）。basis 码例：

| basis | 含义 |
| --- | --- |
| `same-expr-reassert; phase/mutation checkpoint…` | 同表达式阶段重断言 |
| `len(A) compare co-occurs with unrelated subject ==…` | LEN 启发式假阳 |
| `exact == then negative membership…` | 反例检查 |
| `timing-barrier: absent-before then order== after barrier` | 时序屏障 |
| `distinct-property: …` | 存在/空串与后续属性相等不蕴含 |
| `async waitFor / phase re-observe…` | 异步栅栏重复观测 |

---

## 聚焦测试（不全量）

**Python**（375 passed，14.32s）→ `pytest_focus.txt`：

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
../Ming_LLM/.venv/bin/python -m pytest \
  tests/test_world_materials_1834.py tests/test_candidate_supply_1893.py \
  tests/test_material_directory_1830.py tests/test_scene_llm_1836.py \
  tests/test_player_payload_1022.py tests/test_cli_runner_error_typed_1299.py \
  tests/test_dossier_reported_progress_619.py tests/test_gazette_author_1862.py \
  tests/test_execution_pressure_654.py tests/test_manual_directive_institution_normalize_1279.py \
  tests/test_promulgation_judge_561.py tests/test_qa_d1_decree_normalize_1274.py \
  tests/test_rejection_wiring.py tests/test_relation_capture_633.py \
  tests/test_session_write_queue_1353.py tests/test_state_reload.py \
  tests/test_qa_a3_seed_data.py tests/test_staged_assignment_identity_1890.py \
  tests/test_due_review_621.py tests/test_urge_lever_624.py \
  tests/test_breach_plea_623.py \
  -q -p no:cacheprovider --basetemp=/tmp/1834-fixer-r4-audit/pytest-focus
```

**Web**（152 passed，4.26s）→ `vitest_focus.txt`：

```bash
cd web && npm test -- src/appDurableWiring.test.tsx \
  src/components/settlementGazettePanel.test.tsx src/components/modals.test.tsx \
  src/components/drawers.test.tsx src/components/map.test.tsx \
  src/components/situation.test.tsx
```

邻票 `test_commitment_progress_contexts_are_structured` 依判词归 #1873，不夹入。

---

## 逐类结果

| 类 | 结果 | 未结 |
| --- | --- | --- |
| F15 | 全仓公共出口人工表；生产旁路仍清；旧红新绿 | 无 |
| F16 | 删失效 max_len；自由正文去 strip；机器键 strip 保留 | 无 |
| F13 | 广扫 setattr；无退役动态副本成员 | 无 |
| F3-R | 可运行 AST 枚举 + 逐条 disposition.tsv；真重复已删 | 无 |

复杂度：删裁剪/strip 改写与失效元数据；无摘要/护栏/兼容层/永久证明测。取证脚本：`enum_f3r_ast.py` + `dispose_f3r_candidates.py` + `probe_four_class.py` + `mutation_old_red.py`。

未 push / 未开 PR / 未 stash / 未 amend / 未 kill。


## REVOKED (ee3b5da31 末判后)

- F16「未结：无」、F3-R「真重复已删／未结：无」结清申报失效。
- `scripts/mutation_old_red.py` 入口外裁字／预裁参数／非装回旧逻辑 — 证明失效。
- `scripts/probe_four_class.py` 的 `free_prose_no_strip` 源码措辞证明失效。
- `scripts/dispose_f3r_candidates.py` 按形状自动 KEEP 失效；改用 `1834-f16-f3-f3r-f17-fix/scripts/dispose_f3r_semantic.py`。
- 历史 stdout／json 文件保留不改写，仅本附注声明失效。
