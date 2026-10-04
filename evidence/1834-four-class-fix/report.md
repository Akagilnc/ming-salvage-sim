# #1834 四类未结修复回执（末份判词 beff66c17）

**工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1834-w5`  
**分支**：`ak-roles/1834-f15-f16-f13-f3r-beff66c17`（自 `beff66c17` 开出）  
**判词真源**：末份 payload（F15 / F16 / F13 / F3-R）；前份 F3/F14 已结，不重开。  
**诊断**：已读 `diagnosing-bugs`。Phase 1 用真实入口临时探针建立红绿环；判词已确证根因，**跳过 Phase 3 重做假设**（避免重复取证）。未新增永久证明性测试；旧逻辑变异在进程内 monkeypatch，不改仓库文件。

**互联网检索（动手前）**：

- Python frozen dataclass：官方文档要求字段声明完整；退役字段应删除，勿用 `object.__setattr__` 挂未声明副本（[dataclasses](https://docs.python.org/3/library/dataclasses.html)）。
- 自由正文：官方既有解法是**不要切片**，整段透传（非加大上限）。

**共同测试前缀**：

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false
```

---

## 1. F15「公共供料绕过秘密来源边界」

### 类定义

公共 / 邸报作者输入投影，在已启用秘密案卷排除时，仍无条件供出密令关联事务的**名称 / 起因**等元数据，绕过既有秘密来源边界（ADR 0155：邸报不含密令；P6 从输入侧处理可见性）。

### 枚举命令

```bash
rg -n '起因：\{affair\.origin\}|_world_affair_lines|secret_order_affair_ids|exclude_affair_ids|exclude_secret_order_dossiers|prepare_gazette_author_materials' ming_sim --glob '*.py'
```

### 成员表

| 成员 | 处置 | 理由 |
| --- | --- | --- |
| `ming_sim/materials.py:_world_affair_lines` | **FIX** | 只滤文字事实，无条件拼 `起因`+`name` |
| `ming_sim/materials.py:prepare_world_materials` | **FIX** | 公共路径算 secret dossiers 后未排除密令事务 |
| `ming_sim/materials.py:_write_world_tree` 事务环 | **FIX** | 须与 `affair_lines` 同步跳过缺失键，避免漏滤/KeyError |
| `ming_sim/month_chain.py:prepare_gazette_author_materials` | **KEEP** | 已正确传 `exclude_secret_order_dossiers=True`；缺口在 materials 支路 |
| `secret_order_dossier_ids` | **KEEP** | 既有案卷边界真源，复用 |

### 根因

`include_fact` 只挡文字事实；事务身份（name/origin）始终写入公共目录。

### 修复

新增 `secret_order_affair_ids`（由密令案卷 `affair_id` 派生），在 `exclude_secret_order_dossiers` 时传入 `_world_affair_lines(exclude_affair_ids=…)` 整事务丢弃；`_write_world_tree` 对不在 `affair_materials` 的事务 `continue`。不新造第二套密令账。

### 复扫

复扫见 `evidence/1834-four-class-fix/rescan.txt`：公共路径已接 `secret_order_affair_ids`；`起因：{affair.origin}` 仅在未排除成员上写出。

### 变异证据

旧逻辑（`secret_order_affair_ids`→空集）：`opening_has_name=true`，文件命中 name+origin，`clean=false`。  
新逻辑：`clean=true`，零命中。见 `/tmp/1834-fixer-beff-audit/mutation_old_red.txt` vs `probe_new2.txt`。

---

## 2. F16「自由正文在供料来源中被截断」

### 类定义

写入或投影进材料目录可读事实的自由正文，被无依据 `[:N]` 裁剪（禁止加大上限 / 摘要 / 兼容层替代）。

### 枚举命令

```bash
rg -n 'reason\[:240\]|note\[:240\]|case_summary\[:|decree_text.*\[:240\]|\[:48\]' ming_sim --glob '*.py'
rg -n '\[:240\]' ming_sim --glob '*.py'
```

### 成员表

| 成员 | 处置 | 理由 |
| --- | --- | --- |
| `db.py` `case_summary` strip+`[:48]` | **FIX** | 检举供料案情摘要 |
| `db.py` `record_fiscal_config_change` `reason[:240]` | **FIX** | 财政变更事由进效果史→事务材料 |
| `db.py` fiscal creations `note[:240]` | **FIX** | 同类财政创建事由 |
| `db.py` fiscal tombstones `reason[:240]` | **FIX** | 同类财政裁撤事由 |
| `db.py` pay_order materialize `decree_text[:240]` | **FIX** | 旨文作财政 reason 进供料史 |
| `db.py` `_create_grant_fiscal_item` `note[:240]` | **FIX** | 同类拨帑建项事由 |
| `pay_order.py` 三处 tombstone `…[:240]` | **FIX** | 同类财政 tombstone 事由切片（含无意义字面量切片） |
| `materials.py` `clean[:48]` | **KEEP** | 路径段安全身份，非 LLM 供料正文 |
| `staged_commitment.py` `origin_context[:240]` / `criterion[:200]` | **KEEP** | 分期承诺结构化写入，非本类检举/财政供料样本；未进本轮 materials 投影 |
| tlog/raise 内 `[:N]` | **KEEP** | 日志/错误预览 |

### 根因

历史列宽习惯在写入供料史前切片自由正文。

### 修复

删除上述无依据切片，整段透传。

### 复扫

`reason[:240]|case_summary[:|decree_text…[:240]` 生产命中清零；仅余 `staged_commitment`（KEEP）与路径 `clean[:48]`。

### 变异证据

旧：`case_summary` 长 48、丢后缀；`stored_reason_lens=[240]`，`fiscal_full=false`。  
新：`case_full=true`，`stored_reason_lens=[414]`，`fiscal_full=true`。

---

## 3. F13「已退役索引副本仍被动态恢复」

### 类定义

`PreparedMaterials` 仅声明 `root/opening`，却仍用 `object.__setattr__` 动态恢复无消费者的 `index_lines` 副本。

### 枚举命令

```bash
rg -n 'index_lines|object\.__setattr__\(prepared' --glob '*.py'
```

### 成员表

| 成员 | 处置 | 理由 |
| --- | --- | --- |
| `materials.py:73` `getattr(…,"index_lines")` | **FIX** | 读退役副本 |
| `materials.py:93` `object.__setattr__(…,"index_lines")` | **FIX** | 动态恢复 |
| `INDEX.txt` 追加写入 | **KEEP** | 人读索引真源文件，非对象副本 |
| `tests/…1830` 注释 | **FIX 注释** | 去掉过时字段名 |
| evidence 历史回执 | **KEEP** | 非现役代码 |

### 根因

字段声明已删，写入支路仍维护镜像。

### 修复

`write_identity_materials` 只追加 `INDEX.txt` 并返回路径列表；删除 `index_lines` 读写。

### 复扫

生产/测试无 `index_lines`；仅探针脚本检测 `hasattr`。

### 变异证据

旧：`after=true`；新：`before=false, after=false`。

---

## 4. F3-R「测试恢复留下重复断言」

### 类定义

同主体上弱断言已被紧邻强断言逻辑蕴含（`in`⊂`==`；`not.toBeNull`⊂`toContain`/正文断言）。删弱留强；不批删合法契约；不造长度/非空替代。

### 枚举命令

```bash
# Python: assert X in H 后紧邻 assert H == …
# JS: 同 querySelector 上 not.toBeNull 与 toContain/textContent（waitFor 同步除外）
```

（脚本输出记入本回执过程；终态见 `rescan.txt`。）

### 成员表

| 成员 | 处置 | 理由 |
| --- | --- | --- |
| `test_cli_runner_error_typed_1299.py:70–71` | **FIX** | 子串⊂全文相等（判词样本） |
| `appDurableWiring.test.tsx:349–350` | **FIX** | 存在性⊂ toContain（判词样本） |
| `settlementGazettePanel.test.tsx:40–42` | **FIX** | attendant 存在性⊂ toContain（判词样本） |
| `test_execution_pressure_654.py` dossier `in` + frozenset `==` | **FIX** | 成员⊂全集相等 |
| `test_manual_directive_institution_normalize_1279.py` 多条 `not in` + `ids==` | **FIX** | 负向成员⊂精确列表 |
| `test_qa_d1_decree_normalize_1274.py` 同形 | **FIX** | 同上 |
| `test_promulgation_judge_561.py` `in` + names `==` | **FIX** | 成员⊂集合相等 |
| `test_rejection_wiring.py` 五处 `"rejected" not in` + `item==` | **FIX** | 键缺失⊂全等 |
| `test_relation_capture_633.py` `in` + origin `==` | **FIX** | 子串⊂全等 |
| `test_session_write_queue_1353.py` `not in` + order `==` | **FIX** | 同上 |
| `test_state_reload.py` `not in` + metrics `==` | **FIX** | 同上 |
| `appDurableWiring` court-drawer null+toContain | **FIX** | 同节点弱存在性 |
| `appDurableWiring` decision-modal waitFor+toContain | **KEEP** | waitFor 是异步栅栏，非重复证明 |

### 根因

前轮恢复契约时弱强并列，未删已被蕴含的弱断言。

### 修复

只删弱重复。

### 复扫

`in→eq` / 非 waitFor 的 null+content 候选清零；仅余 waitFor 同步 KEEP。

---

## 聚焦测试

**Python**（287 passed，~10.07s / real 10.61s）：

```text
…/python -m pytest tests/test_world_materials_1834.py tests/test_candidate_supply_1893.py \
  tests/test_material_directory_1830.py tests/test_scene_llm_1836.py \
  tests/test_player_payload_1022.py tests/test_cli_runner_error_typed_1299.py \
  tests/test_dossier_reported_progress_619.py tests/test_gazette_author_1862.py \
  tests/test_execution_pressure_654.py tests/test_manual_directive_institution_normalize_1279.py \
  tests/test_promulgation_judge_561.py tests/test_qa_d1_decree_normalize_1274.py \
  tests/test_rejection_wiring.py tests/test_relation_capture_633.py \
  tests/test_session_write_queue_1353.py tests/test_state_reload.py \
  -q -p no:cacheprovider --basetemp=/tmp/1834-fixer-beff-audit/pytest-focus
→ 287 passed in 10.07s
```

**Web**（120 passed，Duration 4.36s / real 4.65s）：

```text
cd web && npm test -- src/appDurableWiring.test.tsx \
  src/components/settlementGazettePanel.test.tsx src/components/modals.test.tsx
→ Test Files 3 passed; Tests 120 passed
```

未跑全量（派单：仅聚焦）。已知邻票红灯 `test_commitment_progress_contexts_are_structured` 依判词归 #1873，本轮不夹入。

---

## 复杂度合法性自验

| 项 | 结论 |
| --- | --- |
| 删简优先 | 删裁剪、删 index_lines 副本、删弱断言；无摘要/护栏/兼容层 |
| 复用既有边界 | 密令排除仍走 `secret_order_dossier_ids`，事务侧只派生 `affair_id` |
| 净复杂度 | `git diff --stat`：15 files，+40/-39，近似持平且去掉平行副本 |
| 无证明性永测 | 仅 `evidence/…/scripts/probe_four_class.py` 临时探针 |

---

## 逐类结果与未结范围

| 类 | 结果 | 未结 |
| --- | --- | --- |
| F15 | 已修；探针旧红新绿 | 无（本类） |
| F16 | 已修枚举 FIX 成员；探针旧红新绿 | `staged_commitment` KEEP 若后审扩类可单开 |
| F13 | 已修；动态副本消失 | 无 |
| F3-R | 已修弱重复；waitFor KEEP | 无 |
| 邻票 | — | #1873 `issue_id` NameError 不在本片 |

**诚实限制**：F15 变异时 opening 只稳定复现 name 泄漏（origin 主要在事务文件）；文件层 name+origin 均在旧红中复现。未 push / 未开 PR / 未 stash / 未 amend / 未改宿主配置。
