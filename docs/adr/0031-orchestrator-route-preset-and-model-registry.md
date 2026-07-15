# 编排器路线 = 一等命名预设 + slug→后端数据注册表

Status: Proposed

Current authority: 本 ADR 只保留“命名路线 + slug 注册表 + family-tight 不变式”。Policy Resolution / Quota Seating 的求值与处置只读 #870，Runner 边界只读 ADR 0131；路线或 override 的专业结果不得进入 Runner。#905 / PR #912 已进一步裁定：`agy` 只指真实 agy CLI，`grok-4.5` 只经 grok-build / SuperGrok provider，OpenCode 不再是编排器 transport。

## 决定

引入**路线（route）**为一等命名预设（`normal` / `codex-tight` / `claude-tight` …）。一条路线为本轮每个需要模型的 Action / worker seat 显式提供模型；完整 seat 集合由 owning Action 的 capability request 与 #870 Policy / route registry 形成，本 ADR 不复制一张会漂移的静态枚举。切路线 = 拨一个总开关（`ORCHESTRATOR_ROUTE`），任一 seat 可被单独 env override 盖过（日常用法 = 选一条 base 路线 + override 那 1-2 个要动的 seat）。CMR review leg 集合的 override 是 `ORCHESTRATOR_CMR_REVIEW_LEG_SLUGS`，格式为逗号分隔 slug（如 `gpt-5.5,agy`），JSON 数组/对象一律拒收。**没有任何 seat 可钉死在某家族**。operator 仍手动选择 base route / override；runtime preflight、quota 与 candidate traversal 只读 #870 / ADR 0134。

slug→后端 从写死的 switch 改成**数据驱动注册表**：每条 = `slug → {provider, model-id, options, family, strong-leg}`，只登记当前获准的可执行 provider。加一个已接入 provider 的兄弟模型（haiku→claudeCode）= **注册表加一行、零代码**；接入新 CLI 则先完成二进制、auth 与 provider adapter，再登记其 slug。**注册表是 slug→后端唯一真源**——路线表、override 与角色/动作配置只引用 slug。当前 owner 约束是 `agy →` 真 agy CLI、`grok-4.5 → provider: grok`；不得用 OpenCode 或 Cursor 转运 Grok，也不得重新登记 OpenCode / glm slug。

**不变式可校验，不靠手填表不出错**：
- **family-tight 自动校验**：每个 slug 标 `family`，Policy / route parser 对所有槽（含 cmr 腿集合）校验 `*-tight` 不含对应家族；`*-cheap` 不适用该断言。表示 tight 家族的编码细节归 #422。解析结果只交回调用它的 Policy / Action；Runner 不读取违规 flag、模型或家族。命名 tight 路线或手动 override 只要破坏 family-tight，就在最早的纯配置 preflight 中零副作用 fail-closed；不静默放行、不启动 worker，也不把配置矛盾交给 Runner 或 decision gate。
- **强腿身份 vs cmr-腿成员（两条轴，别混）**：`strong-leg` 标**只认 opus/codex**、是 cmr **底线**资格（ADR 0032 的 floor 只数它）；这与「能否当一条 cmr 参与腿」是**两回事**。便宜模型（haiku 等）若将来要参与 cmr = **加进某路线的 cmr 腿集合**（多一票 voice），**绝不翻 `strong-leg`**——否则一个 cheap 模型会满足 floor、在 opus+codex 双死时错误放行、绕过承重闸（违反 0032）。要让 cheap 模型**撑底线**须**同时改 0032 的 floor 不变式**（不在本设计内；经验验证见 #424）。
- **fail-closed**：无效路线名 / 无效 slug 一律 fail-closed（throw / 拒跑），typo 不静默跑成错的或不存在的模型。
- **可观测**：解析出的最终阵容跑前可打印 / 审计（每 worker 用哪个模型一目了然）。

## 为什么

额度按**家族整片死**：claude 100% 时 sonnet / opus / haiku 全死，所以没有槽能钉死在一个家族（连 ship/merger 也不行）。最小切换 = 一个预设翻整套（不再三处散改 coder env + reviewer soul + cmr 腿）+ 常见的「只微调 1-2 槽」走 override。注册表是「第一次做点工作、后续方便切」的落点：已接入 provider 的模型只需登记新行；新 CLI 先完成一次 provider 接入，再按 owner 批准的 slug 扩展。

## Tradeoff

选了**为已注册 model-bearing seat 显式赋值（方案 A）**而非「声明可用家族集合 + 赋值器推导（方案 B）」。B 更省、cmr 降级能自动涌现，但 A 对「实验多模型 + 临时只动 1-2 个 seat」更直接可控（用户拍 A：实验的模型不少、额度紧时提前微调、每次多半只调 1-2 个、不是一次干掉全家族）。代价 = 路线表需要覆盖 owning Action 已注册的 seat；seat 集合本身仍只在 Action capability / Policy registry 维护。

## 关联

**注册表（#418）本身不依赖 ADR 0030**——它是纯 prefactor（blocked-by None），只有**路线表 / 已分离的槽**依赖 0030/#369/#419（reviewer 是独立 worker → reviewer 模型才成为可切的槽，否则埋在 coder soul 里切不动）。cmr 腿底线见 ADR 0032。原设计曾把 OpenCode 作为 onboarding 候选；该候选已被 #905 / PR #912 明确废止，历史 commit 保留原始沿革，current registry 与 route 不得恢复它。
