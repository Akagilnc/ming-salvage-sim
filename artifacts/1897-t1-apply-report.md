# #1897 T1 apply 回执（补修：纠正 467625a91／59d1c0ac2）

- **角色**：修内司（ak-roles fixer）
- **工作树**：`/Users/akagilnc/WorkSpace/Ming_LLM-1897-w5`
- **分支**：`ak-roles/issue-1897-k1-k2-f3-fixer-20261005-115628`
- **新判词真源**：`artifacts/1897-t1-review-input.json`
- **末附件末 payload**：`~/.ak-roles/books/Ming_LLM/1897/runs/01a109fb-df35-7bb6-936d-039433dd815c@fixer/attachments/04-1897-judge-21651f2d0.json`（evidence：`style before/after不是结构身份`）
- **范围**：纠正 T1 上轮非法修法；**K1/K2 不动生产**。
- **禁止项**：无 amend／stash／rewrite／push／PR；七变量 BIN=/usr/bin/false；不全量；不真模型；不改法。

**不宣称 merge 或关票。**

---

## 上轮非法修法（如实纠正）

`467625a91`（`59d1c0ac2` 仅 pin 本回执 seal）为填 641 变异红，恢复 `_style_row` before／after 等值／不等值，把自由 `style` 正文说成「列身份」。这正是末判 F3 evidence 点名禁止的换形（`style before/after不是结构身份`）。T1 direction 不恢复 LLM 生成正文逐字锁；不能为变异红恢复正文比较。本轮按行为语义整案删除该修法，不另造替代证明体系，不改名伪装。

---

## 判词要点（仍适用）

T1：要么最短结构化断言（含静态资产身份分桶闸），要么删失去独立契约的壳；不得键在／非空／len／strip／before-after 散文充数；闸类负向不得误删；不恢复正文逐字锁。

---

## 成员处置（本轮补修后）

### `tests/test_featured_dossiers_494.py` — **静态身份闸：合法保留**

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_every_active_seven_faction_minister_has_featured_dossier` | **保留** | 静态资产字段须入 `minister_dossier` |
| `test_seven_faction_dossiers_are_objective_and_identity_scoped` | **保留** | identity 分桶闸：`internal not in middle/low`；core/agenda 分桶；P4 裸数负向 |
| `test_north_star_ministers_have_distinct_featured_voices` | **保留** | 静态 voice 字段入 dossier 且 dossier⊆full |

### `tests/test_style_temperament_641.py`

| 成员 | 处置 | 依据 |
|---|---|---|
| `test_inertia_natural_resolve_applies_temperament_style` | **整案删除** | 宣称 style 写入；仅日志／before-after 皆不足／非法；不另造正向 style 证明 |
| `test_apply_score_extraction_writes_temperament_style_and_log` | **整案删除** | 同上：正向 style 证明壳 |
| `test_temperament_outer_tx_rollback_restores_db_and_runtime` | **整案删除** | reload/rollback style 专属壳；日志计数对 reload 恒真 |
| `test_temperament_committed_style_survives_reload` | **整案删除** | 同上 |
| `test_temperament_blank_style_rejected_keeps_prior` | **保留（削 style 比较）** | `rejected`／`category`＋未写性情日志 |
| `test_apply_score_extraction_rejects_invalid_temperament` | **保留（削 style 比较）** | `rejected`／`category`／applied 结构＋未写日志 |
| `test_relation_edge_events_do_not_mutate_style` | **保留（削 before/after）** | 落边＋性情日志水位不变；不比 style 列 |
| `test_temperament_does_not_write_relation_edges` | **保留（削 style 比较）** | 边表水位不变＋性情日志＋1 |
| `test_character_context_with_db_reads_own_style_and_viewer_ledger` | **删除维持** | 所称消费者未调用 |
| `_style_row` helper | **删除** | 仅为非法 before/after 服务 |

### `tests/test_relation_brew_636.py`（467625 新增填料清理）

| 成员 | 处置 | 依据 |
|---|---|---|
| consecutive／flip／failed 前 `is not None` 填料 | **删除** | 字段访问已会失败；`is not None` 非法充数 |
| parallel／batch `get_relation_summary is not None` | **保留** | 摘要行写入=独立结构契约 |
| `dimension`＋`last_event_id` 水位 | **保留** | 真结构化契约 |
| `test_brew_persistence_chain_accepts_large_recent_segment` | **删除维持** | 无独立可结构化契约 |

### 其它 T1 削壳（本轮复核，未再造）

| 文件 | 处置 |
|---|---|
| scene／highlight／audience_restore 等删 strip | **维持**；保留调用次数／事件类型／chat_turn_id 等结构 |
| opening `previous_summary==""`、seed `recent_segment==""`、六科《明史》卷258 | **保留**（静态／空闸，非 LLM 正文锁） |
| month_call `call_failure.kind/escape_armed` | **保留** |
| Web `data-audience-turn-id`／节点结构 | **保留** |

---

## 聚焦测试

前缀：七变量 `MING_SIM_*_BIN=/usr/bin/false` + `PYTHONDONTWRITEBYTECODE=1`。

```bash
../Ming_LLM/.venv/bin/python -m pytest -q -p no:cacheprovider --tb=line \
  --basetemp=/private/tmp/1897-t1-rework-focus \
  tests/test_featured_dossiers_494.py \
  tests/test_style_temperament_641.py \
  tests/test_relation_brew_636.py \
  tests/test_relation_seed_638.py \
  tests/test_relation_read_640.py \
  tests/test_scene_llm_1836.py \
  tests/test_six_sciences_seed_608.py \
  tests/test_opening_gazette_delete_1356.py
```

输出：`94 passed, 1 warning in 4.58s`

未为已删无契约案再造变异证明。未跑全量／真模型。

### 自查二连

- 同类型：全仓扫 `467625a91` 新增 `_style_row`／style before-after；仅 641 曾引入，已整清。494 静态分桶闸保留。brew 填料 `is not None`（字段访问前）已删；摘要行写入 `is not None` 保留。
- 引入 bug：未改 `ming_sim/`；未改名伪装正向壳；未新增平行证明。

---

## 残留项

- K1／K2：不动生产。
- 不宣称 T1 已由御史台／大理寺复审结清。
- 历史提交 `467625a91`／`59d1c0ac2` 不 amend；以本 commit 纠正。

---

## Seal

```text
branch=ak-roles/issue-1897-k1-k2-f3-fixer-20261005-115628
parent_illegal_fix=467625a91619c92efaa8ee186d935cd02c9606dd
focused=94 passed in 4.58s（八文件＋highlight＋structured_decree）
生产 ming_sim/：无改动
未 push／未开 PR／未关票
```
