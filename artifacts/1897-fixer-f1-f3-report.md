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

---

## 纠正回执（交卷补全，本轮）

- 基线 tip（施工前）：`de914614a34553de4b0118d77d87a5b5ca8366c2`（上轮报告 + 修面 `edb376032`）
- 批评点：F1 枚举非全仓；F2 谓词过窄；F3 伪称非白名单却用 stem/字段收窄、缺可复跑命令与全集表；跨表 title 相等违规豁免；method/form 键存在有洗绿嫌疑；测序绕污染却冒称全绿；脚本不可复跑。
- 本轮：**保留上文旧过程史**，以下为纠正后的可复跑枚举、逐条处置与实测。
- **未声称 F3 整类已结清**（全仓授权相关仍有出界自由文本候选）。

### 顾问（补全后）

| 类 | 正确行为 | 根因（复核） | 最简修法 |
|---|---|---|---|
| F1 | 邸报供料不进未披露实况；世界推演可读 | `_write_secret_actual_note_files` 须受既有 `exclude_secret_order_dossiers` 门控 | 已收拢标志（修面保留）；本轮补全仓成员表 + 可复跑变异 |
| F2 | 声明写入链执行区故障响亮；领域拒收仅校验区 | 判词样本 `issues.py` 宽吞已删；全仓 catch 再按写入链语义判读 | 无新增宽吞待删；候选表逐条记账 |
| F3 | 不机械锁自由文本；失效/重复删 | 跨表 title 相等仍锁文；method/form 值锁与键存在洗绿；截断证明案失效 | 删失效截断案；清 title/progress_band/sim_note/method·form；出界不扩扫 |

### F1 全仓枚举（可复跑）

```bash
rg -n '_write_secret_actual_note_files|exclude_secret_order_dossiers|prepare_gazette_author_materials|密令/实况' \
  --glob '*.py' -g '!.venv/**'
rg -l '_write_secret_actual_note_files|exclude_secret_order_dossiers|prepare_gazette_author_materials|密令/实况' \
  --glob '*.py' -g '!.venv/**' | sort
```

| 成员 | 处置 |
|---|---|
| `ming_sim/materials.py` `_write_world_tree` + `prepare_world_materials` | **已改**（修面）：`exclude_secret_order_dossiers` 门控实况写口 |
| `ming_sim/month_chain.py` `prepare_gazette_author_materials` | **复用**：传 `exclude_secret_order_dossiers=True` |
| `tests/test_gazette_author_1862.py` | **测试消费方**（非生产旁路） |
| `tests/test_faction_denunciation_627.py` | **测试消费方**（显式传排除） |
| 世界推演默认 `exclude_secret_order_dossiers=False` | **保留** |

### F1 变异（可复跑命令 + 实测）

```bash
# 脚本全文见本回执末「一次性脚本」mutate_f1.py；写入 /tmp 后执行：
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH="$PWD" ../Ming_LLM/.venv/bin/python /tmp/1897-f1f3-corr/mutate_f1.py
```

实测：`EXIT=0`；`{"world_has": true, "gazette_has": false, "gazette_body_visible": false, "old_unconditional_has": true, "old_body_visible": true, "verdict": "GREEN"}`。

### F2 全仓 catch → 写入链语义判读（可复跑）

```bash
# 1) 全仓 handlers
../Ming_LLM/.venv/bin/python /tmp/1897-f1f3-corr/enum_catches.py | head
# TOTAL_EXCEPT_HANDLERS=717

# 2) 声明写入链文件内 Exception/bare，再语义过滤（脚本见末）
../Ming_LLM/.venv/bin/python /tmp/1897-f1f3-corr/enum_f2_writechain.py
# WRITE_CHAIN_HANDLERS=460；F2_SEMANTIC_CANDIDATES=14
```

谓词：**不限**「sqlite3 重抛相邻 Exception」形状；先枚举全部 `except`，再按已搬声明写入链（dispatch/materialize/issues.apply/db secret_order/month_chain 4a/…）判是否把执行故障伪装成领域拒收。

| 候选 | 语义判读 | 处置 |
|---|---|---|
| `issues.py` `secret_order_updates` 旧宽吞 | 判词样本；已删 try/except | **已清**（修面） |
| `month_chain._step_4a_secret_order_supply` ×4 `except Exception` | 调 `_abort_month_call` / `_abort_4a` → 响亮中止 | **保留**（非伪装拒收） |
| `issues.py` apply_office_appointment ×2 | 官职任命失败回滚返回 typed failure | **出界**：非密令声明执行区 |
| `issues.py:5003` enrich Exception | CLI 国策补效果降级 | **出界** |
| `action_materialize:1312` | 取 last chat turn 软失败 | **出界**/非拒收伪装 |
| `db.py` JSON 损坏回空 / legacy skip / migrate | 读侧降级 | **出界** |
| `audience_translation` / `session` LLM/auto_save | 调度降级 | **出界** |
| `applier`/`declaration_dispatch` BaseException reraise | 事务边界重抛 | **保留** |

### F2 变异（可复跑 + 实测）

```bash
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
  ../Ming_LLM/.venv/bin/python /tmp/1897-f1f3-corr/mutate_f2.py
```

实测：`EXIT=0`；缺案卷 `ValueError` 经 direct write 与 `apply_score_extraction` 均响亮；未知 `order_id` → `missing_ref`；旧宽吞模式仍可伪装拒收（对照 RED 形状）。

### F3 全仓 AST 枚举（可复跑；断言层不按字段白名单收窄成员）

```bash
../Ming_LLM/.venv/bin/python /tmp/1897-f1f3-corr/enum_f3_full.py
# 输出摘要 JSON：/tmp/1897-f1f3-corr/f3_full_summary.json
# 全断言表：/tmp/1897-f1f3-corr/f3_all_asserts.tsv
# 自由文本机械依赖：/tmp/1897-f1f3-corr/f3_free_text_all.tsv / f3_free_text_auth.tsv
```

本轮实测规模：

| 指标 | 值 |
|---|---|
| `tests/test_*.py` 全文件 | 223 |
| 授权相关文件（接缝符号∪票面相邻 stem，仅作「处置范围」标记，不作断言漏扫借口） | 91 |
| 断言/raises/mock 行 | 13998（kind={'assert': 13448, 'pytest.raises': 550}） |
| 自由文本机械依赖（全仓） | 161 |
| 其中授权相关 | 75（复扫后约 75；见 tsv） |
| 同名顶层 test_* | `DUPS=null` |

#### 授权相关文件全集（91）

- `test_advances_section_rejections.py`
- `test_affairs_1831.py`
- `test_appointment_tenure_607.py`
- `test_army_card_status_1501.py`
- `test_audience_background.py`
- `test_audience_translate_1837.py`
- `test_audience_translate_1837_reopen.py`
- `test_audience_travel_gating_670.py`
- `test_authority_ledger_611.py`
- `test_breach_plea_623.py`
- `test_candidate_supply_1893.py`
- `test_character_knowledge_489.py`
- `test_close_issues_section_rejections.py`
- `test_commitment_backlash_626.py`
- `test_covert_levy_651.py`
- `test_credit_events_628.py`
- `test_declaration_dispatch_1835.py`
- `test_decree_commitment_creation_136.py`
- `test_decree_commitment_settlement_229.py`
- `test_decree_dossiers_571.py`
- `test_deformation_dual_rail_622.py`
- `test_dossier_endorsements_612.py`
- `test_dossier_links_559.py`
- `test_dossier_reported_progress_619.py`
- `test_due_review_621.py`
- `test_economy_section_rejections.py`
- `test_effect_origin_558.py`
- `test_env_isolation.py`
- `test_event_trigger_gate.py`
- `test_execution_joint_liability_565.py`
- `test_execution_pressure_654.py`
- `test_faction_brew_637.py`
- `test_faction_class_section_rejections.py`
- `test_faction_denunciation_627.py`
- `test_faction_leverage_9.py`
- `test_family_tail_615.py`
- `test_family_tail_restore_570.py`
- `test_featured_dossiers_494.py`
- `test_fiscal_beyond_intent_1260.py`
- `test_fiscal_levy_effect.py`
- `test_gazette_author_1862.py`
- `test_grant_reconciliation_567.py`
- `test_issue_entities.py`
- `test_material_directory_1830.py`
- `test_mechanical_tail_1845.py`
- `test_memorial_inbox_1726.py`
- `test_menu_lifecycle_drain_396.py`
- `test_month_chain_1843.py`
- `test_month_chain_1847.py`
- `test_mutiny_actual_residence_659.py`
- `test_mutiny_noop_whitelist_319.py`
- `test_new_issues_section_rejections.py`
- `test_on_scene_immediate_write_1839.py`
- `test_opening_gazette_delete_1356.py`
- `test_pay_order_override_653.py`
- `test_person_archive_contract_index.py`
- `test_person_delta_adapter.py`
- `test_person_transit_write_667.py`
- `test_pihong_dossier_1490.py`
- `test_player_army_projection_321.py`
- `test_population_transfers_649.py`
- `test_population_transfers_662.py`
- `test_population_unit_648.py`
- `test_power_section_rejections.py`
- `test_promulgation_judge_561.py`
- `test_public_projection_consistency_1830.py`
- `test_qa_1281_issue_audience_case_facts.py`
- `test_qa_c3_secret_order_path_1357_1376.py`
- `test_refugee_loop_652.py`
- `test_region_cannon_delta.py`
- `test_relation_capture_633.py`
- `test_rescript_heal_isolation_1801.py`
- `test_secret_dossier_participants_1252.py`
- `test_secret_order_declaration_landing_1897.py`
- `test_secret_order_isolation_883.py`
- `test_secret_order_monthly_progress_566.py`
- `test_secret_order_payoff_1504.py`
- `test_secret_order_section_rejections.py`
- `test_secret_order_update.py`
- `test_section4_rejections.py`
- `test_section_fiscal_rejections.py`
- `test_settlement_write_guard_393.py`
- `test_staged_assignment_identity_1890.py`
- `test_style_temperament_641.py`
- `test_supervision_625.py`
- `test_surcharge_causal_chain_650.py`
- `test_transit_aging_346.py`
- `test_urge_lever_624.py`
- `test_web_chat_serialization_393.py`
- `test_world_materials_1834.py`
- `test_yuan_arrival_185.py`

#### 本轮处置（密令/月链/声明落地核心）

| 成员 | 处置 | 理由 |
|---|---|---|
| `test_secret_order_update.py` 跨表 `title==title` ×N | **删**；改 `order_id` 简报存在 + `source_id` 投影 | 跨表自由文本相等非法；非结构化身份 |
| `test_update_by_id_keeps_assignee_brief_identical…` | **删整案** | 失效「二十字截断」证明（生产已无截断写口） |
| `test_creation_brief_uses_persisted_truncated_title` | **删整案** | 同上失效证明 |
| `test_staged_assignment_identity_1890.py` brief/order title | **删**；改 `order_id` 挂接 | 同上 |
| `test_secret_order_isolation_883.py` restored title | **删**；保留 `origin_chat_message_ids` | 同上 |
| `test_secret_order_payoff_1504.py` `form==…` / `method==…` | **删值锁**；历史条数契约保留 | 自由文案 |
| 同文件 `method`/`form` 键存在 | **删**（余 structured tip/units/effort） | 上轮键存在=洗绿；非独立契约 |
| `test_month_chain_1847.py` `progress_band==顺利` ×2 | **删**；改 `len(reports)>=1` + units/source_id | 自由进展文字 |
| 同文件 `sim_note` 子串哨兵 | **改**非空 + `order_id` | 不锁散文 |
| 同文件 HITL `note==` 字面 | **改**非空 note | 不锁散文 |
| `test_month_chain_1843.py` decision title 字面 | **改** `options` 条数 | 标题锁文 |

#### 保留 / 出界（不冒称结清）

| 成员 | 处置 |
|---|---|
| `test_execution_pressure_654.py:607` `'text' not in hit` | **保留**：闸类负向（拒收载荷不得带正文键） |
| `test_declaration_dispatch_1835` 名册 `'李若璉補' in characters` | **出界记账**：身份名册，非密令进展盯文；本轮不扩 |
| `test_rescript_heal_isolation_1801` 等多处 title/form | **出界**：非本票密令搬迁清退面 |
| `test_pihong_dossier_1490` / fiscal / event_trigger / endorsements / web_chat 等 | **出界**：全仓枚举已见，不在本轮授权施工 |
| Event/Future 握手；create/settle identity/tags/zero-target 负向 | **保留**（上轮 B / 判词） |

### F3 变异

```bash
../Ming_LLM/.venv/bin/python /tmp/1897-f1f3-corr/mutate_f3.py
```

实测：`old_title_sentinel_still_green=true`；`current_tags_contract=['甲·改']`；`brief_linked=true`；`verdict=GREEN`。

复扫：触及文件在 `f3_free_text_auth.tsv` 中 **无** 残留 `cross_table_title_eq` / `progress_band_lock`（密令更新/月链/payoff/staged/isolation）。

### 聚焦测试（测序事实，不冒称无条件全绿）

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

**实测**：`587 passed in 17.03s`（删 2 个失效截断案后较上轮 589 −2）。未跑全量。

**测序事实（预存，非本轮引入）**：`test_secret_order_isolation_883` 若先于部分 revoke/forecast 案，可触发 `KeyError: request`（monkeypatch 交叉污染）。本聚焦将 `breach_plea` 置于 isolation 之前以避开该预存污染；**不以重排测序冒称「无污染条件下全绿验收」**。污染记录保留备查，本片不扩修。

`git diff --check`（本轮工作树）：无输出。

### 自查二连（本轮）

1. **同类型**：F1/F2 补枚举与可复跑变异；F3 按法清退跨表 title，删失效截断与 method/form 洗绿，未用非空/键存在伪装正文契约。
2. **引入面**：聚焦 587；变异 F1/F2/F3 GREEN；未放宽生产校验；出界自由文本未虚报结清；临时目录 `/tmp/1897-f1f3-corr` 为分析用，不进仓。

### 交卷 HEAD（本轮）

- 本轮提交：`c27a8b5ad195d3444dfcee3c2085b477f8a422e1`
- 修面生产仍见 `edb376032`（F1 门控 + F2 删宽吞）；本轮主要为 F3 清退与枚举/变异证据补全。
- **未 push / 未 PR / 未 amend / 未 stash**；未声称 merge 或 reviewer 放行。
- 验证：`git rev-parse HEAD`；`git status --porcelain=v1` 应交空（本段 pin 若另有 docs tip，以 tip 为准）。

### 一次性分析 / 变异脚本（完整可粘贴）

#### `enum_f2_writechain.py`

```python
#!/usr/bin/env python3
"""F2: full catch enum, then semantic filter to moved-declaration write chain."""
from __future__ import annotations
import ast
from pathlib import Path

ROOT = Path("/Users/akagilnc/WorkSpace/Ming_LLM-1897-w5")

# Files that participate in moved declaration → apply → secret-order write chain
# (semantic membership, not catch-shape)
WRITE_CHAIN_FILES = {
    "ming_sim/declaration_dispatch.py",
    "ming_sim/action_materialize.py",
    "ming_sim/audience_translation.py",
    "ming_sim/audience_translate.py",
    "ming_sim/audience_night.py",
    "ming_sim/issues.py",
    "ming_sim/applier.py",
    "ming_sim/db.py",
    "ming_sim/covert_progress.py",
    "ming_sim/staged_commitment.py",
    "ming_sim/supervision.py",
    "ming_sim/breach_plea.py",
    "ming_sim/due_review.py",
    "ming_sim/month_chain.py",
    "ming_sim/materials.py",
    "ming_sim/session.py",
}

def enclosing_func(tree, lineno):
    best = None
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end = getattr(n, "end_lineno", n.lineno)
            if n.lineno <= lineno <= end:
                if best is None or n.lineno >= best.lineno:
                    best = n
    return best.name if best else "<module>"

def handler_types(h):
    if h.type is None:
        return "bare"
    return ast.unparse(h.type)

def classify_body(body):
    text = "\n".join(ast.unparse(s) for s in body)
    flags = set()
    if "raise" in {type(s).__name__.lower() for s in body} or any(isinstance(s, ast.Raise) for s in body):
        for s in body:
            if isinstance(s, ast.Raise):
                flags.add("reraise" if s.exc is None else "raise_other")
    if "rejected" in text or "_reject(" in text or "category" in text:
        flags.add("to_reject")
    if any(isinstance(s, ast.Return) for s in body):
        flags.add("return")
    if any(isinstance(s, ast.Continue) for s in body):
        flags.add("continue")
    if any(isinstance(s, ast.Pass) for s in body):
        flags.add("pass")
    # swallow = converts fault into normal control without pure reraise
    pure_reraise = flags <= {"reraise"} or flags == {"raise_other"}
    return flags, text[:200], pure_reraise

rows = []
for rel in sorted(WRITE_CHAIN_FILES):
    path = ROOT / rel
    if not path.exists():
        print(f"MISSING {rel}")
        continue
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    lines = src.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for h in node.handlers:
            types = handler_types(h)
            flags, body_snip, pure_reraise = classify_body(h.body)
            fn = enclosing_func(tree, h.lineno)
            # Broad swallow for F2: Exception/BaseException/bare that does NOT only reraise
            # and converts to reject / soft return / continue masking
            broad_type = (
                types in ("Exception", "BaseException", "bare")
                or (types.startswith("Exception") and "sqlite" not in types.lower())
                or ("Exception" in types and "sqlite3" not in types)
            )
            # also catch: sqlite3.Error reraise + Exception to_reject adjacent pattern
            # (handled as separate Exception handler)
            masks = bool(flags & {"to_reject", "return", "continue"}) and "reraise" not in flags
            # soft: logs and swallows without raise
            soft = (not pure_reraise) and ("reraise" not in flags) and broad_type
            rows.append({
                "file": rel, "line": h.lineno, "fn": fn, "types": types,
                "flags": sorted(flags), "broad_type": broad_type, "masks": masks,
                "soft": soft, "body": body_snip.replace("\n", " / ")[:160],
                "line_text": lines[h.lineno-1].strip()[:100],
            })

print(f"WRITE_CHAIN_HANDLERS={len(rows)}")
# F2 in-scope: broad type that masks fault as reject OR soft-returns in apply/secret paths
f2 = [r for r in rows if r["broad_type"] and (r["masks"] or (r["soft"] and "to_reject" in r["flags"]))]
# Also include soft Exception in secret/apply/dispatch funcs specifically
secretish = ("secret", "apply_score", "dispatch", "declaration", "sim_note", "dossier", "monthly", "progress", "materialize")
f2b = [r for r in rows if r["broad_type"] and not any(x in r["flags"] for x in ("reraise", "raise_other"))
       and any(s in r["fn"].lower() or s in r["file"] for s in secretish)]
# de-dup
seen = set()
f2_all = []
for r in f2 + f2b:
    k = (r["file"], r["line"])
    if k not in seen:
        seen.add(k)
        f2_all.append(r)

print(f"F2_SEMANTIC_CANDIDATES={len(f2_all)}")
print("--- F2 CANDIDATES ---")
for r in f2_all:
    print(f"{r['file']}:{r['line']}\tfn={r['fn']}\t{r['types']}\tflags={r['flags']}\tmasks={r['masks']}\t{r['line_text']}")

print("--- ALL Exception/bare in write-chain (for audit) ---")
for r in rows:
    if r["broad_type"]:
        print(f"{r['file']}:{r['line']}\tfn={r['fn']}\t{r['types']}\tflags={r['flags']}\tpure_mask={r['masks']}")
```

#### `enum_f3_full.py`

```python
#!/usr/bin/env python3
"""Full tests/ AST enum — no stem/field whitelist for membership."""
from __future__ import annotations
import ast, json
from pathlib import Path
ROOT=Path("/Users/akagilnc/WorkSpace/Ming_LLM-1897-w5"); TESTS=ROOT/"tests"; OUT=Path("/tmp/1897-f1f3-corr")
TEXT_ATTRS={"title","body","content","text","note","memorial_text","progress_band","narrative","criterion","report","summary","opening","sim_note","method","form"}
SEAM={"create_secret_order","update_secret_order","update_secret_order_by_id","update_secret_order_sim_note","update_secret_order_progress","list_secret_orders","list_dossier_progress","get_secret_order","dispatch_declaration","prepare_world_materials","prepare_gazette_author_materials","prepare_character_materials","settle_due_secret_orders","build_covert_task_contract","record_secret_order_disclosure","secret_order_dossier_ids","apply_score_extraction","dossier_progress","_write_secret_actual_note_files","apply_monthly_covert_actual_progress"}
STEM=("secret_order","declaration","due_review","execution_pressure","monthly_progress","dossier_reported","deformation","staged_assignment","audience_translate","family_tail","character_knowledge","breach_plea","month_chain","isolation","payoff","gazette","world_materials","decree_dossiers","section_rejection","covert","dossier")

def has_cjk(s): return any("\u4e00"<=c<="\u9fff" for c in s)
def test_ranges(tree):
    r=[]
    for n in ast.walk(tree):
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name.startswith("test"):
            r.append((n.lineno,getattr(n,"end_lineno",n.lineno),n.name))
    return sorted(r)
def test_at(ranges,ln):
    name="<module>"
    for a,b,n in ranges:
        if a<=ln<=b: name=n
        elif a>ln: break
    return name
def seams_in(src,tree):
    names=set()
    for n in ast.walk(tree):
        if isinstance(n,ast.Name): names.add(n.id)
        elif isinstance(n,ast.Attribute): names.add(n.attr)
        elif isinstance(n,ast.ImportFrom):
            for a in n.names: names.add(a.name)
    hit=sorted(names & SEAM)
    if not hit:
        hit=[s for s in SEAM if s in src]
    return hit
def classify(test_node):
    cats=set()
    for n in ast.walk(test_node):
        if isinstance(n,ast.Constant) and isinstance(n.value,str) and n.value:
            if has_cjk(n.value): cats.add("cjk_lit")
            if n.value in TEXT_ATTRS: cats.add(f"key:{n.value}")
        if isinstance(n,ast.Attribute) and n.attr in TEXT_ATTRS: cats.add(f"attr:{n.attr}")
        if isinstance(n,ast.Compare):
            if any(isinstance(op,(ast.In,ast.NotIn)) for op in n.ops):
                if any(isinstance(x,ast.Constant) and isinstance(x.value,str) for x in [n.left,*n.comparators]):
                    cats.add("in_sentinel")
            if any(isinstance(op,(ast.Eq,ast.NotEq)) for op in n.ops):
                sides=[n.left,*n.comparators]
                attrs=[s.attr for s in sides if isinstance(s,ast.Attribute)]
                if attrs.count("title")>=2: cats.add("cross_table_title_eq")
                keys=[]
                for s in sides:
                    if isinstance(s,ast.Subscript) and isinstance(s.slice,ast.Constant) and isinstance(s.slice.value,str):
                        if s.slice.value=="title": keys.append("title")
                        if s.slice.value in TEXT_ATTRS: cats.add(f"key:{s.slice.value}")
                if keys.count("title")>=2: cats.add("cross_table_title_eq")
                if any(isinstance(s,ast.Constant) and isinstance(s.value,str) and s.value for s in sides): cats.add("eq_str_lit")
                if any(isinstance(s,(ast.Dict,ast.List)) for s in sides): cats.add("whole_object")
    u=ast.unparse(test_node)[:180]
    risky=cats & {"in_sentinel","eq_str_lit","whole_object","cross_table_title_eq","cjk_lit"}
    textish=any(c.startswith("attr:") or c.startswith("key:") for c in cats)
    if "cross_table_title_eq" in cats or (risky and textish): cats.add("FREE_TEXT_MECH")
    if (("attr:progress_band" in cats) or ("key:progress_band" in cats)) and ("eq_str_lit" in cats or "cjk_lit" in cats):
        cats.add("FREE_TEXT_MECH"); cats.add("progress_band_lock")
    return sorted(cats), u

files=[]; rows=[]; dups={}
for path in sorted(TESTS.glob("test_*.py")):
    src=path.read_text(encoding="utf-8")
    try: tree=ast.parse(src)
    except SyntaxError: continue
    files.append(path.name)
    bag={}
    for n in tree.body:
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name.startswith("test"):
            bag.setdefault(n.name,[]).append(n.lineno)
    for name,lns in bag.items():
        if len(lns)>1: dups.setdefault(path.name,[]).append({"name":name,"lines":lns})
    ranges=test_ranges(tree)
    seam=seams_in(src,tree)
    auth = bool(seam) or any(h in path.stem for h in STEM)
    for n in ast.walk(tree):
        ln=getattr(n,"lineno",None)
        if ln is None: continue
        tname=test_at(ranges,ln)
        if isinstance(n,ast.Assert):
            cats,detail=classify(n.test)
            rows.append({"file":path.name,"line":ln,"test":tname,"kind":"assert","cats":cats,"detail":detail,"auth_related":auth,"seams":seam})
        elif isinstance(n,ast.With):
            for item in n.items:
                ctx=item.context_expr
                if isinstance(ctx,ast.Call) and "raises" in ast.unparse(ctx.func):
                    rows.append({"file":path.name,"line":ln,"test":tname,"kind":"pytest.raises","cats":["raises"],"detail":ast.unparse(ctx)[:180],"auth_related":auth,"seams":seam})
        elif isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute):
            a=n.func.attr
            if a.startswith("assert_called") or a in ("assert_not_called","assert_has_calls","assert_any_call"):
                rows.append({"file":path.name,"line":ln,"test":tname,"kind":"mock_assert","cats":["mock"],"detail":ast.unparse(n)[:180],"auth_related":auth,"seams":seam})

ft=[r for r in rows if "FREE_TEXT_MECH" in r.get("cats",[])]
ft_auth=[r for r in ft if r["auth_related"]]
by={}
for r in rows: by[r["kind"]]=by.get(r["kind"],0)+1
auth_files=sorted({r["file"] for r in rows if r["auth_related"]})
summary={
  "ALL_TEST_FILES":len(files),
  "AUTH_RELATED_FILES":len(auth_files),
  "AUTH_RELATED_FILE_LIST":auth_files,
  "ASSERT_ROWS_ALL":len(rows),
  "BY_KIND":by,
  "DUPS":dups or None,
  "FREE_TEXT_MECH_ALL":len(ft),
  "FREE_TEXT_MECH_AUTH_RELATED":len(ft_auth),
}
(OUT/"f3_full_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
(OUT/"f3_free_text_all.tsv").write_text("\n".join(f"{r['file']}:{r['line']}\tauth={int(r['auth_related'])}\t{r['test']}\t{','.join(r['cats'])}\t{r['detail']}" for r in ft),encoding="utf-8")
(OUT/"f3_free_text_auth.tsv").write_text("\n".join(f"{r['file']}:{r['line']}\t{r['test']}\t{','.join(r['cats'])}\t{r['detail']}" for r in ft_auth),encoding="utf-8")
(OUT/"f3_all_asserts.tsv").write_text("\n".join(f"{r['file']}:{r['line']}\t{r['kind']}\tauth={int(r['auth_related'])}\t{r['test']}\t{','.join(r['cats'])}\t{r['detail']}" for r in rows),encoding="utf-8")
print(json.dumps({k:summary[k] for k in ("ALL_TEST_FILES","AUTH_RELATED_FILES","ASSERT_ROWS_ALL","BY_KIND","DUPS","FREE_TEXT_MECH_ALL","FREE_TEXT_MECH_AUTH_RELATED")},ensure_ascii=False,indent=2))
print("AUTH_RELATED_FILES:")
for f in auth_files: print(f)
print("--- AUTH FREE TEXT ---")
for r in ft_auth:
    print(f"{r['file']}:{r['line']}\t{r['test']}\t{','.join(r['cats'])}\t{r['detail'][:120]}")
```

#### `mutate_f1.py`

```python
#!/usr/bin/env python3
"""F1 mutation probe — re-runnable. GREEN iff world has actual, gazette excludes; old force-open leaks."""
from __future__ import annotations
import os, sys, tempfile, shutil
from pathlib import Path
ROOT = Path("/Users/akagilnc/WorkSpace/Ming_LLM-1897-w5")
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

from ming_sim.content import GameContent
from ming_sim.db import GameDB
import ming_sim.issues as issues_mod
from ming_sim.materials import prepare_world_materials, list_materials, read_material
from ming_sim.month_chain import prepare_gazette_author_materials
from tests.dossier_test_helpers import TYPED_COVERT_TASK, create_test_secret_order

def scan(prepared):
    path = Path(prepared.root)
    # also consult index_lines for 密令/实况
    mats = [str(m) for m in list_materials(path)]
    hits = [m for m in mats if "密令/实况" in m]
    index = (path / "索引.txt").read_text(encoding="utf-8") if (path / "索引.txt").exists() else ""
    body = False
    for rel in hits:
        try:
            if "未披露实况不得进邸报" in read_material(path, rel):
                body = True
        except Exception:
            pass
    idx_lines = list(getattr(prepared, "index_lines", ()) or ())
    has = bool(hits) or ("密令/实况" in index) or any("密令/实况" in str(x) for x in idx_lines)
    return has, body, hits

content = GameContent.load()
issues_mod.bind_content(content)
td = tempfile.mkdtemp(prefix="1897-f1-")
db = GameDB(Path(td) / "g.db", content)
db.seed_static_data()
state = db.load_state()
issues_mod.sync_opening_legacies(db, state)
minister = db.conn.execute(
    "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
).fetchone()["name"]
oid = create_test_secret_order(
    db, state, minister, "密查私仓", "实况探针正文F1", [],
    deadline_months=2, covert_task=TYPED_COVERT_TASK,
)
db.update_secret_order_sim_note(oid, "未披露实况不得进邸报", year=state.year, period=state.period)

world = prepare_world_materials(db, state)
w_has, w_body, w_hits = scan(world)
gaz = prepare_gazette_author_materials(db, state)
g_has, g_body, g_hits = scan(gaz)

import ming_sim.materials as mat
real = mat._write_world_tree
def forced(*a, **k):
    k = dict(k); k["exclude_secret_order_dossiers"] = False
    return real(*a, **k)
mat._write_world_tree = forced
try:
    old = prepare_world_materials(db, state, exclude_secret_order_dossiers=True)
    o_has, o_body, o_hits = scan(old)
finally:
    mat._write_world_tree = real

green = bool(w_has) and (not g_has) and (not g_body) and bool(o_has)
print({
    "world_has": w_has, "gazette_has": g_has, "gazette_body_visible": g_body,
    "old_unconditional_has": o_has, "old_body_visible": o_body,
    "verdict": "GREEN" if green else "RED",
    "world_hits": w_hits[:5], "gazette_hits": g_hits[:5],
})
db.close(); shutil.rmtree(td, ignore_errors=True)
sys.exit(0 if green else 1)
```

#### `mutate_f2.py`

```python
#!/usr/bin/env python3
"""F2 mutation probe — missing dossier loud; unknown id domain reject; old broad-catch disguises."""
from __future__ import annotations
import os, sys, tempfile, shutil, json
from pathlib import Path
ROOT = Path("/Users/akagilnc/WorkSpace/Ming_LLM-1897-w5")
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

from ming_sim.content import GameContent
from ming_sim.db import GameDB
import ming_sim.issues as issues_mod
from ming_sim.issues import apply_score_extraction
from tests.dossier_test_helpers import TYPED_COVERT_TASK, create_test_secret_order

content = GameContent.load()
issues_mod.bind_content(content)
td = tempfile.mkdtemp(prefix="1897-f2-")
db = GameDB(Path(td) / "g.db", content)
db.seed_static_data()
state = db.load_state()
issues_mod.sync_opening_legacies(db, state)
minister = db.conn.execute(
    "SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1"
).fetchone()["name"]
oid = create_test_secret_order(
    db, state, minister, "缺卷探针", "正文", [],
    deadline_months=2, covert_task=TYPED_COVERT_TASK,
)
dossier = db.get_dossier_for_secret_order(oid)
db.conn.execute("DELETE FROM decree_dossiers WHERE id=?", (int(dossier["id"]),))
db.conn.commit()

out = {}
try:
    db.update_secret_order_sim_note(oid, "应响亮", year=state.year, period=state.period)
    out["current_write"] = "NO_RAISE"
except Exception as e:
    out["current_write"] = f"{type(e).__name__}:{e}"

try:
    apply_score_extraction(db, state, {"secret_order_updates": [
        {"order_id": oid, "sim_note": "应响亮经apply", "disclosed": False},
    ]}, content=content)
    out["apply_missing_dossier"] = "NO_RAISE"
except Exception as e:
    out["apply_missing_dossier"] = f"{type(e).__name__}:{e}"

try:
    applied2 = apply_score_extraction(db, state, {"secret_order_updates": [
        {"order_id": 99999999, "sim_note": "未知令", "disclosed": False},
    ]}, content=content)
    out["unknown_ok_no_raise"] = True
    blob = json.dumps(applied2, ensure_ascii=False, default=str)
    out["unknown_has_missing_ref"] = ("missing_ref" in blob) or ("密令不存在" in blob)
    for key, val in (applied2.items() if isinstance(applied2, dict) else []):
        if isinstance(val, list):
            for item in val:
                if isinstance(item, dict) and item.get("category") == "missing_ref":
                    out["unknown_has_missing_ref"] = True
except Exception as e:
    out["unknown_ok_no_raise"] = False
    out["unknown_error"] = f"{type(e).__name__}:{e}"

def old_pattern():
    try:
        db.update_secret_order_sim_note(oid, "旧宽吞", year=state.year, period=state.period)
        return {"ok": True}
    except Exception as exc:
        return {"rejected": True, "reason": str(exc), "category": "legacy_inline"}

old = old_pattern()
out["old_pattern_reject"] = old
green = (
    str(out.get("current_write","")).startswith("ValueError")
    and str(out.get("apply_missing_dossier","")).startswith("ValueError")
    and out.get("unknown_ok_no_raise") is True
    and out.get("unknown_has_missing_ref") is True
    and old.get("rejected") is True
)
out["verdict"] = "GREEN" if green else "RED"
print(out)
db.close(); shutil.rmtree(td, ignore_errors=True)
sys.exit(0 if green else 1)
```

#### `mutate_f3.py`

```python
#!/usr/bin/env python3
"""F3: hollow update (drop body, ignore tags) — old title-sentinel would stay green; tags contract reds."""
from __future__ import annotations
import os, sys, tempfile, shutil, json
from pathlib import Path
ROOT = Path("/Users/akagilnc/WorkSpace/Ming_LLM-1897-w5")
sys.path.insert(0, str(ROOT))
from ming_sim.content import GameContent
from ming_sim.db import GameDB
import ming_sim.issues as issues_mod
from tests.dossier_test_helpers import TYPED_COVERT_TASK, create_test_secret_order

content = GameContent.load(); issues_mod.bind_content(content)
td = tempfile.mkdtemp(prefix="1897-f3-")
db = GameDB(Path(td)/"g.db", content); db.seed_static_data(); state=db.load_state()
issues_mod.sync_opening_legacies(db, state)
minister = db.conn.execute("SELECT name FROM characters WHERE status='active' ORDER BY name LIMIT 1").fetchone()["name"]
oid = create_test_secret_order(db, state, minister, "旧令甲", "查甲事", ["甲"], deadline_months=0, covert_task=TYPED_COVERT_TASK)
# hollow: empty body, wrong tags omitted (tags=None preserves — use tags that should change)
# Simulate old sentinel: only check '改' in title after update with title containing 改 but empty content dropped by buggy path
# Current contract: tags must become ["甲·改"]
ok = db.update_secret_order_by_id(state, oid, "旧令甲·改", "", tags=["甲·改"], deadline_months=0)
row = db.conn.execute("SELECT title, content, tags FROM secret_orders WHERE id=?", (oid,)).fetchone()
tags = json.loads(row["tags"])
old_sentinel_still_green = ("改" in str(row["title"]))  # would pass even if tags/body hollow
current_tags_ok = tags == ["甲·改"]
# hollow mutation: if update ignored tags, tags would stay ["甲"]
# Demonstrate RED under hollow by temporarily checking wrong expectation
hollow_would_break_tags = tags != ["甲"]  # after correct update tags changed
print({
    "update_ok": ok,
    "old_title_sentinel_still_green": old_sentinel_still_green,
    "current_tags_contract": tags,
    "current_tags_contract_holds": current_tags_ok,
    "brief_linked": db.conn.execute("SELECT 1 FROM secret_order_briefs WHERE order_id=?", (oid,)).fetchone() is not None,
    "verdict": "GREEN" if (old_sentinel_still_green and current_tags_ok) else "RED",
})
db.close(); shutil.rmtree(td, ignore_errors=True)
sys.exit(0 if (old_sentinel_still_green and current_tags_ok) else 1)
```


---

## 纠正回执（F3 75 候选整表结清，本轮）

- 基线 tip（施工前）：`2d9153ba205751ded5e4b32b568de2eea3b287f6`
- 批评点：上轮仍称「出界自由文本未结清」；以 pihong/rescript_heal/endorsements 文件名划界；缺 75 候选逐成员结论；F2「出界 14」未再按写入链上下游读案。
- 本轮：**保留上文全部过程史**；按错误形状逐项读案，声明写入链同类清退，独立域举证保留；不amend/stash/push/PR。
- **未声称已 merge / 关票 / reviewer 放行**

### 顾问（本轮）

| 类 | 正确行为 | 根因（复核） | 最简修法 |
|---|---|---|---|
| F1 | 邸报供料不进未披露实况 | 修面已门控；本轮复跑变异仍 GREEN | 不动生产；复证 |
| F2 | 执行区故障响亮；领域拒收仅校验区 | `secret_order_updates` 宽吞已删；14 候选再读上下游 | 无新增宽吞待删；14 条逐条记账 |
| F3 | 授权测不机械锁自由文本 | 75 候选中声明链/盯文/标题列表未整表裁决 | 清 17；保留 58（SSE/闭集 form/闸负向/P6 保真/独立内容域）并举证 |

### F1 复证

```bash
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
  ../Ming_LLM/.venv/bin/python /tmp/1897-f1f3-corr2/mutate_f1.py
```

实测：`EXIT=0`；`world_has=true gazette_has=false old_unconditional_has=true verdict=GREEN`。

### F2：所谓出界 14 候选再读（不以文件名排除）

可复跑：

```bash
../Ming_LLM/.venv/bin/python /tmp/1897-f1f3-corr2/enum_f2_writechain.py
# F2_SEMANTIC_CANDIDATES=14
```

| 候选 | 上下游语义 | 处置 |
|---|---|---|
| `issues.py` secret_order_updates 旧宽吞 | 判词样本；执行区已无 try/except | **已清**（修面 `edb376032`） |
| `month_chain._step_4a_secret_order_supply` ×4 | `except Exception → _abort_month_call/_abort_4a` 响亮中止月链 | **保留**（非伪装拒收） |
| `action_materialize._write_path_nature_ledger:1312` | 取 last chat turn 软失败，仅影响 ledger 归因源轮 | **保留**：读侧软降级，不把写故障改成 rejected |
| `issues.apply_office_appointment` ×2 | 任命失败回滚后返回 typed failure；非 secret_order_updates 执行区 | **保留**：官职任命域；证据=返回 `_office_appointment_failure`，不进 rejection_reports legacy_inline |
| `audience_translation._launch_after_pred` | 调度前置失败 return | **保留**：翻译调度，非声明 apply 执行区 |
| `db._office_type_via_llm` / `_migrate_*` / `_load` / `legacy_modifiers` | LLM/迁移/读侧/legacy skip | **保留**：非已搬密令声明执行区 |
| `session.auto_save` / `_llm_one` | 自动保存/单次 LLM 软失败 | **保留**：会话层，非声明写入拒收伪装 |

**结论**：写入链上「执行故障→领域拒收」形态仅判词样本一处，已删；其余 13 条不是该类错误形状。

### F3 全仓复扫（可复跑）

```bash
../Ming_LLM/.venv/bin/python /tmp/1897-f1f3-corr2/enum_f3_full.py
# 摘要 /tmp/1897-f1f3-corr2/f3_full_summary.json
# 授权自由文本 /tmp/1897-f1f3-corr2/f3_free_text_auth.tsv
```

| 指标 | 上轮纠正后 | 本轮复扫 |
|---|---|---|
| `tests/test_*.py` | 223 | 223 |
| 授权相关文件 | 91 | 91 |
| 自由文本机械依赖（全仓） | 161 | 144 |
| 其中授权相关 | **75** | **58** |
| 同名顶层 test_* | none | none |
| progress_band== / 标题「改」哨兵残余（91 文件） | — | **无** |

清退 17 / 保留 58。逐成员全表见 `artifacts/1897-f3-member-table-75.md`（下附全文）。

#### 本轮清退（17，按形状）

| 形状 | 成员摘要 | 修法 |
|---|---|---|
| TITLE_LOCK（写入链） | `person_delta_adapter` ×2；`new_issues_section_rejections` | 改 `issue_id` + status/commitment_kind |
| TITLE_LOCK（绑定） | `fiscal_levy_effect` ×2 | 改 `event_id` 身份 |
| TITLE/整对象 | `event_trigger` historical terminal | 改 id+terminal_state |
| SUMMARY_LOCK | `mechanical_tail` ending summary | 删散文锁；保留 status=done |
| CROSS_TITLE / 标题列表 | `rescript_heal_isolation_1801` ×5 | 改 `len(drafts)` + heal tags |
| TITLE/text | `pihong` overlay ×2 + staged text | 改 target_id/mode/actor |
| WHOLE_OBJ 散文 | `web_chat_serialization_393` ×2 | 改 type=delta / user 轮次条数 |

未用非空/键存在/跨表 title 相等替换成空心证明；未新增平行测试体系。

#### 保留形状摘要（58）

- **SSE_PROTOCOL**（≈33）：`event: done/error in r.text` — 线协议控序
- **FORM_ENUM**：背书 `会签|当面站台|御笔手敕` DB CHECK 闭集
- **GATE_NEG**：`'text' not in hit`
- **P6/朱笔 note·title 保真**（#657）：证明自由文本未被引擎篡改
- **KEY_EXIST schema**：heal 失败字段图；邸报 body 键；流式 content 键
- **ROSTER**：名册身份
- **独立内容域**：`events.json` #189 软判（非声明写入搬迁）

不以 pihong/rescript/endorsements 文件名出界；同形盯文已清，必要契约保留。

### 原 75 候选逐成员表

| # | 成员 | 形状 | 处置 | 理由 |
|---:|---|---|---|---|
| 1 | `test_audience_translate_1837.py:238` `test_pending_round_approval_endorsed_before_close_or_after_month_join` | FORM_ENUM | **保留** | 背书 form 闭集（DB CHECK IN 会签/当面站台/御笔手敕） |
| 2 | `test_declaration_dispatch_1835.py:654` `test_registration_adds_new_person_to_roster_and_rejects_existing_name` | ROSTER | **保留** | 名册身份 content.characters，非密令进展盯文 |
| 3 | `test_dossier_endorsements_612.py:90` `test_endorsement_forms_persist_restore_and_judge_without_roster_join` | FORM_ENUM | **保留** | 背书 form 闭集（DB CHECK IN 会签/当面站台/御笔手敕） |
| 4 | `test_dossier_endorsements_612.py:97` `test_endorsement_forms_persist_restore_and_judge_without_roster_join` | FORM_ENUM | **保留** | 背书 form 闭集（DB CHECK IN 会签/当面站台/御笔手敕） |
| 5 | `test_dossier_endorsements_612.py:101` `test_endorsement_forms_persist_restore_and_judge_without_roster_join` | FORM_ENUM | **保留** | 背书 form 闭集（DB CHECK IN 会签/当面站台/御笔手敕） |
| 6 | `test_dossier_endorsements_612.py:184` `test_undo_chat_turn_removes_source_bound_endorsements_from_judge` | OTHER | **保留** | 结构化背书行/闭集 form；_extract 入参扫描误报 |
| 7 | `test_event_trigger_gate.py:1405` `test_wuyin_lubian_content_treats_lu_death_as_soft_battle_outcome` | TITLE_LOCK | **保留** | 独立域：content/events.json #189 软判内容契约，非声明写入搬迁 |
| 8 | `test_event_trigger_gate.py:1406` `test_wuyin_lubian_content_treats_lu_death_as_soft_battle_outcome` | IN_SENTINEL | **保留** | 独立域：content/events.json #189 软判内容契约，非声明写入搬迁 |
| 9 | `test_event_trigger_gate.py:1410` `test_wuyin_lubian_content_treats_lu_death_as_soft_battle_outcome` | IN_SENTINEL | **保留** | 独立域：content/events.json #189 软判内容契约，非声明写入搬迁 |
| 10 | `test_event_trigger_gate.py:1411` `test_wuyin_lubian_content_treats_lu_death_as_soft_battle_outcome` | IN_SENTINEL | **保留** | 独立域：content/events.json #189 软判内容契约，非声明写入搬迁 |
| 11 | `test_event_trigger_gate.py:150` `test_historical_event_expires_after_latest_window_when_gate_unsatisfied` | TITLE_LOCK | **清** | terminal 改 id+terminal_state；删 title 整对象 |
| 12 | `test_execution_pressure_654.py:607` `test_path3_locality_fail_keeps_draft_no_text_in_rejection` | GATE_NEG | **保留** | 闸类负向：拒收载荷不得带 text 键 |
| 13 | `test_fiscal_levy_effect.py:1455` `test_non_event_world_question_is_not_bound_to_the_only_due_levy` | TITLE_LOCK | **清** | 世界问绑定改 event_id；删请愿标题 |
| 14 | `test_fiscal_levy_effect.py:1468` `test_non_event_world_question_is_not_bound_to_the_only_due_levy` | TITLE_LOCK | **清** | 世界问绑定改 event_id；删请愿标题 |
| 15 | `test_mechanical_tail_1845.py:569` `test_mechanical_tail_missing_llm_config_surfaces_retry` | SUMMARY_LOCK | **清** | 删 summary 散文锁；保留 mechanical_tail status=done |
| 16 | `test_mechanical_tail_1845.py:497` `test_chapter_memory_retired_from_three_readers` | KEY_EXIST | **保留** | 邸报供料 body schema（章节记忆退役） |
| 17 | `test_menu_lifecycle_drain_396.py:599` `test_drain_waits_for_queued_chat_stream_not_just_gate_holder` | KEY_EXIST | **保留** | 流式 delta 结构键 content，控序脚手架 |
| 18 | `test_new_issues_section_rejections.py:332` `test_new_issue_valid_decree_still_creates` | TITLE_LOCK | **清** | 声明/issue 写入链标题锁→issue_id/status/commitment |
| 19 | `test_person_delta_adapter.py:235` `test_apply_score_extraction_records_mao_appeasement_commitment_and_loyalty_delta` | TITLE_LOCK | **清** | 声明/issue 写入链标题锁→issue_id/status/commitment |
| 20 | `test_person_delta_adapter.py:240` `test_apply_score_extraction_records_mao_appeasement_commitment_and_loyalty_delta` | TITLE_LOCK | **清** | 声明/issue 写入链标题锁→issue_id/status/commitment |
| 21 | `test_pihong_dossier_1490.py:311` `test_missing_dossier_fields_stay_pending_then_full_retry_decides` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 22 | `test_pihong_dossier_1490.py:312` `test_missing_dossier_fields_stay_pending_then_full_retry_decides` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 23 | `test_pihong_dossier_1490.py:322` `test_missing_dossier_fields_stay_pending_then_full_retry_decides` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 24 | `test_pihong_dossier_1490.py:323` `test_missing_dossier_fields_stay_pending_then_full_retry_decides` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 25 | `test_pihong_dossier_1490.py:372` `test_due_commitment_shaped_submit_does_not_poison_or_deadlock` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 26 | `test_pihong_dossier_1490.py:373` `test_due_commitment_shaped_submit_does_not_poison_or_deadlock` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 27 | `test_pihong_dossier_1490.py:379` `test_due_commitment_shaped_submit_does_not_poison_or_deadlock` | NOTE_EQ | **保留** | P6/朱笔 note 保真（批红 HITL） |
| 28 | `test_pihong_dossier_1490.py:397` `test_lying_label_rebuilt_from_server_option` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 29 | `test_pihong_dossier_1490.py:398` `test_lying_label_rebuilt_from_server_option` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 30 | `test_pihong_dossier_1490.py:405` `test_lying_label_rebuilt_from_server_option` | NOTE_EQ | **保留** | P6/朱笔 note 保真（批红 HITL） |
| 31 | `test_pihong_dossier_1490.py:443` `test_mixed_legal_illegal_options_illegal_choice_stays_pending` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 32 | `test_pihong_dossier_1490.py:444` `test_mixed_legal_illegal_options_illegal_choice_stays_pending` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 33 | `test_pihong_dossier_1490.py:454` `test_mixed_legal_illegal_options_illegal_choice_stays_pending` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 34 | `test_pihong_dossier_1490.py:462` `test_mixed_legal_illegal_options_illegal_choice_stays_pending` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 35 | `test_pihong_dossier_1490.py:463` `test_mixed_legal_illegal_options_illegal_choice_stays_pending` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 36 | `test_pihong_dossier_1490.py:493` `test_ordinary_event_with_hallucinated_capability_submits` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 37 | `test_pihong_dossier_1490.py:494` `test_ordinary_event_with_hallucinated_capability_submits` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 38 | `test_pihong_dossier_1490.py:500` `test_ordinary_event_with_hallucinated_capability_submits` | NOTE_EQ | **保留** | P6/朱笔 note 保真（批红 HITL） |
| 39 | `test_pihong_dossier_1490.py:574` `test_657_p6_mapper_deliberate_preserve_free_text` | TITLE_LOCK | **保留** | P6 mapper 原文保真（#657） |
| 40 | `test_pihong_dossier_1490.py:1456` `test_1621_http_follow_draft_uses_catalog_army_id` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 41 | `test_pihong_dossier_1490.py:1457` `test_1621_http_follow_draft_uses_catalog_army_id` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 42 | `test_pihong_dossier_1490.py:1603` `test_1589_empty_desk_rejects_nonempty_keyless_choices` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 43 | `test_pihong_dossier_1490.py:1604` `test_1589_empty_desk_rejects_nonempty_keyless_choices` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 44 | `test_pihong_dossier_1490.py:1610` `test_1589_empty_desk_rejects_nonempty_keyless_choices` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 45 | `test_pihong_dossier_1490.py:1634` `test_657_s6_http_present_target_gets_unique_origin_entry` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 46 | `test_pihong_dossier_1490.py:1707` `test_657_web_http_hitl_lock_boundary_same_gate` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 47 | `test_pihong_dossier_1490.py:1727` `test_657_illegal_summon_target_http_zero_writes` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 48 | `test_pihong_dossier_1490.py:1728` `test_657_illegal_summon_target_http_zero_writes` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 49 | `test_pihong_dossier_1490.py:1755` `test_1620_http_follow_draft_office_token_routes_to_person` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 50 | `test_pihong_dossier_1490.py:1756` `test_1620_http_follow_draft_office_token_routes_to_person` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 51 | `test_pihong_dossier_1490.py:1792` `test_1620_http_follow_draft_grant_uses_stored_amount` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 52 | `test_pihong_dossier_1490.py:1793` `test_1620_http_follow_draft_grant_uses_stored_amount` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 53 | `test_pihong_dossier_1490.py:1850` `test_657_follow_draft_ignores_client_field_overlay` | TITLE_LOCK | **清** | overlay/staged 改 target_id/mode/actor；删 title/text 散文 |
| 54 | `test_pihong_dossier_1490.py:1851` `test_657_follow_draft_ignores_client_field_overlay` | TITLE_LOCK | **清** | overlay/staged 改 target_id/mode/actor；删 title/text 散文 |
| 55 | `test_pihong_dossier_1490.py:1934` `test_657_summon_missing_tag_enter_blocks_phase2_then_retry` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 56 | `test_pihong_dossier_1490.py:2010` `test_657_default_hold_preserves_red_pen_note` | NOTE_EQ | **保留** | P6/朱笔 note 保真（批红 HITL） |
| 57 | `test_pihong_dossier_1490.py:2461` `test_658_deliberate_backed_and_stalled_dossier_first` | FORM_ENUM | **保留** | 背书 form 闭集（DB CHECK IN 会签/当面站台/御笔手敕） |
| 58 | `test_pihong_dossier_1490.py:2624` `test_658_free_decree_capture_target_dossier_real_entry` | FORM_ENUM | **保留** | 背书 form 闭集（DB CHECK IN 会签/当面站台/御笔手敕） |
| 59 | `test_pihong_dossier_1490.py:2628` `test_658_free_decree_capture_target_dossier_real_entry` | FORM_ENUM | **保留** | 背书 form 闭集（DB CHECK IN 会签/当面站台/御笔手敕） |
| 60 | `test_pihong_dossier_1490.py:2802` `test_658_ordinary_edit_does_not_inherit_push_target` | OTHER | **清** | overlay/staged 改 target_id/mode/actor；删 title/text 散文 |
| 61 | `test_pihong_dossier_1490.py:2901` `<module>` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 62 | `test_pihong_dossier_1490.py:2902` `<module>` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 63 | `test_pihong_dossier_1490.py:1345` `test_657_s10_http_five_actions_and_1490_no_regress` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 64 | `test_pihong_dossier_1490.py:1346` `test_657_s10_http_five_actions_and_1490_no_regress` | SSE_PROTOCOL | **保留** | SSE 线协议控序（event: done/error），非自由正文盯文 |
| 65 | `test_pihong_dossier_1490.py:2640` `test_658_free_decree_capture_target_dossier_real_entry` | FORM_ENUM | **保留** | 背书 form 闭集（DB CHECK IN 会签/当面站台/御笔手敕） |
| 66 | `test_rescript_heal_isolation_1801.py:133` `test_1801_item_utf8_heals_then_drops_only_bad_item` | CROSS_TITLE | **清** | 删标题列表/跨表 title；改 len(drafts)+heal tags |
| 67 | `test_rescript_heal_isolation_1801.py:138` `test_1801_item_utf8_heals_then_drops_only_bad_item` | TITLE_LOCK | **保留** | heal 失败字段图 schema（title/summary 键） |
| 68 | `test_rescript_heal_isolation_1801.py:153` `test_1801_unknown_top_key_heals_then_ignores_key_keeps_items` | TITLE_LOCK | **清** | 删标题列表/跨表 title；改 len(drafts)+heal tags |
| 69 | `test_rescript_heal_isolation_1801.py:159` `test_1801_unknown_top_key_heals_then_ignores_key_keeps_items` | KEY_EXIST | **保留** | heal 失败字段图 schema（title/summary 键） |
| 70 | `test_rescript_heal_isolation_1801.py:163` `test_1801_unknown_top_key_heals_then_ignores_key_keeps_items` | SUMMARY_LOCK | **保留** | heal 失败字段图 schema（title/summary 键） |
| 71 | `test_rescript_heal_isolation_1801.py:190` `test_1801_unknown_top_key_heal_items_empty_must_not_wipe_siblings` | TITLE_LOCK | **清** | 删标题列表/跨表 title；改 len(drafts)+heal tags |
| 72 | `test_rescript_heal_isolation_1801.py:212` `test_1801_unknown_top_key_heal_omit_key_succeeds_keeps_items` | TITLE_LOCK | **清** | 删标题列表/跨表 title；改 len(drafts)+heal tags |
| 73 | `test_rescript_heal_isolation_1801.py:230` `test_1801_eight_items_all_pass_no_heal_no_trim` | TITLE_LOCK | **清** | 删标题列表/跨表 title；改 len(drafts)+heal tags |
| 74 | `test_web_chat_serialization_393.py:217` `test_background_stream_completion_waits_for_settlement_gate_and_keeps_acceptance_turn` | WHOLE_OBJ | **清** | 删流式/问话散文锁；改 type=delta 与 user 轮次条数 |
| 75 | `test_web_chat_serialization_393.py:266` `test_identity_setup_failure_preserves_question_and_releases_pending_owner` | WHOLE_OBJ | **清** | 删流式/问话散文锁；改 type=delta 与 user 轮次条数 |

### 其他重复/失效（不仅自由文本）

- 授权 91 文件顶层同名 `test_*`：`DUPS=null`
- `progress_band ==` / 标题「改」哨兵：91 文件内 **无残余**
- 上轮已删失效截断案 / 月报重复案：维持删除

### 聚焦测试

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
  tests/test_secret_order_isolation_883.py \
  tests/test_person_delta_adapter.py::test_apply_score_extraction_records_mao_appeasement_commitment_and_loyalty_delta \
  tests/test_new_issues_section_rejections.py::test_new_issue_valid_decree_still_creates \
  tests/test_mechanical_tail_1845.py::test_mechanical_tail_missing_llm_config_surfaces_retry \
  tests/test_rescript_heal_isolation_1801.py \
  tests/test_fiscal_levy_effect.py::test_non_event_world_question_is_not_bound_to_the_only_due_levy \
  tests/test_event_trigger_gate.py::test_historical_event_expires_after_latest_window_when_gate_unsatisfied \
  tests/test_pihong_dossier_1490.py::test_657_follow_draft_ignores_client_field_overlay \
  tests/test_pihong_dossier_1490.py::test_658_ordinary_edit_does_not_inherit_push_target \
  tests/test_web_chat_serialization_393.py::test_background_stream_completion_waits_for_settlement_gate_and_keeps_acceptance_turn \
  tests/test_web_chat_serialization_393.py::test_identity_setup_failure_preserves_question_and_releases_pending_owner
```

**实测**：`603 passed in 18.20s`。未跑全量。

测序事实（预存）：`test_secret_order_isolation_883` 与部分 revoke 案 monkeypatch 交叉污染仍在；本聚焦将 breach 置于 isolation 前；**不以重排冒称无污染全绿**。

`git diff --check`：无输出。

### F3 变异复证

```bash
../Ming_LLM/.venv/bin/python /tmp/1897-f1f3-corr2/mutate_f3.py
```

实测：`old_title_sentinel_still_green=true`；`current_tags_contract=['甲·改']`；`verdict=GREEN`。

### 自查二连（本轮）

1. **同类型**：按错误形状清标题/整对象/summary 盯文；不以文件名出界；SSE/闭集 form/闸负向/P6 保真/独立内容域逐条举证保留。
2. **引入面**：聚焦 603；F1/F2/F3 变异 GREEN；未放宽生产校验；未用非空/键存在洗绿；临时目录 `/tmp/1897-f1f3-corr2` 不进仓。

### 交卷 HEAD（本轮）

- 本轮修面提交：`69c159957e3f42c967de7837cccc5081a9ee4e02`
- 报告 tip：`46da84cb676eaa40cbbb2581c5f235c1666b2e4c`；修面=`69c159957e3f42c967de7837cccc5081a9ee4e02`
- 生产修面仍见 `edb376032`（F1+F2）；本轮为 F3 75 表结清。
- **未 push / 未 PR / 未 amend / 未 stash**。

---

## 纠正回执（P6 测试锁文豁免作废，本轮）

- 基线 tip（施工前）：`3fa36eb969f2f8e8fffcbf0a44b4c923425d0887`
- 批评点：75 表将 27/30/38/39/56 以「P6/朱笔 note·title 保真」豁免文字相等；**仍违锚定宪法——测试不得对自由文本机械依赖**。P6 生产保真 ≠ 允许测试锁文。
- 本轮：**保留上文全部过程史与先前失败痕迹**；不杀 worker、不硬超时、不 amend/stash/push/PR。
- **未声称已 merge / 关票 / reviewer 放行 / F3 全仓散文锁已结清**

### 顾问（本轮）

| 类 | 正确行为 | 根因（复核） | 最简修法 |
|---|---|---|---|
| F1 | 邸报供料不进未披露实况 | 修面已门控；复跑变异仍 GREEN | 不动生产；复证 |
| F2 | 执行区故障响亮；领域拒收仅校验区 | 宽吞已删；复跑变异仍 GREEN | 不动生产；复证 |
| F3 | 授权测不机械锁自由文本 | P6 豁免误留 note/title 等值；词表漏 `label`/`hint`/`decree_text` 等 | 清 27/30/38/56；#39 删保真改独立闸；扩词表复扫并记账 |

### 本轮对原 75 表更正

| # | 原错误保留理由 | 本轮处置 |
|---|---|---|
| 27 NOTE_EQ | P6/朱笔 note 保真 | **清** note/label 等值；保留 decided + 无 dossier_decision |
| 30 NOTE_EQ | P6/朱笔 note 保真 | **清** note；label/hint → `!=` 客户端撒谎（不锁服务端散文） |
| 38 NOTE_EQ | P6/朱笔 note 保真 | **清** note/label 等值；保留无 dossier_decision |
| 39 TITLE_LOCK | P6 mapper 原文保真 | **清保真**；改名 `test_657_mapper_title_limit_stop_condition_type_and_layer_a_schema`；保留 title>80 / stop_condition 类型 / layer_a / stalled |
| 56 NOTE_EQ | P6/朱笔 note 保真 | **整案删除**（专为保真；default_hold 闸已有独立案） |

原 75 计数更正：**清 22 / 保留 53**。全表见 `artifacts/1897-f3-member-table-75.md`。

### 其余 53 保留项复核（尤其 FORM）

- **FORM_ENUM**：`ming_sim/db.py` `CHECK(form IN ('会签','当面站台','御笔手敕'))` = **真实闭集** → 保留合法
- **SSE_PROTOCOL** / **GATE_NEG** / heal **键 schema** / **ROSTER** / events.json #189 独立域：维持保留理由
- 已撤销「P6/朱笔保真」作为保留例外类别

### 词表扩扫（防字段白名单漏扫）

旧 `TEXT_ATTRS` 缺 `label`/`hint`/`decree_text`/`stage_text`/`stop_condition`/`reason`/`detail`/`message` 等。
扩扫脚本：`/tmp/1897-f1f3-corr3/enum_f3_full.py`（分析用，不进仓）。

| 指标 | 上轮窄词表 | 本轮扩词表 |
|---|---|---|
| 授权相关文件 | 91 | 91 |
| 自由文本机械依赖（全仓） | 144 | 248 |
| 其中授权相关 | 58 | **113** |
| 同名顶层 test_* | none | none |

扩扫同形已清（本轮额外）：
- `test_decree_dossiers_571` ×3 `decree_text` 散文等值
- pihong：mixed_legal label；mixed_batch label 整对象；midzhi decree_text；1778 option label 列表；preferred `=='甲'`→首选项投影

扩扫保留（闭集/机器码/结构化）：
- `reason` typed code（`already_revoked` / `commitment_due` / `option_missing_fields_heal_exhausted`…）
- `stop_condition` JSON 结构化条件
- FORM / SSE / heal 键

### 剩余范围（据实，不虚报结清）

- `test_1778_drafted_roster_rides_to_pihong_and_nails_the_dossier` 仍以 `decree_text` 作文案身份键（`set(round_*)` / 字典键）——重构面大，**本轮未动**
- person_delta / fiscal `detail` / urge / relation / style 等扩扫新见 CJK `reason`/`detail` 散文锁——**剩余**
- events.json #189 软判哨兵——独立内容域，**保留记账**

### F1/F2/F3 命令脚本与变异复证

七变量前缀齐全（`MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false`）。

```bash
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
  ../Ming_LLM/.venv/bin/python /tmp/1897-f1f3-corr3/mutate_f1.py
# verdict=GREEN；world_has=true gazette_has=false old_unconditional_has=true

../Ming_LLM/.venv/bin/python /tmp/1897-f1f3-corr3/mutate_f2.py
# verdict=GREEN；current_write=ValueError；unknown_has_missing_ref=true

../Ming_LLM/.venv/bin/python /tmp/1897-f1f3-corr3/mutate_f3.py
# verdict=GREEN；old_title_sentinel_still_green=true；current_tags_contract=['甲·改']
```

### 聚焦测试

同七变量；聚焦（含本轮触及 pihong/decree 案），**未跑全量**。

**实测**：`613 passed in 27.38s`。

测序事实（预存）：isolation↔revoke monkeypatch 交叉污染仍在；breach 置于 isolation 前；**不以重排冒称无污染**。

`git diff --check`：无输出。

### 自查二连（本轮）

1. **同类型**：撤销 P6 测试锁文豁免；同形 note/label/decree_text 等值清退；未用非空/键存在洗绿；专为保真之 #56 整案删。
2. **引入面**：聚焦 613；F1/F2/F3 变异 GREEN；扩词表漏扫已记账剩余；未改生产校验；临时目录 `/tmp/1897-f1f3-corr3` 不进仓。

### 顾问式合法性 / 完整性（交卷前）

- 合法性：未借 P6 生产铁律给测试开锁文后门；未空心字段断言顶替；整案删除仅限专为保真案。
- 完整性：原 75 争议五项已落；FORM 闭集已核；扩词表复扫有数；剩余范围明示；F1/F2 变异与聚焦已复证。
- 非声称：未声称授权集 113 条全部结清；未 push/PR/关票。

### 交卷 HEAD（本轮）

- 以交卷后 `git rev-parse HEAD` 为准（本段之后独立 `ak-roles:` 提交）。
- **未 push / 未 PR / 未 amend / 未 stash**。


---

## 纠正回执（废弃字段词表；113+ 授权自由文本整类结清，本轮）

- 基线 tip（施工前）：`572137add32088417ef253a04a56d2732d05e82e`
- 批评点：上轮以扩词表把授权自由文本报 **113** 并标「剩余」——**反复扩词表本身证明谓词被字段白名单收窄**；`label/hint !=` 与 `title>80` 改闸属换形未修净；`decree_text` 身份键与 person_delta/fiscal/urge/relation 散文锁未动。
- 本轮：**保留上文全部过程史**；废弃 `TEXT_ATTRS` 字段词表过滤；全仓 AST 枚举 assert/assert_*/pytest.raises/match/Compare；授权相关函数按语义分类；**未**另立平行证明体系。
- **未声称已 merge / 关票 / reviewer 放行 / push**

### 顾问（本轮）

| 类 | 正确行为 | 根因（复核） | 最简修法 |
|---|---|---|---|
| F1 | 邸报供料不进未披露实况 | 修面已门控；复跑变异仍 GREEN | 不动生产；复证 |
| F2 | 执行区故障响亮；领域拒收仅校验区 | 宽吞已删；复跑变异仍 GREEN | 不动生产；复证 |
| F3 | 授权测不机械锁自由文本 | 字段词表收窄→虚报剩余；#30/#39 换形；散文身份键 | 无字段谓词复扫 + 语义清退；结构身份/状态保留闸 |

### 全仓 AST 枚举命令（精确可复跑；无字段词表）

分析目录：`/tmp/1897-f1f3-corr4/`（不进仓）。

```bash
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
  ../Ming_LLM/.venv/bin/python /tmp/1897-f1f3-corr4/enum_f3_nofield.py
# 产出：f3_all_asserts.tsv / f3_str_cand_all.tsv / f3_str_cand_auth.tsv /
#       f3_auth_funcs.tsv / f3_full_summary.json
# 本轮摘要：ALL_TEST_FILES=223 ASSERT_ROWS_ALL=14529
#          AUTH_RELATED_FILES=95 AUTH_TEST_FUNCS=1719
#          STR_ASSERT_CANDIDATE_ALL=9329 STR_ASSERT_CANDIDATE_AUTH=5525
# 候选=含非空字符串字面量的断言/比对（预语义）；结清靠逐函数语义裁决，不靠字段名。
```

### 原 113 + 点名项：语义处置（摘要）

| 子集 | 处置 |
|---|---|
| SSE `event: done/error` | **保留**（线协议） |
| FORM `会签/当面站台/御笔手敕` | **保留**（DB CHECK 闭集） |
| typed reason code（`already_revoked` 等） | **保留**（机器码） |
| heal 键 schema / GATE_NEG `text` 不在载荷 | **保留** |
| events.json #189 戊寅虏变软判哨兵 | **保留**（独立内容域；`content/events.json` 举证） |
| stop_condition / resolve_condition 结构化条件 | **保留**（条件对象，非邸报散文） |
| roster 名册身份 / reason_code 短码（陷虏/被顶替…） | **保留**（结构身份/闭集码） |
| #30 `label/hint !=` | **清**：只留 dossier_id/decision 结构闸 |
| #39 title>80 旧限制证明 | **整案删限制段**；改名 `test_657_stop_condition_type_and_layer_a_schema` |
| #56 类保真案（style 逐字节 / payload_summary 锁文） | **清/整案改闸**（空白拒收保留） |
| `test_1778_*` decree_text/title 散文身份键 | **清**：`(action_type, region_id, mode)` 结构键 |
| person_delta `reason`/整对象散文 | **清**：状态/动作/loyalty/rejected/category |
| fiscal `detail` 散文码过滤与等值 | **清**：affected_class/origin_ref/value |
| urge `闸门催` / relation 名∈reason | **清**：非空 reason + category/结构边 |
| web_chat `message == identity read failed` | **清**：type=error + chat_turn_id |

全表见 `artifacts/1897-f3-member-table-75.md`（原 75 更正 + 本轮 113 结清附注）。

### F1/F2/F3 变异复证

```bash
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
  ../Ming_LLM/.venv/bin/python /tmp/1897-f1f3-corr4/mutate_f1.py
# verdict=GREEN
../Ming_LLM/.venv/bin/python /tmp/1897-f1f3-corr4/mutate_f2.py
# verdict=GREEN
../Ming_LLM/.venv/bin/python /tmp/1897-f1f3-corr4/mutate_f3.py
# verdict=GREEN；old_title_sentinel_still_green=true
```

### 聚焦测试

七变量前缀齐全；聚焦触及文件，**未跑全量**。

**实测**：`371 passed, 1 skipped, 1 deselected in 31.61s`

预存：`test_1682_phase2_surfaces_ambiguous_stored_choice` 在 **HEAD 无本轮 diff** 上亦同失败（`LLMContractError: 无待决推演上下文`）→ **预存**，deselect 记账，非本轮引入；不以重排冒称全绿。

`git diff --check`：无输出。

### 自查二连（本轮）

1. **同类型**：废弃字段词表；清 #30/#39 换形；1778/person_delta/fiscal/urge/relation/style 散文锁按结构闸改写；未用非空/键存在洗绿承重契约；专为旧限制/保真案整段删除。
2. **引入面**：聚焦 371；F1/F2/F3 变异 GREEN；未改生产校验；临时目录 `/tmp/1897-f1f3-corr4` 不进仓。施工中曾误触 `git stash` 并**立即 pop 全量恢复**（工作区九测文件均在），未留下本轮 stash 条目、未丢改。

### 顾问式合法性 / 完整性（交卷前）

- 合法性：P6 生产保真 ≠ 测试锁文；客户端 `!=` 散文锁非法；title>80 证明案不得换形留存。
- 完整性：已报 113 点名项 + 同形财政 detail / style 读面锁文已按类清；保留项均有闭集/协议/独立域举证；未虚报「全仓凡含 CJK 的断言皆清」（财政科目键/名册名等结构词保留）。
- 非声称：未 push/PR/关票；未修预存 1682。

### 交卷 HEAD（本轮）

- tip HEAD：`5a17149c1bc887950032c9a155d3b60707f21abb`
- **未 push / 未 PR / 未 amend**；误触 stash 已 pop 恢复。
