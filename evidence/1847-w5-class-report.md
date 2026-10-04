# #1847 w5 修内司 class report（劳务自验，非审官结论）

- worktree: `/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- base HEAD: `cb43ec63ad2dfee9a9326b41367beb69891ef675`
- branch: `ak-roles/1847-fixer-n6-n11-n12-n13`
- 末份判词真源: `02-1847-judge-cb43ec63a.json` payloads **最末份**（N6/N11/N12/N13）
- 既存未跟踪 `node_modules/` 未动；未 push / 未开 PR / 未 amend / 未 stash
- 官方查阅: [pexpect send/sendline](https://pexpect.readthedocs.io/en/latest/api/pexpect.html#pexpect.spawn.send)（不截输入；canonical 限制属终端模式，非应用层 200 字裁）；[pexpect.terminate(force)](https://pexpect.readthedocs.io/en/latest/api/pexpect.html#pexpect.spawn.terminate)（force=True → SIGKILL）；[subprocess.Popen.kill](https://docs.python.org/3/library/subprocess.html)（POSIX = SIGKILL）

## 末份未结类定义全文（不得收窄）

### N6：活链路原文裁剪仍未结清
- disposition: 成立，继续修理
- law: CLAUDE.md 引擎及呈现层对 LLM 自由文本零删改；全局原话传递宪法
- boundary: Web 条件原文运输已修好，但不代表全类结清。该脚本驱动活模型链路，不适用冻结卷宗统计例外；形式解析、固定菜单识别与自由正文裁剪须分判。
- 样本反例: `scripts/play_as_emperor.py` 将有效单行 input 截成 200 字后 send；先前误列 KEEP_structural

### N11：退役机制的状态、兼容形状及专属测试仍被维护
- disposition: 成立，须按类别删简
- law: #1812 被取代旧代码/兼容路径/专属测试删除；全局 #12/#13
- boundary: 不是因测试红封驳，也不要求恢复关键词猜测。现役行为契约及 0055 负向闸不得借清理误删。
- 样本: rank reanchor 标记维护、marker-only 测试、按 prompt 推断 tag 的专属测试、空 `pairing_warnings` 兼容形状及专属测试

### N12：删简后的多余替代接口与重复定义
- disposition: 成立，简化处理
- law: #1812 不新增机制；全局 #12 删简优先、#14 单一真源
- boundary: 删除无用替代接口、收敛重复定义即可；不另造 SDK 参数适配、标签运输层或新枚举机制。保留已合法化的结构字段读取。
- 样本: `ming_sim_caller_tag` 无调用方；ministerFilters / drawers 重复朝廷顺序

### N13：活探针保留可达 SIGKILL 终止路径
- disposition: 成立，移除违法终止机制
- law: 共享硬规 #9 严禁 SIGKILL
- boundary: 裁的是当前可达机制，不声称本轮发生了真实 SIGKILL；不得换成另一套强杀或硬时限护栏。
- 样本: `terminate(force=True)` → SIGHUP/SIGCONT/SIGINT/SIGKILL

---

## 全仓机械枚举命令（开工谓词）

```bash
# N6 — 活链路自由正文裁剪（运输前切片 / 输入截断）
rg -n --glob '!node_modules/**' --glob '!docs/**' --glob '!evidence/**' \
  -e 'action\s*=\s*action\[:|if len\(action\) > 200|输入截断|\[:200\].*send|len\([^)]+\)\s*>\s*200' \
  --type py scripts ming_sim web_app.py

# 辅助：sendline / 自由输入入口（区分菜单固定串 vs 自由正文）
rg -n --glob '!node_modules/**' --glob '!docs/**' --glob '!evidence/**' \
  -e 'sendline\(|\.send\(' scripts ming_sim web_app.py

# N11 — 退役状态 / 兼容形状 / 专属测试
rg -n --glob '!node_modules/**' --glob '!docs/**' --glob '!evidence/**' \
  -e '__leverage_offsets_rank_rules_562|pairing_warnings|infers_trace_tag|legacy_stem_reanchor|_infer_tag' \
  --type py

# N12 — 多余替代接口 / 重复定义
rg -n --glob '!node_modules/**' --glob '!docs/**' --glob '!evidence/**' \
  -e 'ming_sim_caller_tag|_guess_caller_tag' --type py
rg -n --glob 'web/src/**/*.{ts,tsx}' -e 'COURT_OFFICE_TYPE_ORDER|\["内阁".*"吏部"'

# N13 — 可达 SIGKILL
rg -n --glob '!node_modules/**' --glob '!docs/**' --glob '!evidence/**' \
  -e 'terminate\(force=True\)|proc\.kill\(|SIGKILL|signal\.SIGKILL' --type py
```

---

## 成员表与去留

### N6

| 候选 | 来源→契约→去向 | 处置 | 依据 |
|---|---|---|---|
| `scripts/play_as_emperor.py` `action[:200]` 后 `sendline` | 模型自由正文 → PTY 皇帝输入 | **删** | 末份样本；活链路自由正文裁剪；官方 send 不截 |
| `scripts/play_as_emperor.py` `raw[:200]` in ValueError | 解析失败诊断预览 | KEEP | 非运输正文；错误消息展示 |
| 同文件 `prompt_hint[:40]/[:8]` log | 日志预览 | KEEP | 非运输；日志 |
| `cli_backend` `_TRACE_FIELD_CAP` 截断 prompt/response | 本地 trace 落盘 | KEEP | 非游戏呈现/活输入运输；debug 盘 |
| `cli_backend` stderr/异常 `[:200]` | 异常消息 | KEEP | 非自由正文运输 |
| `context.py` JSON 坏值 `[:200]` | 契约错误消息 | KEEP | 非运输 |
| `agents.py` tool_res `[:200]` / 思考截断提示 | 内部遥测/思考流 | KEEP | 非皇帝输入/条件原文运输；形式流控 |
| `action_clusters` `FieldSpec.max_len` | 结构化字段长度 | KEEP | 形式/结构契约（boundary 分判） |
| Web 条件原文 humanize | 已修好 | KEEP | boundary：已修好保留；本轮非未结点 |
| 形式菜单 `quit`/`back`/`exit` 识别 | 固定菜单 | KEEP | boundary：固定菜单识别分判 |

### N11

| 候选 | 来源→契约→去向 | 处置 | 依据 |
|---|---|---|---|
| `db.py` init 块写 `__leverage_offsets_rank_rules_562` | 退役 reanchor → 空标记维护 | **删** | 末份样本；无生产消费者 |
| `db.py` `_calibrate_faction_offsets` 末行同标记 | 同上 | **删** | 同根 |
| `tests/.../test_rank_rule_legacy_stem_reanchor_marker_only_on_reload` | 只断言私有标记 | **删** | 专属退役测试 |
| `cli_backend._infer_tag` 恒 `other` 残 stub | 已删关键词推断后的空壳 | **删**（调用改 `other`） | 退役推断接口残余 |
| `tests/.../test_run_backend_infers_trace_tag_from_prompt` | 仍要求 prompt→tag | **删** | 专属退役测试；不恢复猜测 |
| `issues.pairing_warnings: []` 返回键 | 空兼容形状，无运行时读者 | **删** | 末份样本 |
| `tests/test_initiative_resolve_pairing.py` | 只断言空列表 | **删文件** | 专属兼容测试 |
| `tests/test_person_delta_adapter.py` `pairing_warnings not in applied` | 负向：applied 契约不含该键 | KEEP | 现役行为契约负向 |
| 0055 / rescript 负向闸与现役决策解析 | 现役 | KEEP | boundary 明令不得误删 |
| `__leverage_offsets_calibrated` / `__leverage_offsets_float_v2` | 仍服务现役校准/精度迁移 | KEEP | 非退役空标记 |

### N12

| 候选 | 来源→契约→去向 | 处置 | 依据 |
|---|---|---|---|
| `token_stats._guess_caller_tag` + `ming_sim_caller_tag` | 无调用方提供的替代标签接口 | **删**；日志固定 `?` | 末份样本；不造 SDK pop 适配 |
| `ministerFilters` 六部 Set 与 COURT 列表重复 | 同枚举两份 | **收敛**：MINISTRY 由 COURT 导出 | #14 |
| `drawers.tsx` 内联朝廷 office 列表 | 与 ministerFilters 重复 | **改引用** `COURT_OFFICE_TYPE_ORDER` | 末份样本 |
| 合法结构字段读取（office_type 等） | 结构契约 | KEEP | boundary |
| SDK Completions.create 签名 | 原生 | KEEP | 不另造参数适配层 |

### N13

| 候选 | 来源→契约→去向 | 处置 | 依据 |
|---|---|---|---|
| `play_as_emperor.py` `terminate(force=True)` | 活探针收尾 → SIGKILL | **改** `force=False` | 末份样本；官方 force→SIGKILL |
| `cli_backend._terminate_cli_process` `proc.kill()` | CLI 子进程收尾 → SIGKILL | **删** kill 升级；仅 terminate | 同根可达 SIGKILL；#9 |
| 注释中的「禁 SIGKILL」说明 | 文档 | KEEP | 非机制 |
| `web_app` `SIGTERM` 自进程 | 非 SIGKILL | KEEP | 信号不是 SIGKILL |
| `tests/cli_process_doubles.terminate` | 测试双 | KEEP | 无 SIGKILL |

---

## 真实入口确定性变异（临时 `/tmp/1847-w5-probe/`，非永久测试）

环境前缀七变量均 `/usr/bin/false`。命令：

```bash
MING_SIM_*_BIN=/usr/bin/false \
  /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python /tmp/1847-w5-probe/mutate_verify.py
```

输出摘要：

```
=== N6 ===
LONG_len 269
OLD 269 200 200 False
CUR 269 269 True True
N6_MUTATION_OK
=== N13 ===
OLD [SIGHUP, SIGCONT, SIGINT, SIGKILL] True True
CUR [SIGHUP, SIGCONT, SIGINT] False False
N13_MUTATION_OK
=== N11 ===
marker_present_on_fresh_open False
marker_after_old_stamp True
marker_after_reopen_current False
pairing_warnings_in_return False
trace_tag_without_explicit other ok
N11_MUTATION_OK
=== N12 ===
sdk_has_kw False
N12_MUTATION_OK
ALL_MUTATIONS_OK
```

含义：
- N6：旧 `[:200]` 运输丢「不得动内库」；删裁后 PTY 收满 269 字。
- N13：`force=True` 序列含 SIGKILL；现行 `force=False` 不含；生产无 `proc.kill()`。
- N11：新档不写退役标记；装回旧 stamp 后为 True；清标记再开现行 GameDB 仍为 False；`pairing_warnings` 键消失；无显式 tag 时 trace=`other`（不按 prompt 猜）。
- N12：SDK 无 `ming_sim_caller_tag`；生产不再读该 kw；朝廷顺序单源导出。

## 聚焦测试

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest \
  tests/test_month_chain_1847.py tests/test_pihong_dossier_1490.py \
  tests/test_month_chain_1843.py tests/test_month_call_recovery_1846.py \
  tests/test_cli_backend.py tests/test_rescript_choices_563.py \
  tests/test_llm_channel_config.py::test_scene_and_rescript_entries_pass_default_headers_at_transport \
  tests/test_new_issues_section_rejections.py::test_new_issue_whitespace_resolve_condition_falls_back_to_stop_condition \
  tests/test_scene_llm_1836.py tests/test_office_rank_562.py \
  -q --basetemp=/tmp/1847-w5-pytest/pytest
```

输出：`218 passed in 15.94s`

```bash
cd web && 同七变量前缀 npx tsc -p . --noEmit
```

输出：`TSC_EXIT=0`

未跑全量；未跑活模型网络。

## 净变更

`10 files changed, 18 insertions(+), 143 deletions(-)`（提交前 `git diff --stat`）

## 未结范围（劳务自述）

- 本轮只处理末份未结 N6/N11/N12/N13；N10 及更早结清类未重开。
- X3 `_ledger_by_origin_ref` 静态残留、#1826/#1873 功能缺口不在本票阻断范围，未施工。
- 此乃修内司自验，非大理寺/御史台结论。
