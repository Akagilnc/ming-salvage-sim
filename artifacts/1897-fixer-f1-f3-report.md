# #1897 修内司 F1/F2/F3 回执

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1897-w5`
- 分支：`ak-roles/issue-1897-f1-f3-fixer-20261005-075711`
- 施工前 HEAD：`b8370cc4bcd36667ce87eaacfd183a15d9ba3b5d`
- 派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a10920-e05c-7407-b37f-1b01aceb86c4@fixer/fix-packet.md`
- 冻结判词：同 run `attachments/02-1897-judge-b8370cc4b.json` **末 payload**（`status=continue`；未结仅 F1/F2/F3）
- 旧回执保留：`artifacts/1897-fixer-r1-r4-report.md`、`artifacts/1897-fixer-ab-report.md`
- 状态：本轮新独立 `ak-roles:` 提交；**未 push、未开 PR、未 amend、未 stash**
- **未声称已 merge / 关票 / reviewer 放行**

## 顾问结论（最简修法，施工前）

| 类 | 正确行为 | 根因 | 最简修法 |
|---|---|---|---|
| F1 | 公共邸报供料不进未披露密令实况；世界推演者仍可读 | `_write_secret_actual_note_files` 无条件写入，未承接既有 `exclude_secret_order_dossiers` | 把既有排除标志传入 `_write_world_tree`，排除时跳过实况写口；不新建隔离层、不擦洗模型输出 |
| F2 | 领域拒收在校验区；执行区内部故障响亮上抛 | `issues.py` 执行区 `except Exception → rejected` 宽吞（含缺案卷 `ValueError`） | **删除**该 try/except；保留上方 `missing_ref` / `invalid_enum` 校验 |
| F3 | 授权测不机械锁自由文本；失效证明案与重复删 | 正文锁换标题哨兵；`progress_band`/整对象仍锁文；重复月报案；长正文案只留标题 | 全仓枚举后按行为契约删简/改结构化；不补机械正文断言、不新造平行证明 |

诊断：判词已给确定根因 → 跳过假设排名；用临时真实入口变异新绿旧红证明（不造永久案）。

互联网对照：Python/sqlite 异常分流（窄捕 `sqlite3.Error`、领域校验与内部故障分界）与 AST 扫断言（非 grep）与本修法一致；本仓已有 `exclude_secret_order_dossiers` 与 ADR0005/0008，优先复用删除。

## F1：公共供料旁路

### 成员（接缝枚举）

```bash
rg -n '_write_secret_actual_note_files|exclude_secret_order_dossiers|prepare_gazette_author_materials|public_feed' \
  ming_sim/materials.py ming_sim/month_chain.py ming_sim/agents.py
```

| 成员 | 处置 |
|---|---|
| `materials.py` `_write_world_tree` 无条件 `index.extend(_write_secret_actual_note_files…)` | **改**：受 `exclude_secret_order_dossiers` 门控 |
| `prepare_world_materials` → `_write_world_tree` 未传排除 | **改**：传入既有标志 |
| `month_chain.prepare_gazette_author_materials` 已传 `exclude_secret_order_dossiers=True` | **复用**（调用方不变） |
| 世界推演默认 `exclude_secret_order_dossiers=False` | **保留**（推演者应读） |

### 变异（新绿旧红）

环境前缀：七个 `MING_SIM_*_BIN=/usr/bin/false` + `PYTHONDONTWRITEBYTECODE=1`。

真实入口：`create_secret_order` → `update_secret_order_sim_note` → `prepare_world_materials` / `prepare_gazette_author_materials`。

```
F1 {"world_has": true, "gazette_has": false, "gazette_body_visible": false,
    "old_unconditional_gazette_has": true, "verdict": "GREEN"}
```

旧红：临时将 `_write_world_tree(..., exclude_secret_order_dossiers=False)` 强制打开 → 邸报目录出现 `密令/实况/{id}.txt`。

## F2：执行区宽吞

### 成员（声明写入链枚举）

```bash
rg -n -U 'except sqlite3\.Error:\s*\n\s*raise\s*\n\s*except Exception' ming_sim --glob '*.py'
rg -n '密令进展缺少对应案卷|update_secret_order_sim_note' ming_sim/issues.py ming_sim/db.py
```

| 成员 | 处置 |
|---|---|
| `issues.py` secret_order_updates 执行区宽吞 | **删** try/except；校验区拒收保留 |
| `db.py` 缺案卷 `ValueError` | **保留**（内部不一致 → 响亮） |
| 未知 `order_id` → `missing_ref` | **保留**（领域拒收） |
| 全仓仅此一处「sqlite3 重抛 + Exception 转拒收」形态在该写入链 | 无其他同类成员 |

### 变异（新绿旧红）

```
F2 {"old_pattern_reject": {"rejected": true, "reason": "密令进展缺少对应案卷", "category": "legacy_inline"},
    "current_write": "ValueError:密令进展缺少对应案卷",
    "apply_missing_dossier": "ValueError:密令进展缺少对应案卷",
    "unknown_ok_no_raise": true, "unknown_has_missing_ref": true, "verdict": "GREEN"}
```

## F3：授权测试体系

### 全仓机械枚举命令（非 24 文件白名单）

授权谓词：全仓 `tests/test_*.py` AST；文件入集当且仅当（imports∪调用）触及 #1897 接缝符号  
（`create_secret_order` / `update_secret_order_*` / `dossier_progress` / `dispatch_declaration` /
`prepare_*_materials` / `settle_due_secret_orders` / `build_covert_task_contract` 等）  
**或** stem 锚定密令/声明/due_review/execution_pressure/monthly_progress/dossier_reported/
deformation/staged_assignment/audience_translate_1837/family_tail_restore/character_knowledge/
breach_plea/month_chain/isolation 等。

自由文本载体（**非字段白名单收窄**；标题、进展文字、嵌套正文、整对象一并扫）：  
`title` / `body` / `content` / `text` / `note` / `memorial_text` / `progress_band` /
`narrative` / `criterion` / `report` / `summary` / `opening` 等，含 `in` 哨兵与整对象字面量。

本轮授权集规模：**46** 文件（命令见施工过程 `/tmp/1897-f1f3-enum` 逻辑；可复跑上节 AST）。

### 全成员表与处置（F3 类内须清者 + 保留例外）

#### 清退 / 改结构化（本轮动手）

| 成员 | 处置 | 理由 |
|---|---|---|
| `test_secret_order_update.py` `"改" in title` 哨兵 ×3 | **删**；改 tags/`deadline_span` 结构化 | 判词样本：标题哨兵替正文锁 |
| `test_update_preserves_long_text`（仅断言 title） | **删整案** | 失效证明性案 |
| `test_secret_order_update.py` `title == "新标题"` 字面 | **删**；改跨表 `brief.title == order.title` | 不锁散文字面 |
| `test_character_knowledge_489.py:478/:510` title 字面 | **删**；改 `excluded_names`/`kind` 结构化 | 判词同类标题 |
| `test_character_knowledge_489.py` archive `report ==` | **删**；改 archive 存在 + source_id 可见性 | 自由报告正文 |
| `test_staged_assignment_identity_1890.py:374` title 字面 | **删**；改 brief↔order 跨表一致 | 同类标题 |
| `test_dossier_reported_progress_619.py:94` progress_band 列表 | **删**；保留 turn/origin/is_terminal | 自由进展文字；库无闭集枚举 |
| `test_family_tail_restore_570.py:164` 整对象含 memorial_text | **删整对象**；改 turn/origin/条数 | 嵌套正文整对象 |
| `test_breach_plea_623.py:541` progress_band | **删**；改 progress 条数+turn | 自由进展文字 |
| `test_secret_order_monthly_progress_566.py:73` progress_band | **删**；保留 turn/is_terminal | 同上 |
| `test_emperor_private_payload_preserves_monthly_report` | **删整案** | 与月报 turn 案重复；AB 回执曾称维持删除却仍在 HEAD |
| `test_secret_order_payoff_1504.py:316` progress_band；`:1488-1489` method/form 字面 | **删值锁**；改键存在/条数 | 进展与自由 form |
| `test_secret_order_isolation_883.py:1480` title/content 整对象 | **删**；改 origin_chat_message_ids + 跨表 title 同步 | 整对象锁文 |
| `test_month_chain_1843.py:845` recon note 字面 | **删**；保留 turn | 自由 note |
| `test_month_chain_1847.py` desk/decisions title 字面与 options 标签字面 | **删**；改 len/status | 标题锁文 |

#### 保留（例外，记账）

| 成员 | 保留理由 |
|---|---|
| `brief.title == order.title` / `projected.title == source.title` 跨表一致 | 双方均 DB 投影，无字面散文；截断身份契约 |
| `summary == ""`（`month_chain_1847` 结局） | 结构化「无摘要」空位，非锁散文内容 |
| `registrations == [{"name": "李若璉補"}]` | 名册身份（同既有 `db.content.characters` 例外） |
| `participant_roster` 整对象（tier/role/character_id） | 结构化名册 schema，非密令进展自由文本 |
| fiscal_levy `terminal_reason` / person_delta adapter 整对象等 AUTH 命中但非本票搬迁测试漂移 | **出界**：非 #1897 授权改动对应清退面；本轮不扩扫改写 |
| Event/Future 握手；闸类负向（create/settle identity/tags/zero-target） | 判词/上轮 B 已恢复，保留 |
| 材料路径键 `"密令/进行中.txt" in list_materials`（他案） | 路径键非散文正文值 |

#### 失效证明 / 重复

| 案 | 处置 |
|---|---|
| `test_update_preserves_long_text` | 删（正文承重断言已无，只剩标题） |
| `test_emperor_private_payload_preserves_monthly_report` | 删（与 `test_monthly_report_keeps_its_turn_and_text` 同形重复） |
| AST 同名顶层 `test_*` | 授权集 `DUPS=none` |

### F3 变异

空心更新（忽略 tags、丢弃 body）时：旧标题哨兵仍绿；本轮 tags 契约变红。

```
{"old_title_sentinel_still_green": true, "current_tags_contract_red_under_hollow": true, "verdict": "GREEN"}
```

施工后 DIFF 内散文字面/哨兵复扫：仅余 `summary == ""`（上表保留例外）。

## 聚焦测试

```bash
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
  ../Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=line \
  tests/test_breach_plea_623.py \
  tests/test_secret_order_update.py \
  tests/test_secret_order_monthly_progress_566.py \
  tests/test_secret_order_payoff_1504.py \
  tests/test_secret_order_declaration_landing_1897.py \
  tests/test_secret_order_section_rejections.py \
  tests/test_dossier_reported_progress_619.py \
  tests/test_family_tail_restore_570.py \
  tests/test_staged_assignment_identity_1890.py \
  tests/test_character_knowledge_489.py \
  tests/test_world_materials_1834.py \
  tests/test_month_chain_1843.py \
  tests/test_month_chain_1847.py \
  tests/test_execution_pressure_654.py \
  tests/test_declaration_dispatch_1835.py \
  tests/test_deformation_dual_rail_622.py \
  tests/test_due_review_621.py \
  tests/test_audience_translate_1837_reopen.py \
  tests/test_decree_dossiers_571.py \
  tests/test_secret_order_isolation_883.py
```

**实测**：`589 passed in 21.92s`（`real 22.51`）。未跑全量。

说明：`test_secret_order_isolation_883` **先于** `test_revoke_forecast_translation_input_carries_original_and_continuing_dossier` 时，后者 `KeyError: request`（monkeypatch 污染）。在 **HEAD 无本轮 isolation 改动** 上同样复现 → **预存交叉污染**，非 F1–F3 引入；本聚焦将 breach 置于 isolation 之前。不在本片扩修。

已知基线 FK（`test_audience_translate_1837.py::…appointment…`）仍按 #1812→#1873，不本片接回。

## 测试契约与最小必要成本

- 复用既有真实入口（`update_secret_order_by_id` / `list_secret_orders` / `list_dossier_progress` / `dispatch`/月链案）与结构化字段（tags、turn、origin、source_id、status、跨表 title 同步）。
- 不新增平行证明测试；闸类负向不动。
- 生产面只动两处接缝（materials 门控 + issues 删宽吞），其余为测试删简。

## 自查二连

1. **同类型**：F1 只收拢既有排除标志；F2 只删宽吞；F3 按类清标题/进展/整对象/失效/重复，未用非空伪装。
2. **引入面**：聚焦 589 绿；F1/F2/F3 变异新绿旧红；未放宽断言洗绿；未改宿主配置；临时探针目录已清理。

## 交卷 HEAD

- 代码修提交（修面 HEAD）：`edb3760324a46295eb28ead69706151b2b806526`
- 报告/tip：以交卷后 `git rev-parse HEAD` 为准（本段修复后另有 docs commit，不冒充修面）。
- 验证命令：`git rev-parse HEAD`；`git rev-parse edb376032`；`git status --porcelain=v1` 应交空。
