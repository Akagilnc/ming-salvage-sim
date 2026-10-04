# #1834 四类未结修复回执（末份判词 beff66c17 · r2 扩枚举）

**工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1834-w5`
**分支**：`ak-roles/1834-f15-f16-f13-f3r-beff66c17`
**判词真源**：attachments `01-1834-judge-beff66c17.json` 末份 payload（F15 / F16 / F13 / F3-R）
**上轮收窄（诚实说明）**：`1e9b6d1b1` 回执把 F16 枚举收成 `[:48]/[:240]` 样本形，并把 `staged_commitment` 以「非检举/财政样本」KEEP；F15 只盯 `affair.origin` 且新造平行 `secret_order_affair_ids`（再判 `secret_order_id`）；F13 只扫 `index_lines`；F3-R 只有注释谓词无运行命令。本轮按类定义全仓重枚举，保留依据改为「无材料消费者 / 非自由正文 / 时序检查点」，禁止「不是点名样本」。

**诊断**：已读 `diagnosing-bugs`；判词已复现根因，跳过 Phase 3 重做假设。未加永久证明性测试；探针/枚举脚本仅取证。

**共同测试前缀**：

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false
```

**可运行枚举（真源脚本）**：

```bash
../Ming_LLM/.venv/bin/python evidence/1834-four-class-fix/scripts/enum_four_class.py
# → enum_f15_members.txt / enum_f16_members.txt / enum_f13_members.txt / enum_f3r_members.txt
```

---

## 1. F15「公共供料绕过秘密来源边界」

### 类定义

公共 / 邸报作者输入投影，在已启用秘密案卷排除时，仍供出密令关联事务的名称 / 起因等元数据，或任何同形「平行再判 secret」旁路。

### 枚举范围

`ming_sim/materials.py` + `ming_sim/month_chain.py` 全部公共供料出口与密令边界符号；并全仓扫平行 `secret_order_affair_ids` / `secret_order_id`+`affair_id` 再判。

### 成员表

| 成员 | 处置 | 保留/修复依据 |
| --- | --- | --- |
| `prepare_gazette_author_materials` | **KEEP** | 已传 `exclude_secret_order_dossiers=True`；缺口在世界树元数据 |
| `_gazette_feed` / `_month_fact_materials` | **KEEP** | 已用 `secret_order_dossier_ids` + `is_secret_order_origin` 滤密令来源 |
| `secret_order_dossier_ids` | **KEEP** | 唯一秘密案卷边界真源 |
| `secret_order_affair_ids`（上轮新增） | **FIX→删** | 平行重判 `secret_order_id`，违「勿第二同形 secret 规则」 |
| `affair_ids_for_dossiers(db, dossier_ids)` | **FIX→加** | 仅从**已过滤**案卷 id 派生 `affair_id`，不再读 `secret_order_id` |
| `_world_affair_lines(exclude_affair_ids=…)` | **KEEP** | 整事务丢弃 name/origin/事实 |
| `prepare_world_materials` 接线 | **FIX** | `secret_affairs = affair_ids_for_dossiers(db, secret_dossiers)` |

### 变异

```bash
../Ming_LLM/.venv/bin/python evidence/1834-four-class-fix/scripts/mutation_old_red.py
# F15_old_red: opening_has_name=true, file_hit_n=1, clean=false
../Ming_LLM/.venv/bin/python evidence/1834-four-class-fix/scripts/probe_four_class.py
# F15: clean=true, parallel_secret_order_affair_ids_fn=false, affair_derived_from_dossiers=true
```

结果已落 `evidence/1834-four-class-fix/mutation_old_red.json`、`probe_new_green.json`。

### 复扫

`PARALLEL secret_order_affair_ids`：**无**。见 `rescan.txt`。

---

## 2. F16「自由正文在供料来源中被截断」

### 类定义

写入或投影进材料目录 / 邸报供料可读事实的自由正文，被无依据长度切片、strip 后切片或改写裁断。含阶段承诺 `criterion` / `origin_context` / `title` 等——以**实际消费者**判定，不以是否判词点名样本判定。

### 枚举范围

`enum_four_class.py` → 全 `ming_sim/**/*.py` 中自由正文字段形 `[:N]`（含 LOG_OR_RAISE / PROSE_SLICE）。再逐条追消费者：`materials` 世界树、人物树、检举事实、事务效果史、`_gazette_feed` / `list_due_commitments`。

### 成员表（有消费者 → FIX）

| 成员 | 消费者 | 处置 |
| --- | --- | --- |
| `db.build_faction_denunciation_facts` case_summary（上轮已删 `[:48]`） | 派系检举事实.txt | 维持 |
| `db.record_fiscal_*` reason/note（上轮已删 `[:240]`） | 事务效果史 / 财政史 | 维持 |
| `staged_commitment.normalize_commitment_stages` `criterion/origin [:200/:240]` | `stages_json` → `list_world_effect_history` issues | **FIX** |
| `staged_commitment.list_due_grant_report_*` criterion/origin/title 切片 | 写入 `next_audience_todos`；due_review 拼 note；note 进案卷实况 | **FIX** |
| `settlement_payload.list_due_commitments` `content[:120]` | `_gazette_feed.due_commitments` | **FIX** |
| `flows.apply_economy_moves` `reason[:80]`（及 category 同源切片） | economy_ledger → `_month_fact_materials` | **FIX** |
| `issues` 新建/推进 `title/stage_text/resolve/fail/narrative` 切片 | 人物/事务材料 `stage_text`/`title` | **FIX** |
| `issues`/`db` `status_reason` 切片 | 世界名册状态行 | **FIX** |
| `db.mark_event_*` `terminal_reason` 切片 | 事件终态.txt | **FIX** |
| `due_review` / `covert_progress` `note[:200]` | 案卷复核 note → 实况轨 | **FIX** |
| `issues` fiscal_create `note[:120]` | fiscal creations 史 | **FIX** |

### 成员表（KEEP — 非「不是样本」）

| 成员 | 保留依据 |
| --- | --- |
| `materials._safe_segment` `clean[:48]` | 路径段身份哈希前缀，非 LLM 供料正文 |
| `staged_commitment` / `db` raise 内 `text[:80]` | 错误预览，不进材料目录 |
| tlog/print/`provider_message` 切片 | 日志，非供料 |
| `db` army/region/building `reason[:80]` 等变更日志切片 | 材料侧军队详情走 `army_roster` 定性，不投影这些 change-reason 字段 |
| `breach_plea` meta reason 切片 | 编码进 todo meta，材料目录无读取口 |
| `situations[:12]` / `options[:3]` | 列表长度，非正文裁断 |
| `reason_code[:40]` | 机读码，非自由正文 |

### 变异

旧红见 `mutation_old_red.json`（staged 200/240、fiscal 240、due 120）。
新绿见 `probe_new_green.json`（`staged_criterion_full/origin_full=true`，`fiscal_full/case_full=true`）。

### 复扫

材料供料链上的 PROSE 裁剪已删；剩余见 `enum_f16_members.txt`，均落 KEEP 依据。

---

## 3. F13「已退役索引副本仍被动态恢复」

### 类定义

冻结 dataclass / 材料载体上，用 `object.__setattr__` 或同类手段动态恢复**已退役、无消费者**的镜像字段（不限 `index_lines`）。

### 枚举命令

同 `enum_four_class.py` → `enum_f13_members.txt`（扫 `ming_sim`+`tests` 的 `object.__setattr__` / `index_lines` / frozen 动态写）。

### 成员表

| 成员 | 处置 | 依据 |
| --- | --- | --- |
| `PreparedMaterials.index_lines` 动态读写 | 上轮已删 | 复扫 0 行 |
| 其它 frozen 动态副本 | **无成员** | 枚举空集 |
| `INDEX.txt` 文件追加 | **KEEP** | 人读索引文件真源，非对象镜像 |
| 探针 `hasattr(...,"index_lines")` | **KEEP（取证）** | 非生产代码 |

### 变异

`probe_new_green.json` F13：`before=false, after=false, clean=true`。

---

## 4. F3-R「测试恢复留下重复断言」

### 类定义

同主体上弱断言已被强断言逻辑蕴含（不限紧邻 `in`⊂`==`；含 JS 存在性⊂正文）。删弱留强；时序检查点（变异前/后）不算重复。

### 枚举命令

```bash
../Ming_LLM/.venv/bin/python evidence/1834-four-class-fix/scripts/enum_four_class.py
# AST：IN_THEN_EQ / NOTIN_THEN_EQ；JS：NULL_THEN_CONTENT / KEEP_WAITFOR
```

### 成员表

| 成员 | 处置 | 依据 |
| --- | --- | --- |
| 判词样本三处（上轮已删） | 维持 | — |
| `test_qa_a3_seed_data` `not in` ⊂ `office ==` | **FIX** | 真蕴含 |
| `appDurableWiring` hudAlert / armyPay / attendant 等 null⊂content | **FIX** | 真蕴含 |
| `drawers` / `map` / `modals` / `situation` 同形 | **FIX** | 真蕴含 |
| `test_session_write_queue` / `test_qa_t1` `not in` 后隔 mutation 再 `==` | **KEEP** | 时序检查点（放行前/后），非重复证明 |
| waitFor 异步栅栏 | **KEEP** | 同步，非重复 |

### 复扫

`enum_f3r_members.txt` / `enum_f3r_rescan.txt`：仅余 6 条时序 NOTIN_THEN_EQ；JS 非 waitFor 候选清零。

---

## 聚焦测试

**Python**（343 passed，~10.68s）：

```text
…/python -m pytest tests/test_world_materials_1834.py tests/test_candidate_supply_1893.py \
  tests/test_material_directory_1830.py tests/test_scene_llm_1836.py \
  tests/test_player_payload_1022.py tests/test_cli_runner_error_typed_1299.py \
  tests/test_dossier_reported_progress_619.py tests/test_gazette_author_1862.py \
  tests/test_execution_pressure_654.py tests/test_manual_directive_institution_normalize_1279.py \
  tests/test_promulgation_judge_561.py tests/test_qa_d1_decree_normalize_1274.py \
  tests/test_rejection_wiring.py tests/test_relation_capture_633.py \
  tests/test_session_write_queue_1353.py tests/test_state_reload.py \
  tests/test_qa_a3_seed_data.py tests/test_staged_assignment_identity_1890.py \
  tests/test_due_review_621.py tests/test_urge_lever_624.py \
  -q -p no:cacheprovider --basetemp=/tmp/1834-fixer-r2-audit/pytest-focus
→ 343 passed in 10.68s
```

输出：`evidence/1834-four-class-fix/pytest_focus.txt`。

**Web**（152 passed，Duration 4.15s）：

```text
cd web && npm test -- src/appDurableWiring.test.tsx \
  src/components/settlementGazettePanel.test.tsx src/components/modals.test.tsx \
  src/components/drawers.test.tsx src/components/map.test.tsx \
  src/components/situation.test.tsx
→ Test Files 6 passed; Tests 152 passed
```

输出：`evidence/1834-four-class-fix/vitest_focus.txt`。

未跑全量。邻票 `test_commitment_progress_contexts_are_structured` 依判词归 #1873，不夹入。

---

## 复杂度合法性自验

| 项 | 结论 |
| --- | --- |
| 删简优先 | 删平行 secret 函数、删正文切片、删弱断言；无摘要/护栏/兼容层 |
| F15 复用边界 | 只留 `secret_order_dossier_ids`；事务 id **派生自已过滤案卷集** |
| 无证明性永测 | `scripts/enum_four_class.py`、`probe_four_class.py`、`mutation_old_red.py` 均为取证，非 pytest |

---

## 逐类结果

| 类 | 结果 | 未结 |
| --- | --- | --- |
| F15 | 已修；去掉平行 secret 规则；旧红新绿 | 无 |
| F16 | 已按消费者扩修；上轮 KEEP 的 staged 等已修 | KEEP 仅无消费者/非正文 |
| F13 | 复扫空集；动态副本仍无 | 无 |
| F3-R | 真重复已删；时序 6 条 KEEP | 无 |
| 邻票 | — | #1873 |

未 push / 未开 PR / 未 stash / 未 amend / 未 kill。
