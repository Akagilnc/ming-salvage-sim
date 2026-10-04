# #1853 修内司回执：提交生命周期归一 + 拒收转换收窄（回执纠偏）

- 票：#1853
- 派单：`01a10901-cf48-78eb-88f5-d4ccd507349f@fixer`
- 判词：`attachments/08-1853-judge-3cbc92cfa.json` 末份（第 9 份 payload）
- 基线 HEAD：`3cbc92cfaa090ecd15ffe7b567fb78f1725f4f44`
- 生产修理提交：`2b4e6e2bd5ef4aa61ac594a1a91bff587887ea7c`
- 本回执纠偏提交 SHA：见文末（本文件随该提交落地）
- 施工分支：`ak-roles/issue-1853-j4r-j9-lifecycle`
- 本回执不表示已合并或家族收尾完成

## 回执纠偏说明

前版回执缺陷已纠正：

1. 枚举命令不再写「概念等价 / 施工时实跑」占位；下文为可复制完整命令与实跑输出。
2. 类一谓词放宽：不要求四标记齐全；凡暂存应用 / 状态提交 / 事务所有者候选均入表。
3. 类二不限 `CovertContractError`：凡 `except` 转为 `PendingActionRefusal` / `_reject` / 业务拒收者均入表，并逐项读 try 体排除内部执行洗白。
4. 行为诊断纠正：前版「4 passed」把装回旧宽 try 的旧病复现当成绿；本版用**同一真实入口结构化契约**装回旧宽 try **报红**，恢复新逻辑 **报绿**。结构观察（owner=1）只作枚举复扫，不作行为证明。

## 未结类别（仅末份）

1. **J4-R**「暂存提交生命周期仍有双实现」— 成立，归并完整性 C1
2. **J9**「输入拒收转换覆盖内部执行，洗白真实故障」— 成立，归并正确性 C1

## 官方旁证（先搜后修）

- [PEP 8 Programming Recommendations](https://peps.python.org/pep-0008/#programming-recommendations)：`try` 只包最小必要代码。
- DRY / 单一权威表示：重复的提交生命周期知识只保留一处。
裁决法源仍为仓库规则与判词；上述仅作方向旁证。

## 环境前缀（七变量；全部测试/诊断共用）

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false
```

---

## 类一：暂存提交生命周期单一权威（J4-R）

### 枚举谓词（放宽）

全仓 `*.py` AST 扫描函数体：含 `pending_actions` 且（含任一 lifecycle 强标记，或 `status` committed/failed，或相关 helper 名）。强标记子集为 `SAVEPOINT` / `ROLLBACK TO` / `RELEASE` / `status='committed'`，**不要求四者齐全**。另扫 ≥2 强标记的他域事务所有者。

### 枚举命令（可复制完整）

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false
cd /Users/akagilnc/WorkSpace/Ming_LLM-1853-w5
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
import ast, os
from pathlib import Path
ROOT = Path('/Users/akagilnc/WorkSpace/Ming_LLM-1853-w5')
MARKERS = (
    'SAVEPOINT','ROLLBACK TO','RELEASE',
    "status='committed'",'status="committed"',
    "status='failed'",'status="failed"',
    'pending_actions','_apply_pending_action','commit_pending_actions',
    '_run_pending_action_commit_lifecycle','_dispose_pending_action_apply_exception',
    '_commit_conversational_draft',
)
LIFE = ('SAVEPOINT','ROLLBACK TO','RELEASE',"status='committed'",'status="committed"')
rows=[]; broad=[]
for path in sorted(ROOT.rglob('*.py')):
    rel=str(path.relative_to(ROOT))
    if any(p in rel.split(os.sep) for p in ('.venv','venv','node_modules','__pycache__','.git')): continue
    try: src=path.read_text(encoding='utf-8'); tree=ast.parse(src, filename=rel)
    except Exception: continue
    lines=src.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)): continue
        start=node.lineno; end=getattr(node,'end_lineno',None) or start
        body='\n'.join(lines[start-1:end])
        hits=[m for m in MARKERS if m in body]
        strong=[m for m in LIFE if m in body]
        if len(strong)>=2:
            broad.append((rel,node.name,f'{start}-{end}',strong))
        if not hits: continue
        names={'_apply_pending_action','commit_pending_actions','_run_pending_action_commit_lifecycle',
               '_dispose_pending_action_apply_exception','_commit_conversational_draft'}
        name_hit=node.name in names or any(n in body for n in names)
        pa_hit='pending_actions' in body
        if not (name_hit or (pa_hit and strong) or (pa_hit and any(x in body for x in ("status='committed'",'status="committed"',"status='failed'",'status="failed"')))):
            continue
        is_owner=node.name=='_run_pending_action_commit_lifecycle'
        owns_inline=len(strong)>=2 and any(x in body for x in ("status='committed'",'status="committed"')) and not is_owner
        calls_lc='_run_pending_action_commit_lifecycle' in body and not is_owner
        role=[]
        if is_owner: role.append('UNIQUE_OWNER')
        if owns_inline: role.append('INLINE_LIFE_CANDIDATE')
        if calls_lc: role.append('CALLER')
        if not role: role.append('RELATED')
        rows.append((rel,f'{start}-{end}',node.name,','.join(role),strong,hits))
print('=== CLASS1 pending-action commit / apply / txn candidates (broad; NOT requiring all 4 markers) ===')
print(f'COUNT={len(rows)}')
for r in rows:
    print(f'{r[0]}:{r[1]} {r[2]} role={r[3]} strong={r[4]} markers={r[5]}')
print('\n=== CLASS1 broad txn owners (>=2 of SAVEPOINT/ROLLBACK TO/RELEASE/committed) ===')
print(f'COUNT={len(broad)}')
for rel,name,span,strong in broad:
    print(f'{rel}:{span} {name} strong={strong}')
inline=[r for r in rows if 'INLINE_LIFE_CANDIDATE' in r[3]]
owners=[r for r in rows if 'UNIQUE_OWNER' in r[3]]
callers=[r for r in rows if 'CALLER' in r[3]]
print('\n=== CLASS1 SUMMARY ===')
print(f'INLINE_LIFE_CANDIDATE={len(inline)} UNIQUE_OWNER={len(owners)} CALLER={len(callers)}')
for r in owners+callers+inline:
    print(f'  {r[0]}:{r[1]} {r[2]} role={r[3]}')
PY
```

### 枚举输出（实跑）

```
=== CLASS1 pending-action commit / apply / txn candidates (broad; NOT requiring all 4 markers) ===
COUNT=71
ming_sim/audience_night.py:1066-1097 _commit_night_approved role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
ming_sim/db.py:983-2752 init_schema role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
ming_sim/db.py:10258-10439 undo_chat_turn role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
ming_sim/db.py:14904-14955 add_dossier_links role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
ming_sim/db.py:17221-17264 stage_pending_action role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
ming_sim/db.py:17595-17626 _dispose_pending_action_apply_exception role=RELATED strong=['ROLLBACK TO'] markers=['ROLLBACK TO', "status='failed'", 'pending_actions', '_dispose_pending_action_apply_exception']
ming_sim/db.py:17628-17686 _run_pending_action_commit_lifecycle role=UNIQUE_OWNER strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE', "status='committed'"] markers=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE', "status='committed'", "status='failed'", 'pending_actions', '_apply_pending_action', '_run_pending_action_commit_lifecycle', '_dispose_pending_action_apply_exception']
ming_sim/db.py:18041-18066 list_failed_secret_order_actions role=RELATED strong=[] markers=["status='failed'", 'pending_actions']
ming_sim/db.py:18122-18255 commit_pending_actions role=CALLER strong=[] markers=["status='failed'", 'pending_actions', 'commit_pending_actions', '_run_pending_action_commit_lifecycle', '_commit_conversational_draft']
ming_sim/db.py:18270-18289 _commit_conversational_draft role=CALLER strong=[] markers=['_run_pending_action_commit_lifecycle', '_commit_conversational_draft']
ming_sim/db.py:18291-18522 _apply_pending_action role=RELATED strong=[] markers=['pending_actions', '_apply_pending_action', 'commit_pending_actions']
ming_sim/db.py:18925-18953 hold_over_pending_actions role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
ming_sim/db.py:19010-19025 discard_pending_directives role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
ming_sim/db.py:19027-19037 discard_failed_secret_order_intents role=RELATED strong=[] markers=["status='failed'", 'pending_actions', 'commit_pending_actions']
ming_sim/declaration_dispatch.py:802-845 _item_savepoint_scope role=RELATED strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE'] markers=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE', 'pending_actions', 'commit_pending_actions']
ming_sim/declaration_dispatch.py:2073-2207 _dispatch_promises role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
ming_sim/decree.py:1126-1236 pre_settle role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
ming_sim/urge_lever.py:77-152 collect_urge_history role=RELATED strong=["status='committed'"] markers=["status='committed'", 'pending_actions']
tests/legacy_staging_helpers.py:52-57 close_night_dossier role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/legacy_staging_helpers.py:97-121 close_office_to_dossier role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_appointment_tenure_607.py:18-34 _promulgate_appointment role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_appointment_tenure_607.py:106-175 test_failed_dossier_reappointment_rolls_back_audit_and_sequence role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_audience_commit_failure_1853.py:220-257 test_closed_secret_order_rush_fails_one_item_and_commits_the_rest role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_audience_night_498.py:639-671 test_close_night_committed_without_dossier_does_not_publish_mingfa role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_audience_translate_1837_reopen.py:401-453 test_rush_commitment_stages_pending_催办 role=RELATED strong=["status='committed'"] markers=["status='committed'", 'pending_actions', 'commit_pending_actions']
tests/test_decree_dossiers_571.py:256-283 test_committing_each_directive_creates_independent_restoreable_dossier role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_decree_dossiers_571.py:285-346 test_pending_directive_only_enters_settlement_after_final_approval role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_decree_dossiers_571.py:348-387 test_secret_pending_action_carries_chat_turn_and_pending_provenance role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_decree_dossiers_571.py:407-440 test_office_action_waits_for_verdict_then_materializes_from_same_payload role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_decree_dossiers_571.py:550-576 test_assignment_promulgation_tracks_executor_until_terminal_state role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_decree_dossiers_571.py:585-651 test_directive_assignee_projects_to_executor_only_for_executable_types role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_decree_dossiers_571.py:912-945 test_appointment_alias_uses_canonical_dossier_identity role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_decree_dossiers_571.py:1887-1917 test_allocation_candidate_edit_preserves_mechanical_payload role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_decree_dossiers_571.py:2094-2115 test_durable_allocation_rejects_non_integer_amount_without_downgrade role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_decree_dossiers_571.py:2117-2138 test_durable_military_order_without_assignee_fails_loudly role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_dossier_links_559.py:101-119 test_confirmed_secret_order_materializes_links_through_pending_commit role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_dossier_links_559.py:122-139 test_unknown_target_in_pending_commit_is_rolled_back_and_durably_audited role=RELATED strong=[] markers=['status="failed"', 'pending_actions', 'commit_pending_actions']
tests/test_dossier_links_559.py:181-192 test_pending_rejection_does_not_follow_reused_rolled_back_source_id role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_execution_pressure_654.py:615-663 test_path1_conversational_draft_bad_roster_marks_failed role=RELATED strong=[] markers=['pending_actions', '_commit_conversational_draft']
tests/test_execution_pressure_654.py:768-876 test_revoke_decree_523_producer_durable_oracle_chain role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_execution_pressure_654.py:1009-1071 test_grant_region_to_character_amendment_clears_single_locality role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_execution_pressure_654.py:1074-1129 test_authorization_region_to_character_amendment_clears_single_locality role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_executor_routing_721.py:160-192 test_new_appointee_identity_exists_before_promulgation_and_leads_dossier role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_executor_routing_721.py:195-207 test_unknown_appointee_normalizes_unrecognized_faction role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_executor_routing_721.py:210-247 test_real_assignment_stage_lead_comes_from_extract_not_summoned_minister role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_executor_routing_721.py:250-260 test_real_punishment_stage_preserves_category role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_family_tail_615.py:38-54 _stage_break_rank_acting role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_gazette_author_1862.py:88-461 test_author_archives_own_title_and_same_run_advances role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_pay_order_override_653.py:520-569 test_real_revoke_restores_override_same_month_with_active_commitment role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_recommendation_batch_snapshot_1583.py:59-117 test_same_batch_consecutive_appointments_keep_prebatch_recommendation_snapshot role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_recommendation_batch_snapshot_1583.py:120-160 test_stale_recommendation_snapshot_still_rejected_outside_mutating_batch role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_recommendation_edges_635.py:35-40 _commit_and_promulgate role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_recommendations.py:220-264 test_recommendation_appointment_preserves_kind_and_restores_both_types role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_rescript_choices_563.py:88-103 test_declared_staging_uses_typed_mode_not_minister_text role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_rescript_choices_563.py:106-131 test_presence_aware_mode_preserves_draft_until_explicit_override role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_secret_order_isolation_883.py:782-851 test_976_stage_confirm_pin_provenance_not_max_held_user role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_secret_order_isolation_883.py:871-932 test_976_non_create_stage_commit_update_withholds_oral_pin role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_secret_order_isolation_883.py:935-982 test_976_non_create_stage_commit_rush_withholds_oral_pin role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_secret_order_isolation_883.py:985-1034 test_976_non_create_stage_commit_progress_and_review_withhold_oral_pin role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_secret_order_isolation_883.py:1037-1100 test_976_non_create_pure_public_not_auto_pinned_as_secret_origin role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_secret_order_isolation_883.py:1140-1177 test_976_pending_secret_pin_survives_partial_commit_same_minister role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_secret_order_isolation_883.py:1180-1212 test_976_retryable_failed_secret_pin_stays_withheld_during_other_commit role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_secret_order_payoff_1504.py:781-806 test_1376_candidate_confirm_freezes_explicit_typed_contract role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_staged_assignment_identity_1890.py:477-523 test_undo_deletes_only_this_turns_committed_draft_directive role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_staged_assignment_identity_1890.py:552-601 _promulgate_assignment role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_state_reload.py:148-188 test_rollback_purges_content_character_ghost role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_urge_lever_624.py:549-617 test_commitment_rush_via_pending_actions_gate role=RELATED strong=["status='committed'"] markers=["status='committed'", 'pending_actions', 'commit_pending_actions']
tests/test_web_audience_night_498.py:557-637 test_asgi_inflight_reply_lands_then_issue_closes_and_advances role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_web_audience_night_498.py:724-792 test_asgi_hanging_chat_issue_waits_for_worker_terminal role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_web_audience_night_498.py:588-621 scenario role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']
tests/test_web_audience_night_498.py:747-783 scenario role=RELATED strong=[] markers=['pending_actions', 'commit_pending_actions']

=== CLASS1 broad txn owners (>=2 of SAVEPOINT/ROLLBACK TO/RELEASE/committed) ===
COUNT=12
ming_sim/audience_night.py:893-969 open_night strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE']
ming_sim/db.py:17628-17686 _run_pending_action_commit_lifecycle strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE', "status='committed'"]
ming_sim/db.py:19467-19551 ensure_dossiers_for_draft_directives strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE']
ming_sim/db.py:22151-22224 close_secret_order strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE']
ming_sim/declaration_dispatch.py:802-845 _item_savepoint_scope strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE']
ming_sim/issues.py:3672-4149 _strategic_event_result_preflight_error strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE']
ming_sim/issues.py:7516-7592 _apply_extracted_army_delta strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE']
ming_sim/issues.py:7595-9164 _apply_score_extraction_body strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE']
ming_sim/issues.py:8037-8069 _apply_person_changes_itemwise strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE']
ming_sim/issues.py:8092-8127 _apply_economy_moves_list strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE']
ming_sim/session.py:256-360 register_unlisted_person_record strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE']
tests/test_audience_travel_gating_670.py:1110-1157 test_waiting_active_departure_respects_strategic_preflight_savepoint strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE']

=== CLASS1 SUMMARY ===
INLINE_LIFE_CANDIDATE=0 UNIQUE_OWNER=1 CALLER=2
  ming_sim/db.py:17628-17686 _run_pending_action_commit_lifecycle role=UNIQUE_OWNER
  ming_sim/db.py:18122-18255 commit_pending_actions role=CALLER
  ming_sim/db.py:18270-18289 _commit_conversational_draft role=CALLER
```

### 复扫摘要（实跑）

```
INLINE_LIFE_CANDIDATE 0
UNIQUE_OWNER 1
  ming_sim/db.py:17628-17686 _run_pending_action_commit_lifecycle strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE', "status='committed'"]
CALLER 2
  ming_sim/db.py:18122-18255 commit_pending_actions strong=[]
  ming_sim/db.py:18270-18289 _commit_conversational_draft strong=[]
RELATED_PROD 15
  ming_sim/audience_night.py:1066-1097 _commit_night_approved strong=[]
  ming_sim/db.py:983-2752 init_schema strong=[]
  ming_sim/db.py:10258-10439 undo_chat_turn strong=[]
  ming_sim/db.py:14904-14955 add_dossier_links strong=[]
  ming_sim/db.py:17221-17264 stage_pending_action strong=[]
  ming_sim/db.py:17595-17626 _dispose_pending_action_apply_exception strong=['ROLLBACK TO']
  ming_sim/db.py:18041-18066 list_failed_secret_order_actions strong=[]
  ming_sim/db.py:18291-18522 _apply_pending_action strong=[]
  ming_sim/db.py:18925-18953 hold_over_pending_actions strong=[]
  ming_sim/db.py:19010-19025 discard_pending_directives strong=[]
  ming_sim/db.py:19027-19037 discard_failed_secret_order_intents strong=[]
  ming_sim/declaration_dispatch.py:802-845 _item_savepoint_scope strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE']
  ming_sim/declaration_dispatch.py:2073-2207 _dispatch_promises strong=[]
  ming_sim/decree.py:1126-1236 pre_settle strong=[]
  ming_sim/urge_lever.py:77-152 collect_urge_history strong=["status='committed'"]
NOTE: structure observation only; behavior proof is J9 red/green diag
```

结论：`INLINE_LIFE_CANDIDATE=0`；`UNIQUE_OWNER=1`（`_run_pending_action_commit_lifecycle`）；`CALLER=2`。此为结构观察，行为证明见下文 J9 诊断。

### 成员表（覆盖全部候选）

## Class1 member dispositions (post-rescan)

| 成员 | 处理 | 理由 |
|------|------|------|
| `ming_sim/audience_night.py:1066-1097` `_commit_night_approved` | 保留 | 读/写 pending 状态或调用 commit，不拥有共同生命周期 |
| `ming_sim/db.py:983-2752` `init_schema` | 保留 | 读/写 pending 状态或调用 commit，不拥有共同生命周期 |
| `ming_sim/db.py:10258-10439` `undo_chat_turn` | 保留 | 读/写 pending 状态或调用 commit，不拥有共同生命周期 |
| `ming_sim/db.py:14904-14955` `add_dossier_links` | 保留 | 读/写 pending 状态或调用 commit，不拥有共同生命周期 |
| `ming_sim/db.py:17221-17264` `stage_pending_action` | 保留 | 读/写 pending 状态或调用 commit，不拥有共同生命周期 |
| `ming_sim/db.py:17595-17626` `_dispose_pending_action_apply_exception` | 保留 | 共同异常分流，不是第二套生命周期 |
| `ming_sim/db.py:17628-17686` `_run_pending_action_commit_lifecycle` | 唯一实现（保留） | J4-R 共同提交生命周期唯一权威 |
| `ming_sim/db.py:18041-18066` `list_failed_secret_order_actions` | 保留 | 读/写 pending 状态或调用 commit，不拥有共同生命周期 |
| `ming_sim/db.py:18122-18255` `commit_pending_actions` | 保留（调用方） | 仅委托唯一生命周期；保留各自输入/内存差异 |
| `ming_sim/db.py:18270-18289` `_commit_conversational_draft` | 保留（调用方） | 仅委托唯一生命周期；保留各自输入/内存差异 |
| `ming_sim/db.py:18291-18522` `_apply_pending_action` | 保留 | 应用实现，生命周期由 owner 包住 |
| `ming_sim/db.py:18925-18953` `hold_over_pending_actions` | 保留 | 读/写 pending 状态或调用 commit，不拥有共同生命周期 |
| `ming_sim/db.py:19010-19025` `discard_pending_directives` | 保留 | 读/写 pending 状态或调用 commit，不拥有共同生命周期 |
| `ming_sim/db.py:19027-19037` `discard_failed_secret_order_intents` | 保留 | 读/写 pending 状态或调用 commit，不拥有共同生命周期 |
| `ming_sim/declaration_dispatch.py:802-845` `_item_savepoint_scope` | 保留 | 声明条目 savepoint 域，非 pending commit 生命周期 |
| `ming_sim/declaration_dispatch.py:2073-2207` `_dispatch_promises` | 保留 | 读/写 pending 状态或调用 commit，不拥有共同生命周期 |
| `ming_sim/decree.py:1126-1236` `pre_settle` | 保留 | 读/写 pending 状态或调用 commit，不拥有共同生命周期 |
| `ming_sim/urge_lever.py:77-152` `collect_urge_history` | 保留 | 读/写 pending 状态或调用 commit，不拥有共同生命周期 |
| `tests/legacy_staging_helpers.py:52-57` `close_night_dossier` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/legacy_staging_helpers.py:97-121` `close_office_to_dossier` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_appointment_tenure_607.py:18-34` `_promulgate_appointment` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_appointment_tenure_607.py:106-175` `test_failed_dossier_reappointment_rolls_back_audit_and_sequence` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_audience_commit_failure_1853.py:220-257` `test_closed_secret_order_rush_fails_one_item_and_commits_the_rest` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_audience_night_498.py:639-671` `test_close_night_committed_without_dossier_does_not_publish_mingfa` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_audience_translate_1837_reopen.py:401-453` `test_rush_commitment_stages_pending_催办` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_decree_dossiers_571.py:256-283` `test_committing_each_directive_creates_independent_restoreable_dossier` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_decree_dossiers_571.py:285-346` `test_pending_directive_only_enters_settlement_after_final_approval` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_decree_dossiers_571.py:348-387` `test_secret_pending_action_carries_chat_turn_and_pending_provenance` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_decree_dossiers_571.py:407-440` `test_office_action_waits_for_verdict_then_materializes_from_same_payload` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_decree_dossiers_571.py:550-576` `test_assignment_promulgation_tracks_executor_until_terminal_state` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_decree_dossiers_571.py:585-651` `test_directive_assignee_projects_to_executor_only_for_executable_types` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_decree_dossiers_571.py:912-945` `test_appointment_alias_uses_canonical_dossier_identity` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_decree_dossiers_571.py:1887-1917` `test_allocation_candidate_edit_preserves_mechanical_payload` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_decree_dossiers_571.py:2094-2115` `test_durable_allocation_rejects_non_integer_amount_without_downgrade` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_decree_dossiers_571.py:2117-2138` `test_durable_military_order_without_assignee_fails_loudly` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_dossier_links_559.py:101-119` `test_confirmed_secret_order_materializes_links_through_pending_commit` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_dossier_links_559.py:122-139` `test_unknown_target_in_pending_commit_is_rolled_back_and_durably_audited` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_dossier_links_559.py:181-192` `test_pending_rejection_does_not_follow_reused_rolled_back_source_id` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_execution_pressure_654.py:615-663` `test_path1_conversational_draft_bad_roster_marks_failed` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_execution_pressure_654.py:768-876` `test_revoke_decree_523_producer_durable_oracle_chain` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_execution_pressure_654.py:1009-1071` `test_grant_region_to_character_amendment_clears_single_locality` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_execution_pressure_654.py:1074-1129` `test_authorization_region_to_character_amendment_clears_single_locality` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_executor_routing_721.py:160-192` `test_new_appointee_identity_exists_before_promulgation_and_leads_dossier` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_executor_routing_721.py:195-207` `test_unknown_appointee_normalizes_unrecognized_faction` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_executor_routing_721.py:210-247` `test_real_assignment_stage_lead_comes_from_extract_not_summoned_minister` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_executor_routing_721.py:250-260` `test_real_punishment_stage_preserves_category` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_family_tail_615.py:38-54` `_stage_break_rank_acting` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_gazette_author_1862.py:88-461` `test_author_archives_own_title_and_same_run_advances` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_pay_order_override_653.py:520-569` `test_real_revoke_restores_override_same_month_with_active_commitment` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_recommendation_batch_snapshot_1583.py:59-117` `test_same_batch_consecutive_appointments_keep_prebatch_recommendation_snapshot` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_recommendation_batch_snapshot_1583.py:120-160` `test_stale_recommendation_snapshot_still_rejected_outside_mutating_batch` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_recommendation_edges_635.py:35-40` `_commit_and_promulgate` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_recommendations.py:220-264` `test_recommendation_appointment_preserves_kind_and_restores_both_types` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_rescript_choices_563.py:88-103` `test_declared_staging_uses_typed_mode_not_minister_text` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_rescript_choices_563.py:106-131` `test_presence_aware_mode_preserves_draft_until_explicit_override` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_secret_order_isolation_883.py:782-851` `test_976_stage_confirm_pin_provenance_not_max_held_user` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_secret_order_isolation_883.py:871-932` `test_976_non_create_stage_commit_update_withholds_oral_pin` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_secret_order_isolation_883.py:935-982` `test_976_non_create_stage_commit_rush_withholds_oral_pin` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_secret_order_isolation_883.py:985-1034` `test_976_non_create_stage_commit_progress_and_review_withhold_oral_pin` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_secret_order_isolation_883.py:1037-1100` `test_976_non_create_pure_public_not_auto_pinned_as_secret_origin` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_secret_order_isolation_883.py:1140-1177` `test_976_pending_secret_pin_survives_partial_commit_same_minister` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_secret_order_isolation_883.py:1180-1212` `test_976_retryable_failed_secret_pin_stays_withheld_during_other_commit` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_secret_order_payoff_1504.py:781-806` `test_1376_candidate_confirm_freezes_explicit_typed_contract` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_staged_assignment_identity_1890.py:477-523` `test_undo_deletes_only_this_turns_committed_draft_directive` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_staged_assignment_identity_1890.py:552-601` `_promulgate_assignment` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_state_reload.py:148-188` `test_rollback_purges_content_character_ghost` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_urge_lever_624.py:549-617` `test_commitment_rush_via_pending_actions_gate` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_web_audience_night_498.py:557-637` `test_asgi_inflight_reply_lands_then_issue_closes_and_advances` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_web_audience_night_498.py:724-792` `test_asgi_hanging_chat_issue_waits_for_worker_terminal` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_web_audience_night_498.py:588-621` `scenario` | 保留（测试调用方） | 非生产生命周期所有者 |
| `tests/test_web_audience_night_498.py:747-783` `scenario` | 保留（测试调用方） | 非生产生命周期所有者 |

## Class1 broad txn owners (>=2 markers) outside pending commit

| 成员 | 处理 | 理由 |
|------|------|------|
| `ming_sim/audience_night.py:893-969` `open_night` | 保留 | 他域 savepoint/事务；strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE']；非 pending commit 双实现 |
| `ming_sim/db.py:17628-17686` `_run_pending_action_commit_lifecycle` | 唯一 pending-commit owner | strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE', "status='committed'"] |
| `ming_sim/db.py:19467-19551` `ensure_dossiers_for_draft_directives` | 保留 | 他域 savepoint/事务；strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE']；非 pending commit 双实现 |
| `ming_sim/db.py:22151-22224` `close_secret_order` | 保留 | 他域 savepoint/事务；strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE']；非 pending commit 双实现 |
| `ming_sim/declaration_dispatch.py:802-845` `_item_savepoint_scope` | 保留 | 他域 savepoint/事务；strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE']；非 pending commit 双实现 |
| `ming_sim/issues.py:3672-4149` `_strategic_event_result_preflight_error` | 保留 | 他域 savepoint/事务；strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE']；非 pending commit 双实现 |
| `ming_sim/issues.py:7516-7592` `_apply_extracted_army_delta` | 保留 | 他域 savepoint/事务；strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE']；非 pending commit 双实现 |
| `ming_sim/issues.py:7595-9164` `_apply_score_extraction_body` | 保留 | 他域 savepoint/事务；strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE']；非 pending commit 双实现 |
| `ming_sim/issues.py:8037-8069` `_apply_person_changes_itemwise` | 保留 | 他域 savepoint/事务；strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE']；非 pending commit 双实现 |
| `ming_sim/issues.py:8092-8127` `_apply_economy_moves_list` | 保留 | 他域 savepoint/事务；strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE']；非 pending commit 双实现 |
| `ming_sim/session.py:256-360` `register_unlisted_person_record` | 保留 | 他域 savepoint/事务；strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE']；非 pending commit 双实现 |
| `tests/test_audience_travel_gating_670.py:1110-1157` `test_waiting_active_departure_respects_strategic_preflight_savepoint` | 保留 | 他域 savepoint/事务；strong=['SAVEPOINT', 'ROLLBACK TO', 'RELEASE']；非 pending commit 双实现 |

### 根因与改动

此前 J4 只归一异常分流，两条入口仍复制整段提交生命周期。抽出 `_run_pending_action_commit_lifecycle`，调用方只保留输入/内存差异。放宽复扫无第二套 pending-commit 内联生命周期。生产改动在 `2b4e6e2bd`；本纠偏未再改生产。

---

## 类二：业务输入拒收与内部故障接缝分离（J9）

### 枚举谓词（不限 CovertContractError）

生产代码 AST：`except` handler 若转为 `PendingActionRefusal` / `_reject` / 业务拒收即入候选；读 try 体标 `ONLY_BUILD` / `CONTROL_EXC` / `WRAPS_INTERNAL` / `INPUT_OR_ITEM`。另 `rg` 全仓 `CovertContractError` 捕获与 `PendingActionRefusal` 抛点。

### 枚举命令（可复制完整）

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false
cd /Users/akagilnc/WorkSpace/Ming_LLM-1853-w5
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'
import ast, os
from pathlib import Path
from collections import Counter
ROOT = Path('/Users/akagilnc/WorkSpace/Ming_LLM-1853-w5')
REFUSAL_RAISE = {'PendingActionRefusal', 'OfficeAppointmentRejection'}
REJECT_CALLS = {'_reject', 'record_rejection', '_record_typed_business_refusal'}

def name_of(node):
    if isinstance(node, ast.Name): return node.id
    if isinstance(node, ast.Attribute): return node.attr
    return None
def call_name(node):
    if not isinstance(node, ast.Call): return None
    f=node.func
    if isinstance(f, ast.Name): return f.id
    if isinstance(f, ast.Attribute): return f.attr
    return None
def except_types(handler):
    t=handler.type
    if t is None: return ['(bare)']
    elems=t.elts if isinstance(t, ast.Tuple) else [t]
    return [name_of(e) or ast.dump(e) for e in elems]

rows=[]
for path in sorted(ROOT.rglob('*.py')):
    rel=str(path.relative_to(ROOT))
    if any(p in rel.split(os.sep) for p in ('.venv','venv','node_modules','__pycache__','.git')): continue
    if rel.startswith('tests/'): continue
    try: src=path.read_text(encoding='utf-8'); tree=ast.parse(src, filename=rel)
    except Exception: continue
    lines=src.splitlines()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try): continue
        enc_name='?'; enc_line=0
        for p in ast.walk(tree):
            if isinstance(p,(ast.FunctionDef,ast.AsyncFunctionDef)):
                ps,pe=p.lineno, getattr(p,'end_lineno',p.lineno)
                if ps<=node.lineno<=pe and ps>=enc_line:
                    enc_name=p.name; enc_line=ps
        for h in node.handlers:
            h_start=h.lineno; h_end=getattr(h,'end_lineno',h.lineno)
            htext='\n'.join(lines[h_start-1:h_end])
            raises=[]; calls=[]; soft=[]
            for n in ast.walk(h):
                if isinstance(n, ast.Raise) and n.exc is not None:
                    if isinstance(n.exc, ast.Call):
                        cn=call_name(n.exc)
                        if cn in REFUSAL_RAISE: raises.append(cn)
                if isinstance(n, ast.Call):
                    cn=call_name(n)
                    if cn in REJECT_CALLS or cn in REFUSAL_RAISE: calls.append(cn)
            if 'contract_error' in htext: soft.append('contract_error')
            if 'business_refusal' in htext or 'covert_contract' in htext: soft.append('category_refusal')
            if '_reject(' in htext: soft.append('_reject')
            if not (raises or any(c in REJECT_CALLS or c in REFUSAL_RAISE for c in calls) or soft):
                continue
            body_end=h.lineno-1
            body='\n'.join(lines[node.lineno-1:body_end])
            called=[]
            for stmt in node.body:
                for n in ast.walk(stmt):
                    if isinstance(n, ast.Call):
                        cn=call_name(n)
                        if cn: called.append(cn)
            only_build=('build_covert_task_contract' in called and not any(
                c in {'create_secret_order','merge_investigation_confirmation','merge_investigation',
                      'create_investigation','update_secret_order'} for c in called))
            internal=any(c in {
                'create_secret_order','merge_investigation_confirmation','merge_investigation',
                'create_investigation','update_secret_order','_apply_pending_action',
                'apply_score_extraction','commit_pending_actions','apply_person_changes_only',
                'register_unlisted_person_record','record_relation_edge_event',
            } or (c.startswith('create_') or c.startswith('merge_') or c.startswith('apply_'))
                and c not in {'build_covert_task_contract'} for c in called)
            control_exc = '_ItemAtomicReject' in except_types(h)
            wraps_internal = internal and not only_build and not control_exc
            flag='WRAPS_INTERNAL' if wraps_internal else ('ONLY_BUILD' if only_build else ('CONTROL_EXC' if control_exc and internal else 'INPUT_OR_ITEM'))
            rows.append({
                'file':rel,'func':enc_name,
                'try':f'{node.lineno}-{getattr(node,"end_lineno",node.lineno)}',
                'body':f'{node.lineno}-{body_end}',
                'except':except_types(h),'raises':raises,'soft':soft,
                'flag':flag,'try_calls':called[:16],
                'preview':[ln for ln in body.strip().splitlines()[:6]],
            })
print('=== CLASS2 except→PendingActionRefusal/_reject/business-refusal (prod; not limited to CovertContractError) ===')
print(f'COUNT={len(rows)}')
for r in rows:
    print(f"{r['file']}::{r['func']} try={r['try']} body={r['body']} except={r['except']} "
          f"raises={r['raises']} soft={r['soft']} flag={r['flag']} try_calls={r['try_calls']}")
    for ln in r['preview']:
        print(f'    | {ln}')
    print()
print('=== CLASS2 SUMMARY by flag ===')
print(dict(Counter(r['flag'] for r in rows)))
print('WRAPS_INTERNAL members:')
for r in rows:
    if r['flag']=='WRAPS_INTERNAL':
        print(f"  {r['file']}::{r['func']} except={r['except']} try_calls={r['try_calls']}")
print('CovertContractError conversion members:')
for r in rows:
    if 'CovertContractError' in r['except']:
        print(f"  {r['file']}::{r['func']} flag={r['flag']} except={r['except']} raises={r['raises']} soft={r['soft']}")
PY
rg -n "except .*CovertContractError" -g'*.py' ming_sim
rg -n "raise PendingActionRefusal" -g'*.py' ming_sim
```

### 枚举输出（实跑）

```
=== CLASS2 except→PendingActionRefusal/_reject/business-refusal (prod; not limited to CovertContractError) ===
COUNT=42
ming_sim/cli_backend.py::_extract_secret_order try=4229-4253 body=4229-4248 except=['CovertContractError'] raises=[] soft=['contract_error'] flag=ONLY_BUILD try_calls=['build_covert_task_contract', 'get', 'get', 'get', 'get', 'get', 'get', 'get', 'get', 'get', 'get', 'get', 'get', 'get']
    | try:
    |         covert_task = build_covert_task_contract(
    |             kind=kind,
    |             axes=axes,
    |             direction=direction,
    |             delivery_unit=unit,

ming_sim/db.py::record_monthly_grant_reconciliations try=12445-12451 body=12445-12448 except=['TypeError', 'ValueError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['strict_int', 'get', 'ValueError']
    | try:
    |                 dossier_id = strict_int(item.get("dossier_id", 0))
    |                 if dossier_id <= 0:
    |                     raise ValueError("not positive")

ming_sim/db.py::record_monthly_grant_reconciliations try=12481-12485 body=12481-12482 except=['TypeError', 'ValueError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['strict_int']
    | try:
    |                 amount = strict_int(raw_amount)

ming_sim/db.py::_apply_pending_action try=18334-18341 body=18334-18335 except=['CovertContractError'] raises=['PendingActionRefusal'] soft=['category_refusal'] flag=ONLY_BUILD try_calls=['build_covert_task_contract']
    | try:
    |                     frozen_task = build_covert_task_contract(covert_task=raw_task)

ming_sim/declaration_dispatch.py::_attach_commission_affair try=1073-1080 body=1073-1074 except=['KeyError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['peek_declared_id']
    | try:
    |         db.affairs.peek_declared_id(raw_affair, allowed=ATTACH_BIRTH)

ming_sim/declaration_dispatch.py::_attach_commission_affair try=1073-1080 body=1073-1077 except=['ValueError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['peek_declared_id']
    | try:
    |         db.affairs.peek_declared_id(raw_affair, allowed=ATTACH_BIRTH)
    |     except KeyError as exc:
    |         _reject(rejected, item, str(exc), "hallucinated_id", source)
    |         return False

ming_sim/declaration_dispatch.py::_dispatch_commissions try=1458-1462 body=1458-1459 except=['ValueError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['imperial_push_target_dossier_id']
    | try:
    |             push_id = imperial_push_target_dossier_id(item)

ming_sim/declaration_dispatch.py::_dispatch_commissions try=1471-1502 body=1471-1496 except=['KeyError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['_commission_grant_payload', '_declared_prose', '_reject', 'int', 'len']
    | try:
    |             if grant_raw:
    |                 # 拟旨 + 拨帑（±任免）→ 一份 directive 载荷。
    |                 payload = _commission_grant_payload(
    |                     db, text=text, grant=grant_raw,  # type: ignore[arg-type]
    |                 )

ming_sim/declaration_dispatch.py::_dispatch_commissions try=1471-1502 body=1471-1499 except=['DecreeMaterializationValidationError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['_commission_grant_payload', '_declared_prose', '_reject', 'int', 'len']
    | try:
    |             if grant_raw:
    |                 # 拟旨 + 拨帑（±任免）→ 一份 directive 载荷。
    |                 payload = _commission_grant_payload(
    |                     db, text=text, grant=grant_raw,  # type: ignore[arg-type]
    |                 )

ming_sim/declaration_dispatch.py::_dispatch_commissions try=1503-1507 body=1503-1504 except=['TypeError', 'ValueError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['declaration_from_payload']
    | try:
    |             raw_affair = declaration_from_payload(item, allowed=ATTACH_BIRTH)

ming_sim/declaration_dispatch.py::_dispatch_inquiries try=1883-1887 body=1883-1884 except=['KeyError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['_assert_characters_exist']
    | try:
    |             _assert_characters_exist(db, [attendant])

ming_sim/declaration_dispatch.py::_dispatch_travel_tones try=2032-2036 body=2032-2033 except=['ValueError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['normalize_travel_tone', 'get', 'get']
    | try:
    |             tone = normalize_travel_tone(item.get("tone") or item.get("行程语气"))

ming_sim/declaration_dispatch.py::_dispatch_travel_tones try=2037-2066 body=2037-2041 except=['KeyError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['update_summon_travel_tone', 'int']
    | try:
    |             entry_id = update_summon_travel_tone(
    |                 db, night_id=int(night_id), person_name=person, travel_tone=tone,
    |                 origin_chat_turn_id=chat_turn_id,
    |             )

ming_sim/declaration_dispatch.py::_dispatch_travel_tones try=2037-2066 body=2037-2063 except=['ValueError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['update_summon_travel_tone', 'int']
    | try:
    |             entry_id = update_summon_travel_tone(
    |                 db, night_id=int(night_id), person_name=person, travel_tone=tone,
    |                 origin_chat_turn_id=chat_turn_id,
    |             )
    |         except KeyError:

ming_sim/declaration_dispatch.py::_dispatch_textual_facts try=2308-2315 body=2308-2309 except=['KeyError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['_assert_textual_fact_subject_exists']
    | try:
    |             _assert_textual_fact_subject_exists(db, subject_kind, subject_id)

ming_sim/declaration_dispatch.py::_dispatch_textual_facts try=2308-2315 body=2308-2312 except=['ValueError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['_assert_textual_fact_subject_exists']
    | try:
    |             _assert_textual_fact_subject_exists(db, subject_kind, subject_id)
    |         except KeyError as exc:
    |             _reject(rejected, item, str(exc), "hallucinated_id", source)
    |             continue

ming_sim/declaration_dispatch.py::_dispatch_textual_facts try=2320-2328 body=2320-2325 except=['ValueError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['append', 'get']
    | try:
    |             fact = db.textual_facts.append(
    |                 subject_kind=subject_kind, subject_id=subject_id,
    |                 body=item.get("body"), year=state.year, period=state.period,
    |                 turn=state.turn, origin_ref=origin_ref,
    |             )

ming_sim/declaration_dispatch.py::_dispatch_public_sayings try=2375-2379 body=2375-2376 except=['KeyError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['_assert_characters_exist']
    | try:
    |             _assert_characters_exist(db, involved)

ming_sim/declaration_dispatch.py::_dispatch_public_sayings try=2392-2401 body=2392-2398 except=['ValueError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['record_public_saying', 'get']
    | try:
    |             saying_id = record_public_saying(
    |                 db, state, item.get("body"),
    |                 involved_characters=involved, affair_ref=affair_ref,
    |                 excluded_names=excluded_names,
    |                 excluded_targets={"offices": excluded_offices} if excluded_offices else None,

ming_sim/declaration_dispatch.py::_dispatch_on_scene_facts try=2439-2462 body=2439-2459 except=['_ItemAtomicReject'] raises=[] soft=['_reject'] flag=CONTROL_EXC try_calls=['_item_savepoint_scope', 'apply_person_changes_only', 'list', 'get', '_ItemAtomicReject', '_ItemAtomicReject', 'strip', 'get', 'str', 'str', '_attach_character_affair_pointer', 'int', 'id', 'str', '_ItemAtomicReject', 'get']
    | try:
    |             with _item_savepoint_scope(db, f"on_scene_fact_{int(state.turn)}_{id(item)}"):
    |                 outcome = apply_person_changes_only(
    |                     db, state, [item], content=db.content, origin_ref=origin_ref,
    |                 )
    |                 results = list(outcome.get("applied_person_changes") or ())

ming_sim/declaration_dispatch.py::_dispatch_presence try=2530-2534 body=2530-2531 except=['KeyError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['_assert_characters_exist']
    | try:
    |             _assert_characters_exist(db, [name])

ming_sim/declaration_dispatch.py::_dispatch_presence try=2539-2550 body=2539-2547 except=['AudienceNightError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['append_ledger_entry', 'int']
    | try:
    |             entry_id = append_ledger_entry(
    |                 db, int(night_id),
    |                 person_names=[name], audibility=AUDIBILITY_PUBLIC,
    |                 body=body, tags=[effect], presence_effect=effect,
    |                 check_dead=(effect == PRESENCE_ENTER), origin_ref=origin_ref,

ming_sim/declaration_dispatch.py::_dispatch_scene_facts try=2608-2620 body=2608-2617 except=['AudienceNightError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['append_ledger_entry', 'int', 'list', 'str', 'startswith']
    | try:
    |             entry_id = append_ledger_entry(
    |                 db, int(night_id),
    |                 person_names=list(person_names), audibility=str(audibility),
    |                 body=body, tags=[tag for tag in tags if not tag.startswith("scroll_role:")]
    |                 + ([f"scroll_role:{scroll_role}"] if scroll_role else []),

ming_sim/declaration_dispatch.py::_dispatch_edge_events try=2664-2668 body=2664-2665 except=['ValueError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['validate_edge_kind', 'get']
    | try:
    |             event_kind = validate_edge_kind(item.get("event_kind"))

ming_sim/declaration_dispatch.py::_dispatch_edge_events try=2669-2673 body=2669-2670 except=['KeyError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['_assert_characters_exist']
    | try:
    |             _assert_characters_exist(db, [source_name, target_name])

ming_sim/declaration_dispatch.py::_dispatch_edge_events try=2678-2696 body=2678-2693 except=['_ItemAtomicReject'] raises=[] soft=['_reject'] flag=CONTROL_EXC try_calls=['_item_savepoint_scope', 'record_relation_edge_event', '_ItemAtomicReject', 'attach_pointer', 'int', 'id', 'int', 'int', 'int', 'str', '_ItemAtomicReject', 'isinstance', 'str']
    | try:
    |             with _item_savepoint_scope(db, f"edge_event_{int(state.turn)}_{id(item)}"):
    |                 try:
    |                     event_id = db.record_relation_edge_event(
    |                         source=source_name, target=target_name, event_kind=event_kind,
    |                         context=context, origin=origin,

ming_sim/declaration_dispatch.py::_dispatch_registrations try=2793-2816 body=2793-2810 except=['_ItemAtomicReject'] raises=[] soft=['_reject'] flag=CONTROL_EXC try_calls=['_item_savepoint_scope', 'register_unlisted_person_record', '_ItemAtomicReject', '_attach_character_affair_pointer', 'str', 'list', 'str', 'str', 'int', 'id', 'get', 'get', 'get']
    | try:
    |             with _item_savepoint_scope(db, f"registration_{int(state.turn)}_{id(item)}"):
    |                 character = register_unlisted_person_record(
    |                     db, state, db.content,
    |                     name=name, office=office, office_type=office_type,
    |                     faction=str(item.get("faction") or ""),

ming_sim/declaration_dispatch.py::_dispatch_registrations try=2793-2816 body=2793-2813 except=['OfficeAppointmentRejection'] raises=[] soft=['_reject'] flag=WRAPS_INTERNAL try_calls=['_item_savepoint_scope', 'register_unlisted_person_record', '_ItemAtomicReject', '_attach_character_affair_pointer', 'str', 'list', 'str', 'str', 'int', 'id', 'get', 'get', 'get']
    | try:
    |             with _item_savepoint_scope(db, f"registration_{int(state.turn)}_{id(item)}"):
    |                 character = register_unlisted_person_record(
    |                     db, state, db.content,
    |                     name=name, office=office, office_type=office_type,
    |                     faction=str(item.get("faction") or ""),

ming_sim/declaration_dispatch.py::_dispatch_commissions try=1102-1112 body=1102-1108 except=['KeyError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['append', '_stage_prohibit_covert_levy']
    | try:
    |                 applied.append(
    |                     _stage_prohibit_covert_levy(
    |                         db, state, item, minister_name=minister_name,
    |                         source_chat_turn_id=source_chat_turn_id,
    |                     )

ming_sim/declaration_dispatch.py::_dispatch_commissions try=1102-1112 body=1102-1110 except=['TypeError', 'ValueError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['append', '_stage_prohibit_covert_levy']
    | try:
    |                 applied.append(
    |                     _stage_prohibit_covert_levy(
    |                         db, state, item, minister_name=minister_name,
    |                         source_chat_turn_id=source_chat_turn_id,
    |                     )

ming_sim/declaration_dispatch.py::_dispatch_commissions try=1260-1264 body=1260-1261 except=['CovertContractError', 'TypeError', 'ValueError'] raises=[] soft=['_reject'] flag=ONLY_BUILD try_calls=['build_covert_task_contract', 'get']
    | try:
    |                 frozen_task = build_covert_task_contract(covert_task=secret.get("covert_task"))

ming_sim/declaration_dispatch.py::_dispatch_commissions try=1299-1325 body=1299-1322 except=['DecreeMaterializationValidationError', 'TypeError', 'ValueError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['get', 'normalize_draft_person_roster', 'getattr', 'stage_assignment_candidate', 'int', 'get', 'get', 'get', 'get', 'get', 'get', 'get', 'get', 'get', 'get', 'get']
    | try:
    |                 roster = assignment.get("participant_roster")
    |                 if roster is not None:
    |                     from ming_sim.cli_backend import normalize_draft_person_roster
    |                     roster = normalize_draft_person_roster(
    |                         roster, db=db, content=getattr(db, "content", None),

ming_sim/declaration_dispatch.py::_dispatch_commissions try=1509-1513 body=1509-1510 except=['KeyError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['_assert_characters_exist', 'str']
    | try:
    |                 _assert_characters_exist(db, [str(appointment_fields["name"])])

ming_sim/declaration_dispatch.py::_dispatch_endorsements try=1702-1708 body=1702-1705 except=['TypeError', 'ValueError', 'KeyError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['attach_pending_action_endorsement']
    | try:
    |                 db.attach_pending_action_endorsement(
    |                     action_id, entry, commit=False,
    |                 )

ming_sim/declaration_dispatch.py::_dispatch_rushes try=1959-1963 body=1959-1960 except=['KeyError', 'TypeError', 'ValueError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['int']
    | try:
    |                 stage_idx = int(item["stage_idx"])

ming_sim/declaration_dispatch.py::_dispatch_scene_facts try=2599-2603 body=2599-2600 except=['KeyError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['_assert_characters_exist']
    | try:
    |                 _assert_characters_exist(db, speaker_names)

ming_sim/declaration_dispatch.py::_dispatch_endorsements try=1721-1733 body=1721-1730 except=['TypeError', 'ValueError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['add_dossier_endorsement', 'int']
    | try:
    |                 for d in drow:
    |                     db.add_dossier_endorsement(
    |                         int(d["id"]),
    |                         form=form,
    |                         endorser_id=endorser_id,

ming_sim/flows.py::_apply_population_transfers try=1607-1613 body=1607-1610 except=['TypeError', 'ValueError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['_strict_int']
    | try:
    |             # 数量契约＝严格 int（含拒无损整数串）：extractor 提示明令直接输出数字，
    |             # 转移账不沿用 fiscal 的整数串宽容（#649 票面：amount 非 int 即拒）。
    |             amount = _strict_int(raw_amount, accept_numeric_strings=False)

ming_sim/flows.py::_apply_faction_dict try=1493-1497 body=1493-1494 except=['TypeError', 'ValueError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['_strict_int']
    | try:
    |                 d = _strict_int(val)

ming_sim/flows.py::_apply_class_dict try=1748-1752 body=1748-1749 except=['TypeError', 'ValueError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['_strict_int']
    | try:
    |                 d = _strict_int(raw)

ming_sim/flows.py::_apply_faction_dict try=1483-1487 body=1483-1484 except=['TypeError', 'ValueError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['_strict_int']
    | try:
    |                     d = _strict_int(raw)

ming_sim/issues.py::_apply_bandit_absorptions try=7163-7167 body=7163-7164 except=['TypeError', 'ValueError'] raises=[] soft=['_reject'] flag=INPUT_OR_ITEM try_calls=['_strict_int']
    | try:
    |             requested = _strict_int(raw_req, accept_numeric_strings=False)

=== CLASS2 SUMMARY by flag ===
{'ONLY_BUILD': 3, 'INPUT_OR_ITEM': 35, 'CONTROL_EXC': 3, 'WRAPS_INTERNAL': 1}
WRAPS_INTERNAL members:
  ming_sim/declaration_dispatch.py::_dispatch_registrations except=['OfficeAppointmentRejection'] try_calls=['_item_savepoint_scope', 'register_unlisted_person_record', '_ItemAtomicReject', '_attach_character_affair_pointer', 'str', 'list', 'str', 'str', 'int', 'id', 'get', 'get', 'get']
ONLY_BUILD / CovertContractError conversion members:
  ming_sim/cli_backend.py::_extract_secret_order flag=ONLY_BUILD except=['CovertContractError'] raises=[] soft=['contract_error']
  ming_sim/db.py::_apply_pending_action flag=ONLY_BUILD except=['CovertContractError'] raises=['PendingActionRefusal'] soft=['category_refusal']
  ming_sim/declaration_dispatch.py::_dispatch_commissions flag=ONLY_BUILD except=['CovertContractError', 'TypeError', 'ValueError'] raises=[] soft=['_reject']
```

附 AST 核验：`_apply_pending_action` 的 `CovertContractError` try 体 calls=`['build_covert_task_contract']`；`create_secret_order in try body? False`。

### 成员表（覆盖全部候选）

| 成员 | except | flag | 处理 | 理由 |
|------|--------|------|------|------|
| `ming_sim/cli_backend.py` `_extract_secret_order` try:4229 | ['CovertContractError'] | ONLY_BUILD | 保留 | 纯声明/抽取输入校验，不包内部落库 |
| `ming_sim/db.py` `record_monthly_grant_reconciliations` try:12445 | ['TypeError', 'ValueError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/db.py` `record_monthly_grant_reconciliations` try:12481 | ['TypeError', 'ValueError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/db.py` `_apply_pending_action` try:18334 | ['CovertContractError'] | ONLY_BUILD | 已修（保留收窄后） | try 仅包 build_covert_task_contract；create_secret_order 在外 |
| `ming_sim/declaration_dispatch.py` `_attach_commission_affair` try:1073 | ['KeyError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_attach_commission_affair` try:1073 | ['ValueError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_commissions` try:1458 | ['ValueError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_commissions` try:1471 | ['KeyError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_commissions` try:1471 | ['DecreeMaterializationValidationError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_commissions` try:1503 | ['TypeError', 'ValueError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_inquiries` try:1883 | ['KeyError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_travel_tones` try:2032 | ['ValueError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_travel_tones` try:2037 | ['KeyError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_travel_tones` try:2037 | ['ValueError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_textual_facts` try:2308 | ['KeyError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_textual_facts` try:2308 | ['ValueError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_textual_facts` try:2320 | ['ValueError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_public_sayings` try:2375 | ['KeyError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_public_sayings` try:2392 | ['ValueError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_on_scene_facts` try:2439 | ['_ItemAtomicReject'] | CONTROL_EXC | 保留 | 同 try 内主动 raise 的条目控制异常，非意外内部故障洗白 |
| `ming_sim/declaration_dispatch.py` `_dispatch_presence` try:2530 | ['KeyError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_presence` try:2539 | ['AudienceNightError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_scene_facts` try:2608 | ['AudienceNightError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_edge_events` try:2664 | ['ValueError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_edge_events` try:2669 | ['KeyError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_edge_events` try:2678 | ['_ItemAtomicReject'] | CONTROL_EXC | 保留 | 同 try 内主动 raise 的条目控制异常，非意外内部故障洗白 |
| `ming_sim/declaration_dispatch.py` `_dispatch_registrations` try:2793 | ['_ItemAtomicReject'] | CONTROL_EXC | 保留 | 同 try 内主动 raise 的条目控制异常，非意外内部故障洗白 |
| `ming_sim/declaration_dispatch.py` `_dispatch_registrations` try:2793 | ['OfficeAppointmentRejection'] | WRAPS_INTERNAL | 保留 | OfficeAppointmentRejection 本身即 typed 业务拒收（ADR0015），非 CovertContractError 双用途洗白 |
| `ming_sim/declaration_dispatch.py` `_dispatch_commissions` try:1102 | ['KeyError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_commissions` try:1102 | ['TypeError', 'ValueError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_commissions` try:1260 | ['CovertContractError', 'TypeError', 'ValueError'] | ONLY_BUILD | 保留 | 纯声明/抽取输入校验，不包内部落库 |
| `ming_sim/declaration_dispatch.py` `_dispatch_commissions` try:1299 | ['DecreeMaterializationValidationError', 'TypeError', 'ValueError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_commissions` try:1509 | ['KeyError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_endorsements` try:1702 | ['TypeError', 'ValueError', 'KeyError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_rushes` try:1959 | ['KeyError', 'TypeError', 'ValueError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_scene_facts` try:2599 | ['KeyError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/declaration_dispatch.py` `_dispatch_endorsements` try:1721 | ['TypeError', 'ValueError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/flows.py` `_apply_population_transfers` try:1607 | ['TypeError', 'ValueError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/flows.py` `_apply_faction_dict` try:1493 | ['TypeError', 'ValueError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/flows.py` `_apply_class_dict` try:1748 | ['TypeError', 'ValueError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/flows.py` `_apply_faction_dict` try:1483 | ['TypeError', 'ValueError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/issues.py` `_apply_bandit_absorptions` try:7163 | ['TypeError', 'ValueError'] | INPUT_OR_ITEM | 保留 | 字段/引用校验或条目拒收；try 体无内部执行双用途异常转换 |
| `ming_sim/covert_progress.py` canonicalize `except CovertContractError` | [CovertContractError] | NON_REFUSAL | 保留 | 捕获后 return None，非 PendingActionRefusal/_reject 转换 |

### 根因与改动

将 `CovertContractError → PendingActionRefusal` 收窄到 `build_covert_task_contract`；`create_secret_order`（含内部 `merge_investigation_confirmation`）交既有真出口。放宽复扫后唯一同类双用途洗白缝即此（已修）。`OfficeAppointmentRejection` / `_ItemAtomicReject` / 字段级 `_reject` 保留。本纠偏未再改生产。

---

## 验证

### 临时真实入口结构化契约诊断（不固化为仓库测试）

同一入口：`stage_pending_action` → `commit_pending_actions`。
同一契约：内部 `CovertContractError` 必须上抛且 `status=pending`；坏声明仍 `failed`。
装回旧宽 try 时，对同一新契约断言必须报红。

#### 诊断脚本正文

```python
"""Temporary #1853 J9 structured-contract diagnosis (not a repo test).

Same real entry: stage_pending_action → commit_pending_actions.
Contract: internal CovertContractError from create_secret_order must NOT be
laundered into PendingActionRefusal/failed; bad declaration contract still refuses.
"""
from __future__ import annotations

import textwrap
import types

import pytest

from ming_sim.covert_progress import CovertContractError
from ming_sim.exceptions import PendingActionRefusal
from tests.dossier_test_helpers import TYPED_COVERT_TASK


def _minister(content):
    for c in content.characters.values():
        if c.status == "active" and c.power_id == "ming" and c.office_type not in {"后宫", "宗藩"}:
            return c.name
    raise AssertionError("no minister")


def _stage(db, state, minister):
    return db.stage_pending_action(
        int(state.turn), "secret_order", "新建", minister,
        {
            "title": "夜行查饷",
            "content": "着即密核三边饷数。",
            "assignee": minister,
            "tags": [],
            "covert_task": TYPED_COVERT_TASK,
        },
    )


def _status(db, action_id):
    row = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (int(action_id),),
    ).fetchone()
    return str(row["status"])


def _install_old_wide_try(monkeypatch, GameDB):
    """Install baseline-shaped wide try: build+create under CovertContractError→PendingActionRefusal."""
    from ming_sim.covert_progress import (
        CovertContractError as CCE,
        build_covert_task_contract,
        covert_task_from_payload,
    )
    from ming_sim.exceptions import PendingActionRefusal as PAR
    from ming_sim.db import _coerce_deadline_months

    orig = GameDB._apply_pending_action

    def wide(self, state, pa, payload, *, content=None, rejection_collector=None):
        if pa["kind"] == "secret_order" and pa["action"] == "新建":
            title = str(payload.get("title") or "").strip()
            content_text = str(payload.get("content") or "")
            assignee = str(payload.get("assignee") or pa["minister_name"] or "").strip()
            if not title or not content_text.strip() or not assignee:
                return False
            tags_raw = payload.get("tags") or []
            tags = [str(t).strip() for t in tags_raw if str(t).strip()] if isinstance(tags_raw, list) else []
            deadline = _coerce_deadline_months(payload.get("deadline_months"), default=0)
            excluded = payload.get("excluded_names") or []
            excluded = [str(t).strip() for t in excluded if str(t).strip()] if isinstance(excluded, list) else []
            excluded_offices = payload.get("excluded_offices") or []
            excluded_offices = [str(t).strip() for t in excluded_offices if str(t).strip()] if isinstance(excluded_offices, list) else []
            origin_mid = self._parse_origin_chat_message_id(payload)
            raw_task = covert_task_from_payload(payload) or payload.get("covert_task")
            if not raw_task:
                raise PAR(
                    "密令确认缺少差务类型",
                    category="missing_task_type",
                    item={"pending_action_id": int(pa["id"])},
                )
            # OLD WIDE TRY (baseline 3cbc92cfa shape)
            try:
                frozen_task = build_covert_task_contract(covert_task=raw_task)
                order_id = self.create_secret_order(
                    state, assignee, title, content_text, tags, deadline_months=deadline,
                    excluded_names=excluded, excluded_offices=excluded_offices,
                    origin_minister_name=str(pa.get("minister_name") or "") or None,
                    origin_chat_message_id=origin_mid,
                    origin_chat_message_ids=[] if origin_mid is None else None,
                    pending_action_id=int(pa["id"]),
                    covert_task=frozen_task,
                )
            except CCE as exc:
                raise PAR(
                    str(exc),
                    category="covert_contract",
                    item={"pending_action_id": int(pa["id"])},
                ) from exc
            return order_id is not None
        return orig(self, state, pa, payload, content=content, rejection_collector=rejection_collector)

    monkeypatch.setattr(GameDB, "_apply_pending_action", wide)


def test_new_internal_covert_contract_error_stays_pending_and_raises(game, monkeypatch):
    """NEW logic GREEN: internal CovertContractError is not laundered to failed."""
    db, state, content = game
    minister = _minister(content)
    aid = _stage(db, state, minister)

    boom = CovertContractError("合流缺案卷（诊断注入）")
    monkeypatch.setattr(
        type(db), "create_secret_order",
        lambda self, *a, **k: (_ for _ in ()).throw(boom),
    )
    with pytest.raises(CovertContractError, match="合流缺案卷"):
        db.commit_pending_actions(state, content=content, action_ids=[aid])
    assert _status(db, aid) == "pending"
    assert db.list_secret_orders() == []


def test_old_wide_try_launders_internal_to_failed(game, monkeypatch):
    """OLD wide try RED against the NEW structured contract (reproduces disease)."""
    from ming_sim.db import GameDB

    db, state, content = game
    minister = _minister(content)
    aid = _stage(db, state, minister)
    _install_old_wide_try(monkeypatch, GameDB)

    boom = CovertContractError("合流缺案卷（诊断注入）")
    monkeypatch.setattr(
        type(db), "create_secret_order",
        lambda self, *a, **k: (_ for _ in ()).throw(boom),
    )
    # Old policy soft-fails typed refusal: commit returns, status=failed — NEW contract forbids this.
    db.commit_pending_actions(state, content=content, action_ids=[aid])
    status = _status(db, aid)
    # Assert the NEW contract; this MUST fail under old wide try (RED).
    assert status == "pending", f"old-wide-try disease: status={status} (expected pending under new contract)"


def test_new_bad_declaration_still_business_refusal(game, monkeypatch):
    """NEW logic GREEN: bad declaration covert_task still typed refusal → failed."""
    db, state, content = game
    minister = _minister(content)
    aid = db.stage_pending_action(
        int(state.turn), "secret_order", "新建", minister,
        {
            "title": "夜行查饷",
            "content": "着即密核三边饷数。",
            "assignee": minister,
            "tags": [],
            "covert_task": {"kind": "不是合法差务"},
        },
    )
    # Should soft-fail as PendingActionRefusal via dispose; no raise out of commit.
    applied = db.commit_pending_actions(state, content=content, action_ids=[aid])
    assert applied == []
    assert _status(db, aid) == "failed"


def test_restored_new_after_old_patch_green(game, monkeypatch):
    """After installing then undoing old wide try, NEW contract GREEN again."""
    from ming_sim.db import GameDB

    db, state, content = game
    minister = _minister(content)
    aid = _stage(db, state, minister)
    _install_old_wide_try(monkeypatch, GameDB)
    monkeypatch.undo()  # restore original methods from this monkeypatch stack

    # Re-apply only the create_secret_order boom on fresh method
    boom = CovertContractError("合流缺案卷（诊断注入）")
    monkeypatch.setattr(
        type(db), "create_secret_order",
        lambda self, *a, **k: (_ for _ in ()).throw(boom),
    )
    with pytest.raises(CovertContractError, match="合流缺案卷"):
        db.commit_pending_actions(state, content=content, action_ids=[aid])
    assert _status(db, aid) == "pending"
```

#### 诊断命令

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false
# 将下文「诊断脚本正文」写入 $DIAGDIR/test_diag_1853_j9.py 后执行
DIAGDIR=$(mktemp -d /tmp/1853-j4r-j9-diag.XXXXXX)
# ... write test_diag_1853_j9.py ...
cd /Users/akagilnc/WorkSpace/Ming_LLM-1853-w5
PY=/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
  "$PY" -m pytest -p tests.conftest \
  "$DIAGDIR/test_diag_1853_j9.py::test_new_internal_covert_contract_error_stays_pending_and_raises" \
  "$DIAGDIR/test_diag_1853_j9.py::test_new_bad_declaration_still_business_refusal" \
  -q -s -p no:cacheprovider --tb=short
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
  "$PY" -m pytest -p tests.conftest \
  "$DIAGDIR/test_diag_1853_j9.py::test_old_wide_try_launders_internal_to_failed" \
  -q -s -p no:cacheprovider --tb=short
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
  "$PY" -m pytest -p tests.conftest \
  "$DIAGDIR/test_diag_1853_j9.py::test_restored_new_after_old_patch_green" \
  -q -s -p no:cacheprovider --tb=short
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
  "$PY" -m pytest -p tests.conftest \
  "$DIAGDIR/test_diag_1853_j9.py" \
  -q -s -p no:cacheprovider --tb=line
rm -rf "$DIAGDIR"
```

#### 输出 A（新逻辑绿）

```
[07:31:40.506] [pending_actions] 落库失败上抛 id=1 secret_order/新建：合流缺案卷（诊断注入）
.[07:31:40.517] [pending_actions] 业务拒收 id=1 secret_order/新建：密令确认缺少价值轴
.
2 passed in 0.78s
real 1.24
user 0.98
sys 0.12
```

#### 输出 B（旧宽 try × 新契约 → 红）

```
[07:31:41.652] [pending_actions] 业务拒收 id=1 secret_order/新建：合流缺案卷（诊断注入）
F
=================================== FAILURES ===================================
________________ test_old_wide_try_launders_internal_to_failed _________________
/tmp/1853-j4r-j9-diag.rVVuq3/test_diag_1853_j9.py:139: in test_old_wide_try_launders_internal_to_failed
    assert status == "pending", f"old-wide-try disease: status={status} (expected pending under new contract)"
E   AssertionError: old-wide-try disease: status=failed (expected pending under new contract)
E   assert 'failed' == 'pending'
E
E     - pending
E     + failed
=========================== short test summary info ============================
FAILED ../../../../tmp/1853-j4r-j9-diag.rVVuq3/test_diag_1853_j9.py::test_old_wide_try_launders_internal_to_failed
1 failed in 0.68s
real 1.16
user 1.01
sys 0.13
```

#### 输出 C（恢复新逻辑绿）

```
[07:31:43.002] [pending_actions] 落库失败上抛 id=1 secret_order/新建：合流缺案卷（诊断注入）
.
1 passed in 0.81s
real 1.34
user 1.14
sys 0.14
```

#### 输出 D（合跑：1 failed + 3 passed；failed 必须是旧宽 try 案）

```
[07:31:44.344] [pending_actions] 落库失败上抛 id=1 secret_order/新建：合流缺案卷（诊断注入）
.[07:31:44.357] [pending_actions] 业务拒收 id=1 secret_order/新建：合流缺案卷（诊断注入）
F[07:31:44.407] [pending_actions] 业务拒收 id=1 secret_order/新建：密令确认缺少价值轴
.[07:31:44.419] [pending_actions] 落库失败上抛 id=1 secret_order/新建：合流缺案卷（诊断注入）
.
=================================== FAILURES ===================================
________________ test_old_wide_try_launders_internal_to_failed _________________
/tmp/1853-j4r-j9-diag.rVVuq3/test_diag_1853_j9.py:139: in test_old_wide_try_launders_internal_to_failed
    assert status == "pending", f"old-wide-try disease: status={status} (expected pending under new contract)"
E   AssertionError: old-wide-try disease: status=failed (expected pending under new contract)
E   assert 'failed' == 'pending'
E
E     - pending
E     + failed
=========================== short test summary info ============================
FAILED ../../../../tmp/1853-j4r-j9-diag.rVVuq3/test_diag_1853_j9.py::test_old_wide_try_launders_internal_to_failed
1 failed, 3 passed in 0.85s
real 1.38
user 1.16
sys 0.17
```

| 阶段 | 期望 | 实果 |
|------|------|------|
| A 新逻辑（内部异常 + 坏声明） | 绿 | `2 passed` |
| B 旧宽 try × 新契约 | 红（status=failed 洗白） | `1 failed`；`status=failed` vs 期望 `pending` |
| C 恢复新逻辑 | 绿 | `1 passed` |
| D 合跑 | 1 failed + 3 passed | `1 failed, 3 passed` |

说明：若把 B 改成「洗成 failed 即通过」再合跑得到「4 passed」，只是复现旧病，不是旧红新绿。

### 聚焦测试（触及面，非全量）

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false
cd /Users/akagilnc/WorkSpace/Ming_LLM-1853-w5
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest \
  tests/test_audience_commit_failure_1853.py \
  tests/test_execution_pressure_654.py \
  tests/test_dossier_links_559.py \
  tests/test_secret_order_payoff_1504.py \
  tests/test_urge_lever_624.py \
  tests/test_person_delta_adapter.py \
  -q -p no:cacheprovider --tb=line
```

输出：

```
.................................F...................................... [ 26%]
........................................................................ [ 53%]
........................................................................ [ 80%]
...........................s..........................                   [100%]
=================================== FAILURES ===================================
E   ValueError: 参与人物不存在：查无此人。请填写朝堂名册中已有的大臣姓名。
----------------------------- Captured stdout call -----------------------------
[07:31:59.936] [pending_actions] 落库失败上抛 id=1 directive/拟旨：参与人物不存在：查无此人。请填写朝堂名册中已有的大臣姓名。
/Users/akagilnc/WorkSpace/Ming_LLM-1853-w5/ming_sim/db.py:21042: ValueError: 参与人物不存在：查无此人。请填写朝堂名册中已有的大臣姓名。
=========================== short test summary info ============================
FAILED tests/test_execution_pressure_654.py::test_path1_conversational_draft_bad_roster_marks_failed
1 failed, 268 passed, 1 skipped in 5.16s
real 5.67
user 3.90
sys 1.22
```

- 结果：`1 failed, 268 passed, 1 skipped`
- 唯一失败：`test_path1_conversational_draft_bad_roster_marks_failed`（基线 `3cbc92cfa` 同红；#1812 不为本切片追绿）
- `git diff --check`：无输出

## 自查

- 合法性：仅服务末份两类 + 回执纠偏；未补恢复库；未新造永久扫描器/证明测试；未 amend/push/PR。
- 质量：生产维持 `2b4e6e2bd`；共同生命周期唯一；拒收转换已收窄。
- 枚举复扫：放宽两类后成员表覆盖全部候选。
- 行为证明：旧宽 try 红 + 新逻辑绿；不以结构锁或「4 passed 旧病复现」冒充。

## 剩余缺口（如实）

- 核心恢复接线等仍归 #1873 / 家族收尾。
- `test_path1_conversational_draft_bad_roster_marks_failed` 基线已红，留家族收尾。

## Seal

```bash
git rev-parse HEAD
git branch --show-current
git status --porcelain=v1 --untracked-files=all
```

（提交后回填 SHA。）
