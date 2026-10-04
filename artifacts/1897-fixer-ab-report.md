# #1897 修内司 continue 类 A/B 回执

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1897-w5`
- 分支：`ak-roles/issue-1897-r1-r4-fixer-20261005-053204`
- 施工前 HEAD：`9dc3823b3cda09e71d2a71286e048752cd0000ff`
- 本轮施工后 HEAD：`c8992d3de942b9def0e290f5bc56a00a3bcd442f`
- 源卷最新用户 JSON：`~/.ak-roles/books/Ming_LLM/1897/runs/01a1089b-50c9-7dac-ab41-8ba86b05e2c6@fixer/session/session.jsonl` L51（`role=user`，正文即 continue 判词）；同文亦在 `run-state.json` → `currentCourt.summons.instruction`
- 原修理回执：`artifacts/1897-fixer-r1-r4-report.md`
- 状态：本轮新独立 `ak-roles:` 提交；**未 push、未开 PR、未 amend、未 stash**
- 已知基线 FOREIGN KEY 缺口（`test_appointment_and_relief_through_scene_chat_then_close_and_settle`）**不本片接回**，不洗绿
- R2（P1）按末判词 **不再另议**

## 末份 continue 判词（原样，不摘要）

源：session L51 / `currentCourt.summons.instruction`：

```json
{
  "status": "continue",
  "reason": "R2 修理对表成立，R1/R3 主体清退属实，但仍有两类未结：旧账轨附属物清退不完整，以及 R4 误删了闸类负向契约测试。",
  "findings": "[{\"class\":\"A（P2，R1/R3 同类：旧密令正文账轨附属物未清退净）\",\"phenomenon\":\"secret_orders.sim_note 列已无任何写入者，却仍被保留、读取、透传到前端并被测试钉住。\",\"cause\":\"R1 删除 _append_secret_order_line 及 text_log_json 账族后，sim_note 只剩读口。枚举谓词只盯 text_log_json 和一串 helper 名，没有按『旧正文账轨的列与读口』这一类定义去扫，所以漏了这一列。\",\"evidence\":[\"写入端：INSERT INTO secret_orders（db.py:21840）不含 sim_note；全仓 UPDATE secret_orders 语句也都不写它；update_secret_order_sim_note 的 docstring 明写『不写 secret_orders.sim_note』（db.py:22266）。\",\"残留端：db.py:1486 建表列、db.py:2329 ensure_column、db.py:22082 与 db.py:22408 读出 sim_note（恒为 ''）、web/src/components/secretOrders.tsx:157 渲染『月度动向』块、web/src/types.ts:622。\",\"测试钉住：tests/test_decree_dossiers_571.py:1357，tests/test_secret_order_section_rejections.py:77、:101。三处断言『sim_note == \"\"』，是对死列的断言。\"],\"law\":\"#1897 目的第2项『删去重复可写真源』，#1812 验收第1项旧路清退，全局第12、14条。\",\"boundary\":\"密令记录列／读口／序列化／前端展示／测试里，旧正文账轨（result+sim_note 原双列）的全部残留成员。result 列仍由 db.py:22118 的结案路径写入，属现役，保留。\",\"disposition\":\"按类机械枚举 sim_note 在 ming_sim、web、tests 中的列、读口、前端字段与断言，全部清退。注意 month_chain.py 的 sim_note 是 LLM 更新项的键，不是这一列，不在此类。\"},{\"class\":\"B（P2，R4 同类：把闸类负向契约当 helper-only 误删）\",\"phenomenon\":\"生产闸 build_covert_task_contract 的结构化负向契约，在 R4 删测后只剩零散覆盖。\",\"cause\":\"R4 把『直接调用 helper』一律当 helper-only 删除，没有区分『helper-only 自洽测试』和『生产闸的负向案』。\",\"evidence\":[\"已删：test_confirmation_rejects_incomplete_delivery_identity（7 个参数化负例，覆盖 covert_progress.py:468-478 的 identity 缺失拒收）。\",\"已删：test_task_specific_contract_rejects_tags_without_explicit_fields（tags 不得代替显式字段）。\",\"该闸是现役生产入口，被 cli_backend.py:4230 和 declaration_dispatch.py:1274 调用。\",\"现存的 test_create_secret_order_rejects_missing_contract 只覆盖『整份合同缺失』。我搜过 tests，没有任何测试再覆盖 identity 缺失拒收与 tags 代替显式字段的拒收路径。\",\"decide_secret_order_settlement 的零目标不算交付等负向边界同样需要核对：现役结案路径 covert_progress.py:2101 仍在调用，该函数的 helper 测试已全删，要看真实 settle 入口是否仍断了这条边界。\"],\"law\":\"全局第13条第④尺『闸类契约的负向案不可删』；派单 R4 边界『保留必要的真实入口结构化负向契约』；《测试对行为负责》。\",\"boundary\":\"授权改动对应测试体系里，所有被删的闸类负向案（对生产闸的结构化拒收断言）。\",\"disposition\":\"按类逐项核对被删测试：属生产闸负向案的恢复（可并入现有 create/settle 真入口测试，不新建平行夹具）；确属重复或自由文本的维持删除。\"}]",
  "evidence": [
    "复核 HEAD=9dc3823b3，工作树干净。",
    "聚焦测试：对 R1–R4 触及的 19 个测试文件重跑，569 passed、1 failed。唯一失败是 tests/test_audience_translate_1837.py::test_appointment_and_relief_through_scene_chat_then_close_and_settle，原因是 FOREIGN KEY（db.py:18420）。",
    "基线对照：我在 64b899a0e 的临时 worktree 上单跑该用例，同样失败，非本轮回归。临时 worktree 已用 git worktree remove 清理。",
    "测试均前缀七个 MING_SIM_*_BIN=/usr/bin/false，未跑全量。",
    "R1：全仓 rg text_log_json 及相关 helper 名，仅剩历史文档与 artifacts 命中，生产代码已清；materials.py 改读 dossier_progress，行为接通。",
    "R2：seed_guilt_counts_as_debt 只认 severity∈{轻,中,重}，解析失败和非对象不造罪，与判词 R2 一致。真入口负向测试 test_create_secret_order_fact_lanes_follow_structured_severity_only 走 create_secret_order→live_investigation_fact_keys→案卷 lanes，测的是结构化字段，不盯文。",
    "R3：被删函数 target_progress_units、contract_axes_direction、build_secret_covert_effect_briefs、read_substantiated_legal_reason_code、_substantiate_lane、advance_investigation_lanes、mark_investigation_fact_used、parse_covert_exec_selections、terminal_report_facade、latest_monthly_memorial 在代码和 .py/.md 中无残余引用，仅旧证据文档提及；pyflakes 无 undefined/unused 报告。",
    "本轮未对 diff 做逐条自由文本断言审计，只抽查了 payoff_1504 与 monthly_progress_566 两份 diff。类 B 的修复需顺带复扫其余 17 个文件。"
  ],
  "note": "R2（P1）修理成立，不再另议。R1/R3 的主体清退成立，缺口只在类 A 的 sim_note 死列。R4 的盯文清理方向正确，缺口只在类 B 把闸类负向案一并删除。修理 diff 同尺复核：不得靠加新机制收场，类 A 以删除为主，类 B 并入现有真入口测试。"
}
```

## 类 A：`secret_orders.sim_note` 死列附属物

### 可运行枚举命令

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1897-w5
rg -n --no-heading -g '!artifacts/**' -g '!*.md' 'sim_note' ming_sim web tests scripts content
rg -n --no-heading -g '*.{py,ts,tsx}' \
  'sim_note TEXT|ensure_column\([^)]*sim_note|r\["sim_note"\]|order\.sim_note|sim_note: string|\[.sim_note.\]\s*==' \
  ming_sim web tests
# 分类表（本轮实测写入 /tmp/1897-ab-enum/A-member-table.txt）
python3 /tmp/1897-ab-enum/classify_sim_note.py  # 逻辑见施工过程：按 COLUMN_* / KEEP_LLM_* / KEEP_ACTUAL_RAIL_WRITER 分类
```

复扫（清退后）：

```bash
rg -n --no-heading -g '*.{py,ts,tsx}' \
  'sim_note TEXT|ensure_column\([^)]*sim_note|\[.sim_note.\]\s*==|order\.sim_note|sim_note: string|r\["sim_note"\]' \
  ming_sim web tests
# → CLEARED
```

### 全成员表与处置

| 成员 | 位置 | 处置 | 依据 |
|---|---|---|---|
| CREATE TABLE 列 `sim_note TEXT` | `ming_sim/db.py` schema | **删** | 死列无写者 |
| `ensure_column(..., "sim_note", ...)` + 旧注释 | `db.py` migrate | **删** | 死列附属 |
| `list_secret_orders` 序列化 `"sim_note"` | `db.py` | **删** | 读口恒空 |
| `get_secret_order` 序列化 `"sim_note"` | `db.py` | **删** | 读口恒空 |
| docstring「禁与 …/sim_note 混写」「不写 secret_orders.sim_note」 | `db.py` | **改**（去死列表述） | 文档附属 |
| `SecretOrder.sim_note` 类型 | `web/src/types.ts` | **删** | 前端字段 |
| 「月度动向」`order.sim_note` 块 | `web/src/components/secretOrders.tsx` | **删** | 前端展示 |
| `assert …["sim_note"] == ""` ×3 | `tests/test_decree_dossiers_571.py`、`tests/test_secret_order_section_rejections.py` | **删钉**；改断言实况轨/案卷状态 | 死列测试钉 |

### 保留（非死列）

| 成员 | 位置 | 保留依据 |
|---|---|---|
| `result` 列 + `close_secret_order` 写口 + list/get `"result"` | `db.py` | 现役结案列（判词明示） |
| month_chain LLM 更新项 `"sim_note"` 键 | `ming_sim/month_chain.py` | **不是** `secret_orders.sim_note` 列 |
| `issues.py` secret_order_updates 读 `sim_note` → `update_secret_order_sim_note` / disclosure | `ming_sim/issues.py` | LLM 更新项键 → 实况轨/披露 |
| `simulation.py` 别名 `sim_note`/`推演备注` | `ming_sim/simulation.py` | LLM 字段别名 |
| `update_secret_order_sim_note` / `_update_…_in_transaction` | `db.py` | 写 `dossier_actual_progress.note`，不写死列 |
| 测试里 `secret_order_updates`/`disclosed` 载荷的 `sim_note` 键 | isolation/month_chain/section/566 等 | LLM 更新项，非列钉 |

## 类 B：被删测试审计 `64b899a0e..9dc3823b3`

### 可运行枚举命令

```bash
git diff --diff-filter=D --name-only 64b899a0e 9dc3823b3 -- tests/
git diff -U0 64b899a0e 9dc3823b3 -- tests/ | rg '^[-]def test_'
git diff -U3 64b899a0e 9dc3823b3 -- tests/ | rg -n 'def test_|CovertContractError|build_covert_task_contract|decide_secret_order_settlement'
```

### 逐个删除案审计

| 被删测试 | 原文件 | 审计结论 | 本轮处置 |
|---|---|---|---|
| `test_confirmation_rejects_incomplete_delivery_identity`（7 参） | `test_secret_order_payoff_1504.py` | **生产闸负向**（identity 缺失→`CovertContractError`）；误当 helper-only | **恢复**：并入 `test_create_secret_order_rejects_incomplete_delivery_identity`（`create_secret_order` 真入口） |
| `test_task_specific_contract_rejects_tags_without_explicit_fields` | 同上 | **生产闸负向**（tags 不能代显式字段） | **恢复**：`test_create_secret_order_rejects_tags_without_explicit_fields` |
| `test_zero_target_is_not_delivered` | `test_secret_order_update.py` / payoff 历史 | helper 直调 `decide_*`；settle 唯一调用点在 `require_covert_task_contract`/`coerce` 之后，qty≤0 在 coerce 即拒，**decide 零目标分支经 settle 不可达** | **恢复为真入口**：`test_create_and_settle_reject_zero_target_not_delivered`（create 拒 target=0；案卷置零后 settle 响亮失败且密令保持 active，不静默 done） |
| `test_decide_settlement_delivery_gap_bidirectional` | payoff | helper-only；已有 settle done/gap 真入口覆盖 | **维持删除** |
| `test_task_specific_contract_from_explicit_fields_not_tags` | payoff | helper 正向；`test_confirm_persists_task_specific_contract_absent_before` 已覆盖 | **维持删除** |
| `test_seed_guilt_structured_clean_vs_debt` | payoff | helper-only；R2 已有 create 真入口负向 | **维持删除** |
| `test_non_investigation_contract_keeps_its_delivery_account` | payoff | helper/重复 | **维持删除** |
| `test_actual_units_share_originated_quantity` | payoff | helper-only | **维持删除** |
| `test_target_units_min_one_when_due` | payoff | helper-only | **维持删除** |
| `test_emperor_private_payload_preserves_monthly_report` | `test_secret_order_monthly_progress_566.py` | 自由文本/非闸类负向 | **维持删除** |

其余 19 文件 diff 中的行级删改（盯文等值、自由文本断言）按 R4 已结方向 **维持删除**，不回滚。

### 测试必要契约最小成本

- 不新建平行夹具文件；全部挂在既有 `test_secret_order_payoff_1504.py` create/settle 邻域
- identity 7 例用 `@pytest.mark.parametrize` 一条 tracer
- tags / zero-target 各一条真入口负向
- 不恢复 helper 直调 `decide_secret_order_settlement` / `build_covert_task_contract` 的平行自洽测

## 聚焦测试

环境前缀（七 false + `PYTHONDONTWRITEBYTECODE=1`），未跑全量。

```bash
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
  ../Ming_LLM/.venv/bin/python -m pytest -q \
  tests/test_secret_order_payoff_1504.py::test_create_secret_order_rejects_missing_contract \
  tests/test_secret_order_payoff_1504.py::test_create_secret_order_rejects_tags_without_explicit_fields \
  tests/test_secret_order_payoff_1504.py::test_create_secret_order_rejects_incomplete_delivery_identity \
  tests/test_secret_order_payoff_1504.py::test_create_and_settle_reject_zero_target_not_delivered \
  tests/test_secret_order_section_rejections.py \
  tests/test_decree_dossiers_571.py::test_secret_order_progress_rolls_back_both_axes_in_outer_atomic \
  tests/test_secret_order_isolation_883.py \
  tests/test_secret_order_monthly_progress_566.py
# 62 passed in 2.12s  real 2.64s

../Ming_LLM/.venv/bin/python -m pytest -q \
  tests/test_secret_order_payoff_1504.py::test_settle_due_close_follows_surviving_memorial_and_actual \
  tests/test_secret_order_payoff_1504.py::test_settle_due_reads_actual_rail_only_report_does_not_flip_verdict \
  tests/test_secret_order_payoff_1504.py::test_monthly_actual_then_delivered_done \
  tests/test_secret_order_payoff_1504.py::test_gap_after_months_failed \
  tests/test_secret_order_payoff_1504.py::test_confirm_persists_task_specific_contract_absent_before \
  tests/test_month_chain_1847.py -k 'secret_order or sim_note or disclosure'
# 10 passed, 31 deselected in 1.47s  real 1.99s
```

web：本树无本地 `typescript`/`tsc`；`rg sim_note web/src` → CLEARED。

## 自查二连

1. **同类型**：A 按「列/读口/序列化/前端/死列钉」整类清；未误删 month_chain/issues LLM `sim_note` 键与实况轨 writer；`result` 结案列保留。B 只恢复闸类负向，不回滚盯文/helper 重复。
2. **引入 bug**：零目标经 coerce 不可达 decide——改为 create+settle 真入口断言，避免假绿 helper；section/571 去掉死列钉后改盯实况轨回滚。

## HEAD

`c8992d3de942b9def0e290f5bc56a00a3bcd442f`
