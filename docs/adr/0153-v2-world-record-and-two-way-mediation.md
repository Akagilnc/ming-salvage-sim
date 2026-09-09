# 重构：账本记实况，中间层双向供料与记账，不裁判剧情

Status: proposed（2026-09-09；owner 已拍方向，设计待评审，未实施；本次游戏重构，非独立版本）

沿用 [CLAUDE.md 的游戏总纲](../../CLAUDE.md)，重构后的中间层向外按 LLM 职责组织实况或角色见闻，向内承接推演 LLM 交代的结果，其中需要的语义理解与转译由 LLM 承担，代码只据明确的变更完成分派、规定核算及存储，不猜自然语言意图，也不另判剧情。
理由是世界实况、公开说法和人物记忆必须能同时存在且互不冒充，否则假消息会改写真相、真实账本又会让所有人物全知，参见既有 [0034](0034-minister-audience-fed-perspectival-knowledge-not-omniscient.md) 与 [0073](0073-two-books-reported-vs-actual-rails.md)。
[直接记录取舍](../design/game-v2-architecture.md#直接记录取舍)不排除中间层使用转译 LLM，职责澄清见 [语义转译仍归-llm](../design/game-v2-architecture.md#语义转译仍归-llm)；具体调用划分及存储格式尚未定，本轮只改设计、不改运行实现，多人同场供料取舍另见 [0155](0155-v2-single-scene-llm-with-complete-perspectives.md)。
