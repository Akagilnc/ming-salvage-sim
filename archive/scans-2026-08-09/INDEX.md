# 扫描报告索引 · 2026-08-09

法源：`ak-pi-workflow-roles/CLAUDE.md`（锚定宪法 / 失败诚实宪法 / probe 纪律 / Soul 内容纪律 / 法源优先）+ `~/.claude/CLAUDE.md` 全局 SHARED 条。
执行：cursor-agent（grok-4.5-high）三路 × 三批并发，只读扫描，结果原样存档未删改。
注意：`full-orch-*.md` 三份针对旧编排器（orchestrator/），该子系统已被 ak-pi-workflow-roles 取代，**结论作废，仅供考古**。

## W3 进度盘点（完成 W3 备用）

| 文件 | 内容 |
|---|---|
| `w3-scan-A-slices.md` | W3 三家族（#471/#478/#474）全部 S 切片状态表 + 关键路径 #571→#560 现状 + 可立即开工票 |
| `w3-scan-B-tracker.md` | #486 排程要点、评论时间线、#1120 批次核对（#522 漏交付）、NEXT_ORDER.md 坐标 |
| `w3-scan-C-worktrees.md` | 61 worktree 盘点：W3 相关 0 个、21 个可清理、11 个 prunable |

## 违宪清单 · 锚定宪法（盯文）

| 文件 | 范围 | 条目数 |
|---|---|---|
| `constitution-w1-anchor.md` | W1（#487-#494）生产代码 + 测试 | 13 |
| `constitution-w2-anchor.md` | W2（#498-#507）生产代码 + 测试 | 8 |
| `constitution-core-anchor.md` | ming_sim 内核散文解析（cli_backend/db/settlement/session） | 8 |
| `constitution-web-anchor.md` | web/src 前端盯文 | 8 |

## 违宪清单 · 失败诚实宪法

| 文件 | 范围 | 条目数 |
|---|---|---|
| `constitution-w1-failure.md` | W1 交付面 | 5 |
| `constitution-w2-failure.md` | W2 交付面 | 10 |
| `full-webapp-failure.md` | web_app.py 全量 | 6 |
| `full-adr-and-rest-failure.md` | (a) ADR 冲突无绑定 2 条；(b) ming_sim 剩余模块 6 条 | 8 |

## 违宪清单 · 文本纪律（prompts/souls）

| 文件 | 范围 | 条目数 |
|---|---|---|
| `constitution-texts.md` | content/prompts + orchestrator/prompts + souls | 6 |

## 违宪清单 · 测试与 probe 卫生

| 文件 | 范围 | 条目数 |
|---|---|---|
| `constitution-tests.md` | W1/W2 测试 + scripts probe | 12 |
| `full-tests-rest.md` | tests/ 其余文件 | 8 |

## 复杂度债

| 文件 | 范围 | 条目数 |
|---|---|---|
| `constitution-core-complexity.md` | ming_sim 巨函数/巨石 | 10 |
| `full-cli-session-complexity.md` | cli_backend + session 复杂度 | 8 |
| `full-megaliths.md` | db.py / issues.py 双巨石 | 7 |
| `constitution-web-complexity.md` | web/src 前端 | 13 |
| `full-webapp-complexity.md` | web_app.py | 8 |

## 仓库卫生

| 文件 | 范围 | 条目数 |
|---|---|---|
| `full-scripts-misc.md` | scripts/ 根目录 electron 杂物 | 8 |
