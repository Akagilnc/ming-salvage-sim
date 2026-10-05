# #1891 测试仍引用已删 `_pending_writes_count`（含无界等待）回执

基线 HEAD（开工）：`e12e094249ed938e707cf2ec799bc833c5b3352d`。  
本回执只覆盖判词一类；不改 F1/A/B/C；不扩大 #1873 角色判断。

## 判词原话（完整 JSON，不改写）

见派工用户消息中的 `status/fix/findings/evidence` 整块 JSON（本仓不另存平行副本）。

## 全成员扫描

命令：

```sh
rg -n '_pending_writes_count|_wait_for\b' tests/ web_app.py --glob '*.py'
rg -n 'wait_until\(|ObservingLock|inflight_count' tests/ --glob '*.py'
```

| 成员 | 处置 |
| --- | --- |
| `tests/test_web_audience_night_498.py:497` `_wait_for(getattr(..., "_pending_writes_count", 0) > 0)` | 删 `_wait_for`；改 `_await_inflight_or_task` 读 `game._runtime_write_queue().inflight_count()` + task 终态传播 |
| `tests/test_qa_t1_extraction_dual_source_1353.py:306/316/319/362` | 改 `q.inflight_count()`；去掉与 `inflight_count` 重复的旧属性断言 |
| `tests/test_web_chat_serialization_393.py:386` | 改 `runtime._runtime_write_queue().inflight_count() == 0` |
| `tests/test_menu_lifecycle_drain_396.py:670` | 同形改 `inflight_count()`（本类授权修读取；#1873 其它非阻断归属不变） |
| `web_app.py:2638` docstring | 旧名改为 `inflight_count`（无生产兼容属性恢复） |
| `tests/test_chat_stream_failpaths_393.py:5` 模块注释 | 仅叙述旧名，非读取点；本轮不扩修 |

复扫（修后）：生产/测试 Python 读取点仅余 failpaths 注释一行。

## 同类无界 wait 保留依据

| Helper | 被读状态可达性 | 保留依据 |
| --- | --- | --- |
| `tests/wait_utils.wait_until` | 调用点谓词均为可达终态（`closed`/`killed`/path 消失/`inflight_count()==0`/`completion.done`） | 宪法禁随意硬墙钟；不为一案加 timeout 框架 |
| `test_audience_background._wait_for_pending_writes_to_drain` | 已读 `_runtime_write_queue().inflight_count()==0` | 已接现役计数，非本类残留 |
| `test_web_audience_night_498._await_event_or_task` | event 或 task.done；task 异常原样传播 | 保留；竞态案复用同形终态传播 |
| 已删 `_wait_for(pred)` | `getattr(..., 0)` 使谓词永假 → 无限空转 | 删除 |

**ObservingLock**：未接入本竞态案。`SessionWriteQueue.write_gate` 为 `ClassifiedWriteGate`（需 `acquire_translation` / `is_held_by_translation` 等）；`ObservingLock` 不是其 drop-in。若硬替换即破 ticketed seam——不新增包装机制。改读 `inflight_count`（领票在 `write_gate.acquire` 之前，锁前相位通过后计数可达）+ 既有 task 终态传播即可覆盖假说①②③。

## 操作摘要

1. 读取点全部改接 `_runtime_write_queue().inflight_count()`（与 `get_session_write_queue(...).inflight_count()` 同账本）。
2. 竞态案删除无界 `_wait_for`；新增同文件本地 `_await_inflight_or_task`（镜像 `_await_event_or_task`，非新框架）。
3. 不恢复 `_pending_writes_count`；不改生产 SDK/席位/调度；不新 timeout。
4. 触及文件顺手清 Ruff F401 闲置 import（qa / web_chat）；audience / menu / web_app docstring 无 F401。

## 验证命令与结果

环境恒定：七个 `MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false`、临时 `MING_SIM_USER_DATA_DIR`、`PYTHONDONTWRITEBYTECODE=1`、`/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`、`pytest -p no:cacheprovider --basetemp=...`。

| 案 | 结果 | 日志 |
| --- | --- | --- |
| 主助手开工 red：`test_empty_startup_catchup_claims_zero_tickets` | 1 failed / 0.91s `AttributeError` | `/tmp/1891-inflight-red.rwYQNI/red.log` |
| 判词原空转（不复跑 40s） | 原话：`test_asgi_phase_flip_while_waiting_gate_rejected` 在 e12e09424 上单案 timeout 40 被杀；`getattr` 缺省 0 永不成立 | 引用派工 JSON `findings[0].cause` |
| 核心五案绿 | 5 passed / 1.03s | `/tmp/1891-inflight-green.bctJKz/focus-core.log` |
| `test_web_audience_night_498.py` 整文件 | **12 passed / 3.55s（终止）** | `/tmp/1891-inflight-aud.tOzlc6/aud.log` |
| `test_qa_t1_extraction_dual_source_1353.py` + audience + 两单案复验 | 35 passed / 4.52s | `/tmp/1891-inflight-reverify.DZyQGZ/reverify.log` |
| `test_menu_lifecycle_drain_396.py` 整文件 | 17 passed / 0.75s；本类读取点已绿；未见本轮 #1873 登记红复现 | `/tmp/1891-inflight-menu.OXSAiN/menu.log` |
| 变异 qa：装回 `game._pending_writes_count` 直接读 | 1 failed AttributeError / 0.84s → 恢复后 1 passed / 1.15s | `/tmp/1891-inflight-mut-red.q9NUft/mut-red.log`、`/tmp/1891-inflight-mut-green.lv11eI/mut-green.log` |
| 变异 race：wait 内直接读已删属性 + 保留 `task.done()` 逃生（禁 getattr 默认挂死） | 1 failed AttributeError / 0.70s → 恢复后 1 passed / 0.69s | `/tmp/1891-inflight-race-mut-red.iNGWCu/mut-red.log`、`/tmp/1891-inflight-race-mut-green.hxnhED/mut-green.log` |

### 文件级旁路（非本类、未扩修）

三文件合跑时 `tests/test_web_chat_serialization_393.py::test_chat_stream_sse_waits_for_sync_generator_in_executor` 报 `web_app` 无 `_require_active_minister`（同属 ef9166578 退役残留，**不是** `_pending_writes_count` 读取类）。本类授权边界外，不扩修。本类触及的 `test_nonstream_chat_rejects_when_session_draining` 已绿。

### Ruff / diff

```sh
uv tool run --from ruff ruff check --target-version py313 --select F401,F821 \
  tests/test_web_audience_night_498.py \
  tests/test_qa_t1_extraction_dual_source_1353.py \
  tests/test_web_chat_serialization_393.py \
  tests/test_menu_lifecycle_drain_396.py \
  web_app.py
# All checks passed!
git diff --check   # clean
```

未跑全量。

## Advisor（只读，不庭审）

完整原话路径：`/tmp/1891-inflight-advisor-stdout.txt`  
（独立只读 advisor；不加工摘要。VERDICT: PASS。）

## 自查二连

- 同类型：全仓 `_pending_writes_count` 读取点已扫；剩余仅 failpaths 注释。
- 引入 bug：竞态等待保留 task 终态传播，避免请求先失败时再空转；未恢复兼容属性；未加 timeout 墙钟。
