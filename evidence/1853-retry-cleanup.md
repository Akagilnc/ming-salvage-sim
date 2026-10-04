# #1853 修内司交卷：J2-T / J8 整类清退

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1853-w5`
- 分支：`ak-roles/issue-1853-retry-cleanup`
- 起始 HEAD（J2-T/J8 首轮）：`2e392c22469b3dea6f5e69d21d1abe49adac8714`
- 首轮交卷：`f88af780d0f5e402a9c06a50f5dd88d98488ba5e`（J2-T + 仅三 reply getter 的窄 J8）
- 扩类交卷：`3c4aca7045eaea539bbaee6ae672a853f9d4f73c`（J8 查询空护栏扩类；表 B 误并查询）
- **本轮交卷 commit：（见文末；纠正表 B + `already_done` 查询直调）**
- 派单：`01a108c7-fcb1-77bc-a311-40f04c296e26@fixer`
- 判词冻结：`07-1853-judge-2e392c224.json` payloads **末份**
- **用户裁定（本轮）**：J2 放行；J8 未扫净。授权=重试/转译重试**查询**接缝内，必备接口被当可选、缺失仍正常继续全部直调（不只空 `[]`）一律直调；无新增机制/检查/适配/失败账本；不扩一般聊天/结算/关闭生命周期或 SDK/结果字段。
- **未合入目标分支；不 push / 不开 PR；不 amend / 不 stash**

## 自查二连（本轮）

- 同类型：转译作业内 `get_story_extract_status` 查询假可选→静默重译已直调；同块落账前 `conn` 复查直调；写口 `mark_*` / `set_chat_turn_error_pack` 保留并写可核依据。
- 引入 bug：未改一般聊天 undo / 回话失败落账 / 结算 getattr；未新增证明性测试；未追 appDurableWiring 已知红灯。

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

用户本轮明确：不只空 `[]`；**缺失后仍正常继续全部直调**（例：缺 `get_story_extract_status` → `already_done=False` → 静默整轮重译）同属清退。

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
| 9 | `run_turn_translation_job` **`already_done = hasattr(get_story_extract_status) and …`** | `audience_translation.py` | **属类（查询；缺则静默重译）** | **本轮删 → `db.get_story_extract_status(ctid)=='done'` 直调**；同块早退 `conn` 查询直调 |
| 10 | 同 job 落账前 `hasattr(conn)` 跳过存活复查后继续落账 | `audience_translation.py` ~356 | **属类（查询；缺则继续落账）** | **本轮删 → `db.conn` 直调** |
| J | 首轮三 reply getter hasattr→`[]` | `_reply_retries_for_night` 等 | 属类（已结） | 保持直调 |
| A | `mark_turn_translation_done` `hasattr(conn)`→return | `audience_translation.py:150` | 不属 | **写**：`UPDATE chat_turns SET extract_status='done'`（水位）；缺 conn 跳过写，不投影空重试、不触发重译 |
| B1 | `_mark_translation_pending` / job 内 `hasattr(mark_story_extraction_pending)` :211/:303 | `audience_translation.py` | 不属 | **写**：`GameDB.mark_story_extraction_pending`=`UPDATE … extract_status='pending'`（`db.py:10053`）；缺口跳过置 pending，随后仍走失败上抛/继续；非查询空投影 |
| B2 | job 失败支 `hasattr(set_chat_turn_error_pack)` :372 | `audience_translation.py` | 不属 | **写**：`GameDB.set_chat_turn_error_pack`=`UPDATE … error_pack_path`（`db.py:10046`）；缺口跳过落包，**仍 `raise`**；非查询早退/空列表 |
| C | CLI retry 内 `persist_minister_reply`/`capture_*`/`restore_*` hasattr | `terminal.py` | 不属 | **重试写生命周期**（落回话/回滚/恢复），非查询护栏 |
| D | `_record_audience_exit` hasattr(conn) | `terminal.py` | 不属 | 告退写账 |
| E | `chat_projection` / `_start_chat_turn` / `can_undo_*` 等 hasattr(conn) | `web_app.py` | 不属 | 轻壳双路径 / 一般聊天生命周期；非重试查询→空投影或静默重译 |
| E2 | `_record_persisted_reply_failure` ~1978 `hasattr(conn)`→`False`（用户点名；非 `_chat_turn_extraction_done`） | `web_app.py` | 不属 | **回话后失败落账写路径**：缺 conn 直接 `return False`（未落 pending/error_pack/post_reply）；不返回重试 `[]`、不跳过已 done 查询；属一般聊天失败善后 |
| E3 | `undo_last_chat` ~2042 `hasattr(conn)` 殿上分流 | `web_app.py` | 不属 | **一般撤回路由**：缺 conn 跳过 SCENE 夜序解析，落入大臣撤回主链；非转译/回话重试查询接缝 |
| F | `api_audience_chat_history` hasattr(conn)→open_night None | `web_app.py` | 不属 | 一般夜态查询 |
| G | 启动 `reconcile_interrupted_*` hasattr(conn) | `web_app.py` | 不属 | **写口对账** |
| H | settlement / hot-replace `getattr(game\|session,'db',None)` | `web_app.py` | 不属 | 结算/替换生命周期（授权不扩） |
| I | `session.close` `getattr(self,'db',None)` | `session.py` | 不属 | 关闭清理（授权不扩） |

**表 B 纠错**：上轮把整个 `run_turn_translation_job` 内 `hasattr(conn/status/mark)` 并成「作业写路径 / 不属」——**错误**。查询子句（`get_story_extract_status` → `already_done`、落账前 `conn` 复查）属类须直调；仅 `mark_story_extraction_pending` / `set_chat_turn_error_pack` 为写生命周期保留（上表 B1/B2）。

### 复扫（本轮后）

```bash
rg -Hn 'hasattr\([^)]*get_story_extract_status' ming_sim/audience_translation.py web_app.py ming_sim/cli/terminal.py
# → ZERO
rg -n 'already_done = ' -A2 ming_sim/audience_translation.py
# → already_done = db.get_story_extract_status(ctid) == "done"
```

### 根因（本轮残项）

`hasattr(db, "get_story_extract_status") and … == "done"` 在缺接口时令 `already_done=False`，转译作业**静默整轮重译**——同授权「缺失仍继续全部直调」，不只空列表。

### 变异证据（真实作业入口，既有夹具；临时目录已清理）

入口：`run_turn_translation_job`（`catch_up` / `retry_pending_translation` / schedule 共用作业）；夹具 `_minister`（`tests/test_audience_extraction_501.py`）+ `WebGame(fresh=True)`；七变量前缀；工作树外 `/tmp/j1853-j8-done.*`。

```json
{
  "J8_already_done_old_hasattr_false": true,
  "J8_already_done_new_raises": true,
  "J8_already_done_new_exc": "AttributeError:get_story_extract_status",
  "J8_already_done_translate_calls": 0,
  "J8_no_silent_retranslate": true,
  "J8_done_early_exit_translate_calls": 0,
  "J8_done_early_exit_ok": true
}
```

含义：旧 hasattr 在缺口时 `already_done` 恒假（将进入重译）；新直调同变异 AttributeError 且 `translate_fn` 调用次数 0；真 DB 已 done 早退亦 0 次转译。

---

## 聚焦验证

前缀七变量；不跑全量；不追已知红灯；无新增证明性测试。

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
  tests/test_audience_translate_1837.py \
  -q -p no:cacheprovider --basetemp=<自建>
```

输出：`232 passed, 1 skipped, 1 warning in 10.89s`。

### 未结项

- appDurableWiring `#1853 重试后的记录连续读失败` 红灯仍归 #1873，本切片不追绿。
- 核心恢复接线等功能项维持家族收尾。
- J2 用户已放行；J8 查询类本轮补齐 `already_done`/落账复查后，写生命周期 hasattr 按上表保留。

## commit

见 `git rev-parse HEAD`（本轮独立 `ak-roles:` commit；不 amend）。
