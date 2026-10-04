# #1830 本轮修内司回执

本轮只交修理提交，未 merge、未 push、未开 PR；不宣告关票。冻结判词／回执没有覆写。开工时工作树已有八个文件的未提交改动，本轮保留并接续核验；下面统计包含这些已有改动。

## 枚举方法及边界

按现行票面全文检查：来源／记录身份、归档及去重、显式公开与真正排除；自由正文写出及实际读取；测试正文成员、行数／条数、哨兵、相等／不等、标题拆分、固定措辞、内部锁定、重复及同源筛选／渲染自证；实际消费端负向、失败传播与独立原文搬运；本票文档及新回执事实准确性。不是以点名符号为白名单。

全仓机械枚举产生的是候选，不是通过正则替代语义裁决。测试枚举无文件名、票号、措辞或断言形状过滤：所有 Assert 和函数定义均列出，再按上述契约与调用链核对。生产侧从仓内所有 Python 的读写／变换操作和排除相关引用枚举，跟踪至共用知识投影、三目录写手、真实模型入口、CLI cwd 和 API 工具。网页呈现及无关业务测试不因同文件或关键词相同而升级为本票授权。

执行的枚举／复扫命令：

```sh
rg -n 'knowledge_exclusions_for_source|source_projection|excluded_names|excluded_targets' ming_sim --glob '*.py'
rg -n 'read_text|write_text|open\(|strip\(|rstrip\(|lstrip\(|replace\(|splitlines\(' ming_sim server scripts --glob '*.py'
rg -n '(body|report|title|text|saying|source|content).*( in |==|!=)|( in |==|!=).*(body|report|title|text|saying|content)|splitlines|\.count\(' ming_sim/knowledge.py ming_sim/public_sayings.py
rg -n 'raw_facts|_experience_text|_person_audience_experience|_is_gazette_public_event|_write_public_by_month|def _.*(assert|render|text|directory|public)' tests --glob '*.py'
rg -l 'prepare_.*materials|read_material|public_events|knowledge_items_for_turn|get_character_knowledge|render_character_knowledge|public_saying|secret_order_brief|character_knowledge_(events|sources)' tests --glob '*.py'
rg -n '(#1830|整类|五类|净减|净增)' CHANGELOG.md evidence docs artifacts --glob '*.md'
```

无过滤测试枚举实际执行如下（输出在系统临时目录，不作为生产或测试机制）：

```python
import ast, pathlib
counts = {}; rows = []
for p in pathlib.Path('tests').rglob('*.py'):
    tree = ast.parse(p.read_text())
    for n in ast.walk(tree):
        if isinstance(n, (ast.Assert, ast.FunctionDef, ast.AsyncFunctionDef)):
            rows.append(f'{p}:{n.lineno}\t{type(n).__name__}\t'
                        f'{ast.unparse(n.test) if isinstance(n, ast.Assert) else n.name}')
            counts[type(n).__name__] = counts.get(type(n).__name__, 0) + 1
pathlib.Path('/tmp/1830-final-all-test-members.tsv').write_text('\n'.join(rows))
print(counts)
```

结果：FunctionDef 4738、Assert 13393、AsyncFunctionDef 44。最终排除引用候选 158 行、读写／变换候选 1784 行、知识／说法身份候选 15 行、helper 候选 72 行。这些数量仅描述搜索输出，不充当结清证明。

## 类成员与处置表

| 判词类别 | 实际成员／接缝 | 处置及保留依据 |
|---|---|---|
| 1 显式公开仍继承旧投影的人为排除快照 | db.knowledge_exclusions_for_source；persist_knowledge_items_for_turn；knowledge_items_for_turn；record_public_knowledge_event；knowledge.knowledge_row_visible_to、_source_archive_rows、build_character_knowledge | 在共同来源查询处跳过有注册来源的 source_projection 快照，回到来源的真正排除。没有注册来源的投影未生成参与者补集，保留其显式排除。物化、公开正文优先、结构化来源去重及真正私密 roster 读闸维持。没有加权限字段或第二名单。 |
| 2 材料读取仍转换自由正文换行 | materials._write_text、read_material、material_tools；prepare_character_materials、prepare_world_materials、prepare_scene_materials；agents.create_scene_agent/create_world_segment_agent/create_gazette_author_agent；month_chain.run_world_segment_text/run_gazette_text；cli_backend 的 materials_dir→cwd | 共用写手设 newline=''；共用读取以 Path.open(newline='').read() 原样返回。没有输入清洗。不用 Python 3.13 才支持的 Path.read_text(newline=...)，保持 README Python 3.11+、CI 3.12 契约。CLI 不另实现读工具。路径／身份 strip、判空副本及结构化 JSON 处理保留，不把它们误当自由正文删改。 |
| 3 测试仍有措辞假红及实际消费端负向漏检 | public_projection_consistency_1830 的来源与月载体；gazette_author_1862 的实际作者目录；character_knowledge_489 的真实物化；on_scene_immediate_write_1839 的事实撤回；secret_order_monthly_progress_566 的披露 | 月载体 oracle 改为独立写入原文，不从读侧重建。三目录磁盘、read_material、API 工具核同一原文。实际作者目录在真实 run_gazette_text 调用交给 create_gazette_author_agent 时捕获，恢复密令事实／案卷／经历／账的负向。撤回事实按 id，披露准入按 source_id；正文只核独立输入的完整搬运。 |
| 4 新增泛化筛选与渲染证明副本 | _public_month_text；_assert_author_directory_keeps_each_public_record（含 fact/event/secret-turn/账行筛选和渲染）；1837 的经历拼接循环；1847 的事实筛选拼接；1830 的工具同源相等证明 | 删除上述副本，复用既有 tracer bullet；不增测试案、夹具或生产钩子。_layer_paths/_public_layer 只枚举契约路径与载体归属，保留。作者捕获只读取实际目录，不实现准入规则。 |
| 5 新回执再次声明整类完成 | CHANGELOG 的 #1830 条目；本回执；终局工具回执 | 只报告具体行为及实测结果，不拿搜索完成或绿灯代替全仓无缺陷断言，不覆写冻结材料。名册正文授权及职位权限仍由 #1832 承接，不声称已修复。 |

全仓引用枚举得到的直接知识／材料测试文件（成员表，非仅本轮改动文件）：

- test_qa_1281_issue_audience_case_facts.py、test_decree_forecast_1861.py、test_dossier_links_559.py、test_audience_undo_506.py、test_faction_denunciation_627.py
- test_on_scene_immediate_write_1839.py、test_material_directory_1830.py、test_public_projection_consistency_1830.py、test_audience_background.py、test_mechanical_tail_1845.py
- test_month_chain_1847.py、test_scene_llm_1836.py、test_gazette_author_1862.py、test_audience_translation_1838.py、test_world_materials_1834.py
- test_declaration_dispatch_1835.py、test_person_delta_adapter.py、test_secret_order_monthly_progress_566.py、test_affairs_1831.py、test_character_knowledge_489.py
- test_month_chain_1843.py、test_surcharge_causal_chain_650.py、test_impeachment_surge_655.py、test_due_review_621.py、test_army_card_status_1501.py
- test_textual_facts_1828.py、test_audience_translate_1837_reopen.py、test_secret_order_update.py、test_public_sayings_1829.py、test_secret_order_isolation_883.py

保留项：489／883 的他人读面及共享持久存储负向；原始正文／长正文／原消息与持久来源的搬运；1830／1834 的路径、INDEX、开场、重备与恢复；1836／621 的 JSON 结构化召对事实（不是自由正文身份）；公事档案 military 等结构化键；API 路径拒绝与失败传播。军牌本体、财政计算等无关业务契约不在共用公开读链裁切类中。knowledge.current_court_roster_rows 中正文授权、人事职位权限属明确保留范围 #1832，本轮不改。

## 验证证据

所有 pytest／变异命令均使用同一强制前缀：

```sh
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -
```

变异均在独立解释器内修改函数绑定，不改工作树、冻结卷宗或配置。pytest.main 参数为 `-q -p no:cacheprovider`（后续批次另加 `--tb=short`）。

| 变异命令主体 | 真实入口与结果 |
|---|---|
| `git show HEAD:ming_sim/db.py` 提取旧 knowledge_exclusions_for_source，exec 后绑定回 GameDB | 原 489 公开测试：允许读者缺来源，1 failed in 1.00s。 |
| 令 read_material 保留真实路径解析，但返回 `target.read_text(encoding='utf-8')` | 原 1830 三目录测试：磁盘原文通过，实际读取转换 CR/CRLF 报红，1 failed in 1.40s。 |
| `month_chain.prepare_gazette_author_materials = prepare_world_materials` | 原真实过月作者入口：实际目录出现 SECRET_FACT_1862，必要负向报红，1 failed in 1.59s。这证明测试能检出该变异，不声称当前生产泄密。 |
| `git show cedbc1f69:ming_sim/knowledge.py`，exec 到 knowledge 模块 | 原 1830 入口缺 judge:henan，在结构化来源断言报红，1 failed in 1.14s。 |
| 将本轮查询变异为一律 `kind <> 'source_projection'` | 同一 489 案的独立投影显式排除失守，1 failed, 2 passed in 0.73s。证明不能以丢真正排除换取公开修复。 |
| 在已加载的 1830 测试中仅替换 shared 独立输入为另一合法公开正文，再执行原测试 | 原 1830 两案、489 三归属、566 既有测试共 14 passed in 1.40s，无固定正文行假红。 |

最终聚焦命令主体：`git diff --name-only 0ca77fecc HEAD -- tests` 的十八文件，加 1828、1281、1831、627、566 五文件；`pytest.main(['-q','-p','no:cacheprovider','--basetemp', 临时目录, *files])`。没有跑全量。

输出：`FOCUSED_FILES 23`；`PY_COMPILE_OK`；`419 passed, 1 skipped in 15.56s`；`FOCUSED_EXIT 0 DURATION 15.85`；`TEMP_CLEANED True`。作用域语法检查用 py_compile，pyc 写入同一个自建系统临时目录；本仓无此次适用的 Python 静态类型检查命令，未冒称完成 typecheck。

测试改动契约：既有入口对真实来源身份、真实物化的显式排除、实际消费树隔离和独立原文搬运负责。最小必要成本：复用现有案，只补两种显式排除归属参数和 CR/CRLF 输入，删除通用筛选／渲染副本；聚焦实测 15.85 秒。未新造通用件；采用 Python 标准库 newline 参数（官方 https://docs.python.org/3/library/functions.html#open 说明 newline='' 不转换读取到的行尾），没有网络或真实模型测试。

提交前查询：`git diff --check` 无输出；生产＋测试＋CHANGELOG 为 99 增、206 删、净减 107 行（十文件，未计本叙事回执）。待审边界仍是本票读侧与直接相关测试；未合并及后续庭审结论不由修内司代判。
