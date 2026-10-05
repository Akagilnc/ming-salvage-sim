# #1891/#1899 DRY-C1／D1 + TEST-C1／T1 闭包回执

现场：`/Users/akagilnc/WorkSpace/Ming_LLM-1899-w5`，分支 `ak-roles/1891-class-sweep`。  
开工 HEAD：`7ba04d2263793153383e5e2b95d9d58d54ac5456`。  
法源：末份 `1891m-judge-7ba04d226.json` payload[4]、`1899c-judge-7ba04d226.json` payload[3]、`1891-1899-countersign-7ba04d226.json`（原卷直读）。  
授权面仅两类：DRY-C1／D1 共同结算控制流重复；TEST-C1／T1／F1 退役测试闭包。  
Python：`/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`。  
临时根：`/tmp/1891-dry-test.e72Ys3`。

## 可复跑枚举命令（自包含）

七变量前缀（凡本机游戏 pytest 必带）：

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1
TMPROOT=/tmp/1891-dry-test.e72Ys3
PY=/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python
```

全仓 tracked Python AST（错误上浮，不吞）：

```bash
$PY - <<'PY'
import ast, subprocess
from pathlib import Path
files=subprocess.check_output(['git','ls-files','*.py'], text=True).splitlines()
for rel in files:
    ast.parse(Path(rel).read_text(encoding='utf-8'), filename=rel)  # SyntaxError 直接抛
print(f'TRACKED_PYTHON_PARSED {len(files)} AST_ERRORS 0')
PY
```

本轮实测：`TRACKED_PYTHON_PARSED 351 AST_ERRORS 0`（修后复扫同数）。

消费者索引（官方 `ast.parse` / `ast.walk` / `ast.dump`；参考 [Python ast 文档](https://docs.python.org/3/library/ast.html)）：对 Name(Load)、Attribute、ImportFrom、`@pytest.fixture`／`parametrize` 注册建索引；**同名其它文件的 `func_def` 不算消费者**。授权组合 diff = `10e64fbef..HEAD` 的 `tests/*.py`（含本轮工作树改动）。

庭列 24 逐项命令骨架：对每条 `(file, name)` 查 defs + real consumers；本轮结果见下表。

## 修前扫描

### DRY-C1／D1

- `ming_sim/cli/terminal.py`：`play_turn` 在 `action == "skip"`（约 649）与 `action == "issue"`（约 680）各维护一份快照／`_cli_write_gate`／异常／失败报告／`None`／`ended`／`awaiting`／`advanced` 收尾。
- 独立 `ast.dump(..., include_attributes=False)` 比较两段结果控制流：`OUTCOME_AST_EQUAL True`（与末份判词一致）。

### TEST-C1／T1

| qualified | 修前状态 |
| --- | --- |
| `tests.test_web_court_visibility.test_vassal_prince_chat_rejected` | 调用已删 `web_app._require_active_minister` |
| `tests.test_web_court_visibility.test_active_consort_chat_not_rejected` | 同上 |
| `tests.test_qa_s2_copy_prompts_1356_1402.test_require_active_minister_uses_can_summon_reason` | 同上 |
| `tests.test_web_court_visibility._stub_game` | 仅被上述两案消费 |

旧三案红取证（先红后删，不建替代案）：

```text
命令：七变量 + MING_SIM_USER_DATA_DIR=$TMPROOT/user + pytest -p no:cacheprovider --basetemp=$TMPROOT/pytest-red \
  tests/test_web_court_visibility.py::test_vassal_prince_chat_rejected \
  tests/test_web_court_visibility.py::test_active_consort_chat_not_rejected \
  tests/test_qa_s2_copy_prompts_1356_1402.py::test_require_active_minister_uses_can_summon_reason
日志：$TMPROOT/red-three.log
结果：3 failed in 0.82s；墙钟 time 1.330s total
失败：三案均为 AttributeError: module 'web_app' has no attribute '_require_active_minister'
```

### 庭列 24（修前逐项）

| # | qualified 成员 | 消费者 | 处置 |
| --- | --- | --- | --- |
| 1 | `tests.test_audience_background._assert_next_accepted` | 无 | 删 |
| 2 | `tests.test_decree_dossiers_571._complete_session` | 无 | 删 |
| 3 | `tests.test_faction_brew_637._dual_brew_fn_factory` | 无 | 删 |
| 4 | `tests.test_faction_brew_637._relation_script` | 无 | 删 |
| 5 | `tests.test_fiscal_levy_effect._settled_land_by_region` | 无 | 删 |
| 6 | `tests.test_highlight_judge_544._restore_highlight_seams` | 无 | 删 |
| 7 | `tests.test_highlight_judge_544._drain` | 无 | 删 |
| 8 | `tests.test_month_loop_tracer_1468._install_canned_minister` | 无 | 删 |
| 9 | `tests.test_month_loop_tracer_1468._month_ord_of` | 无 | 删 |
| 10 | `tests.test_month_loop_tracer_1468._play_one_month` | 无 | 删 |
| 11 | `tests.test_month_loop_tracer_1468._setup_open_night_participant` | 无 | 删 |
| 12 | `tests.test_mutiny_actual_residence_659._pin_split_arrears` | 无 | 删 |
| 13 | `tests.test_mutiny_actual_residence_659._simulator_army_dicts` | 无（初扫误把同名 `tests.test_mutiny_third_strike_318._simulator_army_dicts` 的 func_def 当消费者；纠正后仍无 name/attr/import 消费者） | 删（授权面内定义） |
| 14 | `tests.test_pihong_dossier_1490._658_session` | 无 | 删 |
| 15 | `tests.test_pre_settle_transaction._drive_resolve_directives` | 无 | 删 |
| 16 | `tests.test_promulgation_seam_560._stage_policy_dossier` | 无 | 删 |
| 17 | `tests.test_rescript_draft_656._retire_existing_actors` | 无 | 删 |
| 18 | `tests.test_rescript_draft_656._valid_item` | 无 | 删 |
| 19 | `tests.test_rescript_draft_656._legal_item` | 无 | 删 |
| 20 | `tests.test_secret_order_monthly_progress_566._canned_monthly_settlement` | 无 | 删 |
| 21 | `tests.test_structured_decree_contract_1624._month_end_ctx` | 无 | 删 |
| 22 | `tests.test_structured_decree_contract_1624._army_none_legal_item` | 无 | 删 |
| 23 | `tests.test_structured_decree_contract_1624._executing_counts` | 无 | 删 |
| 24 | `tests.test_supervision_625._insert_staged` | 无 | 删 |

非 Python：`_drain`／`_insert_staged` 仅出现在历史 docs／审计 md，**不是代码消费者**，不构成保留依据。

### 同类增补（授权 diff 内扫出的无消费者私有物）

| qualified | 依据 | 处置 |
| --- | --- | --- |
| `tests.test_audience_background._EmptyAgent` | 无 Name/Attribute/Import 消费者 | 删 |
| `tests.test_chat_stream_failpaths_393._FailLeavingAgnoRunAgent` | 同上 | 删 |
| `tests.test_cli_play_turn._noop_atomic` | 同上 | 删 |
| `tests.test_web_chat_serialization_393._SecretOrderAgent` | 同上 | 删 |
| 级联：`_wait_for_pending_writes_to_drain`、`_CannedExtractor`、`_BoomExtractor`、`_CannedMinisterAgent`、`_resolve_decisions_via_stream`、`_choices_from_decisions`、`_army_single_bad_item` | 删上列后二次扫描仍无消费者 | 删 |

## 根因与修法

### DRY-C1／D1

根因：同一结算结果规则两份权威实现。  
修法：`play_turn` 收拢为单一 `if action in ("skip", "issue")`；仅在 `session.advance_without_decree()`／`session.resolve_turn()` 处分派。不新增 helper／路由器／状态机制。  
修后：`HAS_COMBINED True`；`WRITE_GATE_CALLS=1`、`AWAITING_CHECKS=1`、`ADVANCE_CALLS=1`、`RESOLVE_CALLS=1`。

### TEST-C1／T1

根因：旧入口专属测试与无消费者私有支持物续命；`docs/reports/1891-inflight-test-readers.md` 曾以「R2 边界」排除三案——**该排除错误，已在历史文件内撤回说明，文件本身保留**。  
修法：先红取证 → 删三案 + `_stub_game` + 庭列 24 + 同类／级联孤岛；Ruff 清理触及文件 F401。不恢复 `_require_active_minister`，不迁旧证明入夹具，不另造永久缺席自证测试。

## 删除闭包表

| 类别 | 精确删项 |
| --- | --- |
| 退役专属测试 | `test_vassal_prince_chat_rejected`；`test_active_consort_chat_not_rejected`；`test_require_active_minister_uses_can_summon_reason` |
| 专属支持物 | `tests.test_web_court_visibility._stub_game` |
| 庭列 24 | 上表 1–24 全部 |
| 同类／级联 | `_EmptyAgent`、`_FailLeavingAgnoRunAgent`、`_noop_atomic`、`_SecretOrderAgent`、`_wait_for_pending_writes_to_drain`、`_CannedExtractor`、`_BoomExtractor`、`_CannedMinisterAgent`、`_resolve_decisions_via_stream`、`_choices_from_decisions`、`_army_single_bad_item` |
| 闲置 import | `contextmanager`（cli_play_turn）；以及 ruff F401 清掉的 wait_until／json／STANCE_KEY 等（仅触及存活文件） |

## KEEP（注册／消费者保留依据）

| qualified | 保留依据 |
| --- | --- |
| `tests.test_web_court_visibility.test_zongfan_cannot_be_summoned_via_can_summon` | 现役 `GameSession.can_summon` 有效负向契约 |
| `tests.test_web_court_visibility._bare_session` | 同文件现役 can_summon 相关案仍 Name 调用 |
| `tests.test_web_court_visibility._materialized_prince` | 同文件其它可见性案仍调用 |
| `tests.test_mutiny_third_strike_318._simulator_army_dicts` | **不在** `10e64fbef..HEAD` 授权组合 diff；越权不删（即使本仓亦无消费者） |
| 现役生产 `session.can_summon`／场景入口 `SCENE_CHAT_SPEAKER` | 真实消费者；非旧专属测试 |

修后扫描：`STILL_DEFINED []`（庭列 24+点名专属）；`REMAINING_DIFF_PRIVATE_UNCONSUMED 0`。

## 旧范围排除错误撤回

`docs/reports/1891-inflight-test-readers.md` 保留全文；文首已追加撤回注记：不得以「非等待老资格 gate／R2」豁免 `_require_active_minister` 专属测试清退义务。正式处置以本回执为准。

## 验证（实际时长；失败史诚实）

环境共性：七变量 BIN=/usr/bin/false；`MING_SIM_USER_DATA_DIR` 与 `--basetemp` 均为 `$TMPROOT` 下新临时目录；`-p no:cacheprovider`；未跑全量／真实宿主／网络模型。

| 步骤 | 输出 | 墙钟／pytest 时长 | 日志 |
| --- | --- | --- | --- |
| 旧三案红取证 | `3 failed in 0.82s`（AttributeError×3） | time 1.330s | `$TMPROOT/red-three.log` |
| 大文件 collect-only（pihong／decree 等） | `249 tests collected in 1.00s` | time 1.502s | `$TMPROOT/logs/collect-large.log` |
| 聚焦契约（触及模块；**不作全仓**） | `164 passed, 1 skipped, 1 warning in 4.51s` | time 5.070s | `$TMPROOT/logs/focus-main.log` |
| 已删选择器 collect | `ERROR: not found`×3；`no tests collected in 0.58s` | time 1.035s | `$TMPROOT/logs/collect-deleted.log` |
| Ruff 0.11.2 `py313` F401／F821（触及存活 `.py`） | 先 10 F401 → `--fix` 后 `All checks passed!` | fix 0.009s；after 0.009s | `$TMPROOT/ruff/` |
| 符号代码面扫描 | 生产／测试 `.py` 无 `_stub_game` 定义／调用；`_require_active_minister` 仅剩注释／回执说明 | — | `$TMPROOT/logs/symbol-absence-code.log` |

**不冒称 typecheck。** DRY 非功能故障，未造变异证明。  
**不以符号缺席永久测试自证**——闭包依据为 AST 消费者索引 + 旧三案红取证 + 现役 KEEP 案绿。

Advisor 只读方向此前 PASS，非正式庭审；本回执为施工交付。

## 提交约束声明

本轮仅 forward `ak-roles:` 提交；不 amend／stash／reset／checkout 覆盖／rebase／squash／push／PR；不改宪法／Soul／宿主配置／席位表。
