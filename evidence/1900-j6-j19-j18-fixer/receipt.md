# #1900 修内司回执：J6 / J19 / J18（复检续修）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1900-w5`
- 分支：`ak-roles/1900-j6-j19-j18-fixer-8785cd10a`
- 判词真源：`vault/.../1900-judge-8785cd10a-sealed4.json`（末份；前份仅参考）
- 禁令：无 stash / amend / rewrite / push / PR；未改 Soul/宪法/席位配置；未真调模型
- 变异还原：精确编辑 + `finally` 写回原文；**未** `git checkout/reset/stash`

## 1. 未结类别与处置

| 类 | 级别 | 处置 |
|---|---|---|
| **J6** | P2 | 截止/草案改结构化读侧；归档同步到 worker 完成+外部结果；删禁模板负向盯文 |
| **J19** | P2 | 复用 `GameDB.merge_participant_roster_entries`（normalize+equality，同 `_merge_directive_payload`） |
| **J18** | P3 | 维持：死入口已删、失效 docstring 已改；复扫无残留 |

## 2. 枚举

命令真源：[`enum-cmd.txt`](enum-cmd.txt)

权威成员表：
- [`j6-full-members.md`](j6-full-members.md) / [`j6-dispositions.json`](j6-dispositions.json)
- [`j19-full-members.md`](j19-full-members.md) / [`j19-dispositions.json`](j19-dispositions.json)
- [`j18-full-members.md`](j18-full-members.md) / [`j18-dispositions.json`](j18-dispositions.json)

复扫：[`rescan-final.txt`](rescan-final.txt) — J19 静默 helper/平行 loop 0；J18 死入口/失效说明 0；J6 样本盯文 0。

## 3. 逐类修复

### J6
- **截止**：删 prompt/`[chat_turn_id=…]` 哨兵；`list_chat_turns` + 非空消息条数 + `until_chat_turn_id` 参数长短契约。
- **草案**：`list_directives(turn/status)` + `get_dossier_for_directive` 界定 carryover；`prepare_character_materials` 仅跑通入口，不扫 opening/path。
- **归档三案**：`wait_until(closed ∧ move/close 完成 ∧ 外部文件/saves 结果)`，非 `attempts>0`。
- **travel_gating**：删除 `赴京/不能入殿/已传召/临时传` print 负向盯文；保留 unsettled/DB 结构化断言。
- 授权面其余命中标 `REVIEW_*`（不伪称 KEEP 合法）；P7 禁模板不作豁免。

### J19
- 抽出并复用 `GameDB.merge_participant_roster_entries`：`_normalize_participant_roster` 后 equality 追加。
- `_attach_commission_escort` / `_attach_commission_staging_fields` / `_merge_directive_payload` 同缝；不维第二份 id 优先规则。
- 持久化同人异档仍走 `append_decree_dossier_participants`（raise）。

### J18
- 无新残留；复扫确认。

## 4. 聚焦测试

七 BIN 前缀。结果：[`focused-tests.txt`](focused-tests.txt)

```
12 passed in 1.50s
real 2.42  user 1.82  sys 0.25
```

## 5. 变异（最低成本；无入库平行脚本）

一次性精确编辑 + finally 还原；日志 [`mutations.txt`](mutations.txt)。**未**入库 `_run_mutations.py`。

| 项 | 红 | 绿 |
|---|---|---|
| J6 截止（`cutoff_id=0`） | exit 1，`6 == 2` | pass |
| J6 草案（materials `<=`；tmp 探针） | exit 1 | 正式案 pass |
| J6 归档（跳过 WAL 回滚；直调 `_archive_move_db_files`） | exit 1 | lifecycle 案 pass |
| J19 静默 id | 主办统筹被吞 | escort 4 pass |
| J18 死入口 | rg 可见 / 还原后 GONE | — |

`ALL_MUTATIONS_OK`

## 6. 契约与成本

- 不为证明新造入库测试/平行框架；J19/草案/归档变异用 `tests/_tmp_*` 探针，跑完即删。
- 无新生产钩子；J19 仅把既有 merge 规则收束到 `GameDB` 单缝。
- 无界 `wait_until` 不用进程 timeout 当红证。

## 7. 自查二连

- 同类型：三类按谓词全仓枚举；P7 禁模板改为 REVIEW/FIXED，不标合法 KEEP。
- 引入 bug：未再 `git checkout` 抹产物；归档变异改直调接缝避免 hang。

## 8. SHA

`ecf3f66605ec97b1f528299c5d0d5f27f6632bbb`（working tree clean）
