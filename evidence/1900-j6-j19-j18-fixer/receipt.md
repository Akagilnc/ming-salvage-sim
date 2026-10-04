# #1900 修内司回执：J6 / J19 / J18（证据更正收尾）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1900-w5`
- 分支：`ak-roles/1900-j6-j19-j18-fixer-8785cd10a`
- 判词真源：`vault/.../1900-judge-8785cd10a-sealed4.json`（末份；判词不变）
- 禁令：无 stash / amend / rewrite / push / PR；未改 Soul/宪法/席位配置；未真调模型；本轮无扩生产机制、无新增测试

## 0. 禁令史实（不得洗白）

- **第一轮 receipt 已承认**：变异脚本误用 `git checkout` 抹生产修复产物 → 已重施并用 `finally` 写回恢复。收录该违规史；**现状已恢复**；**禁止再发生**。不得改口称「本局全程未 checkout」。
- 本轮证据更正：**未** `git checkout/reset/stash/amend/push`；变异还原继续精确编辑 + `finally`。
- **子进程超时/死锁（真实记录，非 infra failure）**：第一轮归档变异红证 `exit=124`（wait 咬住 timeout）；复检曾因同步跑 worker 死锁，后改真实 `Thread.join`。保留原日志口径，不冒称环境故障。

## 1. 类别范围与 KEEP 依据

| 类 | 范围 | KEEP 依据 |
|---|---|---|
| **J6** | 机械宇宙=`j6-ast-candidates.jsonl`（py 4006 + ts 493 = **4499**）；焦点裁决表=`j6-full-members.md`（**TOTAL_FOCUS=1258**，含补入原 REVIEW 邻行）。**焦点计数≠全部候选**；非 FOCUS 的 STR_LITERAL/ASSERT 仅留在 jsonl，未冒称已逐条 KEEP | 不成立→KEEP+契约（夹具回传/LLM·IO 边界+结构化外部结果/CLI 装配/完成同步/DOM·fetch harness/P4 负向/UI 固定话语/fiscal oracle）；成立→FIX（归档 `make_thread`；草案/截止伪证已删）。P7 禁模板负向不作合法豁免 |
| **J19** | `j19-full-members.md`（共享 merge / normalize / 持久化 append 接缝） | 先 normalize 新名单；空→pop 不覆盖；非空→`merge_participant_roster_entries`；静默 id 残留 0 |
| **J18** | `j18-full-members.md`（存活读取 + 退役文档） | 删软判提案失效说明；死入口复扫 0；ADR/DELTA 退役标注 KEEP_RETIREMENT_DOC |

测试成本：复用归档三负向 + 删盯文/伪证；**无新增测试、不另造证明**。

## 2. 枚举真源

完整可复制命令：[`enum-cmd.txt`](enum-cmd.txt)（原 AST heredoc **照录**；复跑规模 MATCH：path_count=248 / py=4006 / ts=493）

- 机械候选（md 未涵盖全部故 **KEEP**）：[`j6-ast-candidates.jsonl`](j6-ast-candidates.jsonl)
- 最短命令结果：[`j6-ast-summary.json`](j6-ast-summary.json)
- 权威成员表：[`j6-full-members.md`](j6-full-members.md) / [`j19-full-members.md`](j19-full-members.md) / [`j18-full-members.md`](j18-full-members.md)
- 复扫：[`rescan-final.txt`](rescan-final.txt)

## 3. 聚焦测试（席位亲自；七 BIN=/usr/bin/false）

完整命令与结果：[`focused-tests.txt`](focused-tests.txt)

```
MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false \
python3 -m pytest -q \
  tests/test_menu_lifecycle_drain_396.py \
  tests/test_escort_route_1900.py \
  tests/test_audience_translate_1837.py \
  tests/test_audience_background.py \
  tests/test_audience_travel_gating_670.py \
  tests/test_grant_reconciliation_567.py

78 passed in 7.47s
```

前一次误用 `python`（非 `python3`）：**exit 127**，`python: command not found` — **未洗白**，不计入 pass。

（旧回执「17 passed」仅为更窄子集，不得覆盖本席位六文件全量结果。）

## 4. 变异

[`mutations.txt`](mutations.txt)：归档三负向不 start 红→绿；J19 静默 id 红→绿；J18 软判说明/死入口 0；`ALL_MUTATIONS_OK`。历史 timeout/死锁见 §0。

## 5. 自查二连

- 同类型：enum-cmd 补可执行 heredoc；范围声明焦点≠全部；禁样复扫 0；J19/J18 残留 0。
- 引入 bug：禁令陈述已纠正 checkout 史；不把 timeout/deadlock 改写成 infra。

## 6. SHA

- 证据更正：`f665b2008d23604a4062a50f1c26cb74c349bdb5`
- HEAD（本回执最终）：`7acdf777e7daec927110f0384e5a1ea25ed516b0`
