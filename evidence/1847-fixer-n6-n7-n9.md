# #1847 修内司报告：N6 / N7 / N9（全仓枚举补足）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5`
- 分支：`ak-roles/1847-fixer-n6-n7-n9`
- 派单：`01a0fac7-790d-75dd-a718-efb512b4d331@fixer`
- 末份裁定：`01-1847-judge-6d042ddd9.json`（只送修 N6/N7/N9；N8/X1/X2 跨票）
- 上轮证据因枚举谓词收窄（只盯 resolve/fail_condition；N9 以三符号当类定义；成员表用泛称）被打回；本轮按类定义全文重扫。
- **不宣称**全局功能闭环或已 merge

## 官方文档（动手前）

| 问题 | 文档 | 简单修法 |
|---|---|---|
| N7 stderr 冒充正文 | [Python subprocess](https://docs.python.org/3/library/subprocess.html) | 正文只取 stdout；空输出走既有失败 |
| N7 Codex | [Codex non-interactive](https://learn.chatgpt.com/docs/non-interactive-mode) | 禁止 banner/stderr 充正文 |
| N6 trim | [MDN String.prototype.trim](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/String/trim) | 自由文本运输不 strip/截断；判空可读 strip |

## 根因类定义（末份 + 票面，未收窄）

1. **N6**：适用自由文本运输接缝上的 strip/lstrip/rstrip/trim、切片截断、replace/regex/split/join/filter/非空后 fallback 等删改。范围含 LLM 产出、玩家输入、角色材料、数据库运输、UI 展示。不含机械身份、枚举、形式语言、仅判空。
2. **N7**：全部引擎 stdout/stderr 读取及空输出成功路线；禁止 stderr/banner 充正文或把空输出洗成成功。
3. **N9**：本票删除生产入口后的**私有闭包与专属测试**（调用图扫描，不以三符号为类定义）。保留生产共享与现役 0055 负向闸。

跨票不施工：**N8**（#1873）、**X1/X2**（#1826/#1873）。

## 可重跑枚举命令（冻结输出在 evidence/）

席内宽候选 `/tmp/1847-seat-candidates.txt`（1599 行）仅作参考输入；下列命令覆盖全仓执行源码，不按字段名收窄。

```bash
ROOT=/Users/akagilnc/WorkSpace/Ming_LLM-1847-w5
cd "$ROOT"

# 1) 宽 rg 候选（与席内文件同形，不限字段名）
rg -n --no-heading \
  '(\.strip\(|\.lstrip\(|\.rstrip\(|\.trim\(|\[:\s*[0-9]+\]|\.replace\(|re\.(sub|split|findall|search|match|fullmatch)|\.split\(|\.join\(|\.filter\()' \
  -g'*.py' -g'*.ts' -g'*.tsx' -g'*.js' \
  --glob '!**/node_modules/**' --glob '!**/.venv/**' --glob '!**/dist/**' \
  | tee /tmp/ming1847-fixer-scan/rg-wide.txt | wc -l

# 2) AST + TS 正则全量候选 → 冻结
#    产出：evidence/1847-n6-candidates-raw.tsv（本轮 2924 行数据 + 表头）
#    分类：evidence/1847-n6-members-classified.tsv（生产突变/相关 2252 行，逐行 disposition/reason/file:line）
#    复跑方式：将本报告同目录下既有一次性扫描逻辑在 /tmp 重跑后 diff 冻结 TSV；
#    本票不新增持久扫描模块（用冻结 TSV 代替）。

# 3) N7：引擎 stdout/stderr / 空输出
rg -n 'stderr|stdout|communicate|subprocess\.(run|Popen)|OpenAI Codex v|llm_empty_output|empty_output_failure|final_text|stdout_text' \
  ming_sim web_app.py launcher.py tests/test_cli_backend.py \
  | tee /tmp/ming1847-fixer-scan/n7-rg.txt
# 冻结分类表：evidence/1847-n7-members-classified.tsv

# 4) N9：退役闭包调用图（非三符号定义）
#    种子 = prepare_rescript_prewrite 历史调用邻域 ∪ focus 模块内名含
#    rescript|pihong|capability|prewrite|candidate_event|draft_capability 的定义
#    判定：无 ming_sim/web_app 生产调用方 → 退役闭包
# 冻结：evidence/1847-n9-members-classified.tsv

# 5) 本轮已修清单（短表）
# evidence/1847-fix-done.tsv
```

### 冻结文件

| 文件 | 行数（含表头） | 内容 |
|---|---:|---|
| `evidence/1847-n6-candidates-raw.tsv` | 2925 | 全仓 AST/TS 原始候选 |
| `evidence/1847-n6-members-classified.tsv` | 2253 | 生产侧逐实例分类（完整成员表） |
| `evidence/1847-n7-members-classified.tsv` | 203 | 引擎/测试 stdout·stderr 完整成员表 |
| `evidence/1847-n9-members-classified.tsv` | 13 | 调用图种子符号完整成员表 |
| `evidence/1847-fix-done.tsv` | 10 | 本轮+上轮已修短清单 |

**完整成员表以 TSV 为准**（每行含具体 `file:line` / kind / disposition / reason，不用泛称代替）。下表只摘录处置决策与本轮改动；其余 KEEP 行见 TSV。

## N6 处置摘要

### 本轮 FIX（运输删改 → 已修）

| 位置 | 类别 | 处置 |
|---|---|---|
| `ming_sim/session.py:1161` `scene_chat` 玩家问话 | 玩家输入运输 | **修**：`message_text` 原样；`.strip()` 仅判空 |
| `ming_sim/session.py:1016` `_ensure_close_night_confirm_cue` | LLM/回话运输 | **修**：`answer` 原样；判空可读 strip |
| `ming_sim/cli/terminal.py:397` `input("朕问：")` | 玩家输入运输 | **修**：原样；判空可读 strip |
| `ming_sim/cli/terminal.py:611` 新增指令 `input` | 玩家输入运输 | **修**：同上 |
| `ming_sim/cli/terminal.py:634` 改指令 `input` | 玩家输入运输 | **修**：同上 |

### 上轮已修（00e2d9a44，本轮复扫仍净）

| 位置 | 处置 |
|---|---|
| `issues.py:_issue_condition_text` / 写入无 `[:300]` | 条件自然语言零删改 |
| `materials.py:_visible_affair_lines` 条件原样；出栏判空 | 供料链净 |

### 复扫后无剩余 FIX

`evidence/1847-n6-members-classified.tsv` 中 `disposition` 以 `FIX` 开头的行数 = **0**。

代表性 KEEP 类别（完整行在 TSV，此处只说明判据，不替代表）：

- `KEEP_empty_check`：`if not x.strip()` / UI `trim()` 判空后走原值或固定 fallback
- `KEEP_identity_or_formal`：id/职官/枚举/形式语言 regex/JSON 解析前
- `KEEP_match` / `KEEP_match_or_normalize`：封闭前缀、接地匹配、分类器形状（不写回叙事原文运输）
- `KEEP_diag`：tlog/异常信息截断
- `KEEP_template_or_fingerprint`：静态 prompt；`#1356` 开局邸报 strip 指纹契约
- `KEEP_command`：收夜/宣召封闭口令匹配
- `KEEP_surrogate`：surrogate/控制字符，非语义裁剪
- `KEEP_structural`：join/split/filter 结构拼装未见自由文本删改
- `KEEP_ui_*`：配置项/按钮/布局判空；`format.ts:splitReportItems` 无调用方

## N7 完整扫描结论

冻结表：`evidence/1847-n7-members-classified.tsv`（202 数据行）。

| 结论 | 证据 |
|---|---|
| 生产无 `OpenAI Codex v` banner 切割 | `rg 'OpenAI Codex v' ming_sim` → 无 |
| 正文路径 | `_iter_cli_runner_text`：`text = stdout_text if stdout_text.strip() else final_text`；`final_text` 仅来自 stdout JSON 事件 |
| stderr 用途 | pipe 抽干；非零退出/ auth race 的 `provider_message` 诊断；**不交正文** |
| 空输出 | `empty_output_failure` / `llm_empty_output` |
| 负向闸 | `tests/test_cli_backend.py::test_run_codex_stderr_banner_does_not_become_body` 仍绿 |
| 非法成功测试 | 上轮已退役；本轮复扫无「stderr fallback 成功」锁 |

## N9 调用图结论（非三符号定义）

冻结表：`evidence/1847-n9-members-classified.tsv`。

种子扫描后 **GONE（定义与引用均已删除）**：

| 符号 | 说明 |
|---|---|
| `prepare_rescript_prewrite` | 生产入口已删（基线 diff） |
| `bind_decisions_to_candidate_events` | 上轮删 |
| `parse_rescript_capability_pair` | 上轮删 |
| `decision_has_rescript_capability` | 上轮删 |
| `RESCRIPT_CAPABILITY_DECISIONS` | 上轮删 |
| `derive_draft_capability` | **本轮删**（仅被旧票拟/prewrite 能力派生调用；HEAD 无生产调用） |
| `_DRAFT_CAPABILITY_KEYS` / `_DRAFT_CAPABILITY_JSON_KEYS` / `PARTICIPANT_ROSTER_KEY` | **本轮随 derive 闭包删除**（常量仅服务该闭包） |

保留（表中 `KEEP_*`，仍有生产调用或同模块服务现役导出）：

- `bind_decision_options` / `parse_decision_blocks` / `_DECISION_RE`
- `persist_answers` / `apply_imperial_deliberation_push` / `canonical_choice`（同模块服务 persist）
- `produce_memorials` / `consume_memorial_answers` / `triage_officers` / `run_rescript_text`（月链现役）
- 现役 0055 / month_chain_1847 负向闸测试未删
- 未重接旧六动作 / 未补 N8

## 代码改动摘要

- `session.py`：玩家问话与含糊收夜 cue 零 strip 运输
- `cli/terminal.py`：朕问/指令 input 零 strip 运输
- `decree_vocabulary.py`：删除退役 `derive_draft_capability` 闭包（约 −75 行）
- `tests/test_scene_llm_1836.py`：空白运输负向/正向回归
- `evidence/1847-*.tsv` + 本报告：可重跑冻结成员表

## 聚焦测试

前缀：七个 `MING_SIM_*_BIN=/usr/bin/false` + `MING_SIM_TRACE_PATH` / `--basetemp` → `/tmp/ming1847-fixer.*`  
解释器：`/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`（本工作树无本地 `.venv`）。

```text
tests/test_month_chain_1847.py
tests/test_pihong_dossier_1490.py
tests/test_month_chain_1843.py
tests/test_month_call_recovery_1846.py
tests/test_cli_backend.py
tests/test_rescript_choices_563.py
tests/test_llm_channel_config.py::test_scene_and_rescript_entries_pass_default_headers_at_transport
tests/test_new_issues_section_rejections.py::test_new_issue_whitespace_resolve_condition_falls_back_to_stop_condition
tests/test_scene_llm_1836.py
→ 211 passed in 13.17s
```

`web`：`npx tsc -p . --noEmit` → exit 0。

未跑全量；未做真实模型游戏验收。

## 变异证据

| 类 | 操作 | 红 | 绿 |
|---|---|---|---|
| N6 | 临时恢复 `message_text=….strip()` | `test_scene_chat_preserves_player_message_whitespace` 1 failed | 恢复后 1 passed |
| N7 | 既有负向闸 | — | `test_run_codex_stderr_banner_does_not_become_body` 1 passed |
| N9 | `from ming_sim.decree_vocabulary import derive_draft_capability` | ImportError | （保持删除） |

## 测试删改契约

- 新增：空白运输回归（scene_chat / confirm cue / CLI 朕问）——锁既有运输契约，非功能证明
- 未删 0055 / 空输出等现役闸
- 未新增 N8 功能测试

## 质量合法性自查（自查二连 done）

- 同类根因：全仓 AST/rg 枚举 + 冻结完整成员表；复扫 FIX=0
- 引入 bug：未恢复六动作、未补 N8/X1/X2、未 stash/amend/push/PR/全量
- 删简优先；无新机制/护栏/重试层
- 自建物仅工作树 `evidence/` 与 `/tmp/ming1847-fixer.*`；无持久扫描模块（冻结 TSV 代替）

## commitSha / 剩余跨票

- **生产修理 commitSha（上轮）**：`00e2d9a44828cd369e9624e8c263f85ebd5934bf`（条件运输 / N7 stderr / bind 闭包）
- **本轮生产+证据 commitSha**：见交卷 `git rev-parse HEAD`（单次记录，不为写 HEAD 反复 commit）
- **剩余跨票**：N8→#1873；X1→#1826；X2→#1873/#1826
