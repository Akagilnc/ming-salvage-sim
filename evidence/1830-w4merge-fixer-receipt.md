# #1830 组合候选修理回执

## 基线与授权

本轮在专设修理分支 `ak-roles/issue-1830-w4merge` 施工；开工 HEAD `2f20f18bdb4dcb5083bb974a700a627bf73421fc`，进行中的 MERGE_HEAD `a6fbc2d769b0b64b4bc105b0e536270c008f949a`。五个 UU 文件是 materials、due_review_621、gazette_author_1862、month_chain_1843、month_chain_1847。按派单及冻结大理寺判词 F1/F2 逐块收口，不撤销合并、不整文件择边。本分支不是家族底座；本回执仅申报派工修理，不申报全票收官。

已读取本机两份全局规则、仓级 CLAUDE.md、CONTEXT.md 相关领域词表、ADR 0034/0155、fix-packet 与两份冻结附件。裁定类别与边界原样承接；没有新增产品设计或改动治理文件。

## F1：身份供料退役接缝

根因：身份写手仍导入已退役的综合渲染器，真实 run_secret_orders_supply 入口因 ImportError 失败。保留供料调用，不恢复 render_character_knowledge、见闻.txt 或综合正文。

扫描范围：materials.py 的人物、场景、世界写手，knowledge.py 的身份/事务准入，month_chain.py 的身份供料及 4a 生命周期，agents.py 的读取说明；tests 中材料、查案、月链、邸报、知识与密令边界用例。按 identity_material_rel/write_identity_materials/materials_path/此刻所知/render_character_knowledge 搜全接缝，确认运行代码不再引用退役渲染器；仅保留解释退役原因的历史注释。

修法：materials_path 指向 `人物/<安全身份>/可及材料/INDEX.txt`。身份子目录直接复用既有 _write_tree，正文仍分列本人经历、公事档案、可见事务、公开材料及既定辅助载体；人物常规入口与身份写手共用提取出的 _character_material_projection，知识与事务准入不另写一份。主索引只增加身份索引路径。既有显式排除、定性投影和完整历史写手均未改规则。供料 prompt 说明先列本人子目录获取相对调用根目录的实际路径，再取阅文件，避免把索引所在子目录的展示路径误读成世界材料路径。

复用并扩充既有真实 4a 用例：仅替代外部模型边界，实际备树、供料、身份投影、列读与清理照生产走。两条事务分别授予本人并显式排除另一方；断言双方实际子目录的事务路径集合与合法可见投影相符、两读口读同一文件、经历/公事档案存在可读、不含盘面载体；不解析人读索引。实际公事档案读取故障原异常传播且本次树清理，成功调用亦清理。

## F2：合并遗漏收敛续修

用 `git diff a6fbc2d76 66ada2444` 取出已署续修差异，先 `git apply --check` 后逐差异补入；没有用该提交整文件覆盖目标增量。七个既有测试的 INDEX 文本解析/重复证明删简及 `evidence/1830-index-contract-followup.md` 一并承接。该文件和 w5 三份回执是各自历史轮次的报告，不冒称其中历史命令是本轮执行结果；本轮事实以本文件为准。

冲突块采用真实结构化身份断言而非正文哨兵；世界段两读口测试保留目标侧盘面可读、CLI cwd 指向备树的增量，改以 prepare 返回 opening 的搬运验证接线，不从盘面正文搜 instructions。修正源侧合并后遗留的 has_dir 键为实际捕获的 dir_has_index；不放松 API/CLI 边界。

复扫范围包括所有 tests 中的 INDEX、index_lines、splitlines 与展示路径推断。额外发现目标侧 #1892 候选/请旨目录两例仍将人读 INDEX 行集等同文件路径集，同类删除解析，保留实际列目录、读索引和载体；请旨集合改以权威候选 ID 对应的安全路径断言。#1892/#1893 的候选供料及其他目标增量不撤销。保留的 INDEX 断言只涉及载体存在/可读及独立标题原文搬运；工具 list_materials 的字符串协议是结构化路径接口，不是人读 INDEX。

## 本轮验证

所有 pytest/probe 命令均有以下七旗前缀，并设 PYTHONDONTWRITEBYTECODE=1；未真调宿主或模型：

```sh
env MING_SIM_AGY_BIN=/usr/bin/false MING_SIM_CODEX_BIN=/usr/bin/false MING_SIM_CLAUDE_BIN=/usr/bin/false MING_SIM_CURSOR_BIN=/usr/bin/false MING_SIM_KIMI_BIN=/usr/bin/false MING_SIM_GROK_BIN=/usr/bin/false MING_SIM_PI_BIN=/usr/bin/false
```

解释器 `/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python`。常规测试参数 `-m pytest -q -p no:cacheprovider --tb=short`；临时 probe 设 PYTHONPATH=$PWD，并以 TemporaryDirectory 隔离 pytest basetemp。

| 命令/入口 | 实测输出 |
| --- | --- |
| 初始真实 4a 单例（解 materials 冲突标记后） | 1 failed in 1.12s，ImportError: render_character_knowledge |
| `/tmp/1830-identity-mutation.py old`：仅在独立解释器装回 HEAD 旧身份写手，同一真实 4a 入口 | 1 failed in 1.07s，EXIT 1，同一 ImportError |
| 同 probe restored：当前写手，同一扩充用例 | 1 passed in 1.35s，EXIT 0 |
| `/tmp/1830-index-mutation.py old`：INDEX 每项只加人读项目符号，文件/路径/标题不动；装回 a6fbc2d76 三个旧断言及目标 HEAD 候选/请旨两例 | 5 failed in 2.11s，EXIT 1，均失败于展示路径解析 |
| 同 probe restored：当前断言，仍保持该展示变异 | 5 passed in 2.23s，EXIT 0；此模式不是无变异生产结果 |
| 第一批聚焦：material_directory_1830、public_projection_consistency_1830、world_materials_1834、character_knowledge_489、secret_order_payoff_1504、gazette_author_1862、month_chain_1843、month_chain_1847、due_review_621、qa_1281_issue_audience_case_facts、audience_translate_1837_reopen、secret_order_isolation_883 | 279 passed in 13.49s |
| 第二批聚焦：army_card_status_1501、on_scene_immediate_write_1839、person_delta_adapter、player_army_projection_321、public_sayings_1829、scene_llm_1836、secret_order_monthly_progress_566、secret_order_update、surcharge_causal_chain_650、llm_channel_config | 247 passed, 1 skipped in 5.49s |

两 probe 各批均输出 TEMP_CLEANED True。第一批覆盖既有真实月链入口、作者材料私密负向、查案完整行动/传话历史；两批常规测试不装任何变异。总计 526 passed、1 skipped；不是全量套件。修改 Python AST 检查输出 CHANGED_PYTHON_SYNTAX_OK 26；git diff --check 无输出，冲突标记扫描无匹配。未配置/安装 Python mypy 或 pyright，AST 检查不是静态 typecheck；本票不触 Web 类型面。

互联网查阅 Python 官方导入语句文档（curl 下载117001 bytes），与真实入口导入失败相符。仓内现有 _write_tree、身份/事务投影及 list_materials/read_material 已满足需求；没有新造通用件、护栏、适配或查询机制。扩充一个既有行为案，未新增测试案；最小必要成本是同一入口内增加双方授权载体与失败清理证据。其余为承接既有删简，并删目标侧两个同形索引解析，测试总成本不含新增平行体系。

合并差异包含源分支既有成果及历史回执，超过通常单次新增施工行数参考线；不能把承接合并当成本轮新造机制。本轮两个根因必须在同一组合候选上收口，不能拆成恢复旧渲染器与单独测试择边。原源/目标历史提交保留。

## 移交

本轮两类修理交付复核，无未修类别。组合 HEAD 仍须御史台审核及大理寺复裁，收敛后才可合入家族底座；未 push、未开 PR、未改安装/配置/席位、未 amend/stash/rewrite。临时 probe 与官方文档缓存只清理本轮自建之物。
