# #1830 INDEX 续修回执

基线 `a6fbc2d769b0b64b4bc105b0e536270c008f949a`；开工 `git status --short` 无输出，另开 `ak-roles/issue-1830-index-followup`。只修改七个既有测试文件及本新回执；生产呈现、治理文件、配置、冻结材料不动。本轮不宣告整票结清、合并或关票。

## 授权与类定义

读取两份本 run 附件（00 sealed1、01 最终），并以 `gh issue view 1830 --repo Akagilnc/ming-salvage-sim --json body,title` 查询现行票面。P2 沿用票面第2项全文：正文成员、行数／条数、哨兵、相等／不等、标题拆分、固定措辞推断身份／权限／完整性／底账裁切；内部锁定、重复与同源渲染器自证；不缩为固定空格一种形状。必要负向、失败传播、结构化来源／载体归属、真实读取及独立原文搬运保持。P3 核本票文档与新回执的事实、保留依据、净增减和未结声明。

已读归位后的诊断原文：`~/.ak-roles/books/Ming_LLM/1830/runs/01a0f5d7-a9ae-755d-ade3-e3cca6109f3a@secretariat/attachments/01-1830-local-patch-loop-diagnosis.md`（旧 unbound 指针 ENOENT 后在本票目录找到）。承接其范围收窄／证明换形问题，不重新诊断、不实施其工厂机制建议。根因已由判词亲验，诊断 skill 的重新假设／新增回归案步骤不适用；复用既有入口做变异反馈与清理。

## 全仓枚举与复扫命令

先枚举全仓 Python 断言，再枚举定义与比较（含 helper 内推断），不以点名文件或 `rel + " "` 过滤类成员。候选按是否属于共用公开读侧／直接供料接缝及其证明用途核对，不由正则自行裁决。以下命令均已执行；扫描数量不作契约证明。

```sh
python3 - <<'PY'
import ast, pathlib
rows=[]
for p in pathlib.Path('.').rglob('*.py'):
    if any(x in p.parts for x in ('.git','node_modules')): continue
    try: tree=ast.parse(p.read_text())
    except (SyntaxError,UnicodeDecodeError): continue
    for n in ast.walk(tree):
        if isinstance(n,(ast.Assert,ast.FunctionDef,ast.AsyncFunctionDef,ast.Compare)):
            text=(ast.unparse(n.test) if isinstance(n,ast.Assert) else
                  ast.unparse(n) if isinstance(n,ast.Compare) else 'def '+n.name)
            rows.append(f'{p}:{n.lineno}\t{text}')
pathlib.Path('/tmp/1830-all-members-rescan.tsv').write_text('\n'.join(rows))
PY
rg -n 'assert|expect\(' --glob '*test*' --glob '*spec*' web server scripts
rg -l 'prepare_.*materials|read_material|list_materials|index_lines|public_events|knowledge_items_for_turn|get_character_knowledge|render_character_knowledge|public_saying|secret_order_brief|character_knowledge_(events|sources)' tests --glob '*.py'
rg -n 'index_lines|INDEX\.txt|_gazette_index_line' .
rg -n 'expected|render|split|len\(|\.count\(|not in|==|startswith' /tmp/1830-scope-assertions.tsv
rg -n '1830|INDEX|整类|净增|净减' evidence docs artifacts --glob '*.md'
rg -n '(#1830|整类|净减|净增|仅核|原文|渲染|INDEX)' evidence/1830* CHANGELOG.md
```

直接读链及证明候选文件表（均在 tests/）：

- test_material_directory_1830.py、test_public_projection_consistency_1830.py、test_world_materials_1834.py、test_character_knowledge_489.py、test_public_sayings_1829.py
- test_gazette_author_1862.py、test_month_chain_1843.py、test_month_chain_1847.py、test_mechanical_tail_1845.py、test_decree_forecast_1861.py
- test_audience_translate_1837_reopen.py、test_audience_translation_1838.py、test_scene_llm_1836.py、test_on_scene_immediate_write_1839.py、test_qa_1281_issue_audience_case_facts.py
- test_secret_order_isolation_883.py、test_secret_order_monthly_progress_566.py、test_secret_order_update.py、test_dossier_links_559.py、test_audience_undo_506.py、test_audience_background.py
- test_textual_facts_1828.py、test_affairs_1831.py、test_declaration_dispatch_1835.py、test_due_review_621.py、test_impeachment_surge_655.py、test_faction_denunciation_627.py
- test_person_delta_adapter.py、test_surcharge_causal_chain_650.py、test_army_card_status_1501.py、test_llm_channel_config.py；初次调用链扫描还包括 test_audience_continuous_507.py、test_secret_dossier_participants_1252.py、test_player_army_projection_321.py。

生产复查 `knowledge.py` 来源去重、`db.py` 来源与排除归属、`materials.py` 公共写手／列读／索引；当前身份和载体选择仍由 source_id、年月及对象归属承担，INDEX 不作为实际读工具的路径语法。非 Python 候选未发现调用上述材料／公开投影接缝；不借本票改网页展示、财政计算或军牌业务。

## P2 成员表与处置（位置为修前基线）

| 成员 | 错误形状 | 处置 |
| --- | --- | --- |
| material_directory_1830:54–67 | INDEX 固定行成员／前缀及空格猜路径 | 删除解析；按 list_materials 返回路径真实读取，每份含 INDEX 可读 |
| material_directory_1830:165 | 从展示 index_lines 推断事务载体集合 | 改用 list_materials；真实可见投影 id 与路径集合断言保持 |
| material_directory_1830:267–277 | 空格定位邸报行，再检查格式化月标签和标题 | 删除定位及月标签措辞；只核独立写入标题在完整 INDEX 中原样搬运 |
| world_materials_1834:55–77 | 同形空格识别、月标签与展示行证明 | 删除；已有真实列目录／读取保留，独立入档标题直接核完整 INDEX |
| world_materials_1834:243–265 | 把事实／事务／邸报／独立说法路径等同 INDEX 文本行 | 删除展示集合及四条重复包含证明；文件树路径、typed store、载体排除保持 |
| public_projection_consistency_1830:148–155 | 解析场景 INDEX 推断每个材料载体 | 删除；API 列目录与文件树一致、source_id、三目录载体归属及磁盘／direct／API 原文搬运保持 |
| gazette_author_1862:385–411 | 邸报行空格定位及经历／盘面从 index_lines 选路径 | 删除定位／展示月标签；独立标题核完整 INDEX，经历及盘面从真实 list_materials 选择读取；实际作者目录私密负向不动 |
| audience_translate_1837_reopen:368–372 | 由展示 index_lines 判经历载体 | 用真实 list_materials；交办 query 原文读取保持 |
| month_chain_1847:1893–1900 | 同形文字事实载体证明 | 用真实 list_materials；独立 fact_body 搬运保持 |
| qa_1281_issue_audience_case_facts:60–61 | 已证明文件树事务路径后再用 index_lines 重复证明 | 删除两条重复断言；可见性、来源、audience_names 及实际路径集合保持 |

不是将空格换成 TAB／其他分隔符白名单，也不新增正文解析、参考渲染器、夹具、测试案或生产钩子。共同原因是把人读索引当成机器目录；复用已有列目录入口即足够。互联网先查 Python 官方 pathlib 文档（`curl -L --max-time 20 -s https://docs.python.org/3/library/pathlib.html -o /tmp/1830-pathlib-doc.html`），仓内已有 list_materials，无需新造通用件。首次尝试本机 `python` 不存在；实际扫描和语法检查用 python3，pytest 用现有 venv。

复扫保留项：

- tests 中 index_lines 的运行用法仅剩 llm_channel_config 的空 PreparedMaterials 构造；不解析内容。material_directory 文件说明中的字段名只是说明。
- 1830／1834／1843 的 INDEX 文件存在、非空与真实读取；1501 只从文件树排除 INDEX 自身。它们不约束展示排版。
- 三处完整 INDEX 的独立入档标题搬运，不证明路径定位、标题与月份关联、记录次数或准入。年月归属由文件树年月路径承担。该搬运不是固定标题措辞推断身份。
- 489／883 共享存储及他人读面、1862 实际作者目录的必要私密负向；路径拒绝及读取失败传播不删。已结生产身份／公开优先／排除归属／换行搬运不重做。
- 原始输入的持久字段相等、566 披露输入片段和1837交办原文是搬运；来源另由 id/source_id 负责。财政／军牌计算、名册与职位权限不是本票重设对象。结构化 JSON 字段（如世界派系事实文件）不是自由正文解析。

## P3 补正成员及第三项承接

| 旧材料 | 补正（旧材料原样保留） |
| --- | --- |
| evidence/1830-w5-fixer-presentation-followup.md:47–49 | 「不规定三者排版」不准确：基线仍用固定空格定位。现在删除整段展示定位，而非换分隔符 |
| 同文件:53 | 「INDEX 路径解析用于现有目录调用协议」不成立；实际读取只接受文件树相对路径，展示行不是路径 |
| evidence/1830-w5-fixer-followup.md:26；evidence/1830-w5-fixer-receipt.md:59 | INDEX 保留依据不能概括为路径／日期／标题语法契约；正确保留面仅是载体存在、真实读取、独立标题搬运，路径以实际列目录为准 |
| 七测试中的同形说明 | 改正 INDEX 一致性／展示日期被当契约的说明，明示真实文件树与原文搬运各自负责 |

最终判词第三项原文：「“原变异为字面反斜杠t”的事实纠错不成立」；disposition：「不采纳该项事实纠错；原实体裁决维持，回送审刑院复核，不绕站派施工。」本轮不主张历史变异为字面反斜杠t，不改冻结机器记录，不代审刑院裁决。下述 probe 是本轮新独立复验，不拿其字符数量重解释历史调用。

## 实际验证与成本

临时 probe `/tmp/1830-index-probe.py` 仅独立解释器绑定，不写生产文件。每次以下完整前缀调用：

```sh
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$PWD" /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python /tmp/1830-index-probe.py MODE
```

主体用 TemporaryDirectory 隔离 tempfile.tempdir 与 `pytest.main(['-q','-p','no:cacheprovider','--basetemp',temp+'/pytest',*entries])`。五个既有入口：1830 typed_tree、1830 exclude_legacy_raw_turn_report、1834 typed_tree、1862 author_archives_own_title、1830 scene_person_public_layer（完整函数名见上述成员文件）。old-tab 从 `git show a6fbc2d76:文件` 取原函数 AST，在 pytest 实际收集模块的命名空间编译并绑定 item._obj；不 mock 被测备料行为。

TAB 变异仅将 `_gazette_index_line` 的两个 f-string 分隔空格改为实际 chr(9)：`f"{rel} {label} {shown}"` → 路径、label、shown 三者以 TAB 相隔，另一无 label 分支也改 TAB。路径、月份、标题原文及一行一项不动。本轮源码 `ACTUAL_TAB_COUNT 3 LITERAL_BACKSLASH_T_COUNT 0`（含另一分支），`TITLE_RETAINED True ONE_LINE True`。

| MODE／命令 | 实测输出 |
| --- | --- |
| old-tab：装回基线断言，同一真实备料入口 | 4 failed, 1 passed in 2.58s；EXIT 1；实际四个既有判词入口失败于 INDEX 定位 |
| current-tab：当前删简断言，同一 TAB 变异 | 5 passed in 3.83s；EXIT 0；墙钟4.20s |
| title-loss：只令索引写手返回 rel、丢独立标题 | 3 failed, 2 passed in 2.37s；EXIT 1；三处原文搬运仍报红 |
| read-corruption：实际 read_material 返回值 CR/CRLF 改 LF | 1 failed in 0.98s；EXIT 1；三目录原文读取断言仍报红 |
| restored：新独立进程，无任何变异 | 5 passed in 3.74s；EXIT 0 |
| focused：七个修改测试文件＋test_month_chain_1843.py | 93 passed in 11.06s；EXIT 0；墙钟11.37s |

每批输出 `TEMP_CLEANED True`；交卷前清理本轮自建 `/tmp/1830-index-probe.py`、日志、扫描清单和官方文档缓存，不清理任何既存材料。七个改动 Python 文件逐个 `compile(Path(name).read_text(),name,'exec')`：`CHANGED_PYTHON_SYNTAX_OK 7`；不是静态 typecheck。未跑全量、网络测试、真实模型、真实宿主验收。测试最小必要成本：修改既有入口、删除索引解析和重复证明，不加任何案或机制。

提交前 `git diff --numstat`：七测试25增88删，净减63行；本叙事回执另计。`git diff --check` 无输出；`git diff -- ming_sim CLAUDE.md AGENTS.md CONTEXT.md docs/adr` 无输出。不把扫描数量、绿灯或净减当成全票语义完整性证明。

## 未结

本轮 P2／P3 按上述成员处置并提交复核；第三项历史事实异议仍须按最终判词回送审刑院，不由修内司绕站裁决。#1832名册与职位权限、#1834／#1833及#1861／#1840／#1843票面归属保持，转交不等于修复。庭审收敛、合并、发版和真宿主验收不在本轮已证明范围。
