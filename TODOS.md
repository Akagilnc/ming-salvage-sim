# TODO / TOFIX — 探针待修与待办

> 上下文会被压缩，记忆不可靠。所有"要改但还没改"的事，一律记这里。每次发现新问题就追加，修完就划掉（`~~划线~~` + 注明修复 commit/日期）。
>
> **追踪方式（2026-06-08 起，渐进迁移）**：主用 GitHub issue 记问题/讨论/状态；本文件**逐步舍弃**，只留「需要做、但不值得单开 issue 的小事」+ 已上 issue 项的指针索引。新发现的实质 bug/架构项直接开 issue，不再在此写长条目。

## 🟠 PR #2 CMR Deferred（cross-model review 8 轮 5/5 concur 后 defer 的契约/架构项）
- ~~D1 settlement 事务半落库 → [issue #3](https://github.com/Akagilnc/ming-salvage-sim/issues/3)~~ ✅ ADR 0008 PR1 (v0.8.0.0, 2026-06-11)：后半段单一事务 `applier.atomic` + 可恢复 resolve_context + 响亮中止/错误包（合并后手动关 issue，等用户验收）
- ~~D2 城防炮 region.cannon 无 delta 写入路径 → [issue #4](https://github.com/Akagilnc/ming-salvage-sim/issues/4)~~ ✅ PR #16 (v0.5.1)
- D3 conftest 依赖 gitignored probe.db → CI 假绿 → [issue #5](https://github.com/Akagilnc/ming-salvage-sim/issues/5)
- D4 _loads_lenient JSONC 非 quote-aware 病态边界 → [issue #6](https://github.com/Akagilnc/ming-salvage-sim/issues/6)

## 🟠 branch probe/chat-action-pending CMR Deferred（动作闸门确认 UX 重设计，cmr ship-pre 5 轮收敛后 defer，未上 issue）
- CA1【P3 行为缺口·fail-safe】口头用自然语言把**已在位**的妃嫔升位份（嫔→贵妃）：`_commit_office_action` 任命走 consort 路 → `apply_appointment`（[session.py](ming_sim/session.py)）对在位同名妃 `_find_candidate_by_name` 不中 + 非 candidate → 返 `("","")` → commit 标 failed（不崩、不错落，仅升妃没生效）。要不要支持「口头升妃」属品味题；要支持则在 consort 路加「在位妃→改 office/位份」分支。CMR R2/R4 由 Claude 单独提、判 low。
- CA2【P3 死代码】前端「待颁诏」面板拆掉后，`web_app.py` 的 `GET /api/pending_actions` + `POST /api/pending_actions/{id}/withdraw` 两端点 + `tests/test_pending_actions.py` 内 `api_pending_actions`/`api_withdraw_pending_action` 用例**没人再调**（确认改对话驱动）。用户「先留着」；要清就连测试一起删。CMR R5 Claude 顺带提（非 review finding）。
- CA3【验证待办·非缺陷】Slice 4 给 `content/prompts/minister_agent.md` 加的「in-character 领命并补充信息和要点」是 prompt 改、行为=LLM 输出，**无法确定性单测**；需在跑着的 server 上真召对一轮，确认大臣不出戏、不弹系统式「确认?」问句。

## 🔴 BUG / 待修（影响游戏正确性）

### B12. 密令状态在游戏画面露英文 enum（active/pending_review/done/failed） → [issue #48](https://github.com/Akagilnc/ming-salvage-sim/issues/48)
- **现象**：「密旨动向」等展示里密令 status 直接渲染数据库英文 enum「（active）」，明末中文游戏里露英文，出戏。
- **修法**：在展示层把 status enum 映射成中文（active→在办、pending_review→待核议、done→已结、failed→未成 之类），找密令 status 渲染处（web 前端密令面板 / 邸报或 notes 生成器）统一过一层 label 映射。
- **注**：与 LLM 通道 PR 无关，是既有展示/i18n bug；非本次 channel 改动引入。

### B11. 全系统静默吞异常/吞畸形数据（不抛错不告警），该落没落无人知 → [issue #14](https://github.com/Akagilnc/ming-salvage-sim/issues/14)
- 系统级模式（从 B10 抽象）：delta 畸形项 `continue` 丢弃 / apply 拒收只记 `rejected` 不报 / db.py broad `except` 返默认 / gate 解析失败返 None。后果=静默数据丢失 + DB↔叙事漂移 + 调试盲区，侵蚀 P1 落库铁律。修法待定（结算级 reject 收集器 / except 收窄记日志 / gate 失败区分）。与 #3、#13 同根。
- **进展（v0.8.0.0, ADR 0008 PR1）**：「结算级 reject 收集器」已落地（`applier.RejectionCollector`，provenance + 事务内落 DB + commit 后镜像 JSONL）；shape 垃圾/损坏 JSON 改响亮中止+错误包。**剩余**：apply 各分支真正接上 collector（PR1 只建契约层）、db.py broad except 收窄、gate 解析失败区分——issue #14 不关。

### B10. delta 顶层 key 近义易混（人事变更/人物状态变化）+ office_changes 静默拒收吞死亡 → [issue #13](https://github.com/Akagilnc/ming-salvage-sim/issues/13)
- "毛文龙没死"真因：turn21 我把毛的死产进 `人事变更`(office_changes)而非 `人物状态变化`(character_status_changes)，office_changes 因 `new_office` 空静默拒收（[issues.py:1250](../ming_sim/issues.py)）。两个中文 key 太像。rename 候选（待议）：office_changes→`职务变更`、character_status_changes→`人物状态变更`（alias 可保旧加新别名）。修正了 #12 对"毛没死"的归因。

### B9. 历史事件无结构化前提门，袁崇焕斩毛文龙在已安抚前提下误触发 → [issue #12](https://github.com/Akagilnc/ming-salvage-sim/issues/12)
- **现象**（turn21/1629-06 实测）：玩家 turn20 已安排袁安抚毛、奏对确认"毛饷已足、效顺"，`mao_wenlong` 仍被 simulator 弹出（`event_triggers` turn21 source=simulation）；邸报叙述"列十二罪斩毛文龙于帐前"，但 DB 里 `characters.毛文龙.status=active`（**没死**）、军队 faction satisfaction 仍 100。
- **根因 B9a（机制）**：`gather_candidate_events`（[issues.py:308](../ming_sim/issues.py)）历史分支（`trigger_year>0`）进候选池只过 `_event_window_open`（纯日历窗口），无代码前提校验；`precondition`（[models.py:77](../ming_sim/models.py)）纯文本喂 simulator 软判。结构化硬门 `trigger_gate`+`_gate_passed`（[issues.py:270](../ming_sim/issues.py)，能查 character/faction/army/region）**只接 seed_events，没接历史 events**——守大事的门已造好但没接上。
- **根因 B9b（P1 违背）**：安抚决策从没落进结构化 DB（无密令/directive/毛 loyalty 增量），只活在奏对叙事 → 喂 simulator 的结构化盘面无"皇帝已干预防斩帅"信号；连事件结果（毛死）也没落库，DB↔邸报漂移。同类前科见 memory `sim-fabricates-appointments`。
- **修法**：A) 把 `trigger_gate` 接到历史事件，`gather_candidate_events` 历史分支也跑 `_gate_passed` + 给 `mao_wenlong` 加结构化硬前提（治本）；B) 让"安抚"成可落库状态（和解 flag/抬毛 loyalty），门去读；C) 事件触发时强制落 `character_status_changes`（毛→removed）。**A+B+C 互为前提，需一并修**。
- **注**：P1 机制坑（影响所有历史锚定事件，非仅毛文龙）。修前与 cmr session 在 issues.py/db.py 的改动核对避免撞车。

### B8. 游戏聊天框中文输入法不学词（Windows 群员报，待 cmr 完再修） → [issue #7](https://github.com/Akagilnc/ming-salvage-sim/issues/7)
- **现象**：Windows 群员在游戏聊天框打「拟诏/密令」等词，输入法**不学习**（不进用户词库、下次不联想）；同样的词在游戏外能学；回游戏又不联想。打字本身正常（字打得出），只是不学。
- **已排除**：① 回车劫持理论错——用户用**空格**确认候选，`handleKeyDown`(modals.tsx:578) 只拦 Enter，空格没被截；② 编码 UTF-8/GBK（开发者猜）在浏览器版站不住——`web/index.html`+`dist` 都有 `<meta charset="UTF-8">`、服务器返回 `charset=utf-8`，不会回退 GBK，且编码错=乱码非"打得出但不学"。（Electron 打包版未在 mac 验。）
- **最可能真因（未证实）**：聊天 textarea(`web/src/components/modals.tsx:668`) 是受控组件 `value={input} onChange=...`，**无任何 composition 处理**。输入法合成期 onChange 每次更新就 setState→重渲染→React 重写 value，扰乱合成提交。此 bug 在 **Windows 输入法(搜狗/微软拼音)远比 macOS 严重** → 对上"和 Windows 有关"+"app 侧"。
- **修法候选**：modals.tsx 聊天 textarea 加 `onCompositionStart/End` 守卫，合成期不 setState/不重写 value，`compositionEnd` 一次性落；`handleKeyDown` 顺手加 `isComposing` 守卫；同样隐患扫全前端其它 textarea(主聊天/作弊台 main.tsx:1148)。
- **注**：最终须 **Windows + 真实输入法**实测（mac 复现不了 Windows IME），改对方向≠包好。

### B7. CLI 大臣回话偶夹英文（opus code-switch，待摸清再修） → [issue #8](https://github.com/Akagilnc/ming-salvage-sim/issues/8)（0b30d35 已部分治）
- **现象**：opus 后端毕自严回话蹦英文「各衙门account册移交故意拖延」。玩了很久第一次出现 → 疑本 session 改动或换模型带出。
- **可疑诱因（未定论）**：① 换 opus(可能比旧模型更易 code-switch)；② `build_building_brief` 注入拼音 region_id（beizhili/nanzhili…，本 session fd96d96 加的）把英文塞进 system；③ agno skills/tools 框架英文元数据（active/skill/scripts/description… ~117 token）一直在 system 里（CliChat 忽略 tools、function-calling 本不可能，纯属注入污染）—— 但这是早就存在、之前没触发。
- **已回滚的过激修法（e0b497e，已 revert d443d9d）**：曾 CLI 后端删大臣 tools/skills + 中文行为约束补回 + 建筑表中文地区名。教训：**没摸清 .agno_skills SKILL.md 里夹带的行为约束(密令不可自称已执行/拟旨前核名册等)就一刀删，删过头**；且"玩很久才首现"更像本 session 引入，不该靠洁癖式删工具救。
- **下一步（摸清再动）**：先定位主诱因（建议：单独把 building_brief 改中文名试一版、对比；或确认 opus 是否对纯中文 prompt 也偶发夹英文）。修法候选：a) 仅去英文壳(region 名中文化、skills 元数据精简)保留 skill 指引；b) 真要去 skills 须把行为约束完整搬成中文，且确认不影响 api 后端。别再盲删。

### ~~B6. toolcall 在 CLI 后端的缺口~~ ✅ 全修（2026-06-07）
- **动作类(全补，前缀/意图触发 + 落库 + refresh)**：拟旨；密令 create/update(upsert)/submit/rush/progress；**调教妃嫔 cultivate_consort**(后宫+调教意图→聚焦提取技能/性格→落库)。
- **READ 类(注入大臣 system)**：军表(含火器/大炮)、**地区危情(region_report)**、**建筑紧凑表(build_building_brief)**；court/记忆/邸报/钱粮/在办事项原已注入。
- **核实非缺口(不是替代路径搪塞，是其本身的原生路径)**：dismiss/summon = 纯召对流程(结束召见/换下一位)，CLI 下关对话框/点大臣即原生操作，不改状态；罢免/选妃 = 玩家下旨→extractor 人物状态变化/后宫册封，下旨本就是皇帝的原生手段。
- 测试：`test_cli_backend.py`(分类+提取)、`test_minister_context.py`(READ brief)、`test_secret_order_*`、`test_army_firearms`(军表火器)。52 passed。

### ~~B5. 公开圣旨混进保密话术~~ ✅ 已修（2026-06-07）
- 根因=toolcall 修复后「拟旨」抓大臣回话原文整段进草案池，`诏书润色官`无护栏，把密令性保密话术（密旨/密募/严防外泄/防外朝物议）揉进**公开圣旨**。
- **修复**：`content/prompts/decree_writer.md` 加护栏「公开诏书禁含自指保密话术」，密事要么不入公开诏、要么只写明面事由。单测 `test_decree_writer.py` 验证护栏注入；真实验证（opus 含密语草案产诏）保密话术 **0 命中**。

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

### B1. 阉党核心退场，faction leverage 不联动下跌 🔧 已临时修复（见底部修复记录，遗留根因未解） → [issue #9](https://github.com/Akagilnc/ming-salvage-sim/issues/9)
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

## 🟣 探针铁律 / 结构性发现 → 已迁 CLAUDE.md
> P1（决策当回合全量落库·第一铁律）/ P2（军备城防建模数据轴）/ P3（国策非科技树·品味护栏）
> 是「AI 每 session 别违背/别重决」的设计铁律，已迁到项目 **`CLAUDE.md` →「探针设计铁律」节**
> （tracked + 每 session 加载，比 TODO 更合适）。本节只留指针。

## 🔵 探针工程待办（step1 → step2）

### ~~T1. driver 固化成脚本~~ ✅ PR #16 (v0.5.1) → [issue #10](https://github.com/Akagilnc/ming-salvage-sim/issues/10)
- 已落地 `driver.py`：`state` / `settle --delta <json>`（信封 `{narrative,decree_text,delta}`）/ `dump`，复用从 decree.py 抽出的 `pre_settle`+`settle_with_delta`（ADR 0004，与真实流程同核）。delta 从文件喂入、按 schema 校验容器类型崩前拦。

### T2. step2 subagent 化（已立 issue）
- 见 GitHub [issue #1](https://github.com/Akagilnc/ming-salvage-sim/issues/1)。
- 主对话当调度器、subagent 当大臣/裁判，解决 context 污染。
- 触发条件：step1 跑通、玩法验证 OK（✅ 已验证两个月闭环）。可以开始考虑了。

### T3. 立"带月经费的国策"时必须同产 fiscal_creates（已踩坑） → [issue #45](https://github.com/Akagilnc/ming-salvage-sim/issues/45)（实例已补，缺引擎级强制配对）
- **教训**：崇祯二年二月立「大明皇家太学府」(issue 14, 月经费 500 万) 时，**只做了 issue（进度条），漏产对应的 `fiscal_creates` 常设月支**——"月500万"只在邸报叙事里，账上 4 个月（二~五月）一两没扣，崇祯二年六月被陛下当面发现。
- **铁律**：凡诏书新政带"每月 X 万经费/俸/饷"的，产 delta 时**issue + `fiscal_creates` 必须成对出**（issue 管进度、fiscal_creates 管账）。一次性投入才用 `economy_moves`。
- **已补**：崇祯二年六月起 `taixuefu_base`(国库 expense 500) + `huoqi_base`(国库 expense 200) 已立账；六月当月用 economy_moves 补扣、常设账自七月固定 tick 起自动走（采甲案：前 4 月不倒补）。

### T4. "练新军/编新营"国策必须同产 new_armies + office_changes（已踩坑） → [issue #46](https://github.com/Akagilnc/ming-salvage-sim/issues/46)（实例已补，缺引擎级强制配对）
- **教训**：「荡寇天雄军」国策(issue 13)崇祯二年六月结案=练成，但**只做了 issue 进度条，漏了 ① `new_armies` 建天雄军军籍记人马 ② `office_changes` 把卢象升从大名知府调任为带兵主将**。结果"卢象升移驻东协"只在邸报，军册上查无天雄军、卢仍是文官知府，崇祯二年八月被陛下"卢象升现有多少人马"一问当场穿帮。
- **铁律**：凡诏书"练某军/募某营/调某将镇某地"的，产 delta 时 **issue（进度）+ `new_armies`（军籍人马）+ `office_changes`（主将调任）必须配齐**。光推 bar 不落实体 = 账实不符。
- **已补**：崇祯二年八月立天雄军军籍(兵 18000)+ 调卢象升「荡寇将军」督天雄军镇蓟镇东协·喜峰口、受孙承宗节制。

### T5. 密令应支持「撤销/提前结束」（玩家面，留待深挖密令机制时做）
- **缺口**：当前密令(secret_orders)只有建/列两个端点，status 仅 active/pending_review/done/failed，**无玩家面的「撤回/作废/提前结束」**。能撤的只有「撤回召对」（回合级 undo，仅最后一轮、颁诏前）或结算时 close 为 failed。
- **范式**：照局势(issue)的 `cancellable=decree`（可撤旨）+ `cancel_cost`（撤销代价）那套——已颁诏的密令可由「圣旨撤回 + 代价」收回（人已派/钱已花的沉没成本）。见 `db.cancel_issue`(db.py:5060) + `_normalize_cancellable`(issues.py:555)。
- **时机**：属「颁诏后玩法」，**不在 pending_actions(slice 4+5)范围**；留到后续深挖密令机制专项时做。

### T6. 未颁诏草案不该广播给所有大臣（roleplay 硬伤，独立于 pending_actions）
- **现状**：`build_draft_line`(session.py:573)把「本{月}已核定草案」前置注入**每个**大臣的对话上下文，代码注释当 feature（"确保大臣看得到兄弟大臣最新动作"）。
- **问题**：未颁旨的东西不该全员全知。对话中的大臣记得=靠对话记忆（正常）；**别的大臣凭什么知道**？密令更应保密。
- **范围**：改的是**现有拟旨/草案可见性**，与 pending_actions(slice 4+5)的 reroute 可分离；slice 4+5 的新 pending **不广播**（皇帝 UI 看得到、对话大臣靠对话记忆、其他大臣看不到），不依赖也不扩展 `build_draft_line`。本条单独处理该广播本身。
- **细化待定**：首辅/内阁等是否对**公开政策**草案有合理知情权（密令永远保密）——留作该 issue 内的子决策。

### T7. 拟旨为何走叙事 extractor 而非结构化直写——分析合理性，理由不足则统一
- **现状不对称**：颁诏落地时，密令/任命/后宫走**结构化直写**(`commit_pending_actions` 直 INSERT/UPDATE)，但拟旨 draft 走 **LLM extractor**（draft 文本→邸报叙事→抽 delta，不直接写表，见 decree.py:414 / mark_directives_issued）。
- **表面理由**：拟旨是开放式诏书，效果可落在经济/地区/局势/任何模块，故由 LLM 解释成 delta；密令/任命/后宫是闭式结构化记录（确定字段），直写即可。
- **待分析**：这个理由够不够。若拟旨效果其实也能（部分）结构化、或 extractor 往返带来漂移/有损，**后续应统一**到结构化 staging。没有足够理由保留不对称就别留着。
- **范围**：拟旨机制不在 pending_actions(slice 4+5) 改动范围（slice 4+5 只动密令/任命/后宫的 reroute+颁诏直写），拟旨保持现状。本条单独找时间分析。

## 🟡 观察 / 待确认（未必是 bug）

### O1. 客氏出宫但 status 仍 active → [issue #11](https://github.com/Akagilnc/ming-salvage-sim/issues/11)
- 客氏被送出宫颐养，但 `characters.客氏.status` 仍是 active（她还活着、只是不在宫）。游戏没有"出宫/居家"这个状态。
- 暂不算 bug（active=在世可被提及），但若后续要表达"已离开权力中心"，需考虑用 offstage 或加注。

### O2. 大额一次性支出 vs 国库节奏 → [issue #47](https://github.com/Akagilnc/ming-salvage-sim/issues/47)（金手指副作用，低优先，可能并入 #43）
- 十一月三镇补饷一次性 -300 万走 economy_moves，国库够（金矿兜底）。但若没有金矿外挂，这种大额会瞬间击穿国库。原版游戏没有金矿，玩家需量入为出——这正是原版的难度来源。我们有金矿，难度被抹平了（金手指的副作用，符合预期）。

---
**修复记录**：（修完的移到这里，注明日期）
- **[PR #16 / v0.5.1, 2026-06-08]** D2 城防炮 region.cannon delta 落库路径(#4)+ T1 driver.py 固化(#10)：抽确定性结算核 `pre_settle`/`settle_with_delta`（ADR 0004，真实流程与 driver 同核）、城防炮路由 `apply_region_cannon`(city_level×8 clamp)、修 db.py 漏 import `LLMContractError`、driver 多处静默吞守卫。两轮 cross-model + ship review-army + 对抗 review 收敛。
- **[崇祯元年十二月结算]** B1 阉党 leverage：用手动 SQL `UPDATE factions SET leverage=35 WHERE name='阉党'` 临时修复（叙事支撑=核心退场+四十余党羽清出要津），78→35。**遗留根因未解**：长期应让 `db.set_character_status` 在"握实权官职的核心人物"退场时，自动按官职权重联动扣减所属派系 leverage，而非每回合手动 SQL。下次重构结算管线时一并做。
