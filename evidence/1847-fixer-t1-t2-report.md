# #1847 修内司 T1/T2 交卷报告

- worktree: `/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- branch: `ak-roles/1847-fixer-w7-n6-n11-n13-n14`（非默认分支，未切）
- 判词: `/tmp/1847-t1-t2-dispatch.json`（未结仅 T1/T2；已签署类不动）
- 禁令: 未 amend / rewrite / push / stash / PR；未跑全量；未执行旧带 pkill 探针；未跑旧强杀变异

## 已撤回表述（不得静默洗白）

撤回上一终局回执中下列失实表述（旧探针未经核对）：

1. 「本轮没有发送真实 SIGKILL」／「不声称本轮…无真实 SIGKILL」若被理解为**探针运行亦无 SIGKILL** —— 假。
2. 「忽略 SIGTERM 的自建进程自然退出」—— 假。旧 `n13_lifecycle_probe.py` 以 `_sweep`→`pkill -9 -f 'time.sleep\\(120\\)'`（第 31–37 行，调用于 127/164/226）**真实 SIGKILL** 按全系统命令行模式收场。
3. 旧 `n13_lifecycle_probe.json`（含 `cleanup_error_type` 等）不得当作「无强杀／自然退出」证明。

**新证据只证明修正后这次**（见下文命令与输出）。冻结历史文档（w5/w6 旧报告等）不改写。

当前回执已更正处：

- `evidence/1847-fixer-current-report.md`（N13 T1/T2 撤回段）
- `evidence/1847-w7-correction/CORRECTION.md`
- `evidence/1847-w7-correction/human_n13.tsv`（去掉死字段叙述）
- `evidence/1847-w7-correction/n13_lifecycle_probe.json`（`_meta.withdrawn_prior_claim` + 修正后 results）

## T1 — 证据探针去强杀

| 项 | 结果 |
|---|---|
| 删除 `_sweep` / `pkill -9` 及全部调用 | 是（现仅 docstring/撤回叙述提及） |
| IGNORER 忽略 HUP/INT/TERM，数秒后 `sys.exit(0)` | `time.sleep(8)` 后 exit 0 |
| 持有自己 Popen/spawn 句柄 wait | 是；不按进程名搜索/杀/清 |
| 信号记录器不转发 OS SIGKILL | `record_kill` return None；`recorder_forwards_os_sigkill=false` |
| 不新增监管/重试 | 是 |
| 不动生产 `_terminate_cli_process` / `close(force=False)` 传播语义 | 是 |

## T2 — 删除死字段 `cleanup_error`

| 项 | 结果 |
|---|---|
| 删除 `_CliProcessOutcome.cleanup_error` 字段与赋值 | 是（`ming_sim/cli_backend.py`） |
| 保留 raise / add_note / stderr `[soft terminate failed: …]` | 是 |
| 探针改读 notes / stderr；断言字段不存在 | `cleanup_error_field_present=false` |
| `cli/terminal.py` 局部变量 `cleanup_error` | 无关，保留 |

## 机械枚举（证据强杀 / 假自然退出 / 死并行状态）

命令（本轮）：

```bash
# 可执行强杀形状（pkill / kill -9 / _sweep( / process.kill）
rg -n --glob '!node_modules/**' 'pkill|_sweep\s*\(|kill\s+-9' \
  evidence/ scripts/ tests/ ming_sim/ web_app.py launcher.py main.py

# 死字段消费者
rg -n 'cleanup_error' ming_sim/ evidence/ tests/ scripts/
```

### 实际成员表（按 T1/T2 boundary 裁决）

| 成员 | 类 | 处置 |
|---|---|---|
| `evidence/1847-w7-correction/n13_lifecycle_probe.py` 旧 `_sweep`+`pkill -9`×3 | 证据强杀 + 假自然退出 | **FIXED_T1**（已删；IGNORER 自退 + 句柄 wait） |
| 旧回执「无真实 SIGKILL／自然退出」（含曾写于 fixer-current / 0cc7a7521 N13 段） | 回执失实 | **WITHDRAWN**（当前回执更正；冻结历史不改） |
| `ming_sim/cli_backend.py` `_CliProcessOutcome.cleanup_error` + 赋值 | 死并行状态 | **FIXED_T2**（字段与赋值删除） |
| 探针读 `outcome.cleanup_error` | 死字段消费 | **FIXED_T2**（改读 notes/stderr） |
| `human_n13.tsv` 提及 cleanup_error 落点 | 回执失实 | **FIXED_T2**（改为 notes/stderr） |
| `cli_backend.py` 禁 SIGKILL 注释 | 文档 | KEEP_DOC（非可执行强杀） |
| `play_as_emperor.py` force=False / 禁 SIGKILL 注释 | 文档 | KEEP_DOC |
| `web_app.py` `os.kill(getpid(), SIGTERM)` | 自进程软退 | KEEP（已签署 N13 生产边界） |
| `ming_sim/cli/terminal.py` 局部名 `cleanup_error` | 无关异常链 | KEEP_UNRELATED |
| `evidence/1847-w5*` / `w6*` 历史成员表与报告中的 SIGKILL 字样 | 冻结历史 | KEEP_FROZEN（不改写） |
| 修正后探针 docstring / 回执撤回段提及 pkill | 诚实记载 | KEEP_WITHDRAWAL_NOTE |

**残余可执行 `pkill`/`_sweep(`/`kill -9` 定义或调用：0**（修后 rg 仅命中撤回叙述与 `used_pkill_or_sigkill: false` 键名）。

## 修正探针实测（七 false 前缀）

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  evidence/1847-w7-correction/n13_lifecycle_probe.py
```

- **exit**: 0
- **耗时**: `real 24.69` / `user 0.51` / `sys 0.07`
- **stderr**: `VERDICT GREEN`
- **禁止**: 未执行旧带 pkill 探针；未跑旧强杀变异；信号记录器未发真实 SIGKILL

### 关键结果摘录

| case | 关键证明 |
|---|---|
| `raise_cover_compare` | 旧 CleanupBoom 覆盖 BodyBoom；新 BodyBoom + note；sole cleanup 仍 raise（内存确定性，原失败语义） |
| `cli_terminate_soft_fail` | `err_type=TimeoutExpired`，`alive_after=true`，`elapsed=5.01`，随后 `natural_exit_rc=0`，`natural_wait_elapsed=3.04`，`used_pkill_or_sigkill=false` |
| `cli_iterator_body_and_cleanup` | `TransportIdleTimeout` + notes「soft terminate also failed」+ `stderr_marker=true`；`cleanup_error_field_present=false`；`covered_by_cleanup_only=false`；自然退出 rc=0 |
| `pty_soft_close` | 记录 SIGHUP→SIGCONT→SIGINT；`sigkill_in_soft_path=false`；`os_signals_sent=0`；`natural_exit_rc=0`；`recorder_forwards_os_sigkill=false` |

全文：`/tmp/1847-fixer-t1-t2/n13_probe_stdout.txt`；仓内：`evidence/1847-w7-correction/n13_lifecycle_probe.json`。

## 聚焦测试（仅 `tests/test_cli_backend.py`）

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest \
  tests/test_cli_backend.py -q --basetemp=/tmp/1847-fixer-t1-t2/pytest-cli
```

- **结果**: `92 passed in 0.94s`
- **耗时**: `real 2.22` / `user 1.25` / `sys 0.16`
- **exit**: 0
- 未跑全量；未跑八文件套件

## 自查二连 done

- 同类：证据层强杀冒充自然退出；死字段并行落点无消费者
- 引入：删字段不得改 raise/add_note/stderr 语义；撤回叙述不得洗白旧 JSON；不按进程名杀；记录器不发 OS SIGKILL

## git 核实

```text
git diff --check   # 干净（无输出）
git status -sb     # 见 delivery commit 后
```

- delivery commit：以本交卷后 `git rev-parse HEAD` 为准（不为记录 SHA 再循环 docs 提交）
- 临时物：仅 `/tmp/1847-fixer-t1-t2/`（自建）；未动他人临时目录内容以外的系统物
