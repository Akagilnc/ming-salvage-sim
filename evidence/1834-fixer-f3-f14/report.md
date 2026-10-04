# #1834 修内司回执：F3 / F14（语义实读结清 1388）

依据：fix-packet + 冻结判词 `00-1834-judge-768cb88e1.json`；全局 #13 / 质量法；P7 射程。
禁止 amend/rewrite/push/PR/stash。**未合并，不声称关票。**

## 对本局先前错误的纠正

前版用 `scripts/context_dispose_needs.py` / `semantic_keep_review.py` 对 `KEEP_NEEDS_CONTEXT_NOT_AUTO` **1388** 做 regex 词形 + ±10 行机械 classify，并据此声称「已结清」。

**该输出不构成判词所要语义双向复核。已删除自动结清脚本与伪结清声明**（见 `bd49e5ec8`）。

**保留无过滤枚举真源（机器只做枚举，不做决定）：**

- `enum_f3_all_py_asserts.jsonl`（13564）
- `enum_f3_js_expect_assert_check.jsonl`（1602）
- `enum_f3_*_no_assert_tests.jsonl`
- `f14_full_candidates.jsonl`（2323）
- `scripts/enum_full_candidates.py`

## 未结两类（判词边界）→ 本轮处置

1. **F3**：正文断言清理误删合法契约，并留下无效测试。须对照真实输入/输出来源双向复查。
   - 前序：`ea2a01556` 已按实读恢复透明传输；非法生成锁维持删除；空壳已恢复或删除。
   - **本轮**：对原 1388 `KEEP_NEEDS_CONTEXT_NOT_AUTO` **按文件打开源码实读**，共享契约判据分类记账；**未读剩余 = 0**。
   - 结果：1388 全部 KEEP（T_TRANSPARENT 695 / T_STRUCT 579 / T_DET_INPUT 90 / T_NEG_FIXTURE 24）；本轮无新增 DELETE（成员集中未再发现非法生成锁或空壳）。
2. **F14**：探针阶段清除冒称。生产侧日历标签纠正仍保留；历史 stdout（`CLOSED_*`）不改写。现行 `CALENDAR_ADVANCED_*` 见 `probe-current.txt`。

## 证据文件

| 文件 | 作用 |
| --- | --- |
| `f3_needs_context_semantic_disposed.jsonl` | 1388 条逐条处置 |
| `f3_needs_context_read_log.md` | 实读文件清单 + 共同判据 |
| `f3_needs_context_semantic_summary.json` | 计数摘要 |
| `f3_needs_context_remaining.txt` | 未读列表（空） |
| `f3_member_table.md` | 成员表 |
| `probe-current.txt` | F14 现行标签 |

## 复杂度 / 合法性

- 无新增分类机制、来源账、摘要、模型调用、输出擦洗、生产出口。
- 邻票 #1873 不施工；不重开已结生产类（F9/F12 等）。
- 自查二连 done。

## 聚焦验证（七 BIN；非全量）

`focused-pytest.txt` → **327 passed**（触及透明传输 / 材料目录 / 召对恢复 / 年号标签等样本）。
`focused-vitest.txt` → **6 files / 135 passed**（`--environment jsdom`：staleGuard / modals / situation / ministerScrollLens / decisionModal / drawers）。

## 关票声明

分支未合并 → **不声称 #1834 关闭**。
