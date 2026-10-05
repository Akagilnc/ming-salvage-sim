# 1834 F21/F22 修内司回执（纠正轮）

HEAD_BASE（上轮交卷）: `4bc6994ca1bc7a2864624b078661ed1ff07a0345`
BRANCH: `ak-roles/1834-f21-f22-ebcd2d1a1`

## 本轮纠正范围（对复核三点）

1. **枚举收窄** → 撤回「四样本/前缀形即全类」；扩大 F21 谓词（根 launcher + 前端 replace/slice/substring/split/join + 带参 strip）；F22 按定义/类型/字段/参数/消费者全仓扫后**语义**判退役接缝。成员表见 `MEMBER_TABLE.md`（非 3800 行原始 grep）。
2. **伪变异** → 撤销 `mutation_temp_real_entry.py/.json`（见 `MUTATION_FAKE_REVOKED.txt`）。本轮用 `git show ebcd2d1a1` 完整旧函数装入真实入口；含物化入口当前绿。脚本只在 `/tmp`，不留永久证明测试。
3. **证据堆叠** → 删除本目录原始 broad/assign 清单与易炸的 `enum_cmds.sh`；保留可审成员表、命令计数、撤销说明、历史冻结记录不改写。

## 根因（不变）

- **F21**：自由字段（人读 `station`、高亮短语）在 map/物化/读取链被 `str.strip` 改写；官方 strip 返回删边副本。
- **F22**：退役零消费者结构残留；上轮仅删判词点名四样本，漏 `#1838` 废除的 generating scaffold 终态写点与死 `ChatResult`/`refresh_ministers`。

## 生产改动

| 类 | 本轮增量 |
|---|---|
| F21 | 上轮三站点修复保持；扩大枚举后无新增自由字段裁字落库成员 |
| F22 | DELETE `complete_rescript_summon_scaffold_turn`；DELETE `models.ChatResult`；DELETE `ChatTurnResult.refresh_ministers` |

## 真实入口旧红新绿

命令（七 BIN false 前缀 + `/tmp/1834-f21-f22-corr/real_entry_mutation.py`，取证后不入库脚本）：

```
current_mapper_preserved=true
current_hl_preserved=true
current_materialize_preserved=true
current_materialize_station="  山海关  "
old_mapper_preserved=false  old_mapper_station=山海关
old_hl_preserved=false      old_hl_read=["辽饷"]
old_materialize_preserved=false  old_materialize_station=山海关
old_map_src_chars=14279  old_parse_src_chars=420  old_apply_src_chars=1846
MUTATION_OK current_green_old_red real_old_funcs_from_ebcd2d1a1
```

完整 stdout：`mutation_real_entry.out`。
限制：装入的是 ebcd2d1a1 函数体到当前进程入口，不冒称真实模型验收；临时脚本不进仓。

## 保留项（摘要；全表见 MEMBER_TABLE.md）

- 机器键 / 判空副本 / 选项身份键 / origin_ref / station_region
- 现役 `secret_order_can_land`、`prepare_rescript_summon_scaffold`、召对结果契约字段（含无赋值但无退役权威的 appointed/registered/displaced——**不泛删**）
- 冻结 evidence 与上轮错误证明历史（撤销导航，不篡改旧文件正文）

## 聚焦测试

七前缀：`MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false`

- Python：`214 passed, 1 warning in 9.49s` → `pytest-focus.out`
- Web：`Test Files 5 passed；Tests 158 passed；Duration 3.99s` → `vitest-focus.out`

## Advisor

- 未改治理/Soul/配置；未 stash/amend/push/PR/kill。
- 未新建分类层或永久证明测试。
- 自查二连：同类型（退役接缝 vs 泛删；strip 判空 vs 赋值改写）；引入（删 scaffold 写点不影响 TAG_ENTER 现役消费）。
