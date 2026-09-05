# #1723 分诊处置清单（先于改动；dead-leg drift 作待审草稿）

法源：票面类定义 + 分诊三问 + 灰区口径表；样板 `f684ede49`；Q1 无挂起证据 ≠ 保留护栏（无依据则删）。
CI 终线：`ci.yml` `timeout-minutes: 20`（现行 :19，实质成立）。

三问缩写：
- Q1 有无已发生可复现永久挂起/误报证据？
- Q2 接缝不变式是否声称「N 秒内完成」？
- Q3 CI 20min 是否已承接最终挂死？

---

## A. Event.wait(N) / Thread.join(N) — 灰区「打 timeout 参数，保留屏障」

| 位置 | Q1 | Q2 | Q3 | 归属 | 判定 | 处置 |
| --- | --- | --- | --- | --- | --- | --- |
| `test_action_cluster_registry_515.py` L760/767/769 `wait(2)` | 无 | 并发重叠顺序，不声称秒内 | 是 | 事件屏障 | **缺陷** | `wait()`；沿用 drift |
| `test_arrival_dual_voice_671.py` L192-198 `wait(timeout=5)` | 无 | 双声部启动顺序 | 是 | 事件屏障 | **缺陷** | `wait()`；沿用 |
| `test_audience_background.py` `agent.completed.wait(1.0)` ×5 | 无 | 后台召对完成事件 | 是 | 事件屏障 | **缺陷** | `wait()`；沿用 |
| `test_audience_extraction_501.py` `wait(5)`/`join(5)` | 无 | 串行 catch-up 屏障 | 是 | 事件屏障 | **缺陷** | bare；删 `sleep(0.05)` 赌窗改 `len==1` 状态证；沿用 |
| `test_audience_pipeline_499.py` `release_mind.wait(2)` + 多处 | 无 | mind 管道顺序 | 是 | 事件屏障 | **缺陷** | bare；沿用 |
| `test_audience_travel_gating_670.py` 10× wait + join | 无 | offsite scene 生命周期 | 是 | 事件屏障 | **缺陷** | bare；沿用 |
| `test_beat_orchestration_503.py` 多数 wait/join(N) | 无 | scene registry 并发顺序 | 是 | 事件屏障 | **缺陷** | bare；沿用（见 B 节 drift 错改） |
| `test_chat_stream_failpaths_393.py` wait/join | 无 | failpath 清理后可写 | 是 | 事件屏障 | **缺陷** | bare + entered 事件；沿用 |
| `test_cli_backend.py` `killed.wait(5)` | 无 | watchdog 杀进程事件 | 是 | 事件屏障 | **缺陷** | `wait()`；沿用 |
| `test_court_break_player_lock_1727.py` `barrier_claimed.wait(5)` + `join(10/15)` | 无 | 屏障预领与探针并发 | 是 | 事件屏障 | **缺陷** | **drift 未覆盖（main 新文件）→ 本局改** bare |
| `test_dossier_endorsements_612.py` 8× wait(5) | 无 | beat∥endorsement 重叠 | 是 | 事件屏障 | **缺陷** | bare；沿用 |
| `test_dossier_links_559.py` `barrier.wait(2)` | 无 | 确认与抽取重叠 | 是 | 事件屏障 | **缺陷** | bare；沿用 |
| `test_enter_settlement_period_1235.py` 多 wait/join | 无 | write/gate 并发 | 是 | 事件屏障 | **缺陷** | bare；沿用 |
| `test_highlight_judge_544.py` `release.wait(2)` ×3 | 无 | 慢 judge 协作方放行 | 是 | 事件屏障 | **缺陷** | bare；沿用 |
| `test_menu_continue_stream_1195.py` wait/join | 无 | stale continue 世代 | 是 | 事件屏障 | **缺陷** | bare；沿用 |
| `test_menu_lifecycle_drain_396.py` wait/join | 无 | drain/gate 顺序 | 是 | 事件屏障 | **缺陷** | bare；沿用（见 B） |
| `test_month_loop_tracer_1468.py` wait(5) | 无 | trail hold 放行 | 是 | 事件屏障 | **缺陷** | bare；沿用 |
| `test_pihong_dossier_1490.py` wait/join | 无 | phase/desk 并发窗 | 是 | 事件屏障 | **缺陷** | bare + second_submitted 替 sleep；沿用 |
| `test_qa_b3_409_ux.py` wait/join | 无 | resolve body 窗 | 是 | 事件屏障 | **缺陷** | bare；沿用 |
| `test_qa_c2_phase_settlement_mask_1374.py` wait(5) | 无 | phase2 窗 | 是 | 事件屏障 | **缺陷** | bare；沿用 |
| `test_qa_c2_settlement_display_lifecycle_1343.py` wait/join | 无 | clear vs gate | 是 | 事件屏障 | **缺陷** | bare；沿用 |
| `test_qa_c3_secret_order_path_1357_1376.py` join(5) | 无 | 持闸可调用（死锁则 CI） | 是 | 事件屏障 | **缺陷** | bare join；沿用 |
| `test_qa_t1_extraction_dual_source_1353.py` 多 wait/join | 无 | dual-source 屏障 | 是 | 事件屏障 | **缺陷** | bare；沿用 |
| `test_relation_brew_636.py` Barrier/wait | 无 | 并行酿制重叠 | 是 | 事件屏障 | **缺陷** | bare；`if not release.wait()` 死枝 → 本局改 `release.wait()` |
| `test_relation_judge_634.py` wait/join | 无 | judge∥scene | 是 | 事件屏障 | **缺陷** | bare；沿用 |
| `test_rescript_fanout_656.py` barrier.wait(30) | 无 | 五腿汇合 | 是 | 事件屏障 | **缺陷** | bare；沿用 |
| `test_session_cli_fallback.py` classifier wait(1) | 无 | 分类先于回话 | 是 | 事件屏障 | **缺陷** | bare；沿用 |
| `test_session_write_queue_1353.py` 大量 wait/join | 无 | 票序/屏障 | 是 | 事件屏障 | **缺陷** | bare；沿用 |
| `test_settlement_write_guard_393.py` wait/join | 无 | gate 拒写 | 是 | 事件屏障 | **缺陷** | bare；沿用 |
| `test_web_audience_night_498.py` allow/release wait | 无 | fake agent 放行 | 是 | 事件屏障 | **缺陷** | bare；沿用 |
| `test_web_chat_serialization_393.py` wait/join | 无 | drain/chat 重叠 | 是 | 事件屏障 | **缺陷** | bare + settlement_release 事件；沿用 |

---

## B. `assert not done.wait(N)` 负向时序 — 灰区「打；改事件/状态证法」

| 位置 | Q1 | Q2 | Q3 | 判定 | 处置 |
| --- | --- | --- | --- | --- | --- |
| `menu_lifecycle_drain_396` `not done.wait(0.2/0.3)` `not drain_done.wait(0.2/0.05)` | 无 | 持闸时不得完成 | 是 | **缺陷** | `not ev.is_set()`；沿用 |
| `enter_settlement_period_1235` `not done.wait(0.05)` | 无 | 同上 | 是 | **缺陷** | `not done.is_set()`；沿用 |
| `qa_c2_settlement_display_lifecycle_1343` `not a_done.wait(0.08)` | 无 | 同上 | 是 | **缺陷** | `not a_done.is_set()`；沿用 |
| `audience_travel_gating_670` `not close_entered.wait(0.1)` ×2 | 无 | scene 未完不得过 barrier | 是 | **缺陷** | `not close_entered.is_set()`；沿用 |
| `web_chat_serialization_393` `not drain_done.wait(0.15)` | 无 | chat 在飞 drain 不得关 | 是 | **缺陷** | `not drain_done.is_set()`；沿用 |
| `beat_orchestration_503` `waiter.join(0.2)` 后 `assert is_alive`（sibling drain） | 无 | join 不得在 sibling 未完时返回 | 是 | **缺陷** | 去短 join，状态：`is_alive`+outcome 空+sibling 未终；沿用 |
| `beat_orchestration_503` `worker.join(0.2)` 后 `assert is_alive`（gate 持锁 close 两测） | 无 | persist 须等 gate | 是 | **缺陷** | **drift 错改成无时限 join()→自锁**；本局改：`gen_done` 事件 + `assert is_alive`，**禁止**持闸时 join |

---

## C. sleep 赌调度 / 竞速 — 灰区「打」

| 位置 | 判定 | 处置 |
| --- | --- | --- |
| `audience_extraction_501` `sleep(0.05)` 赌第二路未启动 | **缺陷** | 改 `len(seen)==1` 状态；沿用 |
| `enter_settlement_1235` `sleep(0.05)` 赌 A 未完 | **缺陷** | 改 `not a_done.is_set()`；沿用 |
| `pihong_1490` `sleep(0.02/0.15)` 赌 coalesce 窗 | **缺陷** | `second_submitted` 事件；沿用 |
| `web_audience_night_498` `sleep(0.15)` 赌 issue 入队 | **缺陷** | 直接 `not issue_task.done()`；沿用 |
| `web_audience_night_498` `sleep(0.2)` 赌 ticker | **缺陷** | `while ticks < 5: sleep(0)` 状态；沿用 |
| `web_chat_serialization_393` settlement `sleep(0.1/0.02)` | **缺陷** | `settlement_release`/`holding` 事件；沿用 |
| `web_chat_serialization_393` SSE `sleep(0.05/0.01)` | **缺陷** | entered/release 事件；沿用 |
| `menu_continue_stream_1195` deadline+sleep 等 closed | **缺陷** | 无时限 poll；沿用 |
| `enter_settlement` / `menu_*` / `audience_background` deadline 轮询 | **缺陷** | 无时限 `_wait_for`/while；沿用 |

---

## D. sleep 假慢协作方触发生产超时 — 灰区「不打」

| 位置 | 归属 | 判定 |
| --- | --- | --- |
| `test_qa_d1_decree_normalize_1274.py` `sleep(2)` + `capture_timeout_s=0.3` | 假慢→生产有界路径 | **合法保留** |
| `test_qa_v1_participant_heal_retry.py` `sleep(1.5)` + 短 capture_timeout | 同上 | **合法保留** |
| `test_session_write_queue_1353.py` `sleep(slow_s=0.08)` 证屏障不等 elapsed 熔断 | 假慢工人终态 | **合法保留** |
| `test_parallel_extractors.py` `sleep(delay)` 造并发重叠供 `max_active` | 假慢以观测并发峰值 | **sleep 保留**；见 E |

---

## E. 以墙钟为行为证据的断言（类定义正面命中，表外）

| 位置 | Q1 | Q2 | Q3 | 判定 | 处置 |
| --- | --- | --- | --- | --- | --- |
| `parallel_extractors` `elapsed < delay * N` | 无 | 不变式是 `max_active>=2`，不拥有墙钟短于串行 | 是 | **缺陷** | **删 elapsed 断言**；保留 max_active |
| `qa_b3_409_ux` `elapsed < 1.5` + `asyncio.wait_for(..., 2)` | 无 | precheck 不抢 held gate（事件/完成即证） | 是 | **缺陷** | drift 已删；沿用 |

---

## F. `_wait_for` 轮询终线 / Barrier(timeout=) / future.result(timeout) / Lock.acquire(timeout) / asyncio.wait_for — 表外依类+三问

| 形状 | 判定 | 处置 |
| --- | --- | --- |
| `_wait_for(..., timeout=N)` 把 N 当正确性 | **缺陷** | 去 timeout，挂死→CI；drift 沿用 |
| `threading.Barrier(n, timeout=N)` | **缺陷** | 去 timeout；沿用 |
| `future.result(timeout=N)` 测试侧等完成 | **缺陷** | bare `result()`；沿用 |
| `Lock.acquire(timeout=0.3)` 证 gate 可取得 | **缺陷** | `acquire(blocking=False)` 状态证；沿用 |
| `asyncio.wait_for(task, timeout=N)` 等测试任务 | **缺陷** | bare await；沿用 |
| `q.wait_idle(timeout_s=5)` 测侧排空 | **缺陷** | bare `wait_idle()`；沿用 |
| `wait_pending_writes(..., timeout_s=0.05)` 负向测 helper 对 False 报红 | timeout 是 **被测输入** | **合法保留** |
| `poll.wait(0.01)` / `sleep(0.01)` 在无时限 `_wait_for` 内 | backoff，非正确性 deadline | **合法保留** |
| `asyncio.sleep(0)` 让出循环 | 灰区不打 | **合法保留** |

---

## G. 配置项 / 第三方 API 透传 — 灰区「不打」

| 位置 | 判定 |
| --- | --- |
| `test_cli_backend.py` `CliChat(..., timeout=111/222/...)` 透传 | **合法保留** |
| `test_cli_backend.py` `_iter_codex_stream_chunks(..., timeout=0.2)` 被测 API | **合法保留** |
| `test_minister_chat_timeout.py` / TimeoutExpired 生产路径 | **合法保留**（生产超时不在范围） |
| `registry.join(11)` / `_scene_registry.join(1)` | **非 timeout**（scene id） | 不改 |

---

## H. dead-leg 调试残留与错改（本局必修）

| 项 | 判定 | 处置 |
| --- | --- | --- |
| `test_beat_orchestration_503.py` 6× `print("MAIN …")` | 调试残留 | **剔除** |
| 同文件 `t.join(timeout=2.0)` 残留 | 未完成的屏障处置 | → `t.join()` |
| 同文件 close 两测 `worker.join()` 在 `gate.acquire()` 之后 | 把负向短 join 误改无时限 join → **自锁** | `gen_done` 状态证 + 持闸期间不 join |
| 同文件 `test_stream_join_and_abandon…` | 旧测靠 `abandon.wait(2)` AssertionError 被吞才绿；bare wait 后 hang | 补 `atomic` nullcontext + trail stub，success 路径真 done |
| 同文件 `test_close_scene_early_phase1…` | `release.wait(2)` 墙钟自尽；bare 后 drain↔release 自锁 | close 改 worker 线程，主线程 `started` 后 `release` |
| 同文件 `test_657_s2_s3…` `Barrier(2, timeout=)` | open+enter 多 Future 时第 3+ 方永等；timeout 靠 BrokenBarrier 自尽 | 改 `max_active` 状态证并发 |
| `test_menu_lifecycle_drain_396.py` L789/L876 `assert _wait_for(...)` | `_wait_for` 改返回 None 后 assert 恒红 | → `_wait_for(...)` 无 assert |
| `test_court_break_player_lock_1727.py` | main 新文件，drift 未覆盖 | bare wait/join |
| `test_parallel_extractors` `elapsed < delay*N` | 墙钟当并发证据 | 删；保留 max_active + 假慢 sleep |
| `test_relation_brew` `if not release.wait()` | bare wait 后死枝 | → `release.wait()` |

---

## I. 检索面说明

- 票面检索数（wait/timeout=/sleep）是检索面不是缺陷数。
- 本清单覆盖 HEAD 全仓 `tests/*.py` 命中 + main 并入后新文件 `test_court_break_player_lock_1727.py` + drift 草稿重判。
- 生产代码超时、CI job 终线：不在范围。
