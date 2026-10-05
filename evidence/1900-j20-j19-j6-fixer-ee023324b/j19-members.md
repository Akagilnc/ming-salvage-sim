# J19 成员表：新交办名单宽松兼容默认

## 类定义
新交办名单未走严格参与人语义：字符串兼容、缺档猜知情；须复用严格规范化+完整条目合并，不恢复 id 优先级。

## 枚举命令
- `rg -n -e 'merge_participant_roster_entries|_normalize_participant_roster\(' ming_sim --glob '*.py'`
- `rg -n -e 'strict_structured|strict_incoming' ming_sim --glob '*.py'`
- `rg -n -e 'tier_value or .*知情|character_id.*知情.*, "知情"' ming_sim --glob '*.py'`

## 成员
| 路径 | 语义 | 处置 |
|---|---|---|
| ming_sim/declaration_dispatch.py:~1118 merge_participant_roster_entries(existing, roster) 无 strict_incoming | 新交办名单宽松 | 传 strict_incoming=True |
| ming_sim/db.py:merge_participant_roster_entries 默认 strict_incoming=False；existing 侧也非严格 | 合并入口 | 交办调用收紧；保留函数默认供旧兼容调用方审查 |
| ming_sim/db.py:_normalize_participant_roster 非严格：字符串→知情、缺tier→知情、name别名 | 兼容语义本体 | 交办路径启用 strict_structured；不删既有严格分支 |
| 完整条目 equality 追加（merge 已实现） | 已有效 | 保留，不恢复 id 先赢 |
| cli_backend / 其它已 strict_structured=True 调用 | 既有严格通道 | 保留 |
