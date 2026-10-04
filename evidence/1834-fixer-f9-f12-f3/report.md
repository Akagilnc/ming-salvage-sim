# #1834 修内司回执：F9 / F12 / F3（续施工·全仓处置收束）

依据：fix-packet + 冻结判词 `00-1834-judge-52809cdf3.json`；现行 #1834 / #1812；ADR 0143、0155；质量法 #13。
Owner 授权：保留 SIGTERM 前工作树未提交改动并在其上完成；禁止 amend/stash/reset/checkout 覆盖/clean/push/PR。
**未合并，不声称关票。**

## 本轮相对前轮缺口

前轮报告曾写「F3 宽枚举长尾另跟踪」——与判词「全仓同类修净」及 owner「报告不得再留 F3 非材料口长尾待办」冲突。本轮：

1. 结构探针改为喂入 `_material_facts_text` 的 Mapping 键集合（`payload`/`stigma`/`execution_signal`），**不再**用材料树散文字段头 `payload：` 作判据。
2. F3 枚举补 list/tuple 散文相等与 vitest `toBe`/`toEqual`；全仓候选逐条处置（FIX 删断言 / KEEP 附依据），`FIX_REMAINING=0`。
3. 审查未提交改动：恢复 `extract_agent_text` / stream `out` **原样传输**等式；补回四角色结构存在性（非正文）；未为绿放宽合法失败路径。

## 三类根因（判词）

1. **F9** 案卷解码 `payload`（含裸 `loyalty`）进公共/世界材料。
2. **F12** `list_world_effect_history` 整行 `person_logs` 等审计转储进材料。
3. **F3** 人读自由正文机械依赖（`in`/`==`/`len`/非空/`toContain`/`toBe`；含对话/CLI/Web，不整体豁免）。

## 修法

- F9/F12 生产删除：已在 `fc08d7713`（本轮复核 STRUCT + 变异探针）。
- F3：按 `classify_f3_disposition.py` 决策删除 FIX 断言；保留结构化字段 / 原样传输 / 固定 UI（P7）/ 权限负向 / 错误标识。

## 可执行全仓枚举

七变量前缀 + `PYTHONDONTWRITEBYTECODE=1` + `PYTHONPATH=$PWD` + `../Ming_LLM/.venv/bin/python`。

```sh
../Ming_LLM/.venv/bin/python evidence/1834-fixer-f9-f12-f3/scripts/enum_f9_material_payload.py | tee evidence/1834-fixer-f9-f12-f3/enum_f9.txt
../Ming_LLM/.venv/bin/python evidence/1834-fixer-f9-f12-f3/scripts/enum_f12_history_dump.py | tee evidence/1834-fixer-f9-f12-f3/enum_f12.txt
../Ming_LLM/.venv/bin/python evidence/1834-fixer-f9-f12-f3/scripts/enum_f3_free_text_asserts.py | tee evidence/1834-fixer-f9-f12-f3/enum_f3.txt
../Ming_LLM/.venv/bin/python evidence/1834-fixer-f9-f12-f3/scripts/classify_f3_disposition.py
```

复扫：`evidence/1834-fixer-f9-f12-f3/rescan.txt`  
成员表真源：`f3_disposition.json`（全量）+ `f3_fix_list.txt`（本轮末为空）。

| 轴 | 结果 |
| --- | --- |
| F9 | `dossier.items_dump=PRESENT`；skip 含 payload/stigma/execution_signal；HIT=70 |
| F12 | audit dump loop=ABSENT；keeps=实况轨,issues,characters,relation_edge_events；HIT=142 |
| F3 | MATERIAL_BODY_POSITIVE=0；HIT=1960；**FIX=0 KEEP=1960** |

## F3 处置分组（完整；无长尾待办）

### FIX（已删净；末态 0 条）

本轮曾列并删除的同类（路径见 git diff / 应用前 `f3_fix_list` 快照逻辑）：对话答案/回话列表、memorial/execution_note/stance 自由正文、材料 `read_material` 正文相等、CLI capsys 自由子串、vitest 对话/邸报夹具正文等。删除方式=整条 Assert/expect，**不**换成非空/len/哨兵/测试专用生产出口。

### KEEP（1960；按依据计数）

| basis | count | 含义 |
| --- | ---: | --- |
| structured_enum_or_identity_field | 685 | 官职/身份/枚举/配置键等结构化相等 |
| cli_fixed_option_or_error_identifier | 390 | 固定错误串/prompt 硬约束/技术诊断 |
| ui_identity_or_fixed_label_or_technical | 379 | UI 身份点名、技术属性 |
| structured_enum_identity_transport_or_contract | 192 | 其它结构化契约 |
| permission_or_negative_contract | 172 | 权限/非泄漏负向 |
| ui_fixed_chrome_p7 | 65 | 界面固定话语（P7 例外） |
| structured_field_equality | 49 | archive/presented/body 等字段搬运 |
| verbatim_transmission_equality | 21 | `extract_agent_text` / stream out / 玩家问话回显 |
| path_or_directory_structure | 4 | 材料路径成员 |
| structured_presence_not_free_prose | 3 | office/classes 等结构存在性 |

逐条路径:行号:detail 见 `f3_disposition.json`（不得在报告另留「未分类库存」）。

## 结构探针（非 pytest）

`evidence/1834-fixer-f9-f12-f3/scripts/probe_f9_f12_structural.py`

- 判据：输入 Mapping 不得含 machine keys；`list_world_effect_history` 不得含 audit 表；开放/关闭/恢复 × 世界+公共作者。
- **不用** `payload：` 等散文字段头。

| 运行 | 结果（`probe.txt`） |
| --- | --- |
| current | ALL_GREEN（各态 files=279） |
| `--old` | OLD_LOGIC_RED machine keys entered material feed |
| `--old-f12` | F12_OLD_LOGIC_RED dumps ['person_logs'] |

## 聚焦测试

```sh
# A：核心聚焦 + 全部已改 tests（除 breach 文件，见下）
# B：tests/test_breach_plea_623.py 单独进程
# 前缀：七 BIN=/usr/bin/false + PYTHONDONTWRITEBYTECODE=1
# 解释器：../Ming_LLM/.venv/bin/python
```

结果（`focused-pytest.txt`）：

- A：`1228 passed, 1 skipped`，real **57.85s**
- B：`32 passed`，real **2.58s**

说明：`test_decree_continuation_keeps_forecast_and_lands_affair_effect` 与 `test_revoke_forecast_translation_input_carries_original_and_continuing_dossier` 同进程顺序依赖（恢复 `decree_text` 真理断言后仍复现）——**非本轮 F3 删文引入**；分进程均绿。未跑全量。Web vitest：本机无 `web/node_modules`，未跑。

## 复杂度 / 合法性

- 无新增来源账/摘要/模型调用/输出擦洗/生产出口。
- 邻票 **#1873**（四类文字事实公共读侧）不施工。
- 自查二连 done。

## 剩余范围（仅授权外）

- **#1873** 邻票。
- 分支未合并 → **不声称 #1834 关闭**。
