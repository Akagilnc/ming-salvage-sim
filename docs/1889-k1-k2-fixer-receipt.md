# #1889 修内司回执：K1 / K2（全量枚举纠正）

派单：`~/.ak-roles/books/Ming_LLM/unbound/runs/01a10813-895f-7b5f-a223-2e7879189496@fixer/fix-packet.md`  
判词附件（payloads **末份**为准）：`attachments/01-1889-judge-11da7ae74.json`  
上轮施工 commit：`2c4e6ae07`；本轮纠正枚举起点 HEAD 见 git。  
本文件是施工证据，不另立 authority。

官方方向（删简 / 复用，不造轮）：
- [Vulture](https://github.com/jendrikseipp/vulture)：静态未引用只是线索；隐式调用会产生误报，不能不经消费者/职责复核一概删。
- [pytest Anatomy of a test](https://docs.pytest.org/en/stable/explanation/anatomy.html)：断言行为结果，不锁实现内部形状。

未结类（末份原文）：
1. **K1**「已退役入口的持久碎片与重复定义未随删简清退」— 成立。阻断的是具体残留职责与重复实现；尚待家族接线但仍对应票面职责的未调用接口，不因静态未引用一概删。
2. **K2**「测试仍锁定退役实现及内部退役形状」— 成立。清理无必要行为价值的测试成本；保留现役可见边界/拒收/失败负向；不以红灯要求补功能。

---

## 缺陷纠正（相对上轮回执）

上轮回执的 `SHAPE` / `RETIRED_HOOKS` / `standalone` 两行谓词是**点名符号白名单**，不足以满足全类枚举；「其它静态未引用 API 多处」也不是逐成员表。

本轮替换为可重跑诊断脚本（**仅诊断**，不新增生产机制、不加证明性测试）：

```sh
python3 scripts/1889_k1_k2_enumerate.py --write
```

全集：`git ls-files`（prod `ming_sim/**` + `web_app.py` + `tests/**`）。  
删除入口：`fa0175a26..HEAD` 与 `ddf53881f..HEAD` 的 `git diff -U0` 提取 `-def`；**持久消费者子集** = 删除行落在 `ming_sim/db.py` 或 `ming_sim/entities/**/store.py`；**真正已删** = 持久子集且 HEAD 无同名 GameDB/Store 定义（排除改写重挂假阳性）。

落盘（回执引用，勿手抄全表）：

| 文件 | 内容 |
|---|---|
| `docs/1889-k1-k2-deleted-entries.tsv` | 两基线删除 def 全集 + `persistence_consumer` 旗 |
| `docs/1889-k1-k2-members.tsv` | 全 Store/GameDB 方法 + SQL 旧布局 + 重复体/常量 逐成员 |
| `docs/1889-k1-k2-k2-hits.tsv` | 测试交叉（patch/call/assert/hasattr/源码探针/现役负向） |

---

## 本轮复扫计数（脚本 stdout）

| 项 | 值 |
|---|---|
| git-tracked 全集 | 1270（py prod=121 tests=229） |
| Store 方法 | 837 |
| GameDB 方法 | 394 |
| 删除 def 名 fa0175a26→HEAD | 3460 |
| 删除 def 名 ddf53881f→HEAD | 142 |
| 删除 union | 3488 |
| 持久消费者删除名 | 271 |
| **真正已删**（HEAD 无定义） | **175** |
| K1 member 行 | 1242（delete=0 / review=13 / keep=1229） |
| retired_fragment_unref | **0**（清退后） |
| unref_public_store（政策保留） | 17 |
| dup_body 可删孪生 | 0 |
| SQL DROP 无 CREATE peer | 0 |
| 多文件 UPPER 常量 | 5（review→收据判留） |
| K2 hits | 21（deleteish=0；#1873 标注=13；现役负向 keep=6；hasattr review=2） |

---

## 本轮实际修动

| 成员 | 处置 | 理由 |
|---|---|---|
| `IssueStore.read_list_recent_issue_advances` | **删** | 全量枚举新命中：消费者 `GameDB.list_recent_issue_advances` 已删（ddf→HEAD）；全仓零引用；SQL 碎片无其它接线 |
| `test_get_dossier_for_directive_existence_sentinel` | **改名** → `test_dossier_get_for_directive_existence_sentinel` | 用例名锁已删 `get_dossier_for_directive`；体已走现役 `dossiers.get_for_directive`，只去名成本 |
| 上轮已清 K1/K2 样本（faction_report 碎片、standalone `_meta`、population 双真源、DROP dossier_progress_reports 等） | 复扫确认仍清 | 见上轮 `2c4e6ae07`；本轮谓词不再靠白名单宣称 |

---

## K1 逐成员去留（摘要；全表见 TSV）

### 建议 delete（本轮/复扫）

施工后 `suggested=delete` = **0**。  
施工中唯一新命中见上表（已删）。

### 静态未引用公共 Store（17）— 一律 **留**

政策：不因静态未引用一概删（Vulture / 判词）。完整名单见 TSV `class=unref_public_store`，包括但不限于：

- `ReignStateStore.list_closed_nights` — 待接线对应已删 `list_closed_night_archives` 读口；**保留真实待接线职责**
- `CharacterKnowledgeStore.public_events_for_turn` / `sources_for_turn`
- `PersonLogStore.for_person`、`TextualFactStore.pointing_at`、`AffairStore.point_issue`
- `DossierStore.cost_events` / pending-directive 系列
- `ReignStateStore` header/metric CRUD 若干

### 名似退役但仍有引用 — **留**

- `CharacterStore.read_knowledge_items_for_turn`：`opening_seed.py` 仍调用；SQL 是人物名册字段，与已删 GameDB `knowledge_items_for_turn`（知识投影）不同物，不能当无主碎片删。

### 重复方法体 / 常量 — **留**（无删授权）

- `ensure_schema` / `append_log` 等同体：各实体自有 schema/log 表，同形薄包装；两边均有引用或同角色对称 → TSV `duplicate_body_both_live_or_both_dead`
- `_LOG_COLUMNS` / `_MUTABLE_COLUMNS` / `_SCHEMA_SQL` / `_DOSSIER_REF_RE` / `_ISSUE_REF_RE`：按实体或模块各自真源，非「同一单位两份真源」类（上轮已合并的 `POPULATION_UNIT_*` 不在此列）

### SQL 旧布局

- `DROP … IF EXISTS` 无 CREATE peer：**0**（上轮已删 `dossier_progress_reports` DROP）
- `scripts/huangtaiji_rename_qing.sql` ALTER：**review/留**（运维脚本，非运行时旧布局处置）

---

## K2 逐成员去留（摘要；全表见 TSV）

### 授权清退（deleteish）

复扫 **0**。上轮已清：`faction_report` monkeypatch、`_meta`/`standalone` 退役键断言、`turn_region_summary_*` 名锁等。

### 本轮改名

- `test_dossier_get_for_directive_existence_sentinel`（见上）

### 现役负向契约 — **留**（6）

`test_character_knowledge_489.py` 内 `personnel`/`military`/`treasury`/`court` not in `world` — 公私可见边界，非退役形状证明。

### hasattr 探针 — **留**（2）

`test_event_trigger_gate.py` 对 `_test_runtime_ghost_attr` / `ghost_preflight_attr` 的 `assert not hasattr` — 污染护栏，不是退役 API absence 证明。

### 测试调用真正已删入口且生产仍自呼 — **不删测试 / 不恢复入口**（13）

标注 `keep_escalate_1873`（末份 J7/J9 → #1873，本轮不送修）：

| 缺失入口 | 测试侧 | 生产仍调用 |
|---|---|---|
| `list_closed_night_archives` | scroll/p4/qa_d1 | `ming_sim/db.py:5805` |
| `knowledge_items_for_turn` | character_knowledge_489 ×4 | `db.py:5646` 等 |
| `list_supervision_history` | supervision_625 ×5 | `db.py:6954` 等 |

这不是「只锁内部退役形状」的测试成本；删测试会抹掉行为覆盖，补方法越权。收据仅机械登记。

---

## 复扫命令与结果

```sh
python3 scripts/1889_k1_k2_enumerate.py --write
# → K1 suggested=delete (none); K2 deleteish (none); retired_fragment_unref=0
```

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
    tests/test_execution_pressure_654.py::test_dossier_get_for_directive_existence_sentinel \
    tests/test_character_knowledge_489.py::test_inner_court_materials_exclude_court_world_slice \
    tests/test_character_knowledge_489.py::test_office_slice_does_not_read_unrelated_sensitive_reports \
    tests/test_new_game_smoke.py \
    tests/test_qa_a3_seed_data.py -k 'vacancy or office or seed or opening'
```

实测：`12 passed, 7 deselected in 1.85s`。  
复扫：`retired_fragment_unref=0`；`K2 deleteish=0`；`IssueStore.read_list_recent_issue_advances` 已不存在。

未跑全量（派单禁止）。未 amend / stash / push / PR。未动存档与真配置。

---

## 真实未结项

- 本切片未宣称 #1889 / #1812 merge 或关票。
- 功能缺口与测试红灯仍归 **#1873**（末份 J7/J9）；上表 13 条 call_deleted 已机械登记，不在本轮清 K2 形状成本。
- 17 个 unref_public_store 保留待家族接线，不扩删。
- 家族收尾整体复杂度对比仍呈 owner（#1812 验收第 2 条）。
