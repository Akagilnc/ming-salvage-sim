# #1847 修内司 w15 — 类1 假 KEEP 纠正（非流式口 + migrate/backfill）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- 分支：`ak-roles/1847-fixer-w13-n11-n14-legacy-idle`
- 上一交卷：`3015b9ca5`（不 amend）
- 生产删除 commit：`986d9e3fc3e649c125d537d101e1642e4fd88ddb`
- 本轮自查纠正 commit：见文末 SHA（不 amend；不另造证据框架）
- 任务依据：PI session continue（类1 未清尽假 KEEP）；fix-packet 末份类别边界不变
- 类2：本轮无新增 finding，不另扩

## 自查纠正（本轮）

### 撤回「变异真跑」假称谓

原 `evidence/1847-w13-scans/mutation-probe-w15.out` 仅对 `hasattr` / 路由表 / inventory 做源码存在性 assert，**不是**旧生产逻辑真实入口行为变异。`MUTATION_PROBE_DONE PASS` **不得**洗成行为证据。该称谓与该 out 的 PASS 语义一并撤回。

### 测试 diff 自查（SSE 正文 / 锁措辞 / mock / 放松断言）

| 文件 | 问题 | 纠正 |
|---|---|---|
| `test_chat_stream_failpaths_393.py` | 钉 `message == CLI_RUNNER_PLAYER_MESSAGE`（SSE 自由正文） | 只留 `event=error` / `code` / `provider_message` 结构字段 |
| `test_issue_decree_token_1277.py` | 钉 `report` 全文、`message` 非空 | `report` 仅类型；去掉 message 措辞钉；保留 `status_code=409` / `turn` |
| `test_month_open_snapshot_1234.py` | `decisions` 仅 `isinstance(list)` 过松；stream 无 `awaiting_decision` 键 | `len(decisions)==1` 作结构等价钉 |
| `test_enter_settlement_period_1235.py` | `"error" in body` 过松；删非流式后丢 phase 钉 | 钉 `event: error`；恢复 phase 非 settling/awaiting |
| `test_error_pack.py` | 既有 `_StubGame` 替 resolve 边界（迁 stream 前即有） | 保留；只钉 `stage`/`error_pack_path`/`turn`；报告标明非整链真 game |
| `test_month_loop_tracer_1468.py` / `test_player_payload_1022.py` | 已走真 stream 结构字段 | 无本轮再改 |

未改 ADR/治理；未新增永久证明测试；不扩证据框架。

## 纠正 KEEP（上轮不实分类）

| 原 KEEP | 纠正 | 处置 |
|---|---|---|
| `KEEP_ACTIVE_HTTP_ENTRY` 非流式 `POST /api/decree/issue` | 难迁≠保留 | **FIX_DELETE**：删 `web_app.api_issue_decree`；测改走 `/api/decree/issue/stream`；无新适配层 |
| `KEEP_ACTIVE_CONTENT_SYNC` `_migrate_character_identity_seed` / `_backfill_bandit_power_split` | 非新档接续/非账本 | **FIX_DELETE**：删函数 + `init_schema` 调用 + `person_write_inventory` 两条；删 `test_bandit_power_content_sync_*`；**保留** `seed_static_data` 与 `test_seed_splits_*` |

## 枚举命令（可回放）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1847-w5
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD
bash evidence/1847-w13-scans/enum_commands.sh
# 成员表：evidence/1847-w13-scans/members_classified.tsv
# 复扫：evidence/1847-w13-scans/enum_post_w15.out
```

## 成员处置（本轮触及）

**类1**

| 成员 | 处置 |
|---|---|
| `POST /api/decree/issue` 非流式 | FIX_DELETE；消费者迁 stream：`test_enter_settlement_period_1235`、`test_month_loop_tracer_1468`、`test_chat_stream_failpaths_393`；复扫同删口另迁：`test_error_pack`、`test_issue_decree_token_1277`、`test_month_open_snapshot_1234`、`test_player_payload_1022`（去同步对照） |
| `_migrate_character_identity_seed` / `_backfill_bandit_power_split` | FIX_DELETE + inventory 两条 |
| `test_bandit_power_content_sync_*` | FIX_DELETE_TEST |
| `seed_static_data` + `test_seed_splits_*` | KEEP_NEW_SEED |
| 其余既有 KEEP（clamp / read_default / empire / transport / expected_turn / 注释） | 复扫职责未变；非本轮假 KEEP |

**类2**：复扫 `B_hits=0`；不扩。

## 聚焦实测（可回放；七 false 前缀）

七变量前缀真源：`evidence/1847-w15-env-prefix.txt`（`MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false`）。

### 触达切片（原 w15；含 month_chain/fiscal/tenure，255 passed）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1847-w5
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD
BASETEMP=$(mktemp -d /tmp/1847-w15-pytest-XXXXXX)
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q \
  -p no:cacheprovider --basetemp="$BASETEMP" \
  tests/test_bandit_power_model_190.py \
  tests/test_enter_settlement_period_1235.py \
  tests/test_month_loop_tracer_1468.py \
  tests/test_chat_stream_failpaths_393.py \
  tests/test_error_pack.py \
  tests/test_issue_decree_token_1277.py \
  tests/test_month_open_snapshot_1234.py \
  tests/test_player_payload_1022.py \
  tests/test_month_chain_1847.py \
  tests/test_fiscal_substrate_bridge.py \
  tests/test_appointment_tenure_607.py
```

实测（原交卷）：`255 passed, 1 warning in 19.77s` → `evidence/1847-w13-scans/focused-pytest-w15.out`

### 广聚焦（原 w15；本轮自查**不重跑**）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1847-w5
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD
BASETEMP=$(mktemp -d /tmp/1847-w15-pytest-full-XXXXXX)
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q \
  -p no:cacheprovider --basetemp="$BASETEMP" \
  tests/test_month_chain_1847.py \
  tests/test_fiscal_substrate_bridge.py \
  tests/test_surcharge_causal_chain_650.py \
  tests/test_pay_order_override_653.py \
  tests/test_audience_travel_gating_670.py \
  tests/test_session_write_queue_1353.py \
  tests/test_junxin_monthly_tick_314.py \
  tests/test_advance_paths_atomic.py \
  tests/test_state_reload.py \
  tests/test_mutiny_actual_residence_659.py \
  tests/test_mutiny_latch_315.py \
  tests/test_mutiny_progression_316.py \
  tests/test_mutiny_redemption_317.py \
  tests/test_mutiny_third_strike_318.py \
  tests/test_mutiny_noop_whitelist_319.py \
  tests/test_player_army_projection_321.py \
  tests/test_effect_origin_558.py \
  tests/test_qa_c2_phase_settlement_mask_1374.py \
  tests/test_bandit_power_model_190.py \
  tests/test_relation_brew_636.py \
  tests/test_faction_brew_637.py \
  tests/test_enter_settlement_period_1235.py \
  tests/test_month_call_recovery_1846.py \
  tests/test_appointment_tenure_607.py \
  tests/test_structured_decree_contract_1624.py \
  tests/test_audience_background.py \
  tests/test_month_loop_tracer_1468.py \
  tests/test_chat_stream_failpaths_393.py \
  tests/test_error_pack.py \
  tests/test_issue_decree_token_1277.py \
  tests/test_month_open_snapshot_1234.py \
  tests/test_player_payload_1022.py
```

实测（原交卷，不重跑）：`547 passed, 1 warning in 24.00s` → `evidence/1847-w13-scans/focused-pytest-w15-broad.out`

### 自查纠正后触达切片（本轮重跑；仅改断言的 8 文件）

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1847-w5
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD
BASETEMP=$(mktemp -d /tmp/1847-w15-corr-pytest-XXXXXX)
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest -q \
  -p no:cacheprovider --basetemp="$BASETEMP" \
  tests/test_bandit_power_model_190.py \
  tests/test_enter_settlement_period_1235.py \
  tests/test_month_loop_tracer_1468.py \
  tests/test_chat_stream_failpaths_393.py \
  tests/test_error_pack.py \
  tests/test_issue_decree_token_1277.py \
  tests/test_month_open_snapshot_1234.py \
  tests/test_player_payload_1022.py
```

实测：`59 passed, 1 warning in 2.92s`（`/usr/bin/time -p` real 3.70s）→ `evidence/1847-w13-scans/focused-pytest-w15-corr.out`

## 退休路径删除取证（非「变异真跑」）

非流式口删除：诚实作引用与路由结构取证（装回旧口不会使已迁 stream 案变红，故**不伪造变异**）。

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1847-w5
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD
git show 3015b9ca5:web_app.py | rg -n '@app.post\("/api/decree/issue"\)|def api_issue_decree\b|def api_issue_decree_stream'
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python - <<'PY'
import web_app
from ming_sim.db import GameDB
from ming_sim.person_write_inventory import PERSON_WRITE_POINT_INVENTORY
routes = {getattr(r, "path", None) for r in web_app.app.routes}
print("has_api_issue_decree", hasattr(web_app, "api_issue_decree"))
print("route_/api/decree/issue", "/api/decree/issue" in routes)
print("route_/api/decree/issue/stream", "/api/decree/issue/stream" in routes)
print("has__migrate", hasattr(GameDB, "_migrate_character_identity_seed"))
print("has__backfill", hasattr(GameDB, "_backfill_bandit_power_split"))
locs = [e["location"] for e in PERSON_WRITE_POINT_INVENTORY]
print("inventory_seed", any("seed_static_data" in x for x in locs))
print("RETIRE_STRUCTURE_DONE")
PY
```

输出：`evidence/1847-w13-scans/retire-structure-w15-corr.out`
（parent 有 `@app.post("/api/decree/issue")`；HEAD：`has_api_issue_decree False`，stream True；migrate/backfill False；seed inventory 保留）

原 `mutation-probe-w15.out` 保留作撤回对照，**不作行为 PASS**。

## 临时旧逻辑真实入口变异（content_sync；非永久测试）

复用已删 `test_bandit_power_content_sync_*` 原文（parent `3015b9ca5`）经真实 `db.init_schema()` 入口；进程内临时装回旧方法做绿侧。临时文件跑完即删，未入库。

```bash
# 见完整命令输出：evidence/1847-w13-scans/temp-mutation-content-sync-w15-corr.out
# RED（HEAD）：2 failed in 0.63s（real 1.02s）— init_schema 不再补回被删 powers 行
# GREEN（process-local restore parent methods + init_schema 调用）：2 passed in 0.61s（real 1.04s）
# KEEP seed 既有真入口：1 passed in 0.60s（real 1.00s）
```

非流式口：不伪造变异（见上节结构取证）。

## 复扫

- 类2 idle+called_dup：**0**
- 类1 目标：非流式口、两 migrate/backfill、content_sync 专案：**已删尽**
- 机械 A_hits 余注释/现役 KEEP（transport heal、empire、注释「已退役」等），见 TSV

## 自查二连 done

- 同类：假 KEEP 按职责删；难迁不作保留；迁测复用真 stream，无适配层；seed 新档播种保留；假「变异真跑」撤回；断言收束到 stream 外部结构字段
- 引入：纠正后触达 59 绿；content_sync 临时红绿成立；路由结构取证诚实；无 stash/amend/rewrite/push/PR；未改 ADR/治理；未迁旧档；无识别拒收；无新永久证明测试；不另造证据框架

## Commit SHA

生产删除：`986d9e3fc3e649c125d537d101e1642e4fd88ddb`
本轮自查纠正：b2fef28edf911d6a87d6cae2f9943d2fcbe28d71
