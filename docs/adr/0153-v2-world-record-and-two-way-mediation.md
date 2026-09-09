# 重构：账本记实况，中间层双向供料与记账，不裁判剧情

Status: proposed（2026-09-09；owner 已拍方向，设计待评审，未实施；本次游戏重构，非独立版本）

沿用 [CLAUDE.md 的游戏总纲](../../CLAUDE.md)，重构后的中间层向外按 LLM 职责组织实况或角色见闻，向内由推演 LLM 直接调用记录能力，完成规定核算并记回引擎，而非让模型直接操作 DB、让中间层裁判剧情，或预设「另写实况说明再交辅助 LLM 抽取」的必经步骤。
理由是世界实况、公开说法和人物记忆必须能同时存在且互不冒充，否则假消息会改写真相、真实账本又会让所有人物全知，参见既有 [0034](0034-minister-audience-fed-perspectival-knowledge-not-omniscient.md) 与 [0073](0073-two-books-reported-vs-actual-rails.md)。
[讨论依据及案例](../design/game-v2-architecture.md#方向依据)与[直接记录取舍](../design/game-v2-architecture.md#直接记录取舍)保留理由与未决项；本决定不承诺存储格式或调用粒度，本轮只改设计、不改运行实现，也不取消其他辅助 LLM 职责，多人同场的首期供料取舍另见 [0155](0155-v2-single-scene-llm-with-complete-perspectives.md)。
