# #1889 修内司回执：K1 / K2（删简复用，非加诊断框架）

派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a10813-895f-7b5f-a223-2e7879189496@fixer/fix-packet.md`  
判词附件（payloads **末份**为准）：`attachments/01-1889-judge-11da7ae74.json`  
上轮：`7c25c5cae`（枚举白名单化）/ `2c4e6ae07`（首清碎片）；本轮独立纠正后 HEAD 见 git。  
本文件是施工证据，不另立 authority。

官方方向（删简 / 复用，不造轮）：
- [Vulture](https://github.com/jendrikseipp/vulture)：静态未引用只是线索；须按消费者/职责逐项复核。
- [pytest Anatomy of a test](https://docs.pytest.org/en/stable/explanation/anatomy.html)：断言行为结果，不锁实现内部形状。

未结类（末份原文）：
1. **K1**「已退役入口的持久碎片与重复定义未随删简清退」— 成立。
2. **K2**「测试仍锁定退役实现及内部退役形状」— 成立。

---

## 本轮相对上轮回执的纠正

| 上轮问题 | 本轮处置 |
|---|---|
| `_DOSSIER_REF_RE` / `_ISSUE_REF_RE` 凭「各模块自有真源」保留完全相同定义 | **合并**：dossier 复用 `entities.affair.parse_origin_ref`；issue 只留 `breach_plea.parse_issue_id`；`credit_events`/`due_review` 删本地 RE |
| `scripts/1889_k1_k2_enumerate.py` ~1198 行诊断框架（`_NOISE_SYMBOLS`/自动 suggested/模型类） | **压缩**为 ~393 行直接 AST/csv/git 枚举；不新增机制；`suggested` 仅粗标，去留在回执人工表 |
| K2 谓词硬编码 standalone `_meta` | **扩枚举** hasattr / bytecode·getsource / `_meta` absence / standalone assert / patch|call 已删入口；人工逐项去留 |
| 17 unref + 2 GameDB 一律「may be pending wiring」留 | **逐项职责核查**；无消费者且无票面写读口 → 删；有真实接线职责 → 留并写证据 |

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

### 复扫计数（本轮）

| 项 | 值 |
|---|---|
| git-tracked py | 383（tests=229；web_tests=26） |
| Store/GameDB 方法 | 1209 |
| 删除 union 名 | 3546 |
| 真正已删持久名 | 176 |
| K1 members | 1209（unref_store=1 / unref_gamedb=1 / dup_const=0） |
| `_DOSSIER_REF_RE`/`_ISSUE_REF_RE` 同形 | **0** |
| K2 hits | 60（call_deleted 等；见下表） |

---

## K1 本轮实际修动

### 重复引用规则（已授权类）

| 成员 | 处置 | 理由 |
|---|---|---|
| `_DOSSIER_REF_RE`×3（breach/credit/due） | **删本地；复用** `parse_origin_ref` | 结构化 effect-ref 真源已在 `ming_sim/entities/affair/store.py`；`breach_plea.parse_dossier_id` 为其薄包装 |
| `_ISSUE_REF_RE`×2（breach/credit） | **只留** `breach_plea.parse_issue_id` | 同形 kind:id；credit 改 import；不新造解析框架 |
| `_LOG_COLUMNS` / `_MUTABLE_COLUMNS` / `_SCHEMA_SQL` | **留** | 同名不同表 schema；AST dump 不同，非同一规则两份真源 |

### 退役碎片 / 无消费者 API（删）

| 成员 | 处置 | 理由（真实调用/职责） |
|---|---|---|
| `AffairStore.point_issue` | **删** | 零 Attribute 调用；生产走 `point_issue_row`/`attach_pointer` |
| `AffairStore.experiences` / `origin_refs` | **删** | 全仓零调用；输入面用 `input_brief`+`textual_facts.readable_materials` |
| `GameDB.army_detail` | **删** | tools 调用方已删（fa0175 有、现无）；materials 明确改定性名册，禁裸值渲染 |
| `ArmyStore.read_army_detail` | **删** | 唯一消费者即已删 `army_detail` |
| `GameDB.list_night_promulgated_directives` | **删** | 零调用；原测试调用已不在 HEAD |
| `IssueStore.directives_by_ids` | **删** | 唯一消费者即已删 list_night… |
| `ReignStateStore.header_rows/metric_rows/header_row/metric_row` | **删** | 现役读写是 `read`/`read_metrics`/`save`/`exists`；原 GameDB debug 表 API 已删 |
| `ReignStateStore.upsert_header/delete_header/delete_metric` | **删** | 同上，debug CRUD 孤儿 |
| `ReignStateStore.rollback_chat_turn_ids_for_messages` | **删** | 零调用；现役用 `rollback_chat_turn_id_for_pending_action` |
| `DossierStore.pending_directive_ids_for_turn` / `delete_pending_directives_for_turn` | **删** | 零调用；其它 pending_directive_* 仍经 GameDB 使用 |
| `CharacterKnowledgeStore.public_events_for_turn` / `sources_for_turn` | **删** | 零调用；现役 `events_for` / `all_sources` / `sources_upto_turn` |
| `PersonLogStore.for_person` / `by_origin` | **删** | 零调用；现役 `append` + `count_by_origin`（covert_progress） |
| `TextualFactStore.pointing_at` | **删** | 零调用；现役 `readable_materials` / materials 写口 |

### 静态未引用但仍留（逐项职责，非「pending wiring」套话）

| 成员 | 处置 | 理由 |
|---|---|---|
| `ReignStateStore.list_closed_nights` | **留** | `db.py` 仍调用已删 `list_closed_night_archives`（#1873 缺口）；本方法是 Store 侧已就位的 closed-night 读口，删之会抹掉接线落点 |
| `GameDB.flag_directive_needs_clarification` | **留** | #502 AC5 / #612 含糊准驳写口；fa0175 `session.py` 曾调，现接线缺口归 #1873；payload 键 `_needs_clarification` 仍被测试/消费路径识别，删写口越权补洞 |
| `DossierStore.cost_events` | **留** | `scripts/family_tail_acceptance_570.py:87` 真实调用；案卷代价账读口 |

（上轮 17 unref 中其余已按上表删除。）

---

## K2 逐成员去留（人工表）

枚举谓词覆盖：`assert not hasattr`、`__code__`/`co_names`/`getsource`、`_meta`+`not in`/`not any`、`standalone`+assert、对真正已删持久名的 patch/call、tracked web 测试文件登记。

### 本轮删除（无必要行为价值 / 退役形状）

| 成员 | 处置 | 理由 |
|---|---|---|
| `test_border_slice…` 内 `assert "纯军饷漏斗" not in …["_meta"]["postures"]` ×2 | **删断言** | 内部退役姿势证明；同测已有 Due/拨付/军饷欠==0 外部行为 |

### 保留（现役边界 / 拒收 / 失败负向）

| 成员 | 处置 | 理由 |
|---|---|---|
| `test_character_knowledge_489` world 负向 ×6 | **留** | 现役公私可见边界 |
| `test_event_trigger_gate` hasattr ghost ×2 | **留** | 污染护栏，非退役 API absence |
| `assert "_meta_defaults" not in loaded` | **留** | 加载器展开行为（defaults 须被吃掉） |
| provisional 内「官民田/起运定额/正赋应征」not in ×3 | **留** | 现役 seed 精炼完成态，非退役键 |
| surcharge `_meta`/`加派基线` before 态 | **留** | 加派前基线缺席的行为契约 |
| bytecode/getsource | **0 命中** | — |
| standalone assert（退役证明） | **0 命中** | 上轮已清；本轮复扫仍清 |

### 测试调用真正已删入口（不删测试 / 不恢复入口）

`call_deleted` 等（`list_closed_night_archives` / `knowledge_items_for_turn` / `list_supervision_history` 等）→ **#1873**；本轮不送修。due_review/breach 全文件 settle 路径亦踩 `knowledge_items_for_turn` 红灯，同属 #1873，非本轮引入。

### web 测试

26 个 tracked `*.{test,spec}.{ts,tsx}` 仅登记宇宙；本票不改前端测试（非持久职责）。

---

## 聚焦测试（七 BIN=/usr/bin/false）

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
    tests/test_new_game_smoke.py \
    tests/test_qa_a3_seed_data.py -k 'vacancy or office or seed or opening'
```

实测：`credit/effect/border/smoke/knowledge` → **26 passed**；`qa_a3 -k …` → **8 passed**。  
复扫：`CONST_DUP:_DOSSIER_REF_RE/_ISSUE_REF_RE` = 0；`纯军饷漏斗` postures 断言已不在。

未跑全量（派单禁止）。未 amend / stash / push / PR。未动存档与真配置。

---

## 真实未结项

- 本切片未宣称 #1889 / #1812 merge 或关票。
- `list_closed_night_archives` / `knowledge_items_for_turn` / `list_supervision_history` 及 session→`flag_directive_needs_clarification` 接线缺口仍归 **#1873**。
- 家族收尾整体复杂度对比仍呈 owner（#1812 验收第 2 条）。
