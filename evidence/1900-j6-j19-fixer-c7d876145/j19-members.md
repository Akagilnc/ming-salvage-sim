# J19 — 新合并口无消费者宽松模式（末份判词）

## 类定义
新参与人合并口中没有消费者的宽松模式及其不实例外说明。
删简无用模式；保留当前新交办／改草的严格输入和完整条目 equality 合并语义；
不扩大删除仍被其他业务使用的通用规范化能力；不新增冲突优先级或证明性测试。

## 枚举命令
```
rg -n 'merge_participant_roster_entries|_normalize_participant_roster|strict_incoming|strict_structured' ming_sim --glob '*.py'
PYTHONDONTWRITEBYTECODE=1 python3 - <<'PY'  # AST 生产调用清单 → j19-ast.jsonl
```
复扫输出：`j19-rescan.txt`

## 成员表（生产）

| 成员 | 语义 | 处置 |
|---|---|---|
| `ming_sim/db.py` `merge_participant_roster_entries` 原 `strict_incoming: bool = False` | 新合并口宽松默认；全生产 3 调用均显式 True；无消费者 | **FIX**：删除参数；incoming 恒 `strict_structured=True` |
| `ming_sim/db.py` 改草调用 `strict_incoming=True` | 参数调用 | **FIX**：去掉 kwargs |
| `ming_sim/declaration_dispatch.py` 押解合并 `strict_incoming=True` | 参数调用 | **FIX**：去掉 kwargs |
| `ming_sim/declaration_dispatch.py` 交办 staging `strict_incoming=True` | 参数调用 | **FIX**：去掉 kwargs |
| 旧证据「默认供非交办旧读缝」例外说明 | 不实例外说明 | **纠正**：本轮判定该消费者不存在；旧冻结 evidence 不改写 |
| `GameDB._normalize_participant_roster(..., strict_structured=False)` 默认 | 通用规范化，create_issue / 读缝等仍用 | **KEEP** |
| 完整条目 equality 追加（`item not in base`） | 合并语义 | **KEEP** |
| 按 character_id 静默先赢 | 已拆 | 不恢复 |

## 复扫
- `strict_incoming` 在 `ming_sim/` 零命中
- `merge_participant_roster_entries` 仅定义 + 3 调用（均无宽松开关）
- `_normalize_participant_roster` 仍服务其他业务
