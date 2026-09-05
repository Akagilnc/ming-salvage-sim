# Ming_LLM QA w11 playtest report (8010)

## Date reached
- Started: 1627-10 (天启七年十月) via 开始新游戏
- Reached: **崇祯元年二月 (1628-02)** — partial (~4 months of ~6 toward 1628-04)
- Hard stop: **8010 server process died** mid-settlement after Feb 批红 resolve (no listener on 127.0.0.1:8010)

## Stop state
- Last API turn before crash: year=1628 period=2 turn=5 phase=awaiting_decision, settlement_entry_inflight=true, pending_decisions=[] (after confirming 陕西动内帑 + 阉案复核)
- Log last lines: 结算 4/4 落库 + inertia/ongoing → relation-brew + chapter-memory nonstream start → then process gone
- Screenshot before crash: /tmp/ming-qa-8010-w11/shots/45-feb-awaiting.png

## Confirmed reproducible bugs
1. **Issue title leak (dialogue → 近期局势 / issues)**  
   Emperor prompts and minister reply prose appear as issue titles (e.g.「户部亏空日甚，太仓入不敷出。卿可据实奏对…」「臣杨嗣昌叩见皇上。…」). Seen from Nov onward; still present on Feb HUD. Related to closed error-leak work (#1730 family) — **regression**.

2. **Dual pending directives from one 拟旨**  
   After 毕自严 first audience, `pending_directive_count=2` / `/api/pending_actions` showed two `directive/拟旨` rows for the same minister turn. Possible **#1731 midzhi dual-extract regression**.

3. **Settlement ValueError: 无在途拨帑却收到对账提案**  
   Nov (turn2) settlement failed repeatedly; error packs `data/error_packs/turn2_attempt2` and `turn2_attempt3`. UI entered `awaiting_decision` with **empty** pending_decisions + 王承恩「有本待批」+ buttons 续跑结算 / 重新拉取待批决策. Repro: seal month after 内帑济辽-style grant path; observe dossier_reconciliations without in-flight grant. Eventually unblocked via UI 续跑结算 → Dec.

4. **Rescript draft shape failures (degraded)**  
   Log/packs: missing structured fields `account`/`purpose` on 拨饷 options (e.g. turn1 关宁急饷, turn2 关宁续饷, Feb 『宣大欠饷』缺少 purpose). Not always hard-stuck, but ticket-worthy.

5. **North Star gap: empty beat-coda / missing exit·closing·divider after 散夜**  
   Opening/entrance/aside present and strong; after 散夜 only「朕/退朝」+ minister farewell; `beat-coda` empty; no dedicated exit/closing/divider scene beats. Shots: 07/09/10/12 Bi audience; 31/35 Sun.

6. **Server crash during settle 4/4** (hard stop)  
   After Feb dual 批红, extractors finished; settle entered 4/4 relation-brew/chapter-memory; uvicorn on 8010 died (connection refused). Log: `/tmp/ming-qa-8010.log` around 17:27:43 JST.

## North Star notes
- **Like:** Opening (便殿灯影/时局冷气), entrance (宣入/殿门传宣), attendant aside (王承恩读心), dialogue quality for 毕自严/杨嗣昌/孙元化; 「宣入X入殿」layering.
- **Unlike:** Empty coda; weak/absent exit-closing-divider after 散夜; issue-title contamination breaks 近期局势 readability; 批红 gate + settlement fragility overshadows narrative flow.

## Screenshots
Folder: `/tmp/ming-qa-8010-w11/shots/`
