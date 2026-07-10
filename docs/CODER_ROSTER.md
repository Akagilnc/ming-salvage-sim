# Coder 花名册（Coder-Rec roster）

Version: **2026-07-10**（随 [#424](https://github.com/Akagilnc/ming-salvage-sim/issues/424) bench 更新）

设计时标注推荐 coder + 补位顺序；编排器只读查表（[#767](https://github.com/Akagilnc/ming-salvage-sim/issues/767)）。运行时无自适应升档状态机。

## 当前花名册

| coder id（Coder-Rec 用） | 池 | runnable slug | 擅长 | 备注 |
|---|---|---|---|---|
| `grok-4.5` | SuperGrok 周池 | `grok-4.5` | 首发收敛率全场最佳、速度并列最快 | 主力（池子在时） |
| `terra@med` | codex 5h/周 | `gpt-5.6-terra` | 完整面 / 常规 fix | 5.6 选官；别名 `terra@med+fast` |
| `luna@med` | codex 5h/周 | `gpt-5.6-luna` | fix 轮迭代收敛、交互单修 | fix 主力；别名 `luna@med+fast` |
| `sonnet-5` | Claude 池 | `sonnet` | 仅用户点名 | 例外位（政策：Claude 只留 CMR） |

真源表也在 `orchestrator/src/coderRoster.ts`（`CODER_ROSTER` / `CODER_ROSTER_VERSION`）——改表时 docs 与代码同步 bump version。

## 设计时标注

在切片 issue body 加一行：

```text
Coder-Rec: grok-4.5 → terra@med → luna@med
```

- 箭头（`→` / `->`）或逗号分隔均可。
- 只保留花名册内合法项；非法 token 丢弃。
- 缺省（无此行）→ **不改** 当前 route 预设的 coder 槽（运维 `ORCHESTRATOR_ROUTE` / slot override 仍生效）。
- 有此行但 token 全非法 → 回退花名册默认序：`grok-4.5 → terra@med → luna@med`。
- 设计切片时请显式写 Coder-Rec 行（`to-issues` / 花名册默认序作推荐模板）。

## 编排器只读行为

1. S0 读 issue body；**仅当存在 `Coder-Rec:` 行**时覆盖 coder（+ coderFix）槽。
2. 派工第一个花名册合法项。
3. 每完成 `CODER_REC_FALLBACK_AFTER_ROUNDS`（默认 2）个不收敛的 S6 fix 轮 → 顺位补位。
4. `ORCHESTRATOR_CODER_MODEL` 显式覆盖时，跳过 Coder-Rec（运维优先）。
5. 无 `Coder-Rec:` 行 → 保持当前 `ORCHESTRATOR_ROUTE` 预设 coder。

## 池分工硬原则

**coder 池与 reviewer 池尽量异源。** 硬规则：coder 花名册条目不得与当前 reviewer / CMR 腿 **同 slug 双挂**（`poolSeparationViolation`）；冲突时顺位跳到下一个合法项。单池全家桶仅作池外无人时的降级形态。
