# #1900 修内司回执：J6 / J19 / J18（再次复检续修）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1900-w5`
- 分支：`ak-roles/1900-j6-j19-j18-fixer-8785cd10a`
- 判词真源：`vault/.../1900-judge-8785cd10a-sealed4.json`（末份；判词不变）
- 禁令：无 stash / amend / rewrite / push / PR；未改 Soul/宪法/席位配置；未真调模型
- 变异还原：精确编辑 + `finally` 写回原文；**未** `git checkout/reset/stash`

## 1. 未结类别与处置

| 类 | 级别 | 处置 |
|---|---|---|
| **J6** | P2 | 删草案伪证整条；删截止平行块（不宣称证明截止）；归档改真实 Thread join；P7 不作豁免 |
| **J19** | P2 | 共用 `merge_participant_roster_entries`；`_merge_directive_payload` 一次 merge，空 incoming pop |
| **J18** | P3 | 维持死入口已删；复扫 0 |

## 2. 明确不再证明

- **草案**：`test_current_unissued_draft_is_not_character_carryover` 已整条删除（自算 carryover_ids + prepare 无断言 = 伪证）。不另造。
- **截止**：删除 `_strictly_before` / SQL count / `len(night_said)` 平行块；保留未知 section / 坏形状拒收负向。**不宣称证明截止**（boundary：不据测试缺陷指控生产截止错误）。

## 3. 枚举

命令真源：[`enum-cmd.txt`](enum-cmd.txt)

权威成员表（**仅 md，已删平行 `*-dispositions.json`**）：
- [`j6-full-members.md`](j6-full-members.md)
- [`j19-full-members.md`](j19-full-members.md)
- [`j18-full-members.md`](j18-full-members.md)

复扫最短结果：[`rescan-final.txt`](rescan-final.txt)
- 本轮禁样（LEAK/`_strictly_before`/draft 伪证/`len(night_said)`/attempt-only wait）= 0
- 归档三失败案 `wait_until` = 0
- J19 静默 id / 平行 loop = 0
- J18 死入口 = 0
- P7 相关命中标 `REVIEW_PROSE_ILLEGAL_EXEMPTION`（评论/罐头回声），**不**标合法 KEEP

## 4. 逐类修复

### J6
- 截止：只留拒收负向；不证截止。
- 草案：整条删除。
- 归档三案：`api_menu_new_game` → 线程工厂保留真实 Thread → `join`（仅已 start）→ 再断言 `closed`/move/外部文件。无生产钩子。
- travel_gating：先前已删 print 禁模板负向；维持。

### J19
- `_merge_directive_payload`：去掉先 normalize 再 merge 的重复；`add_roster` 非空则一次 `merge_participant_roster_entries`，否则 pop（空 incoming 保留旧名册）。

### J18
- 无新残留。

## 5. 聚焦测试（七 BIN=/usr/bin/false）

结果：[`focused-tests.txt`](focused-tests.txt)

```
11 passed in 0.82s
real 1.24  user 1.05  sys 0.15
```

（草案案已删，故由 12→11。）

## 6. 变异（精确编辑 + finally；无入库平行脚本）

日志：[`mutations.txt`](mutations.txt)

| 项 | 红 | 绿 |
|---|---|---|
| J6 归档：`_spawn_drain_close` 构造 Thread 但不 start | 三案 `assert [] == [1]`（worker 未跑） | 3 passed |
| J19 静默 id keep-first | 主办统筹被吞 | escort 4 passed |
| J18 死入口 | rg 可见 / 还原后 GONE | — |
| 拒收负向（不证截止） | — | 1 passed |

`ALL_MUTATIONS_OK`。**无 cutoff/draft 变异**（不再证明这两项）。

## 7. 自查二连

- 同类型：全仓谓词复扫；P7 不作合法豁免；删平行 json。
- 引入 bug：同步跑 worker 曾死锁，已改真实 Thread join；变异压制 start 时只 join 已启动线程，红在行为断言而非 RuntimeError。

## 8. SHA

见提交后 `git rev-parse HEAD`。
