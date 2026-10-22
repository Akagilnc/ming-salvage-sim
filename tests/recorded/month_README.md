# 月推进边界录音（#1951）

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

## #1952 密令边界录音

归档：`~/WorkSpace/vault/ak-cc-wiki/raw/ming-llm-runner/2026-10-22/issue-1952-implementation/`。

- `night_approved.json`、`night_travel.json`：保留原场景，整夜声明由 `1952-record-approved-r2/messages.json`、`1952-record-travel/messages.json` 重录，含新的成旨轮次与保密声明；不手补模型字段。
- `night_secret.json`：`1952-secret-native/001`–`007` 的原生 CLI JSONL 工具调用和最终场景文字，以及 `008-NightDeclaration-output.txt`。工具名去 MCP transport 前缀后装入原生 `ToolCallPart`；参数、调用 ID、回复原文不改。消息信封时间为冻结时间，不伪称模型原始元数据。
- `secret_report.txt`：`1952-secret/018-secret_report-output.txt`，仅作为模型文本边界；不锁定内容或要求重放文字符合当前局面。
- `month_secret_completed.txt`：`1952-boundary-crossing/output.txt`，通过真实 `Court.translate` 录下。`input.json` 明标人为构造的补充验收场景（内部发现、公开伤情、多次经办及办结），不是完整游戏推演；返回原文不改。测试从 HTTP 过月进入，检验身份可读实体、落账数值、曝光与停报，不检查文句。

`1952-secret-native` 真跑到十一月：密令声明接不住仍有当月曝光与密报。
`1952-secret` 遇真实 CLI 拒答后，显式重试续至十二月；失败与恢复均留卷。
`1952-B-full` 两夜原话及准旨判断均用真实模型，重开存档日期十二月、无失败；
runner 曾在后台工作未完时索取空奏疏列表而报错，补读见 `reopened-final-state.json`。
该局生成两道公开旨，三份月末声明接不住，不能冒称北极星全部语义验收通过。
完整家族终态真跑及全量仍留给父票 runner / CI。
