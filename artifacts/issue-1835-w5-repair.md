# #1835 w5 修内司回执（F6 质量复检·收尾）

分支：`ak-roles/issue-1835-w5`
对比基线：`4b74f00cc`；裸 int 误改提交：`d4a47f6db`
**stash 违规仍留档**：第一劳动调用曾 `stash push`/`apply`/`drop`（见 disposition）；后续轮次未再 stash。
本报告随本轮新提交落账；无 push / amend。

取证脚本指针（不入库大 JSON）：
- `artifacts/issue-1835-w5-mutation-probes.py`
- `artifacts/issue-1835-w5-ast-audit.py`
已删冗余：`mutation-probes.json` / `failed-test-baseline.json` / `ast-audit.json` / `rejudge.json`（缺文件非 blocker）。

---

## 实测命令（每次显式七变量）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1835-w5

MING_SIM_AGY_BIN=/usr/bin/false \
MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false \
MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false \
MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
/usr/bin/time -p /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  /Users/akagilnc/WorkSpace/Ming_LLM-1835-w5/artifacts/issue-1835-w5-mutation-probes.py

MING_SIM_AGY_BIN=/usr/bin/false \
MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false \
MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false \
MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
/usr/bin/time -p /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -p no:cacheprovider -q --tb=line \
  tests/test_execution_joint_liability_565.py \
  tests/test_decree_commitment_creation_136.py \
  tests/test_decree_dossiers_571.py \
  tests/test_commitment_display_348.py \
  tests/test_affairs_1831.py \
  tests/test_settlement_fixed_point_1835.py \
  tests/test_declaration_dispatch_1835.py \
  tests/test_section_fiscal_rejections.py \
  tests/test_credit_events_628.py \
  tests/test_issue_entities.py \
  tests/test_grant_reconciliation_567.py \
  tests/test_decree_commitment_settlement_229.py \
  tests/test_month_chain_1847.py \
  tests/test_new_issues_section_rejections.py \
  tests/test_secret_order_payoff_1504.py \
  tests/test_relation_seed_638.py \
  tests/test_qa_h1_seed_data.py \
  tests/test_faction_leverage_9.py \
  tests/test_population_transfers_649.py \
  tests/test_covert_levy_651.py \
  tests/test_rescript_draft_656.py \
  tests/test_rescript_choices_563.py \
  tests/test_world_materials_1834.py \
  tests/test_material_directory_1830.py
```

---

## d4a47f6db 裸 int 来源成员表（全量·按来源分流）

谓词：值来自 **LLM 本轮输入** vs **持久/内部已落账** vs **batch validated / server persisted option**；「既有 catch」= 真实调用链能否把异常变成逐项拒收 / §B.1 整批回滚。

| # | 站点 | 来源 | d4a 行为 | 既有 catch | 本轮处置 |
|---|---|---|---|---|---|
| 1 | `stage_punishment_candidate` `issue_id` | LLM 声明 | 裸 `int` | dispatch 只捕 ValidationError → **不能** | → ValidationError；dispatch 捕 |
| 2 | 同函数 `amount` | LLM 声明 | 裸 `int(amount or 0)` | 同上 | 同上 |
| 3 | `_assignment_absolute_end_turn` | LLM 声明 | 裸 `int` | 裸 VE **不能** | → ValidationError |
| 4 | `_parse_revoke_decree_target` `raw` | LLM 声明 | 裸 `int` | 同上 | → ValidationError |
| 5 | 同函数 `origin` suffix | **持久** `origin_ref` | 裸 `int` | 持久坏应上抛 | **维持上抛** |
| 6 | `_resolve_unique_active_authority` `authority_id` | LLM 声明 | 裸 `int` | 应收 ValidationError | → ValidationError |
| 7 | 同函数 `effective_turn` 等 | **持久** | 裸 `int` | 上抛 | **维持上抛** |
| 8 | `stage_*` `source_chat_turn_id` | 内部召对 id | 裸 `int(... or 0)` | 非 LLM 票面 | 维持 |
| 9 | `stage_referral` `deadline_months` | LLM 声明 | 裸 `int` | 应收 ValidationError | → ValidationError |
| 10 | `cli_backend._extract_secret_order` | LLM 抽取 | 裸 `int` | 无生产逐项接住（前缀分派已退役） | 脏→`DeclarationDataError`=抽取失败 |
| 11–15 | `db._normalize` 收权/撤回/罚俸/军令/下议 | LLM→normalize | 裸 `strict_int` | ensure 捕 DataError → **能** | → `DeclarationDataError` |
| 16 | `db.add_dossier_links` | 确认关联/程序写 | 裸 `strict_int` | 函数内拒收 | 坏 shape→同拒收 |
| 17–18 | dossier apply / origin / deadline | **持久** | 裸 `int`/`strict_int` | 上抛 | **维持上抛** |
| 19 | `commitment_display.origin_turn` | **持久** | 裸 `int` | 上抛 | **维持上抛** |
| 20 | `breach_plea` | **持久** | 裸 `int` | 上抛 | **维持** |
| 21 | `covert_progress` / `materials` | 混 | 已分 | 已分 | **维持** |
| 22 | `db` new_armies firearm/cannon/arrears | LLM `new_armies` | 去 except→0 | **上游 `dirty_field` 已拒收**；转换时坏值=验证不变量失败 | **维持**：不写「LLM 在场坏上抛」 |
| 23 | `db` faction mid | LLM `faction_delta` | 裸 `int` | **已有 reject**：`faction_delta「…」增量非整数` → `invalid_enum` | **维持**（具体拒收已在） |
| 24 | `rescript_actions` military due/months | **batch validated / server persisted option**（§B.1） | 裸 `int` | §B.1 VE→atomic 整批回滚 | 删无分流价值的 try/re-raise；保留缺席/`§B.1` |
| 25 | 同文件罚俸/`amount` | 同上权威 option | 裸 `int` | 同上 §B.1 | 同上；**不算当轮 LLM** |
| 26 | 同文件 mapped 后 `due_turn` | 已 normalize | 裸 `int` | 内层已 int | 维持 |
| 27 | `rescript_draft` forbid_positive `amount` | LLM 层 A | 裸 `int` | 外层漏捕裸 VE | → `_fail` |
| 28 | `cli` affair draft | LLM | 坏声明上抛 | 有意 | 维持 |

### `_has_stop_condition` / 写端

- 写端：空白不当事内容存；dict→`safe_json_dumps`。
- 读端：`{[` 形损坏→上抛；legacy 散文→False（散文门由 resolve 承接）。
- 催办 `deadline_months`：曾 `except→1` → 本轮 `invalid_shape`。

---

## 实测结果

### 本席独立 24 文件复验（七变量）

`1 failed, 676 passed in 21.22s`（`real 21.86`）

剩红：`test_commitment_progress_skips_non_numeric_gate_values`（坏门值上抛；不装回跳过/默认化；#1812 不挡）。

最后删去无效 try/re-raise 后触及面的独立聚焦：
```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false MING_SIM_PI_BIN=/usr/bin/false /usr/bin/time -p /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -p no:cacheprovider -q --tb=line tests/test_dossier_links_559.py tests/test_new_issues_section_rejections.py tests/test_declaration_dispatch_1835.py tests/test_rescript_draft_656.py tests/test_rescript_choices_563.py
```
结果：`177 passed in 2.66s`，`real 3.08 / user 1.93 / sys 0.56`。未跑全量。

### 变异探针（七变量）

本席实跑 `real 1.87s`；补 stop 入口变异后本席复验 `real 2.42s / user 1.44 / sys 0.71`。结构摘录：

| 探针 | 结果 |
|---|---|
| 持久坏 `origin_turn` | `old_forge_ok_current_raises=true` |
| LLM amount=`若干` / end=`明年` | `invalid_shape`；合法 applied |
| 装回 d4a `stage_*` | `old_red_current_green=true` |
| whitespace resolve→stop 当前 | `resolved` bar=100 |
| **d4a `_has_stop_condition`+写端旧 insert** | **`old_red_current_green=true`**（旧 JSONDecodeError / 当前绿） |
| 持久读 VE 故障注入 | **不被物化宽 catch 吸收**（`inject_not_swallowed_by_wide_catch=true`） |
| 损坏 JSON stop | `ValueError:持久停止条件 JSON 损坏` |
| F5 / F12 | `old_red_current_green` / `old_diverge_current_same` 均 true |

---

## 类结清

| 类 | 状态 |
|---|---|
| F1/F5/F10/F12 | 维持前结清（见 `4b74f00cc` / `d4a47f6db` 已结引用） |
| F6 | **结清**（来源分流；真实入口旧红/当前绿；持久故障仍响亮） |
