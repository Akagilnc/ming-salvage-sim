# 用动作候选取代 Tool Call 作为游戏规则边界

Status: accepted

召对聊天会产生拟诏、密令、更新密令、催办等写动作，但 tool call 不是稳定的游戏规则边界：API 通道可能有 function calling，CLI 通道可能只有文本，streaming 与非 streaming 路径也容易漂移。因此聊天派生的写动作统一先归一成动作候选，再经过玩家确认闸门，确认后才允许改变游戏状态。

## Considered Options

- 把 API tool call 直接当最终写动作：能沿用旧路径，但排斥 CLI runner，并把模型传输能力误当成游戏规则。
- 从文本直接解析并写库：能支持 CLI runner，但误写、歧义写入和 stream/non-stream 分叉风险太高。
- 所有聊天写动作先归一成候选：多一个 pending 状态，但 API 与 CLI 通道获得同一契约，玩家也能在确认闸门前校正。

## Consequences

Tool call、CLI parser、streamed model output 都只能提出动作候选，不能单独成为 durable game truth。Streaming 与非 streaming 聊天路径应共用同一套动作归一和确认行为。
