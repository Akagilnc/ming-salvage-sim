# #1897 D1/D2/D3 修内司回执

- 施工分支：`ak-roles/issue-1897-n5-fix-d123`
- 施工前 HEAD：`874b85adf4eb15985ff88430511338360add5536`
- 上一施工 commit：`87f66be3d800f0a310b1e4b85740adfa51bc4483`
- 证据修订基线 HEAD：`609d13488b3d6b8fbc1073721eb1c7a3f9768a80`
- 判词 base：`0ca77fecc402b67829da5310fdf0cf76d624249d`
- 派单：`01a0facf-8530-76ee-8b30-a2282bf8eed7@fixer`
- 冻结判词：`attachments/00-1897-judge-874b85adf.json`
- 未 push / 未开 PR / 未 amend / 未 stash
- 本轮：仅证据核验修订；全仓枚举无漏成员 → **未改生产**

## 各类根因

| 类 | 根因 | 处置 |
|---|---|---|
| D1 | 搬迁后生产未净减；被替代实现仍并存 | 删散文解析；`capture` 收成结构化薄包装并保留为单一写口；`db` 交办缝只透传显式 stages；暂存口改 `normalize` |
| D2 | 结案奏报正文回填执行格 | `close_secret_order` 缺省写 `""`；`settle_due_secret_orders` 传 `verdict["note"]` |
| D3 | 生产散文年诺捕获 + 坏结构回落正文；旧契约锁定 | 删除 `parse_staged_year_promise` 等；只认显式 stages；同步撤销 #620 P4／AC2 与 DELTA_SCHEMA 捕获条款 |

## 全仓枚举

命令、自动 production changed-union、D1/D2/D3 共表成员与逐项核销／保留说明 → 同目录 `enumeration.txt`。
**枚举范围=全仓**，不以 judge 原 18 文件为授权边界；`urge_lever.py` 等未改同根消费者亦入表。

### capture 薄包装审视（复杂度）

`capture_commitment_stages` 现为单一写口：一处空值短路（`None/""/[]/()/{} → []`）再经 `stages_to_json`→`normalize`。`issues.py` 校验与落库两处都走它。
若删薄包装而把空值分支+规范化内联进两处调用点，会复制两套相同的空值判定与规范化路径——重复控制流与规范化成本上升，接缝面变宽。
**保留**理由=真实重复空值短路与规范化成本（复杂度），不是「原 18 文件行数涨跌」；新文件同样纳入行数统计，行数口径不能充当保留判据。

## 生产行数

详见 `line-counts.txt`（完整可复跑命令 + 当前真值；算法：`git show`/`read_text` → `splitlines()`）。

**production changed-union（git diff base..HEAD 自动，19 文件，含 `staged_commitment.py`）：**

| 点 | 行数 | 相对 |
|---|---:|---:|
| base `0ca77fec` | 53267 | — |
| 施工前 `874b85adf` | 53360 | +93 |
| 现 | 53217 | vs_base **−50**；vs_pre **−143** |

**Judge 原 18 文件（显式列表，不含 staged_commitment）：**

| 点 | 行数 | 相对 |
|---|---:|---:|
| base | 52847 | — |
| 施工前 | 52940 | +93 |
| 现 | 52919 | vs_base **+72**；vs_pre **−21** |

`staged_commitment.py`：420 → 298（−122）。

## 旧路核销

- [x] 奏报 `result`/`close_text` → 执行格 `execution_note` 兜底已断（真实结案入口观察）
- [x] 到期结案写口改走实况 `verdict["note"]`（DB 值与 settle 返回 note 整体相等；写口实参动态记录同源）
- [x] 散文年诺解析符号与调用全仓清零
- [x] 坏结构回落正文路径删除
- [x] #620 P4／AC2 与 DELTA_SCHEMA 旧捕获约同步撤销
- [x] 未新增证明性测试／护栏／机制；未锁自由文本
- [x] D1 成员表按全仓同类旧实现／重复写口枚举，非仅判词原 18

## 聚焦自验

完整七前缀命令与输出见 `focused-pytest.txt`。

结果：**1 failed, 342 passed in 8.13s**（wall real 8.61s）。
失败同判词保留项：`test_path1_conversational_draft_bad_roster_marks_failed` 名册 `ValueError`——御史台 C1/N5，归 #1873，本轮不修。

## 旧逻辑变异入口观察

详见 `observe-d2-d3.txt`（系统临时目录 `git archive` 装回施工前全树；pytest cwd=该树；结构化契约，不锁自由文本）。

| 案 | OLD（874b85adf 归档树） | NEW（本工作树） |
|---|---|---|
| D3 stages=None + 散文正文 | due_turns=**[37,61]** | due_turns=**[]** |
| D3 stages=[] + 散文正文 | due_turns=**[37,61]** | due_turns=**[]** |
| D3 stages={bad:1} + 散文正文 | due_turns=**[37,61]** | due_turns=**[]** |
| D3 显式 due_turn=3 | **[3]** | **[3]** |
| D2 结案（actual=0 + 有奏报） | DB execution_note=**奏报**；write_arg=**None**；≠ settle verdict note | DB execution_note **==** settle verdict note 整体；write_arg 同源；status=failed actual=0 |

**VERDICT: OLD_RED_NEW_GREEN**（NEW rc=0 / 5 passed / ~1.66s wall；OLD rc=1 / 4 failed / ~2.99s wall）。
入口：`_emit` commissions/assignment → `pending_actions.payload_json`；密令批准 + `settle_due_secret_orders` → `decree_dossiers.execution_note`。D2 契约=与真实 verdict note 整体相等 + 写口实参动态记录，非「不得含奏报片段」文本禁令。

## 残留功能范围（#1873）

- 幻觉参与人阻断同批提交（C1/N5）——聚焦红灯仍在，不冒称已修
- 结案玩法完整接线／准宽限等历史玩法——本票不补
- 分段玩法扩展（到期复核场面、财政分期等）——仍归 #621/#705，本票不扩

## 基础设施失败

无。
