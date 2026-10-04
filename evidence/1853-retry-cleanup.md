# #1853 修内司交卷：J2-T / J8 整类清退

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1853-w5`
- 分支：`ak-roles/issue-1853-retry-cleanup`
- 起始 HEAD（J2-T/J8 首轮）：`2e392c22469b3dea6f5e69d21d1abe49adac8714`
- 首轮交卷：`f88af780d0f5e402a9c06a50f5dd88d98488ba5e`（J2-T + 仅三 reply getter 的窄 J8）
- **本轮交卷 commit：`3c4aca7045eaea539bbaee6ae672a853f9d4f73c`（J8 扩类：全仓重试/转译重试查询护栏）**
- 派单：`01a108c7-fcb1-77bc-a311-40f04c296e26@fixer`
- 判词冻结：`07-1853-judge-2e392c224.json` payloads **末份**；复扫纠正：J8 不得收窄为三个 reply getter
- **未合入目标分支；不 push / 不开 PR；不 amend / 不 stash**

## 自查二连（本轮）

- 同类型：授权重试/转译重试**查询**接缝内，必备 DB 接口缺失→正常空结果的兼容一律直调；相邻 startup 预检同类一并清。
- 引入 bug：未扩到写生命周期 / 模型传输能力护栏；未追绿 appDurableWiring 已知红灯；不宣称「几个符号=全类扫净」。

---

## 类一：J2-T（首轮已结，本轮未重开）

首轮沿生产者→历史传输→类型→状态→prop→回退清退；夜卷/归档/`retryReadFailure`/重试 POST 保留。施工证据为 `f88af780d`。

全仓枚举（非仅 reply 符号），最终复扫同命令：
```bash
rg -Hn -I 'translation_retries|translationRetries|setTranslationRetries|TranslationRetry|reply_retries|replyRetries|retryReadFailure' . --glob '!evidence/**' --glob '!package-lock.json'
```

| 成员 | 处置 |
|---|---|
| `web_app.py:api_audience_chat_history` 转译重试响应字段 | 删除历史传输 |
| `useAudienceChat.ts:AudienceHistoryData` 转译重试声明 | 删除旧类型字段 |
| `useChatActions.ts` 转译重试 state/setter/返回值 | 删除副本维护 |
| `main.tsx` 解构及 ChatModal prop | 删除接线 |
| `chatModal.tsx` 转译重试 prop/依赖/非 night 回退 | 删除旧回退，仅取夜卷 |
| `modals.test.tsx` helper prop；`appDurableWiring.test.tsx` 历史接口重试夹具 | 随旧链删除；保留夜卷夹具及失败场景 |
| `test_web_audience_night_498.py`、`test_month_loop_tracer_1468.py` 历史字段断言 | 迁至真实夜卷入口；保留失败、恢复、撤回契约 |
| 夜卷响应、ChatModal 夜态、TranslationRetry/ReplyRetry 类型 | 有现役呈现消费者，保留 |
| ArchiveModal 转译重试状态 | 归档夜独立消费，保留 |
| `pending_translation_retries`、reply 查询方法、真实重试 POST、CLI 重试 | 动作/查询能力而非旧副本，保留 |
| `retryReadFailure` hook/prop/提示 | 真实读取失败事实，保留 |

最终扫描：历史接口无重试响应字段，useChatActions/main 无转译副本；剩余投影均为夜卷或归档消费者。

---

## 类二：J8 必备 DB 查询空结果护栏（本轮扩类）

### 票面/判词定义（整类，**禁止**收窄到三个 getter）

「必备DB查询接口被当成可选能力，缺失时正常返回空投影」——**授权重试查询接缝**内（回话重试 **与** 转译重试/待补投影/补跑预检），将必备接口缺失解释为正常空结果/`[]`/空原话/伪推状态的兼容路径一律删简为直调。

**首轮错误**：枚举收窄为 `list_hall_chat_turns` / `get_interrupted_reply_retries` / `get_post_reply_retries` 三符号；并错误保留 CLI `db is None` 为「合法」。本轮纠正。

### 必备性（GameDB / GameSession）

| 接口 | 定义 | 生产构造 |
|---|---|---|
| `conn` | `GameDB` 连接 | `session.py`：成功构造后 `self.db = GameDB(...)` |
| `list_unextracted_replies` | `db.py:10062` | 同上 |
| `get_story_extract_status` | `db.py:10039` | 同上 |
| `get_interrupted_reply_retries` / `get_post_reply_retries` / `list_hall_chat_turns` | `db.py` | 同上；首轮已直调 |
| `WebGame.db` | `web_app.py` property → `session.db` | 恒为上述实例 |

### 机械枚举命令（先全选 guard，再人工分类）

```bash
# 全仓全部属性兼容与缺DB分支，不以已知 getter 名称限制候选：
rg -Hn -I '(hasattr\(|getattr\(|\bdb is None\b)' . \
  --glob '!evidence/**' --glob '!package-lock.json'
# 辅助索引，非类别边界：
rg -Hn -I '(hasattr|getattr).*?(retr|translat|hall_chat)|((retr|translat).*?(hasattr|getattr))' . \
  --glob '!evidence/**' --glob '!package-lock.json'
# 沿夜卷/CLI回话和转译重试入口反查依赖，再按下表分属类/保留。
```

### 全员表：属类 → 删；不属类 → 保留依据

| # | 成员 | 路径 | 分类 | 处置 / 保留依据 |
|---|---|---|---|---|
| 1 | `pending_translation_retries` 缺 `conn`→`[]` | `web_app.py` | **属类**（转译重试查询） | **删 → 直调** `list_pending_translations` |
| 2 | `list_pending_translations` 缺 `list_unextracted_replies`→`[]` | `audience_translation.py` | **属类** | **删 → 直调** |
| 3 | `_load_emperor_message_for_turn` 缺 `conn`→`""` | `audience_translation.py` | **属类**（补跑/重试读原话） | **删 hasattr**；保留 `ctid<=0→""` |
| 4 | CLI `_print_interrupted_reply_retry_hint` `getattr(session,'db',None)`→正常返回 | `terminal.py` | **属类** | **删 → `session.db` 直调**（纠正首轮错误保留 dbNone） |
| 5 | CLI `_retry_interrupted_reply_cli` 同上 | `terminal.py` | **属类** | **删 → `session.db` 直调** |
| 6 | `WebGame.reply_retries` `hasattr(conn)` 夜查询降级 | `web_app.py` | **属类** | **删**；殿上路径直调 `get_open_night` |
| 7 | `retry_pending_translation` 缺 `get_story_extract_status` 伪推 pending/done | `web_app.py` | **属类** | **删 → 直调** |
| 8 | `_spawn_startup_extraction_catch_up` 缺 `conn`/`list_unextracted_replies`→当无待补 | `web_app.py` | **属类（相邻 startup 同类）** | **删**；与转译待补预检同因 |
| A | `mark_turn_translation_done` / `_mark_translation_pending` hasattr | `audience_translation.py` | 不属 | **写生命周期**，非查询空投影 |
| B | `run_turn_translation_job` 内 hasattr(conn/status/mark) | `audience_translation.py` | 不属 | **作业写路径**能力分支 |
| C | CLI retry 内 `persist_minister_reply`/`capture_*`/`restore_*` hasattr | `terminal.py` | 不属 | **重试写生命周期**，非查询护栏 |
| D | `_record_audience_exit` hasattr(conn) | `terminal.py` | 不属 | 告退写账，非重试查询 |
| E | `chat_projection` / `_start_chat_turn` / `can_undo_*` 等 hasattr(conn) | `web_app.py` | 不属 | 轻壳双路径 / 聊天生生命周期，非重试查询→空投影 |
| F | `api_audience_chat_history` hasattr(conn)→open_night None | `web_app.py` | 不属 | 一般夜态查询，非重试/转译重试入口 |
| G | 启动 `reconcile_interrupted_*` hasattr(conn) | `web_app.py` | 不属 | **写口对账**，非空结果查询护栏 |
| H | settlement / hot-replace `getattr(game\|session,'db',None)` | `web_app.py` | 不属 | 结算/替换生命周期，非授权重试查询 |
| I | `session.close` `getattr(self,'db',None)` | `session.py` | 不属 | 关闭清理 |
| J | 首轮已删的三 reply getter hasattr→`[]` | `_reply_retries_for_night` 等 | 属类（已结） | 保持直调，本轮不回潮 |

### 复扫（本轮施工后，属类查询护栏）

```bash
rg -n -I \
  -e 'if not hasattr\(db, "list_unextracted_replies"\)' \
  -e 'getattr\(session,\s*["'\'']db["'\'']\s*,\s*None\)' \
  -e 'hasattr\(self\.db, "get_story_extract_status"\)' \
  -e 'pending_translation_retries' -A6 \
  web_app.py ming_sim/cli/terminal.py ming_sim/audience_translation.py
# CLI getattr(session,'db',None) → ZERO
# list_unextracted / get_story_extract_status 查询空护栏 → ZERO
# pending_translation_retries 不再先判 conn→[]
```

**不宣称**机械枚举里剩余的 hasattr(conn)「全类扫净」——上表 E–H 等按行为保留。

### 根因

无授权失败诚实兼容：生产 `GameDB`/`GameSession.db` 恒备查询接口，却用 `hasattr`/`getattr(...,None)` 把缺失洗成「没有重试项 / 无原话 / 伪状态 / 启动无待补」。

### 变异证据（真实入口，非只 helper）

入口：`WebGame(fresh=False)` + `TestClient` GET `/api/audience/scroll`；`WebGame.pending_translation_retries` / `reply_retries` / `retry_pending_translation`；`catch_up_pending_translations`；CLI `_print_interrupted_reply_retry_hint` / `_retry_interrupted_reply_cli`。

诊断命令指针：本工作树 Shell 脚本 stdout（七变量 + `MING_SIM_DB`/`MING_SIM_USER_DATA_DIR` 自建临时目录，已清理）。关键结果：

```json
{
  "real_scroll_reply_retry_ids": [1],
  "real_scroll_translation_retry_ids": [2],
  "real_pending_ids": [2],
  "J8_pending_old_hide_conn_empty": true,
  "J8_pending_new_raises": true,
  "J8_list_pending_old_empty": true,
  "J8_list_pending_new_raises": true,
  "J8_load_emperor_old_empty": true,
  "J8_load_emperor_new_raises": true,
  "J8_catchup_entry_new_raises": true,
  "J8_cli_hint_old_none_normal": true,
  "J8_cli_hint_new_raises": true,
  "J8_cli_retry_old_none_normal": true,
  "J8_cli_retry_new_raises": true,
  "J8_reply_retries_old_degraded_ids": [-1],
  "J8_reply_retries_new_raises": true,
  "J8_retry_status_old_fake": true,
  "J8_retry_status_new_raises": true,
  "J8_startup_old_skip": true,
  "J8_startup_new_raises": true,
  "J8_http_scroll_status": "AttributeError",
  "J8_http_scroll_empty_translation_retries": false
}
```

含义：旧护栏在缺接口时正常空/降级/伪推；新直调在同变异下 AttributeError；HTTP scroll 隐藏 `list_unextracted_replies` 不再 200+空 `translation_retries`。

---

## 聚焦验证

前缀七变量；不跑全量；不追已知红灯。

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
  tests/test_month_loop_tracer_1468.py tests/test_qa_t1_extraction_dual_source_1353.py \
  -q -p no:cacheprovider --basetemp=<自建>
```

输出：`212 passed, 1 skipped, 1 warning in 10.62s`。

角色复核再次运行（同七变量前缀）：
```bash
PYTHONDONTWRITEBYTECODE=1 /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest \
  tests/test_audience_scroll_539.py tests/test_cli_play_turn.py -q -p no:cacheprovider
```
实测：`41 passed, 1 warning in 1.45s`。首轮 Web 聚焦为 `1 failed | 132 passed`，唯一失败为既存 #1873 连续读失败案，未放松；`tsc --noEmit -p tsconfig.json` 退出 0。本轮后端扩类不改 Web。

机械辅助索引剩余项：`llm_transport.max_retries` 为SDK能力；`session`/`conftest.pending_audience_translation` 为结果字段；CLI `restore_interrupted_after_failed_retry` 为写恢复；测试 executor.fn 为测试设施。均非必备 DB 查询缺失→空投影。

### 夹具

- CLI `_CliChatDbStub.get_interrupted_reply_retries`（首轮已补真实契约）本轮仍够用；**未**削弱失败断言；**未**新增证明性测试。
- 本轮无新增 mock 被测行为。

### 未结项

- appDurableWiring `#1853 重试后的记录连续读失败` 红灯仍归 #1873，本切片不追绿。
- 核心恢复接线等功能项维持家族收尾。

## commit

`3c4aca7045eaea539bbaee6ae672a853f9d4f73c` — `ak-roles: fix(#1853): expand J8 retry-query empty-guard cleanup beyond reply getters`
