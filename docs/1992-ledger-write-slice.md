# #1992 落账／重建片施工记录（未完成全票）

## 范围与剩余决定

本片替换落账与重建路径，未改 `read_once` 的按提交清空策略。Q4/Q5 的跨无关提交去重尚未实现，不能据本片减少的 SQL 数宣称重复归零。

当前 `Ledger.commit` 每次有 recordings 就 `read_results.clear()`；`read_once` 同时缓存 SQL 结果和中间层派生结果，既不保存查询依赖，也不保存父子读依赖。Q4 要求无关提交不使结果失效，因而不能只删除 clear（会返回旧实体、旧权限和旧事实），也不能仅以表/kind 变更清空（同类无关实体仍会重复）。

继续需要把现有提交级复用改为跨提交、依赖相关状态的复用设计，并明确其存活期和材料增长成本。这个实质设计变更尚未在票面 Q1–Q7 中定义；依“设计修订后重新过庭”，本片不擅自加 SQL 依赖分析器、第二套依赖名单或长寿命无界缓存。待签发方取得设计裁定并重新署票后继续 Q4/Q5；本记录不是新的设计决定。

## SQL 实测

基线 HEAD：`1f2d13220c74df389c8af1d339fbfc1d36a7e169`（本工作树的起点）。票面原探针在 `b60834271`，两者不是同一状态；这里如实记录本树，不把数字冒称复现原票的 2872。

命令：

```sh
PYTHONPATH=/tmp:$PWD .venv/bin/python -m pytest -q -p probe1992 \
  'tests/test_month_steps.py::test_month_pays_affair_from_declaration_month[regular]'
# 修后加 SQL_REPORT=/tmp/1992-after-write.json
```

临时探针 `/tmp/probe1992.py` 用 SQLAlchemy `before_cursor_execute` 记录实际 SQL、参数和仓内调用栈，只统计 pytest call 段。完整数据：`/tmp/1992-before.json`、`/tmp/1992-after-write.json`。事件流为录件驱动、真实 HTTP → Game → Court → Ledger → SQLite；不调用真实模型。

| call 段动作 | 修前 | 本片后 |
| --- | ---: | ---: |
| 全部 SQL | 3207 | 1011 |
| SELECT | 1895 | 601 |
| 读实体／事实表 | 440 | 440 |
| 聚合获取读事件表 | 344 | 161 |
| 初始化、落账、跟随者读事件表 | 427 | 0 |
| 读 tracking | 684 | 0 |
| 写 tracking | 322 | 0 |
| 写事件表 | 322 | 322 |
| 写实体表（执行次数，不是行数） | 322 | 36 |
| 写事实表（执行次数，不是行数） | 322 | 36 |
| PRAGMA | 24 | 16 |

修前输出 `1 passed in 8.33s`；本片后输出 `1 passed in 4.22s`。实体／事实批量写使用 SQLAlchemy 原生 executemany，记录完整性由重开与重建比对验证，不以减少写入条数冒充删除事实。

### 读表 440 句：调用者 × 表（修前、本片后相同）

E＝实体表；E+F＝语句涉及实体与事实表（含关联子查询）。这是实际 SQL 的表参与分类，不冒称逐行语义依赖分析。

| 调用者（均在 `ming/middle/`） | 表 | 次数 |
| --- | --- | ---: |
| calendar.calendar_row | E | 37 |
| calendar.journeys_due | E | 4 |
| court.current_decrees | E+F | 2 |
| court.errands | E+F | 2 |
| court.interactions | E+F | 37 |
| court.month_petitions | E+F | 2 |
| court.nights | E+F | 37 |
| court.pending_nights | E+F | 5 |
| court.pending_petitions | E+F | 37 |
| court.pending_pushes | E+F | 2 |
| court.petition_officials | E | 16 |
| court.petition_products | E+F | 2 |
| court.products | E+F | 67 |
| court.record_catalogue | E+F | 22 |
| court.returned_petitions | E+F | 41 |
| court.unhandled_monthly | E+F | 37 |
| dispatch.dispatch | E+F | 2 |
| dispatch.landing_entities | E | 6 |
| dispatch.landing_sources | E+F | 16 |
| fiscal.Accounts.__init__ | E | 4 |
| fiscal.due_levies | E | 2 |
| fiscal.Accounts.run | E+F | 2 |
| view.entities | E / E+F | 19 / 32 |
| view.month_open | E+F | 2 |
| view.project | E+F | 5 |

事件表／tracking 的剩余修前调用者拆分可在原始 SQL 文件核对；本片后事件表 161 句为 `fiscal.Accounts.__init__` 153、`court.record_product` 7、`court.record` 1，全部为缓存未命中的聚合历史读取，不是快进。

## 重建行为与成本

真实入口 `ming read --db … --identity audit --replay`，与不加 replay 的同库输出比较：

| 历史 | 事件 | 实体 | 事实 | SELECT（含最后两张表输出） | INSERT 执行 | 耗时 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 开局 | 3433 | 3433 | 0 | 7 | 1 | 0.3703s |
| 现成八个月任免案 | 4813 | 3454 | 1359 | 8 | 3 | 0.6618s |

命令 `PYTHONPATH=$PWD .venv/bin/python /tmp/replay1992.py`，两档输出均 `equal: true`。八个月存档来自已有 `tests/test_court.py::test_common_declaration_updates_entities_and_displaces_incumbent_atomically[holders-first_night]`，不是另造业务夹具。额外固定开销均为 10 次 PRAGMA、9 次 CREATE（临时读库的表及索引）。每页至多 1000 条通知；实体累进状态的内存随实体及其状态大小增长，非总内存有界。

## 验证与变异

- CLI 既有案扩充开局、历史、连续两次、坏事实表缺行／多行比对。修前 `10776 != 3592` 红；修后绿。恢复旧 CLI 分别重建实体和事实的逻辑，真实入口再次 `7184 != 3592`，`1 failed in 3.01s`；随后恢复共享重建逻辑。
- `LedgerReplay` 复用已有生成序列与回滚案：比较实体行与聚合 snapshot；失败后新建 Ledger 验证事件、实体、事实仍为原值，再正常提交。未增平行测试函数。
- 在 `ming/middle/calendar.py` 暂加 `import ming.ledger.tables`，`lint-imports` 输出 `3 kept, 1 broken`，点名该非法导入；移除后 `4 kept, 0 broken`。
- `.venv/bin/python -m pytest -q tests/test_ledger.py tests/test_opening.py tests/test_secrets.py` → `15 passed in 33.81s`。
- 八个月案＋CLI 重建案 → `2 passed in 15.53s`。
- `.venv/bin/pyright --pythonpath .venv/bin/python` → `0 errors, 0 warnings, 0 informations`；触及文件 `ruff check` → `All checks passed!`。
- 自审将新增 `Court.records` 并入已有 `Court.read_records`，删去平行入口；CLI 用原入口的新增 replay 选项一次读取实体与事实。
- 最后聚焦调用（本腿 runId `01a180fe-a9d1-74bb-8484-61260ab2fc3f`，跑时 HEAD `1f2d13220c74df389c8af1d339fbfc1d36a7e169` 加本片工作区）：`.venv/bin/python -m pytest -q tests/test_ledger.py tests/test_opening.py tests/test_secrets.py 'tests/test_month_steps.py::test_month_pays_affair_from_declaration_month[regular]' 'tests/test_court.py::test_common_declaration_updates_entities_and_displaces_incumbent_atomically[holders-first_night]'` → `17 passed in 56.42s`。同次随后 ruff、pyright、lint-imports、diff --check 均通过。
- 未跑全量，未 push／开 PR／merge；ADR 0159、0160 与 CONTEXT 修订待评审。Q4/Q5、跨提交边界与错误常驻案仍待施工，不以已有权限测试通过替代它们。
