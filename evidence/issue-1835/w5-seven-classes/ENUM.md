#1835 七类枚举（修内司 apply）

## 1 旧档财政／人口平行架构未退出
谓词：无标档选万人/legacy 财政；entities 按 mode 拒收；flows 预算分流 calc_province_fiscal；唯一支撑测试／错约说明。
命令：`rg -n "POPULATION_UNIT_WAN|fiscal_engine|is_substrate_hub|万人|calc_province_fiscal" ming_sim tests -g '*.py'`
成员（修前样本）：db.population_unit 无标→万人；db.fiscal_engine 无标→legacy；flows.compute_budget_lines 双轨；surcharge/power/recovery/displaced mode gate；pay_order legacy 拒；test_population_unit_648 legacy 案；test_fiscal_substrate_bridge dual_track；test_surcharge legacy；CLAUDE.md 旧档留 legacy。
复扫：population_unit/fiscal_engine 恒现役；calc_province_fiscal 已删；mode gate 已删。

## 2 S3：不合格测试未退净
谓词：非契约呈现锁、内部常量/helper-only、重复 tracer。
命令：`rg` 对 count(中文短语)/endswith(中文)/异常散文含 ID/format_money 出口串。
成员：test_army_display_173 report 金额串；test_decree_dossiers_571「没有这条草案。」count；test_affairs_1831 异常含 ID；test_qa_d1 DEFAULT_TIME_OF_DAY 措辞；test_cli_play_turn「结算中止」。
复扫：c2-rg 仅剩材料路径 endswith（合法路径契约）。

## 3 明确撤令仍被旧强制挽留截流
谓词：明确 cancels/revoke 强制写挽留 todo / deferred_breach_plea。
命令：`rg -n "deferred_breach_plea|try_defer_revoke" ming_sim tests -g '*.py'`
成员：tracker.py cancels 无 pending 则 write_breach_plea_todo+deferred；try_defer_revoke_to_breach_plea。
复扫：两处已空（c3-rg=0）。他类松手挽留保留。

## 4 已裁删除的全表编辑器仍在线
谓词：/admin 页面、routes、ADMIN_TABLES/CRUD、专用测试。
命令：`rg -n "ADMIN_TABLES|api_admin|/admin|admin_upsert" ming_sim web_app.py README.md tests`
成员：web_app admin routes+HTML；db ADMIN_*；write_guard admin cases；README 条。
复扫：c4-rg=0。

## 5 奏报评级成为实况写账依据
谓词：reported progress_band 驱动世界后果（反噬分档等）。
命令：`rg -n "progress_band|list_dossier_progress" ming_sim/breach_plea.py`
成员：assess_foundation_tier 读 list_dossier_progress.progress_band。
复扫：分档只读 bar/段数/已投入；奏报轨仍可写给呈现/材料。

## 6 已裁删除的两省军饷旁账及京运仍运行
谓词：辽东/东江无军份额 standalone 旁账 + 京运补需求。
命令：`rg -n "standalone_military|纯军饷漏斗|_STANDALONE|_primary_source_army_pay" ming_sim content tests`
成员：db standalone_* / primary_source due；regions.json 纯军饷漏斗 Due/拨付gross/军饷欠；支撑测试。
复扫：旁账方法已删；两省 seed Due/gross/欠=0；jingyun 两省 0。

## 7 无票面驱动的事件目录格式化
谓词：events.json 仅格式差、语义不变。
命令：decode 与 10e64fbef 比。
结果：semantic_equal True；工作树恢复紧凑排版。
