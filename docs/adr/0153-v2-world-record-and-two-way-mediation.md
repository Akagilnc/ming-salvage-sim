# V2：账本记实况，中间层双向供料与记账，不裁判剧情

Status: proposed（2026-09-09；owner 已拍方向，设计待评审，未实施；仅适用于 V2）

沿用 [CLAUDE.md 的游戏总纲](../../CLAUDE.md)，V2 中间层向外按 LLM 职责组织实况或角色见闻，向内承接推演结果及经历、完成规定核算并记回引擎，选择双向供料与记账的职责边界，而非纯 DB 筛选或剧情裁判。
理由是世界实况、公开说法和人物记忆必须能同时存在且互不冒充，否则假消息会改写真相、真实账本又会让所有人物全知，参见既有 [0034](0034-minister-audience-fed-perspectival-knowledge-not-omniscient.md) 与 [0073](0073-two-books-reported-vs-actual-rails.md)。
[讨论依据及案例](../design/game-v2-architecture.md#方向依据)保留具体取舍与未决项；本决定不承诺任何存储形状，不废止现行运行规则，多人同场的首期供料取舍另见 [0155](0155-v2-single-scene-llm-with-complete-perspectives.md)。
