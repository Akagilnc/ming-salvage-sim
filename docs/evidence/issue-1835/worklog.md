# #1835 修内司施工记录

本工作树从 `e46a13f938810068915dbcb237ee18dfe021c42d` 续做。以下是已执行工作的证据，不是七类全仓结清声明。F12 按派单留待独立设计裁决，未施工。

## 已施工

| 类 | 共同原因与处置 |
| --- | --- |
| F1 | 单实现迁至 `settlement/preflight.py`、`settlement/run.py` 和实体目录；移除人物快照族、领域提交和专用出口重包；人物、局势、月度结果直接返回段结果。财政承诺去重、月度实体核、recovery 和 legacy 核共置；调用方改真源。 |
| F5 | 正文、标题、奏报、诊断及工具/思考输出不再 strip、截断或抹换行；strip 仅判空。SQLite 不替换孤代理；JSON 编码层转义后保留 codepoints。CLI 删除重新折行的 wrap 及其调用。补修 scene prompt、现有草稿、检举正文、brief 标题、highlight 输入和 ERROR provider 原文。 |
| F6 | 声明数据守卫使用专门异常；持久 JSON、数据库操作和普通代码故障不转拒收或空结果。持久保密排除、局势参与人和目标名单严格解码；可选投影字段缺席与在场损坏分开。回滚失败留诊断。历史 severity 迁移留坏原行并告警、shadow fiscal outcome 保留原异常，均为现有隔离例外。 |
| F10/F7 | 旧返回访问迁至属性/真实入口；移除异常文案锁、默认拒因及历史 strictness 绿卡、源码/prompt 文案绿卡、数值呈现 regex 和结构属性绿卡。保留 fixed-point 文件两例真实结局行为。原文传递测试比较调用输入。 |
| F11 | 信用消费实际落地回执的 source_item；不消费 applied=False；同源去重，不新造平行拒收护栏。该关联实现已由继承提交带入，续做适配真实局势段结果。 |
| F13 | 非对象拒收在产生处包装 raw_value；对象保留原项；不增加中央形状修复层。 |
| F14 | 嵌套指标、经济、派系、建筑、legacy、人物及实体效果汇入既有耐久拒收。月度坏容器/坏项/未知键进入同管线，不恢复退役别名。主体结案不代替后果成功。 |

## 枚举与复扫

临时证据路径位于 `/tmp/1835-*`，不依赖其作为运行前提。

- 命令：`python /tmp/1835-enumerate.py`（Python 为主仓 `.venv/bin/python`）。当前候选表：`/tmp/1835-live-F{1,5,6,10,11,13,14}.json`。宽枚举涵盖函数、文本变换、catch、断言、信用消费和拒收产生点；候选不等于违规成员或结清证明。
- 迁移清单核对：`/tmp/1835-inventory-live.txt`。明定留内的门闩求值器、GameDB 原语、levy 邻接面保留。
- 专项成员表：`/tmp/1835-monthly-relocation-members.txt`、`/tmp/1835-db-operational-members.txt`、`/tmp/1835-presentation-test-members.txt`、`/tmp/1835-copy-lock-final-members.txt`、`/tmp/1835-structure-final-members.txt`、`/tmp/1835-display-tail-members.txt`。
- 复扫：`rg 'strict_effect|_new_army_historically_applied|inspect.getsource' ming_sim tests scripts docs`；历史证据文档引用、退役注释不作为活跃实现。
- `rg 'undefined name' /tmp/1835-pyflakes-clean.txt` 无输出；`git diff --check` 通过。Python compileall 通过。使用生态 autoflake 删除迁移后的闲置 import；pytest fixture 注册 import 保留，消费端不借 issues 做出口桥。

## 验证

所有 pytest/vitest 命令均设置 `MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false` 七旗。

- 触及面命令：`python -m pytest -q -x $(git diff --name-only --diff-filter=ACMR -- 'tests/test_*.py')`。`/tmp/1835-touched-focused22.txt`：2706 passed、3 skipped，145.09s。此后继续修改读端，故不能把该结果称为最新全部触及面绿测。
- 最新读端聚焦：`/tmp/1835-readers-focused26.txt`：118 passed、1 skipped，3.58s；`/tmp/1835-knowledge-focused27.txt`：92 passed，2.08s。
- 新删结构绿卡/scene/highlight 等聚焦：`/tmp/1835-final-targeted18.txt`：119 passed，2.13s。
- Web：使用主仓现有依赖的工作树内符号链接，`web/node_modules/.bin/tsc --noEmit` 通过；`vitest run --environment jsdom src/settleStream.test.ts`：6 passed，492ms（`/tmp/1835-web-focused.txt`）。未修改任何宿主/席位配置。
- 变异真跑：信用段装回直接消费 dossier 输入，真实 settle 入口在既有 `test_fulfill_back_and_urge_three_decisions` 报红（伪信用边 3 != 2），0.65s：`/tmp/1835-credit-source-mutation-red.txt`。恢复后上述聚焦绿。
- 变异真跑：嵌套实体核装回丢弃拒收列表，真实 dispatch 入口 `test_malformed_army_rejected_durably` 报红（rejection_reports 为空），0.64s：`/tmp/1835-nested-mutation-red.txt`。恢复后聚焦绿。
- 失败诚实：经济源变异在宽限例中仍绿（`/tmp/1835-credit-mutation-red.txt`），不作为 F11 修复证明；新加的该证明性片段已删除，未换形重造。
- open_night savepoint 曾批跑偶发失败；单例五次及整文件复跑均绿，整文件 32 passed。未据单次失败猜改生产逻辑，未硬杀 worker。
- 未运行全量；本局不是判官 converged、PR 已开的最终待合并状态。

## a85021835 之后的续修

- F5：知识投影不再以正文相等、包含关系或同回合归档的存在删除独立持久 source；非事件投影不要求选择 event origin 字段。
- F6：继续扫持久 JSON、人物任职查询及声明验证接缝。涉及 audience_translate、covert_progress、decree、participant_roster、materials、public_sayings、session、month_chain、breach_plea、issues、staged_commitment、urge_lever、audience_night、action_materialize、flows、db、context 和 web_app。持久分段载荷损坏不返回空分段或跳过坏项。
- F6：所有指名更新候选的 grant/assignment/authorization/referral/revoke_decree/revoke_authority 读路复用既有严格候选对象读取；pacification、punishment 和任免调用亦共用它。损坏候选不能 break 后新建另一条候选。
- F6：历史饷率的权威财政载荷损坏不跳过省份，也不以不完整分母继续计算；删除失效的宽容 loader 和分母旗。固定财政原有 shadow 隔离契约仍留内。既有错误包接缝记录实际 fixed_fiscal 阶段、保留原异常链；嵌套事务先回滚，由最外层写错误包，不把未知故障假称 substrate bad-state。
- F10/F7：删除 featured dossier 的散文格式/长度/可分性测试；军牌测试去掉逐字段重建实现及呈现哨兵，保留真实 payload 的字段隔离与数据库零改写；promulgation、surcharge、faction 测试删除源码/prompt 措辞锁；保密和知识投影测试继续改 source_id/knowledge_status/原文拷贝契约。CLI 错误测试保 typed code 和完整 provider_message，移除横幅哨兵及模拟消费链的重复测试。
- F12 未改；本轮没有新增通用件，复用 GameDB.parse_engine_payload_json 和原有候选载荷读取/错误包接缝。

### 续修验证

以下 pytest 均设置前述七旗，Python 使用主仓 `.venv/bin/python`。

- `/tmp/1835-continued-focused30.txt`：175 passed；32：156 passed；33：351 passed；34：178 passed。
- `/tmp/1835-continued-focused35.txt`：保密、军牌、Web 投影和 CLI 四文件，70 passed，2.04s。
- `/tmp/1835-continued-focused36.txt`：路由、监督、催办、译旨、违诺及四文件，183 passed，5.02s。
- `/tmp/1835-continued-focused37.txt`：案卷、权限账、一次性拨款及财政基座，317 passed，16.50s。
- 最后触及面命令：`python -m pytest -q -x $(git diff HEAD --name-only --diff-filter=ACMR -- 'tests/test_*.py') tests/test_settlement_fixed_point_1835.py tests/test_urge_lever_624.py tests/test_supervision_625.py tests/test_audience_translate_1837_reopen.py tests/test_fiscal_substrate_bridge.py`。`/tmp/1835-continued-touched41.txt`：426 passed，22.06s。38/39/40 的失败未掩盖：38 暴露持久财政跳省与措辞锁；39/40 暴露提前失败丢失 fixed_fiscal 错误包及嵌套回滚接缝，修正后 41 绿。
- F5 变异：装回按同回合归档隐藏独立 source 的旧规则，经 GameDB.get_character_knowledge 真实入口，既有 `test_turn_report_keeps_source_specific_secret_exclusion_boundary` 报红：`test:490:public` source 缺席；8 passed、1 failed，1.30s（`/tmp/1835-source-visibility-mutation.txt`）。恢复后上述触及面绿。
- 测试成本：复用原有用例，无新平行测试；删除非契约呈现断言、替换为 source_id/原文拷贝/只读库态断言。军牌整文件从 254 行缩为 14 行。保留 fixed-point 两个真实结局用例。
- 全仓候选枚举继续使用 `python /tmp/1835-enumerate.py` 和七份 `/tmp/1835-live-F*.json`；最终候选数 F1=377、F5=2184、F6=703、F10=9624、F11=24、F13=224、F14=29。候选列表依旧不能当作已逐成员裁定。未运行全量。
- `python -m compileall -q ming_sim tests web_app.py`、`git diff --check` 通过；本轮变化文件 pyflakes 无 undefined name（`PYTHONPATH=/tmp/1835-static-tools python -m pyflakes $(git diff HEAD --name-only --diff-filter=ACMR -- '*.py')`）。仓内未找到 mypy/pyright 配置，未把 compileall 冒作类型检查。

## 本轮成员审计与续修

- F13：提交 `F13-members.tsv`，覆盖当前生产 Python 的 227 个构造点及两个 `.item` 赋值；逐点列出对象构造、入口规范化或父循环 dict 先验。`transition_army_owner_power` 的三个显式调用均传对象、默认值也是对象，撤销了本轮一度加入的多余 scalar 护栏；没有集中修形层。
- F14：`F14-members.tsv` 列出 29 个候选及四个范围外真实调用/耐久 owner。新增修复 advance 的坏 metric 容器、未知指标和值拒收，以及 close 的坏终结效果容器。复扫发现硬触发事件忽略效果核拒收：合并重复效果调用，事件身份与原效果对象由既有 RejectionCollector 入账，flush 在事务内，镜像等真正外层提交。
- F5：催办追加结果不再过滤原文空行；执行说明增补不再按正文相同丢弃独立片段；分段承诺保留原 criterion 子字段空白，origin_context 保存完整原文；Web 手改指令向抽取器和写口传原文。删除全仓无调用的 CLI 推荐标记/流缓冲/模拟工具适配旧物，没有替代机制。
- F6：坏持久罪谱不再冒充真实血债，JSON 错误穿透、非对象响亮失败；SQLite 缺列异常不按异常措辞改标；highlight 写库失败不转空成功，TicketCancelled 的既有取消契约保留。
- F10：原有财政失败用例迁到 fixed_fiscal 的 SettlementAbort/错误包以及 Web 409+turn 契约，删除人类错误措辞锁，完整回滚断言保留。罪谱测试不再把坏字符串当合法底账，正向 fixture 改为既定 crime/severity JSON。复用两个原有真实入口用例，分别证明硬触发拒收耐久且不重复、催办不损失原文；没有新平行测试。
- 实验未洗白：`focused43` 暴露旧罪谱夹具；`focused46/47/48` 暴露旧财政异常/HTTP 契约及一处新测试缺 import，已修复。将整个预推原文送入当前段转译的实验在 `focused50` 红，因改变发生段范围已撤回；没有放松其测试。该正式分段边界仍须列入 F5 剩余审计。
- 最新聚焦命令：`python -m pytest -q -x tests/test_event_trigger_gate.py tests/test_secret_order_payoff_1504.py tests/test_secret_order_monthly_progress_566.py tests/test_execution_joint_liability_565.py tests/test_grant_reconciliation_567.py tests/test_issue_entities.py tests/test_advances_section_rejections.py tests/test_close_issues_section_rejections.py tests/test_declaration_dispatch_1835.py tests/test_highlight_judge_544.py tests/test_chat_stream_failpaths_393.py tests/test_settlement_fixed_point_1835.py tests/test_month_chain_1847.py tests/test_month_chain_1843.py tests/test_month_call_recovery_1846.py tests/test_cli_backend.py tests/test_urge_lever_624.py tests/test_breach_plea_623.py tests/test_due_review_621.py tests/test_audience_translate_1837_reopen.py tests/test_credit_events_628.py`。七个 BIN 均为 `/usr/bin/false`，`/tmp/1835-audit-focused52.txt`：640 passed，14.50s。未跑全量。
- 变异真跑：恢复忽略硬触发拒收的旧行为，真实 auto_trigger 入口报红，耐久行 0 而非 1，0.89s（`/tmp/1835-event-rejection-mutation.txt`）；恢复旧空行过滤，真实 rush_secret_order 入口原文拷贝断言报红，0.74s（`/tmp/1835-rush-original-mutation.txt`）。恢复后上述 640 用例绿。
- 测试最小成本：复用原有事件幂等与催办契约用例，增加耐久结构字段和原文精确拷贝断言；财政用例保留失败路径及整库/内存回滚。无新增通用件，无 F12 契约施工。
- 最新枚举：F5=2174、F6=698、F10=9628、F13=227、F14=29。F13/F14 表只清算所列生产点/调用成员，不把它们冒称 F5/F6/F10 全仓逐成员结清。

## 持久读缝续扫：来源授权与军队饷源

- `effect_origin_rejection` 把 SQL 主键解析与持久读分开，复用 `strict_types._parse_sqlite_id`；缺事务只接既有 DeclarationReferenceError，案卷/事务读取的普通 ValueError、KeyError 和代码故障不再变成 invalid_origin_ref。
- 饷源的已知输入转换及业务校验使用既有 DeclarationDataError。两条更新路径将旧值读取前移、复用旧值快照，普通持久标量损坏不进入输入拒收 catch。地区财政复用既有严格 JSON 读取，坏 JSON/坏在场容器穿透；缺财政基座仍是已知不可用饷源。新军、改隶、饷源更新三条边界均只接已知数据异常。
- responsible_bodies 的个人名校验、appointment_tenure 的枚举校验标明已知数据异常，两个调用边界不再吞普通代码 ValueError。
- 聚焦 `/tmp/1835-audit-focused53.txt`：9 个来源/任别触及文件加 declaration 入口，314 passed，7.50s；`/tmp/1835-audit-focused54.txt`：23 个饷源触及文件加 declaration 入口，750 passed、1 skipped，23.42s。七旗均禁宿主，未跑全量。
- 真实入口观察 `/tmp/1835-pay-corruption-run.py`：只写自建临时 DB，将实际饷源地区财政列置为坏 JSON，合法 army_delta 进入 settle_delta。修复后 `/tmp/1835-pay-corruption-new.txt` 得 propagated_fault / ValueError / JSONDecodeError 原因链；装回旧泛型 catch，`/tmp/1835-pay-corruption-old.txt` 得 returned_outcome / invalid_enum，确证旧逻辑洗白。已恢复新逻辑。此为结构化观察，不冒称 pytest 报红；没有新增仓内证明测试。
- F13/F14 表重新从当前树生成；修正 CSV 写出的 CRLF 引起的 diff whitespace 报告，统一 LF。此前 untracked 表未被 diff --check 覆盖，不将先前的绿色当该格式问题不存在的证据。
- compileall、diff --check 通过；`/tmp/1835-audit-static55.txt` 只有既有 unused imports，无 undefined name，未冒称类型检查。候选 F6=699，其余候选数不变，仍不是逐成员完成数。

## F10：密令隔离用例整文件迁约

- `tests/test_secret_order_isolation_883.py` 的正文哨兵、拼接文本查漏、body LIKE 和四字窗锁迁到消息/order/source 身份、knowledge_status、耐久行及级联回滚。删除两条正文汇总 helper，将原无调用的 view_text 改为唯一 source-id 投影 helper；没有新增用例或平行测试。
- 保留对输入原文精确拷贝的断言：简报、公开召对正文、案卷更新正文、公开月报均和送入真实写口的原字符串相等，不约束生成措辞。披露/跨回合幂等以 order 身份和同一 source_id 为证，不以 sim_note 哨兵证明。
- `F10-isolation-members.tsv` 按原文件逐函数列出迁移/保留依据，只清算该文件，不替代全仓 F10 剩余成员。
- 复扫该文件没有正文 substring/LIKE、拼接查漏、四字窗、工具输出措辞或生成物模板锁。`/tmp/1835-audit-focused56.txt`、`focused57.txt` 均 36 passed；最新 `focused58.txt` 包含该文件、character_knowledge、public_sayings，96 passed，6.30s。七旗禁宿主；diff --check 通过；pyflakes 仅既有 unused issues import。
- 测试改动契约是结构化源身份隔离与消息级出处、持久及回滚，不是正文相似度。最小成本是复用原 36 个执行案和现成 SQL/knowledge 入口，删除 192 行旧呈现检查、加入 78 行身份与精确源拷贝检查，没有新增证明用例。
- 最新宽候选 F10=9669（源身份断言也会被宽扫描列入），其余数量不变；候选数上升/下降均不是违规或结清的机械判据。

## F5：共享 JSON 读边界复扫

- 宽扫描进一步发现 `agents.parse_agent_json` 删除字符串内控制字符，以及在有效 JSON 的字符串内误剥代码围栏。原始 JSON 先按语法直接解码；非法控制字符报 LLMContractError 并保留完整 raw_value，不再删字节后冒作成功。
- 删除手写平衡括号扫描及两个 control-char 清洗分支，复用标准库 JSONDecoder.raw_decode 维持既有首对象提取契约。没有加新的通用件或并行解析器。
- 仓内搜索 raw_decode/JSONDecoder 没有既有实现；标准库官方文档 `https://docs.python.org/3/library/json.html#json.JSONDecoder.raw_decode` 实际 HTTP 200；生态 Agno utils/string.py 的 parse_response_dict_str 会合并多个对象，和现有首对象契约不同，未借它改变产品规则。
- 真实共享入口观察 `/tmp/1835-agent-json-run.py`：恢复旧控制字符删除/先剥围栏转换，`/tmp/1835-agent-json-old.txt` 显示非法原文被接受为 body=甲乙，合法包含围栏的原文被拒；恢复后 `/tmp/1835-agent-json-new.txt` 得 contract_failure + raw_preserved=true + JSONDecodeError，以及 valid_original_decoded + body_preserved=true。此为结构化观察，没有伪称 pytest 报红，没有新增仓内测试。
- `/tmp/1835-audit-focused59.txt` 覆盖 pihong_dossier、relation_brew、rescript_draft、audience_translate、month_chain、CLI，303 passed，26.64s，七旗禁宿主。仍须全仓成员复核，不能拿此绿色作为 F5 结清。

## 续修：票拟、材料与财政事实读取

- F6：票拟校验/补交/耗尽只收 LLMContractError 与 DeclarationDataError。明确声明校验改用既有数据异常，MissingFields 两类继承该异常；删除层 A 将普通 ValueError 重包装为数据错误的分支。locality、roster、grant shape 与 stop_condition 依赖仅捕获已知数据类型；普通 ValueError/KeyError 不补交、不降级。
- 复用现有 `test_generate_rescript_draft_program_error_propagates`，增加 ValueError/KeyError 输入维度，不新增平行测试。装回三个旧宽捕获，`/tmp/1835-rescript-fault-mutation.txt`：ValueError 案失败，1 failed、2 passed、1.69s；恢复后的 focused68 包含三个绿色案。
- F5：票拟严格解析只识别恰好覆盖全响应的代码围栏；不再搜索并误剥合法 JSON 字符串内部围栏。复用标准库 re.fullmatch/json.loads，无新解析机制。真实 generate_rescript_draft 入口（仅 LLM 边界返回冻结合法输入）`/tmp/1835-rescript-original-run.py`：旧逻辑 `/tmp/1835-rescript-original-old.txt` returned=false；新逻辑 `/tmp/1835-rescript-original-new2.txt` returned=true、context_preserved=true。最初观察缺 region_targets 导致另一个合法接地拒收，该次不能作为保真证明；已纠正调用输入后重跑。
- F6：材料的 issue/affair 读取、持久人物投影删除跳过/空名单/伪零值 catch；仅缺省 None 保留既有标量缺省。财政事实的 army_logs/region_logs 不再跳过坏持久数字。`/tmp/1835-fiscal-log-run.py` 从真实 DB 到 build_fiscal_fact_brief：旧逻辑 returned_facts=19，新逻辑 propagated_fault/ValueError（`/tmp/1835-fiscal-log-{old,new}.txt`）。
- F6：材料工具仅将明确路径/未就绪数据错误与缺文件转工具错误；坏编码与普通程序 ValueError 穿透。`/tmp/1835-material-read-run.py` 真实 read 工具入口：旧逻辑 returned_tool_text，新逻辑 propagated_fault/UnicodeDecodeError（`/tmp/1835-material-read-{old,new}.txt`）。全部临时变异已恢复，无新增仓内证明性测试。
- F10：character_knowledge 复用既有案例，将正文哨兵、相似文本和名单 JSON 序列化外观断言迁为 source_id、knowledge_status、结构化名单/roster、数据库身份与原文完整拷贝；不应读取的领域依赖直接抛异常。共享档案案避开开局公共事件污染后检查原文完整相等。
- 枚举纠正：F6 数据扫描脚本只读 `/tmp/1835-live-F6.json`，单独重跑并不是当前树复扫。本轮先运行 `/tmp/1835-enumerate.py` 再扫描，结果见 `/tmp/1835-inventory-66.txt`：F1=377、F5=2165、F6=684、F10=9674、F11=24、F13=227、F14=29；宽数据捕获候选247。此为改动中途候选，不是结清数。
- 七旗禁宿主的 `/tmp/1835-audit-focused68.txt`：14个触及文件，382 passed、1 warning、8.56s；compileall（三个生产文件）及 git diff --check 通过。未运行全量，此非最终待合并状态。

## 续修：动作运输、CLI trace 与结构绿卡

- F5 复扫切片发现共享动作 shape 对所有非枚举字符串 strip，并按 FieldSpec.max_len 裁切（包括 JSON 运输字段）。删除共同裁切/删空白实现及全部34个废弃裁切登记，不新增替代规范化。枚举/整数既有契约保留。逐登记处置在 `F5-catalog-trace-members.tsv`，此表是切片，不另立较窄类边界。
- F5 CLI trace 删除 prompt/response 首尾40000字裁切及废弃 TRACE_CAP 读项；原始日志字段完整写盘。纠错反馈、合并旨稿只 strip 判空，其余原样传递。
- 真实 CLI 入口观察（仅外部 CLI 返回值边界提供冻结输入）`/tmp/1835-cli-original-run.py`：旧40000裁切分支 returned_original=true 但 prompt_preserved/response_preserved=false；新逻辑三者true，见 `/tmp/1835-cli-original-{old,new}.txt`。
- 真实 extract_draft_intent 观察 `/tmp/1835-draft-original-run.py`：旧 merged.strip 原文不相等，恢复后相等；`/tmp/1835-draft-original-{old,new}.txt`。`/tmp/1835-grant-original-run.py`：恢复旧 target_id 80字符切片，合法结构化 region_id 与被截 target_id 不一致而抛 StructuredDecreeCombinationError；删除后 returned/target_preserved=true，见 `/tmp/1835-grant-original-old-target-cut.txt` 与 new.txt。恢复的是已确认旧切片，不冒称完整旧实现或 pytest 红测；全部临时变异已恢复。
- F6/F10：删除根据 prompt 措辞猜 trace 调用者的 _infer_tag；显式调用 tag 仍原样记录，缺席只记已知 cli_backend surface。删除7个旧推断参数案，没有换形新造。保留唯一真实 trace 案，对正确输入 prompt 作完整相等断言，不再哨兵子串比较。
- F10 删除 faction_denunciation 的源码文字/函数符号绿卡，保留真实承接案与纯判据行为；无平行替代测试。该处源码扫描机制、ast/Path 依赖一并删除。
- 七旗下 focused70=173 passed/2.38s（中途）；focused72 引用已经不存在的 hitl 文件，0 tests，非验证成功；纠正后的 `/tmp/1835-audit-focused73.txt` 六文件185 passed、1 warning、5.49s。三个生产文件 compileall、diff --check 通过；pyflakes 仅既有unused imports，无undefined name，见 `/tmp/1835-audit-static73.txt`。

## 尚未结清

仍须将宽枚举逐成员完成语义处置，特别是 F10 剩余自由文本/保密哨兵及 helper 呈现测试、F5 下游传递与识别变换的边界、F6 剩余持久与批写接缝，并刷新完整成员处置表与最新触及面验证。本记录不把聚焦绿色冒作整类结清，不声明这些工作缺 owner 决定，也不以执行窗口作合法 blocker。
