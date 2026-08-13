# Ming_LLM — 项目 CLAUDE.md

## 这是什么
`wangwei-ying3/ming-salvage-sim` 的 fork（GPLv3）。明末崇祯 LLM 政略模拟器。
本仓库目的 = 做一个**探针**：把游戏的 LLM 后端从「外部 api key 调商业模型」换成 agent / 真实模型后端，验证「这游戏好不好玩」。**目前 web 版本是第一个尝试方向**（走真实 LLM 后端：codex / agy / hermes，见下）；**CLI 文字沉浸版（agent session 直接当后端：当前对话的 Claude / subagent）待后续开发**。

## 📚 工作手册（每回合开始前必查，别凭"我以为"）
- **[docs/DELTA_SCHEMA.md](docs/DELTA_SCHEMA.md)** — 我产 delta JSON 的格式契约：顶层字段、字段约束、白名单、踩过的坑。**产 delta 前查。**
- **[docs/SETTLEMENT_FLOW.md](docs/SETTLEMENT_FLOW.md)** — 月末结算管线：driver 调引擎的完整顺序 + 不变式 + 接口层。**写 driver / 结算时查。**
- **[TODOS.md](TODOS.md)** — 待修 bug + 探针工程待办。**每回合结算前扫一眼有无"本月要顺手修"的项**。
- **[docs/FISCAL_PROVINCE_SUBSTRATE.md](docs/FISCAL_PROVINCE_SUBSTRATE.md)** — 省级财政基座设计（三饷/火耗/起运存留/宗禄/逋赋/隐田），**22 轮跨模型评审已收敛，现 v23（2026-06-10 拍板补「三饷计火耗」：火耗应派=(正赋+三饷)×火耗率）**；可执行 spike `spike_settle_tick.py`（G1–G22 全 PASS，5 层断言+独立 oracle，~20 mutation 自验全咬）。**状态：`ming_sim` 已 port 省级 tick/DB bridge；新档已接入 substrate hub cutover，明控且已 seed 的省级起运、盐税、商税、太仓亏空、边饷 hub 与中央军饷开始驱动国库和分源欠饷；旧档保留 legacy 财政引擎**（见 [Milestone #1](https://github.com/Akagilnc/ming-salvage-sim/milestone/1) / Epic #65 / #261）。**非每回合必查；要动省级财政机制时查。**
- **[docs/AUDIENCE_NORTH_STAR.md](docs/AUDIENCE_NORTH_STAR.md)** — 召对体验**北极星案例**（单场·越次召对·杨嗣昌 + 连场·乾清宫一夜）：召对记录全文 + 海报 html + 小红书卡 + 王承恩递话旁白层 + 召对流程用词。**做 / 评召对时对着它比。**
- **[M11「北极星·召对效果」总计划/进度 = issue #486](https://github.com/Akagilnc/ming-salvage-sim/issues/486)**（pinned tracker，2026-07-02 立）——10 大方向执行顺序 + 排序逻辑 + 4.5 试玩检查点 + 进展评论日志。**做召对 / M11 相关工作先看它**；阶段进展只用 #486 评论追加，**别另建 md 工作清单**（工作清单曾以 M11-work-order.md 形态存在，已废转 tracker）。层级：#486（顺序）→ #470-479（大方向）→ 各自 sub-issues（方向/PRD/切片，原生挂接带进度条）。

## 探针架构共识（已 grill 定，别推翻重来）
- **定位**：探针（先验证好不好玩），不是地基。**不上 MCP**（连改哪层都没定，固化接口=过早工程化）。
- **代码基线**：copy 全套上游（已 fork），不在 copy 层取舍，按实际慢慢丢。
- **第一刀切片**：单回合透明闭环，目标**第一年（~12 回合）**，每步确定性计算摊开打印，让玩家边玩边摸清机制。
- **月末产出形态**：我每回合产 = 邸报叙事（给玩家看）+ 原 extractor schema 的**稀疏 delta JSON** → 喂 `apply_score_extraction` 落库。把原 simulator + extractor 两个 LLM 步**合并成我一次出**，省掉二次翻译。
- **形态分层（先甲后乙）**：
  - **step1（验证）**：形态(1) 我在对话里直接当 runtime+LLM，玩家当皇帝，`terminal.py` 当流程蓝本（不另起进程）。最快、零基建。
  - **step2（跑完第一年）**：形态(3) subagent 当各 LLM 角色（主对话=引擎调度，subagent=大臣/裁判），解决 context 污染、走订阅额度。见 GitHub issue。
  - 形态(2) 独立进程+桥：搁置到「换模型/分发」阶段。`claude -p` 走单独额度不划算；codex / agy(gemini) 订阅可行。

## 探针设计铁律（已 grill 定，别违背 / 别重决；自 docs/TODO.md 🟣 迁来 2026-06-08）
- **P1 决策当回合全量落库（第一铁律）**：凡下旨，机械后果**必须当回合全量落进 DB**，不许只活在邸报——带经费/俸/饷→`fiscal_creates`；练兵/募营/调将镇地→`new_armies`+`office_changes`；抄没/缴获/一次性→`economy_moves`；人物升黜→`office_changes`/`character_status_changes`。**判据**：restore 只读 DB 能无损接续=到位；需"我记得"补=漏了。（context 压缩后只剩 DB，挂叙事的后果全丢——探针实测最痛点。）
- **P3 品味护栏 → [docs/ROLE_FIDELITY.md](docs/ROLE_FIDELITY.md)**：国策=旨意的具体后果（建军/人物去向/营建/财政/局势的此刻实体后果），**不是科技树/进度面板**；真护栏=皇帝角色保真 + 冰汽时代式高压求生（破局可真）；长线发展须「diegetic 形态 + 史实合理尺度」两轴过。⚠️ 只写 docs、不进游戏 prompt。全文与理由变更史见专档。
- **P2 军备/城防建模（数据轴，判战永远 LLM 软判，代码只 clamp 不算胜负）**：军队 `firearm_equipment` 0-100（鸟铳，野战+守城）、`cannon_equipment` 随军红夷炮门数 cap 12（野战带不动多）；地区 `city_level` 0-5（静态史实分级，京师5）、`cannon` 城防红夷炮门数 cap=`city_level×8`（城头炮，守城关键）。佛郎机轻炮归 firearm；随军炮利攻、城防炮利守。
- **P4 呈现层：DB 有数，皇帝无表（用户核心原则，2026-06-12 拍）**：玩家（皇帝）**永不见裸数值**——忠诚/能力/家产等一律定性叙事呈现（「军事能力优秀」，不是「98」；家产例外——按 0122 报约数放行：「家赀约数十万两」式奏报口吻合法，0143 沿用）；皇帝透过奏对/行为/传闻读人，不看角色卡。数值照旧活在 DB 供引擎（与 P2 不冲突：P2 管引擎侧建模，P4 管呈现侧翻译）。配套方向（机制未设计，勿擅自展开）：锦衣卫可查家产但不保证准、精度拟挂目标「阴谋」类能力；叙事可留线索（「国丈哭穷」本身就是信息）。落 prompt 时用正向表述（「以奏疏口吻定性描述人物」），不写「不要显示数值」式负向句。
- **P5 LLM 流程并行优先（设计铁律，2026-06-23 用户拍；我反复犯的设计盲点）**：设计任何涉 LLM 调用的流程，**第一考虑「能不能并行 LLM 调用以缩短用户等待」**。单次 LLM 调用就很慢（召对回话 ~15-30s、simulator ~47s+、extractor ~30s、codex 每调用 ~15s 固定开销）= UX 真瓶颈；而**写 DB 多写几次根本无所谓**（毫秒级、免费）。判依赖：某调用的输入=另一调用的输出→必串（如 extractor 读 simulator 邸报，必串）；否则**并行**（召对判断 gate 看玩家消息、不依赖回话→与回话并行、回话后 0 黑；密令抽取从对话上下文取→与回话并行；结算 extractor 多模块无依赖→并行）。**严禁为「省 DB 写次数 / 少建几条记录 / 少加一列」而把本可并行的 LLM 调用串起来 = 拿免费的换最贵的。** streaming 也是缩短**感知**等待的手段（simulator 边算边出填等待）。

## 关键技术事实（已挖过，省得重来）
- **启动脱 key**：`GameSession(..., verify_llm=False)` 跳过 LLM 连通校验（`session.py:374`），CLI 无 api key 能起。
- **delta 落库单一入口**：`db.apply_score_extraction(db, state, extracted, content, registry)`，内部分发到 region/army/building/economy/issue 各 apply。我产符合 schema 的 delta 即可，driver 不用自己写落库。
- **schema 契约**：全在 `simulation.py`（`TOP_LEVEL_ALIASES`/`ITEM_FIELD_ALIASES`/`EMPTY_EXTRACTION`/`MODULE_FIELDS`/`_clean_*`/`_sanitize_module_output`/`_merge_module_outputs`）。这是我产 delta 的**格式契约 + 落库守门**，零 agno 依赖，必须保留。
- **接口层（确定性↔LLM，别让 LLM 自己数数）**：`memories.effect_brief`（delta→「国库+30、了结局势X」）、`memories.build_timeline`、`agents.build_simulator_context`（盘面→TSV）。喂给我的盘面快照 / 效果摘要由它们生成。
- **结算编排骨架**：`decree.py` 的月末主链——颁诏/退朝遇开夜先顺势自动收夜（`auto_close_open_night`，#498，见 `ming_sim/audience_night.py`，在飞回话 fail-closed）→ 固定财政 tick → `auto_trigger_seed_issues`（**必须在邸报前**）→ [我产邸报] → `parse_decision_blocks` → [我产 delta] → `apply_score_extraction` → 章节记忆（**必须在结局判定前**）→ `apply_issue_inertia_and_ongoing`(touched_ids) → `clear_gated_legacies` → 结局三级判定（叙事→数值→到期 turn≥240）→ `next_period` → `assert turn==before_turn+1`。**driver 不复刻此链，而是复用从 `decree.py` 抽出的 `pre_settle` + `settle_with_delta`（与真实流程同核，见 `docs/adr/0004-probe-driver-reuses-engine-settle-core.md`）**，别破不变式。**事务边界（v0.8.0.0，ADR 0008 PR1）**：`pre_settle` 自带事务、提交后保持已落（设计明文）；后半段整段 `applier.atomic` 全有或全无；delta 在 settle 前持久化为 ready=1 重试真源（崩溃断点续跑不重跑 LLM）；shape 垃圾 → SettlementAbort+错误包响亮中止；退朝不能跳过已开始的结算。细节查 `docs/SETTLEMENT_FLOW.md`。
- **运行形态（web 第一，CLI 沉浸版后续）**：**目前 web 版本是第一个尝试方向**，走真实 LLM 后端（codex / agy / hermes，见下）。**「agent session 直接当后端」属后续的 CLI 文字沉浸版**——session 串行（一次一个 LLM 调用）使它在 web 月末并发轰多个 extractor 时会死锁，故那条路留给 CLI 沉浸版、不用在 web。⚠️ 别再凭「探针走 CLI」判 web 路 bug「够不着玩家」：web 是当前真实运行形态，web 路的问题就是真问题。
- **6 文件三向处置**（agents/simulation/registry/decree/memories/llm_model）：🟢 保留契约/骨架 🟡 提炼成我的玩法说明书 🔴 扔纯 agno 管道（`llm_model.py` 整扔）。**领域金矿本体在 `content/prompts/*.md`（13 个，尤其 `season_simulator.md` 16K 字裁判规则 + 4 个 `score_extractor`）**。

## LLM 后端（换模型时查，非每回合）
hermes proxy 当 OpenAI 兼容后端：`hermes proxy start --provider nous|xai`，base_url `http://127.0.0.1:8645/v1`（`nous` 按量、`xai` SuperGrok 免费但中文叙事弱）。
- **工程坑（换 codex/claude 前必改）**：codex 必须 `--skip-git-repo-check` + 并发 `--ephemeral`，干净输出在 stdout（日志在 stderr）；claude 用 `MAX_THINKING_TOKENS`（~10k≈medium）代 gpt 的 reasoning_effort，`claude -p` 默认重思考会拖慢。
- **真 baseline = Opus 4.8 在 session 里当 LLM（形态1）**：`probe.db` 现存 14 条国策（id 4-18）是它建的，非 agy。
- 各后端**质量/速度选型对比 + 方法学免责**（建 issue / 叙事 / 速度档 / 淘汰交互）→ 全文见 **[docs/LLM_BACKEND_BENCH.md](docs/LLM_BACKEND_BENCH.md)**。

## 金手指改动（本地实验，非上游原版）
`content/buildings.json` 末尾加了 3 个建筑：皇家天佑金矿（国库 +800/月）、大明中央银行（内库 +300）、帝国航空（皇威 +10）。原理：建筑走真实月度流水，LLM 查账本认账；直接改国库余额会被大臣审计成「虚存」。**只对新开存档生效**（老档建筑已写进 DB）。

## 开发流程（想法 → merge，2026-06-17 定，本项目试行）

> **完整流程文档（Matt Pocock 整套，严格按 Matt 试水）→ [docs/DEV_WORKFLOW.md](docs/DEV_WORKFLOW.md)**（canonical 顺序 / decision-mapping 大目标推雾 / to-spec 两层设计 / 设计六层阶梯 / triage 入口匝道 / 全 skill 速查 / 追踪模型 / 切片并行全在那）。
> **标签 Matt 纯化（2026-06-17）**：全仓删掉 `priority/*` `area/*` `type/*` 那套，**只剩 7 个** —— `bug`/`enhancement`（category）+ `needs-triage`/`needs-info`/`ready-for-agent`/`ready-for-human`/`wontfix`（state）。

**贯穿原则**：持久件做小做单一（一条 ADR 一个不可逆决策、一个 issue 一个切片）；**设计分层落（六层阶梯见 DEV_WORKFLOW.md）**——不可逆决策→ADR、架构级（模块/接口/契约/schema）→`to-spec` 的 Implementation Decisions、**只有代码级实现（真函数/文件结构）才留 `/tdd` 现场长**（「最后责任时刻」：可逆→写码时长；设计时「忽然难受」=越线信号）。⚠️ 别把「详设留 TDD 长」误读成「to-spec 之后到代码之间无设计」——架构级早在 `to-spec` 钉了。跨 session 靠文档 + 你本人 re-seed，**handoff ≠ 交接**（同一个你驱动）；session 边界画在「上下文满/脏」处、不钉死在某步，小功能可一个 session 连做。

**流水线 + skill（Matt canonical 顺序；标〔项目加〕的是 Matt 之外本项目的闸）**。⚠️ 2026-07-14 上游改名：`to-prd`→`to-spec`（纯改名，产物即 PRD）、`to-issues`→`to-tickets`（改名 + 内建原生挂接）；旧名已失效，历史 ADR/log 里的旧名不回改：
1. 想法 → **`grill-with-docs`**（有 codebase）/ `grill-me`（无）→ 逼问（核心引擎 `/grilling`），决策结晶**当场**写 **tiny 单决策 ADR** + `CONTEXT.md` 词表。**逼问那一步在这、不在 to-spec；止于不可逆决策。** 大/模糊、一次 session 定不完的，先 **`decision-mapping`** 建决策图逐票推雾、路清再往下。
2. （可选）`prototype` 去风险（状态/UI 开放问题）——`handoff` 出/回桥接（原型在独立 session 跑），答案落 ADR/issue/NOTES、原型删。
3. **`to-spec`**（旧名 to-prd，产物即 PRD）→ **完整 PRD**（不访谈，只综合 grill 的结论）：详尽 user stories + **Implementation Decisions + Testing Decisions（两层设计）** + Out of Scope；发 issue tracker 当父/epic、贴 `ready-for-agent`（父票贴标无所谓，不参与步骤 5 的设计评审状态判断）。**禁文件路径/代码片段。**
4. **`to-tickets`**（旧名 to-issues，2026-07-14 上游改名）切 thin vertical-slice 子 issue（带 Parent + 验收 + HITL/AFK + blocked-by）。**新版已内建**①子挂父 native sub-issue ②子↔子 native blocked_by（skill 原文「Use the platform's native blocking / sub-issue relationship」）。它默认自动贴 `ready-for-agent`——**贴着无所谓、不用管**（owner 2026-07-14 简化：评审态真源 = ADR Status，Accepted 前=这波未过审，票上贴什么标都不作准；撤父标/闸前 hold 仪式一并废止）。核验/手补命令见 [DEV_WORKFLOW.md](docs/DEV_WORKFLOW.md)。
5. 〔项目加〕设计评审（**在 to-tickets 之后**——cmr 审含切片布线的设计全家；#470/#471/#478 实践序，2026-07-03 修订原 4/5 对调）：`ak-cross-m-review`（本地 cmr）+ 线上 bot → 合 ADR、Status→Accepted。**评审态真源 = ADR Status**（owner 2026-07-14 简化）：Accepted 前=未过审，无论票上贴什么标；不搞撤标/贴回仪式。〈设计侧到此结束〉
6. **逐切片各开新 session `implement`**（canonical 构建步）：约定 seam 调 `/tdd`（never refactor while RED）→ 切片轮次跑 typecheck+聚焦测试（全量 suite 只在家族/批次收尾跑一次作 merge 前门槛，政策真源见 [`docs/DEV_WORKFLOW.md` §测试分级](docs/DEV_WORKFLOW.md)）；**代码级实现现场长**（架构级早在 to-spec 钉了）。手动/单 session 流随后建 baseline commit；硬 bug → `diagnosing-bugs`、架构清理 → `improve-codebase-architecture`。自动化角色接力由仓外 v3 `ak-pi-workflow-roles` 维护，本仓不复制其流程或配置。
7. 〔项目加〕baseline commit 后代码评审：手动/单 session 场景单评用 `/code-review`（Standards + Spec 两轴；它评 `fixed-point...HEAD`，所以必须已有 commit），然后 per-slice `ak-cross-m-review` + ship-pre 双闸 + 线上 bot；`gstack-ship` 收尾。评审修复一律追加新 commit，禁止 amend。自动化交付使用仓外 v3 的独立角色，具体接力以其项目真源为准。
8. merge commit（不 squash）→ 关子 issue；全完 → 关父 issue。

> **分叉**：步骤 3→4（`to-spec`→`to-tickets`）只在「多 session 大活」才走；**单 session 能完的小活直接在同一窗口 implement、跳过 3-5（含步骤 5 设计评审闸——小活无设计文档，不涉）**。步骤 1→3→4 留**同一不间断上下文窗口**（别中途 compact）；每个子 issue **开新 session** 做 6。`triage` 不在这条主线上——它是**入口匝道**，只处理你没创建的外来 issue；`to-tickets` 的产出规格即 agent-ready、不再 triage（标签贴着无所谓——评审态真源 = ADR Status，见步骤 5）。

**两层分工（2026-06-16 定）**：策划+架构 session 出 ADR，开发 session 读 ADR 做（同一 agent 可兼策划/架构两角，但当下分清在哪层、别拿字段/schema/现有代码卡玩法设计）。
**文档三层（采 Matt Pocock grill-with-docs DDD）**：① `CONTEXT.md`=领域词表（是什么、零实现）；② `docs/adr/`=非显然决策的为什么（**ADR-FORMAT：1-3 句、单决策、稀有**，hard-to-reverse / surprising / real-tradeoff 才建，不是 spec；大模板会把可逆细节吸进来＝过度设计，避开）；③ 详设/代码任务 → issue；④ 实现 → 代码。给 AI 最薄一层。
**评审强度跟反悔成本走**：设计审狠（反悔贵）、代码审正确性。
**真 user story（2026-06-18 立，实证栽过）**：user story 必须**从真实用户的需求**写——「谁真在用这东西、要达成什么价值」，不是把 Implementation Decision 套成「作为 X，我希望〔那条决定〕」凑数。**actor = 被造之物的真实用户**：游戏 → 皇帝/玩家（+ 试玩者/我：抓 bug、要错误包、读拒收数据找规律）；**开发者只在「开发者本就是产品真实用户」时才当 actor**（dev 工具/SDK——实证 Matt 的 `sandcastle` PRD 全「As a developer」、`course-video-manager` PRD 全「As a course creator」，actor 跟产品真实用户走）。**判据**：剥掉「作为 X 我希望…以便…」的壳，剩的是「用户可感知的价值」还是「内部怎么实现」？后者＝假 story，挪 Implementation Decisions。别为凑「extensive」机械批量造、被质疑再事后补说辞——extensive 是把真实用户各面写全，非换壳堆量。
**学框架学精神、非照搬（2026-06-18 立）**：跑流程框架（如严格按 Matt 试水）是学它的**精神/原理**（为何这么设计、解决什么真问题），不是邯郸学步照搬条文；最终大概率**魔改成适合本项目的形态**。照搬到「不合理/难受」处先问「这条原理在解决什么、我这场景还成立吗」——成立就守，不成立就改 + 记下为什么，别因「Matt 这么写」就硬套。

## 规则

- **金手指例外**：`content/buildings.json` 金手指为常驻例外（见上文「金手指改动」节）。
- 全局 agent 纪律（授权词 / 中文输出 / 先开分支 / 评审轮禁 amend / 设计文档同评 / merge 不 squash / PR 平台前缀）见 owner 全局 `~/.claude/CLAUDE.md` / `~/.codex/AGENTS.md`，本文件不重复。
- ship-pre DoD 全闭环点检见 [`docs/DEV_WORKFLOW.md`](docs/DEV_WORKFLOW.md)（#911 从本文件迁出）。

## Skill routing

> 自动化开发角色、接力和运行时由仓外 v3 [`ak-pi-workflow-roles`](https://github.com/Akagilnc/ak-pi-workflow-roles) 维护；本仓只保留游戏开发需要的 skill routing，不维护 Runner、Flow、角色镜像或模型路线。
> Routing is by the task at hand, not by ceremony.

When you are an agent assigned a single slice issue in this worktree, route by what the task is:

- **Implement a slice / build a feature / fix a bug test-first** → invoke the `tdd` skill (Claude: `Skill` tool with skill `tdd`; Codex: load `~/.claude/skills/tdd/SKILL.md` and follow it as the active skill), drive red → green → refactor, then run **typecheck + focused tests** for the slice round. Full suite runs **once** at family/batch close as the pre-merge gate — not per slice (policy source: [`docs/DEV_WORKFLOW.md` §测试分级](docs/DEV_WORKFLOW.md), #1185). Manual/single-session implement may then create its baseline commit before `/code-review` because that skill reviews `fixed-point...HEAD`, not uncommitted changes. Automated coder/reviewer separation is owned by the external v3 package.
- **A hard bug / something throwing / failing / slow that needs root-cause diagnosis before a fix** → invoke the `diagnosing-bugs` skill first to find root cause, then return to `tdd` to fix it test-first. `diagnosing-bugs` internally hands off to `improve-codebase-architecture` when the root cause is an architectural seam problem — that skill is present alongside (2b).
- **Designing or improving a module's interface / deciding where a seam goes / making code more testable** → invoke the `codebase-design` skill for the deep-module vocabulary; for a larger architectural cleanup invoke `improve-codebase-architecture` (which itself calls `codebase-design`).
- **Slice-end review of the diff** → manual/single-session flow runs `/code-review`, then the project CMR and ship gates described above. Automated review/fix roles and their handoff are external v3 concerns, not contracts maintained in this repository.
- **Resolving an in-progress git merge/rebase conflict** → invoke the `resolving-merge-conflicts` skill and preserve BOTH sides' behaviour.

Do NOT hand-write the methodology in your reasoning — invoke the skill so the discipline comes from the versioned skill, not from improvisation. Stay strictly inside the slice's scope; if the slice cannot be implemented as specified (real design gap, missing dependency, spec contradiction), do not guess — escalate per your worker output contract.

## Agent skills

### Issue tracker

GitHub Issues（`Akagilnc/ming-salvage-sim`，已设为本 clone 的 gh 默认仓库（`gh repo set-default`），`--repo` 可省；跨 clone / CI / 重设 remote 后仍建议显式带 `--repo` 防误打 upstream）。See `docs/agents/issue-tracker.md`.

### Triage labels

**Matt 纯化（2026-06-17）**：全仓只剩 7 个标签——`bug` / `enhancement`（category）+ 五态 `needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`（state）。旧 `priority/area/type` 已删。See `docs/agents/triage-labels.md` + `docs/DEV_WORKFLOW.md`.

### Domain docs

单语境：根目录 `CONTEXT.md` + `docs/adr/`。See `docs/agents/domain.md`.
