# QA status

- Campaign: 残明朱批：崇祯
- SSE/campaign id: not visible in UI
- Year/turn/phase: 1627年10月; new game started;召对 opened;拟诏台 open
- Metrics: 国库320万两; 内库440万两; 威望/民心显示50/20; current UI header visible
- Completed: navigated to 127.0.0.1:8012; clicked 开始新游戏 and confirmed overwrite; skipped 后宫; opened 召对; entered treasury wording; reached 拟诏草案 panel; checked边政 panels were visible
- Blocker: clicking 新增草案 after entering「从国库拨银十万两解太仓备用」returned Internal Server Error (HTTP 500). Earlier 召对发送 returned network error. Stopped per task rule.

## Backend (from /tmp/ming-qa-8012.log)

- `POST /api/directives` → **500**
- Root: `sqlite3.OperationalError: attempt to write a readonly database`
- Stack: `web_app.api_create_directive` → `session.add_directive` → `db.add_directive` (db.py:19738)
- Same error on chat stream path: `open_night` / `attach_chat_turn_to_night` (audience_night.py)
- 8012 pid open fd still points at `data/saves/drained_1788597391116884628.db` (archived/drained). Code comments reference #396 readonly when workers keep old db handles.
- Evidence excerpts: `8012-directives-500.txt`, `8012-chat-readonly.txt`
