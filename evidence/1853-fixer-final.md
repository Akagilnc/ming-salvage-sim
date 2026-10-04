# #1853 修内司交卷（J2–J5 复核删简）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1853-w5`
- 分支：`ak-roles/issue-1853-j2-j5-unify`
- 授权：本局「继续修内司 #1853」施工劳务指令
- 判词：末份 `05-1853-judge-acc7a7c6d.json` 未结 **J2–J5**；上轮 `60516a6a3` 的 J5 审计过滤被本轮驳回重做
- **未合入目标分支；不 push / 不开 PR；不 amend**

## 自审

- 上轮 J5 新增 `_is_terminal_business_refusal_action`（逐项扫审计 + `OperationalError` pass）属替代过滤，违反失败诚实；且保留 `failedOnly` 全套旧支线，未清退旧呈现。
- 本轮先全仓枚举 `pending_actions status='failed'` 生产者与真异常传输消费者：真异常留 `pending` 并经原轮/月链 `error_pack` / except 上抛；`failed` 仅终态业务拒收 / 软拒收 / 无效拟旨。
- 故整类删除 failed 计数、`failedOnly` UI、CLI/结算专属 failed 载荷与本轮审计过滤；不增分类账本或兼容 catch。
- J4 dispose 恒 True 简化为 `-> None` 直调；J2 夜卷 `reply_retries` 必有，去掉 `||[]` / optional。
- 净删约 700+ 行；不补核心恢复功能。

---

## 全仓枚举：`status='failed'` 生产者

命令：
```bash
git grep -n -I -E "pending_actions SET status=['\"]failed['\"]" -- ':!archive'
```

| 路径 | 符号 | 行 | 类别 | 处置 |
|---|---|---|---|---|
| `ming_sim/db.py` | `_dispose_pending_action_apply_exception` | 17615 | 案卷关联业务拒收 → 终态 failed | **保留**生产者；删其系统待办呈现 |
| `ming_sim/db.py` | `_dispose_pending_action_apply_exception` | 17621 | typed `PendingActionRefusal` / `OfficeAppointmentRejection` → 终态 failed | **保留**生产者与拒收审计 |
| `ming_sim/db.py` | `commit_pending_actions` | 18118 | 拟旨 `classification=="invalid"` → 终态 failed | **保留**（非真异常传输） |
| `ming_sim/db.py` | `commit_pending_actions` | 18172 | `_apply_pending_action` 返 False 软拒收 → 终态 failed | **保留**（非未成故障） |
| `ming_sim/db.py` | `_commit_conversational_draft` | 18264 | 同上软拒收 | **保留** |

真异常路径（对照，不写 failed）：
| 路径 | 符号 | 行为 |
|---|---|---|
| `ming_sim/db.py` | `_dispose_pending_action_apply_exception` 末支 | 留 pending + `raise` |
| `tests/test_audience_commit_failure_1853.py` | `test_secret_order_commit_code_error_is_not_laundered_into_success` | 实测 status=`pending` + `error_pack_path` + 转译重试 |

复扫真异常消费者（原轮/月链上抛，非 failed 行）：
```bash
# 既有入口案（七 false 前缀）
python -m pytest tests/test_audience_commit_failure_1853.py::test_secret_order_commit_code_error_is_not_laundered_into_success -q
# → 1 passed；status=pending，非 failed
```

---

## J5「业务拒收仍被旧支线呈为未处理系统故障」

### 根因（上轮处方错误）
过滤审计 JSON 把拒收从载荷剔除，却保留 `failed_secret_order_count` / `failedOnly` / CLI·结算 `pending_action_failures` 专属传输——旧呈现方向未清退，且 `OperationalError` catch 不诚实。

### 全仓枚举命令（施工前成员）
```bash
git grep -n -I -E \
  'failed_secret_order_count|failedOnly|_is_terminal_business_refusal|_system_secret_order_failure|_print_pending_action_failures|_new_secret_order_failure_payloads|_failed_secret_order_ids|_capture_settlement_failure' \
  -- ':!archive' ':!docs'
```

### 成员表

| 路径 | 符号 | 处置 |
|---|---|---|
| `ming_sim/session.py` | `_is_terminal_business_refusal_action` | **删**（本轮审计过滤） |
| `ming_sim/session.py` | `_system_secret_order_failure_payloads` / `_pending_action_failure_payload` | **删** |
| `web_app.py` | `failed_secret_order_count` 投影 | **删** |
| `web_app.py` | `_failed_secret_order_ids_for_turn` / `_new_secret_order_failure_payloads_for_turn` / `_capture_settlement_failure_snapshot` | **删** |
| `web_app.py` | advance/issue/stream/resolve 附 `pending_action_failures`（源自 failed 行） | **删**专属传输；异常仍经 HTTP/SSE message·abort·error_pack 上抛 |
| `ming_sim/cli/terminal.py` | `_failed_secret_order_ids` / `_new_secret_order_failure_payloads` / `_print_pending_action_failures` 及 skip/issue 调用 | **删** |
| `web/src/components/edictModal.tsx` | `failedOnly` / 退朝确认条 / `onAdvanceWithoutEdict` 页脚支线 | **删** |
| `web/src/styles/edict.css` | `.edict-footer-confirm*` | **删** |
| `web/src/types.ts` | `failed_secret_order_count?` | **删** |
| `ming_sim/db.py` | `_record_typed_business_refusal` 的 setdefault 过滤戳 | **撤**回原「无 item 才写 id」形态（现役审计必要字段保留在 else 分支） |
| `ming_sim/db.py` | `list_failed_secret_order_actions` / `discard_failed_secret_order_intents` | **保留**（清理/查询，非系统待办呈现） |
| `ming_sim/decree.py` | `discard_failed_secret_order_intents` 调用 | **保留** |
| 拒收审计 / 原动作行 / 真异常 raise | — | **保留** |

### 复扫
```bash
git grep -n -I -E \
  'failed_secret_order_count|failedOnly|_is_terminal_business_refusal|_system_secret_order_failure|_print_pending_action_failures|_new_secret_order_failure_payloads|_failed_secret_order_ids|_capture_settlement_failure' \
  -- ':!archive' ':!docs' ':!evidence'
# → EMPTY
```

### 合法保留
- 拒收审计（`rejection_reports` / `decree_dossier_link_rejections`）与原 `pending_actions` 行。
- 真异常：留 pending + 上抛 + `error_pack` / 转译重试（既有入口案绿）。
- `advanceWithoutEdict` API 与结算重试入口仍在（非 failed-only 呈现）。

---

## J2「回话重试存在两份前端权威」

### 枚举
```bash
rg -n 'reply_retries|replyRetries|setReplyRetries' web/ ming_sim/ web_app.py tests/
```

| 路径 | 符号 | 处置 |
|---|---|---|
| `web_app.py` | 夜卷 `reply_retries` | **保留**唯一投影（必有） |
| `web/src/components/chatModal.tsx` | `reply_retries?:` + `\|\| []` | **改**为必有 `reply_retries:`，去掉缺字段兼容 |
| `web/src/useChatActions.ts` | 平行数组 | 上轮已删；本轮维持 |
| 测试夜卷 mock | 缺 `reply_retries` | **补** `reply_retries: []`（契约对齐，非新证明案） |

---

## J3「无消费者预推轮询」

上轮已删 `forecast_inflight` / `has_open_key_prefix`；复扫零命中。本轮无复活。

---

## J4「暂存提交异常分流政策双实现」

| 路径 | 符号 | 处置 |
|---|---|---|
| `ming_sim/db.py` | `_dispose_pending_action_apply_exception` | **保留**共同政策；返回类型改 `None`（不再恒 True） |
| `commit_pending_actions` / `_commit_conversational_draft` | `if dispose(...): ok/result=...` | **改**为 `dispose(...)` 直调，保留原 ok/result |

---

## 测试与变异证据（七 false 前缀）

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false
```

### 聚焦（实测）
```text
python -m pytest tests/test_audience_commit_failure_1853.py \
  tests/test_audience_scroll_539.py tests/test_decree_forecast_1861.py \
  tests/test_cli_play_turn.py tests/test_qa_b3_409_ux.py \
  tests/test_dossier_links_559.py tests/test_chat_stream_failpaths_393.py -q
→ 88 passed, 1 warning in 4.94s

cd web && vitest run src/components/modals.test.tsx src/appDurableWiring.test.tsx \
  --environment jsdom --no-cache
→ 117 passed

tsc --noEmit -p tsconfig.json → TSC_EXIT=0
```

### 变异（复用既有入口；临时文件仅系统临时目录）

**J4** — dispose 在 typed 拒收支改 `raise`：
```text
pytest tests/test_audience_commit_failure_1853.py::test_ineligible_secret_order_is_business_refusal -q --tb=line
红：FAILED … PendingActionRefusal: 皇太极不属大明朝廷…；exit=1
恢复后：1 passed；exit=0
```

**J2** — 夜卷去掉 `reply_retries` 键：
```text
pytest tests/test_audience_scroll_539.py::test_live_and_closed_night_share_the_real_http_contract -q --tb=line
红：AssertionError Extra items in the right set: 'reply_retries'；exit=1
恢复后：1 passed；exit=0
```

**J5** — 临时把 `failed_secret_order_count: len(list_failed_secret_order_actions())` 写回 `state_payload`；临时探针复用 ineligible 应允入口（系统临时目录，非仓内测试）：
```text
红（投影复活）：PROBE_HAS_COUNT_FIELD True；PROBE_FAILED_N 1；探针 pass（旧呈现可观测）
恢复后：PROBE_HAS_COUNT_FIELD False；PROBE_FAILED_N 1；探针 pass（failed 终态保留，呈现字段已无）
复扫呈现符号：EMPTY
```

---

## Commit

- （本轮提交后回填 hash）
- 前缀：`ak-roles:`
- 分支：`ak-roles/issue-1853-j2-j5-unify`（未 push、未开 PR）
