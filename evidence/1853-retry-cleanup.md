# #1853 修内司交卷：J2-T / J8 整类清退

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1853-w5`
- 分支：`ak-roles/issue-1853-retry-cleanup`
- 起始 HEAD：`2e392c22469b3dea6f5e69d21d1abe49adac8714`
- 交卷 commit：`f88af780d0f5e402a9c06a50f5dd88d98488ba5e`
- 派单：`01a108c7-fcb1-77bc-a311-40f04c296e26@fixer/fix-packet.md`
- 判词冻结：`07-1853-judge-2e392c224.json` payloads **末份**未结两类：J2-T、J8
- 互联网旁证：
  - React：[Choosing the State Structure](https://react.dev/learn/choosing-the-state-structure) — Avoid redundant / duplicated state
  - Python：[Glossary — EAFP](https://docs.python.org/3/glossary.html) / [hasattr](https://docs.python.org/3/library/functions.html#hasattr) — 必备接口直调；本案裁决依据仍为仓库法源（#1812 不新增护栏）
- **未合入目标分支；不 push / 不开 PR；不 amend / 不 stash**

## diagnosing-bugs 跳过依据

本案根因已由末份大理寺判词裁定（J2-T、J8 disposition=成立，boundary/direction 已钉）。按 skill「Skip phases only when explicitly justified」及派单「根因已有裁定，假说/仪器步骤不必重复」：跳过 Phase 1–3 假说/仪器循环；改用临时真实入口诊断 + 旧逻辑变异验证（禁止新增证明性测试）。

## 自查二连

- 同类型：被夜卷唯一投影取代的转译历史副本链整类清退；重试查询接缝内必备 DB 接口空结果护栏整类直调。
- 引入 bug：未删夜卷 `translation_retries` / `reply_retries`、未删归档消费、未删 `retryReadFailure`、未删真实重试动作；未新增检查/适配/账本；未追绿 appDurableWiring 已知红灯。

---

## 类一：唯一失败投影的旧副本链清退（J2-T）

### 票面/判词定义（整类，未收窄）

「夜卷归一后，转译重试的旧副本链未退净」——沿生产者→传输→类型→状态→prop→回退及专属夹具清退被夜卷取代且无真实呈现消费者的路径；保留夜卷投影、归档夜消费、真实重试动作与 `retryReadFailure`。不得只扫 `reply` 符号。

### 枚举命令

```bash
rg -n -I --glob '!evidence/**' --glob '!.git/**' \
  -e 'translation_retries' -e 'translationRetries' -e 'setTranslationRetries' -e 'TranslationRetry' \
  web_app.py web/src tests ming_sim
```

### 成员表（施工前 → 处置）

| 成员 | 路径 | 消费者？ | 处置 |
|---|---|---|---|
| GET `/api/audience/chat` `translation_retries` | `web_app.py` `api_audience_chat_history` | 无呈现（探针四态 history_retry_rendered=false） | **删** |
| `AudienceHistoryData.translation_retries` | `web/src/useAudienceChat.ts` | 仅喂历史副本状态 | **删** |
| `useChatActions` `translationRetries` 状态 + `setTranslationRetries` | `web/src/useChatActions.ts` | 无夜卷呈现用途 | **删** |
| `main.tsx` prop 接线 | `web/src/main.tsx` | 平行 prop | **删** |
| `ChatModal` prop + 非 night 回退 `[...translationRetries]` | `web/src/components/chatModal.tsx` | loading/none/error 无持久消息，回退不可见 | **删** |
| `modals.test` helper `translationRetries` prop | `web/src/components/modals.test.tsx` | 专属夹具 | **删** |
| appDurableWiring 历史接口 `translation_retries` 夹具 | `web/src/appDurableWiring.test.tsx` | 专属旧传输夹具 | **删**（夜卷夹具保留） |
| 夜卷 `/api/audience/scroll` `translation_retries` | `web_app.py` | `chatModal` 夜态呈现 | **保留** |
| `pending_translation_retries` / 重试 POST | `web_app.py` | 生产/重试动作 | **保留** |
| `audienceArchiveModal` 状态与卷读 | `web/src/components/audienceArchiveModal.tsx` | 归档夜消费 | **保留** |
| `retryReadFailure` | hooks + ChatModal | 读失败事实 | **保留** |
| `TranslationRetry` 类型 | `web/src/types.ts` | 夜卷/归档 | **保留** |
| 测试读点改夜卷 | `test_web_audience_night_498.py` / `test_month_loop_tracer_1468.py` | 契约迁移 | **改读 scroll** |

### 复扫（施工后）与保留依据

```bash
rg -n -I --glob '!evidence/**' -e 'translation_retries' \
  web_app.py web/src/useAudienceChat.ts web/src/useChatActions.ts \
  web/src/main.tsx web/src/components/chatModal.tsx web/src/components/audienceArchiveModal.tsx
rg -n -I -e 'translationRetries=' -e 'setTranslationRetries' \
  web/src/main.tsx web/src/useChatActions.ts web/src/components/chatModal.tsx
```

- 历史接口 / useChatActions / main prop：**零**。
- 现役：`api_audience_scroll` + ChatModal 夜卷态 + ArchiveModal + `pending_translation_retries`。
- `retryReadFailure` 注入翻译提示路径保留。

### 根因

夜卷成为唯一呈现权威后，转译重试仍经历史接口→前端状态→prop→非 night 回退维护平行副本；真实 ChatModal 四态探针显示仅 night 能渲染，历史链无呈现用途，属被取代旧路径。

### 变异 / 删除边界

删除型无行为变更边界：历史字段移除后，夜卷仍为权威；归档与 `retryReadFailure` 不动。真实入口诊断见下「诊断」。

---

## 类二：必备 DB 接口的空结果兼容护栏清退（J8）

### 票面/判词定义（整类）

「必备DB查询接口被当成可选能力，缺失时正常返回空投影」——重试查询接缝内将必备接口缺失解释为正常空结果的兼容路径一律删简为直调；不新增检查、适配层或失败账本。同授权接缝同类一并处置。

### 枚举命令

```bash
rg -n -I --glob '!evidence/**' --glob '!.git/**' \
  -e 'hasattr\([^)]*(list_hall_chat_turns|get_interrupted_reply_retries|get_post_reply_retries)' \
  -e 'get_interrupted_reply_retries|get_post_reply_retries|list_hall_chat_turns' \
  web_app.py ming_sim/cli/terminal.py ming_sim/db.py
```

### 成员表

| 成员 | 路径 | 处置 |
|---|---|---|
| `hasattr(list_hall_chat_turns)→[]` | `web_app.py` `_reply_retries_for_night` | **删 → 直调** |
| `hasattr(get_interrupted_reply_retries)→[]` | 同上循环 | **删 → 直调** |
| `hasattr(get_post_reply_retries)→[]` | 同上循环 | **删 → 直调** |
| `hasattr(get_interrupted_reply_retries)→[]` | `WebGame.interrupted_reply_retries` | **删 → 直调** |
| `hasattr(get_post_reply_retries)→[]` | `WebGame.reply_retries` | **删 → 直调** |
| `hasattr(get_interrupted_reply_retries)` 与 `db is None` 混写 | `ming_sim/cli/terminal.py` 两处 | **删 hasattr；保留 `db is None`** |
| 生产 `GameDB` 三接口定义 | `ming_sim/db.py` | **保留** |
| CLI 轻壳缺接口 | `tests/test_cli_play_turn.py` | **夹具补接口**（非生产护栏） |

### 复扫

```bash
rg -n -I -e 'hasattr\([^)]*(list_hall_chat_turns|get_interrupted_reply_retries|get_post_reply_retries)' \
  web_app.py ming_sim/cli/terminal.py
# → J8_ZERO
```

### 根因

无授权失败诚实兼容护栏：生产构造恒为 `GameDB`，却用 `hasattr→[]` 把必备 getter 缺失洗成「没有重试项」。

### 变异证据

隐藏必备 getter 后：

- **旧护栏**：`old_reply_retries_for_night(proxy)` → `[]`（`J8_mutation_old_guard_empty=true`）
- **新直调**：`_reply_retries_for_night(proxy)` → `AttributeError`（`J8_new_direct_raises=true`）
- HTTP scroll 同隐接口 → `AttributeError`（不再 200+空列表）

---

## 临时真实入口诊断（命令 + 实测）

前缀：七个 `MING_SIM_*_BIN=/usr/bin/false`；`OPENAI_API_KEY=sk-test`；`MING_SIM_DB`/`MING_SIM_USER_DATA_DIR` 自建临时目录（已清理）。

入口：真实 `WebGame(fresh=False)` + `TestClient`；开夜、落问话、标 `interrupted`；GET `/api/audience/chat` 与 `/api/audience/scroll`；HideGetter 变异。

关键输出：

```json
{
  "J2T_chat_has_translation_retries_key": false,
  "J2T_scroll_has_translation_retries_key": true,
  "J8_real_reply_retry_ids": [1],
  "J8_new_direct_raises": true,
  "J8_mutation_old_guard_empty": true,
  "J8_hide_list_hall_raises": true,
  "J8_mutation_old_list_hall_empty": true,
  "J8_interrupted_hide_raises": true,
  "J8_night_hide_post_raises": true,
  "J8_http_hide_exc": "AttributeError",
  "J2T_keep_archive": true,
  "J2T_keep_retryReadFailure": true,
  "J2T_history_no_translation_retries": true,
  "J2T_scroll_keeps_translation_retries": true,
  "J2T_no_prop_fallback": true,
  "J2T_useChatActions_no_state": true
}
```

---

## 聚焦验证

前缀七变量；Python：`/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`；不跑全量。

### Python

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" \
  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest \
  tests/test_audience_commit_failure_1853.py tests/test_audience_scroll_539.py \
  tests/test_decree_forecast_1861.py tests/test_audience_background.py \
  tests/test_cli_play_turn.py tests/test_person_delta_adapter.py \
  tests/test_urge_lever_624.py tests/test_web_audience_night_498.py \
  tests/test_month_loop_tracer_1468.py \
  -q -p no:cacheprovider --basetemp=<自建>
```

输出：`191 passed, 1 skipped, 1 warning in 9.96s`

### Web

```bash
# 同上七变量前缀
cd web
./node_modules/.bin/vitest run \
  src/appDurableWiring.test.tsx src/components/modals.test.tsx \
  src/chatFailures.test.ts src/useSettlementFlow.test.tsx \
  --environment jsdom --no-cache
./node_modules/.bin/tsc --noEmit -p tsconfig.json
```

输出：`1 failed | 132 passed`；唯一失败 = `#1853 重试后的记录连续读失败在原轮告知…`（`reply-retry-7` 未消，行 717）——按末份判词 / #1873 **保留红灯，不追绿**。`TSC_EXIT=0`。

### 测试改动必要性

| 改动 | 必要性 |
|---|---|
| `test_web_audience_night_498` / `test_month_loop_tracer_1468` 改读 scroll | 历史传输已删，断言须跟唯一真源 |
| `test_cli_play_turn` 轻壳补 `get_interrupted_reply_retries` | 生产直调后夹具须具备必备接口；非新增生产护栏 |
| appDurableWiring / modals 去掉历史 `translation_retries` 夹具/prop | 专属旧链夹具随链删除 |
| **未**新增证明性测试 | 派单禁止 |

---

## 未结项

- appDurableWiring `#1853 重试后的记录连续读失败` 红灯：功能缺口仍归 #1873，本切片不追绿。
- 核心恢复接线、原真因交接等历史功能项：维持家族收尾（#1873），本轮不施工。
- 未 push、未开 PR、未合入目标分支。

## commit

`f88af780d0f5e402a9c06a50f5dd88d98488ba5e` — `ak-roles: fix(#1853): retire translate-retry history chain and required-DB empty guards`
