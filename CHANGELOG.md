# 更新日志

本项目所有重要变更记录于此。格式参考 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.0.0/)。

## [未发布]

## [0.15.0.0] - 2026-06-27

### 新增
- **统一推理强度设置**：菜单页与局中 LLM 配置新增统一「推理强度」选择器，支持 API 与 CLI 通道分别保存 `off/low/medium/high`，并按 OpenAI、DashScope、Minimax、codex、claude 的能力自动启用或禁用。
- **密令确认上下文恢复**：玩家先与大臣商议任务、下一轮只用「密令」按钮确认时，系统会从最近相关召对中恢复皇帝任务和大臣实质补充，生成完整密令，而不是只保存确认短句。

### 变更
- **推理配置迁移到单一旋钮**：旧 `thinking_level` / `advanced_thinking_level` 会迁移到 `reasoning_strength`，保存时清空旧隐藏字段，避免旧配置继续暗中覆盖玩家的新选择；API/CLI 两个槽位互相保留各自的推理强度。
- **探报章节命名收敛**：邸报与军务抽取 prompt 将「陛下未知者」统一改为「探子回报」，前端展示和原始样例同步跟进。
- **军务抽取契约收紧**：`派系变化` 只能使用合法派系 key，不再允许把 `armies`、army_id 或具体军号误写成派系；具体军队后果改走 `军队变化` / `新建军队`。

### 修复
- **API 密令前缀不再重复抽取**：API tool-call 已成功创建密令时，后置 fallback 不再额外发起一次会被丢弃的 LLM 抽取，减少等待和调用成本。
- **密令正文防串台**：确认式密令现在会排除无关早前问答，只保留最近相关任务跨度；同时保留前文大臣的承办人、步骤、保密要求和期限补充。
- **推理强度持久化边界**：切换 API/CLI 通道、清空强度回默认、advanced model 复用主配置、CLI runner 不支持推理强度等路径都按通道正确读写，不再丢失 inactive 槽设置。
- **家族合并测试断言对齐**：修正 orchestrator 家族 worktree 位置测试，使其断言当前实现使用的 `.worktrees/.epic-orchestrator` sibling 路径。

### 测试
- 新增 reasoning strength 运行时配置、CLI 后端映射、web 菜单状态、密令上下文恢复、军务 prompt 契约和探报标签覆盖；ship 验证为 `1767 passed, 13 skipped`，web Vitest `97 passed`，web build 通过。

## [0.14.1.0] - 2026-06-25

### 修复
- **取消飞行中的召对流**：客户端断连（SSE 流提前关闭）时，后端现在能可靠地将对应回合标记为 `failed`、删除其关联的用户提示消息，并清理内存中的对话历史用户条目；已完成回合的取消请求保持幂等，不触发任何副作用。
- **承诺进度条改用挂钟时间**：进度条月数改从 `origin_turn`（承诺创建回合）计算，消除月末滚动更新重试导致月数偏高的问题，使进度条与游戏时间线严格对齐；`origin_turn` 缺失/为 0/NULL 时回退到 `state.turn`（已履行 0 月），不再把绝对回合数泄进进度条。
- **取消守卫异常安全**：`chat_stream` 断连处理器现将清理操作包裹在 `try/except` 中，确保 DB 错误不会替换原始中断信号、破坏 HTTP 流式终止；清理异常会被记录日志而非静默吞掉。
- **取消检测前置 + 防御式关流**：进入阻塞读取前先探一次客户端断连；SSE `finally` 关流前先校验 `close` 可调用，避免迭代器/测试替身缺 `close` 时 `AttributeError` 掩盖原始异常。
- **消息 id 空值判断收紧**：`user_message_id` 与 `minister_message_id` 均改用显式 `is not None` 判断，防御性修复极端情况下 `id=0` 消息被误跳过删除 / 已完成回合被误判为未完成。

### 测试
- 新增取消守卫专项测试：关闭流标记失败/删消息、已完成取消保持幂等、SSE 断连检测端到端、不存在/无消息 id/竞态/正常完成等间隙用例；新增承诺进度条计时集成测试（挂钟推进、边界截断）。

## [0.14.0.0] - 2026-06-24

### 新增
- **行止超时兜底**（#346）：DB 新增 `transit_start_turn` 列，记录人物进入行止状态的回合；`force_transit_arrivals` 在每回合 `pre_settle` 中强制驱动滞留 ≥2 回合（或 `transit_start_turn=0` 旧数据哨兵）的人物到达目的地，防止行止人物因事件复杂度无限阻塞。到达顺序固定在事件终态评估之前。模拟器上下文新增 `transit_nudge` 字段，提示 LLM 哪些人物已兜底抵达。
- **实时召对短超时**（#353）：新增常量 `MINISTER_CHAT_CLI_TIMEOUT_SECONDS = 90.0`；`create_minister_agent` 通过 `dataclasses.replace` 克隆 LLM 配置并将超时降到 90 s，与月末结算的 300 s 超时完全解耦，避免召对等待超时影响结算管线。
- **召对取消按钮与计时**（#353）：前端 `ChatModal` 新增取消按钮（`.composer-cancel` 样式），通过 `AbortController` 中断飞行中的流式请求；弹窗同步显示已等待秒数（`elapsedSeconds`），关闭弹窗或回话结束时自动重置，多大臣并发时补充陈旧响应守卫防跨污染。
- **承诺进度条时间轴**（#348）：新增 `commitment_timed_bar_value(issue, state)` 函数，按已过回合数占总承诺周期比例返回进度条数值（`None` 表示无限期承诺）；`web_app.py` 在承诺类局势 payload 中注入 `bar_value` 字段，前端可直接驱动进度条渲染。

### 修复
- **承诺显示改用相对时长**（#348）：`commitment_display_text` 重构为从当前回合计算剩余回合数，消除因记录截止绝对值导致的「负剩余」和僵死部件堆积。
- **帝国修正不放大支出**（#341）：月末经济结算中，帝国修正系数（empire modifiers）现在只作用于收入项，`base < 0` 的支出项（军饷、俸禄、省级拨付等）直接原值落库，不再被修正放大，消除「下令 100 两、实际出账 130 两」的数值错误。
- **行止 re-emit 不刷新 `transit_start_turn`**（#346）：同目的地的重复行止事件（re-emit）保留原始 `transit_start_turn` 值；派生任命（引退→新任）的回滚路径对称还原 `transit_start_turn`，防止哨兵值被意外重置导致兜底逃逸。

### 测试
- 新增行止兜底（`transit_start_turn` 快照 / 恢复、`force_transit_arrivals` 原子性、re-emit 不刷新哨兵）、召对超时常量契约、`create_minister_agent` 超时上限和无副作用覆盖；ship 验证为 `1552 passed, 13 skipped`，Vitest 3 passed（预存在 `epicOrchestratorWorkflow.test.ts` 失败已收录 TODOS.md B13，非本分支引入）。

## [0.13.0.0] - 2026-06-20

### 新增
- **对话式拟旨**（#137，对齐 ADR 0006）：玩家在召对中用自然语言「拟旨吧 / 你拟一道旨」即可触发大臣草拟圣旨，不再必须点按钮；自然语言拟旨暂存为 `pending_actions(kind=directive)`，不走召对期的应允 / 拒绝即时提交或丢弃，颁诏时自动承接为 `turn_directives` 草案并入拟诏。「补充」走同一条 pending 原地更新（last-write-wins）。「不回 = 颁诏默认同意」路径在真实 Web 全栈接通（后端结算 → 前端 `pending_directive_count` → 拟诏按钮可用）。

### 修复
- pre-landing 跨模型评审（红队 + codex）收敛的若干个正确性 bug：
  - 确认闸不再误扫对话式拟旨草案（应允/拒绝其它待办时不会提前提交或静默删除草案）。
  - 拟诏 / 月末结算遇未决显式拟旨时**先拒绝再提交**，无部分提交副作用。
  - 撤回召对**精确删除**本次产生的草案（`committed_directive_id`），不误删同回合同大臣的无关草案，含补充（restore_row）路径。
  - 草案变化时**作废过时的生成诏书文本**，防止下发不含新草案 / 含已撤回内容的 stale 诏书。

## [0.12.6.0] - 2026-06-20

### 新增
- **圣旨承诺账本**：玩家下达“每月补饷直到补齐”“连续数月执行”“数月后复核”等旨意时，系统会把承诺写成可追踪局势，而不是只停留在邸报叙事里。
- **三类承诺形态**：支持持续直到达标、限期持续、未来一次性复核；到期待裁的承诺会进入密令待核议通道，并通过 `acknowledged` 收尾。
- **承诺进度呈现**：局势面板、详情弹窗、悬浮提示和大臣工具都会显示承诺类型、截止回合、终止条件和当前进展。

### 变更
- **承诺结算独立于普通局势惯性**：圣旨承诺不再按普通 issue 的衰减和惯性推进，而是逐月执行财政、指标、人物、势力、阶级、地区、军队等明确后果。
- **Extractor 契约收紧**：prompt、schema 和工具说明要求承诺必须显式写 `commitment_kind`、`origin_ref`、`ongoing_effects`、`stop_condition` 或未来 `end_turn`，拒收缺锚点、旧式人物条件、立即过期和不可月结的一次性实体效果。
- **承诺状态进入存档载体**：`issues` 表新增承诺字段，模拟器上下文和 web API 输出结构化承诺进度，恢复存档后仍能继续追踪。

### 修复
- **承诺不会空转或误结案**：修复持续效果被判定为有工作但月结不落库、指标被高 bar 折成 0、字符串数值被误判、当前回合截止立刻过期、旧 `resolve_condition` 形状生成死局势等边界。
- **待裁承诺 ACK 不触发奖惩**：未来一次性复核到期后只进入待核议，确认后 dropped，不会误跑 resolve/fail 的实体后果。

### 测试
- 新增承诺创建、schema、结算、恢复、ACK、人物安抚、大臣工具和 web 呈现覆盖；ship 验证为 `1429 passed, 13 skipped`，web Vitest `3 passed`，web build 通过。

## [0.12.5.0] - 2026-06-20

### 修复
- **地区控制者落库守门**：`region_delta.controlled_by` 现在只接受 `powers.id` 中存在的非空势力 id；`null`、空白和未知势力会逐项拒收留痕，不再污染地区控制权。
- **收复地区恢复逻辑保留**：合法 `controlled_by` 变更仍会落库；非明→明的收复路径继续触发 `on_restore` 覆盖，避免守门误伤既有收复流程。

### 文档
- `docs/DELTA_SCHEMA.md` 明确 `controlled_by` 不再是普通文本字段，而是受 `powers.id` 白名单约束的势力 id。

### 测试
- 新增无效控制者拒收、合法势力 id 落库、同批坏字段/好字段隔离与收复 hook 回归覆盖；ship 验证为 `1352 passed, 13 skipped`，`compileall` 通过。

## [0.12.4.0] - 2026-06-19

### 修复
- **事件结局标签本地重试**：历史事件提取器返回缺失或未知结局标签时，会只重跑 `issues` 模块并保留其它模块结果，避免一次坏标签丢掉整轮提取成果。
- **结局标签别名归一**：己巳之变等封闭事件结局支持同义标签规范化；超过重试上限后仍响亮失败，防止下游事件链吃到不明分支。

### 测试
- 新增事件结局标签别名、issues-only 重试和重试上限 fail-loud 覆盖；ship 验证为 `1316 passed, 13 skipped`，`compileall` 通过。

## [0.12.3.0] - 2026-06-19

### 新增
- **战略/外敌事件显式分类**：大凌河、林丹汗西迁、戊寅虏变、松锦决战、洛阳陷、开封围城、北京陷落等历史节点新增 `trigger_class=strategic_foreign` 与结构化 `trigger_gate`，己巳虏变也显式声明为空门控。
- **席位制战事软判**：战略/外敌事件的点名将领按战事席位和盘面结果处理，不再因历史人物提前死亡而直接作废候选。

### 变更
- **战略事件触发收口到主账结果**：`event_pool` 触发战略/外敌事件时，必须同信封落地区、军队、人物、势力或新军等世界状态主账结果；空触发会被拒收并保留明确原因。
- **事件分类消费改为配置驱动**：战略/外敌判定从硬编码事件 id 转为读取 `trigger_class`，后续新增同类事件需同时补内容分类与消费映射；缺消费映射会在内容绑定期响亮失败。

### 修复
- **战略事件文本锚点收窄**：普通河南治理或李自成势力变化不再因“洛阳/开封/河南/流寇”等泛地名被误当成未触发的城陷战果而拒收。

### 测试
- 新增 #194 覆盖：战略/外敌事件分类与门控精确矩阵、点名将死亡不作废、大凌河/林丹汗西迁缺主账拒收与主账落地触发。
- 全量验证：`1323 passed, 13 skipped`。

## [0.12.1.0] - 2026-06-18

### 新增
- **历史事件时间窗过期终态**：历史事件和 seed 事件可声明最晚触发时点；过最晚仍未满足前提门时会记录 `expired` 终态，之后即便盘面条件变为达标也不会再晚弹。

### 变更
- **开放窗显式化**：历史锚定事件必须显式声明 `trigger_end_year` 或 `open_window`；漏填不再静默当作永不过期，现有开放窗事件已逐一标明。
- **事件配置加载校验**：`trigger_month` / `trigger_end_month` 必须在 0-12 内，`open_window` 必须是 JSON boolean，且最晚时点不能早于最早时点；坏内容在加载期响亮失败。

### 修复
- **过期事件拒收路径**：`event_pool` 立项遇到已过期事件时会返回明确“过期终态”拒因，不再落成普通局势或被泛化成候选池不满足。
- **终态落账写路径收口**：候选池读取只过滤过期/作废/避过事件，不再顺手写库；结算前半段通过 `apply_event_terminal_states` 显式落 `event_triggers` 终态，并在外层事务内不提前 commit。

### 测试
- 新增事件窗口、开放窗、过期终态、自动触发过期、加载契约、候选读取只读和事务回滚覆盖；PR 最终全量验证为 `1313 passed, 13 skipped`，前端构建通过。

## [0.12.0.0] - 2026-06-18

### 新增
- **历史战事软判闭环**：戊寅虏变、松锦决战等战略/外敌事件不再只落一条长期局势；裁判可在同一信封写地区、军队、人物、势力和新军等主账结果，主账真实落地后才记录事件触发。
- **人物核心历史门**：毛文龙、袁崇焕、卢象升、洪承畴、孔有德、福王等历史人物事件新增结构化前提和避让逻辑；玩家已经改变人物状态、官职、去向、势力或生死时，历史节点会按盘面避让或转为已处理。
- **流寇分股势力模型**：李自成、张献忠等流寇从笼统 `bandits` 拆成独立势力股；招安、归明、剿股和反噬只作用于对应股，避免“招一人、削错股”。
- **事件结局字段**：新增 `事件结局` / `event_outcomes` 顶层字段，用于己巳之变这类有闭合结果标签的战略事件，并接入 extractor 白名单与误路由检查。

### 变更
- **战略战果契约收紧**：战略/外敌事件必须带有可验证的世界状态主账结果；地区、军队、人物、势力和新军战果都要带事件锚点，孤儿战果、缺结局标签、重复候选、过期候选和无主账结果都会被拒收。
- **人物变更与事件门对齐真实落地**：同状态处置/罢黜、同官职任命/调任、同去向行止、同势力易主等 no-op 不再消耗战略事件；别名、任命、易主反噬和内存回滚按真实写口预检。
- **历史事件 prompt/schema 对齐**：score extractor 与 season simulator prompt 明确战略事件、人物核心事件、流寇招安和 `power_updates` 写法，减少空触发、错字段和双减。

### 修复
- **战略信封原子性**：事件结果预检失败、人物反噬拒收、新军重复、势力字段非法或 power update 提前落库时，整组战果不落主账，避免事件已触发但盘面没有对应后果。
- **旧档与静态盘面回填**：旧 `event_pool` issue 回填为 `event_triggers` 时保留核心效果事件，旧 bandits 人物按静态内容迁到各自流寇势力股。
- **提取器误路由覆盖**：`event_outcomes` 能规范化为 `事件结局`，不会被当作跨模块错放字段丢弃或误报。

### 测试
- 新增和扩展历史事件、战略战果、人事变更、流寇分股、schema/prompt 和 extractor sanitizer 覆盖；PR 最终全量验证为 `1293 passed, 13 skipped`。

## [0.11.1.0] - 2026-06-18

### 修复
- **月末结算后半段事务闸门加固**：局势推进/撤销/结案、实体后果、地区/军队/建筑/阶级/势力副作用、密令更新与结案等写口统一尊重外层事务，避免内部 `commit` 提前落盘导致“结算失败但局部已生效”的半写存档。
- **事件候选池同回合重验**：`event_pool` 立项会同时检查输入时快照、当前候选池、同批去重和同回合人事变更后的前提门；同一事件重复 emit、候选窗口过期、人物状态/官职/缘由/去向/势力变化导致前提失效时，不再误立局势。
- **人事变更 runtime 回滚闭环**：外层事务回滚时，`state.metrics`、`content.characters` 和大臣 registry 的 agent/session 缓存一并回到事务前状态，避免 DB 已回滚但本进程仍保留未提交身份的幽灵大臣。
- **任命与易主闸门对齐真实落地**：同回合任命的别名归一、宗藩拒任、独占实职顶替、`reason_code/status_reason` 清理、`office_type` 推断和易主反噬对 `power.*` 前提门的影响，均按真实写口模拟后再决定是否立项。

## [0.11.0.0] - 2026-06-14

### 新增
- **省级财政基座 port（#66，Epic #65 / M3）**：把 22 轮跨模型评审收敛的 `spike_settle_tick.py`（v23.1）搬成真引擎代码。
  - `ming_sim/fiscal_tick.py` `settle_tick(st, p, actions)`：单省单月复式记账结算（⓪–⑪：action 相位/应征火耗实征民欠/起运存留分池漂没/拨付中饱/法定付款 waterfall 偿旧欠结转），4 独立守恒 oracle（现金/债务 per-account/C 分账/土地）每 tick 自校，坏输入→`ValueError`、守恒破→`FiscalConservationError`。
  - `tests/test_fiscal_tick.py`：G1–G22 末态硬期望 golden + G21 fail-loud 输入校验面 + G9 三 tick 死亡螺旋链（69 测）。
  - `GameDB.settle_province_tick`（`ming_sim/db.py`）：DB↔settle_tick 桥（读 `regions.fiscal.settle.{st,p}` → tick → 写回 `new_st`）。陕西（单省脊柱）种子 = v23 占位数（史实重标见 #70）。
  - 接入月末固定财政相位（`apply_fixed_period_flows`）**shadow 模式**：基座逐月演化+落库，但暂不驱动国库（占位数偏史实 3–10×，⑫国库 cutover 待 #70 重标后切）；fail-loud 但隔离（基座失败不掀翻 pre_settle 固定财政）。
  - 港口锁（ADR 0008）：FAIL tick 在 UPDATE 前 raise、绝不持久化。

## [0.10.0.0] - 2026-06-14

### 新增
- **人事档案 applier 契约（ADR 0009 C1）**：人物状态/名分/去向的落库从分散多入口（office_changes / character_status_changes / character_power_changes / appointments）统一收口到单一 `人物变更` delta + 契约化 applier。新增 `person_archive_contract.py`（状态/动作/缘由转移矩阵 + reason_code 规范化）、`person_delta_adapter.py`（旧四 key → `人物变更` 保真翻译，旧 key 仅作 ready=1 重试兼容、自然枯死）、`person_write_inventory.py`（直写 characters 表的写点清单 + AST 扫描守门）。
- **起复人才池视图**（offstage_ministers）：居家/致仕/削籍在世大臣带 reason_code/status_reason 进 simulator 盘面与 extractor 上下文，裁判/玩家看得见可起复之人。
- **三面同步（决定6）**：Character 携 reason_code/status_reason；处置/易主/顶替/起复后 DB 行、in-txn content、内存 Character 一致，reload 回滚兜底。

### 变更
- 历史 卒/登场 tick 经 `处置` 语义统一落库；易主置 active 并清旧滞留缘由（如「松山兵败被执」）+ 记 status_changed_turn。
- 在朝名单（court_roster）/ 起复人才池 / active_ministers 三处统一 roster 口径 = 大明、非后宫（active 外臣如皇太极、offstage 流寇如李自成不再混入）。
- 月末结算重排：inertia 漂移在留痕 + 章节记忆之前跑，使其追加的玩家可见人物变更并入 applied（SETTLEMENT_FLOW 同步）。
- extractor prompt 正向化（移除负向「不要X」指令）+ 教 reason_code by 缘由。

### 修复
- 新开档老档迁移：罢居府名不再硬写进 region_id 列（地名留 status_reason）；在途中文目的地经 `match_region_id_from_text` 解析成 region_id 落 transit_to（旧码中文 vs 英文 id 恒不等、transit_to 永不落）。
- 顶替全腾缺清 transit_to（被顶替者落听用候铨、不留赴老职路线）。

### 备注
- ship-pre 双闸：5a 完整性闸 PASS、5b 正确性闸 8 轮 cross-model review + 对抗性核验收敛（0 真 P0/P1）。
- Deferred findings（契约加固/审计/测试批）追踪于 [issue #97](https://github.com/Akagilnc/ming-salvage-sim/issues/97)。

## [0.9.0.0] - 2026-06-12

### 新增
- **结算落库拒收契约(ADR 0008 PR2)**:月末落库的 9 个 section(势力/人物易主/地区/军队/建军/财政三段)从「整段吞异常·裸奔崩整月·静默丢脏项」统一迁成**逐项拒收留痕**——LLM 脏数据(幻觉 id、查无此人/此地/此军、字段非法、值不可解析、负值)单项被拒并记进 `rejection_reports`(turn/section/原始项/原因/类别/来源),好项照落,坏一项不再带走整批;代码异常(bug 类)仍上抛回滚。**拒收报告从此有内容**:支撑「哪个 section 最常被喂脏」聚合,事务内落 DB、提交成功后镜像 jsonl(可回收副本)。
- 拒收记录带来源标记(provenance):引擎推演路标 `system_simulation`、探针 driver 路标 `unknown`,随行落 DB+jsonl(按来源细分到玩家诏书/HITL 留后续波次)。

### 变更
- **值语义集中到落库层(applier)单点守门**:财政三段的 key 规范化(strip/多重后缀拒)、direction 中文同义词归一、无损整数串转换、display 默认派生全部收口到 `apply_score_extraction`,cleaner 只做无损 canonicalize 不再吞脏——引擎路与探针 driver 路对同一输入同判(此前两路两判)。
- **国策结案路保留历史容忍语义**:`_apply_issue_entities` 对历史上本就 raise 的脏项升级中断,对历史 print-skip/静默走默认的脏项容忍并留痕(issue_strict 按整项历史谓词分类),不把历史可活的脏数据变成新的崩月路。
- 抽出 `atomic_and_reload` 上下文管理器,收编结算管线 6 处重复的「事务 + 回滚后从 DB 重载 + 链式上抛」模式;回合相位比较统一走 `TurnPhase` 枚举(落库仍是 `.value` 字符串)。
- 错误包/拒收镜像在测试中隔离到临时 user-data 目录(conftest autouse),不再污染真实 `data/error_packs`。

### 修复
- 财政新立项存在性检查覆盖 base+rate 双键:`田赋_base`(田赋默认只有 rate 行)撞 PK 崩整月,改为逐项拒收。
- `_stem_of` 对多重后缀垃圾 key(`辽饷_base_base`)返非法标记而非归一——此前会让裁撤路误删真科目并清零各省实收(不可逆)。
- 空 key / falsy delta(`False`/`0.0`)不再被「无操作短路」吞掉无痕;`delta` 在场脏值显式拒。
- 结算中回滚后内存重载自身再失败时,原异常裸传播(不二次包成 SettlementAbort、不基于脏态写错误包)。

## [0.8.0.0] - 2026-06-11

### 新增
- **月末结算全有或全无(ADR 0008 PR1)**:回合后半段(落库、章节记忆、局势惯性、结局判定、推进回合)收进单一事务——中途崩溃/出错时整段回滚,存档不再出现"国库扣了但军队没建"式半写;事务层经自定义连接(`applier.atomic`)实现,期间内层 `commit` 暂停、`executescript` 拒绝、回滚后自动续开事务,杜绝第三方代码逃逸出事务。
- **结算可恢复**:邸报与 delta 推演结果在结算前持久化(`extracted_ready` 判别列区分"真结果/占位/失败"),崩溃或中止后重开游戏即可从断点续跑——已就绪的结果直接重放落库,不再花一次 LLM 重推演;推演结果损坏或缺失时自动退回重推演,旨意原文跨进程存活。
- **响亮中止 + 错误包**:推演产物不合契约(shape 垃圾、损坏 JSON)时不再静默吞掉,改为中止结算并落一份五件套诊断包(DB 快照/上下文/错误链/manifest/拒收记录,永不覆盖旧包),玩家收到带重试指引的明确报错;另提供"重新推演"逃生口,把坏结果降级为非就绪(保留邸报字段)而非删行,避免新软死锁。
- **拒收报告带出处**:落库被拒的条目(白名单外字段、坏值)记录 provenance,事务内落 DB、提交后镜像 JSONL,事后可审计哪个环节产了坏数据。
- **恢复窗口 UI**:web 端 settling 相位显示恢复横幅 + "续跑结算"按钮;CLI 在恢复入口打印操作指引('back' 给出恢复路径而非静默循环),零草案下也能恢复。

### 变更
- 结算前半段(固定财政、局势播种)自带事务并提交——中止重试时前半段效果保持已落,不重复扣账(设计明文,非缺陷)。
- 回合相位新增 `settling`,作为单一真源下沉到 `models.py`;恢复窗口内冻结改盘操作(下旨草案、撤回、跳过等 7 个入口),web 对应端点返回 409,聊天提案在源头被挡。
- 召对中的口头应允改为延迟提交:恢复窗口内不再即时 commit,统一并入结算事务,杜绝跨事务半写。
- 退朝(无旨推进)在前半段已完成时拒绝执行——结算欠账不可跳过,只能续跑或重新推演。
- 事务回滚后内存状态一律从 DB 重载(含 content 重建),杜绝"DB 回滚了但内存还记得"的幽灵状态。
- 探针 driver 的结算路径与真实流程对齐:同样在 pre_settle 后持久化推演上下文,重试语义一致。
- 恢复窗口冻结范围扩大(评审修):全部即时写聊天路径(任免落地、编外人物登记、密令房四类操作、CLI 前缀密令)与自然语言抽取的新暂存动作一并冻结;窗前已暂存的动作不受影响,仍随结算事务统一提交。

### 修复
- 探针 driver 此前每月固定财政流水在异常路径下静默蒸发——现与结算同事务,要么全落要么全回滚。
- 毒推演结果反复重放导致的永久软死锁(重放→失败→重放)被逃生口切断。
- HITL 暂停时三件状态(相位/草案/上下文)改为同一事务写入,中断不再留下互相矛盾的半套状态。
- settling 相位与恢复上下文(引擎占位/driver 重试真源)改为同一事务提交,引擎与探针 driver 同修——崩在两笔之间不再留下"相位已 settling 但无恢复上下文"的存档,玩家手改的旨意原文不再因此蒸发。
- CLI 恢复期局势分支收到守门拒绝时留在本回合交互循环,不再重进回合重印回合头。

## [0.7.2.0] - 2026-06-10

### 新增
- **三饷计火耗（spec v23，2026-06-10 拍板）**：火耗应派从「只派正赋」改为 `(正赋+三饷)×火耗率`，正赋/三饷分量另立——百姓实际负担与官绅截留不再被系统性低估；三饷分量随辽/剿/练饷时间线注入消长。
- 财政基座 spike 新增 golden：G22 三饷火耗分量、G22b 三饷=0 退化边界、G14b 正赋应征 None≡缺省、G14c 穷省 k=0.5 清丈（钉结算 k 缩放与 oracle 重放两侧）。

### 变更
- 火耗对账 oracle 同步改为正赋/三饷两分量独立重算后相加（与结算同分量式，防极端量级下浮点求和序差致对账漂移），两分量并显式写入结算结果（下游直接消费、不解析 stdout）；`官民田_o` 从开账+诏令独立重放（不再读清丈后的运行时税基）——清丈类「两侧同搬」篡账现在被债务+C 两层 oracle 当场咬死。
- 全部 value golden 钉死 `省库库银` 与 `官民田/隐田` 末态；raise-golden 升级为验证具体守门消息；spike FAIL 时退出码为 1（自动化不再假绿），`sys.exit` 收进 `__main__` guard（import 不杀进程）。

### 修复
- 开账负值校验补齐 CLAIM 四科目（负军饷欠经偿还环凭空生钱）。
- param/Due/开账库存的 NaN/inf 入口拦截（NaN 军饷 Due 原可把整个资金池静默付空且五层断言全过）。
- Due 科目白名单（拼错科目原会让法定支出静默蒸发）；action 缺 type/非数值字段改为干净报错。
- 支付池透支 fail-loud + 浮点尘埃清零；`正赋应征=None` 语义钉死（视为缺省走亩额派生，其余参数拒 None）。
- 必填参数（三饷应征/火耗率/逋赋率/起运定额/Due）缺失改为干净报错而非 KeyError——不给默认 0（火耗率缺省成 0 = 静默改经济学）；开账 stock 为 None 前置拦截；率值/param/Due/开账全面型别守门（字符串/bool 原走半程 TypeError，bool 是 int 子类须显式拒）（G21t–w）。

### 移除
- spike 中只写不读的 Cin/Cout 流水字典（v13 同源对账残留）。

## [0.7.1.0] - 2026-06-10

### 新增
- **任免纳入聊天动作闸门(ADR 0006 三类全做)**：CLI 召对里口头任免(任命/升迁/调任/罢免/纳妃)走**独立检测** `extract_appointment_action`(与密令的 `extract_minister_actions` 不混)、随召对触发不挂密令 gate、覆盖大臣 + 太监、作用域=当前召对的大臣。暂存为 `kind=office`,颁诏 `commit_pending_actions` 透传 `content/registry` 落库。

### 变更
- **确认闸门由「颁诏批量同意 + UI 撤回面板」改为「对话确认」**：大臣(太监)in-character 领命复述;皇帝下一句**应允 → 当场 commit**该召对大臣暂存、**拒绝 → 丢**、不回 → 留、颁诏对没回的算同意。新增 `extract_confirmation_intent`,commit/drop 按 `minister_name` 过滤。
- **任免落地核归一**:抽出 `issues.apply_office_appointment` 作【唯一落地核】(在册且未死→改 active+授官+顶替去重+`office_type` 重算+内存/registry 同步;不在册→建档;dead/空 office 拒),**extractor 的 `office_changes` 与 CLI 任免 commit 共用**,杜绝两份会漂的实现;罢免加 ming-guard + alias + active 校验。
- minister prompt 加「in-character 领命并补充信息和要点」(后宫走 consort_agent 自有领命)。

### 修复
- `_displace_duplicate_offices` 剔除官员一个独占分项后,保留官职的 `office_type` 随之重算并同步 DB+内存(原只改 office、留陈旧 type,大臣 agent 按错类型建身份/工具)。

### 移除
- 拆掉自造的「待颁诏」前端确认 UI:`PendingActionsModal` + 顶部浮窗(`.pending-actions-fab`)+ pending 角标 + 撤回按钮 + 相关 state/type(确认改对话驱动;后端 `pending_actions` 表/暂存基建保留)。

## [0.7.0.0] - 2026-06-09

### 新增
- **聊天动作闸门(ADR 0006)**：CLI 后端召对里 LLM 从自然语言**推断**出的密令写动作(更新/催办/提交核议/记进展)与后宫调教,不再在召对当场直写真实表,改进 `pending_actions` 暂存表;颁诏时(`pre_settle` 最前 / 退朝 `advance_without_edict`)`commit_pending_actions` 在结算管线前批量落库(不拒绝即允许)。暂存行纳入召对 rollback(撤回召对一并删),落不了的标 `failed` 不留孤儿,commit 抛错被兜住不崩结算。**根治**:闲聊被判「更新密令」当场静默改既有密令 + 续期 + 谎报「已交付」(handoff 计划里 slice 4「action-gate」一直没实现)。
- **皇帝复核区**：`GET /api/pending_actions` + `POST /api/pending_actions/{id}/withdraw`(不存在 404 / 已落库或非本回合 409);前端「待颁诏」复核面板(列本回合暂存动作 + 逐条撤回)+ 顶部入口浮窗 + 召对暂存反馈提示(取代旧「密令已秘密交付」对更新动作的谎报)。

### 变更
- 流式与非流式召对路径共用 `apply_cli_conversation_actions` + 同样回传 `pending_action_id`,不漂移。
- 拟旨与「密令如下/拟旨如下」显式前缀按钮 = 玩家明示,仍直接落库,不入闸门(认可例外)。任命走 agno tool-call(api 通道)不在本片(ADR 0002 更大范围)。

## [0.6.1.0] - 2026-06-09

### 新增
- **游戏内 LLM 执行通道选择**：局中设置面板(gameMenu)新增 API / CLI 通道选择器 + CLI runner/model/超时输入。CLI 局开局后改设置不再被强制降级到 API、不再因空 key 误报；显式选 CLI 即可脱 key 续跑(#51)。

### 修复
- **真实流落库二级类型校验**：`validate_delta_shape` 抽成单一真源(`ming_sim.issues`),`apply_score_extraction` 落库前先校验容器/实体二级 dict 类型,畸形 delta 不再在 apply 内部「前字段落库、后字段崩」半落库;driver 仍在 pre_settle 前校验(#57)。
- **探针 driver 纯确定性**：driver 注入 channel=api 确定性配置,即便设了 `MING_SIM_LLM_BACKEND` 也不再 spawn legacy CLI enrichment(ADR-0004:dialogue-Claude 已自产完整 delta)(#54)。
- **CLI 空 cli_model 不漏 API model 名**:补 for_role/advanced 路径回归覆盖(RT2 已修工厂)(#52)。
- **runtime_llm.json 数值类型一致**:`_api_runtime_slot` 类型感知,preserve/fresh/load 三路 max_tokens(int)/timeout(float)同型(#53)。
- **in-game 设置 verify offload**:`api_set_llm_config` 把 LLM 连通性 verify(CLI smoke ~12s,只读)offload 到线程不卡 UI;commit(改 session 态)留在 event loop 同步跑(单人 CLI 串行探针下原子无 race)(#56)。
- `is_real_api_key` 拦截 `__keep__` sentinel,不当真 key(Red Team)。

### 修复(ship-pre 跨厂 CMR 续轮)
- **落库二级类型校验补全**:`_NESTED_DICT_FIELDS` 收敛为 `{region_delta, army_delta, power_updates}`(这三者 apply 逐 entity 写、坏项中途崩=部分已落库),faction/class 排除(apply 各自容忍旧扁平 int / 静默跳);所有 list 字段补「项必须是 dict」校验;None 字段容忍(与 apply `or {}` 一致)。
- **通道切换不丢 key**:`commit_llm_config` 对 CLI 通道 preserve/seed api 槽真实 key——已存槽有 key 则 preserve_api 保留;槽空但当前 session(可能来自 `OPENAI_API_KEY` env)有真实 key 则写进槽。api→cli→api 往返不丢 key。
- **配置 verify 失败不半写**:`api_set_llm_config` 加 `except HTTPException` 透传,verify 失败的干净 detail 不被二次包裹;失败时绝不 commit。
- **gameMenu CLI 字段从已存槽初始化**:用 persisted CLI 槽(`??` 容忍显式空)初始化,API 会话下不把 env 兜底的 API model 名当 cli_model 回传。

### 变更
- **单一真源收口**：`VALID_CHANNELS`、`CLI_DEFAULT_TIMEOUT_SECONDS`、`CODEX_DEFAULT_MODEL`/`CLAUDE_DEFAULT_MODEL` 常量化,替换散落字面量(#55)。
- `apply_llm_config` 拆成 `build_llm_config`(纯派生)/ `commit_llm_config`(落盘+重建)/ `apply_llm_config`(同步组合),支持 verify 与 commit 分离。

## [0.6.0.0] - 2026-06-09

### 新增
- **LLM 执行通道：API / CLI 并行、channel-aware**。`runtime_llm.json` 增双通道槽位（api / cli），`LLMConfig` 带 `channel` + `cli_runner`/`cli_model`/`cli_timeout_seconds`；readiness、模型构造、office 推断与落库 enrichment 全按当前 active channel 判定。脱-key 也能从菜单选 CLI 通道跑（`ApiSettingsModal` 加 channel 选择器）。`cli_backend_active(llm_config)` 单一真源门控 issue/office 的通道感知 enrichment。
- 单一真源 `llm_config.is_real_api_key` + `real_api_key_or_empty` + `CLI_BACKEND_PLACEHOLDER`：占位符只在 `create_chat_model` 构造 CliChat 那一刻注入，`LLMConfig.api_key` 对 CLI 通道永空；手动 key 输入口（getpass / 菜单 request / 局中 request）统一过滤占位符。`web_app._has_real_api_key` 委托同一真源。
- 架构决策记录：ADR 0001（API/CLI 双通道并行保留）、ADR 0002（用 action candidates 而非 tool-call 作游戏规则）。

### 变更
- `settle_with_delta` 增 `delta_applier` 注入闭包（与 `chapter_recorder`/`ending_summarizer` 同构）：merge base 的 ADR-0004 结算重构后，真实流经此闭包把 llm_config 送回落库 enrichment，结算核本体仍不依赖 llm_config；driver 默认 None 走确定性 apply（设 `MING_SIM_LLM_BACKEND` 时仍按 legacy env 判定）。

### 修复（pre-landing review）
- 显式 CLI 通道 `cli_model` 为空时不再把 API model 名（`llm_config.model`）当 `--model` 漏给 codex/claude，改回落 runner 默认（`cli_model_from_env`，agy 无 `--model` 故空）。
- 菜单 LLM 保存端点（`api_menu_save_llm` / `_menu_save_cli_llm`）的 verify smoke（CLI 子进程最长 `cli_timeout_seconds`）改经 `run_in_executor` offload，不再阻塞 asyncio event loop 卡住并发请求。
- 补测：`verify_llm_available` legacy env-only smoke 路径、`CliChat._call_cli` 未知 backend 兜底。

## [0.5.2] - 2026-06-08

### 修复
- 探针 driver `run_settle` 堵两处静默吞(codex 对抗 review）：falsy 非 dict 的 delta（`[]`/`""`/`0`）不再被 `or {}` 吞成空结算照样推进；未知顶层字段（拼写错如 `地区变更`↔`地区变化`）不再静默无效落库——两者结算前响亮报错、回合不半推进。

### 变更
- `docs/TODO.md` 移到根目录 `TODOS.md`（与 gstack 约定一致），标记城防炮(#4)/driver(#10)完成移入修复记录；CLAUDE.md 工作手册引用同步。

## [0.5.1] - 2026-06-08

### 新增
- **确定性结算核**：从 `decree.py` 抽出 `pre_settle`（固定财政 tick + auto_trigger）与 `settle_with_delta`（apply→turn_logs→章节记忆→inertia→clear→结局判定→next_period）。真实流程 `_settle_after_narrative`/`resolve_directives` 改调新核，behavior-preserving；章节记忆/结局总评做注入回调，使核不依赖 `llm_config`。真实流程与探针 driver 共用同一结算核（见 ADR 0004）。
- **探针 driver（`driver.py`）**：`state`（盘面快照）/ `settle --delta <json>`（注入我产的中文 schema delta 跑确定性结算、推进一回合）/ `dump`（地区快照）。`run_settle` 规范化中文 key→英文 canonical 并按 schema 校验各字段容器类型（畸形值结算前响亮报错、不半落库），落 narrative 到 turn_reports + canonical delta JSON 到 turn_extractions（供 replay/timeline 重建）；CLI `settle` 支持信封 `{narrative, decree_text, delta}`（裸 delta 兼容）。
- **城防炮 `region.cannon` delta 落库路径**：`地区变化` 新增 `城防炮` 字段，`apply_region_deltas` 特判路由到 `apply_region_cannon`（复用 `city_level×8` clamp，在白名单检查前），与军队 `随军大炮`（`cannon_equipment`）分域。

### 变更
- 城防炮补入 `REGION_FIELD_LABELS`（turn 日志显示「城防炮」而非回退英文 cannon）。
- CLAUDE.md「结算编排骨架」改述：driver 复用 `pre_settle`/`settle_with_delta`，不再自行复刻结算链（ADR 0004）。
- 新增架构决策记录：ADR 0003（人物相关 delta 合并为单 key + 显式动作意图，实现 deferred）、ADR 0004（探针 driver 复用引擎结算核）。

### 修复
- `db.py` 漏 import `LLMContractError` → 任何非法 `region_delta` 字段曾崩 `NameError`，现正确抛契约错（报清楚的合法字段清单）。
- 探针 driver 对畸形 delta（信封 `delta` 非 object、模块值容器类型不符）一律在动 DB 前响亮报错，不静默吞成空 delta 照样推进回合。

## [0.5.0] - 2026-06-08

### 新增
- **事件记忆系统**：每回合结算后自动提炼记忆卡，按人物/派系/官职类型建索引；大臣召见时注入「旧事记忆」块，上限5条，对话前后贯通。支持规则提取（`record_event_memories_from_resolution`）与 LLM 提取（`memory_extractor` agent）两条路径；每科目保留最近3条，超出自动剪枝。
- **推演记忆注入**：结算链新增 step 1.8——`memory_retrieval` agent 从本月诏书提取人名/地区/军队/势力/关键词（含可选 year/period），按 tags LIKE 匹配召回相关历史记忆（≤10条），注入 `season_simulator` 与 `score_extractor` payload；两个 prompt 同步说明字段含义与使用方式。
- **记忆自动衰减**：写入时按 importance 设 `expires_turn` TTL（importance 1→6回合、2→12、3→24、4→48、5→永久）；查询默认过滤过期记录，按年月查时可 `ignore_expiry=True` 追溯历史档案。
- **大臣按时间回忆**：新增 tool `recall_memories_by_time(year, period, keywords)`——时间查（精确该月，ignore_expiry）与关键词查（当前有效期内）合并去重返回；`memory-recall` skill 说明同步更新。
- **DB 索引**：`event_memories` 新增 `idx_event_memories_expiry(expires_turn, turn)` 加速过期过滤；`get_memories_by_keywords` 支持 `ignore_expiry` 参数。
- 后宫妃嫔卡片支持上传本机图片作专属立绘，存 `data/uploads/`，记入 `portrait_id`，重启后自动复用（`POST/DELETE/GET /api/consorts/{name}/portrait`）。
- 立绘工具脚本：`gen_portraits.py`（调生图接口出图）、`compress_portraits.py`（缩 512 压体积）、`portrait_status.py`（进度表）；附后宫预设图池与寝宫背景图。
- **军备两轴 + 城防（玩法机制）**：军队新增 `火器`（火器装备 0-100：鸟铳/三眼铳，野战+守城）与 `随军大炮`（随军红夷炮门数 0-12，攻坚利器但不利野战机动）；地区新增 `城市等级`（0-5 静态史实分级，京师 5）与 `城防炮`（城头红夷炮，上限 = 城市等级×8）。判战永远由 LLM 软判，引擎只 clamp 不算胜负。全层贯通（DB/extractor prompt/军表/大臣 inspect）。
- **CLI 后端探针（脱 api key）**：游戏可不依赖商业 api key 运行——LLM 后端在单一咽喉点改走本机 `agy`(默认)/`codex`/`claude` CLI（`MING_SIM_LLM_BACKEND=agy|codex|claude`），纯 subprocess，机器本地。补齐无 function-calling 带来的 toolcall 缺口（拟旨/密令入档、会话动作、地区/建筑 context 注入、国策实体后果补全）。详见 `docs/CHANGELOG_cli_backend.md`。

### 变更
- **推演 agent（season_simulator）改 skill+tool 模式**：不再把全量盘面静态塞入 payload；挂 10 个只读工具（`view_state`/`check_treasury`/`list_regions`/`inspect_region`/`list_armies`/`inspect_army`/`list_issues`/`inspect_issue`/`list_external_powers` + `submit_report`），按需查盘面，写完邸报调 `submit_report` 提交正文；`submit_report` docstring 承载完整奏章写作规范（结构/笔法/局势/末章/禁忌），`season_simulator.md` 从 141 行精简至 54 行。
- **结算 agent（score_extractor）改 skill+tool 模式**：payload 去掉 regions/armies/buildings/ministers 五张全表，只保留 narrative + issues摘要 + id列表 + fiscal_config；挂 7 个工具（`get_region`/`get_army`/`get_external_power`/`get_active_ministers`/`get_issue_detail`/`get_faction_class_state` + `submit_extraction`），按章节按需查当前值算 delta；`submit_extraction` docstring 承载完整 JSON schema、16 字段约束、档位标准与骨架示例，`score_extractor.md` 从 266 行精简至 50 行；去掉 `force_json_output`，改由 tool docstring 约束格式。
- **CLI 后端会话落地收敛单一真源**：`session.apply_cli_conversation_actions` 同时供命令行（`session.chat`）与 web 流式路径调用，杜绝两边逻辑漂移；官职分类改走 `content/offices.json` 参考表（替代旧正则词表），无 CLI 后端时落「待铨」graceful。
- **国策实体后果三结案路径对齐**：issue 经 tracker advance / close / 自然惯性（inertia）任一方式结案，都落 `effect_on_resolve/fail` 的建军/补兵/人物状态/帝国修正，不再只有部分路径生效。

### 修复
- 密令「更新」按精确 id 改对应那条（多条 active 时不再改错条），更新不清空原标签；催办对 pending_review 不抛错。
- CLI runner（agy/codex/claude）检查退出码/空输出即抛错，不把 auth/quota 失败当空回复或角色文本落库。
- 落库守门：国策效果字段非 dict 不再崩整月结算；`apply_score_extraction` 非法 delta 严格抛错不静默丢；CLI 后端国策保底有回报，绝不入空壳。
- 火器/随军大炮新档贯通（fresh seed 不再全 0），动态新建军可按 id/名查详情。

## [2026-05-24]

### 新增
- 后宫系统：打通选妃流程，司礼监从秀女池遴选候选呈选、降诏册封入宫；调教 tool 提权，妃嫔学技艺/改性子写入永久记忆；修复 candidate 升格。
- 人物据实奏对：大臣与月末邸报按在朝名册查现职状态，不再凭史实记忆乱报官职；朝堂名册按官品排序。

### 修复
- 财政：`economy_moves` 的 account 按钱实际出自哪库判定，不再按用途误判。

### 文档
- README 重写「已实现」为分模块表格；补后宫、省级财政、月度收支、人物头像等说明。
- 立绘提示词改现代古风；新增 GPL-3.0 许可证。

## [2026-05-23]

### 新增
- extractor：支持人事任命与人物状态变更落库；开局校准到 1627.10。
- 网页结算悬浮框加「本月一次性入账」段；建筑支出改走内库。

### 变更
- 推演重构：叙事零数值化，extractor 按章节扫描，prompt 瘦身。

## [2026-05-22]

### 新增
- 建筑系统：御窑厂/边堡/仓储/工坊/河工，等级状态维护产出按月落账，新建须立项推进；推演 token 优化与遥测。
- 网页地图节点重定位与取点工具；菜单改中央弹窗。

### 文档
- README 加游戏截图与头图。

### 杂项
- 移除 `.vscode` 出版本管理。

## [2026-05-22] — 首次公开发布

晚明对话式政略模拟器初版：月度回合制、大臣召见与拟旨、诏令结算、月末邸报、两京十三省与军队/外部势力盘面、CLI 与网页双端、本地存档、内容外置。
