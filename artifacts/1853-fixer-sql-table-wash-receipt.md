# #1853 fixer apply — SQL-FAILURE-AS-EMPTY（必备 schema 降级）

## 未结类（判词）
**SQL-FAILURE-AS-EMPTY** / P2：「必备 schema 不可用仍被表级兼容洗成无任所或输入缺字段拒收」

## 枚举
目录：`artifacts/1853-fixer-enum-sql-table-wash/`（谓词见 `ENUM_COMMANDS.md`）

| 阶段 | 表 | 成员数 |
| --- | --- | --- |
| 修前真成员 | `r-tablewash-IN_CLASS-pre-true.tsv` | 4（db 两处表探测 + issues 两处 Exception→业务拒收） |
| 修后 | `r-tablewash-IN_CLASS-post.tsv` / `IN_CLASS-post.tsv` | 0 |
| 排除 | `r-tablewash-excluded-post.tsv` | ensure_office / agno / savepoint |

## 修复
1. `ming_sim/db.py`：`_require_local_office_region`、`character_office_region` 删除必备表 `_table_exists` 降级。
2. `ming_sim/issues.py`：`apply_office_appointment` 仅 typed `OfficeAppointmentRejection` → 业务拒收；其它异常 restore 后 re-raise；后宫退役改 typed refusal。
3. 测试适配响亮上抛：`tests/test_appointment_tenure_607.py`、`tests/test_faction_leverage_9.py`（契约仍验回滚）。

## 验证
七前缀 `/usr/bin/false`：聚焦 pytest **168 passed / 3.75s**。
独立探针：缺 `character_offices` → `OperationalError`（不再 `missing_field` / 空 archive_key）。
