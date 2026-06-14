# Ming_LLM — 项目 CLAUDE.md

## 这是什么
`wangwei-ying3/ming-salvage-sim` 的 fork（GPLv3）。明末崇祯 LLM 政略模拟器。
本仓库目的 = 做一个**探针**：把游戏的 LLM 后端从「外部 api key 调商业模型」换成「agent session 直接当 LLM」（当前对话的 Claude / 或 subagent），纯文字 CLI，验证「在 session 里玩」好不好玩。

## 📚 工作手册（每回合开始前必查，别凭"我以为"）
- **[docs/DELTA_SCHEMA.md](docs/DELTA_SCHEMA.md)** — 我产 delta JSON 的格式契约：23 个顶层字段、字段约束、白名单、踩过的坑。**产 delta 前查。**
- **[docs/SETTLEMENT_FLOW.md](docs/SETTLEMENT_FLOW.md)** — 月末结算管线：driver 调引擎的完整顺序 + 不变式 + 接口层。**写 driver / 结算时查。**
- **[TODOS.md](TODOS.md)** — 待修 bug + 探针工程待办。**每回合结算前扫一眼有无"本月要顺手修"的项**（当前：B1 阉党 leverage 不联动）。
- **[docs/FISCAL_PROVINCE_SUBSTRATE.md](docs/FISCAL_PROVINCE_SUBSTRATE.md)** — 省级财政基座设计（三饷/火耗/起运存留/宗禄/逋赋/隐田），**22 轮跨模型评审已收敛，现 v23（2026-06-10 拍板补「三饷计火耗」：火耗应派=(正赋+三饷)×火耗率）**；可执行 spike `spike_settle_tick.py`（G1–G22 全 PASS，5 层断言+独立 oracle，~20 mutation 自验全咬）。**状态：设计已验证、尚未 port**（等重构完成后接进 `ming_sim`，见 [Milestone #1](https://github.com/Akagilnc/ming-salvage-sim/milestone/1) / Epic #65 / 子任务 #66–#71）。**非每回合必查；要动省级财政机制时查。**

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
- **P3 国策=「当下旨意的具体后果」，不是玩家点的进度树/科技树面板（品味护栏）**：真护栏=**皇帝角色保真**——这是模拟皇帝的模拟器，皇帝面前不该有能点的科技树/进度面板（同根=不亲手换兵种、P4 皇帝无表、actor 博弈>资源按钮）。**feel 非钦定悲剧**，是《冰汽时代1》式高压绝境求生 + 硬取舍 + **破局可真**（「越努力越难、但出路恒在」）。**长线发展/科技不是禁区，但「合理」须两轴都过**：①**形态**——经旨意/召对/奏报 diegetic（世界观叙事内）涌现（徐光启奏对「能从澳门葡人搞红夷炮练兵」=✅），不是大臣嘴里冒「先点 A 解锁 B」（面板话术=❌）；②**尺度**——史实合理范围一点点（红夷炮/燧发枪 ✅；蒸汽机/化肥/火车/飞机 跨几百年文明阶梯=❌越界）。**禁的是面板形态 + 越界尺度，不是发展/出路本身**。判据=「皇帝会不会坐这面板前点它」，不是「它给不给出路」（出路本就该有）。类型定位=微硬核模拟器（尺度预算低）；自由奔放版（放宽魔幻度、容科技树造飞机）=后面的事、另一个 mode。国策落点=建军/人物去向/营建/财政/局势这些**此刻实体后果**。⚠️ **这条只写 docs，绝不写进游戏 prompt**（meta 设计话不进游戏内容；曾误写进 season_simulator.md 已删）。（理由变更历史：原作「拒绝科技树…稀释悲剧」，2026-06-14 用户纠为「皇帝角色保真」——拒的是面板形态非发展本身、feel 非必悲剧。）
- **P2 军备/城防建模（数据轴，判战永远 LLM 软判，代码只 clamp 不算胜负）**：军队 `firearm_equipment` 0-100（鸟铳，野战+守城）、`cannon_equipment` 随军红夷炮门数 cap 12（野战带不动多）；地区 `city_level` 0-5（静态史实分级，京师5）、`cannon` 城防红夷炮门数 cap=`city_level×8`（城头炮，守城关键）。佛郎机轻炮归 firearm；随军炮利攻、城防炮利守。
- **P4 呈现层：DB 有数，皇帝无表（用户核心原则，2026-06-12 拍）**：玩家（皇帝）**永不见裸数值**——忠诚/能力/家产等一律定性叙事呈现（「军事能力优秀」，不是「98」）；皇帝透过奏对/行为/传闻读人，不看角色卡。数值照旧活在 DB 供引擎（与 P2 不冲突：P2 管引擎侧建模，P4 管呈现侧翻译）。配套方向（机制未设计，勿擅自展开）：锦衣卫可查家产但不保证准、精度拟挂目标「阴谋」类能力；叙事可留线索（「国丈哭穷」本身就是信息）。落 prompt 时用正向表述（「以奏疏口吻定性描述人物」），不写「不要显示数值」式负向句。

## 关键技术事实（已挖过，省得重来）
- **启动脱 key**：`GameSession(..., verify_llm=False)` 跳过 LLM 连通校验（`session.py:374`），CLI 无 api key 能起。
- **delta 落库单一入口**：`db.apply_score_extraction(db, state, extracted, content, registry)`，内部分发到 region/army/building/economy/issue 各 apply。我产符合 schema 的 delta 即可，driver 不用自己写落库。
- **schema 契约**：全在 `simulation.py`（`TOP_LEVEL_ALIASES`/`ITEM_FIELD_ALIASES`/`EMPTY_EXTRACTION`/`MODULE_FIELDS`/`_clean_*`/`_sanitize_module_output`/`_merge_module_outputs`）。这是我产 delta 的**格式契约 + 落库守门**，零 agno 依赖，必须保留。
- **接口层（确定性↔LLM，别让 LLM 自己数数）**：`memories.effect_brief`（delta→「国库+30、了结局势X」）、`memories.build_timeline`、`agents.build_simulator_context`（盘面→TSV）。喂给我的盘面快照 / 效果摘要由它们生成。
- **结算编排骨架**：`decree.py` 的月末主链——固定财政 tick → `auto_trigger_seed_issues`（**必须在邸报前**）→ [我产邸报] → `parse_decision_blocks` → [我产 delta] → `apply_score_extraction` → 章节记忆（**必须在结局判定前**）→ `apply_issue_inertia_and_ongoing`(touched_ids) → `clear_gated_legacies` → 结局三级判定（叙事→数值→到期 turn≥240）→ `next_period` → `assert turn==before_turn+1`。**driver 不复刻此链，而是复用从 `decree.py` 抽出的 `pre_settle` + `settle_with_delta`（与真实流程同核，见 `docs/adr/0004-probe-driver-reuses-engine-settle-core.md`）**，别破不变式。**事务边界（v0.8.0.0，ADR 0008 PR1）**：`pre_settle` 自带事务、提交后保持已落（设计明文）；后半段整段 `applier.atomic` 全有或全无；delta 在 settle 前持久化为 ready=1 重试真源（崩溃断点续跑不重跑 LLM）；shape 垃圾 → SettlementAbort+错误包响亮中止；退朝不能跳过已开始的结算。细节查 `docs/SETTLEMENT_FLOW.md`。
- **CLI 串行性**让「session 当后端」可行（一次一个 LLM 调用）；web 月末并发轰多个 extractor 会死锁。所以探针走 CLI 不走 web。
- **6 文件三向处置**（agents/simulation/registry/decree/memories/llm_model）：🟢 保留契约/骨架 🟡 提炼成我的玩法说明书 🔴 扔纯 agno 管道（`llm_model.py` 整扔）。**领域金矿本体在 `content/prompts/*.md`（13 个，尤其 `season_simulator.md` 16K 字裁判规则 + 4 个 `score_extractor`）**。

## LLM 后端（对照 / 将来换模型用）
hermes proxy 当 OpenAI 兼容后端：`hermes proxy start --provider nous|xai`，base_url `http://127.0.0.1:8645/v1`，key 随便填。
- `nous`：267 模型按量（`deepseek-v4-flash` 最便宜、`anthropic/claude-sonnet-4.6`/`openai/gpt-5.4` 质量高）。
- `xai`：SuperGrok 订阅免费，但 grok 中文叙事弱、不适合本游戏。

## 后端基准结论（2026-06-07，全文+证据见 `docs/LLM_BACKEND_BENCH.md`，暂存于此待迁专档）
- **建 issue（结构化落库）**：codex 系（5.5/mini/spark）稳，spark 最快；**agy 偶发漏 `origin_kind` 被落库拒**（把 `decree` 错填进 `可撤销`、漏 `来源类型`，见 `web_server.log:97`）——偶发非常态。
- **叙事（邸报/大臣奏对）**：claude（sonnet/haiku）最像人、最懂盘面；codex 系信息密度高但偏公文体；agy 够用。
- **速度可用档（simulator ~40-50s）**：`gpt-5.3-codex-spark`、`gpt-5.5`、`agy`、**`haiku4.5 + MAX_THINKING_TOKENS=10000`**。
- **淘汰交互**：`sonnet4.6`（simulator 5-7 分钟，生成 bound，关思考也救不动，留作离线叙事鉴赏）、`gpt-5.4-mini`（漏 `<<DECISION>>` 块=砍 HITL）。
- **真 baseline = Opus 4.8 在 session 里当 LLM（形态1）**：`probe.db` 现存 14 条国策（id 4-18）是它建的，**不是 agy**（agy 只建了 turn16 的 id 19/20）。别再把 DB 战绩算到 agy 头上。
- **工程坑（换 codex/claude 前必改）**：① codex 必须 `--skip-git-repo-check`（`cli_backend.py:150`，否则非 git cwd 秒失败）② codex 并发必须 `--ephemeral`（否则撞 session 状态丢空输出）③ codex 干净输出在 **stdout**（`OpenAI Codex v` 之前），日志在 stderr，别合并 ④ claude 无 gpt 的 `reasoning_effort` 档，用 `MAX_THINKING_TOKENS`（~10k≈medium），`claude -p` 默认重思考会拖慢。
- **方法学免责**：本基准是单快照 + 部分并发噪声，结构化成功率别当真实多回合率（DB 实证 agy 真实建 issue 没那么差）；唯一干净速度数据是 thinking 串行 4 跑。

## 金手指改动（本地实验，非上游原版）
`content/buildings.json` 末尾加了 3 个建筑：皇家天佑金矿（国库 +800/月）、大明中央银行（内库 +300）、帝国航空（皇威 +10）。原理：建筑走真实月度流水，LLM 查账本认账；直接改国库余额会被大臣审计成「虚存」。**只对新开存档生效**（老档建筑已写进 DB）。

## 规则
- 所有 user-facing 输出用中文。
- 改仓库内容前要明确授权（沿用全局 `~/.claude/CLAUDE.md`）。
- **PR 合并默认 merge commit，尽量不 squash**（用户 2026-06-10 明示：没有「干净历史」洁癖，逐 commit 过程史比 main 整洁重要；squash 唯一一次是 #72，导致 22 轮评审迭代史只活在 probe/tianmu-fiscal 分支上——该分支因此保留勿删）。
- **评审轮 = 独立 commit，禁止 amend 折叠多轮（对所有 agent：Claude / codex / 其它，2026-06-13 立）**：每一轮 cmr/评审 fix **各提一个新 commit**（如 PR2 的 `cmr S3 r5: …`），**严禁 `git commit --amend` 把多轮压进同一个 commit**。理由同「不 squash」：过程史 > 干净历史，评审迭代必须进**永久 git 历史**、PR 上评审者看得见每轮抓了什么改了什么。**reflog 不算数**（本地、默认 90 天 gc、不推远端、PR 不可见——amend 比 squash 还脆，轮次叙事一次 gc/清 worktree 就蒸发）。切片级「一 slice 一 commit」仍可，但 **slice 内每轮必须新 commit**。实证教训：codex 跑 ADR 0009 时把 travel 切片 ~18 轮全 amend 进一个 commit，git log 一行照不到（2026-06-13 reflog 挖出）。
- **设计文档（ADR/契约/spec）与代码同等评审**：产出后必须跑完整评审闭环（本地 cmr 收敛 + 线上三 bot 收敛），不因「只是文档」跳步；用户出此类文档时**主动提醒走评审**。实证：ADR 0008 单文档 8 轮（本地 12→11→3→0 + 线上 4 轮），抓出毒 payload 软死锁、simulator-fallback 事务后门等设计级真洞（2026-06-10）。
- **进 ship-pre / CMR 评审循环前必须确认 feature 全闭环完成，不是「核心写路径接通」就进（对所有 agent：Claude / codex / 其它，2026-06-13 立）**：Definition of Done = 所有闭环面都齐——**写入端 + 读取端 + 恢复端 + 真实 extractor 输出 + UI/呈现端 + 文档契约**，缺一面都不算 ship-ready。把「核心写路径接通 + 单元测试绿 + 前几轮 CMR 收敛」误当成「全闭环完成」两头亏：(1) 在不完整目标上启动昂贵的 ship-pre 评审循环，(2) CMR 一轮轮真抓闭环缺口、滚到离谱轮数才被外人判出「功能不足」。**判据**：进 ship-pre 前对着 plan 逐面点检 DoD，任一面（尤其读取/恢复/呈现这些最容易被「写路径接了」盖过的隐性面）未落 = 早了，先补完再进。注意这是 **ship-gate / DoD 判断**，不是编码能力——写路径接了、测试绿都可能为真，错在把「核心接通」当「全闭环完成」。实证：codex 跑 ADR 0009 person，写路径已接 + 25 单测绿、前几轮 CMR 收敛，但读取端（`offstage_ministers` 人才池）/恢复端/extractor/UI/文档闭环未齐，误进 ship-pre CMR 滚到 **r20** 才被旁路 session 判出「功能不足」（2026-06-13）。
- **任何代码工作先开分支再动手**，main 工作区保持干净（多 session 并行，脏 main 影响别人）；**纯文档工作除外，可直接在 main 改并提交**（TODOS/README/docs 叙事类；用户 2026-06-11 明示。注意：ADR/契约/spec 类设计文档虽可在 main 直改，评审要求见上条不豁免）；常驻例外 = `content/buildings.json` 金手指。

## Agent skills

### Issue tracker

GitHub Issues（`Akagilnc/ming-salvage-sim`，已设为本 clone 的 gh 默认仓库（`gh repo set-default`），`--repo` 可省；跨 clone / CI / 重设 remote 后仍建议显式带 `--repo` 防误打 upstream）。See `docs/agents/issue-tracker.md`.

### Triage labels

五个 triage 角色用默认字符串（`needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`）。See `docs/agents/triage-labels.md`.

### Domain docs

单语境：根目录 `CONTEXT.md` + `docs/adr/`。See `docs/agents/domain.md`.
