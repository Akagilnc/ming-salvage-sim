# #1853 修内司交卷：实际事务提交权单一权威 + 必备DB能力兼容残余清退

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1853-w5`
- 分支：`ak-roles/issue-1853-policy-cleanup`
- 判词真源：`fix-packet.md`；冻结末份 `10-1853-judge-d81e9db05.json` payload[10]
- 未结两类：J4-O「实际事务提交权单一权威」、J8-R「必备DB能力兼容残余清退」
- **未合入目标分支；不 push / 不开 PR；不 amend / 不 stash**
- 互联网先行：SQLite Savepoint/COMMIT 语义（https://www.sqlite.org/lang_savepoint.html）；Python sqlite3 commit；hasattr 替身反模式（hynek / CPython 清退例）

## 两类根因

### J4-O 实际事务提交权单一权威

`connection_owns_transaction` 在 `in_transaction` 时判外层拥有；`_run_pending_action_commit_lifecycle` 据此跳过外层 `atomic`。但 `atomic()` 在 depth==1 且已有外层 BEGIN 时仍于退出时 `conn.commit()`，与归属契约冲突。SQLite COMMIT 清空 savepoint → `RELEASE pending_action_apply_*` 报 `no such savepoint`，半提交（新密令已落、来源动作仍 pending）。

### J8-R 必备DB能力兼容残余清退

生产 `GameSession`/`WebGame` 恒构造完整 `GameDB`，召对/失败/重试接缝仍保留 `hasattr` 替身分支与双实现（空投影、跳过落库、lifecycle_supported、persist 双路径等）。旧回执 `evidence/1853-retry-cleanup.md`「用户裁定」无原话指针。

---

## 类一：全仓枚举与处置

### 枚举命令

```bash
# 事务权威真源与 atomic 落定点
rg -n 'def connection_owns_transaction|def atomic|started_here|conn\.commit\(\)' ming_sim/applier.py
# 生产 with atomic( 全成员（冲突实现扇出面）
rg -n 'with atomic\(' --glob '*.py' -g '!tests/**' -g '!archive/**'
# 写前归属引用（上轮已归一，本轮复扫保持）
git grep -n -E 'owns_transaction|connection_owns_transaction' -- '*.py'
```

### 成员表

| 成员 | 处置 |
|---|---|
| `applier.atomic` 退出路径（depth==1 且已有 `in_transaction` 仍 commit/rollback） | **修正**：`started_here` 仅本层 BEGIN 时为真；借用外层只解除暂停，不抢 COMMIT/ROLLBACK |
| `applier.connection_owns_transaction` | **保留**唯一归属判据真源 |
| 全部生产 `with atomic(...)`（db/create_secret_order、month_chain、session、cli、web 等） | **随 atomic 修正统一行为**；不另造事务框架 |
| 写后提交 / `_commit_suspended` 判断 | **保留**（非写前归属政策副本） |

### 真实入口临时诊断（七 BIN=false）

入口：`create_test_secret_order → stage_pending_action(新建) → {close_false\|BEGIN\|outer atomic\|none} → commit_pending_actions → rollback`。

修前红（摘要）：

```
close_false: OperationalError: no such savepoint: pending_action_apply_1; old=done; new_n=1; pa=pending
begin:       同上半提交
atomic/none: 正常
```

修后绿：

```
RESULT {'mode': 'close_false', 'err': None, 'old': 'active', 'new_n': 0, 'pa': 'pending'}
RESULT {'mode': 'begin', 'err': None, 'old': 'active', 'new_n': 0, 'pa': 'pending'}
RESULT {'mode': 'atomic', 'err': None, 'old': 'active', 'new_n': 0, 'pa': 'pending'}
RESULT {'mode': 'none', 'err': None, 'old': 'active', 'new_n': 1, 'pa': 'committed'}
GREEN_EXIT=0；临时探针与 basetemp 已删
```

未新增永久证明测试 / 事务框架 / 恢复账本 / 护栏。

---

## 类二：全仓枚举与处置

### 枚举命令

```bash
# 召对/失败/重试接缝能力存在性分支
rg -n 'hasattr\([^)]*(db|session\.db|self\.db)' \
  ming_sim/audience_translation.py ming_sim/audience_translate.py \
  ming_sim/audience_night.py ming_sim/cli/terminal.py web_app.py \
  ming_sim/declaration_dispatch.py
# 双实现 / 替身注释
rg -n 'lifecycle_supported|轻量测试替身|旧替身|测试替身无 conn' \
  ming_sim/cli/terminal.py web_app.py
```

### 属类成员表（全修）

| 成员 | 处置 |
|---|---|
| `audience_translation`：`hasattr(conn/mark_story_extraction_pending/set_chat_turn_error_pack)` | **删** → 直调；保留 `ctid<=0` 业务态 |
| `audience_translate`：`hasattr(conn)` 空目录/空摘要 | **删** → 直调；保留 `night_id<=0` |
| `audience_night`：`resolve_standing_roster/conn`、`_allocate_seq` 双实现、`_character_status` 双实现、`list_in_flight` SQL 副本、`list_night_approved`/`mark_pending_night_approved` 跳过、scene recap `conn` | **删副本** → 直调 GameDB；保留空名业务态 |
| `cli/terminal`：retry 路径 capture/persist/record/restore hasattr；`lifecycle_supported`；persist 双路径；`_record_audience_exit` conn | **删** → 直调 |
| `web_app`：chat_projection / agno session / can_undo / in_flight / `_start_chat_turn` / retry·stream 准入 / identity kv·night / reconcile 启动 / api_audience_chat_history | **删替身分支** → 直调 |
| `declaration_dispatch`：capture/record hasattr | **删** → 直调 |
| `evidence/1853-retry-cleanup.md`「用户裁定」 | **改**历史派单说明（无法补原话指针；不作 owner 豁免） |

### 复扫例外（不属本类）

| 命中 | 依据 |
|---|---|
| `web_app.py:1038` rebuild `candidate.db.conn` | 菜单/重建初始化清理，非召对失败重试呈现 |
| `web_app.py:3180` 结算快照无 db | 核账期初始化，非本类 |
| `web_app` month_open_snapshot hasattr | 结算面 |
| materials / month_chain / knowledge `hasattr(conn)` | 供料/过月，非召对失败重试接缝 |
| 结果对象 `getattr(result/exc/...)` | 可选字段，非 DB 能力替身 |

复扫命令结果：`CAT2_HITS=2`（上表两处例外）；`lifecycle_supported` / 替身注释 EMPTY。

夹具对齐（不削弱负向契约）：`test_cli_play_turn` / `test_web_chat_serialization_393` / `test_menu_lifecycle_drain_396` 补齐现役接口与夜补丁；连续读失败 vitest 仍为 #1873 既有红灯，不追绿。

---

## 测试证据（七 BIN=false）

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false
```

### Python 聚焦

```text
pytest -p tests.conftest \
  tests/test_transaction_boundary.py \
  tests/test_audience_commit_failure_1853.py \
  tests/test_secret_order_isolation_883.py \
  tests/test_cli_play_turn.py \
  tests/test_web_chat_serialization_393.py \
  tests/test_menu_lifecycle_drain_396.py \
  tests/test_audience_translate_1837.py \
  tests/test_web_audience_night_498.py \
  tests/test_dossier_links_559.py \
  -q -p no:cacheprovider --basetemp=<tmp>
→ 151 passed in 8.04s；PY_EXIT=0；OWN_TEMP_GONE=yes
```

### Vitest（触及面；已知 #1873）

```text
vitest run src/components/modals.test.tsx src/appDurableWiring.test.tsx \
  -t 'system-layer reply retry|重试后的记录连续读失败' --environment jsdom --no-cache
→ 1 failed | 1 passed | 114 skipped；唯一失败仍为 appDurableWiring 连续读失败（#1873）
```

未跑全量。未改真实席位/宿主配置。未调真实模型。

---

## 合法性与复杂度自查

- 授权：本局修内司 apply 劳务指令 + fix-packet 两类未结。
- 不新增事务框架/恢复账本/护栏/永久证明测试；临时探针已清理。
- 复杂度：删替身分支与双实现，atomic 与归属判据对齐（减冲突实现），净减并行路径。
- 自查二连：同类型（借用外层事务抢提交；召对失败重试 hasattr）已整类扫；引入面（轻壳测试）已对齐现役直调，未放宽负向断言追绿。
- 阻断：无前置缺失；已知 vitest 连续读失败仍归 #1873，非本两类。
