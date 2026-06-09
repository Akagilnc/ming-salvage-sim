# 更新日志

本项目所有重要变更记录于此。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [未发布]

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
