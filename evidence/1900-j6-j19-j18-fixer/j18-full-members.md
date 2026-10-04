# J18 成员表 — 退役清理剩余死入口与失效说明

枚举命令见 [`enum-cmd.txt`](enum-cmd.txt)；机器表 [`j18-full-members.json`](j18-full-members.json)。

类定义（判词）：清除失去消费者的专用入口及描述已删除机制的说明；保留存活的一般密令案卷读取。

| 路径 | 行 | 处置 | 依据 |
|---|---|---|---|
| `ming_sim/db.py` | 14596–14602 | **FIX_DELETE** | `is_secret_order_dossier` 生产调用者=0 |
| `ming_sim/declaration_dispatch.py` | 381–382 | **FIX_DOC** | docstring 仍写「对账只落本段提案」——已删机制当现行 |
| `ming_sim/db.py` | `get_secret_order` / `list_secret_orders` / `get_dossier_for_secret_order` | **KEEP_LIVE_READ** | 一般密令案卷读取，边界禁止删除 |
| `ming_sim/db.py` | `payload_declares_escort` | **KEEP_LIVE** | `decree_forecast` + 自用，有消费者 |
| `ming_sim/materials.py` | `secret_order_dossier_ids` / `is_secret_order_origin` | **KEEP_LIVE_READ** | 存活一般读取 |
| `ming_sim/declaration_dispatch.py` | 1347 | **KEEP_RETIREMENT_NOTE** | 标明「已退役」 |
| `ming_sim/db.py` | 12299 | **KEEP_RETIREMENT_NOTE** | 标明「已退役」 |
| `docs/adr/0054-*.md` / `docs/DELTA_SCHEMA.md` | 退役划线说明 | **KEEP_RETIREMENT_NOTE** | 史档/划线退役说明，非现行假入口 |
| `docs/evidence/issue-1571/*` | 历史盘点 | **KEEP_HISTORICAL** | 旧票证据档，非生产入口 |
| `tests/test_grant_reconciliation_567.py` | 12 | **KEEP_RETIREMENT_NOTE** | 测试说明退役口径 |

死入口谓词：定义存在 ∧ 生产引用=0。失效说明谓词：仍以现行口吻描述已删机制（非「已退役」史注）。
