# #1891 语义退役与测试归并回执

基线 ef9166578，施工树 Ming_LLM-1899-w5；不是家族底座。按本轮给事中三类承办边界施工，财政同写链归 #1899，不修改财政生产模块或共享存档能力。注册、引用与旧功能存在都不抵消点名退役授权。

## 枚举及复扫

```sh
git ls-files '*.py' '*.ts' '*.tsx' '*.html'
git grep -n '留下听着\|今日就到这里\|AMBIGUOUS_CLOSE\|STAY_ATTEND\|stay_attend_in_audience' -- '*.py' '*.ts' '*.tsx' '*.html'
git grep -n '/api/admin\|/admin\|ADMIN_TABLES\|api_admin\|admin_check_table\|admin_columns\|admin_rows\|_admin_valid_cols\|admin_upsert\|admin_delete\|_ADMIN_HTML' -- '*.py' '*.ts' '*.tsx' '*.html'
# 全部 tracked tests 的 AST：逐测试枚举调用/属性，反查
# apply_historical_fiscal_rates、list_fiscal_levy_petitions_due、terminal_reason_labels；
# 复核月链、转译、材料消费者及财政持久账入口，不把候选列表当重复判定。
```

声明、常量、内嵌分支、客户端页面和参数化案例一起枚举，测试不是生产消费者。最终生产零专属两句识别/留侍旁路、零全表编辑器入口及 CRUD；测试中的两句只是普通输入，不是口令替代机制。

## 退役召对识别闭包

| 成员 | 处置 |
| --- | --- |
| constants.AMBIGUOUS_CLOSE_COMMANDS/STAY_ATTEND_COMMANDS | 删除两句及含问号同根识别集 |
| audience_night.CMD_AMBIGUOUS_CLOSE/CMD_STAY_ATTEND/TAG_STAY_ATTEND | 删除退役专属枚举/标签 |
| audience_night._CMD_VERDICTS | 仅保留现役 close_night/none |
| audience_night.stay_attend_in_audience | 删除专属确定性留侍写账 |
| audience_night.recognize_audience_command | 删除两句匹配，保留现役收夜控制集 |
| audience_night.recognize_xuan_command | 共用优先识别只含现役控制集，无两句优先旁路 |
| GameSession._recognize_audience_command_verdict | 共用现役控制识别，不再留侍/含糊分类 |
| GameSession.scene_chat | 删除留侍早退、锚定人物、控制轮标 done 和含糊特殊放行；只保留现役高置信收夜控制 |
| cli.terminal._handle_court_command | 删除专属留侍识别/直接写账；两句返回非控制话语，沿普通 scene_chat |
| test_scene_stay_attend_uses_actual_protagonist_not_virtual_speaker | 删除旧识别专属测试 |
| test_scene_chat_cli_and_api_same_translation_shape | 复用现有场景轮→持久化→后台转译→join 入口，输入参数改为两句，CLI 实际控制入口均返回 None；通过实际 pending_actions 结构化写入核转译已消费 |

保留 q/quit/退朝等现役控制、宣召/退下及 CLI 手拟待定边界；无新增 run、识别器或口令。普通在场声明仍由已有 audience translation 与统一记录入口承接，其必要 enter/exit 负向/来源轮契约测试保留。

## 退役全表编辑闭包

| 成员 | 处置 |
| --- | --- |
| web_app.api_admin_tables GET /api/admin/tables | 删除 |
| web_app.api_admin_table GET /api/admin/table/{table} | 删除 |
| web_app.api_admin_upsert POST /api/admin/table/{table}/upsert | 删除 |
| web_app.api_admin_delete POST /api/admin/table/{table}/delete | 删除 |
| web_app.admin_page GET /admin | 删除 |
| web_app._ADMIN_HTML（页面、前端全表枚举/改格/新增/删除） | 删除完整页面，不隐藏或加鉴权 |
| GameDB.ADMIN_TABLES | 删除专属表白名单 |
| GameDB.admin_check_table/admin_columns/admin_rows/_admin_valid_cols | 删除专属读面与校验 |
| GameDB.admin_upsert/admin_delete | 删除专属 CRUD；不动共享 SQL、账户、存档 |
| test_settlement_write_guard_393._FakeDB.admin_upsert/admin_delete | 删除专属替身 |
| test_settlement_write_guard_393._endpoint_cases 的两个 admin 参数 | 删除专属写门案例，保留其他现役写面完整负向断言 |

临时 TestClient 从真实 HTTP 入口实跑五个地址：页面、列表、读表、upsert、delete 均 404；GameDB 专属成员列表 []。无生产继任编辑器、开关、鉴权或新游戏 run。

## 平行测试

| 成员 | 独立价值及处置 |
| --- | --- |
| test_fiscal_levy_effect.test_liao_levy_rise_is_not_auto_approved_and_awaits_emperor_verdict | 重复首次应呈/无自动终局/征收不变；删除，唯一证明用现有真实月链 test_emperor_approves_levy_petition_through_real_month_chain |
| test_levy_petition_1891.test_content_declares_closed_label_sets_for_levy_events | 仅遍历配置字段，无消费者；删除整文件，闭集正确输入/拒收由真实月链原测试保证 |
| test_lian_levy_gate_waits_until_1639_and_needs_no_stop_event | 删除平行成功应呈、属性与批准结局证明；保留史实时点前不生效及 generic 终态通道不能代批的独立负向 |
| test_fiscal_levy_gate_waits_until_1631_and_generic_terminal_pass_skips_it | 同类应呈/属性证明删除；保留日期前不生效、generic 候选与终态不能吞请饷、event_pool 强塞拒绝及零终态 |
| 月链闭集非法标签/无当次批语/他事件偷用批语 | 保留必要拒收、零写入契约 |
| 月链留中再呈/重开身份/错位机标失败续跑 | 保留必要绑定和恢复契约 |
| 财政 helper 其余 malformed settle/meta、无份额重分配、幂等/all provinces 校准、失省恢复 | 与应呈配置不是同一外部契约，保留；财政消费者真跑由 #1899 承接，不新增平行套件 |
| month_translate_1840/world_materials_1834 的候选身份字段 | 穿实际材料/转译消费者，非仅配置遍历，保留 |

不按案数或绿灯裁断，未新造 test/helper/夹具；复用现有真实入口测试，未删除闭集、身份与失败恢复必要契约。

## 聚焦证据

全部游戏测试/HTTP 自验先设置七个 MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false；另设临时 MING_SIM_USER_DATA_DIR、PYTHONDONTWRITEBYTECODE=1、-p no:cacheprovider、临时 basetemp。

- 项目 Python `-m pytest tests/test_audience_translate_1837.py tests/test_audience_translation_1838.py tests/test_scene_llm_1836.py tests/test_settlement_write_guard_393.py tests/test_levy_petition_month_chain_1891.py tests/test_fiscal_levy_effect.py -q -p no:cacheprovider --tb=short`：127 passed/41.76s，日志 /tmp/1891-r3-focused.log。
- 之后归并两个 gate 案的重复子证明，仅复验 `tests/test_fiscal_levy_effect.py -k gate_waits_until`：2 passed/0.90s，日志 /tmp/1891-r3-gates.log。
- 复用入口变异：装回旧 constants/audience_night/session/CLI 识别，原双输入消费者案 1 failed/1 passed（0.94s），留侍路径未进入转译、结构化落库 0>0 报红；恢复后 2 passed/0.75s。含糊句旧逻辑已放行，故单案本来绿，不伪称它证明识别代码退出；该闭包退出另由全仓枚举复扫证实。日志 /tmp/1891-r3-mutation-{red,green}.log。
- 不锁生成台词/措辞，模型边界替身不冒称真实模型语义验收。没有新增证明性测试。
- HTTP 五地址 404、专属 DB 成员 []；Ruff F401/F821 与 diff --check 通过，无配置化 Python typecheck，不冒称。
- 本轮只做授权三类；不宣告两票或家族 converged，不并底座，不 push/PR/amend/stash，不改席位或宿主。

## c953c19ae 后召对闭包残余复修

前轮漏扫成立：`get_night_protagonist` 的唯一生产消费者是已删留侍分支；剩下测试读取不能维持生产访问器。本轮只承办召对残余，不重修已核准的全表编辑和测试归并，不碰 #1899 财政链。

| 完整增量成员 | 处置 |
| --- | --- |
| audience_night.get_night_protagonist | 删除零生产消费者读口，无替代访问器、别名或兼容层 |
| constants.py 含糊收夜封闭集、留侍口令封闭集两行注释 | 删除指向已删集合的说明 |
| audience_night.py 留侍叙事账标签注释 | 删除指向已删标签的说明 |
| audience_night.read_night_scroll 的 exit/留侍/其它 scene 口令账注释 | 删除已退役留侍类别，保留现役投影说明 |
| test_protagonist_follows_translation_and_xuan_cut | 四处读取（含回调）改读既有 get_night 存储结果 protagonist_name；宣召及转译源轮断言不变 |
| test_protagonist_undo_reprojects_night_current | 四处读取改读同一存储字段；撤回回投及无存活轮空值断言不变 |
| test_retry_older_round_keeps_newer_protagonist | 一处读取改读存储；较早轮重试不能覆盖新主角断言不变 |
| tests/test_audience_translation_1838.py import | 接已有现役 get_night，不留专用测试读口 |

`get_night` 现役消费者见 `git grep -n 'get_night(' -- ming_sim web_app.py scripts`：召对、DB、Web 多处使用；实现直接 SELECT audience_nights。没有新造测试 helper、夹具或生产访问器。

全仓复扫命令：

```sh
git grep -n 'get_night_protagonist\|AMBIGUOUS_CLOSE_COMMANDS\|STAY_ATTEND_COMMANDS\|TAG_STAY_ATTEND\|stay_attend_in_audience\|留侍叙事账标签\|含糊收夜封闭集\|留侍口令封闭集\|exit / 留侍' -- '*.py' '*.ts' '*.tsx' '*.html'
git grep -n '留侍\|含糊收夜' -- '*.py' '*.ts' '*.tsx' '*.html'
```

首命令无匹配；第二命令只余 test_audience_continuous_507 的两个北极星场景说明，描述场景经历，不描述已删口令/集合/标签，依法保留。全部 tracked Python AST 353 文件通过；零名字引用声明候选 55 项（43 项 FastAPI 注册、12 项既有标准/SDK 协议），无同根剩余成员，完整枚举输出 `/tmp/1891-r4-audit.log`。这只是候选筛选，不把有名字引用当保留授权。

本轮聚焦命令（此前设置七项 MING_SIM_*_BIN=/usr/bin/false、临时用户数据目录和 PYTHONDONTWRITEBYTECODE=1）：

```sh
/Users/akagilnc/WorkSpace/Ming_LLM/.venv/bin/python -m pytest tests/test_audience_translation_1838.py tests/test_audience_translate_1837.py::test_scene_chat_cli_and_api_same_translation_shape -q -p no:cacheprovider --basetemp=/tmp/1891-r4-tests --tb=short
```

结果 `10 passed in 1.02s`，日志 `/tmp/1891-r4-tests.log`。Ruff F401/F821、diff --check 通过。本次仅删除失效生产读口/注释，现有断言不放松，不新增证明性测试，不冒称变异真跑或真实模型验收。
