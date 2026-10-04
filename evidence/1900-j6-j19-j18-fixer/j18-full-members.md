# J18 全仓成员表（权威）

类定义：清除无消费者专用入口与描述已删除提案机制的说明；保留存活一般密令读取。

死入口/失效说明复扫（见 enum-cmd）：生产专用入口 0；测试模块说明已改为「不接提案入参」。

| path | line | disposition | why | text |
|---|---|---|---|---|
| `ming_sim/materials.py` | 1295 | KEEP_LIVE_READ | 一般密令/护送声明读取接缝仍有消费者 | `def secret_order_dossier_ids(db: Any) -> set[int]:` |
| `ming_sim/db.py` | 859 | KEEP_LIVE_READ | 一般密令/护送声明读取接缝仍有消费者 | `def payload_declares_escort(payload: object) -> bool:` |
| `ming_sim/db.py` | 21998 | KEEP_LIVE_READ | 一般密令/护送声明读取接缝仍有消费者 | `def list_secret_orders(` |
| `ming_sim/db.py` | 22366 | KEEP_LIVE_READ | 一般密令/护送声明读取接缝仍有消费者 | `def get_secret_order(self, order_id: int) -> Optional[Dict[str, object]]:` |
| `docs/DELTA_SCHEMA.md` | 401 | KEEP_RETIREMENT_DOC | ADR/契约标注已退役字段，非生产死入口 | `### ~~`commissions[].secret_order.escort_pending_targets` / `escort_sources` / `` |
| `docs/adr/0054-ledger-cross-links-and-effect-backrefs.md` | 11 | KEEP_RETIREMENT_DOC | ADR/契约标注已退役字段，非生产死入口 | `#1900 的重构验收只引用 [#1812「重构验收（2026-10-02 陛下重定）」](https://github.com/Akagilnc/ming-s` |

本轮 FIX：`tests/test_grant_reconciliation_567.py` 模块说明去掉「软判提案」失效叙述。

软判提案残留复扫：0 hits（期望 0）。
