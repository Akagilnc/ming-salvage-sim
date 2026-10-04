# J18 全仓成员表（权威）

类定义：清除无消费者专用入口与失效说明；保留存活一般密令读取。

| path | line | disposition | why | text |
|---|---|---|---|---|
| `ming_sim/declaration_dispatch.py` | 2080 | KEEP_LIVE_READ | 存活一般读取 | order = db.get_secret_order(target_id) if hasattr(db, "get_secret_orde |
| `ming_sim/db.py` | 859 | KEEP_LIVE_READ | 存活一般读取 | def payload_declares_escort(payload: object) -> bool: |
| `ming_sim/db.py` | 12297 | KEEP_LIVE_READ | 存活一般读取 | return payload_declares_escort(payload) |
| `ming_sim/db.py` | 14944 | KEEP_LIVE_READ | 存活一般读取 | from ming_sim.materials import SECRET_ORDER_ORIGIN_PREFIX, is_secret_o |
| `ming_sim/db.py` | 14946 | KEEP_LIVE_READ | 存活一般读取 | if is_secret_order_origin(supplied): |
| `ming_sim/decree_forecast.py` | 297 | KEEP_LIVE_READ | 存活一般读取 | declared = payload_declares_escort(payload) |
| `ming_sim/month_translate.py` | 34 | KEEP_LIVE_READ | 存活一般读取 | "secret_dossiers": sorted(secret_order_dossier_ids(db)), |
| `ming_sim/decree.py` | 750 | KEEP_LIVE_READ | 存活一般读取 | for o in db.list_secret_orders(status="done"): |
| `ming_sim/covert_progress.py` | 662 | KEEP_LIVE_READ | 存活一般读取 | rows = list(db.list_secret_orders(status="active")) |
| `ming_sim/covert_progress.py` | 1782 | KEEP_LIVE_READ | 存活一般读取 | orders = list(db.list_secret_orders(status="active")) |
| `ming_sim/month_chain.py` | 195 | KEEP_LIVE_READ | 存活一般读取 | is_secret_order_origin(origin) |
| `ming_sim/month_chain.py` | 304 | KEEP_LIVE_READ | 存活一般读取 | secret_order_dossier_ids, |
| `ming_sim/month_chain.py` | 1204 | KEEP_LIVE_READ | 存活一般读取 | dict(o) for o in db.list_secret_orders(status="active") |
| `ming_sim/month_chain.py` | 1277 | KEEP_LIVE_READ | 存活一般读取 | o for o in db.list_secret_orders(status="active") |
| `tests/test_month_chain_1847.py` | 1641 | KEEP_LIVE_READ | 存活一般读取 | assert db.get_secret_order(order_id)["status"] == "active" |
| `tests/test_dossier_links_559.py` | 124 | KEEP_LIVE_READ | 存活一般读取 | before_orders = len(db.list_secret_orders()) |
| `tests/test_secret_order_monthly_progress_566.py` | 72 | KEEP_LIVE_READ | 存活一般读取 | emperor_order = next(item for item in db.list_secret_orders() if item[ |
| `tests/test_secret_order_section_rejections.py` | 56 | KEEP_LIVE_READ | 存活一般读取 | """正向守门（cmr r2 claude）：合法 active 密令 update 不被新 get_secret_order gate 误 |
| `tests/test_secret_order_section_rejections.py` | 91 | KEEP_LIVE_READ | 存活一般读取 | in_tx = db.get_secret_order(oid) |
| `tests/test_secret_order_section_rejections.py` | 96 | KEEP_LIVE_READ | 存活一般读取 | row = db.get_secret_order(oid) |
| `tests/test_secret_order_section_rejections.py` | 102 | KEEP_LIVE_READ | 存活一般读取 | """超 SQLite 64-bit 范围的 order_id（int() 不抛但 get_secret_order 绑定会 Overflo |
| `tests/test_grant_reconciliation_567.py` | 12 | KEEP_TEST_NOTE | 测试退役说明 | 不再有软判提案入参，坏提案拒收一族随之退役；实抵一律取引擎按护行口径算出的区间中位。 |
| `tests/test_secret_order_payoff_1504.py` | 384 | KEEP_LIVE_READ | 存活一般读取 | closed = db.get_secret_order(oid) |
| `tests/test_secret_order_payoff_1504.py` | 396 | KEEP_LIVE_READ | 存活一般读取 | before = str(db.get_secret_order(oid)["result"] or "") |
| `tests/test_secret_order_payoff_1504.py` | 705 | KEEP_LIVE_READ | 存活一般读取 | live = db.get_secret_order(oid) |
| `tests/test_secret_order_payoff_1504.py` | 800 | KEEP_LIVE_READ | 存活一般读取 | oid = int(db.list_secret_orders(status="active")[0]["id"]) |
| `tests/test_secret_order_payoff_1504.py` | 1508 | KEEP_LIVE_READ | 存活一般读取 | state.turn = int(db.get_secret_order(oid)["due_turn"]) |
| `docs/**` | — | KEEP_RETIREMENT_NOTE | 退役史注 | (retirement notes aggregated) |
| `docs/evidence/issue-1571/boundary-inventory.md` | 396 | KEEP_LIVE_READ | 存活一般读取 | / `list_secret_orders` @21408 / `get_dossier_for_secret_order`、`list_d |