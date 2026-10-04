# #1889 修内司回执：K1 / K2（删简复用，非加诊断框架）

派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a10813-895f-7b5f-a223-2e7879189496@fixer/fix-packet.md`
判词附件（payloads **末份**为准）：`attachments/01-1889-judge-11da7ae74.json`
上轮纠偏 commit：`2a9f164c4`；本轮生产纠正后扫描快照 HEAD=`04fc8d377add8ce8639eada1843f8c78990aeba7`。
本文件是施工证据，不另立 authority。

官方方向（删简 / 复用，不造轮）：
- [Vulture](https://github.com/jendrikseipp/vulture)：静态未引用只是线索；须按消费者/职责逐项复核。**不得因静态无引用删仍属票面职责的接口。**
- [pytest Anatomy of a test](https://docs.pytest.org/en/stable/explanation/anatomy.html)：断言行为结果，不锁实现内部形状。

未结类（末份原文）：
1. **K1**「已退役入口的持久碎片与重复定义未随删简清退」— 成立。
2. **K2**「测试仍锁定退役实现及内部退役形状」— 成立。

---

## 本轮相对 `2a9f164c4` 的纠正

| 上轮问题 | 本轮处置 |
|---|---|
| 以零调用删 `PersonLogStore.for_person/by_origin`、`TextualFactStore.pointing_at`、`AffairStore.experiences/origin_refs/point_issue`、`CharacterKnowledgeStore.public_events_for_turn/sources_for_turn`、`DossierStore.pending_directive_*` | **精确恢复**（自 `7c25c5cae` 方法体手贴回，非 `git checkout`）；零调用≠消费者已退役；票面人物经历 / 文字事实挂对象 / 事务关联 / 公私知识 / pending 旨意职责仍在 |
| `parse_issue_id` 改 `int(rest)`、`parse_dossier_id` 复用 `parse_origin_ref` → 接受 `+1`/`01`/内部空格/全角数字 | **撤回**：`breach_plea` 恢复严格 `^dossier:([1-9][0-9]*)$` / `^issue:([1-9][0-9]*)$` 唯一一份；`credit_events`/`due_review` 只 import `parse_*`，不另立 RE |
| fund/`_issue_refs_strict` 的 `target_id` 误改走 `parse_issue_id` | **撤回**为原 `startswith("issue:")` + `int(split)`；与严格 origin_ref 解析解耦 |
| 回执曾写施工前/旧复扫数字（含 3566），与扫描快照 `04fc8d377` stdout 不符 | **本轮对明确扫描 HEAD 重跑 `--write`，以 stdout 为准写回执**（见下表） |
| 测试报告把两道命令的 passed 混写、且未写全命令 | **分列两道完整命令 + 输出 + 时长** |

未恢复（已有退役证据，保持删）：`GameDB.army_detail` / `ArmyStore.read_army_detail`（tools 消费者已删；materials 改定性名册）、`list_night_promulgated_directives`/`directives_by_ids`、`ReignStateStore` debug 表 CRUD / `rollback_chat_turn_ids_for_messages`。

---

## 枚举命令与全集

```sh
python3 scripts/1889_k1_k2_enumerate.py --write
```

全集：`git ls-files` 全部 `*.py`（含 `main.py`/`launcher.py`/`web_app.py`/`server/`/`scripts/`/`spike_settle_tick.py`）+ 测试 `tests/**`；另登记 tracked web vitest `*.{test,spec}.{ts,tsx}`（26，本票非持久职责，仅宇宙覆盖）。
删除入口：`fa0175a26..HEAD` ∪ `ddf53881f..HEAD` 的 `-def`；持久消费者 = `ming_sim/db.py` 或 `ming_sim/entities/**/store.py`；真正已删 = 持久子集且 HEAD 无同名定义。

落盘：

| 文件 | 内容 |
|---|---|
| `docs/1889-k1-k2-deleted-entries.tsv` | 删除 def 全集 |
| `docs/1889-k1-k2-members.tsv` | Store/GameDB + SQL DROP +（ming_sim 内）同形常量 |
| `docs/1889-k1-k2-k2-hits.tsv` | 测试交叉（call/patch/hasattr/meta/bytecode/web） |

### 复扫计数（扫描快照 `04fc8d377add8ce8639eada1843f8c78990aeba7`，stdout，2026-10-05）

扫描命令：`python3 scripts/1889_k1_k2_enumerate.py --write`（工作树生产/测试与该 SHA 一致；其后若只改文档，生产测试不变）。

```text
git-tracked py=383 tests=229 web_tests=26
Store/GameDB methods=1219
deleted union names=3558 truly_deleted_persistence=187
K1 members=1219 (unref_store=10 unref_gamedb=1 dup_const=0)
K2 hits=60
wrote docs/1889-k1-k2-*.tsv
```

| 项 | 值 |
|---|---|
| 扫描快照 SHA | `04fc8d377add8ce8639eada1843f8c78990aeba7` |
| git-tracked py | 383（tests=229；web_tests=26） |
| Store/GameDB 方法 | 1219 |
| 删除 union 名 | 3558（勿用施工前 3566） |
| 真正已删持久名 | 187 |
| K1 members | 1219（unref_store=10 / unref_gamedb=1 / dup_const=0） |
| `_DOSSIER_REF_RE`/`_ISSUE_REF_RE` 定义份数 | **各 1**（仅 `breach_plea.py`；credit/due 无本地 RE） |
| K2 hits | 60 |

---

## K1 本轮实际修动

### 重复引用规则（严格语义 + 单份 RE）

| 成员 | 处置 | 理由 |
|---|---|---|
| `_DOSSIER_REF_RE` / `_ISSUE_REF_RE` | **只留** `breach_plea` 各一份严格 regex | 原三模块同形严格 RE；合并=复用函数，**不得**借 DRY 放宽有效输入 |
| `parse_dossier_id` / `parse_issue_id` | **breach_plea 真源**；credit/due import | 不新造解析框架；不经 `parse_origin_ref` / `int(rest)` |
| fund / `_issue_refs_strict` 的 `target_id` | **保持**原 `startswith`+`int(split)` | 与严格 origin 解析无关；`2a9f164c4` 误改已撤回 |
| `_LOG_COLUMNS` / `_MUTABLE_COLUMNS` / `_SCHEMA_SQL` | **留** | 同名不同表 schema；非同一规则两份真源 |

### 临时秒级合法/非法参数对照（不入库测试）

对旧严格 RE（`7c25c5cae`）vs 本轮 `parse_*` vs `2a9f164c4` 宽松实现对照（elapsed ≈146ms）：

| 输入 | 旧/本轮 issue | 宽松 issue | 旧/本轮 dossier | 宽松 dossier |
|---|---|---|---|---|
| `issue:1` / `dossier:1` | 接受 | 接受 | 接受 | 接受 |
| `issue:+1` / `issue:01` / `issue: 1` / `issue:１` | **拒** | 曾接受 | — | — |
| `dossier:+1` / `dossier:01` / `dossier: 1` | — | — | **拒** | 曾接受 |
| `issue:0` / `dossier:0` / 空 / `affair:1` | 拒 | 拒 | 拒 | 拒 |

结论：本轮 `parse_*` 与旧严格 RE **零 mismatch**；宽松实现在 `+1`/`01`/内部空格/全角数字上越权放宽已纠正。
`target_id` 分支仍按原 `startswith`+`int(split)`（可收 `issue:+1`/`01`），与严格 `parse_issue_id` 分离。

### 票面职责接口（静态未引用 → **留/已恢复**，非猜删）

| 成员 | 处置 | 理由 |
|---|---|---|
| `PersonLogStore.for_person` / `by_origin` | **恢复留** | 人物经历读口；仅有 `count_by_origin`≠同语义全量列表 |
| `TextualFactStore.pointing_at` | **恢复留** | 文字事实按 origin 挂对象；`readable_materials` 是 subject 轴，非同语义 |
| `AffairStore.experiences` / `origin_refs` / `point_issue` | **恢复留** | 事务经历/关联/挂 issue；`input_brief`+`point_issue_row`/`attach_pointer` 非完整取代证据 |
| `CharacterKnowledgeStore.public_events_for_turn` / `sources_for_turn` | **恢复留** | 公私知识按回合读口；`events_for`/`all_sources`/`sources_upto_turn` 轴不同 |
| `DossierStore.pending_directive_ids_for_turn` / `delete_pending_directives_for_turn` | **恢复留** | pending 旨意按回合读写口；无「已被同语义入口取代」证据 |
| `ReignStateStore.list_closed_nights` | **留** | Store 侧 closed-night 读口；`db.py` 仍调已删 `list_closed_night_archives`（#1873） |
| `GameDB.flag_directive_needs_clarification` | **留** | #502 AC5 / #612 含糊准驳写口；接线缺口归 #1873 |
| `DossierStore.cost_events` | **留** | `scripts/family_tail_acceptance_570.py` 真实调用 |

### 退役碎片（有消费者退役证据 → 删，保持）

| 成员 | 处置 | 理由 |
|---|---|---|
| `GameDB.army_detail` / `ArmyStore.read_army_detail` | **删** | tools 调用方已删；materials 改定性名册 |
| `GameDB.list_night_promulgated_directives` / `IssueStore.directives_by_ids` | **删** | 唯一消费者链已不在 HEAD |
| `ReignStateStore.header_rows/metric_rows/header_row/metric_row` | **删** | 现役 `read`/`read_metrics`/`save`/`exists` |
| `ReignStateStore.upsert_header/delete_header/delete_metric` | **删** | debug CRUD 孤儿 |
| `ReignStateStore.rollback_chat_turn_ids_for_messages` | **删** | 现役 `rollback_chat_turn_id_for_pending_action` |

---

## K2 逐成员去留（人工表；本轮无新增删测）

| 成员 | 处置 | 理由 |
|---|---|---|
| `test_border_slice…` 内 `纯军饷漏斗` postures 断言 | **已删**（上轮） | 内部退役姿势证明 |
| `test_character_knowledge_489` world 负向 ×6 等 | **留** | 现役边界 / 拒收 |
| bytecode/getsource / standalone 退役证明 | **0 命中** | — |
| `call_deleted`（`list_closed_night_archives` 等） | **不删测 / 不恢复入口** | 归 #1873 |

web 测试 26 个仅登记宇宙；本票不改前端测试。

---

## 聚焦测试（七 BIN=/usr/bin/false）— 两道完整命令

### 命令 A（credit / effect / border / dossier sentinel / knowledge / smoke）

```sh
env \
  MING_SIM_AGY_BIN=/usr/bin/false \
  MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false \
  MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false \
  MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  python3 -m pytest -q \
    tests/test_credit_events_628.py \
    tests/test_effect_origin_558.py \
    tests/test_fiscal_substrate_bridge.py::test_border_slice_raw_content_keeps_primary_source_anchors \
    tests/test_execution_pressure_654.py::test_dossier_get_for_directive_existence_sentinel \
    tests/test_character_knowledge_489.py::test_inner_court_materials_exclude_court_world_slice \
    tests/test_character_knowledge_489.py::test_office_slice_does_not_read_unrelated_sensitive_reports \
    tests/test_new_game_smoke.py
```

输出（主座实际七 BIN=/usr/bin/false 运行回执 A 全命令；本轮只写入证据，不重跑）：

```text
..........................                                               [100%]
26 passed in 2.07s
```

### 命令 B（qa_a3 过滤；`-k` 只作用于本文件）

```sh
env \
  MING_SIM_AGY_BIN=/usr/bin/false \
  MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false \
  MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false \
  MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  python3 -m pytest -q \
    tests/test_qa_a3_seed_data.py -k 'vacancy or office or seed or opening'
```

输出：

```text
........                                                                 [100%]
8 passed in 0.62s
real 1.01
user 0.89
sys 0.11
```

未跑全量（派单禁止）。未 amend / stash / push / PR。未动存档与真配置。未新增证明性测试。

---

## 真实未结项

- 本切片未宣称 #1889 / #1812 merge 或关票。
- `list_closed_night_archives` / `knowledge_items_for_turn` / `list_supervision_history` 及 session→`flag_directive_needs_clarification` 接线缺口仍归 **#1873**。
- 家族收尾整体复杂度对比仍呈 owner（#1812 验收第 2 条）。
