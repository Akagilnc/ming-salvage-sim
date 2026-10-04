# #1834 修内司回执：F3 / F14（全仓双向复查补证）

依据：fix-packet + 判词 `00-1834-judge-768cb88e1.json`；全局 #13 / 质量法；P7 射程（固定界面字段合法）。
禁止 amend/rewrite/push/PR/stash。**未合并，不声称关票。**

## 本提交相对上版回执的纠偏

上版 `f3_bidirectional_disposition.jsonl`（251 行）与 `report.md` **仅枚举本轮 purge delete-diff**，空壳复扫也只称触及面——**不足以满足全仓机械枚举 + 旧 KEEP 全表双向复查**。本提交不改正生产类、不新增平行机制；把枚举范围与语义处置补齐进新证据。

## 未结两类（判词边界）

1. **F3**：正文断言清理误删合法契约，并留下无效测试。须全仓机械枚举现存同类，并对照旧 `f3_disposition.jsonl` 全部 KEEP/FIX 双向复查。
2. **F14**：探针阶段标签冒称事务已关闭。纠正现行脚本标签与证据解释；不改写历史执行输出。

## 互联网现成方式（动手前）

pytest assert / bytes 相等：确定性夹具用 `assert actual == expected`；无断言空测不算测试。优先恢复/删除既有契约，不新造平行机制。

## F3 枚举范围（复用旧 enum，不新增分类器）

```sh
env \
  MING_SIM_AGY_BIN=/usr/bin/false \
  MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false \
  MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false \
  MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD \
  ../Ming_LLM/.venv/bin/python \
  evidence/1834-fixer-f9-f12-f3/scripts/enum_f3_free_text_asserts.py
```

| 机械集 | 成员数 | 证据 |
| --- | ---: | --- |
| 现行 free-text assert enum（tests+web test） | 1923 | `enum_f3_current.txt` |
| 旧 disposition 全表双向（KEEP+FIX） | 1979 | `f3_full_bidirectional_disposition.jsonl` / `OLD_*_BIDIR` |
| 其中 KEEP 确认仍在 | 1911 | `KEEP_CONFIRMED` |
| 其中旧 FIX | 68 | 66 合法删除保留；2 误分类已恢复 |
| purge delete-diff 叠加（自由正文仍删） | 231 | `PURGE_DELETE_DIFF_OVERLAY`；旧短表 `f3_bidirectional_disposition.jsonl` |
| 已恢复合法契约 | 12 | `RESTORED_LEGAL_CONTRACT` |
| 已删空壳用例 | 7 | `EMPTY_SHELL_DELETED`（已核 gone） |
| 全仓无 assert 语义扫描 | 7 | `FULLREPO_NO_ASSERT_SCAN`：0 空壳候选；2 helper；5 no-throw |
| evidence/scripts 探针 | 6 | `f3_probe_enum.jsonl`：0 散文 assert；6 stage `check()` |
| 去掉长度替代 | 1 | `REMOVE_LEN_SUBSTITUTE` |

**规范成员表**：`f3_member_table.md`
**规范处置真源**：`f3_full_bidirectional_disposition.jsonl`（2244 行；含上表各 member_set）
**不伪称**：旧短表 251 行 delete-diff ≠ 全仓；本回执以全表为准。

### 语义处置（非词形自动分类）

- **KEEP_CONFIRMED (1911)**：旧 KEEP 逐条对照现行文件，全部仍在。
- **RECLASS_RESTORE (2)**：旧 FIX 误标——`scene_llm` 调用输入、`due_review` criterion/origin 结构化字段 → 已恢复。
- **KEEP_DELETED_FREE_PROSE**：旧 FIX 中 66 + purge 叠加 231；生成/夹具自由正文锁，不机械恢复。
- **RESTORE_*** (12)**：调用输入 / 磁盘原文 / 身份 / periodLabel / 结构化 DTO；文件核验 present=True。
- **DELETE_EMPTY_SHELL (7)**：失去行为证明的空壳；核验 gone=True。
- **FULLREPO_NO_ASSERT_SCAN (7)**：全仓 AST 无 assert；语义判定均非空壳（helper / no-throw 契约），**不因「无 assert 词形」误删**。
- **EVIDENCE_SCRIPTS_PROBE (6)**：仓内现存结构探针 stage 调用；无散文断言依赖。

### 旧 FIX 误分类恢复（样本，非白名单）

- `tests/test_scene_llm_1836.py`：`assert calls == [宣…, "边饷如何？"]`
- `tests/test_due_review_621.py`：`origin_context` / `criterion_text`
- 另有 material 磁盘字节、web 身份与 periodLabel（见成员表）

未恢复生成散文；未加长度/非空替代；未新造平行测试或生产机制。

## F14 阶段标签（机械枚举）

```sh
rg -n '\b(OPEN_WORLD|OPEN_PUBLIC|CLOSED_WORLD|CLOSED_PUBLIC|CALENDAR_ADVANCED_WORLD|CALENDAR_ADVANCED_PUBLIC|RESTORE_WORLD|RESTORE_PUBLIC)\b' evidence scripts
```

| 处置 | 数 | 说明 |
| --- | ---: | --- |
| HISTORICAL_OUTPUT_UNCHANGED | 4 | 旧 `probe.txt` / `1834-fixer-f9-f12-f3/probe-current.txt` 中 `CLOSED_*`：**不改写** |
| CORRECT_LIVE_LABEL | 14 | 现行脚本与新证据使用 `CALENDAR_ADVANCED_*` |
| STAGE_LABEL_OK | 44 | `OPEN_*` / `RESTORE_*` |
| NEW_EVIDENCE_MENTION_CLOSED | 8 | 新证据文档提及历史 `CLOSED_*`（非 live 标签） |
| 合计 token 命中 | 70 | `f14_stage_labels.jsonl`（范围见 `f14_enum_scope.txt`；排除 disposition/enum 自反馈） |

- 脚本 `evidence/1834-fixer-f9-f12-f3/scripts/probe_f9_f12_structural.py`：日历推进阶段标签为 `CALENDAR_ADVANCED_*`，**不得**读作 `affair_status=closed`。
- 历史执行输出中的 `CLOSED_*` 保留；解释以本回执与 `f14_stage_labels.jsonl` 为准。
- 生产关闭读取有效性维持前判；本片不新增关闭机制。

完整标签行：`f14_stage_labels.jsonl`（再跑后与 report 交叉；以该 jsonl + 成员表 F14 节为准）。

## 聚焦测试（七 BIN；非全量）

```sh
env \
  MING_SIM_AGY_BIN=/usr/bin/false \
  MING_SIM_CODEX_BIN=/usr/bin/false \
  MING_SIM_CLAUDE_BIN=/usr/bin/false \
  MING_SIM_CURSOR_BIN=/usr/bin/false \
  MING_SIM_KIMI_BIN=/usr/bin/false \
  MING_SIM_GROK_BIN=/usr/bin/false \
  MING_SIM_PI_BIN=/usr/bin/false \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=$PWD \
  ../Ming_LLM/.venv/bin/python -m pytest -q \
    tests/test_scene_llm_1836.py \
    tests/test_material_directory_1830.py \
    tests/test_due_review_621.py \
    tests/test_audience_restore_505.py \
    tests/test_cli_runner_error_typed_1299.py \
    tests/test_decree_commitment_settlement_229.py \
    -p no:cacheprovider --basetemp=/tmp/1834-fixer-f3-f14-mut/pytest-focus
```

结果见 `focused-pytest.txt`。

Web vitest：本树无 `web/node_modules`。只读 symlink 借用 `Ming_LLM-1901-w5/web/node_modules`（vitest 4.1.9 + `--environment jsdom`），跑后删除 symlink，**未安装、未改宿主**。
结果（`focused-vitest.txt`）：**5 files / 139 passed**，wall **real 4.20s**。
其间发现 `#1849` 密令召见用例在 purge 后留下排除 `.thinking` 的 DOM 等待（假证明）；已去掉失效 DOM 等待，保留 `宣`/非 `/api/ministers`/stream 路由断言。

## 探针复跑

`probe-current.txt`：须见 `OPEN_*` / `CALENDAR_ADVANCED_*` / `RESTORE_*`；不得出现新的 `CLOSED_*` 标签。

## 复杂度 / 合法性

- 无新增来源账、摘要、模型调用、输出擦洗、生产出口。
- 邻票 #1873 不施工。
- 不重开已结生产类（F9/F12 等）。
- 自查二连 done。

## 剩余范围

- #1873 邻票文字事实来源缺口。
- 同进程顺序污染（前轮已记）— 另票。
- 分支未合并 → **不声称 #1834 关闭**。
- 御史台：本轮触及此前 P1 生产修复之后的 P2/P3 证据面；台院条件仍依判词。
