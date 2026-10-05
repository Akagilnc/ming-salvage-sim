# #1891 测试仍引用已删生产属性 / 无界等待同类整净回执

基线 HEAD（本轮开工）：`82d35dd08f5c88b5a2d42c11ab0edee1e6e3957c`。
本回执覆盖：(1) 82d35dd 施工修法重复（镜像 helper）DRY；(2) 已删 `_require_active_minister` 测试残留；(3) 授权面 predicate 轮询全表；(4) **最终 DRY 闭合**：唯一 async helper 落 `tests/wait_utils.py`，audience ×2 与 SSE.tick 同 import。
**不改 F1/A/B/C**；不扩大 #1873 角色判断；不新增 timeout / 兼容属性 / 第三 wait 机制。

> **范围排除错误撤回（保留本历史文件）**：上文曾写「不扩 `_require_active_minister` 非等待老资格 gate 案（R2 边界）」。给事中／大理寺末份判决已驳回该排除——#1812 明文要求旧专属测试退出；R2 功能缺口不阻切片 ≠ 允许保留旧入口专属测试。正式处置见 `docs/reports/1891-1899-dry-test-closure.md`（删除三案及 `_stub_game`；保留现役 `can_summon` 负向）。

## 撤回史（上一轮误述）

82d35dd 回执曾把
`tests/test_web_chat_serialization_393.py::test_chat_stream_sse_waits_for_sync_generator_in_executor`
对已删 `_require_active_minister` 的 monkeypatch 标成「文件级旁路／非本类、未扩修」。

**撤回**：该残留与 `_pending_writes_count` 读取同属 ef9166578 退役后「测试对已删生产属性残留引用」；形状同于 F1/A/B/C 已删的
`tests/test_chat_stream_failpaths_393.py::_post_chat_stream` 同形 patch。不宜剩一处又归 R2。本轮合法同类消费闭包。

另：82d35dd 新增 `_await_inflight_or_task` 镜像 `_await_event_or_task`——独立复核认定平行轮询；「不为此新增机制」下应 generalized 复用，旧镜像无续命权。

## 判词原话（完整 JSON，不改写）

见派工用户消息中的 `status/fix/findings/evidence` 整块 JSON（本仓不另存平行副本）。本轮以用户续派设计指令为准。

## Advisor（只读，设计复用；不庭审、不扩 authority）

完整原话路径：`/tmp/1891-dry-advisor-stdout.txt`
（独立只读 advisor；不加工摘要。VERDICT: PASS——单一 `_await_condition_or_task(predicate, task)` 为正确复用；SSE 删退役 patch + entered/task 终态逃生。）
**现仍适用**：单一 helper、规则唯一；本轮只把该 helper **移动**到已有公共测试工具，不开新庭、不另写机制。

## DRY：单一 predicate helper（权威位置）

| 旧物 | 处置 |
| --- | --- |
| `_await_event_or_task(ev, task)` | 删除 |
| `_await_inflight_or_task(game, task)` | 删除 |
| `test_web_audience_night_498` 本地 `_await_condition_or_task` | **移入** `tests/wait_utils._await_condition_or_task`（单一权威；不另写） |
| SSE.tick 内联「predicate ∨ task.done → 异常传播 → 无条件 done 报错」~10 行 | **删除平行副本**；`await _await_condition_or_task(entered.is_set, stream_task)` 后 append tick / `release.set` |

唯一 helper：`tests/wait_utils._await_condition_or_task(predicate, task)`
规则：`while not predicate() and not task.done()` → task 异常原样传播 → 谓词仍假则 `AssertionError`。
无 `isinstance` / 兼容包装 / timeout / 第三机制；不动既有 `wait_until`／`ObservingLock`（史：当时施工边界；`ObservingLock` 后于 #1891/#1899 TEST-C1 残余因零引用删除，见 `docs/1723-triage-disposition.md` 文首撤回）。

调用点（两文件直接 import 同一符号）：

- `_start_hanging_chat`：`await _await_condition_or_task(started.is_set, task)`
- `test_asgi_phase_flip_while_waiting_gate_rejected`：`await _await_condition_or_task(lambda: game._runtime_write_queue().inflight_count() > 0, chat_task)`
- `test_chat_stream_sse_waits_for_sync_generator_in_executor` tick：`await _await_condition_or_task(entered.is_set, stream_task)` → `events.append("tick")` → `release.set()`；`finally: release.set()` 与序断言保持

## 已删属性测试残留

| 成员 | 处置 |
| --- | --- |
| `test_chat_stream_sse_waits_for_sync_generator_in_executor` monkeypatch `_require_active_minister` | **删除**（无消费者；现役入口固定 `SCENE_CHAT_SPEAKER`） |
| 同案 tick 等待 | 现共用 `wait_utils._await_condition_or_task`；`finally: release.set()` 放行 generator 线程；**保留** `events == ["tick","stream"]` 与 `"event: done"` 断言，不宽放 |
| 兼容符号 / Mock 被测 API | **不恢复** |

## 授权范围内 predicate 轮询全表（tracked）

扫描命令：

```sh
rg -n '_await_condition_or_task|_await_event_or_task|_await_inflight_or_task|_wait_for\b|wait_until\(|while not .*\.is_set|while .*\.inflight_count|asyncio\.sleep\(0\)|release\.wait\(|entered\.wait|\.wait\(\)' \
  tests/test_web_audience_night_498.py \
  tests/test_web_chat_serialization_393.py \
  tests/test_qa_t1_extraction_dual_source_1353.py \
  tests/test_menu_lifecycle_drain_396.py \
  tests/test_audience_background.py \
  tests/wait_utils.py --glob '*.py'
```

### Helpers

| Helper | 被读状态 | 可达？ | 任务异常可终止？ | 合法保留依据 |
| --- | --- | --- | --- | --- |
| `tests/wait_utils.wait_until(pred)` | 调用点自带谓词 | 是（见下消费点） | 否（同步 poll；谓词须自达） | 共享 backoff；宪法禁随意硬墙钟；**不**为一案加 timeout |
| `test_audience_background._wait_for_pending_writes_to_drain` | `wait_idle` 或 `inflight_count()==0` | 是（现役队列） | N/A（drain 终态） | 已接现役计数 |
| `tests/wait_utils._await_condition_or_task` | 调用方 predicate | 是（`started.is_set` / `inflight_count()>0` / `entered.is_set`） | **是**（`task.done`→`task.exception()`） | **唯一** async 终态逃生 helper（公共测试工具） |
| （已删）`_await_event_or_task` / `_await_inflight_or_task` | — | — | — | 镜像重复；已并入上项 |
| （已删）audience 本地 helper / SSE 内联同构副本 | — | — | — | 已迁入 wait_utils；无平行副本 |
| （已删）`_wait_for(getattr(...,"_pending_writes_count",0)>0)` | 缺省 0 永假 | **否** | 否 | 82d35dd 已删 |

### `wait_until` 消费点（授权面）

| 调用点 | 谓词 | 可达终态 |
| --- | --- | --- |
| `test_menu_lifecycle_drain_396.py:85/123` | `closed == [1]` | fixture 回调置位 |
| `test_menu_lifecycle_drain_396.py:401/416` | `bool(killed)` | kill 路径置位 |
| `test_menu_lifecycle_drain_396.py:706` | `not os.path.exists(old_db_path)` | 删档完成 |
| `test_audience_background.py:153` | `inflight_count()==0` | 现役归零 |

### async / 内联 poll（授权面）

| 位置 | 形态 | 终态逃生 | 依据 |
| --- | --- | --- | --- |
| audience ×2 + SSE tick | `wait_utils._await_condition_or_task` | task 异常传播 | **单一共享实现** |
| `test_web_audience_night_498` offload ticker `while ticks < 5: await sleep(0)` | 计数前进 | chat `allow.set` 后收束 | 端点 offload 可观测；非缺属性空转 |
| `test_web_chat_serialization_393` nonstream `asyncio.to_thread(chat_entered.wait)` | thread Event | `finally allow_finish.set` | 并发 state 探针序；sibling 失败也放行 |

### 阻塞 `threading.Event.wait`（合法保留；**不加 timeout**）

这些是生产者/消费者会合钉（release / allow / holding），状态由测试双方置位；不是「读已删属性默认 0」空转。不整改为墙钟 timeout。

| 文件 | 典型 wait | 谁置位 |
| --- | --- | --- |
| `test_web_chat_serialization_393` | `release.wait` / `allow_finish.wait` / settlement holding | tick / finally / 测试主线程 |
| `test_web_audience_night_498` | `allow.wait`（FakeAgent） | `_start_hanging_chat` 调用方 |
| `test_qa_t1_extraction_dual_source_1353` | `release`/`entered`/`entry_done`/`late_*`/`barrier_*` | 同案线程协作 |
| `test_menu_lifecycle_drain_396` | `done`/`drain_done`/`wait_prior_entered`/`allow_finish` | lifecycle 协作 |
| `test_audience_background` | （经 `_wait_for_pending_writes_to_drain`） | 队列 idle |

**例外**：`test_web_audience_night_498.py:323` `release.wait(3)` 为既有短会合（非本轮引入）；本轮不扩改。

### 读取点（现役计数；无缺省 0）

| 成员 | 状态 |
| --- | --- |
| qa / web_chat / menu / audience drain | 均读 `inflight_count()` 或 `wait_idle` |
| `web_app.py` docstring | 已用 `inflight_count` 字样（82d35dd） |
| failpaths 模块注释旧名 | 叙述 only；非读取；本轮不扩 |

## 操作摘要

1. 删除镜像 helper；统一 `_await_condition_or_task`；两调用点改 predicate（c68abac）。
2. SSE 案删除 `_require_active_minister` monkeypatch；补 stream_task 终态逃生；保留 offload 序断言（c68abac）。
3. **本轮**：将唯一 helper **移动**至 `tests/wait_utils.py`；audience 与 SSE 同 import；撤去 SSE 内联平行副本；闲置 `Callable` import 按真实 uses 去掉。
4. 不恢复兼容属性；不加 timeout；不改生产 SDK/席位/调度；不重开 F1/A/B/C；不扩非等待老资格 gate。

## 验证命令与结果

环境恒定：七个 `MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false`、临时 `MING_SIM_USER_DATA_DIR`、`PYTHONDONTWRITEBYTECODE=1`、`/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`、`pytest -p no:cacheprovider --basetemp=...`。

| 案 | 结果 | 日志 |
| --- | --- | --- |
| SSE missing-patch red（开工 HEAD） | 1 failed / 0.79s `AttributeError: no _require_active_minister` | `/tmp/1891-dry-red.CLHmEM/sse-red.log` |
| SSE green | 1 passed / 0.53s | `/tmp/1891-dry-green.QNsuWz/sse-green.log` |
| 核心四案 | 4 passed / 0.77s | `/tmp/1891-dry-green.QNsuWz/core.log` |
| 四文件整面（audience+chat+qa+menu）worker | 12+6+21+17 = **56 passed / 4.98s** | 先前 worker 聚焦日志 |
| 四文件整面（独立主助手复核，c68abac 上） | **56 passed / 4.73s** | `/tmp/1891-inflight-independent.h8z6HX/focus.log` |
| 四文件整面（本轮 helper 迁 wait_utils 后） | **56 passed / 5.97s** | `/tmp/1891-wait-utils-dry.cf2ReX/focus.log` |
| 变异 race：predicate 直读 `_pending_writes_count`（保留 task.done 逃生，禁 getattr 默认挂死） | 1 failed AttributeError / 0.66s → 恢复 1 passed / 0.71s | `/tmp/1891-dry-mut2.zIFi3f/mut-red.log`、`mut-green.log` |
| 变异 SSE：装回 `_require_active_minister` patch | 1 failed AttributeError / 0.54s | `/tmp/1891-dry-mut2.zIFi3f/sse-mut-red.log` |

未跑全量；未硬 kill 40s。

### Ruff / diff

```sh
uv tool run --from ruff ruff check --target-version py313 --select F401,F821 \
  tests/wait_utils.py \
  tests/test_web_audience_night_498.py \
  tests/test_web_chat_serialization_393.py
# All checks passed!
git diff --check   # clean
```

## 自查二连

- 同类型：授权面已删属性读取／退役 monkeypatch；镜像 wait helper 已并；唯一 async helper 现仅 `wait_utils` 一份；SSE 无平行规则副本；predicate 轮询表列全；无「外边界不修」洗白。
- 引入 bug：共享 helper 保留 task 终态传播；SSE 仍 finally release + 原 asserts；未恢复兼容符号；未加 timeout；未改生产；未动 `wait_until`／`ObservingLock`（史；后者后因零引用删除，见 1723 文首撤回）；未扩 F1/A/B/C 或非等待 gate。
