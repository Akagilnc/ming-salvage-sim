# #1835 修内司施工记录

本工作树从 `e46a13f938810068915dbcb237ee18dfe021c42d` 续做。以下是已执行工作的证据，不是七类全仓结清声明。F12 按派单留待独立设计裁决，未施工。

## 已施工

| 类 | 共同原因与处置 |
| --- | --- |
| F1 | 单实现迁至 `settlement/preflight.py`、`settlement/run.py` 和实体目录；移除人物快照族、领域提交和专用出口重包；人物、局势、月度结果直接返回段结果。财政承诺去重、月度实体核、recovery 和 legacy 核共置；调用方改真源。 |
| F5 | 正文、标题、奏报、诊断及工具/思考输出不再 strip、截断或抹换行；strip 仅判空。SQLite 不替换孤代理；JSON 编码层转义后保留 codepoints。CLI 删除重新折行的 wrap 及其调用。补修 scene prompt、现有草稿、检举正文、brief 标题、highlight 输入和 ERROR provider 原文。 |
| F6 | 声明数据守卫使用专门异常；持久 JSON、数据库操作和普通代码故障不转拒收或空结果。持久保密排除、局势参与人和目标名单严格解码；可选投影字段缺席与在场损坏分开。回滚失败留诊断。历史 severity 迁移留坏原行并告警、shadow fiscal outcome 保留原异常，均为现有隔离例外。 |
| F10/F7 | 旧返回访问迁至属性/真实入口；移除异常文案锁、默认拒因及历史 strictness 绿卡、源码/prompt 文案绿卡、数值呈现 regex 和结构属性绿卡。保留 fixed-point 文件两例真实结局行为。原文传递测试比较调用输入。 |
| F11 | 信用消费实际落地回执的 source_item；不消费 applied=False；同源去重，不新造平行拒收护栏。该关联实现已由继承提交带入，续做适配真实局势段结果。 |
| F13 | 非对象拒收在产生处包装 raw_value；对象保留原项；不增加中央形状修复层。 |
| F14 | 嵌套指标、经济、派系、建筑、legacy、人物及实体效果汇入既有耐久拒收。月度坏容器/坏项/未知键进入同管线，不恢复退役别名。主体结案不代替后果成功。 |

## 枚举与复扫

临时证据路径位于 `/tmp/1835-*`，不依赖其作为运行前提。

- 命令：`python /tmp/1835-enumerate.py`（Python 为主仓 `.venv/bin/python`）。当前候选表：`/tmp/1835-live-F{1,5,6,10,11,13,14}.json`。宽枚举涵盖函数、文本变换、catch、断言、信用消费和拒收产生点；候选不等于违规成员或结清证明。
- 迁移清单核对：`/tmp/1835-inventory-live.txt`。明定留内的门闩求值器、GameDB 原语、levy 邻接面保留。
- 专项成员表：`/tmp/1835-monthly-relocation-members.txt`、`/tmp/1835-db-operational-members.txt`、`/tmp/1835-presentation-test-members.txt`、`/tmp/1835-copy-lock-final-members.txt`、`/tmp/1835-structure-final-members.txt`、`/tmp/1835-display-tail-members.txt`。
- 复扫：`rg 'strict_effect|_new_army_historically_applied|inspect.getsource' ming_sim tests scripts docs`；历史证据文档引用、退役注释不作为活跃实现。
- `rg 'undefined name' /tmp/1835-pyflakes-clean.txt` 无输出；`git diff --check` 通过。Python compileall 通过。使用生态 autoflake 删除迁移后的闲置 import；pytest fixture 注册 import 保留，消费端不借 issues 做出口桥。

## 验证

所有 pytest/vitest 命令均设置 `MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false` 七旗。

- 触及面命令：`python -m pytest -q -x $(git diff --name-only --diff-filter=ACMR -- 'tests/test_*.py')`。`/tmp/1835-touched-focused22.txt`：2706 passed、3 skipped，145.09s。此后继续修改读端，故不能把该结果称为最新全部触及面绿测。
- 最新读端聚焦：`/tmp/1835-readers-focused26.txt`：118 passed、1 skipped，3.58s；`/tmp/1835-knowledge-focused27.txt`：92 passed，2.08s。
- 新删结构绿卡/scene/highlight 等聚焦：`/tmp/1835-final-targeted18.txt`：119 passed，2.13s。
- Web：使用主仓现有依赖的工作树内符号链接，`web/node_modules/.bin/tsc --noEmit` 通过；`vitest run --environment jsdom src/settleStream.test.ts`：6 passed，492ms（`/tmp/1835-web-focused.txt`）。未修改任何宿主/席位配置。
- 变异真跑：信用段装回直接消费 dossier 输入，真实 settle 入口在既有 `test_fulfill_back_and_urge_three_decisions` 报红（伪信用边 3 != 2），0.65s：`/tmp/1835-credit-source-mutation-red.txt`。恢复后上述聚焦绿。
- 变异真跑：嵌套实体核装回丢弃拒收列表，真实 dispatch 入口 `test_malformed_army_rejected_durably` 报红（rejection_reports 为空），0.64s：`/tmp/1835-nested-mutation-red.txt`。恢复后聚焦绿。
- 失败诚实：经济源变异在宽限例中仍绿（`/tmp/1835-credit-mutation-red.txt`），不作为 F11 修复证明；新加的该证明性片段已删除，未换形重造。
- open_night savepoint 曾批跑偶发失败；单例五次及整文件复跑均绿，整文件 32 passed。未据单次失败猜改生产逻辑，未硬杀 worker。
- 未运行全量；本局不是判官 converged、PR 已开的最终待合并状态。

## 尚未结清

仍须将宽枚举逐成员完成语义处置，特别是 F10 剩余自由文本/保密哨兵及 helper 呈现测试、F5 下游传递与识别变换的边界、F6 剩余持久与批写接缝，并刷新完整成员处置表与最新触及面验证。本记录不把聚焦绿色冒作整类结清，不声明这些工作缺 owner 决定，也不以执行窗口作合法 blocker。
