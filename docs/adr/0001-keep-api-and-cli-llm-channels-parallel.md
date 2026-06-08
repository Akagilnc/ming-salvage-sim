# API 与 CLI LLM 通道并行保留

Status: accepted

探针需要 CLI 通道，让当前 agent session 或本机 CLI 可以直接扮演游戏 LLM，不再强依赖商业 API key；但原有 OpenAI 兼容 API 通道仍然适合正常 web 游玩、基准对照和成本/质量比较。因此我们保留 API 与 CLI 两条并行 LLM 执行通道，用显式激活通道和独立槽位管理，而不是让 CLI 替换 API，或只靠环境变量切换。

## Considered Options

- 用 CLI 通道替换 API 通道：实现简单，但会丢掉已知可用的游戏路径，也无法做模型/成本对照。
- 只用环境变量切换：接线便宜，但很隐蔽；后来的 `MING_SIM_LLM_BACKEND` 可能劫持已经保存的 API 配置。
- 保留平级通道槽位：需要更多校验和 UI 状态，但能同时保住两条线，并让玩家选择变成显式状态。

## Consequences

显式 API 通道必须忽略 CLI backend 环境变量。保存的 CLI 通道必须能在没有 API key 的情况下启动。保存任一通道时，都要保留未激活通道的槽位，避免切换回来时丢配置。
