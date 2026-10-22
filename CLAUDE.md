# Ming_LLM — 项目 CLAUDE.md

## 📚 工作手册（每回合开始前必查，别凭"我以为"）
- **[docs/adr/0159-ledger-entities-events-and-landing.md](docs/adr/0159-ledger-entities-events-and-landing.md)** — 重写后的四层架构、技术栈、账本（实体＋事件）、落账与重交。**动任何代码前查。**
- **[docs/AUDIENCE_NORTH_STAR.md](docs/AUDIENCE_NORTH_STAR.md)** — 召对体验**北极星案例**（单场·越次召对·杨嗣昌 + 连场·乾清宫一夜）：召对记录全文 + 海报 html + 王承恩递话旁白层 + 召对流程用词。**做 / 评召对时对着它比。**
- **[M11「北极星·召对效果」总计划/进度 = issue #486](https://github.com/Akagilnc/ming-salvage-sim/issues/486)** 大方向执行顺序 

## 架构（#1943 重写，已 grill 定）
- **四层，自上而下**：前端 → 使用者（召对、过月）→ 中间层 → 账本。依赖只向下；账本只有一个门＝中间层；使用者之间只经账本交接；前端读走中间层往外的口（身份＝皇帝），写与动作走使用者。代码不判断。
- **技术栈**：Python；`eventsourcing`（只用 Aggregate＋`@event`）＋ `eventsourcing-sqlalchemy` 落 SQLite（一局一个文件），普通 ORM 表与事件同一事务更新；Pydantic AI `output_type` 声明；ruff（P8 规则、`TID251` 禁正则）、import-linter、pyright，CI 禁 `# noqa`；PyInstaller＋pywebview 打包。
- 账本、落账、重交、接不住、皇帝视图的全部决定 → **ADR 0159**（真源，此处不复述）。

## 探针设计铁律

**总纲**：引擎存在的唯一理由是 LLM 记忆有限——**引擎=物理事实账本**，负责记录、记住、提供世界的物理事实（P1 因此是第一铁律）。**物理事实和人（皇帝、大臣）能看见的没有任何强制关联**：奏报可载假象、账面可虚存、国库数字可以是假的（看着有花不出不稀奇）——真相只活在账本，呈现层是「人在说话」，而人会骗人。

- **P1 决策当回合全量落账本（第一铁律）**：凡下旨，后果**当回合全量落进账本**（实体上的事件）；转译接不住的，也落一条「接不住」，不丢。**判据**：重开只读账本能无损接续=到位；需"我记得"补=漏了。落盘频率：每回合自动存档即可；现选 SQLite 一局一文件，每次落账即提交。
- **P3 品味护栏 → [docs/ROLE_FIDELITY.md](docs/ROLE_FIDELITY.md)**：国策=旨意的具体后果（建军/人物去向/营建/财政/局势的此刻实体后果）；真护栏=皇帝角色保真 + 冰汽时代式高压求生（破局可真）；长线发展须「diegetic 形态 + 史实合理尺度」两轴过。⚠️ 只写 docs、不进游戏 prompt。全文与理由变更史见专档。
- **P2 军备/城防建模（数据轴，判战永远 LLM 软判，代码只 clamp 不算胜负）**：军队 `firearm_equipment` 0-100（鸟铳，野战+守城）、`cannon_equipment` 随军红夷炮门数 cap 12（野战带不动多）；地区 `city_level` 0-5（静态史实分级，京师5）、`cannon` 城防红夷炮门数 cap=`city_level×8`（城头炮，守城关键）。佛郎机轻炮归 firearm；随军炮利攻、城防炮利守。
- **P4 呈现层：DB 有数，皇帝无表**：玩家（皇帝）**不见裸数值**——忠诚/能力/家产等一律定性叙事呈现（「军事能力优秀」，不是「98」；家产例外——报约数放行：「家赀约数十万两」式奏报口吻合法）；皇帝透过奏对/行为/传闻读人，不看角色卡。数值照旧活在 DB 供引擎（与 P2 不冲突：P2 管引擎侧建模，P4 管呈现侧翻译）。配套方向：锦衣卫可查家产但不保证准、精度拟挂目标「阴谋」类能力；叙事可留线索（「国丈哭穷」本身就是信息）。落 prompt 时用正向表述（「以奏疏口吻定性描述人物」）。
- **P5 LLM 流程并行优先**：设计任何涉 LLM 调用的流程，**第一考虑「能不能并行 LLM 调用以缩短用户等待」**。单次 LLM 调用就很慢（召对回话 ~15-30s、simulator ~47s+、extractor ~30s、codex 每调用 ~15s 固定开销）= UX 真瓶颈；而**写 DB 多写几次根本无所谓**（毫秒级、免费）。密令抽取从对话上下文取→与回话并行；结算 extractor 多模块无依赖→并行。**严禁为「省 DB 写次数 / 少建几条记录 / 少加一列」而把本可并行的 LLM 调用串起来 = 拿免费的换最贵的。** streaming 也是缩短**感知**等待的手段（simulator 边算边出填等待）。
- **P6 判断与文字都归 LLM**：角色的决定（要不要弹劾、怎么措辞、判胜负）由 LLM 按人物和局势自己发挥，写出来什么就是什么——代码不替角色做决定（烈度公式/quota/概率门违宪），也不改它写的字，要改效果只改它能看见的输入。
- **P7 文字模板=违宪**：玩家可感文本由 LLM 从特征化输入长出；固定句式/占位符拼装/单句模板不问理由判死。LLM 游戏与普通文本游戏的全部区别=玩家几句话摸不到模板的底。「同一话术呈皇帝」=大臣会骗人（真伪同以可信口吻呈上）。呈现准绳=docs/AUDIENCE_NORTH_STAR.md。 标题、菜单、按钮、过月／等待／锁定提示等界面固定话语不在此列——「这只是游戏必备的固定提示」。

- **P8 代码规模上限**：「max-statements 200 条语句；另 max-args 5、max-branches 12、max-locals 15、max-returns 6　max-module-lines 1000 」

  | 上限 | 值 |
  |---|---|
  | 单函数语句数（max-statements） | 200 |
  | 单函数参数（max-args） | 5 |
  | 单函数分支（max-branches） | 12 |
  | 单函数局部变量（max-locals） | 15 |
  | 单函数 return（max-returns） | 6 |
  | 单文件行数（max-module-lines） | 1000 |

  超限即违宪。

## 关键技术事实
- **领域素材在 `content/`**：新包按 `ming/middle/opening.py` 导入开局数据；尚未使用的数据保留，按需另票导入。`content/prompts/scene_agent.md`、`month_translate.md` 是在用提示词素材，其他提示在 `ming/` 内声明。

## LLM 后端（换模型时查，非每回合）
- **工程坑（换 codex/claude 前必改）**：codex 必须 `--skip-git-repo-check` + 并发 `--ephemeral`，干净输出在 stdout（日志在 stderr）；claude 用 `MAX_THINKING_TOKENS`（~10k≈medium）代 gpt 的 reasoning_effort，`claude -p` 默认重思考会拖慢。

## 金手指改动（本地实验，非上游原版）
`content/buildings.json` 末尾加了 3 个建筑：皇家天佑金矿（国库 +800/月）、大明中央银行（内库 +300）、帝国航空（皇威 +10）。原理：建筑走真实月度流水，LLM 查账本认账；直接改国库余额会被大臣审计成「虚存」。**只对新开存档生效**（老档建筑已写进 DB）。

## 规则

- **本仓分支特例**：任何代码工作先开分支；**纯叙事文档可直改 main**；常驻例外 = `content/buildings.json` 金手指（见上文「金手指改动」节）。
- **`probe/tianmu-fiscal` 孤本分支勿删**（#72 squash 后 22 轮评审迭代史只活在该分支）。
- 测试分级见本文件「## 测试分级」。

## 测试分级（#1185，owner 2026-08-13 裁定）

公共前置的共享与隔离遵循 [ADR 0161](docs/adr/0161-shared-test-prefix-built-once.md)。

**本仓测试分级政策真源**：

- **切片轮次** 推荐逐片 implement / fixer 聚焦测试；不以复跑全量 suite 为必须复核手段。
- **聚焦测试** 本片触及的测试。
- **家族/批次收尾**＝在**最终待合并状态**执行一次全量 suite。
- **CI**（`.github/workflows/ci.yml`）覆盖 **Python 全量 pytest + Web 构建/类型检查**（`tsc` + vite build），**不含 Web vitest**；本政策如实描述既有覆盖面，不改 CI 机制、不把 vitest 加进 CI。

正向口径：切片只跑聚焦；全量在最终待合并状态跑到绿（失败/修复后重跑）

### 报错断言在本仓的落法（规则本身见全局硬规 #13）

#13 禁盯文、保闸类契约的负向案。

## Agent skills

**发票纪律**：父子与依赖关系一律用 GitHub 原生 sub_issues / blocked_by。

### Triage labels

See `docs/agents/triage-labels.md`.

### Domain docs

单语境：根目录 `CONTEXT.md` + `docs/adr/`。 用法见 `docs/agents/domain.md`。
