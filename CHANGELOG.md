# 更新日志

本项目所有重要变更记录于此。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [未发布]

## [0.8.0.0] - 2026-06-11

### 新增
- **月末结算全有或全无(ADR 0008 PR1)**:回合后半段(落库、章节记忆、局势惯性、结局判定、推进回合)收进单一事务——中途崩溃/出错时整段回滚,存档不再出现"国库扣了但军队没建"式半写;事务层经自定义连接(`applier.atomic`)实现,期间内层 `commit` 暂停、`executescript` 拒绝、回滚后自动续开事务,杜绝第三方代码逃逸出事务。
- **结算可恢复**:邸报与 delta 推演结果在结算前持久化(`extracted_ready` 判别列区分"真结果/占位/失败"),崩溃或中止后重开游戏即可从断点续跑——已就绪的结果直接重放落库,不再花一次 LLM 重推演;推演结果损坏或缺失时自动退回重推演,旨意原文跨进程存活。
- **响亮中止 + 错误包**:推演产物不合契约(shape 垃圾、损坏 JSON)时不再静默吞掉,改为中止结算并落一份五件套诊断包(DB 快照/上下文/错误链/manifest/拒收记录,永不覆盖旧包),玩家收到带重试指引的明确报错;另提供"重新推演"逃生口,把坏结果降级为非就绪(保留邸报字段)而非删行,避免新软死锁。
- **拒收报告带出处**:落库被拒的条目(白名单外字段、坏值)记录 provenance,事务内落 DB、提交后镜像 JSONL,事后可审计哪个环节产了坏数据。
- **恢复窗口 UI**:web 端 settling 相位显示恢复横幅 + "续跑结算"按钮;CLI 在恢复入口打印操作指引('back' 给出恢复路径而非静默循环),零草案下也能恢复。

### 变更
- 结算前半段(固定财政、局势播种)自带事务并提交——中止重试时前半段效果保持已落,不重复扣账(设计明文,非缺陷)。
- 回合相位新增 `settling`,作为单一真源下沉到 `models.py`;恢复窗口内冻结改盘操作(下旨草案、撤回、跳过等 7 个入口),web 对应端点返回 409,聊天提案在源头被挡。
- 召对中的口头应允改为延迟提交:恢复窗口内不再即时 commit,统一并入结算事务,杜绝跨事务半写。
- 退朝(无旨推进)在前半段已完成时拒绝执行——结算欠账不可跳过,只能续跑或重新推演。
- 事务回滚后内存状态一律从 DB 重载(含 content 重建),杜绝"DB 回滚了但内存还记得"的幽灵状态。
- 探针 driver 的结算路径与真实流程对齐:同样在 pre_settle 后持久化推演上下文,重试语义一致。
- 恢复窗口冻结范围扩大(评审修):全部即时写聊天路径(任免落地、编外人物登记、密令房四类操作、CLI 前缀密令)与自然语言抽取的新暂存动作一并冻结;窗前已暂存的动作不受影响,仍随结算事务统一提交。

### 修复
- 探针 driver 此前每月固定财政流水在异常路径下静默蒸发——现与结算同事务,要么全落要么全回滚。
- 毒推演结果反复重放导致的永久软死锁(重放→失败→重放)被逃生口切断。
- HITL 暂停时三件状态(相位/草案/上下文)改为同一事务写入,中断不再留下互相矛盾的半套状态。
- settling 相位与恢复上下文(引擎占位/driver 重试真源)改为同一事务提交,引擎与探针 driver 同修——崩在两笔之间不再留下"相位已 settling 但无恢复上下文"的存档,玩家手改的旨意原文不再因此蒸发。
- CLI 恢复期局势分支收到守门拒绝时留在本回合交互循环,不再重进回合重印回合头。

## [0.7.2.0] - 2026-06-10

### 新增
- **三饷计火耗（spec v23，2026-06-10 拍板）**：火耗应派从「只派正赋」改为 `(正赋+三饷)×火耗率`，正赋/三饷分量另立——百姓实际负担与官绅截留不再被系统性低估；三饷分量随辽/剿/练饷时间线注入消长。
- 财政基座 spike 新增 golden：G22 三饷火耗分量、G22b 三饷=0 退化边界、G14b 正赋应征 None≡缺省、G14c 穷省 k=0.5 清丈（钉结算 k 缩放与 oracle 重放两侧）。

### 变更
- 火耗对账 oracle 同步改为正赋/三饷两分量独立重算后相加（与结算同分量式，防极端量级下浮点求和序差致对账漂移），两分量并显式写入结算结果（下游直接消费、不解析 stdout）；`官民田_o` 从开账+诏令独立重放（不再读清丈后的运行时税基）——清丈类「两侧同搬」篡账现在被债务+C 两层 oracle 当场咬死。
- 全部 value golden 钉死 `省库库银` 与 `官民田/隐田` 末态；raise-golden 升级为验证具体守门消息；spike FAIL 时退出码为 1（自动化不再假绿），`sys.exit` 收进 `__main__` guard（import 不杀进程）。

### 修复
- 开账负值校验补齐 CLAIM 四科目（负军饷欠经偿还环凭空生钱）。
- param/Due/开账库存的 NaN/inf 入口拦截（NaN 军饷 Due 原可把整个资金池静默付空且五层断言全过）。
- Due 科目白名单（拼错科目原会让法定支出静默蒸发）；action 缺 type/非数值字段改为干净报错。
- 支付池透支 fail-loud + 浮点尘埃清零；`正赋应征=None` 语义钉死（视为缺省走亩额派生，其余参数拒 None）。
- 必填参数（三饷应征/火耗率/逋赋率/起运定额/Due）缺失改为干净报错而非 KeyError——不给默认 0（火耗率缺省成 0 = 静默改经济学）；开账 stock 为 None 前置拦截；率值/param/Due/开账全面型别守门（字符串/bool 原走半程 TypeError，bool 是 int 子类须显式拒）（G21t–w）。

### 移除
- spike 中只写不读的 Cin/Cout 流水字典（v13 同源对账残留）。

## [0.7.1.0] - 2026-06-10

### 新增
- **任免纳入聊天动作闸门(ADR 0006 三类全做)**：CLI 召对里口头任免(任命/升迁/调任/罢免/纳妃)走**独立检测** `extract_appointment_action`(与密令的 `extract_minister_actions` 不混)、随召对触发不挂密令 gate、覆盖大臣 + 太监、作用域=当前召对的大臣。暂存为 `kind=office`,颁诏 `commit_pending_actions` 透传 `content/registry` 落库。

### 变更
- **确认闸门由「颁诏批量同意 + UI 撤回面板」改为「对话确认」**：大臣(太监)in-character 领命复述;皇帝下一句**应允 → 当场 commit**该召对大臣暂存、**拒绝 → 丢**、不回 → 留、颁诏对没回的算同意。新增 `extract_confirmation_intent`,commit/drop 按 `minister_name` 过滤。
- **任免落地核归一**:抽出 `issues.apply_office_appointment` 作【唯一落地核】(在册且未死→改 active+授官+顶替去重+`office_type` 重算+内存/registry 同步;不在册→建档;dead/空 office 拒),**extractor 的 `office_changes` 与 CLI 任免 commit 共用**,杜绝两份会漂的实现;罢免加 ming-guard + alias + active 校验。
- minister prompt 加「in-character 领命并补充信息和要点」(后宫走 consort_agent 自有领命)。

### 修复
- `_displace_duplicate_offices` 剔除官员一个独占分项后,保留官职的 `office_type` 随之重算并同步 DB+内存(原只改 office、留陈旧 type,大臣 agent 按错类型建身份/工具)。

### 移除
- 拆掉自造的「待颁诏」前端确认 UI:`PendingActionsModal` + 顶部浮窗(`.pending-actions-fab`)+ pending 角标 + 撤回按钮 + 相关 state/type(确认改对话驱动;后端 `pending_actions` 表/暂存基建保留)。

## [0.7.0.0] - 2026-06-09

### 新增
- **聊天动作闸门(ADR 0006)**：CLI 后端召对里 LLM 从自然语言**推断**出的密令写动作(更新/催办/提交核议/记进展)与后宫调教,不再在召对当场直写真实表,改进 `pending_actions` 暂存表;颁诏时(`pre_settle` 最前 / 退朝 `advance_without_edict`)`commit_pending_actions` 在结算管线前批量落库(不拒绝即允许)。暂存行纳入召对 rollback(撤回召对一并删),落不了的标 `failed` 不留孤儿,commit 抛错被兜住不崩结算。**根治**:闲聊被判「更新密令」当场静默改既有密令 + 续期 + 谎报「已交付」(handoff 计划里 slice 4「action-gate」一直没实现)。
- **皇帝复核区**：`GET /api/pending_actions` + `POST /api/pending_actions/{id}/withdraw`(不存在 404 / 已落库或非本回合 409);前端「待颁诏」复核面板(列本回合暂存动作 + 逐条撤回)+ 顶部入口浮窗 + 召对暂存反馈提示(取代旧「密令已秘密交付」对更新动作的谎报)。

### 变更
- 流式与非流式召对路径共用 `apply_cli_conversation_actions` + 同样回传 `pending_action_id`,不漂移。
- 拟旨与「密令如下/拟旨如下」显式前缀按钮 = 玩家明示,仍直接落库,不入闸门(认可例外)。任命走 agno tool-call(api 通道)不在本片(ADR 0002 更大范围)。

## [0.6.1.0] - 2026-06-09

### 新增
- **游戏内 LLM 执行通道选择**：局中设置面板(gameMenu)新增 API / CLI 通道选择器 + CLI runner/model/超时输入。CLI 局开局后改设置不再被强制降级到 API、不再因空 key 误报；显式选 CLI 即可脱 key 续跑(#51)。

### 修复
- **真实流落库二级类型校验**：`validate_delta_shape` 抽成单一真源(`ming_sim.issues`),`apply_score_extraction` 落库前先校验容器/实体二级 dict 类型,畸形 delta 不再在 apply 内部「前字段落库、后字段崩」半落库;driver 仍在 pre_settle 前校验(#57)。
- **探针 driver 纯确定性**：driver 注入 channel=api 确定性配置,即便设了 `MING_SIM_LLM_BACKEND` 也不再 spawn legacy CLI enrichment(ADR-0004:dialogue-Claude 已自产完整 delta)(#54)。
- **CLI 空 cli_model 不漏 API model 名**:补 for_role/advanced 路径回归覆盖(RT2 已修工厂)(#52)。
- **runtime_llm.json 数值类型一致**:`_api_runtime_slot` 类型感知,preserve/fresh/load 三路 max_tokens(int)/timeout(float)同型(#53)。
- **in-game 设置 verify offload**:`api_set_llm_config` 把 LLM 连通性 verify(CLI smoke ~12s,只读)offload 到线程不卡 UI;commit(改 session 态)留在 event loop 同步跑(单人 CLI 串行探针下原子无 race)(#56)。
- `is_real_api_key` 拦截 `__keep__` sentinel,不当真 key(Red Team)。

### 修复(ship-pre 跨厂 CMR 续轮)
- **落库二级类型校验补全**:`_NESTED_DICT_FIELDS` 收敛为 `{region_delta, army_delta, power_updates}`(这三者 apply 逐 entity 写、坏项中途崩=部分已落库),faction/class 排除(apply 各自容忍旧扁平 int / 静默跳);所有 list 字段补「项必须是 dict」校验;None 字段容忍(与 apply `or {}` 一致)。
- **通道切换不丢 key**:`commit_llm_config` 对 CLI 通道 preserve/seed api 槽真实 key——已存槽有 key 则 preserve_api 保留;槽空但当前 session(可能来自 `OPENAI_API_KEY` env)有真实 key 则写进槽。api→cli→api 往返不丢 key。
- **配置 verify 失败不半写**:`api_set_llm_config` 加 `except HTTPException` 透传,verify 失败的干净 detail 不被二次包裹;失败时绝不 commit。
- **gameMenu CLI 字段从已存槽初始化**:用 persisted CLI 槽(`??` 容忍显式空)初始化,API 会话下不把 env 兜底的 API model 名当 cli_model 回传。

### 变更
- **单一真源收口**：`VALID_CHANNELS`、`CLI_DEFAULT_TIMEOUT_SECONDS`、`CODEX_DEFAULT_MODEL`/`CLAUDE_DEFAULT_MODEL` 常量化,替换散落字面量(#55)。
- `apply_llm_config` 拆成 `build_llm_config`(纯派生)/ `commit_llm_config`(落盘+重建)/ `apply_llm_config`(同步组合),支持 verify 与 commit 分离。

## [0.6.0.0] - 2026-06-09

### 新增
- **LLM 执行通道：API / CLI 并行、channel-aware**。`runtime_llm.json` 增双通道槽位（api / cli），`LLMConfig` 带 `channel` + `cli_runner`/`cli_model`/`cli_timeout_seconds`；readiness、模型构造、office 推断与落库 enrichment 全按当前 active channel 判定。脱-key 也能从菜单选 CLI 通道跑（`ApiSettingsModal` 加 channel 选择器）。`cli_backend_active(llm_config)` 单一真源门控 issue/office 的通道感知 enrichment。
- 单一真源 `llm_config.is_real_api_key` + `real_api_key_or_empty` + `CLI_BACKEND_PLACEHOLDER`：占位符只在 `create_chat_model` 构造 CliChat 那一刻注入，`LLMConfig.api_key` 对 CLI 通道永空；手动 key 输入口（getpass / 菜单 request / 局中 request）统一过滤占位符。`web_app._has_real_api_key` 委托同一真源。
- 架构决策记录：ADR 0001（API/CLI 双通道并行保留）、ADR 0002（用 action candidates 而非 tool-call 作游戏规则）。

### 变更
- `settle_with_delta` 增 `delta_applier` 注入闭包（与 `chapter_recorder`/`ending_summarizer` 同构）：merge base 的 ADR-0004 结算重构后，真实流经此闭包把 llm_config 送回落库 enrichment，结算核本体仍不依赖 llm_config；driver 默认 None 走确定性 apply（设 `MING_SIM_LLM_BACKEND` 时仍按 legacy env 判定）。

### 修复（pre-landing review）
- 显式 CLI 通道 `cli_model` 为空时不再把 API model 名（`llm_config.model`）当 `--model` 漏给 codex/claude，改回落 runner 默认（`cli_model_from_env`，agy 无 `--model` 故空）。
- 菜单 LLM 保存端点（`api_menu_save_llm` / `_menu_save_cli_llm`）的 verify smoke（CLI 子进程最长 `cli_timeout_seconds`）改经 `run_in_executor` offload，不再阻塞 asyncio event loop 卡住并发请求。
- 补测：`verify_llm_available` legacy env-only smoke 路径、`CliChat._call_cli` 未知 backend 兜底。

## [0.5.2] - 2026-06-08

### 修复
- 探针 driver `run_settle` 堵两处静默吞(codex 对抗 review）：falsy 非 dict 的 delta（`[]`/`""`/`0`）不再被 `or {}` 吞成空结算照样推进；未知顶层字段（拼写错如 `地区变更`↔`地区变化`）不再静默无效落库——两者结算前响亮报错、回合不半推进。

### 变更
- `docs/TODO.md` 移到根目录 `TODOS.md`（与 gstack 约定一致），标记城防炮(#4)/driver(#10)完成移入修复记录；CLAUDE.md 工作手册引用同步。

## [0.5.1] - 2026-06-08

### 新增
- **确定性结算核**：从 `decree.py` 抽出 `pre_settle`（固定财政 tick + auto_trigger）与 `settle_with_delta`（apply→turn_logs→章节记忆→inertia→clear→结局判定→next_period）。真实流程 `_settle_after_narrative`/`resolve_directives` 改调新核，behavior-preserving；章节记忆/结局总评做注入回调，使核不依赖 `llm_config`。真实流程与探针 driver 共用同一结算核（见 ADR 0004）。
- **探针 driver（`driver.py`）**：`state`（盘面快照）/ `settle --delta <json>`（注入我产的中文 schema delta 跑确定性结算、推进一回合）/ `dump`（地区快照）。`run_settle` 规范化中文 key→英文 canonical 并按 schema 校验各字段容器类型（畸形值结算前响亮报错、不半落库），落 narrative 到 turn_reports + canonical delta JSON 到 turn_extractions（供 replay/timeline 重建）；CLI `settle` 支持信封 `{narrative, decree_text, delta}`（裸 delta 兼容）。
- **城防炮 `region.cannon` delta 落库路径**：`地区变化` 新增 `城防炮` 字段，`apply_region_deltas` 特判路由到 `apply_region_cannon`（复用 `city_level×8` clamp，在白名单检查前），与军队 `随军大炮`（`cannon_equipment`）分域。

### 变更
- 城防炮补入 `REGION_FIELD_LABELS`（turn 日志显示「城防炮」而非回退英文 cannon）。
- CLAUDE.md「结算编排骨架」改述：driver 复用 `pre_settle`/`settle_with_delta`，不再自行复刻结算链（ADR 0004）。
- 新增架构决策记录：ADR 0003（人物相关 delta 合并为单 key + 显式动作意图，实现 deferred）、ADR 0004（探针 driver 复用引擎结算核）。

### 修复
- `db.py` 漏 import `LLMContractError` → 任何非法 `region_delta` 字段曾崩 `NameError`，现正确抛契约错（报清楚的合法字段清单）。
- 探针 driver 对畸形 delta（信封 `delta` 非 object、模块值容器类型不符）一律在动 DB 前响亮报错，不静默吞成空 delta 照样推进回合。

## [0.5.0] - 2026-06-08

### 新增
- **事件记忆系统**：每回合结算后自动提炼记忆卡，按人物/派系/官职类型建索引；大臣召见时注入「旧事记忆」块，上限5条，对话前后贯通。支持规则提取（`record_event_memories_from_resolution`）与 LLM 提取（`memory_extractor` agent）两条路径；每科目保留最近3条，超出自动剪枝。
- **推演记忆注入**：结算链新增 step 1.8——`memory_retrieval` agent 从本月诏书提取人名/地区/军队/势力/关键词（含可选 year/period），按 tags LIKE 匹配召回相关历史记忆（≤10条），注入 `season_simulator` 与 `score_extractor` payload；两个 prompt 同步说明字段含义与使用方式。
- **记忆自动衰减**：写入时按 importance 设 `expires_turn` TTL（importance 1→6回合、2→12、3→24、4→48、5→永久）；查询默认过滤过期记录，按年月查时可 `ignore_expiry=True` 追溯历史档案。
- **大臣按时间回忆**：新增 tool `recall_memories_by_time(year, period, keywords)`——时间查（精确该月，ignore_expiry）与关键词查（当前有效期内）合并去重返回；`memory-recall` skill 说明同步更新。
- **DB 索引**：`event_memories` 新增 `idx_event_memories_expiry(expires_turn, turn)` 加速过期过滤；`get_memories_by_keywords` 支持 `ignore_expiry` 参数。
- 后宫妃嫔卡片支持上传本机图片作专属立绘，存 `data/uploads/`，记入 `portrait_id`，重启后自动复用（`POST/DELETE/GET /api/consorts/{name}/portrait`）。
- 立绘工具脚本：`gen_portraits.py`（调生图接口出图）、`compress_portraits.py`（缩 512 压体积）、`portrait_status.py`（进度表）；附后宫预设图池与寝宫背景图。
- **军备两轴 + 城防（玩法机制）**：军队新增 `火器`（火器装备 0-100：鸟铳/三眼铳，野战+守城）与 `随军大炮`（随军红夷炮门数 0-12，攻坚利器但不利野战机动）；地区新增 `城市等级`（0-5 静态史实分级，京师 5）与 `城防炮`（城头红夷炮，上限 = 城市等级×8）。判战永远由 LLM 软判，引擎只 clamp 不算胜负。全层贯通（DB/extractor prompt/军表/大臣 inspect）。
- **CLI 后端探针（脱 api key）**：游戏可不依赖商业 api key 运行——LLM 后端在单一咽喉点改走本机 `agy`(默认)/`codex`/`claude` CLI（`MING_SIM_LLM_BACKEND=agy|codex|claude`），纯 subprocess，机器本地。补齐无 function-calling 带来的 toolcall 缺口（拟旨/密令入档、会话动作、地区/建筑 context 注入、国策实体后果补全）。详见 `docs/CHANGELOG_cli_backend.md`。

### 变更
- **推演 agent（season_simulator）改 skill+tool 模式**：不再把全量盘面静态塞入 payload；挂 10 个只读工具（`view_state`/`check_treasury`/`list_regions`/`inspect_region`/`list_armies`/`inspect_army`/`list_issues`/`inspect_issue`/`list_external_powers` + `submit_report`），按需查盘面，写完邸报调 `submit_report` 提交正文；`submit_report` docstring 承载完整奏章写作规范（结构/笔法/局势/末章/禁忌），`season_simulator.md` 从 141 行精简至 54 行。
- **结算 agent（score_extractor）改 skill+tool 模式**：payload 去掉 regions/armies/buildings/ministers 五张全表，只保留 narrative + issues摘要 + id列表 + fiscal_config；挂 7 个工具（`get_region`/`get_army`/`get_external_power`/`get_active_ministers`/`get_issue_detail`/`get_faction_class_state` + `submit_extraction`），按章节按需查当前值算 delta；`submit_extraction` docstring 承载完整 JSON schema、16 字段约束、档位标准与骨架示例，`score_extractor.md` 从 266 行精简至 50 行；去掉 `force_json_output`，改由 tool docstring 约束格式。
- **CLI 后端会话落地收敛单一真源**：`session.apply_cli_conversation_actions` 同时供命令行（`session.chat`）与 web 流式路径调用，杜绝两边逻辑漂移；官职分类改走 `content/offices.json` 参考表（替代旧正则词表），无 CLI 后端时落「待铨」graceful。
- **国策实体后果三结案路径对齐**：issue 经 tracker advance / close / 自然惯性（inertia）任一方式结案，都落 `effect_on_resolve/fail` 的建军/补兵/人物状态/帝国修正，不再只有部分路径生效。

### 修复
- 密令「更新」按精确 id 改对应那条（多条 active 时不再改错条），更新不清空原标签；催办对 pending_review 不抛错。
- CLI runner（agy/codex/claude）检查退出码/空输出即抛错，不把 auth/quota 失败当空回复或角色文本落库。
- 落库守门：国策效果字段非 dict 不再崩整月结算；`apply_score_extraction` 非法 delta 严格抛错不静默丢；CLI 后端国策保底有回报，绝不入空壳。
- 火器/随军大炮新档贯通（fresh seed 不再全 0），动态新建军可按 id/名查详情。

## [2026-05-24]

### 新增
- 后宫系统：打通选妃流程，司礼监从秀女池遴选候选呈选、降诏册封入宫；调教 tool 提权，妃嫔学技艺/改性子写入永久记忆；修复 candidate 升格。
- 人物据实奏对：大臣与月末邸报按在朝名册查现职状态，不再凭史实记忆乱报官职；朝堂名册按官品排序。

### 修复
- 财政：`economy_moves` 的 account 按钱实际出自哪库判定，不再按用途误判。

### 文档
- README 重写「已实现」为分模块表格；补后宫、省级财政、月度收支、人物头像等说明。
- 立绘提示词改现代古风；新增 GPL-3.0 许可证。

## [2026-05-23]

### 新增
- extractor：支持人事任命与人物状态变更落库；开局校准到 1627.10。
- 网页结算悬浮框加「本月一次性入账」段；建筑支出改走内库。

### 变更
- 推演重构：叙事零数值化，extractor 按章节扫描，prompt 瘦身。

## [2026-05-22]

### 新增
- 建筑系统：御窑厂/边堡/仓储/工坊/河工，等级状态维护产出按月落账，新建须立项推进；推演 token 优化与遥测。
- 网页地图节点重定位与取点工具；菜单改中央弹窗。

### 文档
- README 加游戏截图与头图。

### 杂项
- 移除 `.vscode` 出版本管理。

## [2026-05-22] — 首次公开发布

晚明对话式政略模拟器初版：月度回合制、大臣召见与拟旨、诏令结算、月末邸报、两京十三省与军队/外部势力盘面、CLI 与网页双端、本地存档、内容外置。
