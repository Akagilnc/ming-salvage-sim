# Coder 花名册（Coder-Rec roster）

Version: **2026-07-11.1**（#795 补入 sol 难片收敛型 coder）

设计时标注推荐 coder + 补位顺序；编排器只读查表（[#767](https://github.com/Akagilnc/ming-salvage-sim/issues/767)）。运行时无自适应升档状态机。

## 当前花名册

| coder id（Coder-Rec 用） | 池 | runnable slug | 擅长 | 备注 |
|---|---|---|---|---|
| `grok-4.5` | SuperGrok 周池 | `grok-4.5` | 首发收敛率全场最佳、速度并列最快 | 主力（池子在时） |
| `terra@med` | codex 5h/周 | `gpt-5.6-terra` | 完整面 / 常规 fix | 5.6 选官；别名 `terra@med+fast` |
| `luna@med` | codex 5h/周 | `gpt-5.6-luna` | fix 轮迭代收敛、交互单修 | fix 主力；别名 `luna@med+fast` |
| `sol@med` | codex 5h/周 | `gpt-5.6-sol` | 难片收敛、换棒接管 | 非批量默认；别名 `sol@med+fast`；#920 起同模型跨角色合法（可与 review/cmr 同 slug） |
| `sonnet-5` | Claude 池 | `sonnet` | 完整面 / 大活 | grok 枯竭后备选（[#789](https://github.com/Akagilnc/ming-salvage-sim/issues/789)） |
| `haiku-4.5` | Claude 池 | `haiku` | 小修 / 快速机械活 | grok 枯竭后小活起步；别名 `Haiku 4.5` / `haiku` |

真源表也在 `orchestrator/src/coderRoster.ts`（`CODER_ROSTER` / `CODER_ROSTER_VERSION`）——改表时 docs 与代码同步 bump version。

## 设计时标注

在切片 issue body 加一行（推荐 + 补位顺序）。设计者在 `to-tickets` / 写切片时人肉贴上；编排器只读、不推断。

### 复制模板

```text
Coder-Rec: grok-4.5 → terra@med → luna@med
```

把 `X → Y → Z` 换成花名册里的 coder id（见上表）。常见写法：

| 场景 | 模板 |
|---|---|
| 默认推荐（池异源） | `Coder-Rec: grok-4.5 → terra@med → luna@med` |
| 只要两档 | `Coder-Rec: grok-4.5 → terra@med` |
| grok 枯竭后大活 Claude | `Coder-Rec: grok-4.5 → sonnet-5 → haiku-4.5` |
| grok 枯竭后小修 Claude | `Coder-Rec: grok-4.5 → haiku-4.5 → sonnet-5` |
| 用户点名 Claude 首发 | `Coder-Rec: sonnet-5 → grok-4.5 → terra@med` |

规则（当前 legacy；canonical cutover 变化写在对应项内）：

- 箭头（`→` / `->`）或逗号分隔均可。
- markdown 粗体 / 行内代码 / 链接装饰可（编排器先用 remark 剥净再匹配；#906）。
- 缺省（无此行、body 也无 `Coder-Rec` 字样）→ **不改** 当前 route 预设的 coder 槽（运维 `ORCHESTRATOR_ROUTE` / slot override 仍生效）。
- 有 `Coder-Rec` 字样但行格式坏 / 含未注册模型名 → **admission fail-closed 报错退出、零派单**（禁止静默丢弃非法 token、禁止回落默认序）。
- canonical cutover 同样要求在纯配置预检中对显式候选 fail-closed；只有未提供显式候选顺序时才使用 route 默认序。
- 设计切片时请显式写 Coder-Rec 行（`to-tickets` / 花名册默认序作推荐模板）。host skill（`~/.claude/skills/to-tickets`）接线另票授权，当前靠本页 + [DEV_WORKFLOW.md](DEV_WORKFLOW.md) 切片节。

## 编排器只读行为

下列各项记录当前 legacy 接线；canonical cutover 后 Coder-Rec 只提供 coder/coderFix 的固定候选顺序，Policy 只按客观可用性求值，Runner 不读，边界见 #870。专业评审不再以质量、finding 或轮数触发换棒。

1. Issue intake 读 issue body；**仅当存在 `Coder-Rec:` 行**时覆盖 coder（+ coderFix）槽。
2. 派工第一个花名册合法项。
3. 当前 legacy 中，专业评审 Action 可声明质量不收敛并要求 coder/coderFix 顺位补位；canonical cutover 删除这条路径，评审按 #869 继续 reviewer → fixer → fresh reviewer，确实无法继续时走既有 decision gate。
4. `ORCHESTRATOR_CODER_MODEL` 显式覆盖时，跳过 Coder-Rec（运维优先）。
5. 无 `Coder-Rec:` 行 → 保持当前 `ORCHESTRATOR_ROUTE` 预设 coder。

Coder-Rec 只服务 coder / coderFix。delivery/shared-tail 的 Finding Repair 使用自身 Action capability / route，不读取本花名册。

## 池分工（#920 / ADR 0132 D5）

**池隔离全拆。** 同模型跨角色合法：coder 花名册候选不再做审卷冲突过滤，cmrReview 腿可与 coder 同 slug 点火；唯一保留的隔离 = fresh context + 角色 prompt。单顺位花名册任意轮数留守顶位、永不因「顺位耗尽」退出。

运维仍可按额度/品味偏好异源排布，但编排器不再以同 slug 为硬否决。
