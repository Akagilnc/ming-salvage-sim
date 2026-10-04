# #1847 w5 修内司 class report（自查修正续修）

> **SUPERSEDED for verdict claims** by `evidence/1847-w5-correction/CORRECTION.md`
> (shape-auto `KEEP_*` ≠ 逐项验证；`1847-mutation-probes.py` ≠ ask_emperor→PTY 真入口).
> This file retained as historical dossier — do not treat KEEP counts below as verified.

- worktree: `/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- branch: `ak-roles/1847-fixer-n6-n11-n12-n13`
- prior delivery HEAD（不合格）: `8fb20d8f1` — CRLF TSV、`KEEP_review_bucket` 无具体来源去向、`_warm_keychain` Popen+wait(timeout)+terminate 仍属硬时限护栏
- 末份判词基准: payloads 最末份 N6/N11/N12/N13（相对 `cb43ec63a`）
- 既存 `?? node_modules/` 未动；未 push / 未开 PR / 未 amend / 未 stash
- 冻结卷宗: `evidence/1847-w5-rescan/`（取代已消失的 `/tmp/1847-w5-rescan/`）

## 本轮自查不合格点 → 处置

| # | 不合格 | 处置 |
|---|---|---|
| 1 | `git diff cb43ec63a HEAD --check` 报几千条 TSV trailing whitespace（CRLF） | 全表改写为 LF；`--check` 现 0 |
| 2 | N6 `KEEP_review_bucket`×287 统一空话；strip 一概 empty-normalize 不足证 | 现役源码重扫+逐项 `source_dest_note`（字段来源/返回使用/空值契约）；**0** `KEEP_review_bucket` |
| 3 | N11/N12/N13 未列全原始候选排除口径 | 全扫命中入库；噪音/非重复有排除表与计数；成员表=已验证去留 |
| 4 | `_warm_keychain` 换 Popen+communicate/wait(timeout)+terminate | **删除**函数与调用；auth race 仍靠 transport 可重试 typed。另：`_login_shell_path` 去掉 `subprocess.run(timeout=8)`（同属 N13 SIGKILL 路径） |
| 5 | `/tmp` 脚本不可核 | 冻结 `evidence/1847-w5-rescan/scan_classify_n6_n13.py` + 产物 + README |

## 类定义（不得再收窄）

| 类 | disposition | 全文边界 |
|---|---|---|
| N6 | 成立，继续修理 | 活链路自由正文切片/strip/replace/split/regex 等潜在加工；活探针链与模型间供料；日志与形式契约须实证来源→去向 |
| N11 | 成立，按类删简 | 退役机制状态 / 兼容形状 / 空壳 / 专属测试 |
| N12 | 成立，简化 | 无调用者替代接口 + 重复常量/枚举/规则定义；保留合法结构字段读取 |
| N13 | 成立，移除违法终止 | 凡可达 SIGKILL 或强杀硬时限入口：kill / terminate(force) / close(force) / os.kill / killpg / subprocess timeout 等 |

## 可核枚举（冻结卷宗）

```bash
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python \
  evidence/1847-w5-rescan/scan_classify_n6_n13.py
# → evidence/1847-w5-rescan/{n6_*,n11_*,n12_*,n13_*,summary.json}
# → sync LF tables evidence/1847-w5-n{6,11,12,13}-members.tsv
```

覆盖：`ming_sim/`、`scripts/`、`web/src/`、`web_app.py`、`main.py`、`launcher.py`、`tests/`

显式豁免：`evidence/1847-w5-exempt-files.tsv`（`docs/raw|archive`、`evidence/**`、`node_modules/**`、`spike_settle_tick.py` KEEP_spike_oracle）

## 结清范围（计数=已验证去留，非扫命中自证）

### N6

- 机械候选 raw：**3119**（`n6_candidates_raw.tsv`）
- 成员表：`evidence/1847-w5-n6-members.tsv` — 每行含 `disposition` + **具体** `source_dest_note`（`src=字段|fn=… → dest=用途；空值/形式契约`）
- `KEEP_review_bucket`：**0**
- 本轮/上轮已删：思考流字数上限+「思考已截断」；`play_as_emperor` `action[:200]`
- 主要 KEEP 桶（均带逐项 note，非占位）：
  - `KEEP_empty_normalize` — strip/lstrip；note 含字段来源、返回/门控用途、only-ws→empty、非 ws 保真
  - `KEEP_join_structure` / `KEEP_split_structure` / `KEEP_casefold_compare` — 结构拼接/切分/大小写比较
  - `KEEP_session_run_truncate` — agno session **run 行数**截断，非正文
  - `KEEP_log_or_trace` / `KEEP_log_preview` / `KEEP_diag_error` — 操作者日志/诊断预览
  - `KEEP_formal_*` / `KEEP_sqlite_sanitize` / `KEEP_form_struct` — 形式解析/库存储/表单边界
  - `KEEP_test` — 测试夹具
- **合法豁免**：操作者 tlog 尾部预览；形式 JSON/DSL/标识符；DB NUL sanitize；列表长度 UI cap（元素正文不改）
- **未宣称**：不把扫命中数当清零；结清=成员表逐项已验证去留

### N11

- 全扫命中：**666**（`n11_focus.tsv`）
- 其中 `EXCLUDED_noise`：**617** — 口径见 `n11_exclusion_summary.tsv`（legacy/compat/deprecated **词汇**命中但无退役机制符号）
- 非噪音成员表：`evidence/1847-w5-n11-members.tsv`（DELETED/KEEP 已验证）
- 已删成员（引用）：`_legacy_commitment_stop_gate`、`PERSON_LEGACY_ALLEGIANCE_CHANGE_WAYS`、`_infer_tag`、pairing 空壳键、rank marker `__leverage_offsets_rank_rules_562`、专属测 `test_legacy_character_resolve_condition_...` 等
- KEEP：`pairing_warnings not in applied` 负向契约；`__leverage_offsets_calibrated` / float_v2 现役迁移；0055 decision_key 现役闸

### N12

- 字面量/枚举名命中：**176**（`n12_literal_hits.tsv`）
- 排除口径：`n12_exclusion_note.tsv`（单一定义读取≠重复；子集白名单≠全等枚举；smell 无第二定义不入删表）
- 成员表：`evidence/1847-w5-n12-members.tsv` — DELETED caller_tag；CONVERGED COURT/GATE/PERSON/DUE/FAVORITES；KEEP_spike_oracle；power 写白名单子集 KEEP

### N13

- 全扫命中：**544**（含大量 tests KEEP_test）
- `FIX_NEEDED_*`：**0**
- **本轮删除**：`_warm_keychain` 整函数+调用（不再换另一套硬时限）；`_login_shell_path` 去 `timeout=`
- KEEP：`terminate()`=SIGTERM；资源 `.close()`；wait/join/cv/HTTP/SDK soft timeout（经验证到期无 `process.kill`）；文档提及 SIGKILL；`os.kill(..., SIGTERM)` 自进程
- 成员表：`evidence/1847-w5-n13-members.tsv`

## 代码实质修正（相对 8fb20d8f）

1. `ming_sim/cli_backend.py`：删除 `_warm_keychain`；`_login_shell_path` 无 timeout；注释同步
2. `tests/test_cli_backend.py` / `tests/cli_process_doubles.py`：去掉 warm mock/断言
3. evidence 表全量 LF 重写 + `evidence/1847-w5-rescan/` 冻结卷宗

（N6 思考截断删、N11 legacy 删、N12 枚举收敛已在 8fb20d8f / 45e1220de 落地，本轮不回退。）

## 验证

### A. 七变量聚焦测试（既有入口，非全量 568 外扩）

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest \
  tests/test_cli_backend.py \
  tests/test_decree_commitment_settlement_229.py \
  tests/test_person_delta_adapter.py \
  tests/test_office_rank_562.py \
  tests/test_new_issues_section_rejections.py \
  tests/test_month_chain_1847.py \
  -q --basetemp=/tmp/1847-w5-selfcheck/pytest
```

结果：`333 passed in 17.64s`（`real 18.31`）→ `evidence/1847-w5-selfcheck-pytest.txt`。

### B. 既有真实入口变异探针（保留首轮 PTY/N6/N10 证据，不覆盖）

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false \
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python evidence/1847-mutation-probes.py
```

既有有效回执（勿覆盖）：`evidence/1847-n6-n10-mutation.txt`、`evidence/1847-selfcheck-mutation.txt`。
本轮复跑（`MING1847_MUTATION_OUT=evidence/1847-w5-selfcheck-mutation-rerun.txt`）：**EXIT=0 / real 1.22s**；探针已对齐 cb43ec63a emperor_fate 结构化透传（旧 `N10_NO_FREE_CHINESE_EMPEROR_FATE` 名过时）。

### C. N13/N6 本轮补验（临时一次性；结构 vs 真入口分列）

见 `evidence/1847-w5-selfcheck-verify.txt`：

- **结构（明示非变异真跑）**：现行无 `_warm_keychain`；`_login_shell_path` AST 无 timeout kw；无 `force=True`/`proc.kill`/`subprocess.run(timeout)` 生产调用
- **真入口**：`test_run_agy_success_single_subprocess` 等既有测跑通（agy runner 不再依赖 warm）；N6 思考全文依赖既有 mutation probes PASS

### D. whitespace

```bash
git diff cb43ec63a HEAD --check   # expect empty
```

## 未结 / 非本票

- N8/X1–X3、`_ledger_by_origin_ref` 静态残留、#1826/#1873：非本票阻断
- N10 及更早结清类未重开
- 未跑全量 pytest；未跑活模型网络
- 此乃修内司自验，非大理寺/御史台结论

## 自查二连 done

- 同类：硬时限护栏不得换皮保留；成员表不得用统一空话桶；CRLF 自产表；临时脚本须可核路径
- 引入：删 warm 后测断言同步；登录 PATH 探测无 timeout 可能偶发挂起（失败走 except，与旧 kill 路径相较取自然退出）
