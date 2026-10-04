# #1834 修内司回执 · F3-N / F16-R / F17-R（continued-ruling）

**工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1834-w5`
**分支**：`ak-roles/1834-f16-f3-f3r-f17-ee3b5da31`
**基线**：`ee3b5da312c5832720d89aee707fe4c7669c5eb0`
**父 HEAD（开工）**：`37af3a31af0421404f7150a476f9276393336acc`
**本轮 commit**：`(stamp after commit)`
**判词**：`evidence/1834-f16-f3-f3r-f17-fix/continued-ruling.json`
**法源**：`~/.ak-roles/books/Ming_LLM/1834/runs/01a108e1-9340-777b-887c-0a7243cf3984@fixer/fix-packet.md` + `attachments/02-1834-judge-ee3b5da31.json`；CLAUDE.md P6/P7；ADR 0142；#1901 删除提交 405fe5075 / b7cdcd639 / 192603c52。

**共同测试前缀（七变量，实写）**：

```bash
MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false
```

方向检索：Python dataclasses frozen / ADR 正文不可静默改写惯例（官方网络）；本票处置仍以仓内 ADR 0142、判词与真实调用为准。

---

## 1. F3-N「恢复越界：措辞/模板锁」

### 枚举命令（完整）

见 `enum_f3n_rescan.txt`：

```bash
rg -n --glob 'tests/**/*.py' --glob 'web/**/*.{ts,tsx}' \
  '不足额|应拨10两|实拨\{|人物终态：dead|后事。（天启|臣\.\*叩见|恭请圣安|名实已乖'
rg -n '许誉卿' tests/test_promulgation_judge_561.py
rg -n '途中病故|后事。' tests/test_secret_order_monthly_progress_566.py tests/test_relation_seed_638.py
git diff ee3b5da31 -- tests/ web/src/components/modals.test.tsx \
  | rg '^\+.*(不足额|应拨10两|人物终态：dead|后事。（天启|叩见|恭请圣安|参与人.*capsys|名实已乖)' \
  || echo NO_RESTORED_PROSE_LOCKS
```

### 成员表与处置

| 成员 | 处置 | 依据 |
| --- | --- | --- |
| `web/src/components/modals.test.tsx` `not.toMatch(/臣.*叩见\|恭请圣安/)` | **WITHDRAWN** | #1901 `405fe5075` 已删同一行；结构契约 `.chat-empty-chrome` 非空 + `.chat-message.minister` null 已在 |
| `tests/test_decree_dossiers_571.py` `assert "参与人" in capsys…` | **WITHDRAWN** | #1901 `b7cdcd639` 删 prose lock；无独立结构替代需要新增 |
| 同上 `"不足额"` / `"应拨10两"` / `实拨{n}两` in `execution_note` | **WITHDRAWN** | #1901 `192603c52` 删引擎模板句锁；保留 `status`/`execution_outcome`/国库结构断言 |
| `tests/test_dossier_reported_progress_619.py` `"名实已乖" in execution_note` | **WITHDRAWN** | #1901 同删；保留 outcome 结构断言 |
| `tests/test_secret_order_monthly_progress_566.py` `"人物终态：dead；途中病故"` | **RESTORED_PASSTHROUGH** | 改回输入子串 `"途中病故"`（非模板前缀锁） |
| `tests/test_relation_seed_638.py` `recent_context == "后事。（天启六年二月）"` | **RESTORED_PASSTHROUGH** | 改回 `"后事。" in recent_context`（不锁括号期号拼装） |
| `tests/test_promulgation_judge_561.py` `"许誉卿" in _gatekeeper_names(after)` | **KEEP** | 判词点名独立契约锚点；仍在 L692 |

复扫：CMD1 仅命中 docstring（565/567），无断言层模板锁；CMD4=`NO_RESTORED_PROSE_LOCKS`。未批量恢复其它旧断言。

---

## 2. F16-R「自由正文搬运 / 手核表模板 KEEP」

### 撤销

- `f16_hand_member_table.tsv` 证据地位 **撤销**（`f16_hand_member_table.REVOKED_TEMPLATE.txt`）：大量 KEEP 用同一模板句代入字段名。

### 枚举命令（完整）

见 `enum_f16_rerun_meta.txt` / `f16_hand_verify_after_ruling.METHOD.txt`：

```bash
rg -n --glob 'ming_sim/**/*.py' --glob 'web_app.py' --glob 'web/src/**/*.{ts,tsx}' \
  '\.strip\(\)|\.trim\(\)|\[:\d+\]|re\.sub\('
# → enum_f16_rewrite_shapes_rerun.txt  HIT_COUNT=1820

rg -n --glob 'ming_sim/**/*.py' --glob 'web_app.py' \
  '^\s*(crime|origin_context|criterion_text|decree_text|draft_text|memorial_text|execution_note|recent_context|player_message|clear_narrative|status_reason|failure_reason|hint|context|note|body|reason|title|text)\s*=\s*.*\.strip\(\)'
# → enum_f16_freeprose_assign_strip.txt  (58)

rg -n --glob 'ming_sim/**/*.py' --glob 'web_app.py' \
  '\.get\(["'\''](crime|origin_context|criterion_text|decree_text|draft_text|memorial_text|execution_note|recent_context|player_message|clear_narrative|status_reason|failure_reason|hint|context|note|body|reason|title)["'\'']\)[^;\n]{0,40}\.strip\(\)'
# → enum_f16_freeprose_get_strip.txt  (15)
```

### 权威处置表

`f16_hand_verify_after_ruling.tsv`（逐行读过上下文后写 basis；同职责可合并说明，无字段名套句）。

### 本轮 FIX_APPLIED（生产）

| loc | 实质 |
| --- | --- |
| `db._seed_guilt_storage_value` | `crime` 保原文；`severity` 仍为枚举 strip |
| `covert_progress.decide_secret_order_settlement` | `origin_context` 保原文；`strip` 只判是否嵌入 note |
| `cli_backend._split_audience_context` | 前缀匹配用 strip 副本；任务正文从 raw 切片 |
| `staged_commitment.normalize_commitment_stages` | 空白 `origin_context` 用 `.strip()` 判空后回退 criterion |
| `staged_commitment.list_due_grant_report_dossiers_for_scan` | 同上判空回退 |
| `due_review.decide_due_review_verdict` | 嵌入原诺用 `.strip()` 判空；取值保原文 |
| `session` SETTLING 恢复 | `decree_text` 保原文 |
| `decree` 批红待裁 | `rejection_reason` 保原文 |

合法例外（表内 KEEP）：机器键/枚举（`origin_ref`、`severity`、人口转移 `reason`、身份 title 闭集等）；局部判空副本；命令识别/JSON 围栏等非自由正文供料写口。

### 当前侧真实入口观察

完整原始输出：`probe_current_side.txt`（命令见该文件生成轨迹；七变量已置）。摘要：crime/note/split/decision/due 均保边空白；空白 origin 回退 criterion。

---

## 3. F17-R「旧生产逻辑装回」

**选用最简合法选项**：撤回「旧生产逻辑已装回」及相关结清申报；如实仅当前侧观察。

| 项 | 处置 |
| --- | --- |
| `mutation_temp_real_entry.json` | 重写：`verdict_old_logic_restored=false`；`observation_scope=current-side only` |
| 永久证明脚本 / old_* 替身 / 新旧并排 | **未新造** |
| 历史 `mutation_old_red.json` / `probe_new_green.json` | 字节保留 + 既有 `*.REVOKED_METHOD.txt` |
| `vitest_focus.txt` EOF 空行 | **已去掉**（新判允许；不再宣称无法修） |

不声称 F17 变异闸因「装回旧逻辑」而结清。

---

## 4. 聚焦测试（完整命令 + 原始输出）

### pytest

完整命令与原始输出：`pytest_focus.txt`

结果：**499 passed in 24.03s**

### vitest

完整命令与原始输出：`vitest_focus.txt`

结果：**Test Files 7 passed；Tests 190 passed**；已无 EOF 额外空行。

邻票 `test_commitment_progress_contexts_are_structured` NameError 仍交 #1873，不夹入。

---

## 撤销申报范围

1. 上轮 F16 手核表（模板 KEEP）证据地位
2. 上轮 F17「临时进程实际替换旧生产 strip 逻辑」结清申报
3. F3 越界恢复的措辞/模板锁断言（上表 WITHDRAWN）
4. 不撤销：561 许誉卿锚点；途中病故 / 后事。输入透传；F3-R 已结清类；先前合法 F16 保原文修复

---

## 未结（诚实）

- F17：仅当前侧观察，**未**用 `git show ee3b5da31:<path>` 做旧/新并排；不宣称变异红绿闸结清。
- F16：权威以 `f16_hand_verify_after_ruling.tsv` 为准；不声称枚举外永无新形状。
- 未跑全量；未 stash/amend/push/PR；未改真配置/治理。

自查二连 done（再读本轮全 diff：测试无重复模板分类；生产仅触及自由正文写/供料与判空回退；证据无套句 KEEP）。
