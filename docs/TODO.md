# TODO / TOFIX — 探针待修与待办

> 上下文会被压缩，记忆不可靠。所有"要改但还没改"的事，一律记这里。每次发现新问题就追加，修完就划掉（`~~划线~~` + 注明修复 commit/日期）。

## 🔴 BUG / 待修（影响游戏正确性）

### B4. 皇帝推动的国策(initiative)是空壳进度条，跑完无回报 ✅ 已修（2026-06-07，CLI 后端）
- **现象**：玩家诏书推动的国策(清丈田亩/西学/太学府/经济封锁…)bar 推到 100「已成」后，盘面无任何变化——`ongoing_effects`/`effect_on_resolve`/`effect_on_fail` 全空。「跑完就是跑完了」。
- **根因（实测定性，非臆断）**：extractor 立国策时**该填的效果字段一贯不填**。schema 支持（DELTA_SCHEMA new_issues 有这三字段）、prompt 也要求（score_extractor_issues.md:46/68 写「必须/必带」）、落库代码也读（issues.py + 别名 simulation.py:82-91 中英全覆盖、`_canonical_item_fields` 全递归）——**唯独 LLM 不产出**。agy 实测 0/4（格致局×1 + 多国策×3 全空）。系统危机(situation)有效果是因为 seed_events.json 预填了。
- **修复（A 方案：把回报挂在局势自己身上）**：落库时**校验** decree-initiative 的 `effect_on_resolve`，空则**聚焦补全**：
  - `cli_backend.enrich_initiative_effects(title, stage)`：纯数值设计调用（不扮演，与月末 extractor 同款可靠），按国策标题/现状生成 解决效果(建筑 create/民心皇威国库增量)+持续效果(月耗)+失败效果，经 `_canonical_item_fields` 规范化成英文 key，建筑缺 region_id 兜底 beizhili。
  - `issues.py` new_issues 落库前：CLI 后端 + initiative + 空 resolve → 调补全；补全也失败 → floor `{民心:+1}`，**绝不入空壳**。
  - 引擎结案时(issues.py:717-723)读 stored `effect_on_resolve` 发 metrics/economy/buildings/legacy——已有逻辑，无需改。
- **实测**：营建国策落库带「建筑 create 京师格致局·科技·产皇威3 + 民心5/皇威15/国库-30 + 月耗-5」；走真实 `apply_issue_tracker_output` 推满结案，**建筑真的建出来**。
- **代价**：每条新国策月末多一次 ~12s agy 补全（agy 一贯不填→基本每条都触发）。
- **范围**：仅 CLI 后端 gated。api 后端历史上「大部分有效果」（强模型自觉填），不走此补全。B 方案（国策同步产 fiscal_creates/new_armies 等独立 delta，对治 T3/T4）后续看需要再补。

### B1. 阉党核心退场，faction leverage 不联动下跌 🔧 已临时修复（见底部修复记录，遗留根因未解）
- **现象**：崇祯元年十一月，田尔耕（流放）、崔呈秀（乞休）、王体乾（致仕）三个阉党核心都退场了，但 `factions.阉党.leverage` 仍是 **78（全场第一）**，只有 satisfaction 跌到 32。
- **根因**：我产 delta 时 `faction_delta` **只改 satisfaction，不改 leverage**（见 DELTA_SCHEMA.md：faction_delta 作用于 satisfaction）。而 `character_status_changes`（人物退场）**没有联动扣减所属派系的 leverage**。
- **应有行为**：一个派系的核心人物（尤其握实权官职者：兵部尚书/司礼监掌印/锦衣卫都督）退场/下狱/致仕时，该派系的 leverage 应按其官职权重相应下跌。阉党核心尽去，leverage 该从 78 跌到 30-40 区间。
- **待查**：`faction.leverage` 到底怎么改？
  - 选项 A：人物退场时由引擎自动按官职权重联动扣 faction leverage（改 db.set_character_status 或 apply_character_status_changes）
  - 选项 B：扩展 delta schema，让我能直接产出 faction leverage 增量（目前 faction_delta 只走 satisfaction）
  - 选项 C：临时 workaround——下回合我在 delta 里手动修正阉党 leverage（需先确认有无 leverage 改法入口）
- **下回合临时处理**：崇祯元年十二月结算时，手动把阉党 leverage 往下压到合理值（先查清改法），并在邸报里叙述"阉党失了要津、号令不行"。

### B2. CLI 后端(agy)把游戏仓库当工作区，自治探查源码 + 英文行动计划泄进大臣嘴里 ✅ 已修（2026-06-07）
> 修复：`_run_agy`/`_run_codex` 加 `cwd=_AGY_CWD`（`/tmp/ming_agy_sandbox` 空目录）；`_messages_to_prompt` 加“无文件/工具/命令、禁英文、禁旁白”硬约束；`_strip_agent_narration` 剥开头英文行动计划兜底。实测孙承宗防务问答 0 英文词。
- **现象**(2026-06-07，probe/session-as-llm 分支)：孙承宗被问蓟镇宣大防务，回话开头冒出整段英文："I will list the contents of the workspace directory to locate the relevant database files... check the `data` directory... list the `ming_sim` directory to understand the project structure and see how state queries are implemented." 之后才接中文奏对。
- **根因**：`ming_sim/cli_backend.py` 的 `_run_agy` 用 `subprocess.run([...], input=prompt)` **没指定 cwd**，agy(自治编程 agent)继承了游戏仓库根目录当 workspace，把"汇报防务进度"当成研究任务，跑去翻 `ming_sim/`、`data/` 找答案。`--sandbox` 只挡写不挡读。
- **双重危害**：① 英文行动计划 narration 泄进角色对话(出戏)；② **元游戏泄漏**——大臣能读游戏真实源码/存档 DB。
- **修法(1)**：
  - 主治：`_run_agy`/`_run_codex` 传 `cwd=<空临时目录>`(如 `/tmp/ming_agy_sandbox`，启动时建)，agy 进空 workspace 无可探。
  - 加固 prompt：`_messages_to_prompt` 明示"你没有任何文件/工具/命令可用，不要描述你要做什么，直接以角色身份用中文作答，禁用英文"。
  - 兜底：输出后剥掉开头的英文行动计划行(`^(I will|Let me|I'll|First|I need to|Looking at|I'm going to)` 等)。
  - cwd 是治本，后两者兜底。

### B3. 大臣"自己动手"的动作工具在 CLI 后端不触发(拟旨/下密令不入档) ✅ 已修（2026-06-07）
> **原版**靠 agno 工具 `propose_directive`/`secret_order`，api 模型 function-call 可靠触发。agy 不做 function-calling = 唯一缺口。
> **最终方案（简单可靠，绕了几道弯才想明白）**：玩家用拟旨/密令按钮 = 消息带「拟旨如下：/密令如下：」前缀 = 已表态要下旨，那大臣**这一句回话原文整段入档**即可——不解析圣旨边界、不用 JSON、不用正则。大臣本就把相关衙门/人等写进回话（原 prompt 行为），所以回话原文就是补全版圣旨。多轮聊出多道 → 颁诏时玩家去重。
> - `cli_backend.resolve_minister_actions(minister_reply, player_message, default_assignee)`：前缀命中则把回话原文当 directive。
> - **密令的结构化字段**（title/content/承办人/期限/标签）原版靠 function-call 让大臣顺手填，agy 无 function-call 丢了。补法 = `_extract_secret_order`：下密令时**多一次聚焦提取 agy 调用**（纯抽取、不扮演，与月末 extractor 同款可靠，~12s）把命令+回话抽成四字段。实测能正确抓到「皇帝点名的承办人」「三月内回奏=期限3」「干净标题」。圣旨**不需要**此步——圣旨在原版也只是文本，机械后果（一次性 vs 常设月支 vs 建军/任命）由月末 extractor 算，agy 版同源无损。
> - `session.chat`（CLI）+ `web_app` 流式 handler（web）各调一次。core 改动小、CLI 后端 gated。`invoke` 只出文本（不再 JSON/正则）。
> - 实测：web 流式拟旨 directive（含户部/巡抚/洪承畴）+ 密令 secret_order 均落库；普通对话不误触发；月末结算无回归。
> - **弯路记录**（别重蹈）：先后试过 ① agno 合成 tool_call（流式 run_output 不 surface）② 散文正则捞「…钦此」（agy 时而不写正式圣旨）③ 强制大臣输出 JSON（被角色扮演 prompt 压制，agy 不遵守）。都不如「前缀已表态 → 抓回话原文」简单可靠。教训：别和 agy 的非确定性输出较劲，用玩家已有的明确信号。
- **现象**：大臣在聊天里"拟旨如下：…奉天承运皇帝…钦此"或下密令，文本出来了，但 `turn_directives`/`secret_orders` 表里**没有对应记录**——月末颁诏无东西可结算。
- **根因**：草稿/密令只能由 agno 工具 `propose_directive`/`issue_secret_order` 触发([session.py:597](../ming_sim/session.py)、[web_app.py:1120](../web_app.py))，检查 `run_output.tools`。CLI 后端(`CliChat`)**不做 function-calling**，无工具执行→分支永不进。
- **范围(实测，比想象小)**：
  - ✅ 玩家点的按钮(下密令直接落库 `POST /api/.../secret_order`、手动加草案 `POST /api/directives`、准/驳、颁诏)——独立端点，不经 LLM，**正常**。
  - ✅ 查询类(查驻军/查名册)——盘面快照本就注入大臣 prompt([registry.py:421-430](../ming_sim/registry.py))，军队≤30 支时全名册直接进 prompt，**大臣答得出**。
  - ⚠️ 问阻力——`estimate_resistance` 精确公式不跑，大臣只能定性编数。
  - ❌ 聊天里"拟旨""下密令"两个**前缀按钮**——靠大臣调工具，不入档。
- **修法(2 = "层次二"文本协议桥接)**：原生 function-calling agy 做不了，但动作工具是终结性的，可文本桥接：
  - 大臣 prompt(仅 CLI 后端)加约定：拟旨用 `<拟旨>旨意全文</拟旨>` 包裹、下密令用 `<密令 标题>内容</密令>`。
  - `CliChat.invoke` 收到 agno 传入的 `tools` schema，检测响应里的标记 → **合成 `propose_directive`/`issue_secret_order` 的 OpenAI tool_call** 塞进假 ChatCompletion → agno 现有入档逻辑原样触发，下游不改。
  - 兜底启发式：大臣忘打标记时，检测"奉天承运/诏曰/钦此"自动当拟旨。
  - 不碰通用工具循环(查询类靠注入已覆盖)。
- **B2、B3 一起改**(用户 2026-06-07 拍板：1+2 都做，玩完这局后)。

## 🟣 探针铁律 / 结构性发现

### P3. 品味护栏：国策=「当下旨意的具体后果」，不是「通往未来的进度树」（2026-06-07 拍板）
- 崇祯局是**末世短局求生**(在位仅 17 年)，核心张力=「越努力越发现无解」的悲剧 + 只算代价不分对错。
- **拒绝科技树/长线文明建造**(EU4/维多利亚那套)——会给「能发展出路」的爽感，稀释悲剧张力，17 年也铺不开树。新版作者加了预设科技树(化肥/火器新法…)，**我们不抄**。
- 国策落点：建军/人物去向/营建/财政/局势这些**此刻的实体后果**，不做「科技 1→2→3 升级线」。
- ⚠️ **这条是设计护栏，只写在 docs，绝不写进游戏 prompt**(2026-06-07 曾误把「别写成科技树」写进 season_simulator.md，已删——meta 设计话不进游戏内容)。

### P2. 军备/城防建模（火器·大炮·城市等级，2026-06-07，全 TDD）
- 军队两轴：`firearm_equipment` 0-100(鸟铳化，野战+守城)、`cannon_equipment` 随军红夷炮门数 cap 12(野战带不动多)。
- 地区：`city_level` 0-5(静态，史实分级，京师5…游牧0；将来兼供经济内政)、`cannon` 城防红夷炮门数 cap=`city_level×8`(城头炮，守城关键)。
- 全是**数据轴 + season_simulator 一句角色语义**，判战永远 LLM 软判，代码只 clamp 不算胜负(贴 P3 与「LLM 主导」)。佛郎机等轻炮归 firearm；随军炮利攻、城防炮利守。

### P1. 「决策当回合全量落库」是探针第一铁律（崇祯二年八月发现）
- **现象**：续局连发现 3 处"账实不符"——太学府经费(月500)没立 `fiscal_creates`、天雄军没建 `new_armies`、卢象升没 `office_changes` 调任。皆"下旨+邸报+推 issue bar"做了，机械后果没落 DB。
- **为何危险**：context-save→restore 后**叙事记忆蒸发、只剩 DB**。挂在叙事里的决策后果一律丢失 → "忘了好多"。用户实测痛点。
- **铁律**：**凡下旨，机械后果必须当回合全量落进 DB**，不许只活在邸报：
  - 带经费/俸/饷 → 配 `fiscal_creates`（见 [T3](#)）
  - 练兵/募营/调将镇地 → 配 `new_armies`+`office_changes`（见 [T4](#)）
  - 抄没/缴获/一次性收支 → `economy_moves`
  - 人物升黜 → `office_changes`/`character_status_changes`
- **判据**：restore 只读 DB 就能无损接续 = 落库到位；需要靠"我记得"补 = 漏了。
- **driver 固化时（T1）应加校验**：诏书文本里出现"每月/月支/练……军/授……将/调……镇"等触发词，而本回合 delta 无对应 `fiscal_creates`/`new_armies`/`office_changes` → 告警，逼人补齐。

## 🔵 探针工程待办（step1 → step2）

### T1. driver 还没固化成脚本
- 现在每回合结算都用 `python3 - <<'PY' ... PY` 内联 heredoc 跑，没有持久 driver。
- 应固化成 `driver.py`，封装：`state`（读盘）/ `settle --delta <json>`（固定tick+apply+惯性+推进）/ `dump`（盘面），复用 DELTA_SCHEMA + SETTLEMENT_FLOW。
- 好处：可复现、可调试、delta 从文件喂入不易出错。

### T2. step2 subagent 化（已立 issue）
- 见 GitHub [issue #1](https://github.com/Akagilnc/ming-salvage-sim/issues/1)。
- 主对话当调度器、subagent 当大臣/裁判，解决 context 污染。
- 触发条件：step1 跑通、玩法验证 OK（✅ 已验证两个月闭环）。可以开始考虑了。

### T3. 立"带月经费的国策"时必须同产 fiscal_creates（已踩坑）
- **教训**：崇祯二年二月立「大明皇家太学府」(issue 14, 月经费 500 万) 时，**只做了 issue（进度条），漏产对应的 `fiscal_creates` 常设月支**——"月500万"只在邸报叙事里，账上 4 个月（二~五月）一两没扣，崇祯二年六月被陛下当面发现。
- **铁律**：凡诏书新政带"每月 X 万经费/俸/饷"的，产 delta 时**issue + `fiscal_creates` 必须成对出**（issue 管进度、fiscal_creates 管账）。一次性投入才用 `economy_moves`。
- **已补**：崇祯二年六月起 `taixuefu_base`(国库 expense 500) + `huoqi_base`(国库 expense 200) 已立账；六月当月用 economy_moves 补扣、常设账自七月固定 tick 起自动走（采甲案：前 4 月不倒补）。

### T4. "练新军/编新营"国策必须同产 new_armies + office_changes（已踩坑）
- **教训**：「荡寇天雄军」国策(issue 13)崇祯二年六月结案=练成，但**只做了 issue 进度条，漏了 ① `new_armies` 建天雄军军籍记人马 ② `office_changes` 把卢象升从大名知府调任为带兵主将**。结果"卢象升移驻东协"只在邸报，军册上查无天雄军、卢仍是文官知府，崇祯二年八月被陛下"卢象升现有多少人马"一问当场穿帮。
- **铁律**：凡诏书"练某军/募某营/调某将镇某地"的，产 delta 时 **issue（进度）+ `new_armies`（军籍人马）+ `office_changes`（主将调任）必须配齐**。光推 bar 不落实体 = 账实不符。
- **已补**：崇祯二年八月立天雄军军籍(兵 18000)+ 调卢象升「荡寇将军」督天雄军镇蓟镇东协·喜峰口、受孙承宗节制。

## 🟡 观察 / 待确认（未必是 bug）

### O1. 客氏出宫但 status 仍 active
- 客氏被送出宫颐养，但 `characters.客氏.status` 仍是 active（她还活着、只是不在宫）。游戏没有"出宫/居家"这个状态。
- 暂不算 bug（active=在世可被提及），但若后续要表达"已离开权力中心"，需考虑用 offstage 或加注。

### O2. 大额一次性支出 vs 国库节奏
- 十一月三镇补饷一次性 -300 万走 economy_moves，国库够（金矿兜底）。但若没有金矿外挂，这种大额会瞬间击穿国库。原版游戏没有金矿，玩家需量入为出——这正是原版的难度来源。我们有金矿，难度被抹平了（金手指的副作用，符合预期）。

---
**修复记录**：（修完的移到这里，注明日期）
- **[崇祯元年十二月结算]** B1 阉党 leverage：用手动 SQL `UPDATE factions SET leverage=35 WHERE name='阉党'` 临时修复（叙事支撑=核心退场+四十余党羽清出要津），78→35。**遗留根因未解**：长期应让 `db.set_character_status` 在"握实权官职的核心人物"退场时，自动按官职权重联动扣减所属派系 leverage，而非每回合手动 SQL。下次重构结算管线时一并做。
