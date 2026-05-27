# 暂留区改动总结

本文档总结当前 Git 暂留区内的改动，基于 `git diff --cached` 生成。

## 总体目标

这批改动把原先偏“外部势力”的系统升级为更通用的“势力 / 归属”世界盘面：大明、后金、蒙古、朝鲜、流寇等都进入统一 `powers` 注册表，人物、地区、军队都能明确归属到某个势力。围绕这个核心，结算抽取、月末推演、数据库结构、Web 展示和 CLI 配置都做了配套调整。

同时，改动强化了月末结算的结构化能力：支持新建军队、人物易主、势力三项变化、外交态度 KV、工程/建筑局势结案落地，并将 extractor 的共同契约拆成共享提示词以减少各模块重复。

## 规模概览

- 共 57 个暂留文件。
- 约 2693 行新增、688 行删除。
- 主要类型包括：内容 JSON、Prompt、核心 Python 逻辑、Web 前端、Web API、CLI 参数、臣工头像资源。
- 新增 21 张臣工头像资源到 `web/public/portraits/`。

## 内容与世界盘面

### 势力系统重命名与扩展

- `content/external_powers.json` 重命名为 `content/powers.json`。
- 代码中的 `ExternalPower` 概念改为 `Power`，数据库表从 `external_powers` / `external_power_logs` 改为 `powers` / `power_logs`。
- `powers` 新增 `kind` 字段，用来区分大明、敌国、部族、藩属、流寇等。
- 原先“威胁 / 兵势 / 粮饷”的展示语义调整为更中性的“威望 / 实力 / 经济”。

### 人物、地区、军队增加归属

- `characters` 增加 `power_id` 与 `location`。
- `regions` 增加 `controlled_by`。
- `armies` 增加 `owner_power`。
- 内容数据中为大明人物、地区和军队补齐默认归属，并新增一批后金、蒙古、朝鲜、流寇相关人物、地区和军队。
- `armies.json` 新增后金八旗主力、汉军与辽人降兵、察哈尔诸部骑兵、朝鲜边军、王嘉胤部等非大明军事实体。
- `regions.json` 扩展到辽东外线、蒙古、朝鲜、奴儿干等外部地区。
- `characters.json` 新增皇太极、代善、莽古尔泰、范文程、林丹汗、朝鲜君臣、王嘉胤等外部势力人物。

### 技能与官署分类

- `skills.json` 重新格式化为多行 JSON，并新增“外臣”官署类别。
- 外臣类别用于世界盘面人物归类，不授予大明朝堂工具。

## 数据库与落库逻辑

### Schema 兼容

- `GameDB` 建表和迁移逻辑新增：
  - `powers.kind`
  - `characters.power_id`
  - `characters.location`
  - `regions.controlled_by`
  - `armies.owner_power`
- 继续用 `ensure_column` 兼容已有数据库。

### 新增落库能力

- 新增 `apply_power_deltas`：只处理非大明势力的 `威望 / 实力 / 经济` 三项增量。
- 新增 `apply_character_power_changes`：处理降敌、投寇、反正、归明等人物势力归属变化。
- 新增 `create_armies_from_extraction`：支持 extractor 输出 `new_armies` 后创建新军队；若 id/name 已存在，则转为既有军队扩编。
- `apply_region_deltas`、`apply_army_deltas` 支持中文字段别名和新增归属字段。
- 局势自然完成或失败时，也会应用 `effect_on_resolve` / `effect_on_fail` 中的建筑效果，避免工程局势结案后建筑不落地。

## 推演与结算抽取

### 推演 payload 复用

- 新增 `build_simulator_payload` 与 `simulate_season_with_payload`。
- 月末推演输入会注入 simulator agent 的 system context，调用时 user payload 变轻。
- extractor agent 也注入同一份 `simulator_payload` 和 `extractor_context`，意图是复用模型上下文缓存、减少重复 token。

### 模块化 extractor 契约调整

- 新增 `content/prompts/score_extractor_shared.md`，集中放置 extractor 通用字段契约。
- 各模块提示词改为更偏中文字段输出，程序通过别名 canonicalize 成内部字段。
- 顶层抽取字段从原来的 `external_power_updates` 调整为：
  - `new_armies`
  - `power_updates`
  - `character_power_changes`
  - 更简化的 `world_advance`
- `world_advance` 从四方小作文结构简化为外交态度 KV，如 `{"后金":"敌对","蒙古":"摇摆"}`。
- `military_external` 模块现在负责军队变化、新建军队、势力变化和外交态度。
- `personnel_secret` 模块新增人物易主抽取。

### Prompt 规则强化

- `season_simulator.md` 明确要求：
  - 募兵、设新军、流寇坐大时，要写成成建制新军，供档房抽 `新建军队`。
  - 实体营建和科技新法必须作为独立工程 / 改革局势写，不要并入亏空等既有事项。
  - 官军倒戈、人物降敌、归明等要在叙事中明确，以便抽取归属变化。
- `game_world.md` 调整世界观描述：势力本身作为注册表和外交对象，实际强弱更多来自其控制地区、所属军队、关键人物和外交态度。
- `memory_extractor.md` 将 `subject_type` 的 `external_power` 改为 `power`。

## 胜负、工具与报告

- 胜负判定从固定查看关宁 / 山海关，改为聚合 `owner_power='ming' AND theater='辽东'` 的大明辽东军力。
- issue gate key 从 `external.<id>.<field>` 改为 `power.<id>.<field>`。
- 工具、注册表、回合报告中的外部态势引用统一切换到 `power_report(exclude_self=True)`。
- `tools.py` 的 schema / 示例更新为新字段：`power_updates`、`world_advance`，并提示不要把势力字段写入军队字段。

## LLM 配置

- CLI 新增：
  - `--advanced-base-url`
  - `--advanced-api-key`
- `LLMConfig` 新增：
  - `advanced_base_url`
  - `advanced_api_key`
- advanced 角色现在可使用独立网关和独立 API Key；留空时仍复用主 base URL / API Key。
- Web 设置页和菜单设置页同步支持 Advanced Base URL / Advanced API Key，并保存到 runtime config。

## Web 前端与 API

- 前端类型新增 `Power`、`power_id`、`controlled_by`、advanced 配置字段。
- 状态 payload 中：
  - `external_power_warning` 改为 `power_warning`
  - `external_powers` 改为 `powers`
- 结算展示支持中文字段与英文字段兼容读取。
- 新增 `NewArmiesBlock`，用于展示本回合新建军队。
- 人物公开数据返回 `power_id`，方便前端区分大明朝臣、外臣、流寇等。
- 删除了一个旧的 `/api/ministers` 路由实现，前端可能已改用其他人物接口。

## 素材资源

- 新增 21 张臣工头像，包括孙传庭、孙承宗、崔呈秀、张瑞图、施凤来、曹化淳、曹文诏、毕自严、洪承畴、温体仁、满桂、王体乾、王绍徽、田尔耕、祖大寿、袁崇焕、赵率教、钱谦益、阎鸣泰、韩爌、黄立极等。

## 兼容与风险点

- 既有数据库需要依赖 `ensure_column` 完成迁移；但旧表 `external_powers` 是否需要数据迁移到 `powers`，要看运行时是否已存在旧库且 `powers` 为空。
- `content/powers.json` 是 rename 后的新入口，任何仍引用 `external_powers.json` 的脚本或文档需要同步清理。
- Prompt 和程序同时支持中文字段别名，但 extractor 输出若混用旧字段，主要依靠 canonicalize 兜底；建议跑一轮实际结算验证。
- `owner_power`、`controlled_by`、`power_id` 进入核心逻辑后，内容数据缺默认值会影响建库和筛选，后续新增内容要注意补齐。
- Web 端删除旧 `/api/ministers` 路由后，需要确认前端没有仍调用该接口。

## 建议验证

- 运行一次内容加载 / 建库 smoke test，确认 `powers`、人物、地区、军队归属字段正常入库。
- 跑一次 CLI 或 Web 月末结算，重点看：
  - simulator payload 是否正确注入；
  - extractor 是否输出中文字段并被 canonicalize；
  - `new_armies` 是否能建军；
  - `character_power_changes` 是否能改人物归属；
  - `power_updates` 是否只改非大明势力；
  - 工程局势结案时建筑是否落库。
- 检查 Web 结算面板是否能展示 `新建军队`、`势力变化`、`人物易主` 等新字段。
