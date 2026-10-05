# #1847 修内司 w15 — 类1 假 KEEP 纠正（非流式口 + migrate/backfill）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- 分支：`ak-roles/1847-fixer-w13-n11-n14-legacy-idle`
- 上一交卷：`3015b9ca5`（不 amend）
- 本轮独立 commit：见文末 SHA
- 任务依据：PI session continue（类1 未清尽假 KEEP）；fix-packet 末份类别边界不变
- 类2：本轮无新增 finding，不另扩

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

## 聚焦实测

七变量前缀见 `evidence/1847-w15-env-prefix.txt`。

```bash
# 触达切片
… pytest tests/test_bandit_power_model_190.py tests/test_enter_settlement_period_1235.py \
  tests/test_month_loop_tracer_1468.py tests/test_chat_stream_failpaths_393.py \
  tests/test_error_pack.py tests/test_issue_decree_token_1277.py \
  tests/test_month_open_snapshot_1234.py tests/test_player_payload_1022.py …
# → 255 passed → evidence/1847-w13-scans/focused-pytest-w15.out

# 广聚焦（沿用 w14 清单 + 本轮触达）
# → 547 passed → evidence/1847-w13-scans/focused-pytest-w15-broad.out
```

## 变异真跑

```bash
python - <<'PY'  # evidence/1847-w13-scans/mutation-probe-w15.out
# assert no api_issue_decree / route /migrate/backfill; seed inventory kept
PY
```

`MUTATION_PROBE_DONE PASS`

## 复扫

- 类2 idle+called_dup：**0**
- 类1 目标：非流式口、两 migrate/backfill、content_sync 专案：**已删尽**
- 机械 A_hits 余注释/现役 KEEP（transport heal、empire、注释「已退役」等），见 TSV

## 自查二连 done

- 同类：假 KEEP 按职责删；难迁不作保留；迁测复用真 stream，无适配层；seed 新档播种保留
- 引入：聚焦 255/547 绿；变异 PASS；无 stash/amend/rewrite/push/PR；未改 ADR/治理；未迁旧档；无识别拒收；无新证明测试

## Commit SHA

（提交后填）
