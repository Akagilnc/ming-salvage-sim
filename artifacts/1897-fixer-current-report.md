# #1897 修内司回执（J1 / J2 / F3）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1897-w5`
- 分支：`ak-roles/issue-1897-j1-j2-f3-fixer-20261005-101325`
- 施工前 tip：`5d0b04dec46eaa8d1e9a4bac6b6c39b56d0c6861`
- 相对基线：`10e64fbef2857a4603c51394d16cea791b4f44c2`
- 判词：末份 `attachments/03-1897-judge-5d0b04dec.json`（先前三份仅参考；未结只取 J1/J2/F3）
- 票面：`gh issue view 1897` / `1812` 已打开；验收真源=#1812「重构验收」
- 互联网方向：YAGNI / dead-code 删除——证无调用后整段删兼容旁路与专属测试，不加适配层（Martin Fowler YAGNI；refactor-break-compat「One shape, no adapters」）
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

### 枚举命令

```bash
# 故事账写口中调用 get_open_night / get_last_active_chat_turn / _current_open_night_id 的函数
python3 - <<'PY'
import ast
from pathlib import Path
for path in Path('ming_sim').rglob('*.py'):
    src = path.read_text(encoding='utf-8')
    try: tree = ast.parse(src)
    except SyntaxError: continue
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)): continue
        body = ast.get_source_segment(src, node) or ''
        uses_ledger = (
            'append_ledger_entry' in body or 'ensure_inactive_office_summon' in body
            or 'path_nature' in node.name
            or '故事账' in (ast.get_docstring(node) or '')
            or '传召账' in (ast.get_docstring(node) or '')
        )
        guesses = (
            'get_open_night' in body or 'get_last_active_chat_turn' in body
            or '_current_open_night_id' in body
        )
        if uses_ledger and guesses:
            print(f'{path}:{node.name}:{node.lineno}')
PY
rg -n 'get_open_night|get_last_active_chat_turn|_current_open_night_id|未带源夜' \
  ming_sim/action_materialize.py
```

### 完整成员表（施工前 → 处置）

| # | 成员 | 根因 | 处置 |
|---:|---|---|---|
| 1 | `ming_sim/action_materialize.py::_write_path_nature_ledger`（判词样本 1281–1346） | 缺源夜时 `get_open_night` + `get_last_active_chat_turn`（含 `except Exception` 续跑） | **已清**：无持久源夜直接 return；只写 pinned 源夜/源轮 |
| 2 | `ming_sim/action_materialize.py::_persist_appointment_summon`（L107） | 缺源夜时 `_current_open_night_id()` 猜当前开夜挂传召账 | **已清**：只传 `pinned_night`；缺源由 `ensure_inactive_office_summon` 响亮拒（既有） |

### 非本类（复扫保留依据）

| 符号 | 为何不是 J1 |
|---|---|
| `audience_night.assert_night_accepts_player_input` / `open_night` / `dismiss_*` / `stay_*` | 当前夜操作/开夜本身，不是「缺持久源时猜夜写故事账」 |
| `db.update_*_candidate` 的 `_current_open_night_id` | pending 归属缝，非故事账 `append_ledger_entry` 猜源；未扩改（避免发明新恢复协议） |
| `materials` / `session` / `web_app` 的 `get_open_night` | 供料与 UI 读当前夜，非故事账猜源旁路 |

### 复扫

施工后：`action_materialize.py` 内 `get_open_night` / `get_last_active_chat_turn` / `_current_open_night_id` 均为 **False**；故事账+猜源函数表为空。

---

## J2：退休 upsert 猜目标入口

### 类定义（判词）

boundary：密令创建／精确更新接缝  
direction：清退按承办人最新 active 猜目标的退休入口、说明和专属测试；不补新调用。

### 枚举命令

```bash
rg -n --type py '\bupsert_secret_order\b' -g '!**/docs/**' -g '!**/TEST_AUDIT*' -g '!**/CMR_*'
```

### 完整成员表

| # | 成员 | 处置 |
|---:|---|---|
| 1 | `ming_sim/db.py::upsert_secret_order` 定义+说明 | **已删** |
| 2 | `update_secret_order_by_id` 文档中对 upsert 的对比说明 | **已删**（保留精确 id 更新说明） |
| 3 | `tests/test_secret_order_update.py::test_upsert_creates_then_updates` | **已删** |
| 4 | `tests/test_secret_order_update.py::test_upsert_different_minister_creates_new` | **已删** |
| 5 | 同文件模块说明（upsert create-or-update） | **已改**为精确更新说明 |
| — | `upsert_secret_order_brief` | **非本类**（不同符号，现役 brief 写口） |
| — | `docs/CMR_REPORT_y2_probe.md` / `TEST_AUDIT_1185.md` 历史记载 | **保留过程史**；非现役入口 |

### 复扫

`def upsert_secret_order(` 在 `ming_sim/db.py` 为 **False**；测试文件无调用。现役精确更新四案保留。

---

## F3：授权触及测试清退

### 类定义（判词）

boundary：授权改动对应测试体系  
direction：按行为契约清退散文机械依赖、换形保真证明及无价值断言；复用真实入口结构化案；保留闸类负向与 Event/Future 控序；不新建平行证明体系。

### 授权触及测试清单（43）

```bash
git diff --name-only 10e64fbef HEAD -- tests | grep '^tests/test_.*\.py$' | sort
```

（完整 43 文件名见本轮 `/tmp/1897-fixer-j1j2f3/touched-tests.txt`；仓内不另堆平行 TSV。）

### 语义审查方法

1. 预扫描：AST 对触及测试中的 `==` / `len+strip` / `isinstance(..., str)` / 自由字段交叉等值  
2. **逐条行为语义终裁**（字段词表不等于类成员）：结构码、SSE、闭集枚举、空位闸、origin_ref、Event/Future **保留**  
3. 缺陷形状：跨文本正文等值、长度/strip 换形、label 透传等值、自由 status_reason 比较、world_segment/forecast 正文锁、类型-only 递送证明、正文子串承重  

### 真正 F3 成员完整表（须清）

| # | 成员 | 形状 | 处置 |
|---:|---|---|---|
| 1 | `test_style_temperament_641.py` summary `len>len(strip)` | LEN_STRIP 换形 | **删断言**；保留键存在 |
| 2 | `test_relation_capture_633` 全文链 context 字节等值案 | CROSS 保真 | **整案删** |
| 3 | 同文件 whitespace 写缝等值 | CROSS 保真 | **改**为空白拒收闸（负向保留）+ event_kind 结构 |
| 4 | `test_pihong` preferred_hitl `label==opt['label']` 两处 | CROSS label 换形 | **改**为 `'label' in` + 结构字段 |
| 5 | `test_person_delta` `status_reason != old_imprison` | 自由 reason 比较 | **改**为 `reason_code==""` + status/turn |
| 6 | `test_month_chain_1847` `world_segment==` 散文 | LIT 锁文 | **改**键存在 |
| 7 | 同案 `secret_forecast in forecasts` | FORECAST 成员锁 | **改**键存在 |
| 8 | 同案 `isinstance(carrier,str)` | TYPE 换形 | **删**；目录键 + read 观察 |
| 9 | 同文件续推 `label==choice['label']` / 正文子串 | CROSS/子串 | **改**调用次数 + 键存在 + segments 非空 |
| 10 | `test_gazette_author_1862` 事实/经历正文 `in` + world_segment 等值 | LIT/子串 | **改**目录键 / `world_segment` 键 |
| 11 | `test_month_chain_1843` `run_world_segment_text=="静"` | LIT 锁返回 | **删等值**；保留侧效结构断言 |
| 12 | `test_fiscal_levy` presented_context/emperor_note 字面 | LIT | **改**键存在；`held` 保留 |
| 13 | `test_decree_dossiers` promulgation_reason / execution_note 字面 | LIT | **改**键存在；层/状态保留 |
| 14 | `test_mechanical_tail` summary 跨文本等值 | CROSS | **改**键/空位；打印面只观察 |
| 15 | `test_secret_order_isolation` body==old_public | CROSS 保真 | **删等值**；knowledge_status 保留 |
| 16 | `test_urge_lever` origin_context/criterion 跨等值 | CROSS | **改**键存在；payload 不泄漏保留 |
| 17 | `test_event_trigger_gate` status_reason!="获罪削籍" | 自由 reason | **删**；`reason_code==""` 保留 |
| 18 | `test_rescript_choices` labels 列表等值 | LABEL 锁 | **改** options 长度；空 label 负向闸保留 |
| 19 | `test_rescript_draft` `isinstance(reason,str)` | TYPE 换形 | **改** `'reason' in pack` |
| 20 | J2 专属 upsert 两案 | 退休机制专属测 | **随 J2 删** |

### 保留例外（非缺陷）

| 类型 | 依据 |
|---|---|
| SSE `event: done/error` | 线协议控序 |
| 空位闸 `label==""` / `summary==""` / blank context ValueError | 闸类负向 |
| `reason_code` / `mode` / `deliberation_state` / `status` 闭集 | 结构化机器码 |
| origin_ref / decree_ref / dossier_id | 身份键 |
| memory↔DB status_reason **同步**断言 | 三面一致结构契约，非锁某一散文字面 |
| Event/Future 握手（declaration landing） | 判词显式保留 |
| style 未变 before==after（性情拒收） | 结构化字段未变契约 |

### 复扫

判词点名样本探针均为 **CLEARED**。未新增平行测试文件。

---

## 测试（聚焦，非全量）

命令（七变量前缀 +）：

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
  --basetemp=/tmp/1897-fixer-j1j2f3/pytest-seal
```

**实测**（`/usr/bin/time -p`）：`5 failed, 813 passed, 1 skipped in 39.27s`；`real 39.72` / `user 27.96` / `sys 9.58`。

### 失败如实记录（不冒称全绿；按 #1812→#1873）

| 失败 | 归属 |
|---|---|
| `test_pihong_dossier_1490.py::test_1682_phase2_surfaces_ambiguous_stored_choice` | 判词/前轮已记功能线索 |
| `test_fiscal_levy_effect.py::test_fiscal_levy_petition_reaches_emperor_desk_and_lands_only_after_choice` | 事件结局未落终态（#1873） |
| `test_fiscal_levy_effect.py::test_same_batch_keeps_the_first_event_outcome` | 同上 |
| `test_fiscal_levy_effect.py::test_unbound_envelope_does_not_overwrite_the_first_event_outcome` | 同上 |
| `test_fiscal_levy_effect.py::test_later_illegal_outcome_does_not_discard_the_first_ruling` | 同上 |

本轮 J1/J2/F3 引入的失败（yizhu 空 reason、continuation decision_key）已当场改回结构化断言后复绿；上表五失败在改前改后均在，非本片新引入。

另：`tests/test_secret_order_declaration_landing_1897.py` + staged/reopen 子集 `65 passed in 2.31s`。

未跑全量；未调真实模型。

---

## 自查二连

1. **同类型**：J1 全仓故事账写口枚举后清两处猜源；J2 整入口+专属测删除不补调用；F3 按行为语义非整表字段词表，负向闸与 Event/Future 保留。  
2. **引入面**：未加恢复/补账/适配层；未 stash/reset/amend/push/PR；未动 Soul/宪法/宿主；自建物仅本仓 `artifacts/` 与 `/tmp/1897-fixer-j1j2f3/`。

## 账目

- diffstat：18 files，约 +51 / −143（以 `git diff --stat` 为准）  
- 未 push / 未 PR / 未 amend  
- 提交 SHA：见提交后 stdout / `git rev-parse HEAD`
