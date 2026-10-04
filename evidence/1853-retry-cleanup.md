# #1853 修内司交卷：J2-T / J8 整类清退

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1853-w5`
- 分支：`ak-roles/issue-1853-retry-cleanup`
- 起始 HEAD（J2-T/J8 首轮）：`2e392c22469b3dea6f5e69d21d1abe49adac8714`
- 首轮交卷：`f88af780d0f5e402a9c06a50f5dd88d98488ba5e`（J2-T + 仅三 reply getter 的窄 J8）
- 扩类交卷：`3c4aca7045eaea539bbaee6ae672a853f9d4f73c`（J8 查询空护栏扩类；表 B 误并查询）
- already_done 交卷：`55888a1b48cf5e40cdae43010d658f8a64002ebe`（纠正表 B + `already_done` 查询直调）
- **本轮交卷 commit：`8b24a73effebfbb444a72ab6481eeefa1d4dcddb`（三处 web_app 查询护栏直调；E2/E3/_fail SELECT 重归属类）**
- 判词冻结：`07-1853-judge-2e392c224.json` payloads **末份**
- **用户裁定（本轮）**：同一 J8 复核继续。`_record_persisted_reply_failure` 缺 conn→False、`_fail_chat_turn_and_reload` SELECT `hasattr(conn) else None`、`undo_last_chat` 殿上 hasconn——三者均为查询接缝（状态/问话 id/夜序定 restore vs fail 或殿上路由），**不能因后续写口把前置 SELECT 错归写生命周期**。授权删三处 conn 兼容、直调；保留无 chat_turn_id / 缺行 / 无 night 等真实业务分支。写 mark/set_error_pack 可保留但回执明确写口无查询伪推。不扩其他一般聊天生命周期。不新增证明测试、不追已知红灯。
- **未合入目标分支；不 push / 不开 PR；不 amend / 不 stash**

## 自查二连（本轮）

- 同类型：三处前置查询缺 conn 不再洗成 False/None/跳过夜路由；真实业务分支（`chat_turn_id=0`、缺行、无 night）保留。
- 引入 bug：未改 `can_undo_last_chat` / `chat_projection` / `_start_chat_turn` / 结算 getattr；未新增证明性测试；未追 appDurableWiring 已知红灯；临时文件仅 `.tmp/j1853-j8-conn/`。

---

## 类一：J2-T（用户裁定放行，本轮不重开）

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

## 类二：J8 必备 DB 查询护栏（含「缺失仍继续全部直调」）

### 票面/判词 + 用户本轮释宽

「必备DB查询接口被当成可选能力，缺失时正常返回空投影」——授权重试查询接缝（回话重试 **与** 转译重试/待补投影/补跑预检/转译作业早退查询）。

用户本轮明确：不只空 `[]`；**缺失后仍正常继续全部直调**（例：缺 `get_story_extract_status` → `already_done=False` → 静默整轮重译）同属清退；**前置 SELECT 定恢复分流亦属查询，不得因后续写口改类**。

### 必备性（GameDB / GameSession）

| 接口 | 定义 | 生产构造 |
|---|---|---|
| `conn` | `GameDB` 连接 | `session.py`：成功构造后 `self.db = GameDB(...)` |
| `list_unextracted_replies` | `db.py:10062` | 同上 |
| `get_story_extract_status` | `db.py:10039` | 同上 |
| `get_interrupted_reply_retries` / `get_post_reply_retries` / `list_hall_chat_turns` | `db.py` | 同上 |
| `WebGame.db` | `web_app.py` property → `session.db` | 恒为上述实例 |

### 机械枚举命令（不以拼写收窄；db / self.db / session.db / game.db）

```bash
rg -Hn -I '(hasattr\(|getattr\(|\bdb is None\b)' . \
  --glob '!evidence/**' --glob '!package-lock.json' --glob '!web/node_modules/**' --glob '!archive/**'
# 辅助：
rg -Hn -I 'hasattr\([^)]*get_story_extract_status' . \
  --glob '!evidence/**' --glob '!**/.git/**'   # 须 ZERO
```

### 全员表：属类 → 删；不属类 → 保留依据（可核）

| # | 成员 | 路径 | 分类 | 处置 / 保留依据 |
|---|---|---|---|---|
| 1 | `pending_translation_retries` 缺 `conn`→`[]` | `web_app.py` | **属类** | **已删 → 直调**（`3c4aca704`） |
| 2 | `list_pending_translations` 缺 `list_unextracted_replies`→`[]` | `audience_translation.py` | **属类** | **已删 → 直调** |
| 3 | `_load_emperor_message_for_turn` 缺 `conn`→`""` | `audience_translation.py` | **属类** | **已删 → 直调** |
| 4–5 | CLI retry hint/入口 `getattr(session,'db',None)` | `terminal.py` | **属类** | **已删 → `session.db` 直调** |
| 6 | `WebGame.reply_retries` `hasattr(conn)` 夜查询降级 | `web_app.py` | **属类** | **已删** |
| 7 | `retry_pending_translation` 缺 status 伪推 | `web_app.py` | **属类** | **已删 → 直调** |
| 8 | `_spawn_startup_extraction_catch_up` 缺接口当无待补 | `web_app.py` | **属类（相邻）** | **已删** |
| 9 | `run_turn_translation_job` **`already_done`** | `audience_translation.py` | **属类（查询）** | **已删 → 直调**（`55888a1b4`） |
| 10 | 同 job 落账前 `hasattr(conn)` 跳过存活复查 | `audience_translation.py` | **属类（查询）** | **已删 → `db.conn` 直调** |
| **E2** | `_record_persisted_reply_failure` 缺 conn→`False` 后跳过 SELECT status | `web_app.py` | **属类（查询；本轮重归）** | **本轮删 → `self.db.conn` 直调**；保留 `not chat_turn_id` / 缺行业务分支。其后 mark/set_error_pack/mark_post_reply_failure = **写口**，不借其合理性护栏前置 SELECT |
| **E2b** | `_fail_chat_turn_and_reload` SELECT user_message_id `hasattr(conn) else None` | `web_app.py` | **属类（查询；本轮点名）** | **本轮删 → 直调**；`None` 伪推会错走 fail 而非 restore。保留 `not chat_turn_id` / 无 user_message_id→fail 业务分支。其后 set_error_pack = **写口** |
| **E3** | `undo_last_chat` 殿上 `hasattr(conn)` 护 `get_open_night`/`list_hall_chat_turns` | `web_app.py` | **属类（查询；本轮重归）** | **本轮删 → 直调**；缺 conn 曾跳过夜序落入大臣主链。保留无 night / 无 active 业务分支 |
| J | 首轮三 reply getter hasattr→`[]` | `_reply_retries_for_night` 等 | 属类（已结） | 保持直调 |
| A | `mark_turn_translation_done` `hasattr(conn)`→return | `audience_translation.py:150` | 不属 | **写**：水位 UPDATE；缺 conn 跳过写，无查询伪推 |
| B1 | `_mark_translation_pending` / job 内 `hasattr(mark_story_extraction_pending)` | `audience_translation.py` | 不属 | **写**：置 pending；缺口跳过写，随后仍走失败上抛 |
| B2 | job 失败支 `hasattr(set_chat_turn_error_pack)` | `audience_translation.py` | 不属 | **写**：落错误包；缺口跳过落包，**仍 `raise`** |
| C | CLI retry 内 `persist_minister_reply`/`capture_*`/`restore_*` hasattr | `terminal.py` | 不属 | **重试写生命周期** |
| D | `_record_audience_exit` hasattr(conn) | `terminal.py` | 不属 | 告退写账 |
| E | `chat_projection` / `_start_chat_turn` / `can_undo_*` 等 hasattr(conn) | `web_app.py` | 不属 | 轻壳双路径 / **一般聊天生命周期**（授权不扩；含 `can_undo_last_chat` 殿上同源形，本轮不跟） |
| F | `api_audience_chat_history` hasattr(conn)→open_night None | `web_app.py` | 不属 | 一般夜态查询 |
| G | 启动 `reconcile_interrupted_*` hasattr(conn) | `web_app.py` | 不属 | **写口对账** |
| H | settlement / hot-replace `getattr(game\|session,'db',None)` | `web_app.py` | 不属 | 结算/替换生命周期（授权不扩） |
| I | `session.close` `getattr(self,'db',None)` | `session.py` | 不属 | 关闭清理（授权不扩） |

**表纠错（本轮）**：上轮把 E2/E3 标「不属／写路径／撤回路由」——**错误**。用户点名：前置 SELECT（status / user_message_id / open_night+hall turns）定恢复分流或殿上路由 = 查询接缝；后续写口不得改类。`_fail_chat_turn_and_reload` 同形一并清退。

### 复扫（本轮后）

```bash
rg -n '_record_persisted_reply_failure|_fail_chat_turn_and_reload|def undo_last_chat' -A12 web_app.py
# → 三处均无 hasattr(conn)；仅业务分支（chat_turn_id=0 / 缺行 / 无 night）
rg -n 'hasattr\(self\.db, "conn"\)' web_app.py
# → 残留均在 E/F/G 等授权不扩位点（chat_projection / can_undo_* / _start_chat_turn / stream 等）
```

### 根因（本轮残项）

1. `_record_persisted_reply_failure`：缺 conn → `return False`，跳过 SELECT status，调用方当「未落 pending」走另一恢复支——**查询缺失洗成假失败落账否**。
2. `_fail_chat_turn_and_reload`：缺 conn → `row=None` → 走 `fail_chat_turn` 而非 `restore_interrupted_*`——**查询伪推错分流**。
3. `undo_last_chat`：缺 conn → 跳过殿上夜序 → 落入大臣撤回主链——**查询护栏错路由**。

### 变异证据（真实 WebGame 方法；工作树临时目录）

入口：`WebGame._record_persisted_reply_failure` / `_fail_chat_turn_and_reload` / `undo_last_chat`；夹具：`SimpleNamespace` 无 `conn`（补契约不削弱：缺 conn 旧 False/None/skip，新抛）；业务分支 `chat_turn_id=0` 仍 False/noop。产物：`.tmp/j1853-j8-conn/mutation.json`。

```json
{
  "J8_record_old_hasattr_false": true,
  "J8_record_new_raises": true,
  "J8_record_new_exc": "AttributeError:'types.SimpleNamespace' object has no attribute 'conn'",
  "J8_fail_old_hasattr_none_fail": true,
  "J8_fail_new_raises": true,
  "J8_fail_new_exc": "AttributeError:'types.SimpleNamespace' object has no attribute 'conn'",
  "J8_undo_old_hasattr_skip_hall": true,
  "J8_undo_new_raises": true,
  "J8_undo_new_exc": "AttributeError:'types.SimpleNamespace' object has no attribute 'conn'",
  "J8_biz_record_zero_false": true,
  "J8_biz_fail_zero_noop": true
}
```

含义：旧 hasattr 在缺口时分别 False / 伪推 None→fail / 跳过殿上；新直调同变异 AttributeError；`chat_turn_id=0` 业务早退仍成立。

---

## 聚焦验证

前缀七变量；不跑全量；不追已知红灯；无新增证明性测试。basetemp 在工作树 `.tmp/j1853-j8-conn/pytest-basetemp`。

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
  tests/test_audience_extraction_501.py tests/test_audience_translation_once_1898.py \
  tests/test_audience_translate_1837.py tests/test_audience_restore_505.py \
  -q -p no:cacheprovider --basetemp=<工作树.tmp>
```

输出：`256 passed, 1 skipped, 1 warning in 13.87s`。

### 未结项

- appDurableWiring `#1853 重试后的记录连续读失败` 红灯仍归 #1873，本切片不追绿。
- 核心恢复接线等功能项维持家族收尾。
- J2 用户已放行；J8 本轮补齐 web_app 三处查询护栏；写生命周期 hasattr 与一般聊天生命周期按上表保留。

## commit

`8b24a73effebfbb444a72ab6481eeefa1d4dcddb` — `ak-roles: fix(#1853): direct-call reply-fail/undo night query guards`
