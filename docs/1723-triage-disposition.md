# #1723 分诊处置清单

法源：票面类定义 + 分诊三问 + 灰区口径表；样板 `f684ede49`；Q1 无挂起证据 ≠ 保留护栏（无依据则删）。
CI 终线：`ci.yml` `timeout-minutes: 20`（现行 :19，实质成立）。

三问缩写：
- Q1 有无已发生可复现永久挂起/误报证据？
- Q2 接缝不变式是否声称「N 秒内完成」？
- Q3 CI 20min 是否已承接最终挂死？

---

## 0. 扫描 revision、原始命令与计数差异

### 固定 revision（HEAD 不可作冻结）

| rev | 角色 |
| --- | --- |
| `ec65c824` | #1721 合入后、#1723 改动前基点（本清单命中展开的冻结 SHA） |
| `a626c7e14` | 本片父 commit（merge #1735）对照 |
| `faf4bddec` | 本片首修（墙钟→事件/状态；分诊草稿同 commit） |

### 原始扫描命令（逐行 regex，`tests/test_*.py` 顶层）

**注意**：`wf`/`tf`/`sf` 必须是**三个独立 set()**。错误写法 `wf=tf=sf=set()` 让三个名字指向同一对象，文件计数变成 35 并集，不可复现票面分项文件数。

```bash
.venv/bin/python - <<'PY'
import re, subprocess
def count(rev):
    files = [l for l in subprocess.check_output(
        ['git','ls-tree','-r','--name-only',rev,'tests'], text=True
    ).splitlines() if re.match(r'tests/test_[^/]+\.py$', l)]
    w=t=s=0
    wf=set(); tf=set(); sf=set()  # three independent sets — never wf=tf=sf=set()
    for path in files:
        text = subprocess.check_output(['git','show',f'{rev}:{path}'], text=True)
        for line in text.splitlines():
            if re.search(r'wait\(\s*\d', line):
                w += 1; wf.add(path)
            if re.search(r'timeout\s*=\s*\d', line):
                t += 1; tf.add(path)
            if re.search(r'\bsleep\s*\(', line):
                s += 1; sf.add(path)
    print(f'{rev[:12]} wait={w}/{len(wf)} timeout={t}/{len(tf)} sleep={s}/{len(sf)} top_files={len(files)} union={len(wf|tf|sf)}')
count('ec65c824'); count('a626c7e14')
PY
```

### 计数对照

| rev | wait(数字) 行/文件 | timeout=数字 行/文件 | sleep( 行/文件 |
| --- | --- | --- | --- |
| 票面口述 | 152 / — | 86 / — | 28 / 10 文件 |
| `ec65c824` 实测（独立 set） | **151 / 21** | **86 / 21** | **28 / 12** |
| `a626c7e14` 实测（独立 set） | **151 / 21** | **89 / 22** | **28 / 12** |
| 错误别名 `wf=tf=sf=set()` | — | — | 并集文件 **35**（不可当分项） |

**差异说明（不伪造凑数）**：

- 票面「152」与实测 151 差 1：原票未附原始命令；本清单以可复现 regex + 固定 SHA 为准，不回填臆造命中。
- 票面 sleep「10 文件」vs 实测 12：同因——原命令未冻结；本清单按 `tests/test_*.py` + `\bsleep\(` 计 12。
- `a626c7e14` timeout 89/22 vs `ec65c824` 86/21：主线并入邻票测试新增 `timeout=` 配置/API 透传与夹具，**不是** #1723 本体回潮。
- 检索面 ≠ 缺陷数：配置透传、生产超时输入、backoff、scene id 形参均会命中 regex。

### 真实时序（清单为首轮之后补作——不伪造「先分诊后施工」历史）

1. **dead-leg drift**（`faf4bddec` 之前未合入草稿）：在工作树直接改 wait/join/sleep，含调试 print、持闸 join 自锁、#657 Barrier 错参与者等。**无**独立「先写完整清单」commit。
2. **`faf4bddec`**：同 commit 交付 `docs/1723-triage-disposition.md` + 测试改动。同 commit **不证明**「先写清单再改代码」；只证明清单与改动一并落地。
3. **判牒 r2 / r3 补卷**：在已落地改动上补竞态证法、sleep 重分诊、恢复 657 屏障，并**事后**以固定 SHA 展开完整位置清单。  
   **本清单明确为首轮施工之后补作的举证文件**——不得声称事后扫描补齐了「先分诊后施工」的历史事实；只补齐可核位置与三问，不改写 git 历史。

---

## 三问真源（同答案引用，位置不省略）

| 真源 ID | Q1 | Q2 | Q3 | 灰区归属 | 判定 |
| --- | --- | --- | --- | --- | --- |
| **T-barrier** | 无已复现永久挂起 | 并发/生命周期顺序屏障，不声称「N 秒内」 | 是，CI 承接挂死 | 事件/线程屏障 | **缺陷** → bare `wait()`/`join()`；负向改事件/状态证 |
| **T-neg-race** | 无 | 须证明已抵竞争接缝再负向断言 | 是 | 竞态证法 | **缺陷** → 完成事件/持锁观测/wait_prior 观测；禁调用前信号、禁 has_open_barrier 等同 wait |
| **T-gate-final** | 无 | clear/exit 须持 gate 的终态 | 是 | 持闸终态 | **有效保留**（除 not-done 外有快照/clear_saw_gate） |
| **T-sleep-race** | 无 | 不拥有秒表；赌调度/观察窗 | 是 | sleep 赌窗 | **缺陷** → 事件/状态/会合；删 sleep 观察窗 |
| **T-sleep-backoff** | 无 | backoff/让出，非正确性 deadline | 是 | backoff | **合法保留** `sleep(0)` / 短 poll backoff |
| **T-prod-timeout** | 无 | 假慢触发生产有界超时输入 | 是 | 生产超时输入 | **合法保留** |
| **T-wall-elapsed** | 无 | 以墙钟 elapsed 为行为证据 | 是 | 墙钟断言 | **缺陷** → 删 |
| **T-wait-dup** | 无 | 三份同步 `_wait_for` 重复 | 是 | 测试支持 | **合并** → `wait_utils.wait_until` |
| **T-barrier-to** | 无 | `Barrier(..., timeout=N)` | 是 | 屏障 timeout | **缺陷** → 去 timeout |
| **T-config** | 无 | 配置/API 形参透传 | — | 配置透传 | **不打** |
| **T-scene-id** | 无 | `join(scene_id)` 非 timeout | — | scene id | **非 timeout 命中**（regex 误伤说明） |

---

## A. Event.wait(N) / Thread.join(N) — 灰区「打 timeout 参数，保留屏障」

冻结 SHA：`ec65c824`。共 **151 行 / 21 文件**。默认真源 **T-barrier**（每命中位置列出；理由同真源不重抄）。

| 位置（`ec65c824`） | 真源 | 判定 | 处置 |
| --- | --- | --- | --- |
| `test_action_cluster_registry_515.py:760,767,769` | T-barrier | 缺陷 | bare `wait()` |
| `test_audience_background.py:209,288,576,596,624` | T-barrier | 缺陷 | bare `wait()` |
| `test_audience_extraction_501.py:283,302` | T-barrier | 缺陷 | bare |
| `test_audience_travel_gating_670.py:1356,1373,1379,1405,1418,1424,1452,1473,1526,1542` | T-barrier；负向 :1379,:1424 另见 B | 缺陷 | bare；负向改 wait_prior 观测 |
| `test_beat_orchestration_503.py:46,53,77,86,146,180,205,410,430,455,469,795,805,1585,1593,1672,1690,1721,1771,2026,2070,2090,2131,2149` | T-barrier；join 负向见 B；657 见 H | 缺陷 | bare；竞态见 B |
| `test_chat_stream_failpaths_393.py:323,394` | T-barrier | 缺陷 | bare |
| `test_cli_backend.py:864` | T-barrier | 缺陷 | bare `killed.wait()` |
| `test_dossier_endorsements_612.py:352,389,467,479,507,511,540,545` | T-barrier | 缺陷 | bare |
| `test_enter_settlement_period_1235.py:658,661,763,805,829,856,865,867,922,950,983` | T-barrier；持闸终态见 B/T-gate-final | 缺陷/有效 | bare；gate 终态保留 |
| `test_menu_lifecycle_drain_396.py:22,43,48,403,409,506,670,678,682,719` | T-barrier；:22 为 poll backoff 见 C3；负向见 B | 缺陷 | bare；backoff 保留；负向改 gate/wait_prior 观测 |
| `test_pihong_dossier_1490.py:4188,4215,4261,4267,4280,4358,4366,4409,4420` | T-barrier；single-flight 见 B | 缺陷 | bare；join 观测见 B |
| `test_qa_b3_409_ux.py:280,309,318` | T-barrier | 缺陷 | bare |
| `test_qa_c2_phase_settlement_mask_1374.py:118` | T-barrier | 缺陷 | bare |
| `test_qa_c2_settlement_display_lifecycle_1343.py:109,113` | T-barrier / T-gate-final | 缺陷/有效 | bare；gate 终态保留 |
| `test_qa_t1_extraction_dual_source_1353.py:80,110,774,780,803,827,840,863,865,879,898,899,933,947,1120` | T-barrier | 缺陷 | bare |
| `test_relation_judge_634.py:547,548,553,568,702,710` | T-barrier | 缺陷 | bare |
| `test_session_cli_fallback.py:2250` | T-barrier | 缺陷 | bare |
| `test_session_write_queue_1353.py:52,59,69,85,106,123,127,160,167,179,239,241,249,267,268,296,317,323,338,350,360,361,389,396,409,433,439,455` | T-barrier | 缺陷 | bare |
| `test_settlement_write_guard_393.py:382,402` | T-barrier | 缺陷 | bare |
| `test_web_audience_night_498.py:102,418` | T-barrier | 缺陷 | bare |
| `test_web_chat_serialization_393.py:34,219,371,419,435,439` | T-barrier；争锁见 B | 缺陷 | bare；ObservingWriteGate |

**另**：timeout= 行里的 `Event.wait`/`join`/`Barrier` 形参见 F；arrival/pipeline/highlight 等仅 timeout= 命中、无 wait(数字) 的文件见 F 表。

---

## B. 负向时序 / 竞态证法 — 灰区「打；改事件/状态证法」；**须证明已抵竞争接缝**

真源默认 **T-neg-race**。

| 位置 | Q1 | Q2 | Q3 | 判定 | 处置（本轮） |
| --- | --- | --- | --- | --- | --- |
| `menu_lifecycle` 持闸 drain/shutdown | 无 | close 须 `gate.acquire` | 是 | 缺陷 | **ObservingGate.contending**：drain 真到 close acquire；**不用** has_open_barrier 冒充 wait |
| `menu_lifecycle` drain vs 在飞 B | 无 | drain 不得先于 B 票清 | 是 | 缺陷 | **observe `wait_prior`** 后再负向；B delta 保留 |
| `enter_settlement` / `qa_c2` clear 持闸 | 无 | clear 须持 gate | 是 | **有效** | **保留** T-gate-final |
| `travel_gating` close vs 未完 scene | 无 | barrier 不得越过未完 scene | 是 | 缺陷 | **observe `wait_prior`**（非 has_open_barrier 领票） |
| `web_chat_serialization` stream vs settlement | 无 | epilogue 须等 gate | 是 | 缺陷 | `_ObservingWriteGate`：holding 下 acquire → contending |
| `web_audience_night` issue vs 在飞 chat | 无 | issue 须进屏障等票 | 是 | 缺陷 | `wait_prior` 观测 inflight>1 |
| `pihong` single-flight 第二路 | 无 | 第二路须抵真实等待接缝才 coalesce | 是 | 缺陷 | **最小诊断**：B 在 A 的 `join_retained` 窗内卡在 entry 的 `_auto_close_open_night_gate_free`（等 A 召见 scene/夜在飞），并发 `join_retained` 架构上不可达；观测 B 在 gen 仍持时进入 auto_close；**不用** `_begin_settlement_entry` 入口记账，也**不**假造并发 join 观测 |
| `beat` sibling join | 无 | join 须排空 sibling | 是 | 缺陷 | `wait_until(not registry.has(11))` 证 join 已 pop 入 drain；**禁止** join 调用前 `join_entered.set()` |
| `beat` close 持闸 persist/cleanup | 无 | 须抵达 write_gate.acquire | 是 | 缺陷 | **ObservingGate.contending**；**不用** gen_done+is_alive+gate.locked 空窗 |
| `web_chat` drain vs 非流式 chat | 无 | drain 等票 | 是 | 缺陷 | sealed 观测 + not drain_done |

**不造**：生产测试钩子、墙钟终线、杀进程护栏、平行证明套件、调用前信号、保持锁定状态替代抵达证明。

**变异要求**：现有入口须能咬住「跳过等待／提前传播」类生产错误（不能只交正常绿）。

---

## C. sleep — 按性质全部分诊（不得用 delay 变量名规避）

冻结 SHA：`ec65c824`。共 **28 行 / 12 文件**。

### C1. 观察窗 sleep（票面明打的赌调度窗——**不是**合法新灰区）

| 位置（`ec65c824`） | 三问 | 灰区 | 判定 | 处置 |
| --- | --- | --- | --- | --- |
| `beat_orchestration_503:365` `slow_discover` sleep(0.05) | T-sleep-race | 赌/扩大 claim 观察窗 | **缺陷** | **删 sleep**；claim 已锁内原子，断言 `discover_calls==1` |
| `parallel_extractors:164` sleep(delay) | T-sleep-race | 赌峰值并发观察窗 | **缺陷** | **Condition 会合**至 active≥2；断言 max_active≥2 |
| `parallel_extractors:190` sleep(0.05) | T-sleep-race | 串行路径无必要 delay | **缺陷** | **删 sleep**；断言 max_active==1 |

> 曾误标「扩大观察窗故保留」——改名不构成修复。冻结票面含「以 sleep 赌调度窗口或竞速」一律打。

### C2. 真·赌调度（已改状态/事件）— 逐项三问

| 位置（`ec65c824`） | Q1 | Q2 | Q3 | 灰区 | 判定 | 处置 |
| --- | --- | --- | --- | --- | --- | --- |
| `audience_extraction_501:303` sleep(0.05) | 无 | 赌第二路 | 是 | 赌调度 | 缺陷 | `len(seen)==1` 状态 |
| `enter_settlement_period_1235:858,979` sleep(0.05) | 无 | 赌 A 未完/时序 | 是 | 赌调度 | 缺陷 | `not a_done` / 事件 |
| `enter_settlement_period_1235:752` sleep(0.01) | 无 | 短延迟 | 是 | 近 backoff/赌窗 | 缺陷 | 事件/状态 |
| `pihong_dossier_1490:4217` sleep(0.15) | 无 | 赌 coalesce 窗 | 是 | 赌调度 | 缺陷 | join 并发观测 |
| `pihong_dossier_1490:3052` sleep(0.02) | 无 | 短延迟 | 是 | 赌调度 | 缺陷 | 事件 |
| `web_audience_night_498:711,758` sleep | 无 | 赌 issue/ticker | 是 | 赌调度 | 缺陷 | wait_prior / `sleep(0)` 让出 |
| `web_chat_serialization_393:203,220,265` sleep | 无 | 赌 settlement/SSE | 是 | 赌调度 | 缺陷 | holding/release/contending |
| `menu_continue_stream_1195:168,239` sleep | 无 | deadline+sleep 轮询 | 是 | 赌调度 | 缺陷 | 无时限 poll |

### C3. backoff（合法）— 逐项三问

| 位置（`ec65c824`） | Q1 | Q2 | Q3 | 灰区 | 判定 |
| --- | --- | --- | --- | --- | --- |
| `audience_background:169,182` sleep(0.01) | 无 | poll backoff | 是 | T-sleep-backoff | 合法 |
| `beat_orchestration_503:220` sleep(0.01) | 无 | 等 max_active 状态 | 是 | backoff | 合法 |
| `web_audience_night_498:224,748` asyncio.sleep(0/0.01) | 无 | 让出循环 | 是 | 让出 | 合法 |
| `web_chat_serialization_393:277,350` sleep(0.01)/asyncio.sleep | 无 | 让出/backoff | 是 | backoff | 合法 |
| `menu_lifecycle:22` poll.wait(0.01)（wait 命中） | 无 | backoff | 是 | backoff | 合法 |
| `wait_utils.wait_until` poll.wait(0.01) | 无 | 共享 backoff | 是 | backoff | 合法 |

---

## D. sleep 假慢协作方 → 生产有界超时输入（灰区「不打」）— 逐项三问

| 位置（`ec65c824`） | Q1 | Q2 | Q3 | 归属 | 判定 |
| --- | --- | --- | --- | --- | --- |
| `test_qa_d1_decree_normalize_1274.py:201,236` sleep(2)+短 capture_timeout | 无 | 假慢→生产超时路径 | 是 | T-prod-timeout | **合法保留** |
| `test_qa_v1_participant_heal_retry.py:607` sleep(1.5)+短 capture_timeout | 无 | 同上 | 是 | T-prod-timeout | **合法保留** |

### D′. 终态顺序契约（**不是**生产超时行；**不是**「超过旧 30s 熔断」证明）

| 位置（`ec65c824`） | Q1 | Q2 | Q3 | 归属 | 判定 | 处置 |
| --- | --- | --- | --- | --- | --- | --- |
| `session_write_queue_1353:286` sleep(slow_s=0.08) | 无 | 不变式=`order==[worker_terminal,barrier]`，**不**读生产熔断秒数 | 是 | 慢工人终态顺序 | 曾误标超时输入 | **改**：worker 事件持票 + observe `wait_prior`；**删 sleep**；doc 去掉「超过旧 30s」 |
| `session_write_queue_1353:312` sleep(0.02) | 无 | 短延迟 | 是 | 视具体测 | 按测改事件或保留 backoff 说明 | 核后按事件/backoff 归类 |

---

## E. 以墙钟为行为证据的断言

| 位置 | 真源 | 判定 | 处置 |
| --- | --- | --- | --- |
| `parallel_extractors` `elapsed < delay * N` | T-wall-elapsed | 缺陷 | **删**；保留 max_active |
| `qa_b3` `elapsed < 1.5` + wait_for | T-wall-elapsed | 缺陷 | 已删 |

---

## F. `_wait_for` / Barrier(timeout=) / future.result(timeout) / Lock.acquire(timeout) / asyncio.wait_for

冻结 SHA timeout= 命中：**86 行 / 21 文件**。逐文件三问归类（同真源引用）。

| 位置（`ec65c824`） | 行 | 真源/性质 | 判定 | 处置 |
| --- | --- | --- | --- | --- |
| `test_arrival_dual_voice_671.py` | 192,193,198 | T-barrier 类 wait timeout | 缺陷 | bare |
| `test_audience_pipeline_499.py` | 127,186,221,381,387,451,460,462 | T-barrier / 任务 wait | 缺陷 | bare |
| `test_beat_orchestration_503.py` | 181,282,909,1673,1691,1756,1808,1895,2383,2391 | T-barrier；657 Barrier 见 H | 缺陷 | bare；657 参与者修正 |
| `test_chat_stream_failpaths_393.py` | 137,150,168,326,395 | 任务/wait | 缺陷 | bare |
| `test_cli_backend.py` | 893,1360,1361,1362,1720 | **T-config** 为主（CliChat timeout 透传） | 不打/分项 | 配置保留；非配置 bare |
| `test_dossier_links_559.py` | 595 | wait timeout | 缺陷 | bare |
| `test_faction_brew_637.py` | 316 | T-barrier-to | 缺陷 | 去 Barrier timeout |
| `test_highlight_judge_544.py` | 49,224,307 | wait timeout | 缺陷 | bare |
| `test_menu_continue_stream_1195.py` | 130,149,157,188,218,229 | wait/poll | 缺陷 | bare / 无时限 poll |
| `test_menu_lifecycle_drain_396.py` | 674 | 负向 wait timeout | 缺陷 | 改事件证法 |
| `test_month_loop_tracer_1468.py` | 219,223,269 | 任务 wait | 缺陷 | bare |
| `test_pihong_dossier_1490.py` | 4219 | 并发 wait | 缺陷 | 改 join 观测 |
| `test_qa_b3_409_ux.py` | 203 | wait | 缺陷 | bare |
| `test_qa_c3_secret_order_path_1357_1376.py` | 185 | join timeout | 缺陷 | bare join |
| `test_qa_t1_extraction_dual_source_1353.py` | 128,129,804,805,844,900,901,948,1121 | wait/join；部分 helper 输入 | 缺陷/输入 | bare；负向 helper 输入保留 |
| `test_relation_brew_636.py` | 467,516,524,903 | wait；死枝 | 缺陷 | bare；`release.wait()` |
| `test_rescript_fanout_656.py` | 38 | Barrier timeout | 缺陷 | bare |
| `test_runtime_llm_config.py` | 40 | **T-config** | 不打 | 保留 |
| `test_session_write_queue_1353.py` | 86,87,105,112,185,186,269,270,362,363,413,414,456,457 | wait；`wait_idle(timeout_s=)` 负向输入 | 缺陷/输入 | bare；负向 timeout_s 保留 |
| `test_settlement_write_guard_393.py` | 349,357,405,414,463,471 | wait/acquire | 缺陷 | bare / nonblocking |
| `test_web_audience_night_498.py` | 716,762 | wait | 缺陷 | bare |

**形状汇总**：

| 形状 | 判定 | 处置 |
| --- | --- | --- |
| 三份同步 `_wait_for`（audience_background / menu_lifecycle / web_chat_serialization） | T-wait-dup | **合并** → `tests/wait_utils.wait_until`；异步 `web_audience_night._wait_for` **不强并** |
| `threading.Barrier(n, timeout=N)` | T-barrier-to | 去 timeout；657 参与者数见 H |
| `future.result(timeout=N)` 测侧 | 缺陷 | bare `result()` |
| `Lock.acquire(timeout=0.3)` | 缺陷 | `acquire(blocking=False)` |
| `asyncio.wait_for(task, timeout=N)` 等测任务 | 缺陷 | bare await |
| `q.wait_idle(timeout_s=5)` | 缺陷 | bare |
| `wait_pending_writes(..., timeout_s=0.05)` 负向 helper | **被测输入** | 合法保留 |

---

## G. 配置 / API 透传（灰区「不打」）— 逐项三问

| 位置 | Q1 | Q2 | Q3 | 判定 |
| --- | --- | --- | --- | --- |
| `cli_backend` `CliChat(..., timeout=111/…)` / `_iter_codex_stream_chunks(..., timeout=0.2)` | 无 | 配置形参透传，非测试墙钟护栏 | — | **合法保留** |
| `minister_chat_timeout` / TimeoutExpired 生产路径 | 无 | 生产超时契约 | — | **合法保留** |
| `runtime_llm_config` timeout 字段 | 无 | 配置 | — | **合法保留** |
| `registry.join(11)` / `_scene_registry.join(1)` scene id | 无 | **非 timeout 秒数**（T-scene-id） | — | **非 timeout**；若 regex 误伤仅说明 |

---

## H. dead-leg / 会合屏障 / 既结

| 项 | 判定 | 处置 |
| --- | --- | --- |
| beat 6× `print("MAIN …")` | 调试残留 | 已剔 |
| beat 持闸 `worker.join()` | 自锁 | ObservingGate contending；持闸不 join |
| beat stream join mock 靠 abandon timeout | 挂 | atomic nullcontext + trail stub |
| beat phase1 crash drain | 自锁 | close 改 worker 线程 |
| **beat 657** `Barrier(2)` 含 open 共 3 gen | **错参与者** | **本类已结**：Barrier(2) 仅两 target enter；`join_saw_free == [True, True]` |
| menu `_wait_for` assert None | 恒红 | 去 assert |
| court_break_1727 | main 新文件 | bare |
| parallel elapsed | 墙钟证据 | 删 |
| relation_brew 死枝 | bare 后死 | `release.wait()` |
| 失效 `import time` | 死 import | 删；**menu_lifecycle 的 time 供 monkeypatch，保留** |
| 同步 wait helper 三合一 | 重复 | **本类已结**：`tests/wait_utils.py` |

---

## I. 检索面与覆盖声明

- 本清单覆盖：`tests/test_*.py` 在冻结 SHA **`ec65c824`** 的 wait/timeout/sleep **全部命中位置**（上表逐文件列行号），加后续 drift/main 并入文件的重判说明。
- **HEAD 不是冻结 revision**；施工后行号可能漂移，对账以 SHA + 命令复现。
- 生产代码超时、CI job 终线：不在范围。
- #1726 未读数双实现：已由 **PR #1741 / `32db0d7f1`** 结清；本腿不重做。
- #1725 typed 结算进度：生产主链已改向；贯通证明落现有 App 入口测试（SSE→progressbar），组件 happy-path 并入 App，组件负向保留。

---

## J. 扫描程序缺陷备忘

```python
# WRONG — three names, one set → union file count 35
wf = tf = sf = set()

# RIGHT
wf = set(); tf = set(); sf = set()
```

判官独立复核：`ec65c824` → wait 151/21、timeout 86/21、sleep 28/12；错误别名并集 35。本清单以 RIGHT 口径为准。
