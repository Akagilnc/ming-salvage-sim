# J6 disposition: private_helper_call_no_obs_token (102)

Structural flag only; many hits are underscore-in-public-import false positives. Disposition is semantic against the full J6 class.

## Counts: retain=78 migrate=20 delete=4 (total 102)

## TRUE class members needing code change (delete/migrate)

- **migrate** `tests/test_audience_restore_505.py::test_truncate_migrated_overlap_does_not_resurrect_via_agno_read` — SUT today is private db._truncate_agno_runs_in_tx; migrate call to public truncate_agno_session_runs while keeping non-resurrection via public run-id read.
- **migrate** `tests/test_enter_settlement_period_1235.py::test_exit_settlement_display_acquires_write_gate` — Today drives private web_app._exit_settlement_display_on_failure/_accept_settlement_period; migrate to the public exit path while keeping gate-held clear result.
- **migrate** `tests/test_mechanical_tail_1845.py::test_advance_schedules_mechanical_tail_after_front_month_advance` — Contract is resolve_turn scheduling; replace month_chain._load_chain observation with get_resolve_context/public tail status.
- **migrate** `tests/test_mechanical_tail_1845.py::test_reopen_resumes_incomplete_mechanical_tail` — Crash-resume contract is valuable; drop private _load_chain/_save_chain as the persistence API.
- **delete** `tests/test_menu_lifecycle_drain_396.py::test_drain_and_close_session_waits_for_gate_then_closes` — Helper-only direct web_app._drain_and_close_session gate wait; covered by api_menu_exit delayed-close and chat_stream drain waits.
- **migrate** `tests/test_menu_lifecycle_drain_396.py::test_get_main_db_path_prefers_active_db_over_launch_env` — Today asserts private _get_main_db_path/_active_db_path_file; migrate to the startup/new_game path that consumes that preference.
- **migrate** `tests/test_menu_lifecycle_drain_396.py::test_drain_archive_skips_move_when_session_close_fails` — Valuable close-fail⇒no-move contract currently locked to private _drain_and_close_session/_claim_close stack.
- **migrate** `tests/test_menu_lifecycle_drain_396.py::test_restore_main_db_path_config_remove_failure_is_loud` — Loud remove-failure contract is real but entry is private _restore_main_db_path_config.
- **migrate** `tests/test_menu_lifecycle_drain_396.py::test_drain_rejects_late_pending_write_before_gate_acquire` — Seal-rejects-late-claim is a real gate negative but currently driven only through private _drain_and_close_session.
- **migrate** `tests/test_month_chain_1843.py::test_world_segment_persists_declaration_ending_with_commit` — Ending persistence is valuable but SUT is private month_chain._run_world_segment.
- **migrate** `tests/test_month_chain_1843.py::test_staged_ending_is_available_inside_its_settlement_transaction` — Keep settle-entry contract; stop using private _ending_from_dispatch_result as the outcome oracle.
- **migrate** `tests/test_month_chain_1843.py::test_advance_uses_staged_declaration_ending` — Ending advance contract locked to private _advance_after_gazette.
- **migrate** `tests/test_month_chain_1843.py::test_advance_reloads_memory_after_transaction_rollback` — Rollback+reload contract is real but entry is private _advance_after_gazette.
- **migrate** `tests/test_qa_c2_settlement_display_lifecycle_1343.py::test_success_clear_throw_still_ends_inflight` — Finally/inflight hygiene is necessary but currently SUT is private _settlement_period_entry.
- **migrate** `tests/test_qa_c2_settlement_display_lifecycle_1343.py::test_failure_exit_throw_still_ends_inflight` — Symmetric finally hygiene locked to private _settlement_period_entry.
- **delete** `tests/test_qa_t1_extraction_dual_source_1353.py::test_empty_startup_catchup_claims_zero_tickets` — Helper-only re-call of _spawn_startup_extraction_catch_up; empty-queue init already implied by other seam tests.
- **migrate** `tests/test_qa_t1_extraction_dual_source_1353.py::test_barrier_waits_trail_ticket_then_auto_close` — Trail-ticket barrier ordering is a real gate; migrate off private _settlement_period_entry/_mark_pending_write as the sole entry.
- **migrate** `tests/test_qa_t1_extraction_dual_source_1353.py::test_production_seam_cancel_blocks_trail_write` — Cancel-blocks-write is valuable but driven through private _ticketed_write_gate/_mark_pending_write.
- **migrate** `tests/test_qa_t1_extraction_dual_source_1353.py::test_production_seam_post_barrier_ticket_ordered` — Post-barrier ticket ordering contract needs public settlement entry, not private helpers only.
- **delete** `tests/test_qa_t1_extraction_dual_source_1353.py::test_startup_catchup_uses_ticketed_gate_not_bare` — Internal wiring probe: fake catch_up inspects write_gate type via private _run_startup_extraction_catch_up.
- **delete** `tests/test_qa_t1_extraction_dual_source_1353.py::test_ticketed_write_gate_rejects_none` — Private helper-only: game._ticketed_write_gate(None) raises; no external entry/result contract.
- **migrate** `tests/test_verify_llm_clocks_884.py::test_cli_channel_does_not_smoke_retained_api_advanced_slot` — CLI smoke-vs-retained-advanced contract is real but entry is private _verify_llm_configs_or_raise.
- **migrate** `tests/test_web_llm_runtime_config.py::test_advanced_llm_verification_preserves_api_channel_over_backend_env` — API-channel preservation under env backend is valuable; migrate off private _verify_llm_configs_or_raise.
- **migrate** `tests/test_web_llm_runtime_config.py::test_advanced_llm_verification_preserves_reasoning_strength` — Reasoning-strength preservation during verify is real; entry is private helper.

## Retain note

Retain only where a concrete public/real entry + observable result (+ explicit mock_boundary) already exist; necessary gate negatives kept with real entry + actual results.

Full JSONL: `evidence/1900-j18-j6-retire-fixer/j6-disposition-private-helper.jsonl`
