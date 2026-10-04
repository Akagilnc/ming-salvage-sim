# #1835-w5 按类扫描：`merge-seam-retired-symbol-import`

## 承认（前序聚焦缺口）

前序聚焦清单 `artifacts/issue-1835-w5-conflict-tests.txt` **只覆盖冲突文件**，漏掉底座 W4 自动并入的**非冲突新增**测试。  
实证：`tests/test_staged_assignment_identity_1890.py` 属 W4 非冲突新增，仍 `from ming_sim.issues import apply_score_extraction`，导致全仓 `pytest --collect-only` 收集中断。

## 扫描类与符号

- **类名**: `merge-seam-retired-symbol-import`
- **符号**: `apply_score_extraction` / `EMPTY_EXTRACTION` / `default_terminal_reason` / `MODULE_FIELDS`
- **方法**: AST 扫 import / Call（非 docstring 命名残留）；范围 = W4 新增 ∪ W4/merge 修改的全部 `tests/`（不仅冲突清单）
- **universe**: 162 文件（见 `artifacts/issue-1835-w5-retired-symbol-scan.json`）

## 修复前代码命中（本轮）

| 文件 | 行 | 命中 |
|---|---|---|
| `tests/test_staged_assignment_identity_1890.py` | 25 | `from ming_sim.issues import apply_score_extraction` |
| 同上 | 693 / 720 | `apply_score_extraction(...)` 两条 `new_issues` 用例 |

同类整类结论：在 W4 新增/修改测试宇宙内，**仅此文件**有可打断收集的退役符号 import/call。其余命中多为历史函数名 / docstring 叙述，不构成 ImportError。

## 处置

- 两条 `new_issues` 用例改走现役 `settle_delta` + `issue_rows` / `rejected_view`（SettlementOutcome 局势段）
- 行为保持：散文年诺不成承诺段（拒收 `invalid_enum`、库零行）；结构化 `stages` 正常落段
- 同类运行时：`tests/test_candidate_supply_1893.py` 改读 `issue_rows` / `rejected_view`
- 同文件复核补生产：`_dispatch_commissions` `source_chat_turn_id` 透传；`stages_to_json` 严格拒收散文段表
- **不**恢复 `apply_score_extraction` / `EMPTY_EXTRACTION` / 兼容壳

## 扩充聚焦清单

- 路径: `artifacts/issue-1835-w5-focused-tests.txt`
- 构成: 原冲突清单 ∪ W4 非冲突新增 ∪ 按类扫描受影响文件
- 命令脚本已改指该清单: `artifacts/issue-1835-w5-focused-cmd.sh`

## 验证摘要

- 聚焦：2303 passed / 0 failed / 4 skipped（≈61.37s real）
- 全仓 `--collect-only`：3707 collected / 0 error（≈5.43s real）
