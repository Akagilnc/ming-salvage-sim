# #1830 消费边界续修回执

基线 `4ab5969b7fc5dfd2f650125102c5408b03d4a813`；工作分支 `ak-roles/issue-1830-w4merge`。本轮只修既有测试与事实说明，生产逻辑不变；不宣告合并、整票收敛或关票。判词根因已有最小变异证据，诊断不再重复假设/生产取证阶段；直接恢复入口验证、变异验证与清理。

## 类定义与机械枚举

沿用判词完整三类：必要负向被删除或转移到另一读面；独立契约退化成 helper 自测（包括恢复函数却丢消费链）；当前覆盖、形态、处置与净增减说明失配。不存在按文件名、正文关键词或判词样本缩小成员定义。

扫描对象为全仓受版本控制文件。先枚举所有 Python 函数、调用、断言、比较及非 Python 测试，再比较历史删除/改写断言，核对其原边界与当前真实消费端。关键词只导航，不能裁决成员。命令：

```sh
git ls-files
git diff --name-only 2f20f18bd -- tests
git diff --name-only 88d114e21 -- tests
git diff 2f20f18bd -- tests
git diff 88d114e21 -- tests
rg -n 'assert|expect\(|test\(|it\(' --glob '*.ts' --glob '*.tsx' --glob '*.js' --glob '*.jsx'
rg -n '覆盖|负向|失败传播|helper|自测|结清|全部|未修|净增|净减|归档列' --glob '*.md'
```

Python 机械枚举使用标准库 AST，对 `git ls-files` 返回的每个 `.py` 无文件/变量白名单执行：

```python
for file in tracked_python_files:
    for node in ast.walk(ast.parse(Path(file).read_text())):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.Assert, ast.Call, ast.Compare)):
            emit(file, node.lineno, type(node).__name__, ast.unparse(node))
```

历史比较对两基线的每个变更测试文件建立函数名到 AST 的映射，分别枚举函数中的全部 Assert，输出旧集合减现集合；函数消失时现集合为空。嵌套 helper 同样枚举，不仅看 `test_` 顶层函数。运行 `/tmp/1830-enumerate.py` 的结果：360 个 Python 文件；FunctionDef 7774、AsyncFunctionDef 97、Assert 13712、Call 75639、Compare 21133；2f20f18bd 比较30个测试文件、322条删除/改写断言；88d114e21 比较17文件、115条。非 Python候选2044行，文档导航候选1860行。数字是候选计数，不是缺陷或结清证明。

### 本轮成员表

| 类 | 文件 / 成员 | 处置 |
| --- | --- | --- |
| F1 | `test_gazette_author_1862.py::test_author_archives_own_title_and_same_run_advances` 的事实、经历、召对、案卷与国库作者供料负向 | 从 `session.resolve_turn` 进入。在本次作者备料期间，真实事实对象被写手取正文时记录 origin_ref；真实经历写手的输入记录 source_id / source_chat_turn_id；真实开场写手记录案卷 id。原函数与原数据照常消费，无替代结果，不调用筛选 helper 自测。国库读口另核调用者交出的排除参数，目录载体与公开原文搬运另核。 |
| F1 | `test_character_knowledge_489.py::test_turn_report_counterpart_never_uses_aggregate_when_sources_exist` | 新回合登记单一独立公开来源，真实 `save_turn_report` 接受另含无来源改写的聚合输入；直接读 `get_turn_report_archive(...)[report]`，要求完整搬运独立公开输入。不重建筛选/拼接，不按正文片段识别权限。 |
| F1 | 同文件 `test_shared_archive_storage_never_writes_restricted_aggregate` | 同样隔离到新回合，公开与受限来源均真实登记；核共享归档 report 完整搬运独立公开输入，保留承办人/他人来源集合正负向。不能用后者替代归档边界。 |
| F1 | `test_secret_order_monthly_progress_566.py::test_emperor_private_payload_preserves_monthly_report` | 同类额外成员：历史删除了人物材料负向，只有皇帝 payload 正例。复用该入口准备真实承办人目录，观察真实订单映射的字段消费；title/content 正向，dossier_progress 负向。订单原字段值与真实写手保留，不恢复整目录正文权限 oracle。 |
| F2 | `test_army_display_173.py::test_army_arrears_presentation_rounds_half_steps_up` | 恢复 DB 写入→`army_detail` 真出口；五个半档输入使用独立预期，不再直接调用 `_approx_wanliang`。 |
| F2 相关同根 oracle | 同文件 `test_army_payload_exposes_approx_arrears_text_not_raw` | 删除 `_player_army_situation` 生成 expected 的同源自证，按真实 payload 契约字段核独立近似额与 raw 字段/精确小数缺席；不锁整个情况句或月数措辞。 |
| F3 | `CHANGELOG.md` #1830 条目中共享归档、作者材料两项覆盖说明 | 如实说明曾有覆盖退化及本轮直接归档/消费观察的形态。国库排除参数验证不声称证明渲染结果语义。 |
| F3 | `1830-w4merge-fixer-class-followup.md:155` 及相关历史续修说明 | 以本回执下面的更正取代无证据保留声明；旧回执保留，不覆写冻结历史。 |

### 复扫保留项

- 489 其余人物读侧排除、参与者、职署、后加入读者等断言保护各自来源准入，不冒称保护共享归档列；883 共享来源按 source_id 查行、私密聊天按消息 id 查状态，仍在原共享存储边界。883 的纯公开归档正例仍直接读 archive，并不把密令 marker 字面缺席当权限判据。
- 1829 真实世界/作者供料调用的 public_events 来源观察仍在实际写手接缝，不另准备参考目录。1838 whisper 测试仍从真实转译结果的 applied id 到人物经历 id 集合，私密负向未丢；539/670 派生记录不上卷轴仍核真实卷轴的 record_id，不转移读面。
- 1830/1834 的材料路径拒绝、恢复重建与失败传播保留。原文搬运与路径协议不是公开权限证明。
- 1501 helper 只核直接 DB 字段搬运，真实 army_payload 完整键集及 raw 字段缺席仍在；321 真跨出口装配链、firearms 真出口两态、CLI 输入未仕→真朝臣及494独立契约均保留，不因出现字符串删除。321 原有纯派生 truth table 不是本轮删简造成的真实入口退化。
- 非 Python 测试未发生本票对应边界删除/转移或恢复为 helper 的变更，不施工相邻独立业务。机械候选与历史改动复核未发现本表以外需本轮修改的成员；这不是对未来缺陷或模型语义的保证。

## 历史事实更正（F3）

`1830-w4merge-fixer-class-followup.md:155` 的「原有负向和失败传播没有为绿灯放松」对作者事实/经历等供料及489共享归档不成立。上轮只排除密令目录或查人物来源，不能证明原消费边界。

`1830-w4merge-fixer-scope-correction.md` 的独立测试函数恢复属实，但173半档恢复成 helper 调用不等于真实出口契约恢复。旧「七条已恢复」不能据此推出全部行为覆盖。

`1830-index-contract-followup.md`、`1830-w5-fixer-presentation-followup.md`、`1830-w5-fixer-receipt.md`、`1830-w4merge-fixer-receipt.md` 关于保留实际作者/共享负向的说明是各轮历史报告；不得沿用为4ab5969b7的覆盖证明。新报告以本轮命令和成员表为准。此前作者目录整体放宽变异的红灯，不证明只放开某一来源筛时也会红。本轮逐一重验。

## 验证（非全量）

全部测试/变异命令均使用此前缀（没有真实宿主、模型、网络验收）：

```sh
export MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false \
 MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false \
 MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false \
 MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1
P=/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python
$P -m pytest -q -p no:cacheprovider \
 tests/test_gazette_author_1862.py tests/test_character_knowledge_489.py \
 tests/test_army_display_173.py tests/test_secret_order_monthly_progress_566.py \
 tests/test_secret_order_isolation_883.py tests/test_public_sayings_1829.py \
 tests/test_public_projection_consistency_1830.py tests/test_material_directory_1830.py \
 tests/test_player_army_projection_321.py tests/test_army_card_status_1501.py \
 tests/test_army_firearms.py tests/test_web_court_visibility.py
```

结果：`194 passed, 1 skipped in 7.16s`。先前四文件验证 `78 passed in 3.51s`；最终作者三条单独验证 `3 passed in 1.95s`。未跑全量，不触Web类型面；`command -v mypy; command -v pyright` 均无输出。全仓 AST 枚举解析成功是语法检查，不冒称静态 typecheck。

变异脚本只在独立解释器内装回错误逻辑，不写生产文件；`prior` 在 collection hook 装回基线 HEAD 对应测试函数，`current` 使用本轮函数。命令 `$P /tmp/1830-boundary-probe.py <mode> <prior|current>`，每次自己的 TemporaryDirectory 均输出 `TEMP_EXISTS False`：

| mode / 错误逻辑 | prior | current | 健康逻辑 |
| --- | --- | --- | --- |
| fact：作者事实公开筛无条件允许 | 1 passed 2.05s | 1 failed 1.65s，消费来源含 secret_order:9 / 密令案卷 | 上述聚焦绿 |
| event：作者经历公开筛无条件允许 | 1 passed 2.29s | 1 failed 1.62s，经历输入含 secret_order_brief:1 | 聚焦绿 |
| audience：召对裁切直接返回全部记录 | 1 passed 4.51s | 1 failed 2.11s，密令轮进入写手输入 | 聚焦绿 |
| archive：共享归档直接保存调用方 aggregate | 2 passed 0.72s | 2 failed 0.73s，共享 report 不等于独立公开输入 | 聚焦绿 |
| detail：helper 不动，真实军饷出口将12.5错误呈10万两 | 1 passed 0.55s | 1 failed 0.66s，真实 detail 缺独立预期15万两 | 聚焦绿 |
| monthly：真实人物材料写手追加消费 dossier_progress.memorial_text | 1 passed 0.69s | 1 failed 0.72s，订单消费键含 dossier_progress | 聚焦绿 |

补充观察：payload错误装配近似额，旧/新测试均红；不能冒称该变异揭出旧覆盖遗漏。清空 secret_order_dossier_ids 同时触多个既有边界，旧/新也都红；不把它计成新修复红绿证据。

初次正常自验有4红：归档新正例混入seed来源；payload断言误要求整句只有近似额；月报探针误要求完全不查询私轨（真实list_secret_orders会装配但人物写手不消费）。修法分别为换新回合隔离输入、不约束额外月数措辞、观察真实订单字段消费；不改生产、不删失败路径或mock被测行为。最终两条归档的独立输入完整相等不是从生产读取/拼接 expected。

## 成本、合法性与剩余

无生产护栏、正文解析器、测试入口钩子或平行夹具，无新增测试函数；复用原四文件和游戏夹具。测试观察器均函数内局部，实际数据与原调用照常执行；不作为新通用件。官方 `https://docs.python.org/3/library/unittest.mock.html` 已读取，采用既有pytest monkeypatch与标准库inspect/AST，未新增依赖或适配层。

最小必要成本：给原作者入口增加消费身份观察、给月报入口增加字段消费观察、给原归档测试直接读取该边界、将原半档helper测试接回真实出口并删除同源expected。实际测试diff为112增16删（四文件）；CHANGELOG一行替换。本新回执不计作运行时机制。

未修改治理文件、宿主安装/配置/席位；未 amend、stash、rewrite、push、开PR或合并。三类本轮施工交付复审，仍须大理寺复裁收敛后方可并入家族底座；不把聚焦绿或候选扫描数字宣称为整票收官。
