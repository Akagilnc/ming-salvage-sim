# #1834 修内司回执：F3 / F14（NEEDS_CONTEXT 全量形状归类结清）

依据：fix-packet + 冻结判词 `00-1834-judge-768cb88e1.json`（vault: `1834-judge-768cb88e1.json`）；全局 #13 / 质量法；P7 射程。
禁止 amend/rewrite/push/PR/stash。**未合并，不声称关票。**

## 本提交相对上版回执

上版将 `KEEP_NEEDS_CONTEXT_NOT_AUTO` **1388** 标为「另派」——**违背本局全仓复查授权**（用户明示：1388 不得另派/当剩余）。

本提交：对 1388 + 未入手旗标 + FIX presence 假阳 + no_assert 扫描命中，**按文件上下文错误形状批量语义归类**，成员映射至共同判据（`class_id`）；拒 old_basis / still-present / 纯词形确认。
**无生产类代码改动**；未发现须再删的生成散文锁或新空壳；合法契约 12 / 空壳 7 仍 verified。

临时工作：`/tmp/1834-fixer-f3-f14-context-dispose/`；复现脚本：`evidence/1834-fixer-f3-f14/scripts/context_dispose_needs.py`。

## 未结两类（判词边界）— 本座处置

1. **F3**：正文断言清理误删合法契约，并留下无效测试。须全仓机械枚举现存同类，并对照旧 disposition KEEP/FIX 双向复查 → **本座完成 1388 上下文归类 + 旗标/FIX/空壳复核**。
2. **F14**：探针阶段标签冒称事务已关闭。纠正现行脚本标签与证据解释；不改写历史执行输出 → **全仓 2323 候选已区分历史冻结 / 现行日历标签 / 加宽谓词噪声**。

## 互联网现成方式（动手前）

pytest assert / bytes 相等：确定性夹具用 `assert actual == expected`；无断言空测不算测试。优先恢复/删除既有契约，不新造平行机制。

## F3 结算

### 机械枚举规模（上版谓词纠偏仍有效）

| 机械集 | 成员数 | 证据 |
| --- | ---: | --- |
| Python `ast.Assert`（无文字过滤） | 13564 | `enum_f3_all_py_asserts.jsonl` |
| JS/TS expect/assert/check | 1602 | `enum_f3_js_expect_assert_check.jsonl` |
| Python / JS no_assert 扫描 | 7 / 8 | `enum_f3_*_no_assert_tests.jsonl` → 上下文后多为扫描假阳或 no-throw 烟测 |
| 旧 KEEP / FIX | 1911 / 68 | 语义复核表 |

### 原 1388 NEEDS_CONTEXT — 本座全量归类（不得另派）

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

| 产物 | 说明 |
| --- | --- |
| `f3_needs_context_disposed.jsonl` | 每成员 → `class_id` + action（覆盖全部 1388 path:line） |
| `f3_needs_context_class_ledger.json` | 共同判据 + 样本指针 + 路径计数 |
| `f3_member_table.md` | 规范成员表 |

**处置合计**（含 1388 + 未入手旗标 + 19 FIX presence 假阳 + no_assert 扫描）：

| action | 数 | 合法依据（摘要） |
| --- | ---: | --- |
| KEEP_STRUCTURED_IDENTITY | 332 | DTO/DB/枚举/身份字段 |
| KEEP_NEGATIVE_OR_PERMISSION | 319 | 否定/权限/密令隔离 |
| KEEP_FIXED_UI_OR_PERIOD | 295 | 固定 UI / 时期 / 设置文案（P7 界面固定话语） |
| KEEP_ERROR_CODE | 258 | 固定错误/拒绝/reason |
| KEEP_WEB_STRUCTURAL | 111 | DOM/API/路径/布尔/焦点结构 |
| KEEP_DETERMINISTIC_CALL_INPUT | 99 | 玩家/调用输入或 HITL 原样 |
| KEEP_PATH_OR_DIRECTORY | 63 | 材料路径/目录结构 |
| KEEP_DELETED_FREE_PROSE_OK | 19 | 旧 FIX 自由正文已删；presence 假阳 |
| KEEP_TRANSPARENT_TRANSPORT | 17 | 夹具写入→读回相等 |
| KEEP_SCANNER_FALSE_POSITIVE | 14 | no_assert 扫描假阳 |
| KEEP_NO_THROW_SMOKE | 1 | 故意无 assert：不抛即过 |
| KEEP_NUMERIC_OR_BOOL_CONTRACT | 1 | 数值/布尔结构 |
| **DELETE_\*** | **0** | 本轮未见须再删的生成散文锁或新空壳 |

**方法诚实**：按 LHS/上下文窗口形状归类并映射共同判据；**不是**对每条 assert 正文做文学细读。拒 old_basis 自动确认。

### 既有恢复 / 空壳（复核仍成立）

| 集 | 结果 |
| --- | --- |
| 已恢复合法契约 12 | 全部 present（scene_llm / material_directory / due_review / web period·身份） |
| 已删空壳 7 | 全部 gone |
| `剿抚孰先？` 多行 assert | KEEP_DETERMINISTIC_CALL_INPUT（presence 假阴已在手核） |
| `extract_agent_text('臣领旨。')` | 随空壳区删除；不恢复 |

旧 FIX：自由正文删除仍成立（19 presence 假阳已核为行漂移/合法非散文）；误分类恢复 2 条仍在。

## F14 结算（全仓 2323）

| disposition | 数 | 说明 |
| --- | ---: | --- |
| WIDENED_PREDICATE_NOISE | 1232 | 加宽 close 词噪声；非探针阶段标签 |
| RESTORE_OPEN_WORDING_NOT_STAGE | 753 | 「恢复/开放」叙述 |
| CLOSE_TOKEN_IN_COMMENT_OR_DOC | 252 | 注释/文档/测试中的 close 用语 |
| LIVE_OR_DOC_OPEN_RESTORE_LABEL | 32 | OPEN_*/RESTORE_* |
| LIVE_LABEL_CORRECT_CALENDAR_ADVANCED | 18 | 现行 `CALENDAR_ADVANCED_*` |
| PROD_OR_TEST_REAL_CLOSE_QUERY | 17 | 真 `declare_closed` / `affair_status` 查询 |
| HISTORICAL_FREEZE_RETAIN | 12 | 历史输出/文档指针；**不改写** |
| F14_OTHER_TOKEN | 7 | 其它加宽命中 |

证据：`f14_full_disposed.jsonl` + `f14_full_dispose_summary.json`。
历史 stdout（不改写）：`evidence/1834-fixer-f9-f12-f3/probe.txt` / `probe-current.txt` 中 `CLOSED_*`。
现行探针：`CALENDAR_ADVANCED_*`（`probe_f9_f12_structural.py`）；本目录 `probe-current.txt` 已为正确标签。

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
    -p no:cacheprovider --basetemp=/tmp/1834-fixer-f3-f14-context-dispose/pytest-focus
```

结果：`focused-pytest.txt` → **95 passed**。

Web vitest：本轮无 web 行为改动；不强制重跑。

## 复杂度 / 合法性

- 无新增来源账、摘要、模型调用、输出擦洗、生产出口、平行生产枚举机制。
- 邻票 #1873 不施工。
- 不重开已结生产类（F9/F12 等）。
- 自查二连 done。

## 剩余范围（真缺口，非 1388）

- #1873 邻票文字事实来源缺口。
- 同进程顺序污染（前轮已记）— 另票。
- 分支未合并 → **不声称 #1834 关闭**。
- **本局授权范围内的 1388 NEEDS_CONTEXT：已结清，不另派。**
