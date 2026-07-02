# 结构化聊天动作暂存、对话确认落库

Status: accepted（2026-06：确认形态由「颁诏批量同意 + UI 撤回面板」修订为「对话确认」，见下「确认形态修订」）

细化 [ADR 0002](0002-use-action-candidates-instead-of-tool-calls-as-game-rules.md)。0002 定了「聊天写动作先成动作候选、过确认闸门才改游戏状态」，但没定确认闸门的形态。实践发现：对话中**明确**的命令（显式「密令如下：/拟旨如下：」按钮）逐条点「准」是画蛇添足；而让结构化动作直写真实表、再靠快照式「撤回召对」回退，机制复杂且只能撤最后一轮、颁诏后失效。因此对密令、任免、后宫这类**结构化、由 LLM 从自然语言推断**的聊天写动作，采用「召对期进 `pending_actions` 暂存、不动真实表」的提交模型。

## 确认形态修订（2026-06）

初版确认闸门 = **颁诏批量同意**（暂存动作活到颁诏一次性落库，皇帝靠独立「待颁诏」面板复核/撤回）。playtest 否之：独立面板 + 顶部浮窗 + pending 角标 + 撤回按钮是**画蛇添足的第二套 UI**，且「确认」本应在**对话里**完成、不该跳出人物。改为**对话确认**：

- 大臣（含太监）判出动作后，在回话里以 in-character 身份**领命并复述要点**（不出戏、不弹系统式「确认?」问句）；
- **皇帝下一句明确应允** → 当场 commit 该召对大臣的暂存（不等颁诏）；
- **拒绝** → 丢（删暂存行）；**不回** → 留着不动；**颁诏对没回的算同意**（沿用 `commit_pending_actions` 批量落全回合）。
- 前端**不新增任何 UI**：密令仍在 ChatModal 左密令区按原样显示，任免/后宫不挂额外标记/角标/面板（原来有的照旧、原来没有的不加）。

## Considered Options

- 逐条确认闸门（每个动作点准/驳 UI）：最稳，但对明确命令是多余摩擦，且把确认搬出对话、伤沉浸。
- 乐观直写 + 撤回召对 undo：撤回靠前后快照差异还原，只能撤全局最后一轮、颁诏后不可撤，且「未颁诏草案广播给所有大臣」是 roleplay 硬伤。
- 暂存 + 颁诏批量同意 + UI 撤回面板（初版）：撤回免费、节律统一，但需独立面板这第二套 UI，确认脱离对话——playtest 否。
- 暂存 + **对话确认**（现行）：暂存机制不变，确认改由对话驱动（大臣领命 + 皇帝应允/拒绝/不回 + 颁诏兜底），零额外 UI、不出戏、零摩擦。

## Consequences

- **闸门覆盖聊天写动作**：召对里皇帝没点按钮、只是说话，由 LLM 判出的密令更新/催办/提交核议/记进展、**任免（任命/罢免）**、后宫调教 —— 这类**推断**动作进暂存、过确认才落库。显式「拟旨如下：」按钮/前缀同样先进 `pending_actions(kind=directive)`：大臣以 in-character 方式润色草案并问准否；皇帝拒绝→删暂存，皇帝不回→颁诏 checkpoint 默认同意为 `draft`，皇帝在召对里应允→转成 `turn_directives.status='pending'`，仍走既有准/驳界面。显式「密令如下：」仍是权威分类，但密令字段提取保留独立路径。
- **三类全入闸（任免纳入）**：CLI 自然语言路径里 ① 密令 4 动作 ② 后宫调教 ③ **任免（任命/罢免）**。任免是**独立检测**（`extract_appointment_action`，与密令的 `extract_minister_actions` 不搅在一起）、**随召对触发、不挂密令 gate**（任何召对都可能口头派官，含跟太监说）、作用域=当前召对的大臣、**公开**（不同于密令私密）。〔修订：初版把任免留作后续、走 agno tool-call(api 通道)；现纳入 CLI 自然语言闸门。〕
- **落地机制按数据性质分**：`commit_pending_actions` 直接 INSERT/UPDATE 真实表——密令、后宫调教走 db 自身；**任免（office）落库需 content/registry**（注册新臣 Agent），故 `commit_pending_actions`/`_apply_pending_action` 透传 content/registry（探针 driver 无聊天暂存，传 None 即 no-op）。任免 commit 按动作与被任者分流：**朝臣任命/升迁/调任 → `issues.apply_office_appointment`**（与 extractor 的 `office_changes` 共用的【唯一落地核】：在册且未死→改 active+授官+顶替去重+同步内存/registry，不在册→**拒收 `hallucinated_id`**（ADR 0009 决定8 已有意回退此「建档」旧路径——唯一例外=后宫 candidate；本处原作「建档」系当时落地核现状的旁注、已被 0009 覆盖，后出为准），dead/空 office 拒），**纳妃（office 推断为后宫）→ `apply_appointment` 的 consort 路**，**罢免 → `_find_existing_minister`（ming-guard+解 alias）+`set_character_status(dismissed)`+清内存 office**。〔CMR R2 reground：曾在 `_commit_office_action` 手抄一份 office 落地、漏 status 生命周期等守卫；现归一到 `apply_office_appointment` 一处真源。〕拟旨仍走 simulator→extractor→`apply_score_extraction`。
- **提交时机**：对话应允 = 当场 commit 该大臣暂存；颁诏 `commit_pending_actions` 在 `resolve_turn` 最前、跑 LLM 结算前批量落全回合未拒的——**先提交再结算**，盘面时序与旧「召对期直写」一致；幂等（落库即标 committed，HITL phase2 resume 不重跑）。〔**2026-07-02 #470 设计闸（ADR 0038）取代「应允=当场 commit」在召对夜容器下的语义**：夜内应允改为暂存标「已应允」（夜域态、撤回可逆转），**收夜批量提交**本夜已应允的（任免/后宫 commit、拟旨候选转档）；「不回→颁诏/过回合默认同意」不变；密令仍应允即落地。后出为准，详 ADR 0038。〕
- **可见性**：暂存动作对话之外的大臣**看不到**（无 UI 面板，确认靠对话本身；密令私密、任免公开）。不依赖、不扩展 `build_draft_line` 广播（去留见 TODOS.md T6）。
- **暂存是 append-only**：`stage_pending_action` 每次 INSERT 一行（无 upsert），commit 时按 id 序（=操作发生序）逐条 apply、保操作语义；落不了的标 failed（不留 pending）。对话确认的 commit/drop 按召对大臣（`minister_name`）过滤，不波及他人暂存。
- **决策即落库（CLAUDE.md P1 铁律）仍满足**：`pending_actions` 是真实 DB 表，待确认动作落在其中，context 压缩后 restore 仍可无损接续。
- **颁诏后反悔**不是 undo，是新的游戏内命令（有代价），照局势 `cancellable=decree`+`cancel_cost` 范式，属本 ADR 范围外（见 TODOS.md T5）。
