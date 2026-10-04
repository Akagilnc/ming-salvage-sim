# #1853 修内司交卷（J2-R / J6 / J7）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1853-w5`
- 分支：`ak-roles/issue-1853-j2r-j6-j7`
- 起始 HEAD：`a32fc01b3090415f9715d45734c81a312de208b4`
- 交卷 commit：`eb0910d70b1a351dc73b6f691ce6e5c46b269e39`
- 派单：`01a108a4-34d0-738f-9496-b94236066dca@fixer/fix-packet.md`
- 判词冻结：末份 payloads（`06-1853-judge-a32fc01b3.json`）未结三类：J2-R / J6 / J7
- 互联网旁证：[React Choosing the State Structure](https://react.dev/learn/choosing-the-state-structure) — Avoid redundant/duplicated state；裁决依据仍为仓库法源
- **未合入目标分支；不 push / 不开 PR；不 amend / 不 stash**

## 自查二连

- 同类型：被夜卷唯一投影取代的传输字段整类清退；失败夹具排除整类复核；预推同形异常出口整类归一。
- 引入 bug：未删夜卷 `reply_retries`、未删 `reply_retries()`/`retry_interrupted_reply` 服务端能力；未新增生产状态/轮询追绿；未造异常框架。

---

## 类一：被唯一投影取代的传输契约清退（J2-R）

### 票面/判词定义

删除无真实消费者的字段、类型及维护路径；保留现役夜卷投影和真实重试使用的服务端能力，不补新消费者。

### 枚举命令

```bash
rg -n -I --glob '!evidence/**' --glob '!.git/**' -e 'reply_retries' -e 'replyRetries' -e 'ReplyRetry'
rg -n -I -e 'data\.reply_retries|ChatUndoResponse|AudienceHistoryData' web/src
```

### 成员表（施工前）

| 成员 | 路径 | 消费者？ | 处置 |
|---|---|---|---|
| undo 递归出口 `reply_retries` | `web_app.py:2056` | 无（`useChatActions.undoLastChat` 不读） | **删** |
| undo 主出口 `reply_retries` | `web_app.py:2118` | 无 | **删** |
| GET `/api/audience/chat` `reply_retries` | `web_app.py:5293` | 无（`loadMinisterChat` 明确不以历史维护副本） | **删** |
| `ChatUndoResponse.reply_retries` | `web/src/types.ts:704` | 无 | **删** |
| `AudienceHistoryData.reply_retries` | `web/src/useAudienceChat.ts:30` | 无 | **删** |
| `ReplyRetry` 类型 | `web/src/types.ts:628` | 夜卷/钮仍用 | **保留** |
| 夜卷空卷/在飞 `reply_retries` | `web_app.py:5248/5273` | `chatModal.tsx:191/335–337` | **保留** |
| `reply_retries()` / `_reply_retries_for_night` / DB getters | `web_app.py` / `db.py` | `retry_interrupted_reply:2283` + 夜卷 | **保留** |
| 夜卷夹具 `reply_retries` | `modals.test.tsx` / `appDurableWiring.test.tsx` | 现役投影夹具 | **保留** |

### 复扫（施工后）

```bash
rg -n -I --glob '!evidence/**' -e 'reply_retries' web_app.py web/src/types.ts web/src/useAudienceChat.ts
```

- `web_app.py`：仅剩服务端能力 + `/api/audience/scroll` 投影（无 undo/history 输出）。
- `types.ts` / `useAudienceChat.ts`：无 `reply_retries` 字段声明。
- `chatModal.tsx` 仍读夜卷 `reply_retries`。

---

## 类二：失败测试场景不得为绿灯缩减（J6）

### 票面/判词定义

撤销修理带入的失败场景排除，整类复核夹具和断言是否向实现妥协。功能缺口及红灯送 #1873，不以新增生产机制追绿。

### 枚举命令

```bash
rg -n -I -e '!replied' -e '&& !replied' web/src tests
git show 60516a6a3 -- web/src/appDurableWiring.test.tsx
rg -n -I -e '&& !' web/src/appDurableWiring.test.tsx web/src/components/modals.test.tsx web/src/useSettlementFlow.test.tsx
```

### 成员表

| 成员 | 路径 | 性质 | 处置 |
|---|---|---|---|
| `&& !replied` 排除 POST 成功后夜卷读失败 | `appDurableWiring.test.tsx:661`（`60516a6a3` 引入） | 为绿灯缩减负向场景 | **撤销排除** |
| 同案 history 500 注入 `[2,3,5]` | 同文件 `:675` | 合法负向 | **保留** |
| 同案 scroll 失败计数/原轮告警断言 | `:703–717` | 合法负向契约 | **保留（不放松）** |
| 其它 `&& !` 失败排除（同目录聚焦文件） | 枚举零命中 | — | 无其它成员 |

### 已知失败（恢复夹具后如实记录）

见下方「聚焦验证」。负向案在撤销排除后预期红（POST 成功后夜卷刷新仍失败时按钮消不掉）；**不**新增生产状态/轮询追绿。已登记 #1873。

---

## 类三：预推异常政策单一实现（J7）

### 票面/判词定义

归一相同异常处置，保留必要执行步骤、失败分类及 finally 清理，不增加恢复层或框架。

### 枚举命令

```bash
rg -n -I -e '_call_exhausted' ming_sim/decree_forecast.py
rg -n -I -U -e 'except Exception as exc:\n(?:[^\n]*\n){0,3}\s*if _call_exhausted' ming_sim/decree_forecast.py ming_sim/audience_translation.py ming_sim/session_write_queue.py
```

### 成员表

| 成员 | 路径 | 处置 |
|---|---|---|
| snapshot 段 `_call_exhausted→return else raise` | `decree_forecast.py` 原 `:436–439` | **并入单一出口** |
| `_forecast` 段同形政策 | 原 `:445–448` | **并入单一出口** |
| 共用 `finally: release + complete` | 原 `:449–451` | **保留** |
| `_call_exhausted` 谓词 | `:59` | **保留** |
| submit 失败 `complete+raise` | `:453–456` | **保留**（不同形状：提交失败非耗尽分类） |

### 复扫

`ming_sim/decree_forecast.py` 内 `_call_exhausted` 异常出口仅 **一处**（归一后）。

---

## 聚焦验证

前缀（全部七变量）：

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false
```

### Python（触及面）

```bash
OWN_TMP=$(mktemp -d /private/tmp/j1853-fixer.XXXXXX)
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" MING_SIM_USER_DATA_DIR="$OWN_TMP/focus-data" \
  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest \
  tests/test_audience_commit_failure_1853.py \
  tests/test_decree_forecast_1861.py \
  tests/test_audience_background.py \
  tests/test_audience_scroll_539.py \
  tests/test_audience_restore_505.py \
  -q -p no:cacheprovider --basetemp="$OWN_TMP/focus" --durations=5
```

输出：`60 passed, 1 warning in 7.00s`；`PYTEST_EXIT=0`；墙钟约 7s。

### Web / 变异观察（J6）

```bash
cd web
./node_modules/.bin/vitest run src/appDurableWiring.test.tsx \
  -t '#1853 重试后的记录连续读失败' --environment jsdom --no-cache
```

- **恢复负向后**：`1 failed | 53 skipped`，约 2.13s。失败点 `:719`：`reply-retry-7` 在第二次 POST 成功后仍未消（夜卷在 `historyReads∈{3,5}` 继续 500）。这是夹具恢复后的已知红，**不是**功能修好；旧弱夹具（`&& !replied`）曾绿。
- **不**新增生产状态/轮询追绿；登记 #1873。

聚焦批：

```bash
./node_modules/.bin/vitest run src/appDurableWiring.test.tsx src/components/modals.test.tsx \
  --environment jsdom --no-cache
./node_modules/.bin/tsc --noEmit -p tsconfig.json
```

输出：`1 failed | 115 passed`（约 4.75s；唯一失败即上案）；`TSC_EXIT=0`（约 3s）。

临时目录已删：`OWN_TEMP_EXISTS=False`。

---

## #1873 登记

https://github.com/Akagilnc/ming-salvage-sim/issues/1873#issuecomment-5984191976

## 剩余家族功能缺口（不阻本切片）

依 #1812 / 前判留存，不冒称已实现：

- POST 成功后夜卷连续读失败时，原轮重试钮如何消/如何告知（本轮 J6 红灯所映）
- 核心续未成 / 原真因交接 / 空操作恢复 / 历史半撤回·迟到失败·跨 run 覆盖等（既有 #1873 记录）
