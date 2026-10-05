# #1902 修内司 S1 续修回执（底座差分·187 真实处置）

- 分支：`ak-roles/1902-s123-fixer-6850e0b5f`
- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1902-w5`
- 底座：`10e64fbef`；施工前 HEAD：`6b91e05b9`
- 本轮范围：**仅 S1**（S2/S3 本轮已核属实，不送修）
- 判词方向：用底座差分对 187 个零生产引用候选逐成员给出真实 disposition（删除或保留及依据）；凡生产调用方被本分支删除、现仅测试/monkeypatch 存活者，根连专属测试一并清；**不得把 disposition_hint 冒充全处置**
- **不宣称已合并 / 总票完成**；不 stash/amend/rewrite/push/PR

七 BIN 前缀（显式展开）：

```bash
env \
  MING_SIM_AGY_BIN=/usr/bin/false \
  MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false \
  MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false \
  MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=. \
  python3 -m pytest ...
```

---

## 实际枚举命令（临时 AST，非永久扫描器）

```bash
cp evidence/issue-1902/s123-scan-s1.ast.py.txt /tmp/scan_s1.py
SCAN_ROOT=. SCAN_OUT=/tmp/ming1902-s1-after python3 /tmp/scan_s1.py \
  | tee evidence/issue-1902/s123-s1-rescan-summary.txt
cp /tmp/ming1902-s1-after/s1-full.json evidence/issue-1902/s123-s1-enum.json
```

施工前零引用集：`ZERO_PROD_REF_CANDIDATE=187`（另 FRAMEWORK=3 / DYNAMIC=1 / DUNDER=6）。

施工后复扫：`ZERO_PROD_REF_CANDIDATE=184`（−3 根；`credit_event_to_edge` 删前因同文件 Load 不在 187，随独占依赖清后退役 defs 缺席）。

底座差分审计（临时）：

```bash
BASE_SHA=10e64fbef SCAN_ROOT=. python3 /tmp/ming1902-s1-disp/audit_s1.py
# 产出 /tmp/ming1902-s1-disp/s1-disposition.json + 全员核实 →
# evidence/issue-1902/s123-s1-disposition.json|.md
```

谓词：对每个 ZERO 候选，核对 `10e64fbef` 与 HEAD 的生产 Load/Attribute/scripts 引用；**仅当底座有外生产消费者且本分支已删尽、现仅测试/monkeypatch 存活 → DELETE**；否则 KEEP（含 FastAPI 假死、#1847 待接线、底座从未接线、scripts 消费者等）。

---

## S1 类处置摘要

| 类 | 数 | 含义 |
|---|---|---|
| DELETE（187 内） | 3 | `credit_events_as_edges` / `get_night_protagonist` / `delete_chat_messages` |
| DELETE（独占依赖） | 1 | `credit_event_to_edge`（仅被上一根调用） |
| KEEP | 184 | 见全表；含 FastAPI、#1847、never-wired、假死注释命中等 |

**全员真实处置表（禁止 hint 冒充）**：

- `evidence/issue-1902/s123-s1-disposition.json`
- `evidence/issue-1902/s123-s1-disposition.md`

### 本轮 DELETE（逐成员）

| 成员 | 底座生产消费者 | 现存活 | 处置 |
|---|---|---|---|
| `ming_sim/relations.py::credit_events_as_edges` | `db.read_credit_events_as_edges`（已删） | `test_relation_store_632::test_credit_contract_fixture_*` | **删根** + 独占依赖 `credit_event_to_edge` + 专属测 |
| `ming_sim/audience_night.py::get_night_protagonist` | `session` 留侍分支（已删） | `test_audience_translation_1838` 9 观测引用 | **删包装**；AC3 真入口测改读 `audience_nights.protagonist_name`（`set`/`reproject` 仍写） |
| `ming_sim/db.py::delete_chat_messages` | `cli/terminal.py`（已删） | `test_character_knowledge_489` 直调 + `test_cli_play_turn` monkeypatch | **删方法** + 专属测 + 清无意义 monkeypatch |

### 点名 KEEP（判词例外）

| 成员 | 处置 | 依据 |
|---|---|---|
| `minister_speaker_role` | KEEP | 底座原本无调用，不强求删 |
| `project_preferred_hitl_choice` | KEEP | `scripts/agy_turn_probe.py` / `scripts/family_tail_acceptance_570.py` 真实消费者（不在零引用集） |
| `generate_rescript_draft` / `create_rescript_draft_agent` | KEEP | #1847 待接线能力合法保留 |
| FastAPI `api_*` / 框架入口 | KEEP | 装饰器注册；AST Load=0 属假死 |

同类一次核实：187 全员底座/当前生产引用交叉后，**仅上述 3 根符合「本分支删尽生产消费者」**；无第四个遗漏同类。

---

## S2 / S3

本轮**不送修**。上轮全宇宙 S2（3293）与 S3 单源已核属实，维持既有回执结论。

---

## 聚焦测试证据

`evidence/issue-1902/s1-orphan-focus-pytest.txt`：

```
93 passed in 2.62s
real 3.25
```

触及面：

- `tests/test_relation_store_632.py`
- `tests/test_audience_translation_1838.py`
- `tests/test_character_knowledge_489.py`
- `tests/test_cli_play_turn.py`

未跑全量、未真调模型。七 BIN 均显式 `/usr/bin/false`。

---

## 自查二连

- **合法性**：未改 CLAUDE.md/AGENTS.md/CONTEXT.md/ADR；未恢复手拟入口；未增护栏/永久扫描器/生产钩子/兼容层；未改治理或宿主席位配置；扫描与处置表以 evidence 临存，`/tmp/ming1902-s1-*` 自建可清。
- **质量**：187 逐成员真实 disposition（非 hint）；DELETE 仅底座差分证实之孤儿；AC3 行为测保留并对账本列观测；S2/S3 本轮不动。
- **复杂度**：净删 3 根 + 1 独占依赖 + 专属测/无意义 monkeypatch；无新增机制。

---

## 例外 / 上呈

无缺 owner 决定项。`generate_rescript_draft` 仍按 #1847 保留；`minister_speaker_role` 按判词不强求删；`project_preferred_hitl_choice` 因 scripts 消费者保留。
