# #1897 修内司回执（J1 / J2 / F3）— F3 HEAD 纠正

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1897-w5`
- 分支：`ak-roles/issue-1897-j1-j2-f3-fixer-20261005-101325`
- 相对基线：`10e64fbef2857a4603c51394d16cea791b4f44c2`
- 施工前 tip：`c905115fdb0a84f26d1c9b4b26701e621ba89dc8`
- 判词：末份 `~/.ak-roles/books/Ming_LLM/unbound/runs/01a1099e-2506-7580-a2b3-0f15a8209f3b@fixer/attachments/03-1897-judge-5d0b04dec.json`（先前三份仅参考；未结只取 J1/J2/F3）
- 派单：同 run `fix-packet.md`
- 票面：`gh issue view 1897` / `1812`；验收真源=#1812「重构验收」
- 本回纠正（HEAD 核对）：上轮回执错误豁免 rendered 人名、content seed summary 子串、pay_order summary 过滤、criterion_text「闭集」；缺可复放全断言枚举；month_chain 续推 spy / read_material 无结果却称递送；J1 旧逻辑探针冒称变异证明
- 本回执不自指待生成 SHA；提交后以 `git rev-parse HEAD` 为准

## 环境前缀

```bash
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1
```

---

## J1：故事账猜源兼容

### 类定义（判词）

boundary：故事账持久来源接缝  
direction：清退当前夜／最后轮猜源兼容及其附属物，沿已有持久来源承接；不新增补账、等待或恢复协议。

### 枚举命令（可复跑）

```bash
python3 - <<'PY'
import ast, re
from pathlib import Path
GUESS = [
    r'get_open_night\b', r'get_last_active_chat_turn\b', r'_current_open_night_id\b',
    r'当前开夜', r'最后一轮', r'未带源夜', r'缺源夜', r'猜.*源',
]
LEDGER = [
    r'append_ledger_entry\b', r'ensure_inactive_office_summon\b', r'path_nature',
    r'故事账', r'传召账', r'ledger_entr', r'write_path_nature',
]
for path in sorted(Path('ming_sim').rglob('*.py')):
    src = path.read_text(encoding='utf-8')
    try: tree = ast.parse(src)
    except SyntaxError: continue
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
        body = (ast.get_source_segment(src, node) or '') + '\n' + (ast.get_docstring(node) or '')
        lh = [p for p in LEDGER if re.search(p, body)]
        gh = [p for p in GUESS if re.search(p, body)]
        if lh and gh:
            print(f'{path}:{node.name}:{node.lineno} ledger={lh} guess={gh}')
PY
rg -n 'get_open_night|get_last_active_chat_turn|_current_open_night_id' ming_sim -g'*.py'
```

### 成员与处置

| # | 成员 | 处置 |
|---:|---|---|
| 1 | `action_materialize._write_path_nature_ledger` | 已清猜源；缺源夜直接 return；无 `turn` 退休兼容 |
| 2 | `action_materialize._persist_appointment_summon` | 已清；只传 `pinned_night` |

### 变异取证（诚实口径）

授权套件中**无**专打 path-nature 猜源的真实入口红绿案。上轮进程内装回旧 `get_open_night` 探针仅说明当前缺源夜不写账，**未提供**「旧逻辑 RED → 新逻辑 GREEN」的可复放变异证据。  
**本回执不把该探针记为变异证明**；J1 以生产路径无猜源调用 + 枚举复扫记账，不以 GREEN 标签冒充变异闭合。

---

## J2：退休按承办人最新 active 猜目标

### 类定义（判词）

boundary：密令创建／精确更新接缝  
direction：清退按承办人最新 active 猜目标的退休入口、说明和专属测试；不补新调用。

### 枚举命令（可复跑）

```bash
rg -n --type py \
  'upsert_secret_order\b|最新 active|最新active|create-or-update|该大臣最新|承办人最新|status=.active. ORDER BY id DESC' \
  ming_sim tests docs content -g '!**/__pycache__/**' -g '!**/CMR_*' -g '!**/TEST_AUDIT*' -g '!**/docs/raw/**'
```

### 成员

| # | 成员 | 处置 |
|---:|---|---|
| 1 | `db.upsert_secret_order` | 已删 |
| 2 | `update_secret_order_by_id` 对 upsert 的对比说明 | 已删 |
| 3 | `create_secret_order`「upsert 回落」措辞 | 已删 |
| 4 | `tests/test_secret_order_update.py` upsert 专属两案 | 已删 |

复扫：`def upsert_secret_order(` 无。

---

## F3：授权触及测试清退

### 类定义（判词）

boundary：授权改动对应测试体系  
direction：按行为契约清退散文机械依赖、换形保真证明及无价值断言；复用必要真实入口结构化测试，保留闸类负向；不得恢复锁文或另建平行证明体系。

### 授权触及测试清单（43）

```bash
git diff --name-only 10e64fbef HEAD -- tests | grep '^tests/test_.*\.py$' | sort
```

1. `tests/test_audience_translate_1837.py`
2. `tests/test_audience_translate_1837_reopen.py`
3. `tests/test_breach_plea_623.py`
4. `tests/test_character_knowledge_489.py`
5. `tests/test_declaration_dispatch_1835.py`
6. `tests/test_decree_dossiers_571.py`
7. `tests/test_deformation_dual_rail_622.py`
8. `tests/test_dossier_reported_progress_619.py`
9. `tests/test_due_review_621.py`
10. `tests/test_effect_origin_558.py`
11. `tests/test_event_trigger_gate.py`
12. `tests/test_execution_pressure_654.py`
13. `tests/test_faction_denunciation_627.py`
14. `tests/test_family_tail_restore_570.py`
15. `tests/test_fiscal_levy_effect.py`
16. `tests/test_gazette_author_1862.py`
17. `tests/test_grant_reconciliation_567.py`
18. `tests/test_mechanical_tail_1845.py`
19. `tests/test_memorial_inbox_1726.py`
20. `tests/test_month_chain_1843.py`
21. `tests/test_month_chain_1847.py`
22. `tests/test_new_issues_section_rejections.py`
23. `tests/test_on_scene_immediate_write_1839.py`
24. `tests/test_pay_order_override_653.py`
25. `tests/test_person_delta_adapter.py`
26. `tests/test_pihong_dossier_1490.py`
27. `tests/test_qa_1281_issue_audience_case_facts.py`
28. `tests/test_region_cannon_delta.py`
29. `tests/test_relation_capture_633.py`
30. `tests/test_rescript_choices_563.py`
31. `tests/test_rescript_draft_656.py`
32. `tests/test_rescript_heal_isolation_1801.py`
33. `tests/test_rescript_option_field_heal_1746.py`
34. `tests/test_secret_order_declaration_landing_1897.py`
35. `tests/test_secret_order_isolation_883.py`
36. `tests/test_secret_order_monthly_progress_566.py`
37. `tests/test_secret_order_payoff_1504.py`
38. `tests/test_secret_order_section_rejections.py`
39. `tests/test_secret_order_update.py`
40. `tests/test_staged_assignment_identity_1890.py`
41. `tests/test_style_temperament_641.py`
42. `tests/test_urge_lever_624.py`
43. `tests/test_web_chat_serialization_393.py`

### 可复放：全断言 + pytest.raises(match=) 枚举命令

不按字段词表收窄成员；对 43 文件 AST 走全部 `assert` 与 `raises(..., match=)`：

```bash
python3 - <<'PY'
import ast
from pathlib import Path
files = [Path(x) for x in Path('/tmp/1897-f3-corr7/authorized-43.txt').read_text().splitlines()]
# 或: git diff --name-only 10e64fbef HEAD -- tests | grep '^tests/test_.*\.py$' | sort > /tmp/1897-f3-corr7/authorized-43.txt
n_assert = n_raises = 0
for path in files:
    src = path.read_text(encoding='utf-8'); tree = ast.parse(src)
    fmap = {}
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sn in ast.walk(n):
                if hasattr(sn, 'lineno'): fmap[sn.lineno] = n.name
    for n in ast.walk(tree):
        if isinstance(n, ast.Assert):
            n_assert += 1
            seg = (ast.get_source_segment(src, n) or '').replace('\n', ' ')[:180]
            print(f'ASSERT\t{path}:{n.lineno}\t{fmap.get(n.lineno,"?")}\t{seg}')
        elif isinstance(n, ast.Call):
            fn = ast.get_source_segment(src, n.func) or ''
            if 'raises' in fn:
                for kw in n.keywords or []:
                    if kw.arg == 'match':
                        n_raises += 1
                        seg = (ast.get_source_segment(src, n) or '').replace('\n', ' ')[:180]
                        print(f'RAISES_MATCH\t{path}:{n.lineno}\t{fmap.get(n.lineno,"?")}\t{seg}')
print(f'# TOTAL_ASSERT={n_assert} TOTAL_RAISES_MATCH={n_raises}')
PY
```

本回实测落盘：`/tmp/1897-f3-corr7/full-assert-enum.txt`  
**`TOTAL_ASSERT=5291` `TOTAL_RAISES_MATCH=15`**（清退后；清退前同命令约 5332 assert）。

### 所谓「闭集」生产 / schema 真相（不可自称）

| 字段 / 说法 | 真相 | 本回合口径 |
|---|---|---|
| `criterion_text` | `TEXT NOT NULL DEFAULT ''`（`db.py` 列定义）；无 CHECK IN | **非闭集**。松手类中文「断供/挪用/撤人」只是 `BREACH_KIND_LABELS` 写入自由列的标签。断言改认 `origin_context` 内结构化 `breach_kind` |
| `status_reason` | `TEXT` 自由列 | **非闭集**；空白闸可留；非空字面 / 跨面等值不可豁免 |
| `reason_code` | `PERSON_REASON_CODES` 机器码 | **闭集**可锁 |
| `form`（背书） | `CHECK(form IN ('会签','当面站台','御笔手敕'))` | **闭集**可锁 |
| `close_issue` / heal `reason` 如 `resolved` / `commitment_due` / `option_missing_fields_heal_exhausted` | 生产枚举／哨兵码 | **机器码**可锁 |
| content seed `summary`/`title`/… | `content/events.json` 自由文 | 夹具固定 **≠** 字段变闭集；子串锁文仍违宪 |
| `turn_region_summary` 拼接 `reason` | 返回自由摘要串 | 不可用「民变事实」等子串作契约 |
| HITL `label`「强颁/收回/留中」 | `decree.py` 展示文；决策码在 `dossier_decision` | 认 `dossier_decision` 码，不锁展示 label |

夹具固定、测试未真调 LLM，**均不**构成自由字段豁免。

### 本轮发现成员完整表与逐案独立契约依据

#### A. 须清 / 已清（自由文本机械依赖或无价值证明）

| # | 成员 | 形状 | 处置 | 保留的真正独立契约（若有） |
|---:|---|---|---|---|
| 1 | `test_style_temperament_641::test_context_includes_viewer_ledger_without_prose_lock` | `person.name/other.name in rendered` | **整案删**（独立锁文证明；不改成键/计数空壳） | — |
| 2 | 同文件 `test_character_context_with_db_reads_own_style_and_viewer_ledger` 的 `other.name in rendered` | NAME_IN_RENDERED | **删** | ledger `source`/`target` 身份；style before≠after |
| 3 | 同文件成功路径 `content.characters.style == after` / `old_style`/`new_style` 等值 | CROSS 保真 | **删** | 性情落库：`动作`/person_logs；拒收/回滚 before 不变闸保留 |
| 4 | `test_event_trigger_gate::test_wuyin_lubian_content_treats_lu_death_as_soft_battle_outcome` | content seed summary/title/… 子串 | **整案删** | — |
| 5 | 同文件 economy `out[...]["reason"] == reason` | EQ 自由 reason | **删** | 外层 rollback 后 ledger count==0 |
| 6 | `test_breach_plea_623` 四处 `criterion_text == "断供/挪用/撤人"` | 伪闭集锁文 | **改** `decode_plea_meta(...).breach_kind == BREACH_KIND_*` | 写 plea、dossier/issue status、皇威/代价不变等原结构断言 |
| 7 | `test_pay_order_override_653::...claim_audit...` `"民变事实" in summary` 与 claim reason 子串 | LIT_IN 摘要 | **删**；改查 summary SQL 窗口 `field` 集合 | `settle_*欠_*` 不进 limit 窗口；`unrest` 可见 |
| 8 | `test_month_chain_1847` `len(continuation_calls[0])==1` | 内部 spy 替代 label 锁文 | **清无价值半截**；留 `len(continuation_calls)==1` 幂等 | turn_phase / world_questions 清空 / world_continued / gazette |
| 9 | 同文件 `"预推不可见:…" in message` / `question_context in message` | LIT_IN message | **删** | payload `this_decree.status`；经济 ledger 计数；材料根释放 |
| 10 | 同文件 HITL `labels >= {"强颁","收回","留中"}` | 展示 label | **改** `dossier_decision` 码集 | rescript_pending；affected_parties |
| 11 | 同文件 `read_material(...)` 无结果断言却称递送 | 无价值 | **删调用**；目录键 `rel in list_materials` 保留 | 目录键递送 |
| 12 | `test_grant_reconciliation_567` `"赈银押解到达" in note` | LIT_IN execution_note | **删** | status=closed；arrived_amount；无二次扣库 |
| 13 | `test_mechanical_tail_1845` `text == "史评"` | mock 透传保真 | **删** | ending_status；timeline 结构键；payload 无重复 gazette |
| 14 | `test_new_issues_section_rejections` resolve/stop 表达式字面等值 | EQ 自由表达式 | **改** `resolve_condition == stop_condition`（回落契约） | bar/status 推进 |
| 15 | `test_rescript_option_field_heal_1746` `text == '{"ok":true}'` | mock 透传 | **删** | prior_messages → Message 列表角色序 |
| 16 | `test_person_delta_adapter` displaced 元组锁 `status_reason=="被顶替"` | 自由 reason | **删该字段比较** | office / office_type / **reason_code**（真闭集） |
| 17 | `test_secret_order_isolation_883` 多处 `_shared_source_body == fixture` | 正文保真 | **删等值**；`is None` 扣留闸保留 | knowledge_status；source_id 可见性 |
| 18 | 同文件 `test_883_shared_write_seam_keeps_public_assignee_audience` | 仅正文等值承重 | **整案删** | — |

#### B. 保留例外（逐案依据；非「局部探针整类完成」）

| 类型 | 成员样例 | 独立契约依据 |
|---|---|---|
| SSE 线协议 | `test_pihong_dossier_1490` 多处 `'event: done'/'event: error' in r.text` | HTTP SSE 控序；非 LLM 散文 |
| 空白闸 | `summary==""` / `status_reason==""` / blank style 拒收 before 不变 | 闸类负向 |
| 机器码闭集 | `reason_code`；`form` CHECK；`breach_kind`；`dossier_decision`；`resolved`/`commitment_due`/heal exhausted | schema / 生产枚举 |
| 身份键 | origin_ref / decree_ref / dossier_id / order_id / source/target | 结构化身份 |
| Event/Future 握手 | `test_secret_order_declaration_landing_1897` | 判词显式保留 |
| 材料目录键 | `rel in list_materials` | 供料递送；**不**把无断言的 `read_material` 当递送证明 |
| 隔离扣留 | `_shared_source_body(...) is None` + knowledge_status | 缺席/状态，非正文等值 |
| `pytest.raises(..., match=注入哨兵)` | 15 处 | 合法负向闸（注入错误串） |
| 性情/边 before 不变 | style == before_* 于拒收/回滚/边不改 style | 负向「未变」，非成功路径锁文 |

### 复扫声明（禁止局部探针冒充整类完成）

- 已对 **43 授权文件全部 5291 assert + 15 raises(match=)** 做 AST 枚举（命令见上；全文 `/tmp/1897-f3-corr7/full-assert-enum.txt`）。
- 自由字段机械依赖复扫（Subscript 键 + Compare + raises match）：清退后残留 **LIT_IN 33（皆 SSE）+ EMPTY_GATE 7 + RAISES_MATCH 15**；**无** EQ_FREE / NAME_IN_RENDERED / criterion_text 字面 / rendered 人名。
- **不声称**「仓内再无任何自由文字」或「F3 全仓散文锁已结清」——仅记账本授权 43 文件本轮语义终裁；出界文件未扩扫。
- **不**用键存在/长度/类型/非空/计数承接已删正文锁；**不**因「测试未跑真 LLM / 夹具固定」豁免自由列。

---

## 测试（聚焦，非全量；七变量前缀）

```bash
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 \
../Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=line \
  tests/test_style_temperament_641.py \
  tests/test_event_trigger_gate.py \
  tests/test_breach_plea_623.py \
  tests/test_pay_order_override_653.py \
  tests/test_month_chain_1847.py \
  tests/test_grant_reconciliation_567.py \
  tests/test_mechanical_tail_1845.py \
  tests/test_new_issues_section_rejections.py \
  tests/test_rescript_option_field_heal_1746.py \
  tests/test_person_delta_adapter.py \
  tests/test_secret_order_isolation_883.py \
  tests/test_secret_order_update.py \
  tests/test_secret_order_declaration_landing_1897.py \
  --basetemp=/tmp/1897-f3-corr7/pytest-focus
```

**实测**：`639 passed, 1 skipped in 11.99s`（`real 12.51`）。  
跳过：`test_person_delta_adapter` 缺 `data/probe.db`（预存 #5 followup），非本轮引入。

未跑全量；未调真实模型。

### 测试最小必要成本（一行）

聚焦 13 文件≈640 例 / ~12s；契约=清自由字段机械依赖与无价值 spy/空壳，保留闸/机器码/SSE/Event·Future/目录键。

---

## 自查二连

1. **同类型**：F3 按 schema 真相撤伪闭集豁免；删独立锁文/保真案而非换形；全 43 可复放枚举进回执；J1 变异不作假。
2. **引入面**：未加恢复/补账/适配层；未 stash/reset/amend/push/PR；未动 Soul/宪法/宿主；自建物仅本仓 `artifacts/` 与 `/tmp/1897-f3-corr7/`。

## 账目

- 本轮相对 `c905115fd`：11 test files，`+45 / −142`（以 `git diff --stat` 为准）+ 本回执
- 未 push / 未 PR / 未 amend
- 提交 SHA：见提交后 stdout / `git rev-parse HEAD`
