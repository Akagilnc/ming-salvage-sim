# Ming_LLM 语境

本文件固定明末政略模拟探针的项目语言。它只做 glossary：给 API key 游戏线、本地 CLI 探针线、聊天写动作和结算流程提供稳定词汇，不记录实现方案。

## Language

### Runtime And LLM

**探针**:
用于验证游戏是否好玩的本地学习版本，优先摸清体验和边界，再决定是否固化接口或重写地基。
_Avoid_: 平台、地基、正式架构

**LLM 执行通道**:
一次游戏 LLM 调用实际走的执行路径。每个 runtime 同一时刻只有一个激活通道：**API 通道**或**CLI 通道**。
_Avoid_: 后端（容易和 web server 混淆）

**API 通道**:
通过 OpenAI 兼容 HTTP API 调模型的 LLM 执行通道，由 base URL、模型名和 API key 组成。
_Avoid_: 商业模型线、旧线

**CLI 通道**:
通过本机 agent CLI（如 agy、codex、claude）调模型的 LLM 执行通道。它让探针可以不依赖商业 API key 运行。
_Avoid_: 假 API、无 key 模式

**Runtime LLM 配置**:
玩家当前选择的持久 LLM 配置。它记录激活通道，并保留未激活通道的设置，避免切换通道时擦掉另一条线。
_Avoid_: env 配置、模型设置

**通道槽位**:
某一个 LLM 执行通道的保存配置。API 槽和 CLI 槽是平级关系；只会激活一个，但可以同时记住两个。
_Avoid_: 备用配置、fallback 配置

### Chat Actions

**聊天写动作**:
从召对聊天里产生、会改变游戏状态的动作，例如拟诏、创建密令、更新密令、催办、记录进展。
_Avoid_: tool 结果、副作用

**动作候选**:
已经被归一化、但尚未写入游戏状态的聊天写动作提案。
_Avoid_: 最终动作、tool call

**确认闸门**:
玩家接受、编辑或驳回动作候选的关口。通过确认闸门之后，动作才可以改变游戏状态。
_Avoid_: approval mode、模型自检

**待确认动作**:
位于模型回复和确认闸门之间的动作候选。
_Avoid_: 草案（因为候选不一定是诏书）

### Settlement And Memory

**稀疏 delta**:
用于结算的结构化变更集，只描述发生变化的事实，并通过 score extraction 管线落库。
_Avoid_: 全量状态、邸报 JSON

**决策即落库**:
玩家决策只有在机械后果写入数据库后才算成立。只有叙事、没有落库，不是 durable truth。
_Avoid_: agent 记得、邸报暗示

**邸报**:
回合结束后展示给玩家的朝廷报告。它应该渲染已结算事实，而不是成为第二套事实来源。
_Avoid_: 把 durable state 语境里的邸报称作 simulator output

**有状态实体**:
字段即事实来源的持久游戏对象，例如人物、军队、事项、建筑、机构、关隘。
_Avoid_: 故事点、氛围物件

**瘦裁判**:
检查玩家决策的机械后果是否落到对应有状态实体上的结算守门人。它负责拦一致性错误，不负责计算历史判断。
_Avoid_: 规则引擎、平衡公式

**场景**:
一整场被游玩的戏，包括环境、动作、神态、叙述和对白。它比 chat message 大，用来恢复旧 session 的手感。
_Avoid_: transcript、只有对白

## Flagged Ambiguities

**后端**:
讨论 API-vs-CLI 调模型时，用 **LLM 执行通道**。讨论 HTTP 应用进程时，用 web server 或 FastAPI app。

**Tool Call**:
只用来指模型能力或传输机制。不要把 tool call 当成持久游戏规则；聊天状态变化应先成为**动作候选**。

**批准 / approval**:
玩家接受游戏动作时，用**确认闸门**。开发流程里的 plan/review approval 另说，不混用。

**记忆**:
游戏事实用数据库状态或场景历史承载。Agent memory 只是对话上下文，不足以承载玩家决策。

## Example Dialogue

开发者：“玩家说‘拟旨如下’时，CLI 通道能不能直接把诏书写进库？”

领域专家：“不能直接写。模型可以提出聊天写动作，但结果先成为动作候选。”

开发者：“所以 tool call 不是游戏规则？”

领域专家：“对。Tool call、CLI 解析、stream 输出都只是发现候选的方式。玩家通过确认闸门后，待确认动作才算提交。”

开发者：“玩家从 API 切到 CLI 呢？”

领域专家：“那是切换 LLM 执行通道。它不应该擦掉 API 槽；显式 API 通道也不该被 CLI 环境变量劫持。”

开发者：“一个决策什么时候算真的发生？”

领域专家：“稀疏 delta 落到数据库里的有状态实体之后。邸报可以写得有声有色，但数据库才是 durable truth。”
