# #642 restore 全链点检矩阵（P-2 / TD-5）

| # | 故障缝 | 证据（测试名） | 结果 |
|---|---|---|---|
| **R1** | 边事件流水 + 关系摘要持久边界 | 本片 `tests/test_family_tail_642.py::test_r1_edges_and_summaries_survive_reopen`（双表面；扩既有 `tests/test_relation_store_632.py::test_relation_edges_survive_restore` 仅边面） | CI 确定性 |
| **R2** | settle 已提交 → join 完成 → **persist 前**可控中止 | `tests/test_relation_brew_636.py::test_r2_commit_join_before_persist_fault_keeps_pending_and_rebrrews_once` | 非 SIGKILL；pending 在册、旧摘要不变、补酿恰一次、边 id 不双增。**已删** fault A/B SIGKILL 形状 |
| **R3** | seed 新档导入中断 / 重开幂等 / 旧档不触发 | 既有 `tests/test_relation_seed_638.py`：`test_seed_failure_rolls_back_new_save_and_retry_imports`、`test_invalid_bundled_seed_rolls_back_new_save_and_can_retry`、`test_repeated_import_is_idempotent_no_double_write`、`test_existing_save_is_never_touched_by_seed_import` | 点检引用 |

注入纪律（r3）：R2 路径零 SIGKILL 残留。
