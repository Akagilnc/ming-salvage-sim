# #1853 fixer apply — SQL-FAILURE-AS-EMPTY（必备 schema 降级）

## 未结类（判词）
**SQL-FAILURE-AS-EMPTY** / P2：「必备 schema 不可用仍被表级兼容洗成无任所或输入缺字段拒收」

## 枚举
目录：`artifacts/1853-fixer-enum-sql-table-wash/`（谓词见 `ENUM_COMMANDS.md`）

全仓生产 `*.py`（排除 tests/archive/artifacts/evidence/scripts/spikes/docs/web），谓词覆盖判词全文：

- **B_TABLE_PROBE**：`_table_exists("T")` / sqlite_master 名探测；T∈init_schema 必备；missing 洗成空任所或跳查询后 missing_field
- **A_TRY**：try 体触及 SQL/任所写；宽 Exception 洗成 `_office_appointment_failure`/rejected 或无 log 空态

| 阶段 | 表 | 成员数 |
| --- | --- | --- |
| 修前真成员 | `IN_CLASS-pre.tsv` / `r-tablewash-IN_CLASS-pre-true.tsv` | 4（db 两处表探测 + issues 两处 Exception→业务拒收） |
| 修后 | `IN_CLASS-post.tsv` | **0** |
| 排除 | `class-excluded-post.tsv` | ensure_office 初始化 / agno 可选 / rejection_reports / savepoint re-raise / typed OfficeAppointmentRejection |

## 修复
1. `ming_sim/db.py`：`_require_local_office_region`、`character_office_region` 删除必备表 `_table_exists` 降级；缺表 SQL 响亮失败。
2. `ming_sim/issues.py`：`apply_office_appointment` 仅 typed `OfficeAppointmentRejection` → 业务拒收；其它异常 restore 后 re-raise；后宫退役改 typed refusal。
3. `ming_sim/issues.py`：派生任命（放归/赦还）路径代码故障上抛前共用 `_restore_pre_derive_person_state`，DB+内存与业务拒收同口径还原。
4. 测试契约对齐响亮上抛并仍验回滚：`test_faction_leverage_9`、`test_appointment_tenure_607`、`test_person_delta_adapter`（业务拒收 per-item 案改注 `OfficeAppointmentRejection`）。

## 边界保留（非白名单实例）
- Agno 可选表探测
- `rejection_reports` 首次 flush 才建
- `_ensure_office_type_parents` 初始化/迁移表检查
- 成功查询缺行 / 合法空任所 / 真缺字段 → 既有业务判断

## 验证
七前缀 `MING_SIM_{AGY,CODEX,CLAUDE,CURSOR,KIMI,GROK,PI}_BIN=/usr/bin/false`：

```text
tests/test_faction_leverage_9.py::test_failed_appointment_rolls_back_faction_leverage
tests/test_person_delta_adapter.py
tests/test_office_inference.py
tests/test_character_knowledge_489.py
tests/test_audience_commit_failure_1853.py
→ 195 passed, 1 skipped in 4.47s
```

独立探针（判词同法：RENAME character_offices）：
`project` / `character_office_region` / `set_character_office` omit-region / `apply_office_appointment`
全部 `OperationalError: no such table: character_offices`；**不再** `missing_field` / 空 archive_key；表名恢复后投影复原。`VERDICT PASS`。
