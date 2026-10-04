# #1834 修内司回执：F3 / F14（撤自动结清；按实读处置）

依据：fix-packet + 冻结判词 `00-1834-judge-768cb88e1.json`；全局 #13 / 质量法；P7 射程。
禁止 amend/rewrite/push/PR/stash。**未合并，不声称关票。**

## 对本局先前错误的纠正

前版用 `scripts/context_dispose_needs.py` / `semantic_keep_review.py` 对 `KEEP_NEEDS_CONTEXT_NOT_AUTO` **1388** 做 regex 词形 + ±10 行机械 classify（例如凡 `not in`/`not.to` 即 `KEEP_NEGATIVE`），并据此声称「已结清」。

**该输出不构成判词所要语义双向复核。已删除：**

- `scripts/context_dispose_needs.py`
- `scripts/semantic_keep_review.py`
- `f3_needs_context_disposed.jsonl` / `f3_needs_context_class_ledger.json`
- `f14_full_disposed.jsonl` / `f14_full_dispose_summary.json`
- 一切「1388 已结清」声明

**保留无过滤枚举真源（机器只做枚举，不做决定）：**

- `enum_f3_all_py_asserts.jsonl`（13564）
- `enum_f3_js_expect_assert_check.jsonl`（1602）
- `enum_f3_*_no_assert_tests.jsonl`
- `f14_full_candidates.jsonl`（2323）
- `scripts/enum_full_candidates.py`

语义决定只来自人工读文件上下文；相同错误形状可共享判据，但成员映射不得由词形脚本代写。

## 未结两类（判词边界）

1. **F3**：正文断言清理误删合法契约，并留下无效测试。须对照真实输入/输出来源双向复查（确定性输入、原样字节、结构化身份、固定界面字段合法；生成散文锁非法；**negative 生成散文同样非法**；固定输入透明传输合法，不得与「generated/fixture free prose」混为必删）。
2. **F14**：探针阶段标签冒称。生产侧日历标签纠正仍保留；历史 stdout（`CLOSED_*`）不改写。

## 本座已实读并处置（非脚本词形）

见 `f3_member_table.md`。方法：打开源文件与 `52809cdf3` 删除前版本，核对断言字面量是否等于同测夹具种子 / 磁盘写入 / 调用输入，再定 KEEP / RESTORE / DELETE。

本提交代码：恢复误删透明传输（staleGuard / modals night·history / situation bars / cli 回包 / audience 回话落库 / decree CLI / ministerScrollLens 夹具 content / textual_facts body / fiscal presented / relation brew·read / grant note / month_chain / style payload_summary / player_payload / decisionModal 标题）。**未**恢复无固定输入来源的生成正文锁。

## F14（证据范围，非自动结清）

| 事实 | 证据 |
| --- | --- |
| 历史探针 stdout 含 `CLOSED_WORLD/PUBLIC`（不改写） | `evidence/1834-fixer-f9-f12-f3/probe.txt` / `probe-current.txt` |
| 现行脚本标签为 `CALENDAR_ADVANCED_*` | `probe_f9_f12_structural.py`；本目录 `probe-current.txt` |
| 全仓阶段/关闭 token 无过滤候选 | `f14_full_candidates.jsonl`（2323）— **未对 2323 声称语义结清** |

## 复杂度 / 合法性

- 无新增分类机制、来源账、摘要、模型调用、输出擦洗、生产出口。
- 邻票 #1873 不施工；不重开已结生产类（F9/F12 等）。
- 自查二连 done。

## 聚焦验证（七 BIN；非全量）

`focused-pytest.txt` → **343 passed**（触及恢复与透明传输样本文件）。
`focused-vitest.txt` → **6 files / 135 passed**（staleGuard / modals / situation / ministerScrollLens / decisionModal / drawers）。

## 剩余范围（诚实）

- 原 `KEEP_NEEDS_CONTEXT_NOT_AUTO` 中**尚未人工读完**的文件仍属未结清范围；本回执只对已实读批次负责。
- 分支未合并 → **不声称 #1834 关闭**。
