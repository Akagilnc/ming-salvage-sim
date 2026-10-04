# #1847 w5 修内司 class report（全仓按类定义枚举续修，劳务自验）

- worktree: `/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- prior fixer HEAD: `45e1220de9a1246334a414099eb973ff961812ff`（点名白名单谓词过窄）
- branch: `ak-roles/1847-fixer-n6-n11-n12-n13`
- 末份判词: `02-1847-judge-cb43ec63a.json` payloads **最末份**（N6/N11/N12/N13）
- 既存 `?? node_modules/` 未动；未 push / 未开 PR / 未 amend / 未 stash
- 自建临时目录: `/tmp/1847-w5-rescan/`、`/tmp/1847-w5-rescan2/`（仅本轮扫描/验证）

## 上轮收窄问题（本轮纠正）

上轮开工谓词把类定义收成点名白名单：
- N6 仅 `action/200`
- N11 仅点名符号
- N12 仅点名 tag/列表
- N13 仅 `proc.kill` / `force=True`

本轮按判词类定义全文重开机械枚举（实例≠白名单）。

## 类定义（不得再收窄）

| 类 | disposition | 全文边界 |
|---|---|---|
| N6 | 成立，继续修理 | 活链路自由正文切片/strip/replace/split/regex 等潜在加工；活探针链与模型间供料；日志与形式契约须实证来源→去向，不得笼统「思考流即豁免」 |
| N11 | 成立，按类删简 | 退役机制状态 / 兼容形状 / 空壳 / 专属测试；结合底座→当前删除定义及引用检查 |
| N12 | 成立，简化 | 无调用者替代接口 + 重复常量/枚举/规则定义；不另造适配/新枚举机制；保留合法结构字段读取 |
| N13 | 成立，移除违法终止 | 凡可达 SIGKILL 或强杀硬时限入口：kill/terminate(force)/close(force)/os.kill/killpg/subprocess timeout 等；尤其 pexpect 默认 close(force=True) 与 subprocess.run(timeout) |

## 覆盖与豁免（显式，非静默）

```bash
git ls-files | wc -l                    # 1317
git ls-files | rg -i '\.(py|ts|tsx|js|jsx|mjs|cjs)$' | wc -l   # 431
```

显式归档/第三方豁免（见 `evidence/1847-w5-exempt-files.tsv`）：
- `docs/raw/`、`docs/archive/`、`evidence/`（历史冻结卷宗/探针产物）
- `node_modules/`（未跟踪第三方；未扫、未改）
- `spike_settle_tick.py`：**已扫入 N12**，处置=KEEP_spike_oracle（一次性 oracle 镜像，非静默排除）

生产扫描面：`ming_sim/`、`scripts/`、`web/src/`、`web_app.py`、`main.py`、`launcher.py`、`tests/`（测试参与 N11 专属测试判定）。

## 可核枚举命令（本轮开工谓词）

```bash
# 文件宇宙
git ls-files | rg -i '\.(py|ts|tsx|js|jsx|mjs|cjs)$' \
  | tee /tmp/1847-w5-rescan/prod-script-files.txt

# N6 — 全潜在正文加工（切片 + 变异调用 + 关键词）；临时 AST 见 /tmp/1847-w5-rescan/scan_n6_n13.py
rg -n --glob '!node_modules/**' --glob '!docs/raw/**' --glob '!docs/archive/**' --glob '!evidence/**' \
  -e '\[\s*:\s*\d+\s*\]' --type-add 'web:*.{ts,tsx,js,jsx}' -t py -t web \
  ming_sim scripts web_app.py web/src main.py launcher.py tests
rg -n --glob '!node_modules/**' --glob '!docs/raw/**' --glob '!docs/archive/**' --glob '!evidence/**' \
  -e '\.(strip|replace|split|sub)\s*\(|re\.(sub|split|findall|search|match|compile)\s*\(|humanize|截断|truncate|max_len|FIELD_CAP' \
  -t py ming_sim scripts web_app.py

# N11 — 退役标记/兼容键/空壳/legacy 名 + 底座删除符号残留引用
rg -n --glob '!node_modules/**' --glob '!docs/raw/**' --glob '!docs/archive/**' --glob '!evidence/**' \
  -e '__leverage_offsets_|pairing_warnings|_infer_tag|_guess_caller|legacy|退役|marker.?only|compat|deprecated' \
  -t py ming_sim scripts web_app.py tests
git diff 2f20f18bd..HEAD -U0 -- '*.py' '*.ts' '*.tsx' | rg '^-((async )?def|class|export )'

# N12 — 重复字面量列表/集合 + 无调用替代名气味
# 临时脚本 /tmp/1847-w5-rescan/scan_refine.py → n12_duplicate_consts.tsv / n12_smell_names.tsv
rg -n 'COURT_OFFICE|MINISTRY_OFFICE|GATE_METRIC|_LEGACY_ACCOUNT|DUE_SUBJECTS|_DUE_KEYS|_DEFAULT_FAVORITES' \
  ming_sim web_app.py web/src

# N13 — 强杀/硬时限入口（含 subprocess timeout / pexpect close / signals）
rg -n --glob '!node_modules/**' --glob '!docs/raw/**' --glob '!docs/archive/**' --glob '!evidence/**' \
  -e '\.kill\s*\(|os\.kill|killpg|SIGKILL|terminate\s*\(|\.close\s*\(\s*force|subprocess\.(run|call|check_output)\s*\(|timeout\s*=' \
  -t py ming_sim scripts web_app.py launcher.py tests
# 辅证：CPython subprocess.run 在 TimeoutExpired 路径调用 process.kill()（POSIX=SIGKILL）
```

原始扫描产物（临时，非永久机制）：
- `/tmp/1847-w5-rescan/n6_candidates_raw.tsv`（4168）
- `/tmp/1847-w5-rescan/n6_focus.tsv`（2092）
- `/tmp/1847-w5-rescan/n13_focus.tsv`（302）
- `/tmp/1847-w5-rescan/n11_focus.tsv` / `n12_duplicate_consts.tsv`

入库分类成员表（可核）：
- `evidence/1847-w5-n6-members.tsv`（2092 行数据）
- `evidence/1847-w5-n11-members.tsv`
- `evidence/1847-w5-n12-members.tsv`
- `evidence/1847-w5-n13-members.tsv`
- `evidence/1847-w5-exempt-files.tsv`

## 枚举数量摘要

| 类 | 原始/聚焦候选 | 本轮+上轮删简要点 | 复扫残留违法入口 |
|---|---|---|---|
| N6 | raw 4168 / focus 2092 | 删 play `action[:200]`；删 agents `_THINKING_STREAM_CHAR_LIMIT`/`思考已截断` | 复扫无 action 裁、无思考截断常量；余多为形式/日志/诊断 KEEP |
| N11 | focus 1635（含大量 legacy 词噪音） | 删 rank marker/pairing/_infer_tag 及专属测；本轮再删 `_legacy_commitment_stop_gate`+专属测+`PERSON_LEGACY_ALLEGIANCE_CHANGE_WAYS` | `pairing_warnings not in applied` 负向契约保留 |
| N12 | dup groups 9 + smell 99 | 删 caller_tag；收敛 COURT/favorites/GATE/PERSON_STATUSES/DUE | spike oracle 显式 KEEP；power 写白名单子集 KEEP |
| N13 | focus 302 | 删 force=True、proc.kill；本轮改 `_warm_keychain` 去 `subprocess.run(timeout)` | 复扫无 force=True/proc.kill/run(timeout)；剩 SIGTERM/资源 close/软 wait |

## 本轮实质修正（相对 45e1220de）

### N6
- `ming_sim/agents.py`：删除思考流字符上限与「思考已截断」注入；`on_thinking` 原样收全文。`tlog` 仍可预览尾部（dest=操作者日志，已分判）。

### N11
- `ming_sim/issues.py`：删除 `_legacy_commitment_stop_gate`（旧档 `resolve_condition` 散文→gate 兼容）；`_commitment_stop_gate` 只读结构化 `stop_condition`。
- 删除专属测 `test_legacy_character_resolve_condition_commitment_settles_when_threshold_reached`。
- 删除无引用 `PERSON_LEGACY_ALLEGIANCE_CHANGE_WAYS`。
- 清理 `test_new_issues_section_rejections.py` 对已删 pairing helper 的注释残留。

### N12
- `_LEGACY_ACCOUNT_KEYS` → `GATE_METRIC_KEYS`
- `MINISTRY_OFFICE_TYPES = COURT_OFFICE_TYPES - {"内阁"}`
- person status 集合 → `PERSON_STATUSES`
- `fiscal_tick._DUE/_ARREARS` → `pay_order.DUE_SUBJECTS/ARREARS_SUBJECTS`
- `web_app._DEFAULT_FAVORITES` 单源

### N13
- `_warm_keychain`：去掉 `subprocess.run(..., timeout=5)`（stdlib TimeoutExpired→`process.kill()`=SIGKILL）；改为 `Popen` + `terminate` 软停，超时不 kill。
- 注释修正：idle 收尾写明 SIGTERM，禁 SIGKILL。
- `play_as_emperor` 仍 `terminate(force=False)`，且不调用 `child.close()`（pexpect `close` 默认 `force=True` 的结构风险已避开）。

## 复扫结果（修正后）

```text
N6 THINKING_STREAM / 思考已截断 → NONE
N6 action[:200] play → NONE
N11 rank/pairing/_infer/_legacy_commitment/PERSON_LEGACY → 仅负向 assert pairing_warnings not in applied
N13 force=True / proc.kill / subprocess.run(timeout) 生产 → NONE（仅文档提及 SIGKILL）
web_app os.kill(..., SIGTERM) 自进程 → KEEP_sigterm_self
```

## 结构探针（非「真实入口变异」、非 BIN 伪 shell 作证）

命令前缀七变量仅用于随后 pytest，不作为本探针证据。

```bash
# AST：_warm_keychain 无 run/kill，有 Popen/terminate
# stdlib：subprocess.run 源码含 process.kill()（说明旧 timeout 路径为何违法）
# 局限：未向 OS 实发 SIGKILL；未跑活模型 PTY；签名/AST ≠ 真实入口变异
```

输出：`ALL_STRUCTURAL_OK`；明示 `LIMITATION: structural only`。

旧逻辑→现行：
- N13：旧 `subprocess.run(timeout)` 结构上可走 stdlib kill；现行 AST 无 kill。
- N6：旧思考上限会截断 `on_thinking`；现行全文传递。
- N11：装回 legacy stop gate 会使专属旧测再绿；现行该测已删、行为改为无 stop_condition 则无门。**局限**：旧档仅有 `resolve_condition` 散文、无 `stop_condition` JSON 的承诺案，不再自动按忠诚阈值结案（#1812 无历史包袱；现役路径用结构化 stop_condition，见保留测 `test_character_loyalty_commitment_ongoing_...`）。

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
  tests/test_new_issues_section_rejections.py \
  tests/test_scene_llm_1836.py tests/test_office_rank_562.py \
  tests/test_person_delta_adapter.py \
  tests/test_decree_commitment_settlement_229.py \
  tests/test_fiscal_substrate_bridge.py \
  -q --basetemp=/tmp/1847-w5-rescan2/pytest
```

输出：`568 passed in 39.78s`

```bash
cd web && 同七变量前缀 npx tsc -p . --noEmit
```

输出：`TSC_EXIT=0`

未跑全量；未跑活模型网络。

## 未结范围（劳务自述）

- N6 `KEEP_review_bucket`（~287）与大量 `KEEP_form_parse_or_empty`：已按来源→去向分桶，未发现新的活链路自由正文→皇帝/模型供料裁剪；若后续审官对某桶提出实证反例，再按同类删简。
- N8/X1–X3、`_ledger_by_origin_ref` 静态残留、#1826/#1873 功能缺口：非本票阻断，未施工。
- N10 及更早结清类未重开。
- 跨语言（py COURT set vs ts COURT_OFFICE_TYPE_ORDER）未强行单文件真源（避免新运输层）；各自仓内已收敛。
- 此乃修内司自验，非大理寺/御史台结论。
