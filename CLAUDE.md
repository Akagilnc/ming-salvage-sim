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

**总纲（宪法级，2026-08-18 owner 拍；一切立法/票面/判词不得绕开，抵触即违宪）**：引擎存在的唯一理由是 LLM 记忆有限——**引擎=物理事实账本**，负责记录、记住、提供世界的物理事实，是唯一不会忘的东西（P1 因此是第一铁律），但引擎不是游戏本体。**物理事实和人（皇帝、大臣）能看见的没有任何强制关联**：奏报可载假象、账面可虚存、国库数字可以是假的（看着有花不出不稀奇）——真相只活在账本，呈现层是「人在说话」，而人会骗人。

- **P1 决策当回合全量落库（第一铁律）**：凡下旨，机械后果**必须当回合全量落进 DB**，不许只活在邸报——带经费/俸/饷→`fiscal_creates`；练兵/募营/调将镇地→`new_armies`+`office_changes`；抄没/缴获/一次性→`economy_moves`；人物升黜→`office_changes`/`character_status_changes`。**判据**：restore 只读 DB 能无损接续=到位；需"我记得"补=漏了。（context 压缩后只剩 DB，挂叙事的后果全丢——探针实测最痛点。）
- **P3 品味护栏 → [docs/ROLE_FIDELITY.md](docs/ROLE_FIDELITY.md)**：国策=旨意的具体后果（建军/人物去向/营建/财政/局势的此刻实体后果），**不是科技树/进度面板**；真护栏=皇帝角色保真 + 冰汽时代式高压求生（破局可真）；长线发展须「diegetic 形态 + 史实合理尺度」两轴过。⚠️ 只写 docs、不进游戏 prompt。全文与理由变更史见专档。
- **P2 军备/城防建模（数据轴，判战永远 LLM 软判，代码只 clamp 不算胜负）**：军队 `firearm_equipment` 0-100（鸟铳，野战+守城）、`cannon_equipment` 随军红夷炮门数 cap 12（野战带不动多）；地区 `city_level` 0-5（静态史实分级，京师5）、`cannon` 城防红夷炮门数 cap=`city_level×8`（城头炮，守城关键）。佛郎机轻炮归 firearm；随军炮利攻、城防炮利守。
- **P4 呈现层：DB 有数，皇帝无表（用户核心原则，2026-06-12 拍）**：玩家（皇帝）**永不见裸数值**——忠诚/能力/家产等一律定性叙事呈现（「军事能力优秀」，不是「98」；家产例外——按 0122 报约数放行：「家赀约数十万两」式奏报口吻合法，0143 沿用）；皇帝透过奏对/行为/传闻读人，不看角色卡。数值照旧活在 DB 供引擎（与 P2 不冲突：P2 管引擎侧建模，P4 管呈现侧翻译）。配套方向（机制未设计，勿擅自展开）：锦衣卫可查家产但不保证准、精度拟挂目标「阴谋」类能力；叙事可留线索（「国丈哭穷」本身就是信息）。落 prompt 时用正向表述（「以奏疏口吻定性描述人物」），不写「不要显示数值」式负向句。
- **P5 LLM 流程并行优先（设计铁律，2026-06-23 用户拍；我反复犯的设计盲点）**：设计任何涉 LLM 调用的流程，**第一考虑「能不能并行 LLM 调用以缩短用户等待」**。单次 LLM 调用就很慢（召对回话 ~15-30s、simulator ~47s+、extractor ~30s、codex 每调用 ~15s 固定开销）= UX 真瓶颈；而**写 DB 多写几次根本无所谓**（毫秒级、免费）。判依赖：某调用的输入=另一调用的输出→必串（如 extractor 读 simulator 邸报，必串）；否则**并行**（召对判断 gate 看玩家消息、不依赖回话→与回话并行、回话后 0 黑；密令抽取从对话上下文取→与回话并行；结算 extractor 多模块无依赖→并行）。**严禁为「省 DB 写次数 / 少建几条记录 / 少加一列」而把本可并行的 LLM 调用串起来 = 拿免费的换最贵的。** streaming 也是缩短**感知**等待的手段（simulator 边算边出填等待）。
- **P6 判断权归 LLM（2026-08-18 拍）**：凡角色的决定（要不要弹劾、怎么措辞、判胜负），LLM 按人物/局势自己发挥；代码只做三件事：供事实、clamp、记账。烈度公式/quota/概率门这类「代码替角色做决定」的形状违宪。P2「判战 LLM 软判」是本条个案。「没人能预计，但要查又能查」=机制本身：不可预计因为真生成，可查因为产出指向真实账本事实。
- **P7 任何文字模板=违宪（2026-08-18 拍）**：玩家可感文本一律由 LLM 从特征化输入长出（0035 语）；固定句式/占位符拼装/单句模板不问理由判死。LLM 游戏与普通文本游戏的全部区别=玩家几句话摸不到模板的底。「同一话术呈皇帝」=大臣会骗人（真伪同以可信口吻呈上），非字符串相等。呈现准绳=docs/AUDIENCE_NORTH_STAR.md。

- **P6 LLM 输出不可篡改（owner 2026-08-20 逐字拍；违者=违宪）**：「llm 想怎么写就怎么写。写出来什么就是什么。别在那去扣文字、改词。有些东西不想 AI 说，**要从它能看见的东西入手，而不是去篡改它的输出**。」——引擎/呈现层对 LLM 产出的自由文本**零删改**（禁 regex/词表/裁剪/替换，ADR 0142）；要改效果只有两条合法路：改**输入**（prompt 正向表述、喂的材料，ADR 0143）或改**呈现结构**（UI 布局，不碰字）。判官核任何触 LLM 输出显示的处方先问一句「这是在改它写的字吗？」——是即驳回。实证：#1473 曾有判官处方开 regex 剥「叩答」前缀、fixer 已落词表，r6 庭依 0142 拦于 merge 前（2026-08-20）。

## 关键技术事实（已挖过，省得重来）
- **启动脱 key**：`GameSession` 构造即不连 LLM（连通校验只在设置页主动提交配置时跑），CLI 无 api key 能起。
- **delta 落库单一入口**：`db.apply_score_extraction(db, state, extracted, content, registry)`，内部分发到 region/army/building/economy/issue 各 apply。我产符合 schema 的 delta 即可，driver 不用自己写落库。
- **schema 契约**：全在 `simulation.py`（`TOP_LEVEL_ALIASES`/`ITEM_FIELD_ALIASES`/`EMPTY_EXTRACTION`/`MODULE_FIELDS`/`_clean_*`/`_sanitize_module_output`/`_merge_module_outputs`）。这是我产 delta 的**格式契约 + 落库守门**，零 agno 依赖，必须保留。
- **接口层（确定性↔LLM，别让 LLM 自己数数）**：`memories.effect_brief`（delta→「国库+30、了结局势X」）、`memories.build_timeline`、`agents.build_simulator_context`（盘面→TSV）。喂给我的盘面快照 / 效果摘要由它们生成。
- **结算编排骨架**：`decree.py` 的月末主链——颁诏/退朝遇开夜先顺势自动收夜（`auto_close_open_night`，#498，见 `ming_sim/audience_night.py`，在飞/待补回话并入收夜流程处理完再结算，玩家无感；仅统一重试耗尽才走失败单源）→ 固定财政 tick → `auto_trigger_seed_issues`（**必须在邸报前**）→ [我产邸报] → `parse_decision_blocks` → [我产 delta] → `apply_score_extraction` → 章节记忆（**必须在结局判定前**）→ `apply_issue_inertia_and_ongoing`(touched_ids) → `clear_gated_legacies` → 结局三级判定（叙事→数值→到期 turn≥240）→ `next_period` → `assert turn==before_turn+1`。**driver 不复刻此链，而是复用从 `decree.py` 抽出的 `pre_settle` + `settle_with_delta`（与真实流程同核，见 `docs/adr/0004-probe-driver-reuses-engine-settle-core.md`）**，别破不变式。**事务边界（v0.8.0.0，ADR 0008 PR1）**：`pre_settle` 自带事务、提交后保持已落（设计明文）；后半段整段 `applier.atomic` 全有或全无；delta 在 settle 前持久化为 ready=1 重试真源（崩溃断点续跑不重跑 LLM）；shape 垃圾 → SettlementAbort+错误包响亮中止；退朝不能跳过已开始的结算。细节查 `docs/SETTLEMENT_FLOW.md`。
- **运行形态（web 第一，CLI 沉浸版后续）**：**目前 web 版本是第一个尝试方向**，走真实 LLM 后端（codex / agy / hermes，见下）。**「agent session 直接当后端」属后续的 CLI 文字沉浸版**——session 串行（一次一个 LLM 调用）使它在 web 月末并发轰多个 extractor 时会死锁，故那条路留给 CLI 沉浸版、不用在 web。⚠️ 别再凭「探针走 CLI」判 web 路 bug「够不着玩家」：web 是当前真实运行形态，web 路的问题就是真问题。
- **6 文件三向处置**（agents/simulation/registry/decree/memories/llm_model）：🟢 保留契约/骨架 🟡 提炼成我的玩法说明书 🔴 扔纯 agno 管道（`llm_model.py` 整扔）。**领域金矿本体在 `content/prompts/*.md`（13 个，尤其 `season_simulator.md` 16K 字裁判规则 + 4 个 `score_extractor`）**。

## LLM 后端（换模型时查，非每回合）
hermes proxy 当 OpenAI 兼容后端：`hermes proxy start --provider nous|xai`，base_url `http://127.0.0.1:8645/v1`（`nous` 按量、`xai` SuperGrok 免费但中文叙事弱）。
- **工程坑（换 codex/claude 前必改）**：codex 必须 `--skip-git-repo-check` + 并发 `--ephemeral`，干净输出在 stdout（日志在 stderr）；claude 用 `MAX_THINKING_TOKENS`（~10k≈medium）代 gpt 的 reasoning_effort，`claude -p` 默认重思考会拖慢。
- **真 baseline = Opus 4.8 在 session 里当 LLM（形态1）**：`probe.db` 现存 14 条国策（id 4-18）是它建的，非 agy。
- 各后端**质量/速度选型对比 + 方法学免责**（建 issue / 叙事 / 速度档 / 淘汰交互）→ 全文见 **[docs/LLM_BACKEND_BENCH.md](docs/LLM_BACKEND_BENCH.md)**。

## 金手指改动（本地实验，非上游原版）
`content/buildings.json` 末尾加了 3 个建筑：皇家天佑金矿（国库 +800/月）、大明中央银行（内库 +300）、帝国航空（皇威 +10）。原理：建筑走真实月度流水，LLM 查账本认账；直接改国库余额会被大臣审计成「虚存」。**只对新开存档生效**（老档建筑已写进 DB）。

## 规则

- **本仓分支特例**（全局 #6 的本仓部分）：任何代码工作先开分支；**纯叙事文档可直改 main**；常驻例外 = `content/buildings.json` 金手指（见上文「金手指改动」节）。
- **`probe/tianmu-fiscal` 孤本分支勿删**（#72 squash 后 22 轮评审迭代史只活在该分支）。
- 测试分级见本文件「## 测试分级」。

## 测试分级（#1185，owner 2026-08-13 裁定）

**本仓测试分级政策真源**：

- **切片轮次** 推荐逐片 implement / fixer 聚焦测试；不以复跑全量 suite 为必须复核手段。
- **聚焦测试** 本片触及的测试。
- **家族/批次收尾**＝在**最终待合并状态**执行一次全量 suite。
- **CI**（`.github/workflows/ci.yml`）覆盖 **Python 全量 pytest + Web 构建/类型检查**（`tsc` + vite build），**不含 Web vitest**；本政策如实描述既有覆盖面，不改 CI 机制、不把 vitest 加进 CI。

正向口径：切片只跑聚焦；全量在最终待合并状态跑到绿（失败/修复后重跑）。同构于仓外 `ak-pi-workflow-roles` 司天家族测试策略（该仓 #215 provenance）；worker prompt / reviewer 验收面属外部编排器仓，由其维护，本仓不改。

## ship-pre DoD 全闭环点检（#911 自项目 CLAUDE.md 迁出 → DEV_WORKFLOW；PR #1193 迁回）

进 ship-pre / CMR 评审循环前必须确认 feature 全闭环完成，不是「核心写路径接通」就进。Definition of Done = 所有闭环面都齐——**写入端 + 读取端 + 恢复端 + 真实 extractor 输出 + UI/呈现端 + 文档契约**，缺一面都不算 ship-ready。

把「核心写路径接通 + 单元测试绿 + 前几轮 CMR 收敛」误当成「全闭环完成」两头亏：(1) 在不完整目标上启动昂贵的 ship-pre 评审循环，(2) CMR 一轮轮真抓闭环缺口、滚到离谱轮数才被外人判出「功能不足」。

**判据**：进 ship-pre 前对着 plan 逐面点检 DoD，任一面（尤其读取/恢复/呈现这些最容易被「写路径接了」盖过的隐性面）未落 = 早了，先补完再进。这是 **ship-gate / DoD 判断**，不是编码能力——写路径接了、测试绿都可能为真，错在把「核心接通」当「全闭环完成」。

且即便 DoD 齐、进了 ship-pre，装起来跑的整体 cmr 仍是独立一道闸——别当走过场：per-slice cmr 各自全绿 ≠ feature 完成，整体闸基本仍会抓出 per-slice 照不到的**跨片接缝**（字段名/类型对不对、字段口径一不一致、组合后才出现的 e2e 行为），要预期它有料、按真闸认真跑。

## Agent skills

### Issue tracker

GitHub Issues（`Akagilnc/ming-salvage-sim`，已设为本 clone 的 gh 默认仓库（`gh repo set-default`），`--repo` 可省；跨 clone / CI / 重设 remote 后仍建议显式带 `--repo` 防误打 upstream）。See `docs/agents/issue-tracker.md`.

**发票纪律（2026-08-29 owner 拍）**：父子与依赖关系一律用 GitHub 原生 sub_issues / blocked_by。

### Triage labels

**Matt 纯化（2026-06-17）**：全仓只剩 7 个标签——`bug` / `enhancement`（category）+ 五态 `needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`（state）。旧 `priority/area/type` 已删。See `docs/agents/triage-labels.md`.

### Domain docs

单语境：根目录 `CONTEXT.md` + `docs/adr/`。设计判据（真 user story / 文档三层+ADR 颗粒度 / Accepted≠已实现 / 评审强度跟反悔成本）与用法见 `docs/agents/domain.md`。
