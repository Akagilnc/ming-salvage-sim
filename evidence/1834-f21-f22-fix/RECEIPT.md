# 1834 F21/F22 修内司回执

HEAD_BASE: `ebcd2d1a168e46da52ccf7f3f898406b9e29e54f`
BRANCH: `ak-roles/1834-f21-f22-ebcd2d1a1`

## 根因

- **F21**：自由字段（人读 `station`、高亮短语）在输入映射 / 物化 / 读取链上被 `str.strip` 改写；前轮误标 `emptiness_predicate_only` 并申报全清。官方：`str.strip` 返回删去首尾空白的**副本**（https://docs.python.org/3/library/stdtypes.html#str.strip）。
- **F22**：退役零消费者结构（`_target_active_officeholder`、`night_dossiers_ready`、`directive_confirmation_ambiguous` 参数/透传/类型）被「出类 KEEP」留下。

## 枚举命令与完整成员表路径

- 命令脚本：`evidence/1834-f21-f22-fix/enum_cmds.sh`
- 运行日志：`evidence/1834-f21-f22-fix/enum_cmds_run.log`
- F21 broad（1748）：`enum_f21_broad.txt`
- F21 assign-strip（492→after）：`enum_f21_assign_strip.txt` / `enum_f21_assign_strip_after.txt`
- F21 samples：`enum_f21_samples.txt`
- F21 free-assign filter：`enum_f21_free_assign_candidates.txt`
- F22 named / consumer / keep-shared：`enum_f22_named.txt` / `enum_f22_consumer_proof.txt` / `enum_f22_keep_shared.txt`

未新增自动分类层；按下述数据流语义逐项处置。

## F21 修复项

| 成员 | 处置 |
|---|---|
| `ming_sim/rescript_actions.py` military_order 人读 `station` 写入 payload | FIX：判空用 `station.strip()` 副本；payload 保原文 |
| `ming_sim/db.py` `_apply_military_order_station_effect` 人读 `station` | FIX：`dest` 保原文；`station_region` 机器键 strip 保留 |
| `ming_sim/db.py` `_parse_highlights_json` | FIX：判空用副本；`out.append(item)` 保原文 |

## F21 旧错误 KEEP / 全清撤销

- REVOKED `emptiness_predicate_only@rescript_actions.py:776`：实际赋值改写人读 station，非仅判空。
- REVOKED `emptiness_predicate_only@db.py:16302`：`dest=strip(station)` 物化改写。
- REVOKED `emptiness_predicate_only@db.py:9184`：`out.append(item.strip())` 读取改写。
- REVOKED 前判「F16 整类全清」：以真实入口推翻未清读取/物化链；已修写入部分不否认，重开为 F21。

## F21 合法保留（摘录；完整候选见 enum 文件）

| 成员 | 理由 |
|---|---|
| `station_region` strip（db/content） | 结构化驻地机器键归一 |
| `office` / `transaction_category` strip（mapper/appointment） | 职衔/类目匹配机器键，非人读 station |
| materials `spoken if spoken.strip() else …` | 判空副本，写出原文 |
| `set_message_highlights` / highlight_judge 短语写出 | 已保原文；仅判空 |
| staged_commitment criterion/origin | F16 已保原文；JSON envelope strip 非自由字段值 |
| `recognize_*_command` 局部 `message.strip()` | 口令匹配副本，不回写存储正文 |
| matching `aliases.strip` | 别名身份机器键 |
| `web/src/highlights.ts` | 不裁字；对原文 `includes` |
| web format/reasoning 对 URL/model trim | 配置键归一 |
| `db.py` `requires_due = not station.strip()` | 仅判空，不改写 `normalized.station` |

## F22 修复项

| 成员 | 处置 |
|---|---|
| `_target_active_officeholder` | DELETE（零调用） |
| `night_dossiers_ready` | DELETE（零调用） |
| `ChatTurnResult.directive_confirmation_ambiguous` | DELETE（默认 None、无生产赋值） |
| `web_app._chat_payload` 参数与透传 | DELETE（仅透传、前端零消费） |
| `DirectiveConfirmationAmbiguous` 类型与字段 | DELETE（专属类型零消费） |

## F22 保留项

| 成员 | 理由 |
|---|---|
| `secret_order_can_land` / `secret_order_landing_gaps` | 现役真实消费者 |
| `_canonical_minister_key` | 现役真实消费者 |
| `_appointment_intent_is_current_office_noop` | 现役真实消费者 |
| `night_archive_metadata` / `night_scroll_container` | 现役真实消费者 |
| `evidence/1834-f18-f19-f20-fix` 冻结 KEEP 叙述 | 冻结失败记录保留不改；不接回旧机制 |

## Phase1 红绿与变异（临时真实入口；不造永久证明测试）

- 红：mapper / materialize / hl_read 均 rewrite；frontend `fresh=[]` vs `restored=['辽饷']`
- 绿：三者 `preserved=True`；frontend 对带空格原文短语可匹配
- 变异：`mutation_temp_real_entry.py` 在真实入口 monkeypatch 装回旧 strip；`mutation_temp_real_entry.json` 记 `verdict_old_logic_restored=true`，current green / old red
- 限制：入口函数替换与边界注入，不冒称真实模型验收；不新增永久证明测试或分类层

## 聚焦测试

- Python：`171 passed in 6.69s`（wall ~7.26s）→ `pytest-focus.out`
- Web：`158 passed` Duration ~3.98s（wall ~4.18s）→ `vitest-focus.out`

## Advisor 自审

- 动工前：读全局/仓级规则、ADR 0142、#1834/#1812、末份判词 F21/F22；官方 strip 语义已查。
- 提交前：未改治理/Soul；未接回旧机制；未造永久证明测试；冻结失败记录未改写；F22 共享能力保留；`git diff --check` 待提交前再查。
