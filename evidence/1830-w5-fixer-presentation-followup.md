# #1830 修内司续办：区分输入原文与排版

本轮按 ce1b27fa4 冻结判词的 P2、P3 续修，保留既有生产修复。不修改生产呈现、治理文件、配置或冻结材料；不宣告整票结清、合并、关票。工作分支 `ak-roles/issue-1830-w5`，开工 `git status --short` 无输出。

## 类定义与全仓枚举

P2 按现行票面第2项全文核对：正文成员、行数／条数、哨兵、相等／不等、标题拆分、固定措辞推断身份／权限／完整性／底账裁切，内部锁定、重复及同源筛选／渲染自证；保留结构化来源、真实终端独立输入搬运、必要负向和失败传播。独立输入不能授权外围排版。P3 核本票文档与新交卷中的测试形态、保留理由及统计声明。

枚举不是正则判罪。执行下面无断言形状过滤的 Python 枚举，再核直接供料调用链及完整断言；另枚举非 Python 测试与叙事声明。临时扫描产物仅供调查，不加入仓库或测试机制。

```sh
python3 - <<'PY'
import ast,pathlib
rows=[]
for p in pathlib.Path('.').rglob('*.py'):
    if '.git' in p.parts: continue
    tree=ast.parse(p.read_text())
    for n in ast.walk(tree):
        if isinstance(n,(ast.Assert,ast.FunctionDef,ast.AsyncFunctionDef)):
            rows.append(f'{p}:{n.lineno}\t{ast.unparse(n.test) if isinstance(n,ast.Assert) else "def "+n.name}')
pathlib.Path('/tmp/1830-all-members.tsv').write_text('\n'.join(rows))
print('ENUMERATED',len(rows))
PY
rg -n 'assert|expect\(' --glob '*test*' --glob '*spec*' web server scripts
rg -l 'prepare_.*materials|read_material|public_events|knowledge_items_for_turn|get_character_knowledge|render_character_knowledge|public_saying|secret_order_brief|character_knowledge_(events|sources)' tests --glob '*.py'
rg -n '(#1830|整类|净减|净增|仅核|原文|渲染)' evidence/1830* CHANGELOG.md
```

输出：Python 定义／断言 21115 项；非 Python 候选 1715 行。首次误用本机不存在的 `python`，未产生扫描结果；改用 `python3` 才获得上述枚举，不把失败当完成证据。查看全仓读文件／expected／render／split／count 候选283行，并核正文相等、成员与拼接候选。这些数值不证明契约成立。

调用链关联测试文件表（均在 tests/）：

- test_affairs_1831.py、test_textual_facts_1828.py、test_secret_order_update.py、test_audience_translate_1837_reopen.py、test_qa_1281_issue_audience_case_facts.py
- test_secret_order_isolation_883.py、test_public_sayings_1829.py、test_month_chain_1847.py、test_audience_translation_1838.py、test_faction_denunciation_627.py
- test_mechanical_tail_1845.py、test_month_chain_1843.py、test_declaration_dispatch_1835.py、test_person_delta_adapter.py、test_scene_llm_1836.py
- test_impeachment_surge_655.py、test_audience_undo_506.py、test_on_scene_immediate_write_1839.py、test_audience_background.py、test_decree_forecast_1861.py
- test_dossier_links_559.py、test_surcharge_causal_chain_650.py、test_army_card_status_1501.py、test_world_materials_1834.py、test_secret_order_monthly_progress_566.py
- test_material_directory_1830.py、test_character_knowledge_489.py、test_public_projection_consistency_1830.py、test_due_review_621.py、test_gazette_author_1862.py

## P2 成员与处置

| 成员（修前位置） | 不成立的额外约束 | 处置 |
| --- | --- | --- |
| public_projection_consistency_1830:166,174–177 | 两条标题／正文冒号、顺序、换行的整段相等 | 去掉 expected 拼装；三目录磁盘、direct、API 各核独立输入标题及完整正文，不锁排版；source_id 和载体归属断言不变 |
| gazette_author_1862:320 | 两条事实固定顺序与拼接换行 | 各独立事实完整搬运；实际作者目录的密令负向不动 |
| gazette_author_1862:393 | 邸报正文尾换行 | 核独立作者输入 _REPORT 完整搬运；归档 title/report 字段相等仍核输入落库 |
| gazette_author_1862:394 | INDEX 路径、日期、标题的空格拼装 | 保留路径定位及日期、独立标题展示，不规定三者排版 |
| material_directory_1830:276 | 同类 INDEX 整段拼装 | 同上 |
| world_materials_1834:76–78 | 同类 INDEX 整段拼装 | 同上 |
| month_chain_1847:1900 | 独立事实搬运外的尾换行 | 核完整 fact_body 搬运，不约束额外空白 |
| public_projection_consistency_1830 文件说明 | 将月份渲染器拼装提升为契约 | 补正说明：来源、路径、搬运各自负责，不声称原文存在证明同正文次数 |

保留依据：883／489 的私密原始输入在他人读面或共享存储中的负向是隔离契约，不因出现正文成员自动删除；566 的 marker、sim_note 正例检查独立输入完整搬运，不是来源身份（来源另有结构化断言）；1837 的 query 为独立写入正文。raw-file API 测试1830:203,209 是直接写入文件的原文相等，没有拼装生产排版；JSON 字段／source_id／archive_key／路径集合是结构化契约。INDEX 路径解析用于现有目录调用协议，不由标题正文推断记录。财政、军牌业务与 relation_brew 等非共用公开读链的断言不升格为本票施工范围。非 Python 邸报候选属于网页展示、状态恢复及独立响应正文搬运，不是本票三目录筛选／渲染 oracle，未改。

限制明报：标题、完整正文在终端出现是搬运检查，不证明身份或权限。相同正文两来源在读侧的存在由 source_id 断言负责；本测试不计同一正文出现次数，也不证明标题正文关联。不能将这些局部证明概括为全仓语义完整性证明。未加计数、哨兵、参考渲染器、测试案、平行夹具或生产钩子。

## P3 补正成员

- `evidence/1830-w5-fixer-receipt.md` 类3「正文只核独立输入的完整搬运」不准确：当时月载体还夹带冒号、顺序和拼接换行；类4关于渲染副本删除也不能覆盖该残留。
- `evidence/1830-w5-fixer-followup.md` 的同形保留理由不准确：1830月载体并非仅独立原文核对；1830／1834／1862 INDEX 整段相等也附带了未获契约的排版，1862事实与1847事实另附加拼接／尾换行。
- 两份旧回执原样保留，本新回执补正上述依据；不重写历史统计或冻结材料。
- CHANGELOG 的月载体说明明确区分准入和原文搬运，删去可能被解读为整段渲染契约的概括。其他条目对直接持久字段的原文相等未改。

## 实际验证

官方 pytest 文档先以 curl 读取 https://docs.pytest.org/en/stable/how-to/capture-stdout-stderr.html（存系统临时目录）。本轮删简既有断言，不新造机制或通用件。

所有 pytest 调用命令前缀：

```sh
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false MING_SIM_PI_BIN=/usr/bin/false PYTHONDONTWRITEBYTECODE=1 /Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -
```

聚焦主体：TemporaryDirectory 内设 `tempfile.tempdir`，py_compile 五个改动测试文件（pyc 同临时目录）；`pytest.main(['-q','-p','no:cacheprovider','--basetemp',tmp+'/pytest',*files])`，files 为上表涉及的五文件。

输出：`53 passed in 6.36s`；`FOCUSED_EXIT 0 DURATION 6.62 SCOPE_SYNTAX_OK`；`TEMP_CLEANED True`。未跑全量或真实模型，未冒称 Python 静态 typecheck。

变异均独立解释器、沿既有真实测试入口、只改解释器绑定，不改生产文件。以下命令主体与结果可据 tool 调用核对：

1. `inspect.getsource(materials._write_public_by_month)`：把 `f"{title}：{body}"` 改为 `f"{title} — {body}"`，把 `"\n".join(lines)` 改为 `"\n\n".join(reversed(lines))`，exec 到 materials 命名空间。用 `git show HEAD:tests/test_public_projection_consistency_1830.py` 提取修前测试函数 AST，收集后绑定旧函数，再跑原入口：`1 failed in 1.01s`，旧174行报红，`MUTATION old-legal EXIT 1`。
2. 同一合法呈现变异跑当前原入口：`1 passed in 1.01s`，`MUTATION current-legal EXIT 0`。同时变更分隔符、顺序和拼接换行，不动原始输入。
3. read_material 真实返回值把 CR/CRLF 转 LF，再跑当前原入口：`1 failed in 0.95s`，完整独立正文在 direct 中缺失，`MUTATION newline EXIT 1`。搬运检查仍检出改字。
4. 只在 `_write_public_by_month` 的循环漏写 `judge:henan`，读侧 source_id 不动：`1 failed in 0.99s`，终端 disk 缺独立标题原文，`MUTATION loss EXIT 1`。这证明检出本次终端漏写变异，不冒称正文次数证明。
5. 共用 `_write_text` 仅传入 `text+'\n'`，原文不变，五文件当前聚焦：`53 passed in 6.16s`，`LEGAL_TRAILING_SPACING_EXIT 0`。

以上每批 `TEMP_CLEANED True`。初次当前聚焦为未变异独立进程，不把批内旧函数残留当恢复证据。复扫及 `git diff --check` 无格式错误；生产文件无 diff。提交前五测试＋CHANGELOG 为24增23删，净增1行；不宣称净减。叙事回执另计。

## 未结与交卷边界

本轮处置上述授权内呈现锁定及保留依据；未发现需要另增机制的修法。#1832名册授权、#1834／#1833及#1861／#1840／#1843接线归属保持票面，不声称已替邻票修复。合并、发版、真宿主验收与庭审结论尚不属本轮已完成事项。扫描、语法检查或53案绿灯均不替代契约证明。
