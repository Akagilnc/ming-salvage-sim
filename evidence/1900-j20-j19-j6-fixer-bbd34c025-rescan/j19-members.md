# J19 成员表：新交办名单严格参与人语义（完整类定义）

## 类定义
新交办名单沿既有严格参与人语义；清除字符串兼容与缺档猜「知情」的新默认；保留完整条目 equality 合并；不恢复人物 id 优先级；不新造冲突裁决。

## 枚举命令
见 `j19-enum-raw.txt`、`j19-deep.txt`、`j19-verify.txt`：
- 全部 `merge_participant_roster_entries` / `_normalize_participant_roster` / `strict_*` 调用
- 交办顶层与 grant 内 `participant_roster` 写入
- `知情` 默认与字符串名单路径
- `action_materialize` / `cli_backend.normalize_draft_person_roster` / 改草 `_merge_directive_payload`

## 入口矩阵与处置

| 入口 | 路径 | 严格？ | 处置 |
|---|---|---|---|
| 押解→roster | `declaration_dispatch._attach_commission_escort` merge `strict_incoming=True` + normalize `strict_structured=True` | 是 | **KEEP** |
| 交办顶层/grant 内名单 | `_attach_commission_staging_fields` merge `strict_incoming=True` | 是 | **KEEP**（上轮已收紧） |
| 仅 lead 无名单 | 同函数写结构化「主办」条目 | 显式结构化 | **KEEP** |
| 责成 assignment | `normalize_draft_person_roster`→`strict_structured=True` | 是 | **KEEP** |
| 成案/案卷写缝 | `db` 多处 `_normalize(..., strict_structured=True)` | 是 | **KEEP** |
| 改草 `_merge_directive_payload` | 原宽松 normalize+merge | 本轮前否 | **本轮 FIX**：`strict_structured=True` + `strict_incoming=True` |
| `merge` 默认 `strict_incoming=False`；existing 侧非严格 | 函数默认 | 默认宽松 | **KEEP 组别例外**：新交办/改草调用方已传 True；默认供非交办旧读缝，不在此恢复 id 先赢 |
| `create_issue` `_normalize(participants)` 非严格 | 局势立项 | 否 | **KEEP 组别例外**：非「新交办名单」边界；不扩开新机制 |
| `cli_backend` / `rescript_draft` | 已 `strict_structured=True` | 是 | **KEEP** |
| 完整条目 equality 追加 | `merge` 实现 | — | **KEEP**（同人异档均保留） |
| 字符串/缺档→知情（非严格分支本体） | `_normalize` else 支 | 兼容本体 | **KEEP 实现**；交办/改草入口不得走该支 |

## 核实探针（本轮）
- `strict_incoming=True` + 字符串 → ValueError「必须为对象」
- `strict_incoming=True` + 缺 tier → ValueError
- `strict_incoming=False` + 字符串 → 知情（仅非交办默认）
- 同人协办+主办两条 → equality 均保留
