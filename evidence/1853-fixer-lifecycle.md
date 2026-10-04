# #1853 修内司回执：提交生命周期归一 + 拒收转换收窄

- 票：#1853
- 派单：`01a10901-cf48-78eb-88f5-d4ccd507349f@fixer`
- 判词：`attachments/08-1853-judge-3cbc92cfa.json` 末份（第 9 份 payload）
- 基线 HEAD：`3cbc92cfaa090ecd15ffe7b567fb78f1725f4f44`
- 施工分支：`ak-roles/issue-1853-j4r-j9-lifecycle`
- 本回执不表示已合并或家族收尾完成

## 未结类别（仅末份）

1. **J4-R**「暂存提交生命周期仍有双实现」— 成立，归并完整性 C1  
2. **J9**「输入拒收转换覆盖内部执行，洗白真实故障」— 成立，归并正确性 C1  

## 官方旁证（先搜后修）

- [PEP 8 Programming Recommendations](https://peps.python.org/pep-0008/#programming-recommendations)：`try` 只包最小必要代码，避免把内部错误一并捕获。  
- DRY / 单一权威表示：重复的提交生命周期知识只保留一处，调用方保留真差异。  
裁决法源仍为仓库规则与判词；上述仅作方向旁证。

## 类一：暂存提交生命周期单一权威（J4-R）

### 枚举谓词

函数体**同时**含 `SAVEPOINT` + `ROLLBACK TO` + `RELEASE` + `status='committed'` 的暂存提交生命周期实现（全仓 `*.py` AST 扫描）。

### 枚举命令

```bash
# 概念等价（实跑为内联 python AST）：
# 遍历全仓 *.py，找 FunctionDef 体同时含上述四标记者
python3 - <<'PY'
# （施工时实跑；结果见下表）
PY
```

### 修理前成员表

| 成员 | 处理 | 理由 |
|------|------|------|
| `ming_sim/db.py` `commit_pending_actions` 内联生命周期 | 改为调用唯一实现 | 与拟旨专路重复整段 atomic/savepoint/apply/status/dispose/release/flush |
| `ming_sim/db.py` `_commit_conversational_draft` 内联生命周期 | 改为调用唯一实现 | 同上；保留拟旨 `_directive_status` 输入准备 |
| `ming_sim/db.py` `_dispose_pending_action_apply_exception` | **保留** | 已是共同异常分流，不是第二套生命周期 |
| office 内存快照 / `restore_office_memory` | **保留在调用方** | 判词允许的必要差异，不进入共同生命周期 |
| 拟旨 `payload_for_apply["_directive_status"]` | **保留在调用方** | 判词允许的输入准备差异 |

### 修理后复扫

| 角色 | 成员 |
|------|------|
| 唯一内联实现 | `ming_sim/db.py:17628-17686` `_run_pending_action_commit_lifecycle` |
| 调用方 | `commit_pending_actions`、`_commit_conversational_draft` |

复扫结果：inline owner = 1；不再有第二套共同生命周期。

### 根因与改动

此前 J4 只归一了 `_dispose_pending_action_apply_exception`，两条入口仍各自复制整段提交生命周期。抽出 `_run_pending_action_commit_lifecycle`，两条入口只保留各自输入/内存差异后委托。

## 类二：业务输入拒收与内部故障接缝分离（J9）

### 枚举谓词

全仓 `except CovertContractError`：是否转换为业务拒收（`PendingActionRefusal` / `_reject`），以及 `try` 体是否覆盖 `create_secret_order` / `merge_investigation*` 等内部执行。

### 修理前成员表

| 成员 | 处理 | 理由 |
|------|------|------|
| `db.py` `_apply_pending_action` 密令新建：`try` 包 `build_covert_task_contract` **与** `create_secret_order` | **修** | 内部 `CovertContractError`（如合流缺案卷）被洗成 `PendingActionRefusal`/`failed` |
| `declaration_dispatch.py` 只包 `build_covert_task_contract` → `_reject` | **保留** | 纯声明输入校验 |
| `cli_backend.py` 抽取时只包 `build_covert_task_contract` → `contract_error` | **保留** | 输入抽取契约，不洗内部落库 |
| `covert_progress.py` canonicalize 捕获后 `return None` | **保留** | 非拒收转换、非提交洗白 |

### 修理后复扫

全部 `CovertContractError` 捕获点：`wraps_internal_exec=False`；唯一拒收转换点均 `only_build=True`。

### 根因与改动

将 `CovertContractError → PendingActionRefusal` 收窄到 `build_covert_task_contract`；`create_secret_order` 及其内部异常交既有 `_dispose_pending_action_apply_exception` 真出口（留 `pending` 并上抛）。

## 验证

### 环境前缀（七变量）

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false
```

### 临时真实入口变异诊断（不固化为仓库测试）

自建 `/tmp/1853-j4r-j9.*`，测后已删。

| 案 | 期望 | 结果 |
|----|------|------|
| 新码：`create_secret_order` 抛内部 `CovertContractError` | 上抛、status=`pending` | 绿 |
| 新码：坏声明契约 | 仍业务拒收、status=`failed` | 绿 |
| 临时装回旧宽 `try`（包 create） | 洗成拒收、status=`failed`（旧红） | 绿（复现旧病） |
| 结构：仅一处 inline lifecycle | owners=`[_run_pending_action_commit_lifecycle]` | 绿 |

- 输出摘要：`4 passed in 1.07s`；`DIAG_DURATION≈1.56s`；`OWN_TEMP_EXISTS=False`

### 聚焦测试（触及面，非全量）

```bash
# 同上七变量前缀
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
  ../Ming_LLM/.venv/bin/python -m pytest \
  tests/test_audience_commit_failure_1853.py \
  tests/test_execution_pressure_654.py \
  tests/test_dossier_links_559.py \
  tests/test_secret_order_payoff_1504.py \
  tests/test_urge_lever_624.py \
  tests/test_person_delta_adapter.py \
  -q -p no:cacheprovider
```

- 结果：`1 failed, 268 passed, 1 skipped in 6.47s`；`FOCUS_DURATION≈6.96s`
- 唯一失败：`test_path1_conversational_draft_bad_roster_marks_failed`
- **基线对照**：将 `ming_sim/db.py` 临时换回 `3cbc92cfa` 后同案仍 `ValueError` 红（`BASELINE_EXIT=1`）。属修理前既有红灯，非本两类引入；按 #1812 不为本切片追绿、不削弱断言。

## 自查

- 合法性：仅服务末份两类；未补恢复库/分类账本/新框架；未改宿主/席位配置；未 amend/stash/push/PR。  
- 质量：删简复用既有 dispose 出口；共同生命周期唯一；输入准备与 office 恢复差异保留。  
- 枚举复扫：两类谓词复扫无遗漏成员。  
- `git diff --check`：无输出。

## 剩余缺口（如实）

- 核心恢复接线、夜卷连续读失败等功能事项仍归 #1873 / 家族收尾，本切片不接通。  
- `test_path1_conversational_draft_bad_roster_marks_failed` 基线已红（坏花名册走真异常上抛而非 soft failed），留家族收尾处置。
