# #1897 D1/D2/D3 修内司回执

- 施工分支：`ak-roles/issue-1897-n5-fix-d123`
- 施工前 HEAD：`874b85adf4eb15985ff88430511338360add5536`
- 判词 base：`0ca77fecc402b67829da5310fdf0cf76d624249d`
- 派单：`01a0facf-8530-76ee-8b30-a2282bf8eed7@fixer`
- 冻结判词：`attachments/00-1897-judge-874b85adf.json`
- 未 push / 未开 PR / 未 amend / 未 stash

## 各类根因

| 类 | 根因 | 处置 |
|---|---|---|
| D1 | 搬迁后生产未净减；被替代实现仍并存 | 删散文解析整段；`capture` 收成 `stages_to_json` 薄包装；`db` 交办缝去掉重复捕获、只透传显式 stages；暂存口改 `normalize` |
| D2 | 结案奏报正文回填执行格（跨轨旧兜底） | `close_secret_order` 不再用 `close_text` 填 `execution_note`；`settle_due_secret_orders` 显式传 `verdict["note"]` |
| D3 | 生产散文年诺捕获 + 坏结构回落正文；#620 P4／DELTA_SCHEMA 旧约锁定 | 删除 `parse_staged_year_promise` 等；只认显式结构化 stages；同步撤销 #620 P4／AC2 与 DELTA_SCHEMA 捕获条款 |

## 全仓枚举

命令与成员表见同目录 `enumeration.txt`。

### D2 成员表

| 成员 | 处置 |
|---|---|
| `ming_sim/db.py` `close_secret_order`：`close_text if execution_note is None` | **清退**：缺省写 `""`，不回填奏报 |
| `ming_sim/covert_progress.py` `settle_due_secret_orders` 未传 `execution_note` | **清退**：传 `execution_note=verdict["note"]` |
| `ming_sim/db.py` 人物离场结案（已 `execution_note=reason`） | **保留**：双轨已分写（result=奏报，note=实况原因） |
| `player_facing_secret_order_close_text` | **保留**：只写密令 `result` 奏报轨，不再进执行格 |

### D3 成员表

| 成员 | 处置 |
|---|---|
| `parse_staged_year_promise` / `_STAGE_YEAR_RE` / `_cn_years_to_int` / `_CN_YEAR_DIGITS` | **删除** |
| `capture_commitment_stages` 散文／narrative 回落 | **清退**：薄包装 `stages_to_json`，只吃显式结构 |
| `action_materialize` 坏 stages→正文年诺 try/except | **清退**：改 `normalize_commitment_stages` |
| `db._apply_assignment_verdict_effect` 重复 capture+narrative | **清退**：只透传显式 stages，捕获单口在 issues |
| `issues.py` 两处 capture（校验+落库） | **保留**：结构化响亮校验／落段；已去掉 narrative_text |
| `docs/DELTA_SCHEMA.md` scripted 年诺条款 | **同步撤销** |
| `#620` P4／AC2 捕获条款 | **同步撤销**（`gh issue edit 620`） |
| `normalize_commitment_stages` / `stages_to_json` / 到期扫描读口 | **保留**：显式结构化载体（ADR0074） |

## 生产行数

详见 `line-counts.txt`。

- 判词原 18 文件：base 52847 → 施工前 52940（+93）→ 现 52919（相对 base +72；相对施工前 −21）
- **含 D3 真源 `staged_commitment.py` 的票面生产 19 文件**：base 53267 → 施工前 53360 → **现 53216（相对 base −51；相对施工前 −144）**
- `staged_commitment.py`：420 → 297（−123）

## 旧路核销

- [x] 奏报 `result`/`close_text` → 执行格 `execution_note` 兜底已断
- [x] 到期结案写口改走实况 `verdict["note"]`
- [x] 散文年诺解析符号与调用全仓清零
- [x] 坏结构回落正文路径删除
- [x] #620 P4／AC2 与 DELTA_SCHEMA 旧捕获约同步撤销
- [x] 未新增证明性测试／护栏／机制

## 聚焦自验

前缀：`env MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false`

命令（与判词同清单）：

```
.../Ming_LLM/.venv/bin/python -m pytest \
  tests/test_secret_order_declaration_landing_1897.py \
  tests/test_audience_translate_1837_reopen.py \
  tests/test_secret_order_monthly_progress_566.py \
  tests/test_secret_order_payoff_1504.py \
  tests/test_execution_pressure_654.py \
  tests/test_decree_dossiers_571.py \
  tests/test_deformation_dual_rail_622.py \
  tests/test_dossier_reported_progress_619.py \
  tests/test_due_review_621.py \
  tests/test_secret_order_section_rejections.py \
  tests/test_world_materials_1834.py \
  -q -p no:cacheprovider --tb=short
```

结果（`focused-pytest.txt`）：**1 failed, 342 passed in 7.71s**（real 8.14s）。
失败同判词保留项：`test_path1_conversational_draft_bad_roster_marks_failed` 名册 `ValueError`——御史台 C1/N5，归 #1873，本轮不修。

## 旧逻辑变异入口观察

`observe-d2-d3.txt`：

- D3：散文「三年…五年…」→ `ValueError`（不落段）；显式 `due_turn=3` 保留
- D2：`close_secret_order` 源码无 `close_text if execution_note`；settle 传 verdict note；奏报与 machine note 分轨

## 残留功能范围（#1873）

- 幻觉参与人阻断同批提交（C1/N5）——聚焦红灯仍在，不冒称已修
- 结案玩法完整接线／准宽限等历史玩法——本票不补
- 分段玩法扩展（到期复核场面、财政分期等）——仍归 #621/#705，本票不扩

## 基础设施失败

无。
