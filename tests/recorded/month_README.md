# 月推进边界录音

## #1978 契约迁移（确定性输入，不冒充新录音）

场景录件中的 `read_person(name)` 调用改为 `read_records(kind=person, key=...)`；工具返回仍由当前生产链现场取得。`account_dossiers.json` 的专用人物账户包退役，账户权限由 `test_web.assert_record_queries` 的统一工具案覆盖。

`month_force.txt`、`month_provincial_county.txt`、`month_two_payments_{combined,split}.txt`、`month_interim_{approved,rejected}.json` 的量表输入改为增减，原稿最终值减去开局量表值；这是人工迁移的结构化测试输入，不再声称这些量表字段是原生模型输出。其余文字保留，原生卷仍以以下归档为真源。`month_secret_appointment.json` 是本票的确定性密令任命输入，不是录音。

这些变更不作为真实宿主效果证据；合并后的北极星由调用者另验。

## #1972 逐笔钱粮、统一查询与接不住提示（2026-10-25）

- `month_two_payments_combined.txt`、`month_two_payments_split.txt`：`~/WorkSpace/vault/ak-cc-wiki/raw/ming-llm-runner/2026-10-24/1972/trial-1/001-process`、`002-process` 的最终原生回话，不改字；合写、拆写经同一 HTTP 过月链对照。
- `month_provincial_county.txt`：同根 `2026-10-24/1965-acceptance/run-ambiguous/pi-232512/017-Declaration/stdout.jsonl` 的最终原话；带省县名不再需要退回。
- `declarations_1972.json`：真源见 `source`／`source_by_case`（`2026-10-25/1972-implementation/native*`），生产 schema、校验与工具，pi `openai-codex/gpt-6.1-sol` 逐次调用。错误案按故意错误指示录制，保持原样。工具调用只去 `mcp__court__` transport 前缀，参数、ID、正文不动；不回放工具返回值。初录的空 capture、未按指示交错例、未发生退回的样本留在证据目录，没有拿来冒充通过。
- `read_catalogues` 已退役；旧 `appointments.json` 的原始回复仍用于任免，未使用的旧工具回合 `responses` 已删除。新查询录件从收夜、过月两个 HTTP 入口验证同一个 `read_records`，转译仅两表、无历史；其他身份维持原权限。以下 #1965 段落描述当时录制历史，不代表现行工具。
- 属地只补开局数据：采用「本条 region 对应的省名＋原正名」，不猜配父级；1356 个县州补带省别名，74 个正名已带省；河南府、云南府不是省级前缀，照府级正名写「河南河南府…」「云南云南府…」。辽东两州正名已含辽东都司，不另强加省名。此前误接父级形成的错误别名已撤回，原条目出处保留，无运行时补名算法。

## #1965 J3 边镇收窄（2026-10-24）

陛下 `deb03fe0-2afa-457f-9e9c-33a12b130cf4` 改定卫所仅收边镇有设官者，撤销上一轮全国历史卫所目录口径。
`border_appointments.json` 来自本机 Claude CLI 逐次 `haiku --json-schema`，原输入、schema、原生回话见其 `source`；合成任命场景、真实模型转译，不冒充史实或完整 runner。
在原任免 HTTP 测试内替代旧 `wei` 正向分支，并顺序验证旧称替任、军卫与驻镇辖区分立、高山卫/所及天成/镇虏各自独立；不增加平行测试。
`cabinet_wei.json` 只供首辅与财政错误案；已删除其中退役的全国卫所 `wei` 案，其余各案原样保留。删前完整录件归档于本票证据根 `fixer-b1/cabinet_wei-before.json`，原生回话仍见 `fixer-j1-j6/declarations-native.json`。两份在用录件直接合并读取，没有同名案覆盖。
首录宁远未限定地域，真实入口报多候选；原卷与诊断保留于 `fixer-j3-border/record-native.json`、`initial-recording/`。施工自审撤销了仅凭同城合并军卫与辖区的尝试（`withdrawn-same-city-merge-preview.json`）；最终在 `explicit-recording/` 以司属全名“辽东都司宁远卫”真录，不给匹配加优先级。
证据根仍为本票归档的 `fixer-j3-border/`；删除项按新裁以后实际用到再补，不靠放宽匹配或新增官地组合限制变绿。

## #1965 J1–J6 送修（2026-10-24）

归档为本票证据根的 `fixer-j1-j6/`。`cabinet_wei.json` 保留本机 Claude CLI 逐次 `haiku --json-schema` 原生 `structured_output` 中仍在用的首辅与财政错误案；输入、schema 与 session 在 `source` 指向的三份原卷中。各案独立转写已发生的任免与故意错误；退役的 `wei` 案已移出仓内夹具，其原记录留在上述原卷及 `fixer-b1/cabinet_wei-before.json`。在用各案回话不改，`chief_join` 正文中的异文也原样保留。首辅案供原任免 HTTP 测试的连续分支，财政案供既有拒收参数，不新建平行测试。

`account_dossiers.json` 来自生产 `Audience` 的本机 Claude CLI 逐次 `sonnet`；原生 JSONL 为 `dossiers-v2-native.jsonl`。仅去 MCP 工具名前缀，参数、工具调用 ID、最终文字原样保留；Pydantic 消息信封时间是导入时间，不冒充原生元数据。重放在真实 `read_person` 上取当前档案，不重放工具返回值。首份 `dossiers-native.json` 只有宿主最终文本，缺原生工具调用，不用作夹具；原失败取证保留。

首辅出阁、同份先入阁后任首辅、双缺位、非阁臣重交、跨地区卫所任命，以及所有账户名称和新库按月入账，均在已有 HTTP → CLI audit / 场景工具返回的结构化断言上验证。不锁正文措辞，不把录件当作历史正确性的证明。

## #1965 御史台重交（2026-10-24）

证据在下述归档根的 `r2/`：`appointments.json` 按当前 NightDeclaration 重录，
源输入、定稿 schema 与原生回话见夹具 `source` 指针。`record-appointments.py` 的输入明写“增任，原阁臣全部留任”，
并录出 `西安知府` / `西安府知府` 的两次先后任职与 `大同巡抚`；不是手改 holders。
第一份新录未带员额，且把户部尚书写为两人，留在 `appointments-live/`，未用于夹具；
补齐实际目录的员额后再录 `appointments-retry-live/`，得到合法草稿。最终夹具采用
`live-catalogue-lookup-final/` 中生产 `Court.translation_agent` 的原生 `read_catalogues` 调用及最终回话，
保留工具参数、call id 与正文，仅去 MCP transport 前缀；重放也走真实两表查询。
测试里恢复了查无背书人及旨意 people 单项查无两条负向案，均由既有真回复改一个引用字段，不改被测行为。
五份旧 northstar/r2 孤儿录件移至 `r2/retired-recordings/`，路径记入 `artifact-relocation.json`。
静态两表由转译的原生 `read_catalogues` 工具在需要时供给，不再写进每次世界实况与名册提示两遍；
审计读仍保留完整账本，世界按 kind 显式查目录仍可读，普通全量世界读不夹带目录。

## #1965 官职、知情与单笔钱粮迁移（2026-10-24）

归档根：`~/WorkSpace/vault/ak-cc-wiki/raw/ming-llm-runner/2026-10-24/1965/`。
`artifact-relocation.json` 将旧临时路径映射到永久归档；原输入、原生响应、SQLite 与失败卷均保留。
夹具的 `source` / `translation_source` 是各份录制的具体指针，不用本表替代原卷。

| 夹具 | 归档内真源 | 边界 |
| --- | --- | --- |
| `appointments.json`、`appointments_replace_aliases.json` | `ming-1965-record.py`、`ming-1965-alias-v3/`；各夹具 session 指针 | 多职、替任、免职、起复与正名别名 |
| `appointment_dossiers.json` | `ming-1965-knowledge/` | 真 CLI 工具往返；档案当前任职及知情账 |
| `declarations_v9.json` | `source_by_case`；`ming-1965-ordering-translations/unknown_incumbency_report.json` | 新建限制、引用、缺必需项；故意错误输入不修成成功样本 |
| `month_money_once_*.json` | `ming-1965-money-record.py`；夹具内 session / input | 每笔只声明付方，收入与奏报保留原数 |
| `range_v9.json` | `ming-1965-range-record.py`；夹具内 session / input | 越界值夹范围，不拒收 |
| `night_new_office.json` | `ming-1965-F2-live/` | 原皇帝话重录，杨嗣昌任户部右侍郎且保留兼职 |
| `endorsed_dossier.json` | `ming-1965-host.1X28rM/` | 担过名者再查档，真实 read_person 工具回复 |
| `night_tools.json` | `ming-1965-tools-live/` | 所在地准入、整次失败与批准时知情 |
| `night_secret.json` | `ming-1965-secret-live/` | 王绍徽在京旁听，不把山西韩爌搬到京师；7轮原生响应 |
| `night_ordering.json` | `ming-1965-ordering-now-live/`、`ming-1965-ordering-now-translations/` | 公旨先于密旨，本月生效的两次任命 |
| `sources_vacancy.json`、`sources_appointment.json` | `officials-current-live/`、`import-current-officials.py` | 按含李国普的现开局重新真跑全阁免职、曹化淳补任；没有手补免职项 |
| `month_fiscal_1631.json`、`month_fiscal_1640.json`、`month_fiscal_reject.txt` | `ming-1965-fiscal-v9/` | 冻结推演重新转译，不把 source 元数据登记成模型步骤 |
| `month_force.txt`、`month_travel.txt` | `remaining-consumers/*.input.json`、`*.native.json` | 旧实况原文按新契约重译，非新一次完整推演；导入结构与原生 structured_output 一致 |
| `night_interim.json` 的 `replies` | `interim-v2/`、`interim-v3/` | 原四轮整夜重新转译；首次把御笔写为皇帝，HTTP 原生校验反馈后重交，两份回话都保留 |

原生 MCP 工具仅去 `mcp__court__` 前缀，参数、ID、文字原样入 Pydantic 消息信封。
新的秘密录音没有旧版两条 handled 事件，不为维持旧累计分数补造事件。
旅行测试按山东毕自严（1月）与上海徐光启（1.6月）的开局距离分别验抵京，不能沿用旧版两人皆南京的前置。
部分沿用戏文仍误称毕自严在南京、徐光启原任礼部右少卿；这不是开局事实。新旅行转译明确读取当前所在地及真实原官，未为旧戏文放宽校验。
`interim-current` 是未采用的首卷（turn=3、仅毕自严背书），未将其洗成正确成旨记录。`interim-v2` 显式携带原轮次序号后录出 turn=4，但把御笔写成皇帝；`interim-v3` 将同一原夜、原始错误回复与 HTTP 返回的四键校验反馈照传，录得 turn=4、毕自严及御笔两条背书。没有手补或改写任何模型字段。
退役的镜像拨款 `.txt` 与三个未使用任免/支付录件移至 `retired-recordings/`，不再参与测试；旧声明未就地手改。
F1 单人/双人背书档案、F2 任职后过月沿用 HTTP 行为测试，只有模型边界替换。
全量及完整北极星真跑仍由家族最终待合并状态的调用者 / CI 执行。

## #1951 月推进边界录音

确定性测试走 HTTP `/actions`、CLI `read`；仅通过原生 `Agent.override`
替换外部模型。Agent、工具、结构重交、分派及 SQLite 落账仍走生产链路。
断言只看结构化结果，不约束戏文、奏疏或邸报措辞。

2026-10-21 施工录音归档：
`~/WorkSpace/vault/ak-cc-wiki/raw/ming-llm-runner/2026-10-21/issue-1951-implementation/`。
每次模型调用保存输入、Pydantic AI 原生 messages 和输出；SQLite 存档与驱动日志另存。
新 `.txt` 从原生 `ModelResponse.text` 原样取出，不改回复内容，不手补字段。
`haiku` / `sonnet` 是本机 Claude CLI 的逐次模型旗，不改宿主或席位配置。

| 夹具 | 归档内真源 | 用途 |
| --- | --- | --- |
| `deliberation.txt` | `1951-A/009-deliberation-messages.json` | 结构化准行判词 |
| `deliberation_rejected.txt` | `1951-transfer-3200000/005-deliberation-messages.json` | 结构化封驳判词 |
| `deliberation_vital.txt` | `1951-vital/001-deliberation-messages.json` | 命门（迁都）中旨亦不可颁判词 |
| `simulation.txt` | `1951-world/003-simulation-messages.json` | 月底、零奏疏 |
| `month_petition.txt` | `1951-transfer-3200000/006-simulation-messages.json` | 一道月中岔路 |
| `month_multiple_petitions.txt` | `1951-world/001-simulation-messages.json` | 同段多道独立岔路 |
| `month_deferred.txt` | `1951-world/002-simulation-messages.json` | 月底奏疏留到下月，不预推 |
| `month_force.txt` | `1951-B-full/052-Declaration-messages.json` | 强颁后皇威、满意度及赈银字段 |
| `month_travel.txt` | `1951-B-sonnet/014-Declaration-messages.json` | 毕自严、徐光启启程 |
| `night_travel.json` | `1951-B-sonnet/001`–`006` 的原生 messages；`1951-B-words.json` | 五轮原话与整夜声明；用原生 adapter 序列化，无改写 |
| `night_empty.txt` | `1951-transfer-300000/004-NightDeclaration-messages.json` | 无成旨的一夜 |
| `travel_admission.json` | `1951-admit2/set_hall-inputs.json`、`1-scene-messages.json` | 真实 MCP 调用的原参数和场景回复 |
| `month_zero.txt` | `1951-extra/zero-messages.json` | 补充真实模型调用：月初零奏疏、尚未月底，验证自动续写 |
| `month_money_*.txt` | `1951-translations/*-messages.json` | 补充转译边界录音：30万、320万、500万及官员奏报 |

MCP 调用不在 CLI 的 Pydantic 消息文本中。`travel_admission.json` 的工具参数
在真实 `Court.set_hall` 调用时观察记录，按 `ToolCallPart` 契约装入重放信封；
信封的 call id/时间不是原 MCP 元数据。参数及最终模型回复均未改，测试仍调用真实工具。

补充录音不是另一次完整北极星：零奏疏例通过生产推演 Agent 发出月初场景输入；
金额例通过生产 `Court.translate` 转译同额拨款，输入原文也在归档。
HTTP 新开局真跑见 `1951-A`、`1951-B-full`；两者均推进至 1627 年十二月。
A 沿原主线、末尾显式加“准。”，未调用原 runner 的逐步准旨判断，不冒称逐步一致验收；
`1951-A-full`、B-full 均从原 driver 取输入、用真实模型逐轮判断是否补“准。”。
A-full 也推进至十二月，但原场景仍停在询问，整夜译出零道成旨，不能称为 A 成旨验收成功。
`1951-B-sonnet` 是补充召还/旅行存档，包含一次真实 CLI 失败及随后显式重试，
并非一条无失败的验收记录。`1951-postforce` 续档议旨读取皇威新档位；`1951-withdraw` 续档实跑撤旨及罢差，
推进至 1628 年正月。撤旨转译夹带另一道罢差事实，并将退银对手写为内库；
原卷照存，不将模型语义偏差抹成全通过。完整北极星的家族最终状态复验仍由父票 runner 执行。

## 沿用的错误与空声明录音

`month_empty.txt`、`month_invalid.txt` 保留 #1948 的原始模型回复；
前者来自 Claude Haiku，后者来自 DeepSeek 的未使用 typed output 错误回复。
不把缺字段、错误 changes 形状修成有效声明。

`deliberation_invalid.txt`、`simulation_invalid.txt` 是 #1956 的原始非结构化回复
（本票起点 `bf198d143` 的同名旧文件），用于正式交结构重交用尽后停住、可重试的路径。
`gazette.txt` 仍为 #1956 原始公开邸报回复，含其编辑附言。
原卷为 `2026-10-20/northstar-accept/A/saves/df549bf5-99de-4fff-8182-6516f929f1ce.errors.log`。
这些旧回复仅作原样错误/文本边界材料，不伪称本票的新形状录音。

## 急务与派系弹劾（#1954）

2026-10-22 开发真跑归档：
`~/.ak-roles/books/Ming_LLM/1954/runs/01a163ab-f6f8-74de-ae87-0e9162ba9a17@coder/evidence/`。
使用本机 Claude CLI 的逐次 `haiku` / `sonnet`，未改宿主或席位配置。
`1954-record.py` 从 `Game.command` 进入完整生产月推进；`1954-cases.py` 仅对目标来源真调模型，其他来源用录样，以开发指令要求错误输出来观察重交耗尽。录音本身不是运行依赖。

| 夹具 | 归档内真源 |
| --- | --- |
| `sources_urgent.txt` | `1954-live/004-urgent-messages.json` |
| `sources_impeachment.txt` | `1954-live/005-impeachment-messages.json` |
| `sources_empty.txt` | `1954-cases/empty/004-urgent-messages.json` |
| `sources_*-name.json`、`sources_*-structure.json` | `1954-cases/<同名 case>/` 的目标来源 messages；两次完整回复原样取出，不修字段 |
| `sources_vacancy.json` | `scenes`、`words` 同 `1954-vacancy/001-scene`、`002-scene` messages 与 `state.json`；`declaration` 为合并 #1952 后重录，`~/.ak-roles/books/Ming_LLM/1952/artifacts/merge-1955-rerecord-sources/` `run/001-NightDeclaration-replies.json` |
| `sources_appointment.json` | `scenes`、`words` 同 `1954-appointment/001-scene`、`002-scene` messages 与 `state.json`；`declaration` 为 `~/.ak-roles/books/Ming_LLM/1952/artifacts/merge-1955-rerecord-sources/` `run/002-NightDeclaration-replies.json`；`landing` 为补任月月末本旨，`landing-r2/001-Declaration-replies.json` |
| `sources_revision.txt` | `1954-appointment/014-urgent-messages.json` 的完整 `ModelResponse.text`，包含曹化淳改票及原案引用 |

`1954-resume` 是选发回后的下月改票；`1954-retry` 是双缺位后无急务、原案搁置；`1954-appointment` 是曹化淳补任后按原案 id 改票。
初次 vacancy 录制器嵌套 `capture_run_messages` 干扰转译错误处理，留下 `IndexError`；去掉外层 capture 后在同一存档重试成功，原失败卷保留，不算生产来源的失败证据。
`1954-recovery-cases/*/state.json` 与 `recovered.json` 是两类来源坏正名、坏结构停住及仅补失败来源的真跑。
`1954-consequences` 与 `1954-consequences-sonnet` 曾漏落奏疏的派系、去留字段：转译范围将奏疏处置误排作另份圣旨。明确只排除 `others` 后，`1954-effects/002-Declaration-output.json` 与最终存档记有皇威、派系满意度及人物去留字段，推进到 1628 年五月。
缺位测试的补任阶段原样重放 `sources_revision.txt`：正确例只在初始月的奏疏构造处对齐 `source=urgent、ordinal=0` 这一原案的生成 ID，再交给真实 `PendingPetition` 构造器，使其 id 对齐录音的 revision_of；不按并发调用次序分配 UUID，其余 ID 随机，不改回话、不改落账和校验。错误例不对齐原案 id，同一原样录音两次交回，验证引用失败点、停住且原案保留。两例都从 HTTP 入口走任免、发回、改票与重开。
#1952 起旨意不当夜执行：两夜声明在合并后的 schema 下按原场景原话重录（本机 Claude CLI 逐次 `haiku`，HTTP 入口，仅 `NightDeclaration` 真调，其余原样重放），任命由补任月月末本旨落账生效；测试在补任月把 scope=decree 的 Declaration 交 `landing` 录音，世界份仍用 `month_empty.txt`。录制脚本 `record_1952_sources.py`、`record_1952_landing.py` 同在归档；`landing/` 是 #1952 E1 修复前那次接不住的真跑，`landing-harness-bug/` 是录制脚本解析错误、未发出模型调用的废卷。
测试只断言结构化输入、状态、引用及落账，不约束这些模型回复的措辞。

#1955 转译边界录音

做法同 `month_fiscal_payments.txt`：`Court.translation_agent(Declaration, content/prompts/month_translate.md)`，
本机 Claude CLI 逐次旗 `haiku`，合成输入，原生 `ModelResponse.text` 原样入夹具。
归档：`~/.ak-roles/books/Ming_LLM/1955/artifacts/t1-recordings/`。

| 夹具 | 归档 | 用途 |
| --- | --- | --- |
| `month_fiscal_reject.txt` | `reject/reply-1.txt` | 辽饷加派驳回，`terminal_reason` 为已驳 |
| `month_fiscal_reorder.txt` | `reorder/reply-1.txt` | 边饷优先，改国库 `payment_order` 与 `army_order` |
| `month_fiscal_building.txt` | `building/reply-1.txt` | 新建「钦定银矿」，按 `condition` 折算产出 |

留中用既有 `month_empty.txt`，不另造结局声明。坏输入在测试参数表里手造，不是录音。

## #1977 承办人声明输入

`night_secret.json`、`night_tools.json`、`night_allocation.json`、`night_ordering.json` 的夜间声明现为基于录音的合成测试输入：仅为密令补入新契约的 `handler`（前三份王承恩，末份杨嗣昌）。它们不再是原生回复的逐字副本；场景、旨文与其他声明字段未改。原始录音仍以各文件 `source` 指针及下文归档为准。这些输入只验声明落账与取阅，不证明真实模型能识别承办人；该效果留给合并后真跑。

## #1952 密令边界录音

归档：`~/WorkSpace/vault/ak-cc-wiki/raw/ming-llm-runner/2026-10-22/issue-1952-implementation/`。

- `night_approved.json`、`night_travel.json`：保留原场景，整夜声明由 `1952-record-approved-r2/messages.json`、`1952-record-travel/messages.json` 重录，含新的成旨轮次与保密声明；不手补模型字段。`night_travel.json` 的整夜声明（第 2、4 轮成旨）另供 `test_audience` 的合成四轮夜判知情圈。
- `night_secret.json`：`1952-secret-native/001`–`007` 的原生 CLI JSONL 工具调用和最终场景文字，以及 `008-NightDeclaration-output.txt`。工具名去 MCP transport 前缀后装入原生 `ToolCallPart`；参数、调用 ID、回复原文不改。消息信封时间为冻结时间，不伪称模型原始元数据。
- `secret_report.txt`：`1952-secret/018-secret_report-output.txt`，仅作为模型文本边界；不锁定内容或要求重放文字符合当前局面。
- `month_secret_completed.txt`：`1952-boundary-crossing/output.txt`，通过真实 `Court.translate` 录下。`input.json` 明标人为构造的补充验收场景（内部发现、公开伤情、多次经办及办结），不是完整游戏推演；返回原文不改。测试从 HTTP 过月进入，检验身份可读实体、落账数值、曝光与停报，不检查文句。

`1952-secret-native` 真跑到十一月：密令声明接不住仍有当月曝光与密报。
`1952-secret` 遇真实 CLI 拒答后，显式重试续至十二月；失败与恢复均留卷。
`1952-B-full` 两夜原话及准旨判断均用真实模型，重开存档日期十二月、无失败；
runner 曾在后台工作未完时索取空奏疏列表而报错，补读见 `reopened-final-state.json`。
该局生成两道公开旨，三份月末声明接不住，不能冒称北极星全部语义验收通过。
完整家族终态真跑及全量仍留给父票 runner / CI。

## 背书与中旨（#1953）

2026-10-22 归档根：`~/WorkSpace/vault/ak-cc-wiki/raw/ming-llm-runner/2026-10-22/`。
`issue-1953-implementation/` 保存驱动脚本、输入、原生 messages、SQLite 与失败日志。
五份新增 JSON 的 `source` 指向原卷；`replies` 原样取原生文本响应，连同首次把御笔写成
「皇帝」的错误回复一起保留，不手改模型字段。测试只在模型边界重放。

- `night_endorsed.json`：北极星 L240–262 两轮原话，追加真实场景的「都准了。」；
  译出毕自严当面站台，独立于办事人。
- `night_double.json`：同一前缀后请王绍徽会签、御笔亲担但照常制送阁；
  录出毕自严、王绍徽、御笔三条背书，非中旨。
- `night_interim.json`：同一前缀后明确亲下手敕、以中旨明发、不经内阁票拟，再认可拟稿；录出中旨。

三份夜录音的 `replies` 已在并入 #1952 后按合并后 schema 重录，归档
`~/.ak-roles/books/Ming_LLM/1953/artifacts/merge-1952-rerecord-nights/production/`（脚本
`rerecord_1953_production.py`）。录法同 #1952：按 `conftest` 建夜（场景与轮次 id 原样重放），
HTTP dismiss 驱动整夜转译，仅 `NightDeclaration` 真调；模型设置同原录，claude-cli 不带
`--model`（本机 CLI 默认，`~/.claude/settings.json` 为 `sonnet`）。每次 CLI 往返的请求（含重交反馈）
与原文回话逐份落卷，回话不手改。每份只录一次，均命中：endorsed 1 次（毕自严当面站台）；
double 1 次（首回把御笔写成「皇帝」被校验打回，重交得毕自严、王绍徽、御笔三条，两条回话同存）；
interim 1 次（interim=True、非密令）。interim 第 3 轮原话由「不经内阁，以中旨颁行」改为
「以中旨明发天下，不经内阁票拟」使意图明确，场景回话仍原样重放。double 场景重放不含召人工具调用，
殿上无王绍徽，与原录不同。废卷：`input-deviation/`（走测试路径但逐次 `haiku`）与
`backed/`、`double/`、`interim/`（原 ledger、另拼转译 agent、逐次 `haiku`，backed 失败未留回话），均不作夹具来源。
- `month_interim_*.json`：分别沿生产推演、转译 Agent 录出准行与封驳的后果。
  外廷采用 #1951 冻结判词；旧判词正文与本旨不一致，模型把它解释成错引旨文。
  这是混合边界录样，不冒称完整同源历史。封驳首份转译含该局旨 UUID，未改写它；
  明确中旨事实不重复声明后，另录 `13-Declaration.json`，原卷两份均保留。

HTTP 验收从共享夜前缀复制私有库，CLI audit 验背书来源、担名履历与落账，
畸形案只改真实回复中的背书项。代价只验结构化字段是否落账、是否重复，不锁数额。
`1953-boundary/result.json` 是北极星 L107 请手敕、L115 密令授剑的独立观察：模型交空成旨，
未用关键词补造背书。不是完整 B 场；完整 B 观察仍留家族最终状态执行。

`1953-strong-2.log` 留有本次真实强推重议失败：Claude CLI exit 1、provider `refusal`
（request `req_011CgHMizepEMT2QkhxPXsyn`）。未伪称成功、未改宿主或模型配置绕过；
确定性强推准／驳／传输重试案沿用既有真实判词，真实重议成功验收尚缺。

## 月末声明的其余旨意（#1971）

录件根：`~/WorkSpace/vault/ak-cc-wiki/raw/ming-llm-runner/2026-10-24/1967-acceptance/`。
`night_allocation.json` 的皇帝原话取 `pi-004526/actions.jsonl`，五轮场景取
`001-scene`–`005-scene/stdout.jsonl` 的完整 assistant 消息；工具调用仅去掉
`mcp__court__` transport 前缀后装入原生 Pydantic AI 消息，参数、调用 ID、回话不改。
消息信封时间是导入时间，不冒称原模型时间；整夜声明为 `texts/006-NightDeclaration.txt`。

| 夹具 | 原卷 | 用途 |
| --- | --- | --- |
| `month_allocation_night.txt` | `texts/008-simulation.txt` | 同夜明发拨款与查库密令 |
| `month_allocation_world.txt` | `texts/009-simulation.txt` | 含赈银起解及巡抚续奏的完整世界推演 |
| `month_allocation.txt` | `texts/013-Declaration.txt` | 010 结构重交后的本旨声明，十万与二十万分别起解 |

三份文本逐字复制，不手补字段。复用 `steps`、`game_db` 与现有月推进测试，
从 HTTP `/actions` 进入，检查世界份 `others` 的旨意 ID、议处结构及 CLI audit 落账。
世界声明重放既有 `month_empty.txt`，不是修复后的模型回话；确定性案只证明输入完整、
原样声明落账，不证明模型自主避重。两路拨款不重复及 #1954 奏疏后果的真模型复验，
按票面由 runner 在并入家族分支前执行。
