# 编排器路线 = 一等命名预设 + slug→后端数据注册表

Status: Accepted（2026-06-29；本地 cmr 8 轮[完整性 4 + 正确性 4] + 线上 bot 3 轮双闸收敛，PR #425）

## 决定

引入**路线（route）**为一等命名预设（`normal` / `codex-tight` / `claude-tight` …）。一条路线**显式列出本轮全部模型槽**（coder / per-slice reviewer / coder-fix / ship / merger / cmr 腿集合）各自的模型；切路线 = 拨一个总开关（`ORCHESTRATOR_ROUTE`），任一槽可被单独 env override 盖过（日常用法 = 选一条 base 路线 + override 那 1-2 个要动的槽）。CMR review leg 集合的 override 是 `ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS`，格式为逗号分隔 slug（如 `gpt-5.5,agy`），JSON 数组/对象一律拒收。**没有任何槽可钉死在某家族**。切换**手动**（额度紧但未耗尽时提前调，不自动探额度）。

slug→后端 从写死的 switch 改成**数据驱动注册表**：每条 = `slug → {provider, model-id, options, family, strong-leg}`，覆盖 Sandcastle 原生 6 provider（`claudeCode` / `codex` / `opencode` / `copilot` / `cursor` / `pi`）。加一个「已烤进镜像的 CLI」的兄弟模型（haiku→claudeCode、spark→codex）= **注册表加一行、零代码**；加一个**新 CLI**（opencode 跑 glm5.2 等）= 烤二进制进镜像 + 挂 auth **一次**，之后该 CLI 的多模型全靠加行解锁。**注册表是 slug→后端唯一真源**——路线表 / override / StepSpec 只引用 slug。

**不变式可校验，不靠手填表不出错**：
- **family-tight 自动校验**：每个 slug 标 `family`，路线解析器**自动断言** family-tight 不变式（claude-tight → 无 Claude-family 槽），把「没有槽钉死家族」从一句承诺变成可校验谓词。**校验遍历所有槽、含 cmr 腿集合的每一条腿**（cmr 腿是 set 不是单值，是最易漏的槽——claude-tight 必须断言 codex+agy 里没有 opus 这类 Claude 腿）。**每条 `*-tight` 路线须知道自己 tight 哪个家族**（`claude-tight`→Claude、`codex-tight`→codex）→ 断言该家族无槽（别一律查 Claude，否则误杀故意带 opus/sonnet 的 codex-tight）。**「路线怎么知道自己 tight 家族」是编码细节（显式属性 vs 前缀派生），归 #422、不在 ADR 定**。注意：family-tight 断言只对 `*-tight` 路线生效；`*-cheap` 路线**故意**保留吃紧家族的那一条 cmr 强腿（cheap 的定义），不触发该断言。**纯解析器（`(routeName,overrides)→{slot:slug}`）只检测并返回「违规 flag」，不自己问**（纯函数不交互）；**runner（调用方）见 flag → 弹提示 + 阻塞等人答**。手动 override 若会破坏 family-tight（如 claude-tight 下 `merger=sonnet`）→ 分两路：**交互（有 TTY）= 警告 + 问是否继续，不硬拒**（用户拍：claude 紧时我手动我担责）；**非交互（无 TTY / CI / 自治 AFK）= escalate-stop**（明确报错 + flag、**不静默挂死**——CI 里无限期挂起且无错误日志比 escalate 更糟；2026-06-29 线上 Gemini-2 + 用户拍）。两路都**绝不静默放行带 Claude 的 claude-tight**；且只在你**故意**塞了违规 override 时才触发（base 路线由构造不违规）。
- **强腿身份 vs cmr-腿成员（两条轴，别混）**：`strong-leg` 标**只认 opus/codex**、是 cmr **底线**资格（ADR 0032 的 floor 只数它）；这与「能否当一条 cmr 参与腿」是**两回事**。便宜模型（glm/haiku/spark）若将来要参与 cmr = **加进某路线的 cmr 腿集合**（多一票 voice），**绝不翻 `strong-leg`**——否则一个 cheap 模型会满足 floor、在 opus+codex 双死时错误放行、绕过承重闸（违反 0032）。要让 cheap 模型**撑底线**须**同时改 0032 的 floor 不变式**（不在本设计内；经验验证见 #424）。
- **fail-closed**：无效路线名 / 无效 slug 一律 fail-closed（throw / 拒跑），typo 不静默跑成错的或不存在的模型。
- **可观测**：解析出的最终阵容跑前可打印 / 审计（每 worker 用哪个模型一目了然）。

## 为什么

额度按**家族整片死**：claude 100% 时 sonnet / opus / haiku 全死，所以没有槽能钉死在一个家族（连 ship/merger 也不行）。最小切换 = 一个预设翻整套（不再三处散改 coder env + reviewer soul + cmr 腿）+ 常见的「只微调 1-2 槽」走 override。注册表是「第一次做点工作、后续方便切」的落点：onboarding 成本分两档（已烤 CLI 的模型 = 一行；新 CLI = 一次烤+auth），opencode 多模型一次 onboard 解锁 glm/deepseek/kimi 一整排。

## Tradeoff

选了**显式全槽清单（方案 A）**而非「声明可用家族集合 + 赋值器推导（方案 B）」。B 更省、cmr 降级能自动涌现，但 A 对「实验多模型 + 临时只动 1-2 槽」更直接可控（用户拍 A：实验的模型不少、额度紧时提前微调、每次多半只调 1-2 个、不是一次干掉全家族）。代价 = 多一张小而稳的「路线 → 全槽」表要维护。

## 关联

**注册表（#418）本身不依赖 ADR 0030**——它是纯 prefactor（blocked-by None），只有**路线表 / 已分离的槽**依赖 0030/#369/#419（reviewer 是独立 worker → reviewer 模型才成为可切的槽，否则埋在 coder soul 里切不动）。cmr 腿底线见 ADR 0032。opencode 的 auth = 用户的 opencode go 订阅凭证（挂进容器，同 codex/claude auth 模式；模型覆盖 onboard 时实测）。
