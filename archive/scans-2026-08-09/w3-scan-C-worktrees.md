## 盘点摘要

主工作区共 **61** 个 worktree；本地分支 **191**、远程跟踪分支 **249**。  
`feat`/`fix`/`takeover` 类 worktree **21** 个，对应 issue **全部 CLOSED** 且均有合入 PR → 归入「已合入可清理」。  
当前 **没有任何** worktree 挂在 W3 切片号（#515–#529 / #560 / #571）或 #471/#478/#474 家族分支上。

---

## (1) 与 W3 相关的工作树清单

| 编号 | 路径 | 分支 | HEAD | 对应 issue 状态 | 判断 |
|------|------|------|------|-----------------|------|
| — | — | — | — | — | **无**：`git worktree list` 中无路径/分支匹配 #471/#478/#474 家族切片，亦无 #515–#529、#560、#571 |

**W3 相关分支（无 worktree，仅事实）：**

| 分支 | 备注 |
|------|------|
| `family/513`（本地 + `origin/family/513`） | #513 CLOSED 部分切片已合入 PR #1120（2026-07-24）；无对应 worktree |
| `origin/family/571` | HEAD `ae41aa0f`（2026-07-26）；#571 仍 OPEN；无对应 worktree |

**W3 范围 issue 快照（无 worktree）：** 父票 #471/#478/#474 均 OPEN；#515/#527 CLOSED；#516–#526/#528/#529/#560/#571 OPEN。上述切片号 `gh pr list --search '#N in:title' --state open/merged` 除 #513→merged #1120 外，open/merged 标题命中均为 `[]`。

---

## (2) 可清理 / 停滞工作树清单

### 已合入可清理（feat/fix/takeover；issue CLOSED + 已合入 PR）

| # | 路径 | 分支 | HEAD | issue | 合入 PR | 判断 |
|---|------|------|------|-------|---------|------|
| 1145 | `.../.ak-orchestrator/ming-code-delivery/issue-1145` | `fix/1145` | `fa91fbac` | CLOSED | #1148 | 已合入可清理 |
| 1002 | `Ming_LLM-1002` | `feat/1002` | `2a362540` | CLOSED | #1017（战役体含 #1002） | 已合入可清理 |
| 1005 | `Ming_LLM-1005` | `feat/1005` | `e9b67dc1` | CLOSED | #1017 | 已合入可清理 |
| 1006 | `Ming_LLM-1006` | `feat/1006` | `f8f999ac` | CLOSED | #1017 | 已合入可清理 |
| 1007 | `Ming_LLM-1007` | `feat/1007` | `f0ed92aa` | CLOSED | #1017 | 已合入可清理 |
| 1010 | `Ming_LLM-1010` | `feat/1010` | `aba9394a` | CLOSED | #1017 | 已合入可清理 |
| 1012 | `Ming_LLM-1012` | `feat/1012` | `5f878561` | CLOSED | #1017 | 已合入可清理 |
| 1014 | `Ming_LLM-1014` | `feat/1014` | `95645402` | CLOSED | #1017 | 已合入可清理 |
| 1016 | `Ming_LLM-1016` | `feat/1016` | `7dd2da60` | CLOSED | #1017 | 已合入可清理 |
| 677 | `Ming_LLM-677` | `feat/677-ac-overturn-gate` | `2c47dbb3` | CLOSED | #775 | 已合入可清理 |
| 683 | `Ming_LLM-683` | `feat/683-quota-probe-429` | `74a462e2` | CLOSED | #773 | 已合入可清理 |
| 686 | `Ming_LLM-686` | `feat/686-relay-dispatch` | `4bb9160b` | CLOSED | #781 | 已合入可清理 |
| 688 | `Ming_LLM-688` | `fix/688-defer-guard-teeth` | `c56e7392` | CLOSED | #769 | 已合入可清理 |
| 706 | `Ming_LLM-706` | `fix/706-escalation-status-contract` | `da461067` | CLOSED | #771 | 已合入可清理 |
| 743 | `Ming_LLM-743` | `fix/743-recheck-identity-keys` | `6d711689` | CLOSED | #777 | 已合入可清理 |
| 747 | `Ming_LLM-747` | `feat/747-souls-hardening` | `68424b72` | CLOSED | #765 | 已合入可清理 |
| 764 | `Ming_LLM-764` | `feat/764-model-flip-56` | `c6a233a7` | CLOSED | #770 | 已合入可清理 |
| 800 | `Ming_LLM-800` | `fix/800-telemetry-flake` | `449e4d85` | CLOSED | #805 | 已合入可清理 |
| 825 | `Ming_LLM-826` | `feat/825-regression-suite` | `9016b496` | CLOSED | #840 | 已合入可清理（路径号 826 ≠ issue 825） |
| 873 | `Ming_LLM-873D` | `takeover/873-single-slice-courts` | `408e4fea` | CLOSED | #891 | 已合入可清理 |
| 603 | `Ming_LLM-bench-603` | `feat/issue-603-cleanup` | `eff73c37` | CLOSED | #734 | 已合入可清理 |

### 同类 fix 分支命名（`codex/fix-*`，已查 issue）

| # | 路径 | 分支 | HEAD | issue | 合入 PR | 判断 |
|---|------|------|------|-------|---------|------|
| 1132 | `Ming_LLM-1132` | `codex/fix-1132-fresh-panel-no-capture` | `f3c25ee0` | CLOSED | #1133 | 已合入可清理 |

### 在跑未完成

| — | 无（上表全部 CLOSED） |

### 停滞（issue 仍 OPEN 且无近期活动）

| — | 无（上表 feat/fix/takeover 对应 issue 均非 OPEN） |

---

## (3) exam 与其他工作树统计

| 类别 | 数量 | 说明 |
|------|------|------|
| **合计 worktree** | **61** | 含主工作区 |
| **exam\*** | **29** | exam742×17；exam766×9（其中 9 条 prunable）；exam818×2；exam600×1（detached） |
| **exp/** | **3** | `Ming_LLM-766b/c/d`（`exp/766-*-marathon`） |
| **feat/fix/takeover** | **21** | 见上表；全部可清理类 |
| **其他** | **8** | 主仓 `kimi/menu-keyart-and-drawer-fixes`；`codex/fix-1132`；`codex/runner-exit-path-audit`；`docs/matt-skill-rename`（design）；`codex/fix-coder-fix-cargo-abi`（fastfix）；`review-bench`（detached）；`/private/tmp/collect-1145-{spec,standards}-38722`（detached+prunable） |
| 本地分支 | 191 | `git branch` |
| 远程跟踪分支 | 249 | `git branch -r` |

---

## (4) prunable 条目列表

`git worktree list` 已标 **prunable**（共 **11**）：

| 路径 | HEAD | 分支/状态 |
|------|------|-----------|
| `/private/tmp/collect-1145-spec-38722` | `c9a6a02c` | detached |
| `/private/tmp/collect-1145-standards-38722` | `c9a6a02c` | detached |
| `/Users/akagilnc/WorkSpace/Ming_LLM-exam766-haiku` | `4a90e833` | detached |
| `/Users/akagilnc/WorkSpace/Ming_LLM-exam766-haiku2` | `67efc51e` | detached |
| `/Users/akagilnc/WorkSpace/Ming_LLM-exam766-luna` | `4a90e833` | detached |
| `/Users/akagilnc/WorkSpace/Ming_LLM-exam766-opus` | `4a90e833` | detached |
| `/Users/akagilnc/WorkSpace/Ming_LLM-exam766-sol` | `4a90e833` | detached |
| `/Users/akagilnc/WorkSpace/Ming_LLM-exam766-sonnet` | `4a90e833` | detached |
| `/Users/akagilnc/WorkSpace/Ming_LLM-exam766-sonnet2` | `4a90e833` | detached |
| `/Users/akagilnc/WorkSpace/Ming_LLM-exam766low` | `3a853e7b` | `exam/766-low` |
| `/Users/akagilnc/WorkSpace/Ming_LLM-exam766xh` | `4a90e833` | detached |

（porcelain 原因字段均为：`gitdir file points to non-existent location`。）盘点批查已跑完，结论与先前报告一致：

- **W3 相关 worktree：0**（仅有无挂载的 `family/513`、`origin/family/571`）
- **feat/fix/takeover：21 个**，issue 全 CLOSED + 已合入 → 可清理
- **exam：29**（含 9 条 prunable）；**prunable 合计 11**
