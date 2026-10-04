# J6 wide disposition — batch1 (alphabetical first third, py)

## Slice

| Metric | Value |
|--------|------:|
| Unique `tests/*.py` in structural candidates | 209 |
| First-third files (alphabetical) | 70 |
| Structural candidates in slice | 877 |
| Skipped (already in `j6-wide-disposition-prio.jsonl`) | 35 |
| **Rows in `j6-wide-disposition-batch1.jsonl`** | **842** |

Mechanical input: `j6-structural-candidates.jsonl`. Each row was dispositioned after reading the flagged source segment (`line`–`end`); prio keys `(file, name, line)` were not re-emitted.

## Actions

| action | count |
|--------|------:|
| retain | 824 |
| migrate | 18 |
| delete | 0 |

### migrate (18)

- `test_army_needed_derives_from_manpower_rate`
- `test_audience_admission_distinguishes_capital_fresh_and_existing_transit`
- `test_knowledge_exclusion_reads_current_office_without_nameerror`
- `test_kimi_material_file_is_removed_on_start_failure`
- `test_clichat_codex_response_stream_passes_reasoning_strength`
- `test_add_gate_llm_args_uses_gate_cli_runners`
- `test_protagonist_lands_and_rejects_nonexistent_person`
- `test_draft_extraction_does_not_capture_acting_appointment`
- `test_batch_draft_extraction_preserves_each_mechanical_payload`
- `test_bake_uses_half_endpoint_weights_and_zero_diagonal`
- `test_baked_content_covers_all_regions_and_three_golden_anchors`
- `test_commission_malformed_escort_is_rejected_not_dropped`
- `test_commission_escort_names_must_exist`
- `test_commission_without_escort_declares_none`
- `test_mao_event_effect_uses_unified_person_change_key`
- `test_issue_194_strategic_foreign_events_are_explicitly_classified_and_gated`
- `test_auto_trigger_historical_events_use_preloaded_terminal_refs`
- `test_cli_capture_rejects_bad_target_or_scope`

### delete (0)

No first-third candidate (outside prio) met delete after segment review: remaining cases are public-entry integration/contract tests, content-load fail-loud gates, or CLI/HTTP surfaces with observable DB/state/exception outcomes. Class-member deletes from earlier J6 rounds live in prio / `j6-class-members.jsonl` (files mostly outside this alphabetical slice).

## Test code touched (migrate)

- `tests/test_advance_paths_atomic.py`: removed `I._event_trigger_refs` internal oracle from `test_submit_event_decision_persists_choice_after_pending_cleanup` (public `has_event_triggered` + `event_triggers` row remain).

## Regenerate

```sh
python3 evidence/1900-j18-j6-retire-fixer/j6_build_wide_batch1.py
```

Post-adjust rules in that script encode hand-reviewed corrections (event content load gates, CLI surfaces, advance_paths HITL, declaration dispatch, distance-matrix oracle, etc.).

## Output schema

Each JSONL row: `file`, `name`, `line`, `flags`, `action`, `entry`, `result`, `mock_boundary`, `reason`, `spec_cite`.
