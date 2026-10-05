# #1889 六类修内司回执（交卷闸更正 · 类6全员映射）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1889-w5r`
- 施工分支：`ak-roles/1889-six-class-fixer`
- 判词真源：`…/attachments/04-1889-judge-00aff8316.json` → `outcome.payloads` **末份**
- 相对开工基线：`00aff8316`；前序：`684919d60` / `8e77a2b46` / `23a761a8a` / `ed2c32253`
- 本轮：席核纠类6「65 条长汉抽查 ≠ 18295 全员处置」；补全员语义映射 + 真锁 DELETE + CLI 轻壳接 Store
- 约束：无 amend / rebase / stash / push / PR；七变量 BIN=`/usr/bin/false`；只跑聚焦且**不得 `-k`**；不新建证明测试/护栏/兼容；不改角色包或全局交卷工具；不为绿补功能；不跑基线归因

---

## 交卷闸更正（本轮要点）

| 更正项 | 事实 | 处置 |
|---|---|---|
| 类6 抽查冒充全清 | 前收回执仅长汉 65 抽查却称 18295 分组完；TSV 无逐成员 disposition | **本轮**合并 assert+compare 同址 → 10587 唯一位点；`evidence/1889-c6-member-disposition.tsv` 全员有 disposition+basis；`evidence/1889-c6-group-review.tsv` 按源文件×处置族给审阅行号范围 |
| 短汉/英文非自动 KEEP | 禁止长度/正则裁决自由文 | 入参来源四分：机器标识 / 测试自注入保真 / 固定 UI / 非契约生产叙事·标题·报错锁；无源依据不落 KEEP |
| 真锁 vs 放松结构化 | `canonical target` 锁 rejection reason 措辞 | **DELETE** 该措辞锁；改姊妹用例同形 `rejection_reports COUNT WHERE section='directive_locality'`（见 `evidence/1889-c6-deletes.tsv`） |
| CLI 轻壳缺 dossiers | more 批曾 4 红：`Db` 挂 `list_pending_actions` 旧 facade | 按类6改现有 fixture → `db.dossiers.list_pending_actions`（现役 Store 入口）；不恢复 compat、不扩面 |
| 红测归因 | 本轮未跑基线同令 | **不**标「非本票引入」；记为观察。修 dossiers 后 more 批现 **513 passed** |
| 不以抽查无 DELETE 报整类完 | — | 全员映射 0×NEED_REVIEW；DELETE 1 处已落码 |

---

## 可复跑枚举

```bash
cd /Users/akagilnc/WorkSpace/Ming_LLM-1889-w5r
python3 scripts/1889_six_class_enumerate.py --out evidence/1889-six-class-enum.tsv
# 本轮：real 8.42s；rows=19568；c6_string_lock=18293（删措辞锁后 −2 assert/compare 行）
```

### lane 计数（实测）

| lane | count |
|---|---|
| c1_fiscal_retired | 6 |
| c2_forward | 4 |
| c2_sql_framework | 65 |
| c2_sql_in_store | 792 |
| c2_sql_leak_candidate | 9 |
| c2_sql_schema | 1 |
| c3_orphan_mech | 21 |
| c4_pop_parallel | 376 |
| c5_affair_close | 1 |
| c6_string_lock | 18293 |

### `git diff --check`

```bash
git diff --check 00aff8316 HEAD   # exit=0（提交前对已提交区间）
git diff --check                  # 工作树含证据 TSV：exit=0
```

---

## 类1 — 退役财政分流

### 定义边界
删除退役公式、标记及 shadow 平行路径和仅为它们存在的测试；复用现役 hub；不增加兼容或护栏。

### 成员与处置（全 6）
| 成员 | 处置 | 依据 |
|---|---|---|
| 注释「hub-only: cutover markers retired」×6 | **KEEP** | 仅文档注释；生产 cutover 谓词复扫 **0** |

### 结果
无残留退役分流实现。不以命中 6/0 单边洗白。

---

## 类2 — 持久职责泄漏与重复实现

### 定义边界
领域编排留领域；持久读写归既有 owner。合并双份 SQL，清退纯转发，调用方直接使用现有 Store。

### `c2_forward`（4）KEEP
`save_state` / `save_resolve_context` / `clear_resolve_context` / `close` — 领域适配或跨 Store / 连接关闭（同前序依据）。

### `c2_sql_leak_candidate`（9）KEEP
RejectionCollector owner CRUD；连接 `executescript`；PRAGMA/`sqlite_master`/可恢复性 `SELECT 1`。

### 结果
纯转发已清；剩余均有框架/owner/适配依据。

---

## 类3 — 被取代的孤立机制

### 定义边界
依实际退役关系清退遗留辅助链；不能仅因未引用删除仍属票面职责的待接接口。

### 成员（21）
禁摊派中和现役、Store upsert 原语、退役说明注释、测试 `reason_code` 取值 — **KEEP**；`_fail_cli_chat_turn_scene` / debug upsert / 旧坐实链生产复扫 **0**。

### 结果
无应删孤立机制残留。

---

## 类4 — 人口规则平行实现

### 定义边界
保留一个现役领域真源，删除复制件与旧名兼容。

### 枚举 376
领域真源唯一定义：`displaced_population.apply_levy_driven_transfers` / `apply_recovery_driven_transfers`；`apply_issue_inertia_and_ongoing` 复扫 0。同名 Store 读口 / 测试 helper — **KEEP**（非第二套公式）。

### 结果
单一领域真源。

---

## 类5 — 撤回的事务了结机制

### 定义边界
清退显式了结、拒绝该动作的守门及专用旧测试；不借修理新建自动了结。

### 复扫
`close_from_declaration` / `declare_closed` / `ATTACH_RESULT_CLOSE` / `birth_close` / `attach=close` = **0**。余 `c5_affair_close` 1：`materials.py:416` ADR 叙述 **KEEP**。

### 结果
显式了结与专用 close 拒收案已清；未建自动了结。

---

## 类6 — 测试契约边界处置错误

### 定义边界
复用已有最短行为用例承接必要结构化结果，清理非契约叙事锁和重复成本。不得靠删掉仍生效契约洗绿，不恢复措辞锁，不新增证明性测试。

### 全员覆盖（本轮补足）

| 指标 | 值 |
|---|---|
| 原始 enum `c6_string_lock` | **18293** |
| 合并同址 assert+compare 后唯一位点 | **10587** |
| `raw_enum_rows` 合计 | **18293**（=全覆盖） |
| NEED_REVIEW 残留 | **0** |
| 本轮 DELETE | **1**（见 deletes.tsv） |

证据表（入库）：

1. `evidence/1889-c6-member-disposition.tsv` — 每唯一位点：`disposition` / `basis` / `group_id` / `raw_enum_rows` / literals
2. `evidence/1889-c6-group-review.tsv` — 按 `源文件|处置族`：`line_range` + `member_count` + `raw_enum_rows_sum` + reason
3. `evidence/1889-c6-deletes.tsv` — 本轮真锁删除记录

### 处置族计数（唯一位点）

| disposition | count |
|---|---|
| KEEP_INPUT_FIDELITY | 6104 |
| KEEP_MACHINE_ID | 3544 |
| KEEP_SQL_SCHEMA | 486 |
| KEEP_STRUCT | 143 |
| KEEP_ENTITY_ID | 106 |
| KEEP_INJECTED_FAILURE | 74 |
| KEEP_UI_CHROME | 66 |
| KEEP_ENTITY_SEED | 28 |
| KEEP_MACHINE_FORMATTER | 13 |
| KEEP_MACHINE_ENUM | 12 |
| KEEP_STRUCT_EMPTY | 9 |
| KEEP_P4_ABSENCE | 2 |

### 入参来源判据（非长度自动）

| 来源 | 处置 | 依据形态 |
|---|---|---|
| 机器标识 | KEEP_MACHINE_* / SQL_SCHEMA | schema 键、状态枚举、路径前缀、gate 公式、度量键；对照生产符号/content seed |
| 测试自注入保真 | KEEP_INPUT_FIDELITY / INJECTED_FAILURE | 同函数 Assign/Call/Raise/parametrize/helper 注入后再读回 |
| 固定 UI | KEEP_UI_CHROME | P7 界面固定话语 / aria / 菜单选择器 |
| 非契约生产叙事·标题·报错锁 | **DELETE** | 本轮：rejection reason 含 `canonical target` 措辞锁 → 改结构化 COUNT |

**明确拒绝**：短汉字+英文不得仅因短/ASCII 自动 KEEP；无同函数注入且非闭集机器/实体 → 打开函数体审源后才落账。

### 本轮代码变更（类6相关）

1. **DELETE** `tests/test_decree_dossiers_571.py::test_mechanical_directive_missing_target_fails_loudly_at_real_entry` 对 production reason 的 `"canonical target"` 子串锁；改为与 `test_incomplete_mechanical_directive_is_rejected_instead_of_retyped` 同形的 section 计数断言。
2. **CLI fixture** `tests/test_cli_play_turn.py`：轻壳 `list_pending_actions` 改挂 `db.dossiers`（现役 Store），覆盖 review_directives / secret_order failure 路径。

### 残留探针
`AGENDA_FROZEN` / `关（codex` / `attach=close` / `close_from_declaration` / `birth_close` / `canonical target`（tests+web）= **0**。

### 变异取证
沿用前轮 scrollTop 红绿（`chatModal.tsx` 临时注释 → vitest 2 failed → 还原 34 passed）；本轮未再改该文件。

### 结果
全员有可回溯处置；不以抽查代替全清。结构化契约保留；真措辞锁已删。

---

## 聚焦测试（七变量前缀，无 `-k`）

```bash
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
MING_SIM_PI_BIN=/usr/bin/false
```

| 批次 | 命令摘要 | 实测 |
|---|---|---|
| touched | `pytest tests/test_cli_play_turn.py tests/test_decree_dossiers_571.py -q --tb=line` | **155 passed**；real 2.10s |
| core | 同前 core 11 文件 | **419 passed**；real 15.12s |
| more | 同前 more 23 文件 | **513 passed**；real 11.00s（前轮曾观察 4 failed：CLI dossiers 轻壳；本轮改 fixture 后绿） |
| web | vitest 6 组件文件 | **102 passed**；real 1.56s |

未跑全量。

### 红测观察（如实）
- 开工前 more 批曾见 `test_cli_play_turn` 4 红（`Db` 无 `dossiers` / `#42` 未打印）。**未**做基线同令取证，故不声称「非本票引入」。
- 归因到已删 facade 写口后，按类6把既有轻壳改到 `dossiers` Store；修后 more 全绿。不为绿扩 CLI 功能面。

---

## 自查二连

1. **合法性**：未改治理/角色包/交卷工具；未新建自动了结/证明测试/行数或全绿门槛；类5 close 案未复活；类6 全员映射入库；短汉未长度自动 KEEP；真锁 DELETE 未放松结构化结果断言。
2. **引入 bug**：CLI 轻壳仅补现役 `dossiers` 入口；decree 拒收断言改为 COUNT；变异文件未再触。
3. **边界**：c1–c5 按全定义复扫非样本零；不以「抽查无 DELETE」报类6完。

---

## 剩余范围 / 真实未结

- 整体复杂度对比仍归 #1812 / owner 家族收尾。
- 类6 全员已映射；若后续 enum 行号漂移须重跑 enumerate + 重对 disposition（本票证据表绑定当前 HEAD 代码行）。
- 不宣告合并、不关票、不 push、不开 PR。
