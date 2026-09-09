# V2 首期：一个 LLM 演整场召对，一次提供可见材料

Status: proposed（2026-09-09；owner 已拍首期取舍，设计待评审，未实施；仅适用于 V2）

首期由一个 LLM 演整场召对，按人物组织材料后一次给全本次职责可见内容、让它自己阅读取舍，优先还原北极星的连贯演出并减少等待，不采用每人一个模型、导演调用或按需检索往返。
这是对 [0034](0034-minister-audience-fed-perspectival-knowledge-not-omniscient.md) 的 V2 多人同场实现所作的明确取舍：同一次调用可看见各在场人物的材料，由 LLM 维持人物视角，但不把全局实况无差别提供给角色，职责区分仍依 [0153](0153-v2-world-record-and-two-way-mediation.md)。
本决定不把世界推演和所有辅助处理合成一次调用，原话及被替代的前案见 [召对取舍依据](../design/game-v2-architecture.md#召对取舍依据)。
