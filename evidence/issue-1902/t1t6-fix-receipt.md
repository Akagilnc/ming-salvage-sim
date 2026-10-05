# #1902 修内司 T1–T6 回执

- 分支：`ak-roles/1902-t1t6-fixer-092109acf`
- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5`
- 施工前 HEAD：`092109acf`
- 判词真源：末份 `06-1902-judge-092109acf.json` → `outcome.payloads[-1]`（status=continue；T1–T6）
- **不宣称已合并 / 总票完成**；未 amend/stash/push/PR；未改治理文件与宿主席位

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

官方文档（T1，先搜后修）：[subprocess — Python docs](https://docs.python.org/3/library/subprocess.html) — `run(timeout=…)` 超时会 kill 子进程；POSIX 上 `Popen.kill` = SIGKILL。本票按硬规9拆除该路径，不另造监督层。

---

## 类定义与枚举谓词（全文，未收窄到点名样本）

| 类 | 谓词（票面+判词 direction） |
|---|---|
| T1 | 显式及隐式强杀路径和硬期限兜底；保留合法静默判定；如实报告终止缺口；不另造监督层 |
| T2 | 从自由输出词面判故障、切分呈现横幅的机制及钉误判的测试；改用原生状态/结构化契约 |
| T3 | 代码故障响亮失败；确证安全旁路留真因日志；不依赖调试开关；不给所有 catch 加统一框架 |
| T4 | 合并已有恢复生命周期，删除入口编排副本；保留输入/呈现/宿主资源适配 |
| T5 | 按独立外部契约处置纯内部与重复证明；复用真实行为测试；修正虚假零剩余分类 |
| T6 | 按当前实际消费者清退退役入口残根/独占证明；撤销底座时点豁免；保留有真实用途的共享能力 |

成员表路径：`evidence/issue-1902/t1t6-member-tables.json`  
复扫：`evidence/issue-1902/t1t6-rescan.json`

临时枚举（非永久扫描器）命令摘要：

```bash
python3 /tmp/ming1902-t1t6-enum/...   # 施工前全仓 AST/文本谓词
python3 …rescan…                     # 施工后复扫 → t1t6-rescan.json
```

---

## 逐类结果

### T1 — 强杀 / 硬期限
- **处置**：`_terminate_cli_process` 去掉 `kill`；`_login_shell_path` / `_warm_keychain` 去掉 `timeout=`；terminate 后未退只 `logger.warning` 记终止缺口。
- **保留**：idle 静默判定；`worker.join(timeout=5)`；`web_app` 对自身 `SIGTERM`（宿主退出，非 CLI 强杀）。
- **复扫**：可执行强杀/timeout-subprocess = 0（仅注释命中 `timeout=` 字样，KEEP）。

### T2 — 自由词面判故障
- **处置**：删除 `_AGY_AUTH_MARKERS` 与 Codex 横幅 `split`；退出码 0 的词面按正文；空 stdout 走 `llm_empty_output`。
- **测试**：负向钉「词面≠连接错误」；transport 瞬断改空输出 typed。
- **复扫**：可执行 prose 机制 = 0。

### T3 — 静默代码故障 / 旁路无痕
- **处置**：`_trace` / enrich canonicalize / login PATH / keychain / `auto_save` → `logger.warning`（不依赖 `_VERBOSE`）。
- **保留**：CLI `print(失败)` 呈现；web 启动缓冲 `pass`；verify 冒烟转 HTTPException。
- **复扫**：判词点名三缝已留痕；其余命中为呈现/宿主适配（KEEP 依据见成员表）。

### T4 — 恢复生命周期共核
- **处置**：新增 `GameSession.execute_interrupted_reply_retry`（reopen→快照→scene_chat→complete/fail；可选 `write_gate`）。
- CLI / Web retry 入口改为调用共核；Web 保留票据/写闸/投影/`persisted_message_id`。
- **复扫**：入口内同时含 `reopen_interrupted…`+`scene_chat` 的编排副本 = 0。

### T5 — 内部形状证明
- **处置**：删除 `SectionResult`/`ApplyContext` 纯构造测 4 条；保留 Provenance/RejectedItem/RejectionCollector 落库镜像。
- 聚合行为复用 `tests/test_declaration_dispatch_1835.py`（22 passed）。
- **纠正**：上轮 `INTERNAL_SHAPE=0` 虚假分类；本轮 INTERNAL_SHAPE 复扫 = 0（真删后）。

### T6 — 退役入口残根
- **处置**：删除 `web_app._require_active_minister` 及独占测试/死 monkeypatch；撤销「底座从未接线→KEEP」豁免。
- **保留**：`session.can_summon`（现役共享闸）。
- **复扫**：生产/测试可执行引用 = 0（仅历史注释）。

---

## 聚焦测试

命令见上七变量前缀；文件集：

`test_cli_backend` / `test_cli_transport_1465` / `test_cli_entry_1902` / `test_web_entry_1902` /
`test_audience_restore_505` / `test_applier_contract` / `test_web_court_visibility` /
`test_qa_s2_copy_prompts_1356_1402` / `test_cli_play_turn` / `test_web_chat_serialization_393` /
`test_chat_stream_failpaths_393` / `test_settlement_write_guard_393` / `test_audience_background` /
`test_cli_runner_error_typed_1299`

实测：`evidence/issue-1902/t1t6-focus-pytest.txt`

```
275 passed in 6.70s
real 7.24
```

另：`tests/test_declaration_dispatch_1835.py` → 22 passed（T5 聚合真实入口）。

未跑全量、未真调模型。

---

## 变异真跑证据

`evidence/issue-1902/t1t6-mutations.out`（临时目录 `/tmp/ming1902-t1t6-mut`，已恢复工作树）：

| 变异 | 入口 | 红 | 绿 |
|---|---|---|---|
| A 恢复 `proc.kill` | `_terminate_cli_process` 假进程探针 | `terminate→wait→kill→wait` | 无 `kill`，仅 terminate+wait+警告 |
| B 恢复词面鉴权 | `test_run_agy_exit_zero_prose_is_not_connection_error` | exit=1 `LLMUnavailable/llm_connection_error` | exit=0 |
| C 恢复 auto_save 无痕 | `GameSession.auto_save` + PermissionError | `SILENT True` | `SILENT False`（warning 真因） |

---

## 质量 / 合法性

- 未改 `CLAUDE.md` / `AGENTS.md` / `CONTEXT.md` / ADR。
- 未新增永久扫描器、通用编排框架、第二运行配置。
- 未恢复手拟入口；未改四个第 8 项后端保留面。
- 净复杂度：入口编排副本合并；强杀/词面/退役包装删除；测试去内部形状。

---

## 剩余范围 / 阻断

- 剩余：#1902 其它已结交付面不在本轮；家族收尾/合并/关票不在授权内。
- 阻断：无（T1–T6 授权内可执行成员已清；宿主 CLI 鉴权若无结构化状态则如实当正文——宿主缺口已记录，不另造词表）。
