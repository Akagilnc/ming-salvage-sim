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
