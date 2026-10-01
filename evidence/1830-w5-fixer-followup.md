# #1830 续办回执：披露正文断言

本轮回应续办判词，仅修改测试；生产修复保留。前轮 2a2a95851 新增披露整段相等确实复制了生产渲染模板，前轮类 3、4 的完成表述对此不成立。本回执补正，不覆盖前轮及冻结材料；不宣告整票结清、合并或关票。

## 处置

| 成员 | 根因与处置 |
| --- | --- |
| secret_order_monthly_progress_566 的披露测试 | 删除按生产模板构造的整段相等。独立写入 marker、sim_note，分别核各自完整原文存在于按 source_id 取得的披露正文；不约束二者之间的括号、分隔符或顺序。保留披露前结构化来源负向。 |
| on_scene_immediate_write_1839 的 facts／sayings 条数 | 本案契约是独立正文落库及搬运，不是结果集合恰好一条。删去两条 len==1，不换成其他计数或存在性证明副本；既有取记录及原文相等已检出没有落库。撤回测试按 id 的证明不变。 |

## 同形复扫

沿用前轮机械枚举的 30 个知识／材料文件，包含判词两文件及其余 28 文件；先 rg 枚举 f-string 相等、join、helper，再以 AST 遍历断言，人工核对候选的输入与生产来源。435 条候选不代表 435 条缺陷，也不作为结清证明。

命令（`files` 为下列 30 文件，均在 tests/ 下）：

```sh
rg -n 'assert.*(==|!=).*f["\x27]|expected.*join|def .*render|def _.*text|expected.*\[' $files
```

AST 复扫：对每文件 `ast.parse`，遍历 FunctionDef/AsyncFunctionDef 内 Assert，将 `ast.unparse(n.test)` 含 body/text/report/blob/title/marker/split/count/len( 的候选列出，核对完整断言与调用上下文。此为调查脚本，不进入测试机制。

成员：test_qa_1281_issue_audience_case_facts.py、test_decree_forecast_1861.py、test_dossier_links_559.py、test_audience_undo_506.py、test_faction_denunciation_627.py、test_on_scene_immediate_write_1839.py、test_material_directory_1830.py、test_public_projection_consistency_1830.py、test_audience_background.py、test_mechanical_tail_1845.py、test_month_chain_1847.py、test_scene_llm_1836.py、test_gazette_author_1862.py、test_audience_translation_1838.py、test_world_materials_1834.py、test_declaration_dispatch_1835.py、test_person_delta_adapter.py、test_secret_order_monthly_progress_566.py、test_affairs_1831.py、test_character_knowledge_489.py、test_month_chain_1843.py、test_surcharge_causal_chain_650.py、test_impeachment_surge_655.py、test_due_review_621.py、test_army_card_status_1501.py、test_textual_facts_1828.py、test_audience_translate_1837_reopen.py、test_secret_order_update.py、test_public_sayings_1829.py、test_secret_order_isolation_883.py。

同形候选保留依据：1830／1834／1862 的目录 INDEX 比较属于既有路径、日期、存储标题契约，不是披露散文模板；883:258 的 f-string 是独立写入的原消息，非生产渲染 oracle；1862 的事实文件由独立事实原文写入，非从消费端重新筛选渲染；489 的 archive_key 和 issue／origin_ref 比较是结构化身份。其他正文相等核独立写入原文搬运；业务结果条数不因出现 len 自动等同生成物计数。军牌和财政业务等保留前轮授权边界，不借此次续办扩改。复扫未发现第二处与本轮披露整段相等相同的渲染模板复制实例；不以此声称全仓绝无遗留。

## 验证

所有测试及变异均强制七个 `MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false`，同时 `PYTHONDONTWRITEBYTECODE=1`。解释器为 `/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`；`pytest.main` 参数 `-q -p no:cacheprovider --basetemp <自建临时目录>`；变异另用 `--tb=short`。临时目录由 TemporaryDirectory 清理，不修改配置或生产文件。

变异真实入口：既有 `test_disclosure_promotes_monthly_report_to_public_event_only_after_disclosure`。解释器内取 `inspect.getsource(decree_vocabulary.format_public_progress_disclosure)`，仅将换行 join 分隔符改为双换行、`【band】` 改为 `(band) `，exec 后绑定给 issues 同名函数。来源、准入及独立正文不变。

- 以 `git show HEAD:tests/test_secret_order_monthly_progress_566.py` 取前轮函数 AST，绑定回已加载测试模块：**1 failed in 0.65s**（实际 0.75 秒），失败在旧整段相等。
- 当前函数，同一合法渲染变异：**1 passed in 0.60s**（实际 0.69 秒）。未放松独立原文搬运。
- 最后删去冗余存在性断言后的两文件聚焦：**14 passed in 0.87s**（实际 1.10 秒）；作用域 compile 检查 `SCOPE_SYNTAX_OK`。未跑全量，未冒称 typecheck。

测试契约：披露来源准入保持结构化判断，两个独立输入原文完整搬运且不锁渲染模板；事实落库不额外规定记录数量。最小必要成本：修改既有两案，不新增测试、夹具、生产钩子或通用件。续办只报告此 finding 的处置与聚焦验证，后续庭审不代判。
