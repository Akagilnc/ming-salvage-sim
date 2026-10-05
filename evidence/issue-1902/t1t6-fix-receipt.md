# #1902 修内司 T1–T6 回执（自验纠偏轮）

- 分支：`ak-roles/1902-t1t6-fixer-092109acf`
- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5`
- 上一轮 HEAD：`9df958435`（初修）
- 本轮：独立新 commit（禁止 amend）
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

## 自验纠偏（相对 9df958435）

| 问题 | 处置 |
|---|---|
| T3：`enrich_initiative_effects` 仍 catch canonicalize 返回原 obj | **删除 catch**；规范化响亮失败（ADR 0005）。LLM 补全失败仍为确证安全旁路+`logger.warning`。判词点名「296/318」对应旧 `_log` 受 `_VERBOSE` 门控——trace/login/keychain 已改 `logger.warning`，非规范化洗白。 |
| T4：snapshot 在 try 外 → 遗留 generating | reopen 已赢即建 turn；snapshot 在同一 try；`fail_audience_chat_turn` 的 after-snapshot 失败留痕并继续翻回 interrupted。 |
| T4：Web 投影/转译失败不走 fail 收口；ticketed gate 误用于票后清理 | 适配段外包 `fail_audience_chat_turn`，**cleanup 用 runtime gate**；收夜在放行 pending write 之后调共核调度。 |
| T4：CLI/Web 收夜各编排 | CLI retry 收夜进 `execute_interrupted_reply_retry`；Web 因票据顺序 `schedule_close_night=False` 后调同一共核方法（宿主适配，非第二生命周期）。 |
| T5：新增词面钉误判测试 | **删除** `test_run_agy_exit_zero_prose_is_not_connection_error`；复用既有 exit0 正文契约。 |
| T5：applier 公开契约 | 余下标为 **PUBLIC_STRUCTURED（ADR 0008）**，非 INTERNAL_SHAPE、非 EXTERNAL_REAL_ENTRY；聚合复用 `test_declaration_dispatch_1835`。 |
| 回执用 `python …rescan…` 占位 | 成员表改列完整 `rg` 谓词与命令（见下）；禁止点名三文件冒充全仓。 |

---

## 类定义与枚举谓词（全文）

| 类 | 谓词 |
|---|---|
| T1 | 显式/隐式强杀与硬期限兜底；保留合法静默判定；如实报告终止缺口；不另造监督层 |
| T2 | 自由输出词面判故障、切分呈现横幅及钉误判测试；改用原生状态/结构化契约 |
| T3 | 代码故障响亮失败；确证安全旁路留真因日志；不依赖调试开关；不给所有 catch 加统一框架 |
| T4 | 合并恢复生命周期，删入口编排副本；保留输入/呈现/宿主资源适配；不新增通用编排框架 |
| T5 | 处置纯内部与重复证明；复用真实行为测试；修正虚假零剩余；保留负向闸与公开结构化契约 |
| T6 | 按当前消费者清退役残根/独占证明；撤销底座时点豁免；保留有真实用途的共享能力 |

成员表：`evidence/issue-1902/t1t6-member-tables.json`  
复扫：`evidence/issue-1902/t1t6-rescan.json`

### 可核复扫命令（完整谓词，非占位脚本）

```bash
rg -n --glob '*.py' -g '!tests/**' '(\.kill\(|SIGKILL|subprocess\.run\([^)]*timeout\s*=)' ming_sim web_app.py
rg -n --glob '*.py' '_AGY_AUTH_MARKERS|Authentication required|OpenAI Codex v' ming_sim web_app.py tests
rg -n --glob '*.py' '_canonical_item_fields|规范化失败|norm = obj' ming_sim
rg -n -U --glob '*.py' -g '!tests/**' -g '!scripts/**' \
  'except Exception(?: as \w+)?:\n(?:\s+#.*\n)*\s+(pass|return None|return \{\}|return \[\]|return ""|continue)\b' \
  ming_sim web_app.py
rg -n 'reopen_interrupted_chat_turn_for_retry|execute_interrupted_reply_retry|schedule_close_night_after_chat_if_needed' \
  ming_sim/cli/terminal.py web_app.py ming_sim/session.py
rg -n 'SectionResult|ApplyContext|prose_is_not_connection|_require_active_minister' tests ming_sim web_app.py
```

复扫计数（纠偏后）：`T1_actionable=0 T2_actionable=0 T3_canonical_whitewash=0 T4_entry_owns_reopen=0 T5_actionable_tests=0 T6_live_refs=0`。  
生产 `SectionResult`/`ApplyContext` 有现役消费者 → **KEEP**（不以 AST 零引用整删）。

---

## 逐类结果

### T1
维持：无 `kill`/timeout-subprocess 可执行路径；宿主自 SIGTERM KEEP。

### T2
维持删除词表/横幅切分；**删除**钉误判测试；既有 `test_run_agy_success_single_subprocess` 覆盖 exit0 正文。

### T3
canonicalize **响亮**；LLM enrich / login PATH / keychain / trace / auto_save = 旁路+warning。嵌套 rollback `pass` 后仍 `raise` → KEEP。

### T4
共核：`execute_interrupted_reply_retry`（reopen→turn→snapshot→scene→complete/fail→可选收夜）。  
Web：票据/投影/转译适配 + runtime cleanup；票后收夜。CLI：retry 收夜在共核内。

### T5
INTERNAL_SHAPE 测已删；钉误判测已删；applier 余下 = PUBLIC_STRUCTURED。

### T6
`_require_active_minister` 仅历史注释；无活引用。

---

## 聚焦测试

```
296 passed in 6.50s
```

文件集：`test_cli_backend` / `test_cli_transport_1465` / `test_cli_entry_1902` / `test_web_entry_1902` /
`test_audience_restore_505` / `test_applier_contract` / `test_web_court_visibility` /
`test_qa_s2_copy_prompts_1356_1402` / `test_cli_play_turn` / `test_web_chat_serialization_393` /
`test_chat_stream_failpaths_393` / `test_settlement_write_guard_393` / `test_audience_background` /
`test_cli_runner_error_typed_1299` / `test_declaration_dispatch_1835`

输出：`evidence/issue-1902/t1t6-focus-pytest.txt`

---

## 变异真跑（真实入口；临时文件已删，未落永久证明测试）

`evidence/issue-1902/t1t6-mutations.out` + `t1t6-mutations.collected.txt`

| 变异 | 入口 | 结果 |
|---|---|---|
| canonicalize→RuntimeError | `enrich_initiative_effects` | LOUD；printed='' |
| LLM enrich 失败 | 同上 | 旁路空结构；warning 真因 |
| terminate 后未退 | `_terminate_cli_process` | terminate+wait；无 kill；终止缺口 warning |
| reopen 后 snapshot 失败 | `execute_interrupted_reply_retry` | status=`interrupted`（非 generating） |

---

## 质量 / 合法性

- 未改 `CLAUDE.md` / `AGENTS.md` / `CONTEXT.md` / ADR。
- 未新增永久扫描器、通用编排框架、第二运行配置、钉误判证明测试。
- 未恢复手拟入口；未按 AST 零引用整删生产类型。
- 净复杂度：去掉 canonicalize 洗白与钉误判测；恢复失败收口与 runtime cleanup 归位。

## 剩余 / 阻断

- 剩余：#1902 其它已结面；家族收尾/合并/关票不在授权内。
- 阻断：无。
