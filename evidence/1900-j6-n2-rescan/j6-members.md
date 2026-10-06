# J6 members (N2 rescan)

Boundary: 必要失败行为、原故障来源与实际结果的证明遗漏，以及修理新增的非契约文字锁
Members: 4
Dispositions: {'FIX_DONE': 3, 'KEEP_EXTERNAL_STATE': 1}

| file | test | tags | disposition | why |
| --- | --- | --- | --- | --- |
| `tests/test_mechanical_tail_1845.py` | `test_mechanical_tail_missing_llm_config_surfaces_retry` | JUDGE_SAMPLE_REVIEW | **FIX_DONE** | wrap real ending path; bind error to str(captured LLMUnavailable); no production Chinese lock |
| `tests/test_menu_lifecycle_drain_396.py` | `test_spawn_pending_write_thread_start_failure_releases_ownership` | JUDGE_SAMPLE_REVIEW | **FIX_DONE** | error→end + message==str(start_error); ownership release retained |
| `tests/test_secret_order_monthly_progress_566.py` | `test_real_no_edict_entries_roll_back_every_external_state_after_fiscal_write` | JUDGE_SAMPLE_REVIEW | **FIX_DONE** | web detail.message==str(fiscal_fault); cli identity; rollback retained |
| `tests/test_web_llm_runtime_config.py` | `test_hot_replace_http_failure_keeps_old_state_and_writes_usable` | S_HTTP_DIAG | **KEEP_EXTERNAL_STATE** | 契约=热替换失败后旧局可写/turn 保真；status 500 为入口信号。诊断面非本案必要结果；不机械加身份。 |
