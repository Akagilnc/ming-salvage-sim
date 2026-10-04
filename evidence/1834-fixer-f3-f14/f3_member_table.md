# F3/F14 member table — NEEDS_CONTEXT 全量形状归类结清

依据：冻结判词 `1834-judge-768cb88e1.json`。
**本局授权**：原 `KEEP_NEEDS_CONTEXT_NOT_AUTO` 1388 **不得另派**；已按文件上下文错误形状归类完毕。

## 谓词纠偏（仍有效）

| 上版问题 | 纠正 |
| --- | --- |
| `is_prose` + tests/web only | 全仓 `ast.Assert` + JS expect（见 `enum_predicate_correction.txt`） |
| F14 八标签 + evidence/scripts | 全仓关闭/阶段 token（`f14_full_candidates.jsonl`） |
| STILL_PRESENT + 复制 old_basis | 形状/上下文语义；拒 still-present / old_basis 确认 |

## F3：原 1388 + 残余旗标 / FIX presence / no_assert

复现：

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
  MING_ENUM_ROOT=$PWD MING_ENUM_OUT=$PWD/evidence/1834-fixer-f3-f14 \
  ../Ming_LLM/.venv/bin/python evidence/1834-fixer-f3-f14/scripts/context_dispose_needs.py
```

全表：`f3_needs_context_disposed.jsonl`  
共同判据账本：`f3_needs_context_class_ledger.json`  
覆盖核：1388 path:line **missing=0**。

### 按 class_id 映射（成员→共同判据；同根因一类）

| class_id | action | 数 | 共同判据 | 样本指针 |
| --- | --- | ---: | --- | --- |
| C_STRUCT_FIELD | KEEP_STRUCTURED_IDENTITY | 332 | LHS=DTO/DB/枚举/身份字段；字面量为夹具/枚举，非 LLM 散文 | `tests/test_appointment_tenure_607.py:64` 任别==真除 |
| C_NEGATIVE | KEEP_NEGATIVE_OR_PERMISSION | 319 | 否定/权限/密令隔离 | `tests/test_audience_background.py:212` 密令 in failures.message |
| C_FIXED_UI | KEEP_FIXED_UI_OR_PERIOD | 295 | 固定 UI/时期/设置（P7 界面固定话语） | `web/src/components/modals.test.tsx:970` 便殿·戌时 |
| C_ERROR | KEEP_ERROR_CODE | 258 | 固定错误/拒绝/reason | `tests/test_applier_contract.py:155` 军队 id 不存在 |
| C_WEB_STRUCT | KEEP_WEB_STRUCTURAL | 111 | DOM/API/路径/布尔/焦点 | `web/src/components/gameMenu.test.tsx:299` select value high |
| C_DET_INPUT | KEEP_DETERMINISTIC_CALL_INPUT | 99 | 玩家/调用输入或 HITL 原样 | `tests/test_audience_restore_505.py:144` 杨卿何以教朕？ |
| C_PATH | KEEP_PATH_OR_DIRECTORY | 63 | 材料路径/目录/结构键 | `tests/test_world_materials_1834.py:266` 邸报/…路径 |
| C_FIX_PRESENCE_FP | KEEP_DELETED_FREE_PROSE_OK | 19 | 旧 FIX 散文已删；当前行漂移/合法非散文 | `tests/test_textual_facts_1828.py:71` |
| C_TRANSPARENT | KEEP_TRANSPARENT_TRANSPORT | 17 | 夹具写入→读回 | `tests/test_character_knowledge_489.py:479` body==该案已奉明发（record_public 种子） |
| C_SCAN_FP | KEEP_SCANNER_FALSE_POSITIVE | 14 | no_assert 扫描假阳 | `web/src/styles.test.ts:110` 有 expect |
| C_NO_THROW | KEEP_NO_THROW_SMOKE | 1 | 不抛即过 | `tests/test_llm_channel_config.py:591` empty content passes |
| C_NUMERIC | KEEP_NUMERIC_OR_BOOL_CONTRACT | 1 | 数值/布尔结构 | `tests/test_start_sh_deps_1721.py:105` |
| C_DELETE_* | — | **0** | 本轮无新删 | — |

旗标手核 70（上版 `f3_hand_flagged_disposition.jsonl`）仍有效；未入手旗标已并入上表。

### 恢复契约 / 空壳

| 集 | 数 | 状态 |
| --- | ---: | --- |
| RESTORED_LEGAL_CONTRACT | 12 | present |
| EMPTY_SHELL_DELETED | 7 | gone |

## F14：全仓候选处置

全表：`f14_full_disposed.jsonl`；摘要：`f14_full_dispose_summary.json`（2323）。

| disposition | 数 | 历史 vs 现行 |
| --- | ---: | --- |
| WIDENED_PREDICATE_NOISE | 1232 | 加宽噪声，非阶段标签 |
| RESTORE_OPEN_WORDING_NOT_STAGE | 753 | 叙述命中 |
| CLOSE_TOKEN_IN_COMMENT_OR_DOC | 252 | 注释/文档 |
| LIVE_OR_DOC_OPEN_RESTORE_LABEL | 32 | 现行/文档 OPEN_*/RESTORE_* |
| LIVE_LABEL_CORRECT_CALENDAR_ADVANCED | 18 | **现行正确**：日历推进 |
| PROD_OR_TEST_REAL_CLOSE_QUERY | 17 | 真关闭查询（非探针冒称） |
| HISTORICAL_FREEZE_RETAIN | 12 | **历史冻结不改写**（含旧 probe `CLOSED_*` 与文档指针） |
| F14_OTHER_TOKEN | 7 | 其它 |

历史冻结（stdout 不改写）：

- `evidence/1834-fixer-f9-f12-f3/probe.txt:13–14` `CLOSED_WORLD/PUBLIC`
- `evidence/1834-fixer-f9-f12-f3/probe-current.txt:16–17` `CLOSED_WORLD/PUBLIC`

现行纠正：

- `evidence/1834-fixer-f9-f12-f3/scripts/probe_f9_f12_structural.py:220/225` `CALENDAR_ADVANCED_*`
- `evidence/1834-fixer-f3-f14/probe-current.txt:4–5` `CALENDAR_ADVANCED_*`

## 本轮代码变更

**无生产机制变更；无测试行为变更。** 仅证据归类结清（脚本 + jsonl + 回执）。
旧 `KEEP_NEEDS_CONTEXT_NOT_AUTO` 状态废作「未读剩余」；范围主张以本表 + `f3_needs_context_disposed.jsonl` 为准。
