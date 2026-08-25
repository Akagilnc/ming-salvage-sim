# #642 restore 全链点检矩阵（P-2 / TD-5）

| # | 故障缝 | 证据 | 结果 |
|---|---|---|---|
| **R1** | 边 + 摘要持久 | `tests/test_relation_store_632.py::test_relation_edges_survive_restore`（#642 扩摘要面） | CI |
| **R2** | commit→join→persist 前 | `tests/test_relation_brew_636.py::test_r2_commit_join_before_persist_fault_keeps_pending_and_rebrrews_once` | 非 SIGKILL；**已删** fault A/B 硬杀。契约=该生产接缝窗口（不默示覆盖原进程猝死窗） |
| **R3** | seed 中断/幂等/旧档 | seed_638：`test_seed_failure_rolls_back_*`、`test_invalid_bundled_seed_*`、`test_repeated_import_*`、`test_existing_save_is_never_touched_*` | 点检引用 |
