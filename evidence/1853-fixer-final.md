# #1853 修内司交卷（J2–J5 复核删简 · J5 结算死契约收尾）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1853-w5`
- 分支：`ak-roles/issue-1853-j2-j5-unify`
- 授权：本局「继续 #1853 工作树」施工劳务指令
- 判词：末份 `05-1853-judge-acc7a7c6d.json` 未结 **J2–J5**；上轮 `1fb9888ad` 已删 failed 计数/`failedOnly`/CLI 专属传输，本轮复扫发现结算 FE 仍读已删载荷
- **未合入目标分支；不 push / 不开 PR；不 amend / 不 rewrite**

## 自审 / 自查二连

- 上轮删后端结算 `pending_action_failures` 生产者后，前端 `useSettlementFlow` / `decisionModal` / `api.ts` / `types.ts` 与专属夹具仍消费该字段 → 纯死契约。
- 独立核 `ChatTurnResult.pending_action_failures`：全仓 `ming_sim/` **零写入**；转译真异常现役路径 = `story_extract_status==pending` + 后台 future 上抛（`test_audience_translate_1837` 实测断言水位，不经该字段）。故字段本身亦无生产者，随结算死契约删除；**不**误删 `list_failed_secret_order_actions` / `discard_failed_secret_order_intents` / `SET status='failed'` 拒收终态生产者。
- 不另加机制、不补核心恢复、不跑全量。

---

## 生产者→消费者核对（本轮机械命令）

### A. `pending_action_failures` / `PendingActionFailure` / `decisionFailures`

施工前（tracked，排除 archive）：

```bash
git grep -n -I 'pending_action_failures\|PendingActionFailure\|decisionFailures\|setDecisionFailures' -- ':!docs/archive/**'
```

| 路径 | 符号 | 生产者？ | 处置 |
|---|---|---|---|
| `ming_sim/session.py:165` | `ChatTurnResult.pending_action_failures` | **无**（全仓零写入；默认 `[]`） | **删**字段 |
| `tests/test_audience_translate_1837.py` | docstring「经 pending_action_failures 回场」+ 空列表负向断言 | 读者/死契约 | **改** docstring→`story_extract pending`；**删**空字段断言 |
| `tests/test_audience_night_498.py` / `presence_500.py` | 夹具 `pending_action_failures=[]` | 无 | **删**夹具键 |
| `web_app.py` advance/issue/stream/resolve | 注释 only；return **无**该键 | 已删生产者 | **保留**注释（说明不另造） |
| `web/src/api.ts` | `normalizeApiError` 转换 detail | 无上游 | **删**转换 |
| `web/src/types.ts` | `PendingActionFailure` + `ApiErrorDetail.pending_action_failures` | 无 | **删** |
| `web/src/useSettlementFlow.ts:368/489/523` | `setDecisionFailures` / detail 读 | 无 | **删**状态、写权、读口 |
| `web/src/main.tsx` | `failures={decisionFailures}` | 无 | **删** |
| `web/src/components/decisionModal.tsx` | `failures` 呈现 | 无 | **删** prop + UI |
| `web/src/styles/decision.css` | `.decision-failure-*` | 无 | **删** |
| `web/src/chatFailures.test.ts` | normalizeApiError 保失败数组 | 专属死契约 | **删**该 describe |
| `web/src/staleGuard.test.tsx` | `DecisionsFailureFixture` +「密令失败提示」 | 专属死契约 | **删**整案 |
| `web/src/useSettlementFlow.test.tsx` | 夹具键 + #1808 假载荷 | 夹具对齐 | **删**键；#1808 改仅 `message` 响亮 |
| `web/src/appDurableWiring.test.tsx` | advance mock 空数组 | 夹具 | **删**键 |

施工后复扫（排除 evidence/md）：
```text
仅剩：TODOS.md 史注；web_app.py 四处「不以 failed 行另造」注释
→ 代码路径 EMPTY（无类型/状态/呈现/夹具）
```

### B. 转译真异常（保留核对）

| 路径 | 行为 | 处置 |
|---|---|---|
| 后台转译失败 → `get_story_extract_status==pending` | `test_translate_call_failure_is_not_empty_success_dispatch` | **保留** |
| 成功空声明仍可分派 | `test_translate_empty_success_still_dispatches_without_failure` | **保留**（去掉死字段断言） |
| 原轮/月链 `error_pack` / HTTP/SSE `message` | 结算真异常上抛 | **保留** |

### C. `list_failed_secret_order_actions` / `status='failed'`（保留）

```bash
git grep -n -I -E 'list_failed_secret_order_actions|discard_failed_secret_order|SET status=.failed.' -- ming_sim/ tests/ web_app.py
```

| 路径 | 符号 | 处置 |
|---|---|---|
| `ming_sim/db.py:17615/17621` | dispose 案卷/typed 拒收 → failed | **保留** |
| `ming_sim/db.py:18118/18172/18264` | invalid / soft-reject → failed | **保留** |
| `ming_sim/db.py:17981` | `list_failed_secret_order_actions` | **保留**（清理查询） |
| `ming_sim/db.py:19016` + `decree.py:1184` | `discard_failed_secret_order_intents` | **保留** |
| `tests/test_secret_order_isolation_883.py:1201` | 查询契约 | **保留** |

---

## J2「回话重试两份前端权威」

命令：
```bash
git grep -n -I -E 'reply_retries|replyRetries|setReplyRetries' -- web/src/ web_app.py
git grep -n -I -E 'setReplyRetries|useState<.*>\(.*ReplyRetry' -- web/src/   # → EMPTY
```

| 路径 | 符号 | 处置 |
|---|---|---|
| `web_app.py` 夜卷/回话 | `reply_retries` 投影 | **保留**唯一权威 |
| `web/src/components/chatModal.tsx` | 必有 `reply_retries` → `replyRetries` | **保留**（上轮已去 `\|\|[]`） |
| `web/src/useChatActions.ts` | 平行数组 | 上轮已删；复扫 **EMPTY** |
| 测试夜卷 mock | 补 `reply_retries: []` | 上轮契约对齐；维持 |

本轮无新改；复扫平行数组 EMPTY。

---

## J3「无消费者预推轮询」

```bash
git grep -n -I -E 'forecast_inflight|forecastInflight|has_open_key_prefix' -- ':!docs/archive/**' ':!evidence/**'
# → EMPTY
```

| 符号 | 处置 |
|---|---|
| `forecast_inflight` / `forecastInflight` / `has_open_key_prefix` | 上轮已删；本轮复扫零命中 |

---

## J4「暂存提交异常分流政策双实现」

```bash
git grep -n -I '_dispose_pending_action_apply_exception' -- ming_sim/db.py
```

| 路径 | 符号 | 处置 |
|---|---|---|
| `ming_sim/db.py:17595` | `_dispose_pending_action_apply_exception(...) -> None` | **保留**共同政策 |
| `commit_pending_actions` / `_commit_conversational_draft` | 直调 dispose（无 `if dispose():`） | 上轮已归一；维持 |

---

## J5 本轮「结算专属死契约」收尾

根因：后端已停造 `pending_action_failures`，前端仍读并 `setDecisionFailures` → DecisionModal 旧失败条。另：`ChatTurnResult` 字段无写入，转译 docstring 误指该字段。

处置：删结算读者/状态/呈现/类型/专属测试；删无写入的 ChatTurnResult 字段；校正转译 docstring；**保留** failed 终态生产者与 list/discard。

---

## 测试与时长（七 false 前缀）

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false
```

### 聚焦 Python（结构化契约复用，非新证明案）
```text
pytest tests/test_audience_commit_failure_1853.py \
  tests/test_audience_scroll_539.py tests/test_decree_forecast_1861.py \
  tests/test_audience_translate_1837.py \
  tests/test_audience_night_498.py tests/test_audience_presence_500.py \
  -q -p no:cacheprovider --basetemp=<tmp>
→ 80 passed, 1 warning in 7.24s；PY_EXIT=0；OWN_TEMP_EXISTS=False
```

### 聚焦 Web
```text
vitest run src/useSettlementFlow.test.tsx src/staleGuard.test.tsx \
  src/chatFailures.test.ts src/components/modals.test.tsx \
  src/appDurableWiring.test.tsx --environment jsdom --no-cache
→ 145 passed in 5.03s；VITEST_EXIT=0
tsc --noEmit -p tsconfig.json → TSC_EXIT=0
```

### 测试改动性质
| 文件 | 性质 |
|---|---|
| `chatFailures.test.ts` | **删**保死载荷的 normalize 专属案 |
| `staleGuard.test.tsx` | **删**密令失败提示死契约整案 |
| `useSettlementFlow.test.tsx` | 夹具去键；#1808 仅验 `message` 响亮（现役行为） |
| `appDurableWiring.test.tsx` | mock 去死键 |
| `test_audience_translate_1837.py` | docstring 对齐现役；删空字段断言 |
| night_498 / presence_500 | 夹具去死键 |

不全量；未 stash/amend/rewrite/push/PR。

---

## Commit

- `466ccd929d0ca61c532a8493791344e3157492b3`
- `ak-roles: fix(#1853): delete settlement pending_action_failures dead readers`
- 分支：`ak-roles/issue-1853-j2-j5-unify`（未 push、未开 PR）
