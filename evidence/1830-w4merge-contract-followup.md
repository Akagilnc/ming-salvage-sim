# #1830 消费裁切与独立输入搬运续修

基线 `e169af0b5559cadfc90b77217121d0d094ee7a3e`，工作分支 `ak-roles/issue-1830-w4merge`。仅修现有测试与当前事实说明，不改生产逻辑，不宣告整票收敛、合并或关票。

## 类定义、枚举与成员

R1 沿用「必要负向覆盖被删除或转移到另一读面」，不是仅查户部函数：核公开来源、共享归档、作者实际供料、底账消费、场景／单人／世界材料与失败传播。R2 沿用「原样搬运契约退化为载体存在或字段已读取」，不是仅查长密令：核独立输入→真实持久／投影／材料读取出口；不恢复身份或权限正文 oracle、渲染副本、正文行集、TAIL 哨兵及重复长夹具。

机械枚举命令：`python3 /tmp/1830-enumerate-current.py`；全仓 `git ls-files` 中每个 Python 文件用 AST 遍历**全部**函数及 Assert，不先按符号筛掉文件；对 `git diff --name-only <revision> HEAD -- tests` 的每个文件，比较同名函数的旧／现全部断言（含嵌套 helper、消失函数），两基线为 `2f20f18bd`、`88d114e21`。不存在于旧基线的新文件跳过历史比较，但仍参加当前枚举。脚本的核心谓词如下，非关键词白名单：

```python
for name in subprocess.check_output(['git', 'ls-files'], text=True).splitlines():
    if not name.endswith('.py'): continue
    tree = ast.parse(pathlib.Path(name).read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            assertions = [ast.unparse(n.test) for n in ast.walk(node)
                          if isinstance(n, ast.Assert)]
# 每个历史函数：old_assertions 中不在 current.get(function_name, []) 的项均枚举。
```

复扫独立节点统计：360 Python 文件，FunctionDef 7777、AsyncFunctionDef 97、Assert 13721、Call 75654、Compare 21140。函数断言目录含嵌套重复计入，235 有断言文件、3117 函数、13801 条；不能与独立 Assert 数混称。历史比较分别104、46个函数发生断言移除／改写；计数是候选，不是缺陷数量。

其他扫描命令：

```sh
git diff 2f20f18bd HEAD -- tests
rg -n '(assert|expect\(|to(Equal|Contain|Be)|read_material|prepare_.*materials|material_tools|source_id|origin_ref|excluded_|dossier_progress|\.content|\.body)' --glob '!*.py' --glob '!*.md' --glob '!*.json' --glob '!*.svg' --glob '!*.lock' .
rg -n '(原样|搬运|负向|裁切|F1|结清|01a0f1f4)' evidence/1830* CHANGELOG.md
```

非 Python 候选1844行，当前／历史声明84行。语义复核同时看实际写手及真实调用链，不把枚举后的关键词导航当类定义。变更测试30文件的全部历史断言差异已检查；非 Python 读面没有发现本轮两种退化的新成员。

| 类 | 全部本轮缺陷成员（测试名） | 处置／实际边界 |
| --- | --- | --- |
| R1 | `test_character_knowledge_489.py::test_household_secret_ledger_keeps_amount_but_hides_case_semantics` | 真实 `get_character_knowledge` 及 `prepare_character_materials` 消费 SQLite 流水；数额／余额正向，reason／category 负向。保留案卷准入，但不拿它代证裁切。 |
| R1 | 同文件 `test_household_secret_ledger_hides_case_by_excluded_office` | 原户部与继任户部均核实际字段消费；继任前清空观察集合，防止原户部调用冒充继任证明；他职 treasury 缺席负向保留。 |
| R2 | `test_material_directory_1830.py::test_secret_order_materials_keep_full_content_and_fail_loud_on_db_error` | 独立输入经真实密令写手→`material_tools` API读文件完整搬运；不钉外围标题、换行拼接或条数；原 DB 异常传播保持。 |
| R2 | `test_on_scene_immediate_write_1839.py::test_textual_fact_and_public_saying_land_and_show_in_materials` 的文字事实与公开说法两个出口 | 同类额外成员：此前只核持久 body 及材料路径，未证明下一句场景目录搬运；复用原独立输入，分别从确定的事实／月份载体真实读取，不从正文推断权限。 |

保留项及依据（不是缩小类边界）：

- 489 来源公开／密令排除、撤回、恢复、来源归属及883密令隔离：原消费读面已有 source_id／持久来源缺席断言；共享归档两案直接核 `get_turn_report_archive(...)[report]` 独立输入，不转移到人物读面。1862作者事实、经历、召对及开场案卷观察真实写手消费；国库排除参数本来只证明调用输入，不提升为消费结果语义证明。566 `dossier_progress` 的不消费是必要负向，保留；title/content 已读不再冒领搬运证明，密令搬运由1830真实API出口承担。
- 1830 public_projection 的三目录磁盘／direct／API独立原文搬运、883原消息／简报持久字段、489公开说法及报告归档、650自由报告、1847独立事实材料、1862作者事实／报告均已有独立输入断言，保持；不重复长正文夹具。
- 1837查访独立输入已有 `test_inquiry_declaration_preserves_assignment_in_attendant_materials` 贯穿事件body及材料read；`test_separate_inquiries_same_turn_survive_and_retry_is_idempotent` 另保来源身份与重试，不为同一搬运契约重复造案。1838分段可闻性、539／544场景滑卷身份负向各在原结构化出口；不恢复正文身份 oracle。
- 1834世界实况路径、候选／请旨目录、1830／1834开场、重备／恢复、1843 API／CLI同树及路径拒绝、读取失败传播仍保原契约；未因载体非空就声称逐条完整性，亦不为已结纯路径整理新造正文证明。173／321／1501、firearms及CLI独立军备契约已恢复，未改；名册准入及职位权限仍归1832。
- 历史正文权限、固定军牌措辞、INDEX解析、同源重渲染断言不恢复；此次新增的完整原输入比较只证明搬运，不能证明记录身份、授权或叙事语义。

## 当前说明与历史归因更正

`test_material_directory_1830.py` 旧271行把「只核非空」归于01a0f1f4，不成立；该裁决不驳回独立原文API／CLI搬运。已删除错误注释、恢复真实API搬运。`1830-w4merge-boundary-followup.md` 的成员表遗漏户部消费两案，其 F1 不能沿用为整类结清；`1830-w4merge-fixer-class-followup.md` 关于材料独立原文搬运保留的概括不能覆盖此前密令只读非空和1839只核持久body。CHANGELOG同步明确实际消费及出口，本回执补正，历史文件和冻结回执不覆写。

## 验证

所有 pytest 均用以下七旗；未调真实模型／宿主，未跑全量：

```sh
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python ...
```

聚焦命令：上述前缀 `-m pytest -q -p no:cacheprovider tests/test_character_knowledge_489.py tests/test_material_directory_1830.py tests/test_on_scene_immediate_write_1839.py tests/test_secret_order_monthly_progress_566.py tests/test_public_projection_consistency_1830.py tests/test_gazette_author_1862.py tests/test_world_materials_1834.py tests/test_audience_translate_1837_reopen.py`：**105 passed in 7.01s**。四个触及入口单跑：**4 passed in 1.24s**。

独立进程变异命令：同一前缀 `/tmp/1830-contract-probe.py MODE prior|current`；prior在collection仅绑定 `git show HEAD:<test_file>` 的原测试函数，current用工作树；真实生产函数只在解释器内变异，不写生产文件。每次 `TemporaryDirectory` 输出 `TEMP_EXISTS False`。

| MODE／仅改一处 | 修前测试 | 当前测试 |
| --- | --- | --- |
| hide：`_household_secret_case_hidden` 恒False | 2 passed，0.76s | 2 failed，0.75s，实际reason消费报红 |
| successor：只对继任户部返回False，原户部裁切不变 | 1 passed，0.99s | 1 failed，0.78s，仅继任reason消费报红 |
| truncate：实际密令写手 `lines.append(content[:80])` | 1 passed，0.68s | 1 failed，0.67s，API缺完整输入 |
| drop：保留实际content读取，再 `lines.append("")` | 1 passed，0.68s | 1 failed，0.69s，API缺完整输入 |
| scene-fact：真实写手只丢按月实况body | 1 passed，0.69s | 1 failed，0.70s，事实材料出口报红 |
| scene-public：真实写手只丢公开说法body | 1 passed，0.75s | 1 failed，0.70s，月份材料出口报红 |

hide/prior探针最初因旧函数签名不接受新fixture报TypeError，随后直接赋值冻结fixture信息报FrozenInstanceError，均不作为行为证据；改以 `dataclasses.replace` 使用原函数参数后重跑，结果才是表中2 passed。恢复真实逻辑的绿证据为上述105案聚焦。

诊断skill的阶段1–4不重复：冻结判词已有独立变异定位和确定根因，本次无未知生产根因；阶段5复用真实入口修测试断链、阶段6复跑绿灯并清理。互联网先读Python官方sqlite3的row_factory说明（`curl -Ls https://docs.python.org/3/library/sqlite3.html -o /tmp/1830-sqlite-doc.html`）；仓内已有566/1862真实消费观察，采用标准库 `sqlite3.Row` 子类和连接现有row_factory，保留原行值，不写替代裁切器或渲染器。未新增通用件／生产钩子／测试案。三文件修改只增加一个两案共用观察fixture及必要断言，余项复用原夹具；测试成本为既有8文件7.01秒，不建平行测试。

本轮生产代码零改动；测试diff为53行增加、9行删除，净增44行，不宣称净减。没有恢复重复长夹具、哨兵、正文行集或同源渲染比较。

三处变更Python用 `compile(Path(f).read_text(), f, 'exec')`：`CHANGED_PYTHON_SYNTAX_OK`；这是语法检查，不冒称静态typecheck。`git diff --check`无输出。自建13个 `/tmp/1830-*` 票面缓存、扫描清单、官方文档缓存与探针已逐个清理，命令查询输出 `OWN_TEMP_FILES_REMAIN 0`；每次变异目录均自行释放。不清理任何既存材料。后续只提交本分支供复审，不push、不PR、不amend、不stash、不改宿主安装配置或席位表。
