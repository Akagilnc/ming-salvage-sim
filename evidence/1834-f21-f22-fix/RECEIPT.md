# 1834 F21/F22 修内司回执（删简自验）

BASELINE: `ebcd2d1a168e46da52ccf7f3f898406b9e29e54f`
BRANCH: `ak-roles/1834-f21-f22-ebcd2d1a1`
PRODUCTION: `66b88fa77f5158c8f015d97480803e798283dd3e`
（最终 SHA 见本轮 commit stdout；回执不 stamp HEAD）

## 本轮删简

1. 删除本轮自建永久枚举脚本 `scripts/enum_f21_*.py` / `scripts/enum_f22_*.py` 与 wrapper `enum_cmds.sh`。
2. 删除重复全量原始索引 / 副本：`enum_out/f21_all_crop_write_shapes.jsonl`、`f21_freeish_crop_candidates.{jsonl,md}`、`f22_all_defs.jsonl`、`f22_zero_consumer_candidates.{jsonl,md}`、`f22_zero_disposition.tsv`、summary json。
3. 保留可审完整 `MEMBER_TABLE.md`、可执行短命令 `ENUM_CMDS.txt`、摘要结果（本回执 + pytest/vitest/mutation outs）。
4. 修净 `git diff --check ebcd2d1a1 HEAD` EOF 多空行：`MEMBER_TABLE.md`、`audience_translate.py`、`covert_progress.py`、`report.py`。
5. 不再提交 stamp 循环写 HEAD。

## 根因

- **F21**：人读自由字段不得 strip 改写落库；沿输入→写入→读取→物化→供料→前端显示保原文；判空用副本。
- **F22**：退役零消费者专属结构残留；删除须全仓函数名/字符串/动态引用复验，不得仅凭「公开 API 名」笼统 KEEP 或 DELETE。

## 生产改动摘要（PRODUCTION 相对 BASELINE）

| 类 | 处置 |
|---|---|
| F21 | FIX：`rescript_actions` station 保原文、`db` 物化/highlights 保原文；materials spoken / 前端 trim 判空赋原文 KEEP已正确 |
| F22 | DELETE：零消费者退役结构（见 MEMBER_TABLE DELETE 表）；零调用但无退役职责证据者逐条 KEEP |

## 枚举 / 成员表

- 命令：`evidence/1834-f21-f22-fix/ENUM_CMDS.txt`
- 成员表：`evidence/1834-f21-f22-fix/MEMBER_TABLE.md`
- 计数（历史枚举记录，表内完整）：F21 freeish=132；F22 zero 候选=124（abs 54 + prod_test_only 70）

## 复检（本轮）

- DELETE 符号全仓 absent（含字符串命中）：见 ENUM_CMDS F22 CMD；实测全 `hits=0`。
- F21 保原文站点仍在：见 ENUM_CMDS F21 CMD。
- 假变异：`MUTATION_FAKE_REVOKED.txt`（旧 temp 脚本判决作废）。
- 真实入口：`mutation_real_entry.out` → `current_green=true`；限制=只验证现役 preserve 站点 intact，不另造证明测试。

## 聚焦测试（七 BIN 前缀；仅空白/证据变更可复用）

`MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false`

- Python：`323 passed, 1 warning in 9.63s`（real 10.05s）→ `pytest-focus.out`
- Web：`Test Files 5 passed；Tests 158 passed；Duration 3.93s`（real 4.05s）→ `vitest-focus.out`

## Advisor

- 未改治理/Soul/配置；未 stash/amend/push/PR/kill/全量。
- 未新增证明测试、分类层或索引机制。
- 自查二连：同类型（证据堆叠/永久脚本 vs 成员表+短命令）；引入（EOF/删证据不影响生产语义）。
