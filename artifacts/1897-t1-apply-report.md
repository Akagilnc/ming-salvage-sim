# #1897 T1 apply 回执

- **角色**：修内司（ak-roles fixer）
- **工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1897-w5`
- **分支**：`ak-roles/issue-1897-k1-k2-f3-fixer-20261005-115628`
- **新判词真源**：`artifacts/1897-t1-review-input.json`（全文已读，未摘要替代）
- **任务包**：`~/.ak-roles/books/Ming_LLM/1897/runs/01a109fb-df35-7bb6-936d-039433dd815c@fixer/fix-packet.md`
- **末附件**：`.../attachments/04-1897-judge-21651f2d0.json`
- **范围**：T1 整类（`21651f2d0`→`6c44b0e02` 修理 diff 内被改写的 Python/Web 测试）。**K1/K2 不动生产。**
- **禁止项**：无 amend／stash／rewrite／push／PR；七变量 BIN=/usr/bin/false；不全量；不真模型；不改法。

**不宣称 merge 或关票。**

---

## 判词要点（原文约束）

T1：修理把盯文换成存在／非空／长度／键在空壳，并误删闸类负向案。方向：枚举谓词为起点非白名单；逐案要么最短结构化断言（含静态资产身份分桶闸），要么删壳；不得键在／非空／len／strip 充数；恢复被误删负向身份闸；不扩大盯文禁令删负向闸。首轮笼统合法不可信。

---

## 枚举命令（精确）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1897-w5
# 谓词起点（非白名单）
python3 - <<'PY'
import re, subprocess
from collections import defaultdict
diff = subprocess.check_output(
    ["git","diff","21651f2d0","-U0","--","tests","web"], text=True, errors="replace")
hollow = re.compile(
    r" in .*keys|is not None|isinstance|\.strip\(\)|len\(.*\)\s*[<>]"
    r"|toBeGreaterThan|not\.toBeNull|assert .+ in |trim\(\)\.length")
# …逐文件汇总新增命中行，再逐案读消费者与 base 双向比对
PY
```

修后复扫（strip／键在／trim.length 等非法换形新增行）：`remaining_hollow_added {}`。

---

## 完整成员表

# T1 成员处置表（完整）

枚举范围：`git diff 21651f2d0 -U0 -- tests web` 的新增断言行，谓词：
`in .*keys|is not None|isinstance|\.strip\(\)|len\(.*\) *[<>]|toBeGreaterThan|not.toBeNull|assert ".." in |trim().length`
（谓词为起点非白名单；逐案读消费者与 base 双向比对。）

## `tests/test_featured_dossiers_494.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_every_active_seven_faction_minister_has_featured_dossier` | 恢复 | 静态资产字段须进入 minister_dossier 渲染；minister_dossier→x 变异红 |
| `test_seven_faction_dossiers_are_objective_and_identity_scoped` | 恢复 | identity 分桶闸：internal not in middle/low；core/agenda 分桶；P4 裸数负向。删 len 形状壳 |
| `test_north_star_ministers_have_distinct_featured_voices` | 恢复 | 静态 voice 字段入 dossier 且 dossier⊆full；distinct voices |

## `tests/test_style_temperament_641.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_inertia_natural_resolve_applies_temperament_style` | 恢复 | characters.style 列 before≠after + runtime；非 person_logs 计数洗绿 |
| `test_apply_score_extraction_writes_temperament_style_and_log` | 恢复 | style 列契约 + applied 结构 |
| `test_temperament_blank_style_rejected_keeps_prior` | 保留/恢复 | 领域拒收闸 + style 列/runtime 保持 |
| `test_temperament_outer_tx_rollback_restores_db_and_runtime` | 恢复 | 回滚后 style 列与 runtime 同回；删日志计数空壳 |
| `test_temperament_committed_style_survives_reload` | 恢复 | reload 后 style 列续存；删 person_logs 恒真壳 |
| `test_apply_score_extraction_rejects_invalid_temperament` | 保留/恢复 | 领域拒收闸 + style 列不变 |
| `test_relation_edge_events_do_not_mutate_style` | 恢复 | 落边不改 style 列/runtime |
| `test_temperament_does_not_write_relation_edges` | 恢复 | 性情写 style 列且不写边 |
| `test_character_context_with_db_reads_own_style_and_viewer_ledger` | 删除维持 | 所称消费者未调用；不恢复空心壳 |

## `tests/test_relation_brew_636.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_founding_summary_survives_consecutive_brews` | 删壳保结构 | 删 founding/recent 键在；保留 dimension + last_event_id 水位 |
| `test_no_new_events_and_no_pending_month_bytes_unchanged_zero_brews` | 删壳保结构 | 保留水位/dimension；行存在可佐证无事月不删摘要 |
| `test_flip_brew_input_must_contain_new_edge_events` | 删壳 | 删 recent_segment 键在；保留 origin/event_kind |
| `test_failed_month_degrades_to_pending_and_rebrews_next_month` | 删壳保结构 | 删 recent_segment 键在；保留 pending/dimension/水位 |
| `test_build_brew_input_projects_prior_event_fields` | 保留 | 字段集合投影 + id 负向闸（结构） |
| `test_brew_persistence_chain_accepts_large_recent_segment` | 整案删除 | 无独立可结构化契约（原字节保真已清退） |
| `test_brew_batch_runs_items_in_parallel_not_serialized` | 删壳保结构 | 删键在；保留并行线程数 + 摘要行写入 |
| `test_duplicate_json_objects_rejected_not_first_object_picked` | 删壳保结构 | 畸形拒收 + 水位不推进 + pending |
| `test_batch_of_five_relations_all_enter_call_seam_concurrently` | 删壳保结构 | 同并行 |
| `merge_founding_segment_*` | 删除维持 | 正文专属证明；不恢复 |

## `tests/test_relation_seed_638.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_reverse_chronological_seed_keeps_latest_event_readable` | 删壳 | 删 recent_context 键在；保留纪年序 + era label |
| `test_new_save_seed_founding_events_enter_founding_segment` | 恢复负向闸 | recent_segment=="" 领域闸 + last_event_id==0；删键在 |

## `tests/test_relation_read_640.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_dto_shape_summary_plus_recent_context_with_backref` | 删壳 | 删冗余键在；保留 FROZEN_DTO_WHITELIST |
| `test_judge_face_reads_edges_invisible_to_role_view` | 删壳 | 删 summary 键在；保留可见性对身份 |
| `test_load_relation_history_before_returns_full_stable_prior_stream` | 保留 | year/period/event_kind 序 + id 排序 |

## `tests/test_relation_store_632.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_relation_edges_survive_restore` | 删壳 | 删 context 键在；保留 structured 字段等值与 origin_round |

## `tests/test_scene_llm_1836.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_scene_chat_one_call_returns_multi_person_script` | 删壳 | 删 answer.strip；保留单次调用与输入身份 |
| `test_cli_selection_uses_scene_turn_as_admission_origin` | 删壳 | 删 readings strip；保留 minister_message_id 与 readings 次数 |

## `tests/test_highlight_judge_544.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_chat_stream_done_before_highlights_and_degrade` | 删壳 | 删 answer.strip；保留事件类型序与空高亮 |
| `test_chat_stream_slow_success_attaches_after_done` | 删壳 | 删 reply strip；保留 highlights 结构 |
| `test_chat_nonstream_folds_judge_within_timeout` | 删壳 | 删 answer.strip |
| `test_chat_nonstream_timeout_returns_reply_without_highlights` | 删壳 | 删 answer.strip |

## `tests/test_audience_restore_505.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_reopen_reconcile_unblocks_and_keeps_question` | 删壳保结构 | 删 question 键在；保留 user/retry chat_turn_id |
| `test_retry_regenerates_reply_without_duplicate_question` | 删壳 | 删 answer.strip；保留消息计数 |
| `test_post_reply_failure_resumes_close_without_regenerating_reply` | 删壳 | 同 |
| `test_failed_retry_rolls_back_side_effects_and_keeps_question` | 删壳 | 同 |
| `test_pure_audience_zero_ledger_turn_survives_reopen` | 保留 | role+chat_turn_id 结构身份 |

## `tests/test_audience_translation_1838.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `edge context 键在` | 删除 | affair_id + origin 前缀已够 |

## `tests/test_cli_backend.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_extract_secret_order_returns_assignee_without_title_prose_lock` | 删壳 | 删 title 键在；保留 assignee |

## `tests/test_draft_admission_resubmit_1769.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `decree_text/purpose 键在` | 删除 | failure_reason/bad_payload/投影结构化字段已够 |

## `tests/test_execution_joint_liability_565.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_execution_note_merge_interface_and_restore` | 删壳 | 删 execution_note 键在；保留 outcome + costs restore |

## `tests/test_month_call_recovery_1846.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_settlement_recovery_projects_month_call_failure` | 改结构 | 删 message 键在；保留 error_pack_path 清空 + call_failure.kind/escape_armed |

## `tests/test_opening_gazette_delete_1356.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_state_payload_t0_previous_summary_empty` | 恢复 | previous_summary=="" 领域空闸（非 LLM 正文） |
| `test_old_save_exact_purge_keeps_real_with_phrase_counterexample` | 保留 | turn0 删除/turn1 行存在是 purge 结构契约 |

## `tests/test_qa_s2_copy_prompts_1356_1402.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `previous_summary 键在` | 删除 | previous_reign_period_label 月份投影已够 |
| `stored turn/year/period` | 保留 | 行身份结构 |

## `tests/test_recommendation_edges_635.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `reason 键在` | 删除 | candidate/office/边 origin+event_kind 已够 |

## `tests/test_six_sciences_seed_608.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_fresh_seed_contains_sourced_six_sciences_censors` | 恢复 | 静态 seed 出处《明史》卷258；非 LLM 正文 |

## `tests/test_structured_decree_contract_1624.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `draft_text.strip` | 删除 | 身份束字段已够 |

## `tests/test_surcharge_causal_chain_650.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `turn_reports/projection is not None` | 保留 | 写后行存在／知识投影存在=落账结构；删正文等值后最短入口 |

## `tests/test_secret_order_isolation_883.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `turn_reports is not None` | 保留 | 同：写后行存在 |

## `web/src/components/situation.test.tsx`

| 成员 | 处置 | 依据 |
|---|---|---|
| `outcomes.trim().length` | 删除 | 非法正文非空换形 |
| `issue-commitment-progress / situation-row not.toBeNull` | 保留 | UI 节点结构契约（替换 textContent 盯文） |

## `web DOM 结构断言族（appDurableWiring/modals/decisionModal/settlement*/mindreading/useSettlementFlow）`

| 成员 | 处置 | 依据 |
|---|---|---|
| `data-audience-turn-id / role class / gazettePanel not.toBeNull` | 保留 | UI 结构契约；判词 unverified 亦称多数已改结构；非 strip/len 正文壳 |


---

## 诊断与变异（diagnosing-bugs）

### 494 — red-capable 环

**正常（修后）**

```bash
export MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1
../Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=line \
  --basetemp=/private/tmp/1897-t1-494n tests/test_featured_dossiers_494.py
```

输出：`3 passed in 0.78s`

**变异（identity=60 泄 internal + minister_dossier 恒 `x`）**

```bash
# /tmp/1897-t1-plugins/mut494.py 在 import 前替换 ming_sim.context 二函数
PYTHONPATH="/tmp/1897-t1-plugins:$PYTHONPATH" \
../Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=line \
  -p mut494 --basetemp=/private/tmp/1897-t1-mut-final \
  tests/test_featured_dossiers_494.py
```

输出摘录：`3 failed`（minister 资产字段入 `x` 失败；`internal not in middle` 失败；voice 入 dossier 失败）。
变异后已无生产残留（仅测插件）。

### 641 — red-capable 环

**正常**：`13 passed in 0.88s`

**变异**：临时注释 `issues.py` 性情分支 `UPDATE characters SET style` 与 runtime 回写：

输出：`5 failed, 8 passed`（写路径／回滚／reload／不写边案红；**领域拒收闸仍绿**）。
已 `cp` 还原 `ming_sim/issues.py`，`diff -q` 与备份一致。

### 636

无独立可结构化契约的大体积字节案整案删除；连续酿制保留 `dimension` + `last_event_id` 水位；键在壳删除。

---

## 聚焦测试

前缀：七变量 `MING_SIM_*_BIN=/usr/bin/false` + `PYTHONDONTWRITEBYTECODE=1`。

### Python（触及面）

```bash
../Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=line \
  --basetemp=/private/tmp/1897-t1-focus-final \
  tests/test_featured_dossiers_494.py \
  tests/test_style_temperament_641.py \
  tests/test_relation_brew_636.py \
  tests/test_relation_seed_638.py \
  tests/test_relation_read_640.py \
  tests/test_relation_store_632.py \
  tests/test_scene_llm_1836.py \
  tests/test_highlight_judge_544.py \
  tests/test_audience_restore_505.py \
  tests/test_audience_translation_1838.py \
  tests/test_cli_backend.py \
  tests/test_draft_admission_resubmit_1769.py \
  tests/test_execution_joint_liability_565.py \
  tests/test_month_call_recovery_1846.py \
  tests/test_opening_gazette_delete_1356.py \
  tests/test_qa_s2_copy_prompts_1356_1402.py \
  tests/test_recommendation_edges_635.py \
  tests/test_six_sciences_seed_608.py \
  tests/test_structured_decree_contract_1624.py \
  tests/test_surcharge_causal_chain_650.py \
  tests/test_secret_order_isolation_883.py
```

输出：`339 passed, 1 warning in 15.26s`（聚焦墙钟约 16s）

### Web

```bash
cd web && npm test -- --run src/components/situation.test.tsx
```

输出：`Test Files 1 passed (1) / Tests 10 passed (10)`，Duration ~697ms

---

## 必要测试成本

| 项 | 成本 |
|---|---|
| 枚举＋逐案读 base | ~1 轮脚本 + 人工读生产消费者 |
| 494/641 变异环 | 各 <1s×多跑 |
| 聚焦 Python 21 文件 | ~16s／339 passed |
| Web situation | ~0.7s／10 passed |
| 全量／真模型 | **未跑**（禁） |

---

## 残留项

- K1／K2：判词已结清，本轮未动生产。
- Web 侧 `data-audience-turn-id`／节点 `not.toBeNull`：判为 UI 结构契约保留；未再造平行分类器。
- `month_call_recovery` 中既有 `"核账期可见原文" in message` 子串锁属 base 既有、非本轮修理新增换形；未扩 scope 清扫。
- 不宣称 T1 已由御史台／大理寺复审结清；本文件仅修内司 apply 回执。

---

## Seal（精确查询）

```text
HEAD=467625a91619c92efaa8ee186d935cd02c9606dd
parent=6c44b0e029aeb841db6bb62345e0b6e810b803f9
branch=ak-roles/issue-1897-k1-k2-f3-fixer-20261005-115628
git status --porcelain=v1 --untracked-files=all：（提交后清洁，见下轮查询）
git diff --check HEAD~1 HEAD：artifacts/1897-t1-apply-report.md EOF blank（本轮已去）
生产 ming_sim/：无改动
未 push／未开 PR／未关票
```
