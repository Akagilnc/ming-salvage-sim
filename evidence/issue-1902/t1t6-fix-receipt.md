# #1902 修内司 T1–T6 回执（最终自验 · 删证明测 · 全文枚举）

- 分支：`ak-roles/1902-t1t6-fixer-092109acf`
- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5`
- 上一轮 HEAD：`452fb6e04`（stamp）／功能基线 `a18683603`
- 本轮 HEAD：`7eca74e0e`（独立新 commit，禁止 amend）
- 判词真源：`06-1902-judge-092109acf.json` → `outcome.payloads[-1]`（T1–T6）
- fix-packet：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a10a10-a917-76cc-966b-7ef94176ba78@fixer/fix-packet.md`
- **不宣称已合并 / 总票完成**；未 stash/push/PR；未改治理文件与宿主席位

七 BIN 前缀（本轮全部测试显式展开）：

```bash
env \
  MING_SIM_AGY_BIN=/usr/bin/false \
  MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false \
  MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false \
  MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=. \
  python3 -m pytest ...
```

---

## 本轮硬纠偏（相对 a18683603 回执）

| 问题 | 处置 |
|---|---|
| 新增 `test_retry_keyerror_after_cas_won...` / `test_fail_audience...snapshot...` 为修复证明测 | **已删**（含独占夹具 `_KeyErrorAfterCasRetrySession`）。证据改走已有 `test_lost_reopen_cas_*` / `test_failed_retry_rolls_back_side_effects_*` / `test_run_codex_stdout_empty_does_not_parse_stderr_banner` + 系统临时变异脚本。 |
| T2 谓词限词串 | 改为输出变量**数据流**枚举（bind stdout/stderr/communicate/agent.run → compare/re/split）+ 显式 returncode／负向闸；过宽 `compare_in` 2098 条仅作噪声对照，不当宇宙。 |
| T5 仅 SectionResult/ApplyContext + 旧 68 批量 KEEP_EXTERNAL | 全仓 **3364** Py/TS 测试函数预分类；对精细 INTERNAL 候选 **79** 条逐案读 docstring/入口后处置（成员表逐条不同文案）；**无**批量 `KEEP_EXTERNAL_...`。 |
| T6 仅旧 133 名单 | 生产符号聚焦枚举 **1927** + 授权退役词表 ∩ 当前引用；133 KEEP_NEVER_WIRED **逐名**标 prod/test/auth 与处置（撤销底座时点豁免理由）。 |
| T4 fail_snapshot「无伪造差异」冒充安全 | 变异 **M3b FAIL**：副作用 +40 忠诚未回滚、`rollback_items=0`。对照 M3c 快照正常则回滚。→ **BLOCK**（完整补救=未授权第二套回滚设计）。日志改为 `logger.exception` 明示「副作用可能残留」。 |

成员表：`evidence/issue-1902/t1t6-member-tables.json`  
复扫摘要：`evidence/issue-1902/t1t6-rescan.json`  
枚举脚本全文：`evidence/issue-1902/t1t6-enum-script.py.txt`  
变异脚本全文：`evidence/issue-1902/t1t6-mutations-script.py.txt`

### 可核复扫命令

```bash
python3 evidence/issue-1902/t1t6-enum-script.py.txt
# 另产 /tmp/ming1902-t1t6-final/raw_full.json（T5 全 3364 预分类在 results.T5）
python3 evidence/issue-1902/t1t6-mutations-script.py.txt
# T2 数据流补充（同轮临时；逻辑亦在 enum 报告）：
#   AST：函数内 bind .stdout/.stderr/communicate/run → compare|re|split 使用
rg -n --glob '*.py' -g '!tests/**' '(\.kill\(|SIGKILL|subprocess\.run\([^)]*timeout\s*=|os\.kill\()' ming_sim web_app.py scripts
rg -n 'returncode|llm_empty_output|does_not_parse_stderr_banner|<<<CMRPATH>>>' ming_sim/cli_backend.py tests/test_cli_backend.py
rg -n 'reopen_interrupted_chat_turn_for_retry|execute_interrupted_reply_retry|fail_audience_chat_turn|record_chat_turn_rollback_diffs' ming_sim web_app.py tests
```

候选宇宙（机械）→ 语义处置后 actionable：

| 类 | 候选宇宙 | actionable |
|---|---|---|
| T1 | 7 | 0 |
| T2 | 21（数据流+显式）；对照噪声 2098 | 0 |
| T3 | 313 | 0 |
| T4 | 103 + snapshot 缺口 | **1 BLOCK** |
| T5 | 3364 预分类；79 精细逐案 | 0 可删 |
| T6 | 1927 生产符号 + 133 KNW 逐名 | 0 授权内未清残根 |

---

## 逐类结果

### T1
无可执行 `.kill`/timeout-subprocess；宿主自 SIGTERM KEEP；注释/文档禁 SIGKILL KEEP。终止缺口 `logger.warning` 如实报告（变异 M4）。

### T2
生产无「自由输出词面→鉴权故障／横幅切分」路径；`returncode!=0` 与 `llm_empty_output` 为原生/结构化状态 KEEP；`<<<CMRPATH>>>` sentinel 非故障推断 KEEP；负向闸 `test_run_codex_stdout_empty_does_not_parse_stderr_banner` KEEP。数据流 17 bind 均无 fault 近邻使用。

### T3
沿用全文 except→pass/continue/return 分类（313）；canonicalize 响亮（M5）；旁路真因日志保留。不另加统一 catch 框架。

### T4
共核 `execute_interrupted_reply_retry`：CAS→`None`；赢后失败→`fail_audience_chat_turn`。Web/CLI 读 `None` 译 409／提示。  
**未结／阻断**：after-snapshot 失败时跳过 `record_chat_turn_rollback_diffs` → `restore_interrupted_after_failed_retry` **不能**还原本次副作用（M3b）。不伪造零差异；亦不声称「仍安全」。完整补救需未授权新设计 → **BLOCK**。现仅 `logger.exception` 明示缺口。

### T5
删除本轮两条新增证明测。`SectionResult`/`ApplyContext` 纯内部形状测仍为 0；applier 余下 = PUBLIC_STRUCTURED（ADR 0008）逐案。全仓 3364 预分类见 raw；79 精细 INTERNAL 候选逐条读入口后均为真实行为／公开契约／附带 isinstance——**无**可删纯内部重复。负向闸保留。

### T6
`_require_active_minister` 定义已清、仅历史注释。`generate_rescript_draft` KEEP（现役共享能力）。133 KEEP_NEVER_WIRED 逐名：授权退役且 prod=0 仅 `_require_active_minister`（已 CLEARED）；其余为现役单一定义／多消费者，或 **OUT_OF_T6_SCOPE**（非入口/手拟授权退役类，不按零引用整仓盲删）。不按底座时点豁免 KEEP。

---

## 聚焦测试

```
296 passed in 7.27s
```

（相对上轮 298：−2 = 删除的两条证明测。）  
命令与文件集见 `evidence/issue-1902/t1t6-focus-pytest.txt`（含七 BIN）。

**未**新增红→绿证明测。

---

## 变异真跑（已有 Web retry / GameSession / CLI terminate / enrich）

`evidence/issue-1902/t1t6-mutations.out` + `t1t6-mutations.collected.txt` + 脚本全文 `t1t6-mutations-script.py.txt`

| 变异 | 入口 | 结果 |
|---|---|---|
| CAS 未赢 | `GameSession.execute_interrupted_reply_retry` | `None` PASS |
| CAS 后 KeyError | `WebGame.retry_interrupted_reply` | KeyError；status=`interrupted` PASS |
| after-snapshot 失败无伪造 diffs | `fail_audience_chat_turn` | recorded=0；interrupted PASS |
| after-snapshot 失败+副作用 | `_FailingRetrySession` + Web retry | **FAIL** loyalty +40 残留；rollback_items=0 → **T4 BLOCK 证据** |
| 对照：快照正常 | 同上无 boom | loyalty 回滚 PASS |
| terminate 未退 | `_terminate_cli_process` | terminate+wait；无 kill PASS |
| canonicalize RuntimeError | `enrich_initiative_effects` | LOUD PASS |

---

## 质量 / 合法性

- 未改 `CLAUDE.md` / `AGENTS.md` / `CONTEXT.md` / ADR。
- 未新增永久扫描器、通用编排框架、第二运行配置、钉误判证明测试。
- 未恢复手拟入口；未按 AST 零引用整删生产类型。
- 临时枚举/变异脚本全文落入 `evidence/issue-1902/*-script.py.txt`（可复现命令记录，非常驻机制）。
- 自查二连 done：同类型（证明测≠质量；伪造零差异≠副作用安全）+ 引入（删测后契约仍由已有测+变异覆盖；exception 日志不改变回滚语义）。

## 剩余 / 阻断

- **阻断（T4）**：`fail_audience_chat_turn` 在 after-snapshot 失败时无法记 rollback diffs，副作用可能残留。完整补救需要未授权的第二套快照/回滚或等价新机制——**本轮不瞎补**。现状：不伪造差异 + `logger.exception` 明示缺口。
- 剩余：#1902 其它已结面；家族收尾/合并/关票不在授权内。
- T3 `KEEP_narrow_exc_control_flow` 等窄类型控制流 KEEP（见成员表 T3_all）非本轮新增沉默故障。
- T5 全 3364 预分类中非精细 79 条的「重复契约」深度合并未在本轮做整仓删并（无行数盲删；若要继续需另授权按契约 ID 合并）——**未结项：T5 重复契约整仓合并**（非虚假零剩余；公开声明未做）。
- T6 授权外零引用符号整仓清退 **不在** #1902 授权——如实标 `OUT_OF_T6_SCOPE`，不冒称已清。
