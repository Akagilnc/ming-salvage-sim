# #1723 分诊处置清单

法源：票面类定义 + 分诊三问 + 灰区口径表；样板 `f684ede49`；Q1 无挂起证据 ≠ 保留护栏（无依据则删）。
CI 终线：`ci.yml` `timeout-minutes: 20`（现行 :19，实质成立）。

三问缩写：
- Q1 有无已发生可复现永久挂起/误报证据？
- Q2 接缝不变式是否声称「N 秒内完成」？
- Q3 CI 20min 是否已承接最终挂死？

---

## 0. 扫描 revision、原始命令与计数差异

### 固定 revision

| rev | 角色 |
| --- | --- |
| `ec65c824` | #1721 合入后、#1723 改动前基点（判官实测） |
| `a626c7e14` | 本片父 commit（merge #1735） |
| `faf4bddec` | 本片首修（墙钟→事件/状态；分诊草稿） |
| `HEAD`（本局） | 判牒 r2：竞态证法/会合屏障/清单补齐 |

### 原始扫描命令（逐行 regex，`tests/test_*.py` 顶层）

```bash
# wait 数字行：Event.wait(N) / join(N) / wait(timeout=N)
python - <<'PY'
import re, subprocess
def count(rev):
    files = [l for l in subprocess.check_output(
        ['git','ls-tree','-r','--name-only',rev,'tests'], text=True
    ).splitlines() if re.match(r'tests/test_[^/]+\.py$', l)]
    w=t=s=0; wf=tf=sf=set()
    for path in files:
        text = subprocess.check_output(['git','show',f'{rev}:{path}'], text=True)
        for line in text.splitlines():
            if re.search(r'wait\(\s*\d', line):
                w += 1; wf.add(path)
            if re.search(r'timeout\s*=\s*\d', line):
                t += 1; tf.add(path)
            if re.search(r'\bsleep\s*\(', line):
                s += 1; sf.add(path)
    print(f'{rev[:12]} wait={w}/{len(wf)} timeout={t}/{len(tf)} sleep={s}/{len(sf)} files={len(files)}')
count('ec65c824'); count('a626c7e14'); count('HEAD')
PY
```

### 计数对照

| rev | wait(数字) 行/文件 | timeout=数字 行/文件 | sleep( 行/文件 |
| --- | --- | --- | --- |
| 票面口述 | 152 / — | 86 / — | 28 / 10 文件 |
| `ec65c824` 实测 | **151 / 21** | **86 / 21** | **28 / 12** |
| `a626c7e14` 实测 | **151 / 21** | **89 / 22** | **28 / 12** |
| 跨行/宽口径另计 | ~153 wait | — | — |

**差异说明（不伪造凑数）**：

- 票面「152」与实测 151 差 1：原票未附原始命令；本清单以可复现 regex 为准，不回填臆造命中。
- 票面 sleep「10 文件」vs 实测 12：同因——原命令未冻结；本清单按 `tests/test_*.py` + `\bsleep\(` 计 12。
- `a626c7e14` timeout 89/22 vs `ec65c824` 86/21：主线并入 #1725/#1726/#1727 等邻票测试新增 `timeout=` 配置/API 透传与少量夹具，**不是** #1723 本体回潮。
- 检索面 ≠ 缺陷数：配置透传、生产超时输入、backoff、scene id 形参均会命中 regex。

### 真实「先分诊后施工」轨迹（不伪造历史）

1. **dead-leg drift**（`faf4bddec` 之前未合入草稿）：在工作树直接改 wait/join/sleep，含调试 `print("MAIN …")`、持闸 `join()` 自锁、#657 `Barrier(2, timeout=)` 错参与者、`_wait_for` 改返回 None 后 `assert _wait_for` 恒红。无独立「先写完整清单」commit。
2. **`faf4bddec`**：同 commit 交付 `docs/1723-triage-disposition.md` + 34 文件测试改动。同 commit **不证明**「先写清单再改代码」的严格时序，只证明清单与改动一并落地；Spec(a)1 时序举证缺口在本局以可复现扫描命令 + 逐项三问补齐，**不回写伪造的分诊-only commit**。
3. **本局（判牒 r2）**：在已落地改动上补竞态证法、恢复 657 会合屏障、简化 `_wait_for`、纠正 sleep 分诊错类，并重写本清单使 I 覆盖声明可核。

---

## A. Event.wait(N) / Thread.join(N) — 灰区「打 timeout 参数，保留屏障」

每命中：Q1=无已复现永久挂起；Q2=并发/生命周期顺序，不声称秒内；Q3=CI 承接 → **缺陷** → bare `wait()`/`join()`。

| 位置 | 归属 | 判定 | 处置 |
| --- | --- | --- | --- |
| `test_action_cluster_registry_515.py` L760/767/769 | 事件屏障 | 缺陷 | `wait()` |
| `test_arrival_dual_voice_671.py` L192-198 | 事件屏障 | 缺陷 | `wait()` |
| `test_audience_background.py` `completed.wait(1.0)` ×5 | 事件屏障 | 缺陷 | `wait()` |
| `test_audience_extraction_501.py` wait/join(5) | 事件屏障 | 缺陷 | bare |
| `test_audience_pipeline_499.py` 多处 | 事件屏障 | 缺陷 | bare |
| `test_audience_travel_gating_670.py` 10× | 事件屏障 | 缺陷 | bare；负向 is_set 见 B |
| `test_beat_orchestration_503.py` 多数 | 事件屏障 | 缺陷 | bare；657 见 H |
| `test_chat_stream_failpaths_393.py` | 事件屏障 | 缺陷 | bare |
| `test_cli_backend.py` `killed.wait(5)` | 事件屏障 | 缺陷 | `wait()` |
| `test_court_break_player_lock_1727.py` | 事件屏障 | 缺陷 | bare（main 新文件，drift 未覆盖） |
| `test_dossier_endorsements_612.py` 8× | 事件屏障 | 缺陷 | bare |
| `test_dossier_links_559.py` | 事件屏障 | 缺陷 | bare |
| `test_enter_settlement_period_1235.py` | 事件屏障 | 缺陷 | bare；gate 终态断言保留（见 B） |
| `test_highlight_judge_544.py` ×3 | 事件屏障 | 缺陷 | bare |
| `test_menu_continue_stream_1195.py` | 事件屏障 | 缺陷 | bare |
| `test_menu_lifecycle_drain_396.py` | 事件屏障 | 缺陷 | bare；负向见 B |
| `test_month_loop_tracer_1468.py` | 事件屏障 | 缺陷 | bare |
| `test_pihong_dossier_1490.py` | 事件屏障 | 缺陷 | bare；single-flight 见 B |
| `test_qa_b3_409_ux.py` | 事件屏障 | 缺陷 | bare |
| `test_qa_c2_phase_settlement_mask_1374.py` | 事件屏障 | 缺陷 | bare |
| `test_qa_c2_settlement_display_lifecycle_1343.py` | 事件屏障 | 缺陷 | bare；gate 终态保留 |
| `test_qa_c3_secret_order_path_1357_1376.py` | 事件屏障 | 缺陷 | bare join |
| `test_qa_t1_extraction_dual_source_1353.py` | 事件屏障 | 缺陷 | bare |
| `test_relation_brew_636.py` | 事件屏障 | 缺陷 | bare；死枝 `if not release.wait()` → `release.wait()` |
| `test_relation_judge_634.py` | 事件屏障 | 缺陷 | bare |
| `test_rescript_fanout_656.py` barrier.wait(30) | 事件屏障 | 缺陷 | bare |
| `test_session_cli_fallback.py` | 事件屏障 | 缺陷 | bare |
| `test_session_write_queue_1353.py` 大量 | 事件屏障 | 缺陷 | bare |
| `test_settlement_write_guard_393.py` | 事件屏障 | 缺陷 | bare |
| `test_web_audience_night_498.py` | 事件屏障 | 缺陷 | bare；issue 进屏障观测见 B |
| `test_web_chat_serialization_393.py` | 事件屏障 | 缺陷 | bare；epilogue 争锁见 B |
| `test_faction_brew_637.py` Barrier timeout | 事件屏障 | 缺陷 | 去 timeout |

---

## B. 负向时序 / 竞态证法 — 灰区「打；改事件/状态证法」；**须证明已抵竞争接缝**

| 位置 | Q1 | Q2 | Q3 | 判定 | 处置 |
| --- | --- | --- | --- | --- | --- |
| `menu_lifecycle` 持闸 drain/shutdown `not done.is_set` | 无 | 持闸不得完成 | 是 | **缺陷（空窗 is_set）** | `wait_until(has_open_barrier)` 后再负向断言 |
| `menu_lifecycle` drain vs 在飞 B `:668/:675` | 无 | drain 不得先于 B 票清 | 是 | **缺陷（空窗）** | barrier 票 open 后再断言；B delta 保留 |
| `enter_settlement` / `qa_c2` clear 持闸 | 无 | clear 须持 gate | 是 | **有效** | **保留**：除 `not done` 外有快照未清 / `clear_saw_gate` 终态 |
| `travel_gating` close vs 未完 scene `:1378/:1423` | 无 | barrier 不得越过未完 scene | 是 | **缺陷（空窗）** | `wait_until(has_open_barrier)` 后再 `not close_entered` |
| `web_chat_serialization` stream vs settlement | 无 | epilogue 须等 gate | 是 | **缺陷（未争锁就 release）** | `_ObservingWriteGate`：holding 下 acquire → `epilogue_contending` 后再放行 |
| `web_audience_night` issue vs 在飞 chat `:703` | 无 | issue 须进屏障等票 | 是 | **缺陷（create_task 后即查 done）** | `wait_prior` 观测 inflight>1 后再 `not issue_task.done()` |
| `pihong` single-flight 第二路 `:4207` | 无 | 第二路须进 entry 才 coalesce | 是 | **缺陷（run 前 set submitted）** | `_begin_settlement_entry` inflight≥2 → `second_entered` |
| `beat` sibling join `:98-105` | 无 | join 须排空 sibling | 是 | **缺陷（未入 join 体）** | `join_entered` 后再 `is_alive` + outcome 空 |
| `beat` close gen_done 后 is_alive | 无 | persist 须等 gate | 是 | **缺陷（偏空）** | gen_done + worker 活 + **卷轴/夜状态仍无 exit** |
| `web_chat` drain vs 非流式 chat | 无 | drain 等票 | 是 | 缺陷→已改 | sealed 观测 + `not drain_done` |

**不造**：生产测试钩子、墙钟终线、杀进程护栏、平行证明套件。

---

## C. sleep — 按性质全部分诊（不得用 delay 变量名规避）

### C1. 曾误标「赌调度」→ 实为扩大竞态观察窗（**不是**生产超时输入）

| 位置 | 三问 | 灰区归属 | 判定 | 处置 |
| --- | --- | --- | --- | --- |
| `beat_orchestration_503` `:364` `slow_discover` sleep(0.05) | Q1 无；Q2 不变式=discover 原子 claim 次数，不拥有秒表；Q3 是 | **扩大 discover 竞态观察窗** | 观察窗 sleep，**非**生产超时 | 保留 sleep 作重叠窗；断言落 `discover_calls==1`（已有） |
| `parallel_extractors` `:164` sleep(delay) | 同上 | **扩大峰值并发观察窗** | 观察窗 | 保留 sleep；断言 `max_active>=2`；**删** elapsed 墙钟（E） |
| `parallel_extractors` `:186` sleep(0.05) 串行 | 同上 | 串行路径观察窗 | 观察窗 | 保留；`max_active==1` |

> 初稿 D 节把 parallel sleep 写成「假慢触发生产超时 / 合法保留」**错类**——生产路径无 timeout 读这些 sleep。本局纠正为 C1 观察窗。

### C2. 真·赌调度（已改状态/事件）

| 位置 | 判定 | 处置 |
| --- | --- | --- |
| `audience_extraction_501` sleep(0.05) 赌第二路 | 缺陷 | `len(seen)==1` |
| `enter_settlement` sleep 赌 A 未完 | 缺陷 | `not a_done.is_set()` |
| `pihong` sleep 赌 coalesce | 缺陷 | `second_entered` 事件（本局） |
| `web_audience_night` sleep 赌 issue 入队 | 缺陷 | 屏障 inflight 观测（本局） |
| `web_audience_night` sleep 赌 ticker | 缺陷 | `while ticks<5: sleep(0)` |
| `web_chat_serialization` settlement/SSE sleep | 缺陷 | holding/release/entered 事件 |
| `menu_continue_stream` deadline+sleep | 缺陷 | 无时限 poll |

### C3. backoff（合法）

| 位置 | 判定 |
| --- | --- |
| `wait_until` / 旧 `_wait_for` 内 `poll.wait(0.01)` / `sleep(0.01)` | backoff，非正确性 deadline |
| `asyncio.sleep(0)` 让出循环 | 灰区不打 |
| `beat` open/enter 并发 `while max_active<2: sleep(0.01)` | backoff 等状态 |

---

## D. sleep 假慢协作方 → **生产有界超时输入**（灰区「不打」）

| 位置 | 归属 | 判定 |
| --- | --- | --- |
| `test_qa_d1_decree_normalize_1274.py` sleep(2)+`capture_timeout_s=0.3` | 假慢→生产超时路径 | **合法保留** |
| `test_qa_v1_participant_heal_retry.py` sleep(1.5)+短 capture_timeout | 同上 | **合法保留** |

### D′. 终态顺序契约（**不是**生产超时行）

| 位置 | 三问 | 归属 | 判定 |
| --- | --- | --- | --- |
| `session_write_queue_1353` `:289` `sleep(slow_s=0.08)` | Q1 无；Q2 不变式=`order==[worker_terminal,barrier]`，**不**读生产 `DEFAULT_TICKET_WAIT_S` 熔断；Q3 是 | **慢工人终态顺序** | 合法保留 sleep 作假慢工人；**初稿「触发生产超时」豁免撤销**——本测证明屏障**不按 elapsed 失败**，属终态顺序契约，不是 timeout 输入行 |

---

## E. 以墙钟为行为证据的断言

| 位置 | 判定 | 处置 |
| --- | --- | --- |
| `parallel_extractors` `elapsed < delay * N` | 缺陷 | **删**；保留 max_active |
| `qa_b3` `elapsed < 1.5` + wait_for | 缺陷 | 已删 |

---

## F. `_wait_for` / Barrier(timeout=) / future.result(timeout) / Lock.acquire(timeout) / asyncio.wait_for

| 形状 | 判定 | 处置 |
| --- | --- | --- |
| 三份同步 `_wait_for`（audience_background / menu_lifecycle / web_chat_serialization） | 重复 | **合并** → `tests/wait_utils.wait_until`；异步 `web_audience_night._wait_for` **不强并** |
| `threading.Barrier(n, timeout=N)` | 缺陷 | 去 timeout；657 参与者数见 H |
| `future.result(timeout=N)` 测侧 | 缺陷 | bare `result()` |
| `Lock.acquire(timeout=0.3)` | 缺陷 | `acquire(blocking=False)` |
| `asyncio.wait_for(task, timeout=N)` 等测任务 | 缺陷 | bare await |
| `q.wait_idle(timeout_s=5)` | 缺陷 | bare |
| `wait_pending_writes(..., timeout_s=0.05)` 负向 helper | **被测输入** | 合法保留 |

---

## G. 配置 / API 透传（灰区「不打」）

| 位置 | 判定 |
| --- | --- |
| `cli_backend` `CliChat(..., timeout=111/…)` / `_iter_codex_stream_chunks(..., timeout=0.2)` | 合法保留 |
| `minister_chat_timeout` / TimeoutExpired 生产路径 | 合法保留 |
| `registry.join(11)` / `_scene_registry.join(1)` scene id | **非 timeout** |

---

## H. dead-leg / 会合屏障 / 本局必修

| 项 | 判定 | 处置 |
| --- | --- | --- |
| beat 6× `print("MAIN …")` | 调试残留 | 已剔 |
| beat 持闸 `worker.join()` | 自锁 | gen_done + 状态；持闸不 join |
| beat stream join mock 靠 abandon timeout | 挂 | atomic nullcontext + trail stub |
| beat phase1 crash drain | 自锁 | close 改 worker 线程 |
| **beat 657** `Barrier(2)` 含 open 共 3 gen | **错参与者 + 删屏障 + 放松断言** | 诊断：open×1+enter×2；**Barrier(2) 仅两 target enter**；恢复 `join_saw_free == [True, True]`；禁 max_active 碰运气 / 非空 all |
| menu `_wait_for` assert None | 恒红 | 去 assert |
| court_break_1727 | main 新文件 | bare |
| parallel elapsed | 墙钟证据 | 删 |
| relation_brew 死枝 | bare 后死 | `release.wait()` |
| 失效 `import time` | 死 import | 删 audience_extraction / pihong×2 / qa_b3 / qa_t1；**menu_lifecycle 的 time 供 :390/:420 monkeypatch，保留** |

---

## I. 检索面与覆盖声明

- 本清单覆盖：`tests/test_*.py` 在 `ec65c824` / `a626c7e14` / 本片 HEAD 的 wait/timeout/sleep 命中，加 main 并入新文件与 drift 重判。
- 生产代码超时、CI job 终线：不在范围。
- #1726 未读数双实现：已由 **PR #1741 / fix/1740-w / `32db0d7f1`** 结清；本腿不重做。
- #1725 typed 结算进度全链：本轮 **不施工**（待 owner 裁定落点）。
