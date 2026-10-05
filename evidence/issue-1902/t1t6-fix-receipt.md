# #1902 修内司 T1–T6 回执（自验纠偏轮 · 谓词全文重扫）

- 分支：`ak-roles/1902-t1t6-fixer-092109acf`
- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5`
- 上一轮 HEAD：`0e044f154`
- 本轮 HEAD：`a18683603`（独立新 commit，禁止 amend）
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

## 自验纠偏（相对 0e044f154）

| 问题 | 处置 |
|---|---|
| 成员表 note 把 T5 收窄为 nail+internal-shape | **撤销**。T5 谓词恢复全文：全仓内部形状 + 重复证明；候选宇宙含 68 条 stale INTERNAL_SHAPE_CANDIDATE 语义复判 + applier 公开契约逐案。 |
| T2 只枚举 Auth/Codex 字串 | 谓词扩至 prose→fault／banner-split／nail-misjudgment／结构化 `llm_connection_error`；全仓 Py+TS 机械枚举后逐项判。 |
| T6 只点名 `_require_active_minister` | 谓词扩至授权内退役残根／独占子树／专属证明；对 S1 `KEEP_NEVER_WIRED` 133 名做消费者复审并**撤销底座时点豁免**作为 KEEP 理由。 |
| T3 只扫 except+pass | AST 枚举一切 `pass/continue/return None\|{}\|[]\|""\|原名`；确证安全旁路补真因日志（web buffering、office_type LLM、mechanical_tail、VERSION、derive_draft_capability、FK migrate）。 |
| T4 `except LookupError` 无条件绕过 fail | CAS 未赢改为 `reopen False → return None`；删除 LookupError 信号。KeyError/IndexError 走 fail 收口。 |
| `fail_audience_chat_turn` 空 snapshot 伪造零差异 | after-snapshot 失败留真因、**跳过** `record_chat_turn_rollback_diffs`（不伪造 before==after），仍走 restore→interrupted。 |
| Web 转译／失败收口 | 对照后：票后投影失败 fail 与 runtime cleanup 属宿主资源适配，与共核不重复生命周期；不强行加通用编排。 |

成员表：`evidence/issue-1902/t1t6-member-tables.json`  
复扫：`evidence/issue-1902/t1t6-rescan.json`

### 可核复扫命令（全文谓词）

```bash
python3 /tmp/ming1902-t1t6-enum/enum_t1t6.py
rg -n --glob '*.py' -g '!tests/**' '(\.kill\(|SIGKILL|subprocess\.run\([^)]*timeout\s*=|os\.kill\()' ming_sim web_app.py scripts
rg -n --glob '*.{py,ts,tsx}' 'llm_connection_error|Authentication required|OpenAI Codex v|_AGY_AUTH|banner|prose_is_not_connection' ming_sim web_app.py tests web/src scripts
# T3：AST except→pass|continue|return None|{}|[]|""|name（见 enum_t1t6.t3_scan_py）
rg -n 'reopen_interrupted_chat_turn_for_retry|execute_interrupted_reply_retry|fail_audience_chat_turn|schedule_close_night_after_chat_if_needed' ming_sim web_app.py tests
# T5：AST SectionResult(|ApplyContext( + attr/identity 且无 I/O/入口
rg -n '_require_active_minister|手拟|manual_draft|KEEP_NEVER_WIRED|generate_rescript_draft' ming_sim web_app.py tests scripts evidence/issue-1902/s123-s1-disposition.md
```

候选宇宙（机械）→ 语义处置后 actionable：

| 类 | 候选宇宙 | actionable |
|---|---|---|
| T1 | 7 | 0 |
| T2 | 12 | 0 |
| T3 | 313（全部分类，非零命中冒充） | 0 |
| T4 | 88 | 0 |
| T5 | 89 行（含 68 stale INTERNAL 复判 + applier + 清退记录） | INTERNAL=0 DUP=0 |
| T6 | 3 符号审计 + 133 KEEP_NEVER_WIRED 复审 | 0 |

**不能用零命中代替分类**：T3 `by_disposition` 见 rescan；T5 对 68 条 prior INTERNAL_SHAPE_CANDIDATE 逐案标 `KEEP_EXTERNAL_REAL_ENTRY_after_semantic_review`。

---

## 逐类结果

### T1
无可执行 `.kill`/timeout-subprocess；宿主自 SIGTERM KEEP；注释/文档禁 SIGKILL KEEP。终止缺口 `logger.warning` 如实报告。

### T2
生产无散文鉴权词表／横幅切分；`llm_connection_error` 为 transport 结构化码 KEEP；钉误判测已删；负向注释 KEEP。

### T3
canonicalize 响亮；旁路补真因日志（本轮新增若干）；嵌套 rollback→raise、入项 clamp、解析跳过、typed reject、入口向玩家打印失败等 KEEP。313 条全部分类。

### T4
共核 `execute_interrupted_reply_retry`：CAS→`None`；赢后失败→`fail_audience_chat_turn`。Web/CLI 读 `None` 译 409／提示。snapshot 失败不伪造差异。Web 票后投影 fail = 宿主适配 KEEP。

### T5
`SectionResult`/`ApplyContext` 纯内部形状测 = 0；applier 余下 = PUBLIC_STRUCTURED（ADR 0008）；68 条 stale INTERNAL 候选语义复判为外部行为 KEEP；急务两案按判词 **非** 重复。负向闸保留。

### T6
`_require_active_minister` 定义已清、仅历史注释；133 名 KEEP_NEVER_WIRED 撤销底座时点豁免理由——TEST_ONLY 残仅注释、其余有现役消费者或非授权退役范围；`generate_rescript_draft` KEEP（现役共享能力）。不按 AST 零引用盲删。

---

## 聚焦测试

```
298 passed in 7.63s
```

命令与文件集见 `evidence/issue-1902/t1t6-focus-pytest.txt`（含七 BIN 前缀）。

新增红→绿：
- `test_retry_keyerror_after_cas_won_fails_closed_not_cas_bypass`
- `test_fail_audience_chat_turn_snapshot_failure_keeps_recovery_without_forged_diffs`

---

## 变异真跑（真实 Web retry / GameSession / CLI terminate / enrich 入口）

`evidence/issue-1902/t1t6-mutations.out` + `t1t6-mutations.collected.txt`

| 变异 | 入口 | 结果 |
|---|---|---|
| CAS 未赢 | `GameSession.execute_interrupted_reply_retry` | `None` |
| CAS 后 KeyError | `WebGame.retry_interrupted_reply` | KeyError 上抛；status=`interrupted` |
| after-snapshot 失败 | `fail_audience_chat_turn` | 无伪造 diffs；interrupted |
| terminate 未退 | `_terminate_cli_process` | terminate+wait；无 kill |
| canonicalize RuntimeError | `enrich_initiative_effects` | LOUD |

---

## 质量 / 合法性

- 未改 `CLAUDE.md` / `AGENTS.md` / `CONTEXT.md` / ADR。
- 未新增永久扫描器、通用编排框架、第二运行配置、钉误判证明测试。
- 未恢复手拟入口；未按 AST 零引用整删生产类型。
- 自查二连 done：同类型（LookupError⊆LookupError；空 snapshot 伪造）+ 引入（CAS 信号改 None 后入口适配）。

## 剩余 / 阻断

- 剩余：#1902 其它已结面；家族收尾/合并/关票不在授权内；T3 `KEEP_narrow_exc_control_flow` 6 条为窄类型控制流 KEEP（非沉默代码故障）。
- 阻断：无。
