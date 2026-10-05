# #1897 修内司回执（J1 / J2 / F3）— 纠正复扫

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1897-w5`
- 分支：`ak-roles/issue-1897-j1-j2-f3-fixer-20261005-101325`
- 相对基线：`10e64fbef2857a4603c51394d16cea791b4f44c2`
- 施工前 tip：`725d3aaa4932981435c94dfc85093d687eeffeed`
- 判词：末份 `~/.ak-roles/books/Ming_LLM/unbound/runs/01a1099e-2506-7580-a2b3-0f15a8209f3b@fixer/attachments/03-1897-judge-5d0b04dec.json`（先前三份仅参考；未结只取 J1/J2/F3）
- 派单：同 run `fix-packet.md`
- 票面：`gh issue view 1897` / `1812`；验收真源=#1812「重构验收」
- 本回纠正上轮：F3 换形空壳（键存在/长度/类型/非空/计数）、错误豁免 memory↔DB `status_reason`、J1/J2 枚举过窄、43 名单只落临时路径、`turn` 退休兼容形参
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

### 枚举命令（可复跑；不限已知函数名）

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

### 完整成员表与处置

| # | 成员 | 根因 | 处置 |
|---:|---|---|---|
| 1 | `action_materialize._write_path_nature_ledger` | 缺源夜时曾 `get_open_night`+`get_last_active_chat_turn` | **已清猜源分支**；缺源夜直接 return；删无用 `turn` 形参与调用方传参；无退休兼容注释 |
| 2 | `action_materialize._persist_appointment_summon` | 缺源夜时曾 `_current_open_night_id()` | **已清**；只传 `pinned_night` |

### 枚举命中但非本类（保留依据）

| 符号 | 为何不是 J1 |
|---|---|
| `audience_night.assert_night_accepts_player_input` / `open_night` / `dismiss_*` / `stay_*` | 当前夜操作/开夜本身，不是「缺持久源时猜夜写故事账」 |
| `db.undo_chat_turn`「最后一轮」 | 撤回全局最后一轮召对的既有规则文案，非故事账猜源旁路 |
| `session.consume_audience_admission`+`get_open_night` | 入殿读当前夜，非缺源猜写账 |
| `db.update_*_candidate` 缺省 `_current_open_night_id` | pending 归属缝，非 `append_ledger_entry` 猜源；未扩改（避免发明新恢复协议） |
| materials/session/web 的 `get_open_night` | 供料与 UI 读当前夜 |

说明：枚举仍命中 `_write_path_nature_ledger` / `_persist_appointment_summon`，因 docstring 含「缺源夜不写／不猜」；**代码路径已无** `get_open_night` / `get_last_active_chat_turn` / `_current_open_night_id`。

### 变异取证

授权套件中无专打 path-nature 猜源的真实入口案；对生产函数做进程内旧逻辑探针（七变量前缀）：

- CURRENT 缺 `night_id`：ledger delta=0
- 装回旧 `get_open_night` 猜源：delta=1
- 恢复当前：delta=0
- 结果：`J1_MUTATION GREEN`（输出见本轮 `/tmp/1897-fixer-rescan/j1-mutation.txt`，回执已摘录，不依赖该临时文件）

---

## J2：退休按承办人最新 active 猜目标

### 类定义（判词）

boundary：密令创建／精确更新接缝
direction：清退按承办人最新 active 猜目标的退休入口、说明和专属测试；不补新调用。

### 枚举命令（可复跑；不限 upsert 符号）

```bash
rg -n --type py \
  'upsert_secret_order\b|最新 active|最新active|create-or-update|该大臣最新|承办人最新|status=.active. ORDER BY id DESC' \
  ming_sim tests docs content -g '!**/__pycache__/**' -g '!**/CMR_*' -g '!**/TEST_AUDIT*' -g '!**/docs/raw/**'

python3 - <<'PY'
import ast, re
from pathlib import Path
for path in sorted(Path('ming_sim').rglob('*.py')):
    src = path.read_text(encoding='utf-8')
    try: tree = ast.parse(src)
    except SyntaxError: continue
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
        body = ast.get_source_segment(src, node) or ''
        if re.search(r"status\s*=\s*['\"]active['\"].*ORDER BY id DESC|ORDER BY id DESC.*active", body, re.S):
            if 'minister' in body or 'secret_order' in body.lower():
                print(f'{path}:{node.name}:{node.lineno}')
PY
```

### 完整成员表

| # | 成员 | 处置 |
|---:|---|---|
| 1 | `db.upsert_secret_order` 定义+说明 | **已删**（上轮） |
| 2 | `update_secret_order_by_id` 文档对 upsert 的对比说明 | **已删**（上轮） |
| 3 | `create_secret_order` 注释「upsert 回落 create」 | **本轮删**该退休措辞 |
| 4 | `tests/test_secret_order_update.py` upsert 两案+模块说明 | **已删/改**为精确 id 更新说明（上轮） |
| — | `upsert_secret_order_brief` | **非本类**（不同符号，现役 brief 写口） |
| — | `get_active_secret_orders_for_minister` | **非本类**（列举 active，不猜更新目标） |
| — | `create_secret_order` 内 `chat_turns … ORDER BY id DESC` | **非本类**（由 provenance message_ids 取源轮，非按大臣最新密令） |
| — | `docs/CMR_REPORT_y2_probe.md` 等历史记载 | **保留过程史** |

### 复扫

`def upsert_secret_order(`：无。生产/测试对「最新 active 猜条」仅剩精确更新说明中的否定表述。

---

## F3：授权触及测试清退

### 类定义（判词）

boundary：授权改动对应测试体系
direction：按行为契约清退散文机械依赖、换形保真证明及无价值断言；复用必要真实入口结构化测试，保留闸类负向；不得恢复锁文或另建平行证明体系。

### 授权触及测试清单（43，完整名单在回执内）

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

### 断言枚举方法（不限等值/词表）

对上述 43 文件 AST 枚举全部 `assert`（本轮约 5350 条），再按独立外部行为契约逐案语义终裁；预分类仅辅助，不代替终裁。禁止把承重锁文改成键存在/长度/类型/非空/计数后宣称清净。

### 本轮须清成员（含上轮换形空壳）与处置

| # | 成员 | 形状 | 处置 | 保留的真正契约（若有） |
|---:|---|---|---|---|
| 1 | `test_style_temperament` summary len/strip 与后续 `"summary" in dto` | LEN_STRIP→KEY 换形 | **删空壳键存在** | source/target 身份；rendered 含人名 |
| 2 | `test_relation_capture` 全文链 context 等值 | CROSS 保真 | **整案已删**（上轮） | — |
| 3 | 同文件 whitespace 保真改写后的 happy-path+event_kind | 无价值新断言 | **只留空白拒收负向闸** | `ValueError` + 零行 |
| 4 | `test_pihong` preferred_hitl `label==`→`'label' in` | CROSS→KEY 换形 | **删 label 断言** | action/draft_capability/decision_key/dossier_* |
| 5 | `test_pihong` `_body_canonical==` / `'新拟甲' in labels` / `"新甲" in labels` | 正文/label 锁 | **删** | revision_round/status/action/capability；options 非空 |
| 6 | `test_person_delta` `status_reason != old` 及 memory↔DB `status_reason` 等值 | 自由 reason / 伪「三面」豁免 | **删跨面散文等值** | `reason_code` 闭集同步/清空；status；status_changed_turn；空白闸 `status_reason==""`（被顶替清除） |
| 7 | `test_person_delta` `payload_summary` 字面 | LIT | **删** | action/derived_from/source/reason_code |
| 8 | `test_person_delta` 拒收还原元组含 status_reason | CROSS | **DB/内存比较去掉 status_reason** | status/office/office_type/reason_code/transit* |
| 9 | `test_month_chain_1847` world_segment/forecast/`label in`/segments 非空/`sim_note in` | LIT/KEY/COUNT 换形 | **删** | continuation 调用次数；turn_phase；world_continued；decree_ref；目录键+read |
| 10 | `test_month_chain_1843` `run_world_segment_text=="静"` | LIT | **删等值**（上轮） | 材料目录/INDEX 侧效 |
| 11 | `test_gazette_author` 事实/经历子串与 world_segment 等值→键存在 | LIT→KEY | **删 world_segment 键空壳**；目录键保留 | author_files 目录键；origin_ref/exclude；reign_period_label；rescript event_id |
| 12 | `test_fiscal_levy` presented_context/emperor_note→键存在 | LIT→KEY | **删空壳** | `held is True`；petition id 集合 |
| 13 | `test_decree_dossiers` promulgation_reason/execution_note/decree_text 键；revised_text in prompt；restore reason 等值 | LIT/KEY | **删** | layer/status/action_type/amount/account/mode/国库 delta；decision 结构化字段 |
| 14 | `test_mechanical_tail` summary 跨等值→`"summary" in` | CROSS→KEY | **删空壳** | summary_pending；空白闸 `summary==""`；ending is not None |
| 15 | `test_secret_order_isolation` body==old_public | CROSS | **删等值**（上轮） | knowledge_status withheld/释放 |
| 16 | `test_urge_lever` origin_context/criterion 等值→键存在 | CROSS→KEY | **删空壳**；改 assert 投影无 payload_json | truth/grace_fake；payload_json 不泄漏 |
| 17 | `test_event_trigger` status_reason!="获罪削籍" | 自由 reason | **删**（上轮） | `reason_code==""` |
| 18 | `test_rescript_choices` labels 列表等值→options 计数 | LABEL→COUNT | **删计数** | 空 label 负向；非空分支 `len(decisions)==1` |
| 19 | `test_rescript_draft` isinstance(reason,str)→`'reason' in pack` | TYPE→KEY | **保留 error-pack schema 键**（非正文锁） | 降级文件存在；`'reason' in pack` |
| 20 | J2 upsert 专属两案 | 退休机制专属 | **随 J2 删** | 精确 id 更新四案 |

### 保留例外（非缺陷；逐案依据）

| 类型 | 依据 |
|---|---|
| SSE `event: done/error` | 线协议控序 |
| 空位闸 `label==""` / `summary==""` / blank context `ValueError` / 被顶替清除 `status_reason==""` | 闸类负向 |
| `reason_code` / `mode` / `status` / `deliberation_state` / `event_kind` / `decision_key` 等闭集 | 结构化机器码 |
| origin_ref / decree_ref / dossier_id / order_id | 身份键 |
| Event/Future 握手（declaration landing） | 判词显式保留 |
| 材料目录键 `rel in list_materials` / `fact_rel in author_files` | 供料递送结构化契约，不锁正文 |
| breach `criterion_text`∈{断供,挪用,撤人} | 闭集准则码，非自由生成文 |
| content seed 事件 summary 子串（event_trigger） | 内容域夹具，非 LLM 产出锁 |
| pay_order summary 过滤「民变事实」vs settle claim reasons | 区域摘要过滤契约的夹具观察点 |
| 性情拒收 before==after style | 结构化字段未变 |
| **不**豁免 memory↔DB `status_reason` 跨散文等值 | 字段名/「三面一致」不能豁免 |

### 复扫声明

- 已复扫上轮换形空壳点名样本：**不再**以键存在/长度/类型/非空/计数承接正文锁。
- 未对全部 5350 条断言宣称「仓内再无任何自由文字」；上表与保留表为本次语义终裁账本。
- 未新增平行测试文件；未恢复锁文。

---

## 测试（聚焦，非全量）

```bash
../Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=line \
  tests/test_secret_order_update.py \
  tests/test_style_temperament_641.py \
  tests/test_relation_capture_633.py \
  tests/test_pihong_dossier_1490.py \
  tests/test_person_delta_adapter.py \
  tests/test_month_chain_1847.py \
  tests/test_month_chain_1843.py \
  tests/test_gazette_author_1862.py \
  tests/test_fiscal_levy_effect.py \
  tests/test_decree_dossiers_571.py \
  tests/test_mechanical_tail_1845.py \
  tests/test_secret_order_isolation_883.py \
  tests/test_urge_lever_624.py \
  tests/test_event_trigger_gate.py \
  tests/test_rescript_choices_563.py \
  tests/test_rescript_draft_656.py \
  tests/test_secret_order_declaration_landing_1897.py \
  tests/test_staged_assignment_identity_1890.py \
  tests/test_audience_translate_1837_reopen.py \
  --basetemp=/tmp/1897-fixer-rescan/pytest-final
```

**实测**（`/usr/bin/time -p`）：`5 failed, 813 passed, 1 skipped in 43.33s`；`real 44.10` / `user 29.95` / `sys 10.37`。

### 失败如实记录（不冒称全绿；#1812→#1873）

| 失败 | 归属 |
|---|---|
| `test_pihong_dossier_1490.py::test_1682_phase2_surfaces_ambiguous_stored_choice` | 判词/前轮已记功能线索 |
| `test_fiscal_levy_effect.py` 四条事件结局/首判 | #1873 功能线索 |

本轮引入的 yizhu 空 `status_reason` 误闸已当场撤销；上表五失败改前改后均在。

未跑全量；未调真实模型。

### 测试最小必要成本（一行）

聚焦 19 文件≈818 例 / ~44s；契约=删换形空壳与自由 reason 跨面等值，保留闸/闭集/Event·Future/目录键。

---

## 自查二连

1. **同类型**：J1 全仓故事账+猜源谓词复扫后清旁路与 `turn` 死参；J2 覆盖 upsert 以外形状与说明；F3 按行为语义删空壳而非换形，不豁免 status_reason 跨散文。
2. **引入面**：未加恢复/补账/适配层；未 stash/reset/amend/push/PR；未动 Soul/宪法/宿主；自建物仅本仓 `artifacts/` 与 `/tmp/1897-fixer-rescan/`。

## 账目

- 本轮相对 `725d3aaa`：约 13 files，`+25 / −58`（以 `git diff --stat` 为准）
- 未 push / 未 PR / 未 amend
- 提交 SHA：见提交后 stdout / `git rev-parse HEAD`
