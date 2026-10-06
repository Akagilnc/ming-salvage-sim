# #1853 fixer enum — SQL-FAILURE-AS-EMPTY（表级兼容 + try→业务拒收/空）

## 类定义（判词全文，未收窄）
「必备 schema 不可用仍被表级兼容洗成无任所或输入缺字段拒收」
并入既有 SQL-FAILURE-AS-EMPTY。

## 枚举谓词
全仓 tracked 生产 `*.py`（排除 tests/archive/artifacts/evidence/scripts/spikes/docs/web）：

**A_TRY**：`try` 体触及 SQL/`set_character_office`/任所 resolver；handler 为宽 Exception/sqlite；
- IN_CLASS：洗成 `_office_appointment_failure`/rejected，或无 log 返回空业务态
- EXCLUDED：re-raise、savepoint 清理、typed `OfficeAppointmentRejection`、带 logger 的探测

**B_TABLE_PROBE**：`_table_exists("T")` / sqlite_master 名探测；`T` ∈ init_schema 必备表；
missing 分支洗成空任所或跳过查询后落入 missing_field/OfficeAppointmentRejection。

3. **C_EXCEPT_TO_BUSINESS_REJECTION**：`except Exception`（或裸 except）体调用 `_office_appointment_failure` 且无 re-raise——把 schema/SQL/代码故障洗成任命业务拒收。

## 边界排除（定罪例外，非实例白名单）
- 可选 Agno 表（`agno_*`）
- 首次 flush 才创建的 `rejection_reports`
- 初始化/迁移能力探测（`_ensure_*` / `seed_*` / `init_schema` / `migrate_*`）
- savepoint 清理后外层 re-raise
- 成功查询缺行、合法空任所、真正缺输入字段（无表探测降级）
- typed `OfficeAppointmentRejection` 业务拒收出口

## 命令
本目录旁内联 `python3` 枚举（写入 pre/post TSV）。

修后期望：`IN_CLASS-post.tsv` 仅表头（0 成员）。
