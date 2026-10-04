# #1900 修内司回执：J6 / J19 / J18（全仓整类结清·禁 REVIEW）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1900-w5`
- 分支：`ak-roles/1900-j6-j19-j18-fixer-8785cd10a`
- 判词真源：`vault/.../1900-judge-8785cd10a-sealed4.json`（末份；判词不变）
- 禁令：无 stash / amend / rewrite / push / PR；未改 Soul/宪法/席位配置；未真调模型
- 变异还原：精确编辑 + `finally` 写回原文；**未** `git checkout/reset/stash`

## 1. 未结类别与处置

| 类 | 级别 | 处置 |
|---|---|---|
| **J6** | P2 | AST 全仓枚举 248 测试路径；焦点 1258 项逐项 KEEP/FIX；**0 REVIEW**；Thread 工厂简化；原未决项全结清 |
| **J19** | P2 | `_merge_directive_payload`：先 normalize 新名单一次，空则 pop 不覆盖旧名册；非空再共享 `merge_participant_roster_entries` |
| **J18** | P3 | 删 `test_grant_reconciliation_567` 软判提案失效说明；死入口复扫 0 |

## 2. 明确不再证明

- **草案**：整条已删（不另造）。
- **截止**：平行块已删；只留未知 section/坏形状拒收负向。**不宣称证明截止**。

## 3. 枚举

命令真源：[`enum-cmd.txt`](enum-cmd.txt)

- AST 原始候选：[`j6-ast-candidates.jsonl`](j6-ast-candidates.jsonl)（py 4006 + ts 493）
- 摘要：[`j6-ast-summary.json`](j6-ast-summary.json)（path_count=248）
- 权威成员表（**仅 md**）：
  - [`j6-full-members.md`](j6-full-members.md) — 含原 REVIEW 逐项结清表 + 全焦点表；**无 REVIEW / 无授权面外拒修**
  - [`j19-full-members.md`](j19-full-members.md)
  - [`j18-full-members.md`](j18-full-members.md)
- 复扫：[`rescan-final.txt`](rescan-final.txt)

## 4. 逐类修复

### J6
- 原 `REVIEW_*` 项逐项打开：夹具回传 / LLM 边界+结构化结果 / CLI 装配 / 完成同步 → **KEEP+契约**；成立者此前已删（草案/截止平行/print 盯文）。
- 归档三案：`make_thread` 工厂（无 37 行 Thread 包装类）+ `api_menu_new_game` + join 已 start 线程 → 外部文件/失败断言。
- Web/TS 纳入枚举并给 KEEP 契约（DOM fixture / fetch harness / P4 负向 / UI 固定话语）；**不划面外**。

### J19
- 空 incoming：`normalize` 后为空 → `pop`，`{**old,**incoming}` 保留旧名册。
- 非空：`merge_participant_roster_entries(old, new_roster)`（new 已规范化一次后再进共享 merge）。

### J18
- 测试模块说明去掉「软判提案」失效叙述；ADR/DELTA 退役标注保留为文档。

## 5. 聚焦测试（七 BIN=/usr/bin/false）

结果：[`focused-tests.txt`](focused-tests.txt)

```
17 passed in 1.11s
real ~1.6s
```

## 6. 变异（精确编辑 + finally）

日志：[`mutations.txt`](mutations.txt)

| 项 | 红 | 绿 |
|---|---|---|
| J6 归档：`_spawn_drain_close` 构造 Thread 不 start | 三案 `assert [] == [1]` | 3 passed |
| J19 静默 id keep-first | 协办押解被吞 | escort 4 passed |
| J19 空 incoming | — | empty_merge_ok |
| J18 软判提案说明 | rg 无命中 | — |
| 拒收负向 | — | 1 passed |

`ALL_MUTATIONS_OK`。

## 7. 自查二连

- 同类型：全仓 AST 焦点表无 REVIEW；禁样 LEAK/_strictly_before/draft 伪证/attempts wait = 0；J19 静默 id = 0；J18 死入口 = 0。
- 引入 bug：全局吞 Thread.target/start 会挂其它写路径线程 → 变异改为只改 `_spawn_drain_close` 的 `.start()`；merge 空名单用 normalize 判定而非 raw truthiness。

## 8. SHA

（fix commit；working tree clean after docs fill）
