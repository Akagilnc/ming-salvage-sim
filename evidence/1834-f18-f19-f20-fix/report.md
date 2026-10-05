# #1834 修内司回执 · F18 / F19 / F20（末份判词 ecdbc39ab）

**工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1834-w5`  
**分支**：`ak-roles/1834-f18-f19-f20-ecdbc39ab`  
**基线 HEAD（开工）**：`ecdbc39abd7a4c93ef1383047832707c92ca75cd`  
**派单**：`…/01a1097a-bf6b-726c-bacb-5208aa0e1d03@fixer/fix-packet.md`  
**末份判词**：`…/attachments/03-1834-judge-ecdbc39ab.json` 末 payload（唯一未结）  
**共同测试前缀**：`MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false`

方向检索：Python 死码删除优先于兼容 shim（deadcode / PEP 387 仅适用于需保留公共 API 的库；本仓 #1812「没有历史包袱」+ 判词明确禁兼容层 → 直接删）。

未改治理法源：`AGENTS.md` / `CLAUDE.md` / `CONTEXT.md` / `docs/adr/**` 无 diff。

---

## 1. F18 — 已退役口令仍由代码裁断并代写人物台词

### 根因
`#1812` 待拍第5项已裁定「留下听着」「今日就到这里吧」不再由代码识别；场景模型照常演、转译声明在场与退下。生产仍保留 `AMBIGUOUS_CLOSE_COMMANDS` / `STAY_ATTEND_COMMANDS` 封闭集、`scene_chat` 专用早退，以及 `_ensure_close_night_confirm_cue` 代写「陛下是要退朝么？」大臣台词（P7 人物对话）。

### 枚举命令（类定义全文，未收窄为判词样本）
见 `enum_f18_cmd.sh` / `enum_f18_before.txt`：

```bash
rg -n --glob '!evidence/**' --glob '!docs/**' --glob '!archive/**' \
  'AMBIGUOUS_CLOSE_COMMANDS|STAY_ATTEND_COMMANDS|CMD_AMBIGUOUS_CLOSE|CMD_STAY_ATTEND|TAG_STAY_ATTEND|stay_attend_in_audience|_ensure_close_night_confirm_cue|陛下是要退朝么'
rg -n --glob '!evidence/**' --glob '!docs/**' --glob '!archive/**' \
  '留下听着|今日就到这里吧'
```

### 成员表（修前 → 处置）

| 成员 | 处置 | 理由 |
| --- | --- | --- |
| `ming_sim/constants.py` `AMBIGUOUS_CLOSE_COMMANDS` / `STAY_ATTEND_COMMANDS` | DELETED | 退役口令封闭集 |
| `ming_sim/audience_night.py` `TAG_STAY_ATTEND` / `CMD_AMBIGUOUS_CLOSE` / `CMD_STAY_ATTEND` | DELETED | 仅服务退役裁断 |
| `ming_sim/audience_night.py` `stay_attend_in_audience` | DELETED | 口令写缝；零转译消费者 |
| `ming_sim/audience_night.py` `recognize_audience_command` 中 stay/ambiguous 分支 | DELETED | 仅留 `COURT_BREAK` |
| `ming_sim/session.py` `_ensure_close_night_confirm_cue` + 「陛下是要退朝么？」 | DELETED | 代写人物台词 |
| `ming_sim/session.py` `scene_chat` ambiguous/stay 早退 | DELETED | 复用场景／转译接缝 |
| `ming_sim/cli/terminal.py` stay 口令分支 | DELETED | 同形退役裁断 |
| `tests/test_audience_translate_1837.py::test_scene_stay_attend_uses_actual_protagonist_not_virtual_speaker` | DELETED | 专用测试，随机制删 |

**保留**：`COURT_BREAK_COMMANDS` / `CMD_CLOSE_NIGHT`（现役退朝）；`MINISTER_DISMISS_COMMANDS`（CLI 短句退下）；场景调用 + `audience_translate` 统一转译。

### 复扫
`enum_f18_after.txt`：CMD1 符号命中为空（EXIT=1）；CMD2 仅剩删除说明注释三处（非裁断代码）。

---

## 2. F19 — 被统一转译取代的密令抽取闭包及专用测试

### 根因
现役 `declaration_dispatch` 直接承接 `commission.secret_order`；`cli_backend._extract_secret_order` 及其拼装／词表／案卷确认闭包仅被专用测试引用，仍被维护并继续改传输细节——退役机制的复杂度缺陷。

### 枚举命令
见 `enum_f19_cmd.sh` / `enum_f19_before.txt`：

```bash
rg -n --glob '!evidence/**' --glob '!docs/**' --glob '!archive/**' --glob '!TODOS.md' \
  '_extract_secret_order|assemble_secret_order_content|_content_reflects_emperor_intent|_merge_secret_content|_split_audience_context|_choose_assignee|_extract_imperative_assignee|_secret_context_|_secret_confirmation_material|_secret_metadata_from_command|_normalize_dossier_link_proposals|confirm_dossier_links|_secret_prefix_needs_recent_context|_SECRET_CONFIRM_ATOM|_CLAUSE_SPLIT|_is_institution_like_name|_ASSIGNEE_'
rg -n --glob 'tests/**' \
  '_extract_secret_order|assemble_secret_order_content|test_secret_exclusion_extracts|test_extract_secret_order|test_secret_content_assembly|test_secret_extract_traces|_so_json'
rg -n --glob '!evidence/**' --glob '!docs/**' --glob '!archive/**' \
  'secret_order_can_land|secret_order_landing_gaps|compose_secret_order_landing_recovery'
```

### 成员表

| 成员 | 处置 | 理由 |
| --- | --- | --- |
| `_CLAUSE_SPLIT` … `_extract_secret_order` 整段闭包（含 assemble／assignee／split_audience／secret_context 词表／confirm_dossier_links／`_secret_prefix_needs_recent_context`） | DELETED | 专属抽取闭包；生产无调用 |
| `cli_backend` 顶层 `_ASSIGNEE_HINT_INSTITUTION_TOKENS` 等仅服务该闭包的 import | DELETED | 随闭包 |
| 注释仍指 `_extract_secret_order` 为现役路径 | FIXED | 改为声明已删／现役转译承接 |
| `tests/…::test_secret_exclusion_extracts_people_and_offices` | DELETED | 专用测试 |
| `tests/…::test_extract_secret_order_preserves_long_title_without_formal_cap` | DELETED | 专用测试 |
| `tests/…::test_secret_content_assembly_is_emperor_plus_extractor_only` | DELETED | 专用测试 |
| `tests/…::test_secret_extract_traces_exactly_once` | DELETED | 专用测试 |
| `_so_json` 测试夹具 | DELETED | 仅服务上述测试 |

**保留（现役仍引用／共享落库闸）**：

| 保留项 | 理由 |
| --- | --- |
| `secret_order_can_land` / `secret_order_landing_gaps` | `declaration_dispatch` 现役闸 |
| `compose_secret_order_landing_recovery` | 落库恢复共享能力；web/`ChatTurnResult.secret_order_landing_recovery` 字段面仍在 |
| `test_typed_secret_exclusions_canonicalize_roster_alias_and_office` | 测 `db.canonical_secret_order_exclusions`，非抽取闭包 |

### 复扫
`enum_f19_after.txt`：生产闭包符号仅剩「已删」注释一行；专用测试 CMD2 空；共享闸 CMD3 仍在。

### 测试删除必要成本
删 4 个只绑 `_extract_secret_order` / `assemble_secret_order_content` 的专用案 + `_so_json`；未新造平行证明测试。保留 typed exclusions 真共享契约案。净减测试复杂度，符合 #1812「只为旧代码存在的测试已删」。

---

## 3. F20 — 现行证据导航仍指向已撤销的处置真源

### 根因
`F17_F3R_REVOCATION.txt`「Current F16 evidence」仍指向 `f16_hand_verify_after_ruling.tsv` + METHOD；同目录 `f16_disposition_after_counterexample.METHOD.txt` 已将其标为 `REVOKED_PACKAGING_KEEP`。现行导航与现行处置真源矛盾。

### 枚举命令
见 `enum_f20_cmd.sh` / `enum_f20_before.txt`：

```bash
rg -n 'Current F16 evidence|Disposition authority|f16_hand_verify_after_ruling|REVOKED_PACKAGING_KEEP|f16_disposition_after_counterexample' \
  evidence/1834-f16-f3-f3r-f17-fix/
rg -n 'F17_F3R_REVOCATION|f16_hand_verify_after_ruling|f16_disposition_after_counterexample' \
  evidence/1834-f16-f3-f3r-f17-fix/report.md
```

### 成员表

| 成员 | 处置 | 理由 |
| --- | --- | --- |
| `F17_F3R_REVOCATION.txt` Current F16 段 | FIXED | 改为 `f16_disposition_after_counterexample.{tsv,METHOD.txt}` + `f16_disposition_member_locs.tsv`；明确 hand_verify／rerun 为冻结撤销记录 |
| `f16_hand_verify_after_ruling.tsv` / `.METHOD.txt` / `*.REVOKED_PACKAGING_KEEP.txt` | KEPT | 冻结失败记录，不重写 |
| `enum_f16_*` REVOKED_STUB 文件 | KEPT | 冻结失败记录 |
| `report.md`（旧回执） | KEPT | 已引用 `f16_disposition_after_counterexample.tsv` 为权威组表；F17-R 行引用本导航文件，修导航后链闭环 |

未重做分类机制或变异脚本。

### 复扫
`enum_f20_after.txt`：Current F16 已指向 `f16_disposition_after_counterexample.*`；hand_verify 仅出现在 REVOKED／冻结说明中。

---

## 4. 聚焦测试

```bash
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
../Ming_LLM/.venv/bin/python -m pytest -q \
  tests/test_cli_backend.py \
  tests/test_audience_translate_1837.py \
  tests/test_scene_llm_1836.py \
  tests/test_cli_transport_1465.py \
  tests/test_material_directory_1830.py \
  tests/test_world_materials_1834.py \
  -p no:cacheprovider --basetemp=/tmp/1834-f18-f19-f20-pytest --tb=short
```

完整输出：`pytest_focus.txt` — **143 passed, 1 warning in 6.64s**（`/usr/bin/time -p`：real 7.18 / user 3.99 / sys 1.36）。

未跑全量。

---

## 5. 差异自检

- `git diff --check`：见 `diff_check.txt`（无输出＝干净）
- `git diff --stat`：见 `diff_stat.txt`（约 −879 / +25，八文件）
- 禁项自检：无 push／PR／amend／stash／kill；未新增模型／提示器／兼容层／分类层／证明性测试；冻结历史未改写正文

---

## 6. 阻断

无真实阻断。
