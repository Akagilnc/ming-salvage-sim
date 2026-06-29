# 编排器路线 = 一等命名预设 + slug→后端数据注册表

Status: Proposed（2026-06-29，grill 结晶；评审闸在 to-prd 之后，本 ADR 尚未评审）

## 决定

引入**路线（route）**为一等命名预设（`normal` / `codex-tight` / `claude-tight` …）。一条路线**显式列出本轮全部模型槽**（coder / per-slice reviewer / coder-fix / ship / merger / cmr 腿集合）各自的模型；切路线 = 拨一个总开关（`ORCHESTRATOR_ROUTE`），任一槽可被单独 env override 盖过（日常用法 = 选一条 base 路线 + override 那 1-2 个要动的槽）。**没有任何槽可钉死在某家族**。切换**手动**（额度紧但未耗尽时提前调，不自动探额度）。

slug→后端 从写死的 switch 改成**数据驱动注册表**：每条 = `slug → {provider, model-id, options}`，覆盖 Sandcastle 原生 6 provider（`claudeCode` / `codex` / `opencode` / `copilot` / `cursor` / `pi`）。加一个「已烤进镜像的 CLI」的兄弟模型（haiku→claudeCode、spark→codex）= **注册表加一行、零代码**；加一个**新 CLI**（opencode 跑 glm5.2 等）= 烤二进制进镜像 + 挂 auth **一次**，之后该 CLI 的多模型全靠加行解锁。

## 为什么

额度按**家族整片死**：claude 100% 时 sonnet / opus / haiku 全死，所以没有槽能钉死在一个家族（连 ship/merger 也不行）。最小切换 = 一个预设翻整套（不再三处散改 coder env + reviewer soul + cmr 腿）+ 常见的「只微调 1-2 槽」走 override。注册表是「第一次做点工作、后续方便切」的落点：onboarding 成本分两档（已烤 CLI 的模型 = 一行；新 CLI = 一次烤+auth），opencode 多模型一次 onboard 解锁 glm/deepseek/kimi 一整排。

## Tradeoff

选了**显式全槽清单（方案 A）**而非「声明可用家族集合 + 赋值器推导（方案 B）」。B 更省、cmr 降级能自动涌现，但 A 对「实验多模型 + 临时只动 1-2 槽」更直接可控（用户拍 A：实验的模型不少、额度紧时提前微调、每次多半只调 1-2 个、不是一次干掉全家族）。代价 = 多一张小而稳的「路线 → 全槽」表要维护。

## 关联

依赖 ADR 0030（reviewer 是独立 worker → reviewer 模型才成为可切的槽，否则埋在 coder soul 里切不动）。cmr 腿底线见 ADR 0032。opencode 的 auth = 用户的 opencode go 订阅凭证（挂进容器，同 codex/claude auth 模式；模型覆盖 onboard 时实测）。
