# #1900 修内司回执：J6 / J19 / J18（末份判词 8785cd10a）

- 工作树：`/Users/akagilnc/WorkSpace/Ming_LLM-1900-w5`
- 分支：`ak-roles/1900-j6-j19-j18-fixer-8785cd10a`
- 基数：`8785cd10a`
- 判词真源：`~/.ak-roles/.../04-1900-judge-8785cd10a.json`（末份；前四份仅参考）
- N1：无代码施工（笼统禁令已撤销）
- 禁令：无 stash / amend / rewrite / push / PR；未改 Soul/宪法/席位配置；未真调模型

## 1. 未结类别与处置

| 类 | 级别 | 处置 |
|---|---|---|
| **J6** | P2 | 清盯文/未经失败路径证明；复用真实入口+外部结构化结果 |
| **J19** | P2 | 拆除按人物 id 静默保留先项；复用押解侧 equality 追加 |
| **J18** | P3 | 删死入口 `is_secret_order_dossier`；改失效 docstring；保留一般密令读取 |
| **N1** | — | 无施工 |

## 2. 枚举命令

完整真源：[`enum-cmd.txt`](enum-cmd.txt)

成员表：
- J6：[`j6-full-members.md`](j6-full-members.md) / [`j6-full-members.json`](j6-full-members.json)
- J19：[`j19-full-members.md`](j19-full-members.md) / [`j19-full-members.json`](j19-full-members.json)
- J18：[`j18-full-members.md`](j18-full-members.md) / [`j18-full-members.json`](j18-full-members.json)

复扫：[`rescan-final.txt`](rescan-final.txt) — J19/J18 残留 0；J6 失败案均有 move/close 尝试证据。

## 3. 逐类修复摘要

### J6
- 截止案：泄漏哨兵改搜结构化 `[chat_turn_id={later}]`，不再锁「后轮问/后轮答」正文。
- 草案隐私：断言 `draft-{id}` 未入 opening/目录/INDEX，不再锁草案正文。
- 归档失败三案：补 `move_attempts` / `close_attempts` + `wait_until`，证明 worker 实际走过失败路径。

### J19
- 删除 `_merge_participant_rosters`；staging 合并改为与 `_attach_commission_escort` 同形的 equality 追加。
- 现役 `append_decree_dossier_participants` / `_normalize_participant_roster` 未改。

### J18
- 删除无消费者 `is_secret_order_dossier`。
- `_persist_specialized_extraction` docstring 去掉「对账只落本段提案」现行口吻。
- `get_secret_order` / `list_secret_orders` / `secret_order_dossier_ids` 等一般读取保留。

## 4. 聚焦测试

前缀七 BIN=`/usr/bin/false`。命令与结果：[`focused-tests-final.log`](focused-tests-final.log)

```
10 passed in 1.02s
real 1.59  user 1.33  sys 0.21
```

触及：`test_audience_translate_1837` 截止案、`test_audience_background` 草案案、`test_menu_lifecycle_drain_396` 归档四案、`test_escort_route_1900`。

## 5. 变异红/绿

脚本：[`_run_mutations.py`](_run_mutations.py)（evidence 一次性；finally 还原源码）。日志：[`mutations.log`](mutations.log)

| 项 | 红 | 绿 |
|---|---|---|
| J6 截止（`cutoff_id=0`） | exit 1，`leak-turn-*` 入账 | pass |
| J6 草案（carryover ≤ 本回合） | exit 1，`draft-1` 入 opening | pass |
| J6 归档（C7 永不搬库） | timeout 124（wait 咬住） | pass |
| J19 静默 id（装回旧合并） | 主办统筹被吞 | 两条同人条目均在 |
| J18 死入口/失效说明 | 装回可见；删后 GONE | 复扫无 |

结论：`ALL_MUTATIONS_OK`

## 6. 测试契约与成本

- 不为证明新造入库测试；J19 变异用临时 `tests/_tmp_*` 探针，跑完即删。
- 断言只盯外部结构化结果（turn id / draft id / move·close 尝试 / roster 条目），不锁自由叙事。
- 无新生产机制；净删平行合并 helper + 死入口 + 失效说明。

## 7. 自查二连

- 同类型：三类均按谓词全仓枚举后处置，非点名白名单；J6 REVIEW 项（CLI argv / 禁模板句 / status 非泄漏）附例外依据。
- 引入 bug：变异脚本曾误 `git checkout` 抹生产修复 → 已重施并加 finally 还原；归档变异改 timeout 防无界 hang。

## 8. SHA

见提交后 `git rev-parse HEAD`。
