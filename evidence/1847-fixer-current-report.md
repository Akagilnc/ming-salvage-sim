#1847 修内司交卷 — w7 自验修正（主席复检未结）

- worktree: `/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- branch: `ak-roles/1847-fixer-w7-n6-n11-n13-n14`
- 派单: `/Users/akagilnc/.ak-roles/books/Ming_LLM/unbound/runs/01a10906-b970-7021-8014-282026406f92@fixer/fix-packet.md`
- 判词真源: 附件 `03-1847-judge-bcf7a7bf7.json` **末份 payload**
- 禁令: 未 amend / rewrite / push / PR / stash；临时物 `/tmp/1847-fixer-w7/` + `evidence/1847-w7-correction/`

## 主席复检未结 → 本轮纠正

1. **N13 `raise cleanup_err` 覆盖原失败**：`scripts/play_as_emperor.py` finally 改为 `body_err` 跟踪；仅当无原失败时 `raise cleanup_err`，并存时 `body_err.add_note(...)`。
2. **`except: pass` 吞 fileobj.close / child 状态写入**：删除 `fileobj.close` 与状态写入外包的 `except: pass`；软失败后只做必要的 `fd/closed` 标记。
3. **手写 pty 私有补丁像适配机制**：先读已安装 `ptyprocess.PtyProcess.close/terminate/__del__` 与 `pexpect.spawn.close`。生态最简选择=`child.close(force=False)`。实证：官方 `close(force=False)` 在 soft terminate 失败时已关 FD 但未置 `closed=True`，`__del__` 默认 `close()`→可升 SIGKILL；**无 public detach API**。故仅在该失败路径标记 `closed`（完成官方 close 未写完的尾部），不重关 fileobj、不加监管/重试。
4. **cli_backend finally 以 logger 掩盖唯一失败**：去掉「只 warning 后正常结束」；`cleanup_error` 入 outcome；无 `body_err` 时 `raise cleanup_err`，有则 `add_note`。
5. **报告枚举谓词收窄**：重做全仓机械枚举（见下），成员表 TSV 全量写入，不 head 截取。

## 修改前 advisor

- 已读派单、末份判词、仓内 CLAUDE/AGENTS、上一份 `evidence/1847-fixer-current-report.md`。
- diagnosing-bugs：主席复检已给独立根因与边界；本轮反馈环对准未结 N13 覆盖/吞异常/私有补丁与枚举收窄，不另立平行假设。
- 官方 API：[ptyprocess](https://ptyprocess.readthedocs.io/en/latest/api.html) `close(force=False)` / `terminate(force=False)`；subprocess `terminate`≠`kill`。

## 全仓枚举谓词（覆盖类定义全文）

扫描根：`git ls-files` 中 tracked 生产+测试代码（`.py/.ts/.tsx/.js/.jsx`）。`docs/raw|docs/archive|evidence|archive|node_modules` → `exempt_files.tsv`（冻结/卷宗，明确不适用）。

可复跑：

```bash
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  evidence/1847-w7-correction/scan_n6_n11_n13_n14.py
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  evidence/1847-w7-correction/classify_dispositions.py
```

| 类 | 发现集合（全量 TSV） | 处置表 |
|---|---|---|
| N6 | `n6_candidates_raw.tsv` / `n6_members_classified.tsv`（2849 行） | `n6_disposition.tsv` |
| N11 | `n11_members_classified.tsv`（223 符号；含 name-pattern 扩展） | `n11_disposition.tsv`（judge seed 闭包 vs name-pattern 非权威分列） |
| N13 | `n13_members_classified.tsv`（286 行） | `n13_disposition.tsv` |
| N14 | `n14_members_classified.tsv`（439 行） | `n14_disposition.tsv` |
| 汇总 | `scan_summary.json` + `disposition_summary.json` | |

### N6 — 自由正文运输删改

谓词：AST/rg 全仓扫 strip/lstrip/rstrip/replace/split/join/slice/sub/read_text 换行变换等；再按自由正文字段线索（body/opening/player_message/…）与来源→去向分类。判空局部副本 / 标识符规范化 / 形式语言 ≠ 运输删改。

种子样本复扫：`audience_night` body 运输用原文 + `if body.strip()` 判空；`registry.scene_prompt` 判空局部；judge 点名运输 strip 赋值已清除。`FIX_TRANSPORT_MUTATION` 处置后为 **0**（`play_as_emperor:482` 为 menu `prompt_hint` 形式标签，`action` 原样入史 → KEEP_FORM_LANGUAGE）。

### N11 — 退役独占支链闭包

谓词：以末份判词种子符号为闭包起点，核对 def/非 def 生产·测试引用；**不按 legacy/secret_order 字样猜删**。name-pattern 扩展行标 `NOT_AUTO_RETIRE_NAME_PATTERN`（非本轮删简权威）。

| symbol | disposition |
|---|---|
| rescript_summon_origin_ref / _consumed / prepare_rescript_summon_scaffold | DELETED_CONFIRMED |
| RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES | DELETED_CONFIRMED |
| find_deliberation_dossier_by_decision_key | DELETED_CONFIRMED |
| _extract_secret_order 及独占装配岛 / _DRAFT_PREFIXES / _SECRET_PREFIXES / _so_json 等 | DELETED_CONFIRMED |
| _ledger_by_origin_ref | KEEP_LIVE_SHARED（1764/1789/1808） |

seed actionable（须再删）: **[]**

### N13 — 完整软收尾生命周期

谓词：全仓扫 `force=True` / SIGKILL / `.kill(` / `terminate(` / `close(` / `except Exception: pass` / `subprocess.run(...timeout=`；再按软收尾位点分类。

代码修正：

- `cli_backend._iter_cli_process_lines`：`body_err` + `cleanup_error`；唯一软失败必 raise；并存 add_note；禁 logger-only 成功返回。
- `play_as_emperor` finally：同上；`close(force=False)`；软失败后最小 `closed` 标记（见上 API 实证）。

`FIX_*` 处置行：**0**（生产 force=True 命中空；软位点 KEEP_SOFT_*）。

### N14 — 测试质量

谓词：全仓 `tests/**/*.py` 扫 getsource/AST 源码证明、同值复查、`str(row)`/正文身份哨兵、`read_text` 绕过、CR/CRLF 夹具；分类不凭盯文自动删。原文运输原样性断言 KEEP。

聚焦文件：`test_advance_paths_atomic` 无 getsource；`test_month_chain_1847` 已恢复 `decree_ref`/`target_id`/`read_material`/CRLF `fact_body`。全表见 `n14_disposition.tsv`（跨文件 `str()` 命中需按「是否替代结构化身份」人工读处置列，禁止按文件名整表删除）。

## N13 变异证据（旧红/现绿；不发 OS 强杀）

探针：`evidence/1847-w7-correction/n13_lifecycle_probe.py` → `n13_lifecycle_probe.json`

| case | 结果 |
|---|---|
| raise_cover_compare | 旧 `raise cleanup` → CleanupBoom **覆盖** BodyBoom；新 BodyBoom + note；唯一 cleanup 亦 raise（非成功返回） |
| cli_terminate_soft_fail | 忽略 SIGTERM 真子进程：`TimeoutExpired`，`alive_after=True`，`elapsed≈5.01` |
| cli_iterator_body_and_cleanup | 传播 `TransportIdleTimeout`，note 含 soft terminate TimeoutExpired；`covered_by_cleanup_only=false` |
| pty_soft_close | 记录器：SIGHUP→SIGCONT→SIGINT；**无 SIGKILL**；`os_signals_sent=0`；spawn/pty `closed=True`；未标记时 force=True 序列才含 SIGKILL |

VERDICT **GREEN**。不声称本轮生产路径发生过真实 SIGKILL。

## 聚焦测试

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest \
  tests/test_month_chain_1847.py tests/test_pihong_dossier_1490.py \
  tests/test_cli_backend.py tests/test_advance_paths_atomic.py \
  -q --basetemp=/tmp/1847-fixer-w7/focused
```

实测：`155 passed`（见 `evidence/1847-w7-correction/focused_pytest.txt`）。未跑全量。

## 提交前质量复检

- `git diff --check`：无报错。
- 净删简取向：去掉 except:pass 护栏与 logger-only 掩盖；不新增监管/重试/适配层。
- 0055 / 无人站台 / 中旨 / 御笔强推案仍在。
- 无 secrets；无 amend/push/PR/stash。
- **本交卷仅一个代码+证据 commit**；不以 docs 戳记循环制造 HEAD。

## git 事实

```bash
git rev-parse HEAD
git status --porcelain=v1
git branch --show-current
```

- branch: `ak-roles/1847-fixer-w7-n6-n11-n13-n14`
- delivery commit：以本交卷 `git rev-parse HEAD` 为准（见交卷 query）
- 相对上一 delivery `b04ea3af3`：N13 覆盖/吞异常/cli 唯一失败掩盖 + 全仓枚举表

## 剩余事项

- 未 push / 未开 PR。
- N6/N14 全表仍有大量 `POTENTIAL_*`（标识符 strip、异常 `str(exc)` 等）— 已按来源契约分类，非自动 FIX；种子未结项已清。
- N11 name-pattern 扩展行明确非删简权威，避免按字样误删现役。
