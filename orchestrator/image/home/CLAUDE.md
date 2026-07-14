# 容器工作环境（worker 必读）

你在编排器的一次性容器里干活：

- **没 commit 的等于没做**。容器随时回收；工作以 commit 为存在单位。
  你的 worktree 是隔离克隆——放手改，交付走 commit。
- **没有人在线**。你是 spawned / 非交互进程：不等人回话；skill 内的
  提问按其 spawned 契约自决；真需要人裁决的，走派单说明的升级通道。
- **工具与凭证**：skills 在 `~/.agents/skills`（claude / codex 共用
  一个池）；gh / git / codex 等 CLI 与 auth 已注入，直接用。
