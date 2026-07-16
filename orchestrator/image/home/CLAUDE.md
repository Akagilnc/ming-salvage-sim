# 容器工作环境（worker 必读）

你在编排器的一次性容器里干活：

- **没 commit 的等于没做**。容器随时回收；工作以 commit 为存在单位。
  你的 worktree 是隔离克隆——放手改，交付走 commit。
- **没有人在线**。你是 spawned / 非交互进程：不等人回话；skill 内的
  提问按其 spawned 契约自决；真需要人裁决的，走派单说明的升级通道。
- **工具与凭证**：skills 在 `~/.agents/skills`（claude / codex 共用
  一个池）；gh / git / codex 等 CLI 与 auth 已注入，直接用。

## 宪法（裁决与修复的法源）

宪法 = 三件套：**本单 issue 原文 + AC**（本单最具体法）、**`docs/adr/`
已 Accepted 条目**（跨单宪法）、**CONTEXT.md 词表**（概念法）。

- **开工先立案**：判官建庭 / 修复工（含 coder-fix）接单的第一动作 =
  枚举本单 authority set（适用 ADR 编号 + 票号）写进自己的记录；裁决
  与驳回引 clause 锚点。
- **宪法只读**：修复不得触碰宪法文件来消解 finding；唯一例外 = 票面 AC
  明文授权的修订。需要修宪才能修 → 上抛（`escalate`，修宪权在 owner）。
- **AC 与 ADR 相抵 → 上抛（`escalate`）**：两份已批文件打架 = 设计
  裂缝，不自行挑边。

## finding 裁决法理（四理由——评审 / 修复 / 判卷通用）

真 → 修；驳回必须点名依据、附证据。驳回理由仅四条：

1. **违宪** `unconstitutional`：与已拍定 ADR / owner 决策 / 验收文相抵。
   宪法压过评审员——驳修法，不改宪法。
2. **过度防御** `over_defense`：护栏类处方答不上三问——
   出事概率多大？后果多重？下游有没有兜底——会响的失败自有人接。
3. **事实不成立** `not_established`：主张对不上真实代码。
4. **越权加戏** `scope_creep`：只看修法，不看 bug 从哪被发现——仅当修法
   发明 authority / spec 未授权的新行为时成立；bug 早于 fixed point、位于邻接文件或偶然被发现，
   均不构成越权加戏，真问题仍须 fix_now。

四条之外自认有正当理由 → 不自创新法，上抛 owner。难修不是驳回理由；
便宜的修复直接修，不缓交。
