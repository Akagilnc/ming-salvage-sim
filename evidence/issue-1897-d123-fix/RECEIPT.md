# #1897 D1/D2/D3 修内司回执

- 施工分支：`ak-roles/issue-1897-n5-fix-d123`
- 施工前 HEAD：`874b85adf4eb15985ff88430511338360add5536`
- 上一施工 commit：`87f66be3d800f0a310b1e4b85740adfa51bc4483`
- 判词 base：`0ca77fecc402b67829da5310fdf0cf76d624249d`
- 派单：`01a0facf-8530-76ee-8b30-a2282bf8eed7@fixer`
- 冻结判词：`attachments/00-1897-judge-874b85adf.json`
- 未 push / 未开 PR / 未 amend / 未 stash

## 各类根因

| 类 | 根因 | 处置 |
|---|---|---|
| D1 | 搬迁后生产未净减；被替代实现仍并存 | 删散文解析；`capture` 收成结构化薄包装并保留为单一写口；`db` 交办缝只透传显式 stages；暂存口改 `normalize` |
| D2 | 结案奏报正文回填执行格 | `close_secret_order` 缺省写 `""`；`settle_due_secret_orders` 传 `verdict["note"]` |
| D3 | 生产散文年诺捕获 + 坏结构回落正文；旧契约锁定 | 删除 `parse_staged_year_promise` 等；只认显式 stages；同步撤销 #620 P4／AC2 与 DELTA_SCHEMA 捕获条款 |

## 全仓枚举

命令、18 文件清单、D1/D2/D3 完整成员表与逐项核销／保留说明 → 同目录 `enumeration.txt`。

### capture 薄包装审视

试删 `capture_commitment_stages` 并把空值分支内联进 `issues.py` 两处后，judge **18 文件**口径从 vs_base **+72** 涨到 **+83**（`staged_commitment` 省行不进原 18）。结论：**保留**薄包装作单一写口，不凑删。

## 生产行数

详见 `line-counts.txt`（算法：`git show`/`read_text` → `splitlines()`，与判词同口径）。

**Judge 原 18 文件 production changed union：**

| 点 | 行数 | 相对 |
|---|---:|---:|
| base `0ca77fec` | 52847 | — |
| 施工前 `874b85adf` | 52940 | +93 |
| 现 | 52919 | vs_base **+72**；vs_pre **−21** |

**含 D3 真源 `staged_commitment.py` 的票面生产 19 文件：**

| 点 | 行数 | 相对 |
|---|---:|---:|
| base | 53267 | — |
| 施工前 | 53360 | +93 |
| 现 | 53217 | vs_base **−50**；vs_pre **−143** |

`staged_commitment.py`：420 → 298（−122）。

可复跑：见 `line-counts.txt` 文件清单 + 同算法脚本。

## 旧路核销

- [x] 奏报 `result`/`close_text` → 执行格 `execution_note` 兜底已断（真实结案入口观察）
- [x] 到期结案写口改走实况 `verdict["note"]`
- [x] 散文年诺解析符号与调用全仓清零
- [x] 坏结构回落正文路径删除
- [x] #620 P4／AC2 与 DELTA_SCHEMA 旧捕获约同步撤销
- [x] 未新增证明性测试／护栏／机制；未锁自由文本
- [x] D1 成员表按搬迁后被替代／重复真源整类枚举，非仅判词符号

## 聚焦自验

前缀：`env MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false`

命令（与判词同清单）见 `focused-pytest.txt`。

结果：**1 failed, 342 passed in 7.59s**（wall ~8s）。
失败同判词保留项：`test_path1_conversational_draft_bad_roster_marks_failed` 名册 `ValueError`——御史台 C1/N5，归 #1873，本轮不修。

## 旧逻辑变异入口观察

详见 `observe-d2-d3.txt`（系统临时目录 `git archive` 装回施工前全树；pytest cwd=该树以解析旧 `ming_sim`；同一结构化契约）。

| 案 | OLD（874b85adf 归档树） | NEW（本工作树） |
|---|---|---|
| D3 stages=None + 散文正文 | due_turns=**[37,61]** | due_turns=**[]** |
| D3 stages=[] + 散文正文 | due_turns=**[37,61]** | due_turns=**[]** |
| D3 stages={bad:1} + 散文正文 | due_turns=**[37,61]** | due_turns=**[]** |
| D3 显式 due_turn=3 | **[3]** | **[3]** |
| D2 结案（actual=0 + 奏报「臣已查明全部」） | execution_note=**奏报原文** | execution_note=**machine_settle…**；result 仍为奏报 |

**VERDICT: OLD_RED_NEW_GREEN**（统一契约：NEW rc=0 / 6 passed；OLD rc=1 / 4 failed）。
入口：`_emit` commissions/assignment → `pending_actions.payload_json`；密令批准 + 月结 → `decree_dossiers.execution_note`。不锁自由文本；非仓内证明性测试。

## 残留功能范围（#1873）

- 幻觉参与人阻断同批提交（C1/N5）——聚焦红灯仍在，不冒称已修
- 结案玩法完整接线／准宽限等历史玩法——本票不补
- 分段玩法扩展（到期复核场面、财政分期等）——仍归 #621/#705，本票不扩

## 基础设施失败

无。
