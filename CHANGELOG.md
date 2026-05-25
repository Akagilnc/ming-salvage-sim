# 更新日志

本项目所有重要变更记录于此。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [未发布]

### 新增
- **事件记忆系统**：每回合结算后自动提炼记忆卡，按人物/派系/官职类型建索引；大臣召见时注入「旧事记忆」块，上限5条，对话前后贯通。支持规则提取（`record_event_memories_from_resolution`）与 LLM 提取（`memory_extractor` agent）两条路径；每科目保留最近3条，超出自动剪枝。
- **推演记忆注入**：结算链新增 step 1.8——`memory_retrieval` agent 从本月诏书提取人名/地区/军队/势力/关键词（含可选 year/period），按 tags LIKE 匹配召回相关历史记忆（≤10条），注入 `season_simulator` 与 `score_extractor` payload；两个 prompt 同步说明字段含义与使用方式。
- **记忆自动衰减**：写入时按 importance 设 `expires_turn` TTL（importance 1→6回合、2→12、3→24、4→48、5→永久）；查询默认过滤过期记录，按年月查时可 `ignore_expiry=True` 追溯历史档案。
- **大臣按时间回忆**：新增 tool `recall_memories_by_time(year, period, keywords)`——时间查（精确该月，ignore_expiry）与关键词查（当前有效期内）合并去重返回；`memory-recall` skill 说明同步更新。
- **DB 索引**：`event_memories` 新增 `idx_event_memories_expiry(expires_turn, turn)` 加速过期过滤；`get_memories_by_keywords` 支持 `ignore_expiry` 参数。
- 后宫妃嫔卡片支持上传本机图片作专属立绘，存 `data/uploads/`，记入 `portrait_id`，重启后自动复用（`POST/DELETE/GET /api/consorts/{name}/portrait`）。
- 立绘工具脚本：`gen_portraits.py`（调生图接口出图）、`compress_portraits.py`（缩 512 压体积）、`portrait_status.py`（进度表）；附后宫预设图池与寝宫背景图。

### 变更
- **推演 agent（season_simulator）改 skill+tool 模式**：不再把全量盘面静态塞入 payload；挂 10 个只读工具（`view_state`/`check_treasury`/`list_regions`/`inspect_region`/`list_armies`/`inspect_army`/`list_issues`/`inspect_issue`/`list_external_powers` + `submit_report`），按需查盘面，写完邸报调 `submit_report` 提交正文；`submit_report` docstring 承载完整奏章写作规范（结构/笔法/局势/末章/禁忌），`season_simulator.md` 从 141 行精简至 54 行。
- **结算 agent（score_extractor）改 skill+tool 模式**：payload 去掉 regions/armies/buildings/ministers 五张全表，只保留 narrative + issues摘要 + id列表 + fiscal_config；挂 7 个工具（`get_region`/`get_army`/`get_external_power`/`get_active_ministers`/`get_issue_detail`/`get_faction_class_state` + `submit_extraction`），按章节按需查当前值算 delta；`submit_extraction` docstring 承载完整 JSON schema、16 字段约束、档位标准与骨架示例，`score_extractor.md` 从 266 行精简至 50 行；去掉 `force_json_output`，改由 tool docstring 约束格式。

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
