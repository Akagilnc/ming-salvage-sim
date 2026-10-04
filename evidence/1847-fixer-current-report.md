#1847 修内司交卷 — w7 四类（N6/N11/N13/N14）

- worktree: `/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- branch: `ak-roles/1847-fixer-w7-n6-n11-n13-n14`
- base HEAD（开工）: `bcf7a7bf7`
- 派单: `/Users/akagilnc/.ak-roles/books/Ming_LLM/unbound/runs/01a10906-b970-7021-8014-282026406f92@fixer/fix-packet.md`
- 判词真源: 附件 `03-1847-judge-bcf7a7bf7.json` **末份 payload**（共 4 payloads；先前 sealed 仅供参考）
- 禁令: 未 amend / rewrite / push / PR / stash；未触席位/宿主配置；临时物仅 `/tmp/1847-fixer-w7/`

## 修改前 advisor 检查

- 已读全局 `~/.claude/CLAUDE.md`、`~/.codex/AGENTS.md`、仓内 CLAUDE/AGENTS/CONTEXT、派单与四份判词。
- 已读 `diagnosing-bugs` skill；**跳过 Phase 3 假设阶段的依据**：末份判词对四类均给出独立探针证据与根因（merge 带回 strip、独占退役支链、软收尾吞异常+析构 force 默认、测试身份退化），本轮反馈环直接对准既确认根因做删简复验，不另立平行假设。
- 互联网官方文档（生命周期最简生态选择）：
  - [subprocess](https://docs.python.org/3/library/subprocess.html)：`terminate()`=SIGTERM；`kill()`=SIGKILL。本仓只走 terminate+wait。
  - [ptyprocess API](https://ptyprocess.readthedocs.io/en/latest/api.html)：`terminate(force=False)` 软信号；`close(force=True)` 默认可升 SIGKILL；**最简选择=`close(force=False)`**。
- 不新增监管/重试/适配/保护层。

## 未结四类（末份原文边界）

1. N6 活链路原文运输删改被合并重新带回  
2. N11 退役后端的独占支链及专属测试仍在  
3. N13 软终止没有覆盖完整生命周期，失败无痕且析构仍可强杀  
4. N14 测试退化为源码证明、同值复查及自由正文身份哨兵  

## 四类枚举谓词（覆盖判词类定义全文，不收窄为样本）

### N6 — 自由正文运输删改

谓词：生产路径上，对自由正文（故事账 body / 材料 opening / 玩家原文 / 注入戏文底）执行 strip/replace 等变换后，**把变换结果继续运输到去向**；判空用局部 `.strip()` 副本不算删改。

可复跑：

```bash
# 运输赋值：prose 名 = …strip() 且后续 append/return/join 运输该名
rg -n 'body = str\(entry\.get\("body"\) or ""\)\.strip\(\)' ming_sim/

# 对照：判空局部副本（应保留）
rg -n 'if .*\.strip\(\)' ming_sim/materials.py ming_sim/audience_night.py | head
```

| file | member | disposition | 来源→变换→去向 / 理由 |
|---|---|---|---|
| ming_sim/audience_night.py:2257 | `audience_scene_recap` body strip→append | **FIXED** | story_ledger.body → `.strip()` → SCENE_RECAP → materials `_spoken_this_scene` → opening |
| ming_sim/cli_backend.py | player_message/failed_slot strip→parts | **FIXED** | 玩家原文 → strip → 自愈接地拼接 |
| ming_sim/registry.py | scene_prompt.strip→instructions | **FIXED** | bundled 戏文底 → strip → Agent instructions |
| ming_sim/materials.py | `raw_latest if raw_latest.strip() else …` | KEEP_empty_local | 判空局部副本，非空运输原文 |
| ming_sim/materials.py | `spoken if spoken.strip() else …` | KEEP_empty_local | 同上 |
| ming_sim/audience_night.py | command recognize `text=message.strip()` | KEEP_form_language | 封闭口令匹配，非自由正文运输 |
| scripts/play_as_emperor.py | JSON envelope strip | KEEP_form_language | 形式 JSON 定位，input 字段原样取出 |

复扫：运输 strip 赋值谓词命中 **0**。

### N11 — 退役独占支链闭包

谓词：已失去真实生产消费者的专属定义/岛内调用/专属测试；按消费者闭包删，不按 legacy 字样猜删。现役共用读口保留。

可复跑：

```bash
rg -n 'rescript_summon_origin_ref|prepare_rescript_summon_scaffold|rescript_summon_origin_consumed|RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES|find_deliberation_dossier_by_decision_key|_extract_secret_order|assemble_secret_order_content|_DRAFT_PREFIXES|_SECRET_PREFIXES' \
  ming_sim/ scripts/ web_app.py tests/
# expect empty (exit 1)

rg -n '_ledger_by_origin_ref' ming_sim/audience_night.py
# expect def + live callers at office summon paths
```

| member | disposition | 闭包说明 |
|---|---|---|
| `rescript_summon_origin_ref` / `_consumed` / `prepare_rescript_summon_scaffold` | **DELETED** | 仅定义+岛内互调 |
| `RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES` + self-assert | **DELETED** | 仅定义与自断言 |
| `GameDB.find_deliberation_dossier_by_decision_key` | **DELETED** | 零消费者 |
| `_extract_secret_order` 及独占装配岛（`_CLAUSE_SPLIT`…`confirm_dossier_links`…`assemble_secret_order_content`…） | **DELETED** | 零生产调用；现役密令写口在 `declaration_dispatch` |
| `_DRAFT_PREFIXES` / `_SECRET_PREFIXES` | **DELETED** | 仅定义、无引用 |
| tests: extract/assemble/trace 专属案 + `_so_json` | **DELETED** | 独占测试 |
| `_ledger_by_origin_ref` | **KEEP_live_shared** | 现役 office summon 1764/1789/1808 |
| `tests/test_pihong_dossier_1490.py` 0055/无人站台/中旨/御笔强推 | **KEEP** | 判词明示保留 |
| `DOSSIER_LINK_TYPES`（constants） | **KEEP_shared** | db 现役消费者 |

复扫：退役符号生产/测试命中 **0**；`_ledger_by_origin_ref` 仍在。

### N13 — 完整软收尾生命周期

谓词：软终止失败被吞；析构/默认 `close(force=True)` 仍可达 SIGKILL；失败无真实留痕。

可复跑：

```bash
rg -n 'except Exception:\n        pass' -U ming_sim/cli_backend.py   # around terminate
rg -n 'terminate\(force=True\)|close\(force=True\)' scripts/play_as_emperor.py
rg -n 'close\(force=False\)' scripts/play_as_emperor.py
```

方案（生态已有，不加监管/重试）：

1. `cli_backend._terminate_cli_process`：仅 `terminate()`+`wait(timeout=5)`；异常上抛；`_iter_cli_process_lines` finally 写入 `result.stderr` 诊断，**不**从 finally 再 raise 以免覆盖原失败。
2. `play_as_emperor` finally：`child.close(force=False)`（官方软收尾）；若软失败，标记 pty/spawn closed 完成 FD 生命周期，避免 `PtyProcess.__del__` 默认 `close(force=True)`→SIGKILL；再 `raise` 保留软失败真因。

实测（自建忽略 SIGTERM 子进程，READY 握手）：

```
{'err': 'TimeoutExpired', 'alive': True, 'elapsed': 5.0}
```

不声称本轮生产路径发生过真实 SIGKILL。

### N14 — 测试质量

谓词：`inspect.getsource`/同值复查证明；用 note/正文/`str(row)` 哨兵替代结构化身份；绕过 `read_material`；删除 CR/CRLF 原文边界夹具。

可复跑：

```bash
rg -n 'inspect\.getsource' tests/test_advance_paths_atomic.py
rg -n 'decree_ref|target_id|read_material|\\\\r\\\\n' tests/test_month_chain_1847.py
```

| member | disposition |
|---|---|
| `test_skip_refused_at_front_half_done`（getsource+同值复查） | **DELETED** |
| supply feed note/`str(row)` 哨兵 | **RESTORED** → `decree_ref` / `item.origin_ref` / `item.target_id` |
| Path.read_text 绕过 | **RESTORED** → production `read_material` |
| CR/CRLF+尾空白 `fact_body` | **RESTORED** |
| 0055 负向闸（pihong 1490） | **KEEP** |

未新建证明性测试。

## 诊断反馈环

- 聚焦：七前缀 + 四文件 pytest（见下）——绿。
- 变异：N6 内存装回 strip→`preserves_raw=False`；当前 True。N13 忽略 SIGTERM→TimeoutExpired 且仍存活。N11/N14 复扫空/结构断言在。

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

实测输出：`155 passed in 10.02s`（real 11.36s）。未跑全量。

## 提交前质量复检

- `git diff --check`：无报错。
- 净删简：9 files, +95 / −776（复杂度下降）。
- 0055 / 无人站台 / 中旨 / 御笔强推案仍在 `tests/test_pihong_dossier_1490.py`。
- 无 secrets；无 amend/push/PR/stash。

## git 事实 / commit

```bash
git rev-parse HEAD~1   # delivery
git rev-parse HEAD     # report stamp
git status --porcelain=v1
git branch --show-current
```

- branch: `ak-roles/1847-fixer-w7-n6-n11-n13-n14`
- delivery commit（代码修复）: `b04ea3af3690a96268119bfb6f553b5289816a5c`
- 含报告的最新 HEAD：以 `git rev-parse HEAD` 为准（本交卷后可能仅有 docs 戳记）
- status: clean after final report polish commit

## 剩余事项

- 未 push / 未开 PR（派单禁止）。
- 家族收尾全量 suite 不在本轮（#1185 切片只跑聚焦）。
- 文档 `docs/issue-657-construction-contract.md` 仍提及已删 `RESCRIPT_EMITTED_*` 史迹字样——非生产消费者，未当本轮阻断；若后续文档扫可另票清理。
- X3/#1826/#1873 功能接线仍按家族边界，非本票阻塞。
