# 全仓机械枚举命令（可复核；类定义全文谓词）

## 类一：实际事务提交权

谓词覆盖：`commit` / `rollback` / `BEGIN` / `SAVEPOINT|RELEASE|ROLLBACK TO` / 归属 `owns_transaction|connection_owns_transaction` / `in_transaction` / 暂停与深度 `_commit_suspended|_atomic_depth|_atomic_rollback_only|started_here` / `with atomic(|def atomic`

```bash
rg -n --glob '*.py' \
  -e '\.commit\(' -e '\.rollback\(' -e '\bBEGIN\b' -e '\bSAVEPOINT\b' -e 'RELEASE\b' -e 'ROLLBACK TO' \
  -e 'owns_transaction' -e 'connection_owns_transaction' -e 'in_transaction' \
  -e '_commit_suspended' -e '_atomic_depth' -e '_atomic_rollback_only' -e 'started_here' \
  -e 'with atomic\(' -e 'def atomic' \
  . --glob '!archive/**' --glob '!.venv/**' --glob '!**/node_modules/**'
```

- 完整命中：`class1-raw.txt`
- 逐成员语义分类（含测试/历史标注）：`class1-members.tsv`

## 类二：必备 DB 能力存在性 + 重复 SQL

```bash
rg -n --glob '*.py' -e 'hasattr\(' -e 'getattr\(' -e 'callable\(' \
  . --glob '!archive/**' --glob '!.venv/**' --glob '!**/node_modules/**'

rg -n --glob '*.py' \
  -e 'SELECT .*FROM (audience_nights|chat_turns|pending_actions|chat_messages|secret_orders)' \
  . --glob '!archive/**' --glob '!.venv/**'
```

- 完整命中：`class2-raw.txt` / `sql-raw.txt`
- 逐成员语义分类：`class2-members.tsv`
- 跨文件 SQL 重复组：`sql-cross-file-dups.tsv`（多数为同形查询多调用点；不属「失败呈现替身双实现」则表内标注）

## 召对失败重试真实调用链（不得凭文件名豁免）

静态入口：`web_app` / `cli/terminal` / `audience_*` / `decree_forecast` / `declaration_dispatch` / `session_write_queue`  
可达且供料：`materials` ← `decree_forecast.prepare_world_materials` / `session.prepare_scene_materials`；`knowledge` ← materials；另有 `action_materialize` / `urge_lever` / `audience_night` / `session` 任命辅助。

过月 `month_chain` 虽在 import 图可达，职责为结算供料/快照 → **不属类**（见 fixer 回执表）。
