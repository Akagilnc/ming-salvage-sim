# J18 全仓成员表（权威）

类定义：清除无消费者专用入口与失效说明；保留存活一般密令读取。

死入口复扫：`is_secret_order_dossier|对账只落本段提案|未提案目标的中位` → 0 hits。

| path | line | disposition | text |
|---|---|---|---|
| `ming_sim/materials.py` | 1295 | KEEP_LIVE_READ | def secret_order_dossier_ids(db: Any) -> set[int]: |
| `ming_sim/db.py` | 859 | KEEP_LIVE_READ | def payload_declares_escort(payload: object) -> bool: |
| `ming_sim/db.py` | 21996 | KEEP_LIVE_READ |     def list_secret_orders( |
| `ming_sim/db.py` | 22364 | KEEP_LIVE_READ |     def get_secret_order(self, order_id: int) -> Optional[Dict[str, ob |
