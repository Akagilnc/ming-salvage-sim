# F3 删除侧成员表（52809cdf3→HEAD）

依据：`rejudge-deletion-side.json`；逐条对照旧源码夹具来源实读。**样本非白名单**。F14 本轮不处理。

成员总数：**175**；RESTORE 到位：**175**；PENDING：**0**

| # | file:old | class | disposition | source (fixture) | basis |
| --- | --- | --- | --- | --- | --- |
| 000 | `tests/test_army_card_status_1501.py:181` | T_TRANSPARENT_FIXTURE | RESTORE | `欠饷严重` | 对照旧源码夹具种子；确定性调用输入或结构化字段 |
| 001 | `tests/test_army_card_status_1501.py:213` | T_TRANSPARENT_FIXTURE | RESTORE | `欠饷严重` | 对照旧源码夹具种子；确定性调用输入或结构化字段 |
| 002 | `tests/test_army_display_173.py:129` | T_TRANSPARENT_FIXTURE | RESTORE | `"SELECT id FROM armies WHERE owner_power='ming' ORDER BY id LIMIT 1"` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 003 | `tests/test_audience_continuous_507.py:50` | T_TRANSPARENT_FIXTURE | RESTORE | `heard = _public(db, nid, "徐光启", "徐光启奏：宜用洪承畴督师陕西。")` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 004 | `tests/test_audience_continuous_507.py:72` | T_TRANSPARENT_FIXTURE | RESTORE | `_public(db, nid, "徐光启", "徐光启方入奏水利。")` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 005 | `tests/test_audience_continuous_507.py:99` | T_TRANSPARENT_FIXTURE | RESTORE | `_public(db, nid, "徐光启", "徐光启奏：陕西糜烂，非洪承畴不可。")` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 006 | `tests/test_audience_restore_505.py:216` | T_TRANSPARENT_FIXTURE | RESTORE | `_land_full_turn(db, state, minister, "四轮问对之一", "臣愚见如此。")` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 007 | `tests/test_audience_restore_505.py:217` | T_TRANSPARENT_FIXTURE | RESTORE | `_land_full_turn(db, state, minister, "四轮问对之一", "臣愚见如此。")` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 008 | `tests/test_audience_restore_505.py:292` | T_TRANSPARENT_FIXTURE | RESTORE | `answer` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 009 | `tests/test_audience_restore_505.py:332` | T_TRANSPARENT_FIXTURE | RESTORE | `ct = _land_full_turn(db, state, minister, "退朝", "臣遵旨。")` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 010 | `tests/test_audience_restore_505.py:335` | T_TRANSPARENT_FIXTURE | RESTORE | `db, state, content = restore_env.db, restore_env.state, restore_env.content` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 011 | `tests/test_audience_restore_505.py:452` | T_TRANSPARENT_FIXTURE | RESTORE | `answer` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 012 | `tests/test_audience_scroll_539.py:263` | T_TRANSPARENT_FIXTURE | RESTORE | `"role", "speaker", "audibility", "time", "content",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 013 | `tests/test_audience_scroll_539.py:268` | T_TRANSPARENT_FIXTURE | RESTORE | `"role", "speaker", "audibility", "time", "content",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 014 | `tests/test_audience_scroll_539.py:513` | T_TRANSPARENT_FIXTURE | RESTORE | `current_turn, _ = append_night_chat(db, state, current_night, "杨嗣昌", "本夜问话", "本夜` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 015 | `tests/test_audience_translate_1837.py:476` | T_TRANSPARENT_FIXTURE | RESTORE | `return SimpleNamespace(content="臣等遵旨。", tools=[])` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 016 | `tests/test_audience_translate_1837.py:739` | T_TRANSPARENT_FIXTURE | RESTORE | `return SimpleNamespace(content="臣在。", tools=[])` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 017 | `tests/test_audience_translate_1837.py:739` | T_TRANSPARENT_FIXTURE | RESTORE | `return SimpleNamespace(content="臣在。", tools=[])` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 018 | `tests/test_audience_translate_1837_reopen.py:369` | T_TRANSPARENT_DISK_OR_READ | RESTORE | `query = "去查那件未见于词表的事，原话留档。"` | 测试自写固定字节经 read_material/API/磁盘读回；独立输入透明搬运 |
| 019 | `tests/test_audience_translation_1838.py:346` | T_TRANSPARENT_FIXTURE | RESTORE | `"context": "当殿为赈灾站台",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 020 | `tests/test_breach_plea_623.py:381` | T_TRANSPARENT_FIXTURE | RESTORE | `撤令不再被当作无结构纯正文（special_decree/policy/commission-text）暂存。` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 021 | `tests/test_cli_backend.py:467` | T_TRANSPARENT_FIXTURE | RESTORE | `yield _Delta(reasoning_content="先核辽饷账目…")` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 022 | `tests/test_cli_play_turn.py:470` | T_TRANSPARENT_FIXTURE | RESTORE | `awaiting=False, advanced=True, report="留中案卷本月重判月报",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 023 | `tests/test_cli_runner_error_typed_1299.py:89` | T_TRANSPARENT_FIXTURE | RESTORE | `monkeypatch.setattr(cc, "_call_cli", lambda p: ("臣遵旨，边事容臣细奏。", 1))` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 024 | `tests/test_declaration_dispatch_1835.py:76` | T_TRANSPARENT_FIXTURE | RESTORE | `"body": "抱恙数日，仍可视事",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 025 | `tests/test_declaration_dispatch_1835.py:219` | T_TRANSPARENT_FIXTURE | RESTORE | `{"subject_kind": "character", "subject_id": minister, "body": "如实记事"},` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 026 | `tests/test_declaration_dispatch_1835.py:747` | T_TRANSPARENT_FIXTURE | RESTORE | `{"subject_kind": "character", "subject_id": minister, "body": "旨三：后到之旨"},` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 027 | `tests/test_declaration_dispatch_1835.py:762` | T_TRANSPARENT_FIXTURE | RESTORE | `{"subject_kind": "character", "subject_id": minister, "body": "旨三：后到之旨"},` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 028 | `tests/test_declaration_dispatch_1835.py:791` | T_TRANSPARENT_FIXTURE | RESTORE | `"subject_kind": "character", "subject_id": minister, "body": "旨三：首次暂存",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 029 | `tests/test_declaration_dispatch_1835.py:808` | T_TRANSPARENT_FIXTURE | RESTORE | `"subject_kind": "character", "subject_id": minister, "body": "旨三：首次暂存",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 030 | `tests/test_decree_commitment_settlement_229.py:1444` | T_TRANSPARENT_FIXTURE | RESTORE | `"narrative": "皇帝已复试孙承宗，此承诺已由圣裁处理。",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 031 | `tests/test_decree_dossiers_571.py:536` | T_TRANSPARENT_FIXTURE | RESTORE | `promulgation_reason` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 032 | `tests/test_decree_dossiers_571.py:1082` | T_TRANSPARENT_FIXTURE | RESTORE | `# #1624：组合契约先过；本测专咬参与人，补事务类别以免挡在组合闸` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 033 | `tests/test_decree_dossiers_571.py:1621` | T_TRANSPARENT_FIXTURE | RESTORE | `不足额` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 034 | `tests/test_decree_dossiers_571.py:1621` | T_TRANSPARENT_FIXTURE | RESTORE | `不足额` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 035 | `tests/test_decree_dossiers_571.py:1996` | T_TRANSPARENT_FIXTURE | RESTORE | `应拨10两` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 036 | `tests/test_decree_dossiers_571.py:1997` | T_TRANSPARENT_FIXTURE | RESTORE | `实拨{abs(expected_actual)}两` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 037 | `tests/test_decree_dossiers_571.py:2115` | T_TRANSPARENT_FIXTURE | RESTORE | `dossier_id, "fulfilled", "押解到陕", state.turn,` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 038 | `tests/test_deepseek_thinking_disable_1797.py:209` | T_TRANSPARENT_FIXTURE | RESTORE | `reasoning_content="思考过程甲",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 039 | `tests/test_deepseek_thinking_disable_1797.py:210` | T_TRANSPARENT_FIXTURE | RESTORE | `reasoning="中转 reasoning 正文",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 040 | `tests/test_dossier_reported_progress_619.py:95` | T_TRANSPARENT_FIXTURE | RESTORE | `memorial_text` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 041 | `tests/test_dossier_reported_progress_619.py:140` | T_TRANSPARENT_FIXTURE | RESTORE | `"memorial_text": "首批已出关619",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 042 | `tests/test_dossier_reported_progress_619.py:146` | T_TRANSPARENT_FIXTURE | RESTORE | `"SELECT dossier_progress_json FROM secret_orders WHERE id=?", (order_id,),` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 043 | `tests/test_dossier_reported_progress_619.py:237` | T_TRANSPARENT_FIXTURE | RESTORE | `memorial_text` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 044 | `tests/test_dossier_reported_progress_619.py:252` | T_TRANSPARENT_FIXTURE | RESTORE | `{"dossier_id": transformed_id, "outcome": "transformed", "note": "名实已乖"},` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 045 | `tests/test_dossier_reported_progress_619.py:306` | T_TRANSPARENT_FIXTURE | RESTORE | `memorial_text` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 046 | `tests/test_event_trigger_gate.py:1418` | T_TRANSPARENT_FIXTURE | RESTORE | `本局按盘面软判` | 对照旧源码夹具种子；确定性调用输入或结构化字段 |
| 047 | `tests/test_event_trigger_gate.py:1421` | T_TRANSPARENT_FIXTURE | RESTORE | `卢象升生死由软判` | 对照旧源码夹具种子；确定性调用输入或结构化字段 |
| 048 | `tests/test_event_trigger_gate.py:1422` | T_TRANSPARENT_FIXTURE | RESTORE | `本局按盘面软判援锦主帅` | 对照旧源码夹具种子；确定性调用输入或结构化字段 |
| 049 | `tests/test_execution_joint_liability_565.py:405` | T_TRANSPARENT_FIXTURE | RESTORE | `merged = db.merge_execution_note(dossier_id, "对账差额：应拨十两实拨三两")` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 050 | `tests/test_faction_brew_637.py:139` | T_TRANSPARENT_FIXTURE | RESTORE | `皇党` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 051 | `tests/test_faction_brew_637.py:140` | T_TRANSPARENT_FIXTURE | RESTORE | `阉党` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 052 | `tests/test_faction_brew_637.py:174` | T_TRANSPARENT_FIXTURE | RESTORE | `brew_fn = _dual_brew_fn_factory(calls, stance="东林因钱谦益蒙召对而势涨。")` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 053 | `tests/test_faction_brew_637.py:232` | T_TRANSPARENT_FIXTURE | RESTORE | `brew_fn = _dual_brew_fn_factory(calls, stance="皇党内因温周之隙而生嫌隙。")` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 054 | `tests/test_faction_brew_637.py:277` | T_TRANSPARENT_FIXTURE | RESTORE | `brew_fn = _dual_brew_fn_factory(calls, stance="皇党旧文。")` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 055 | `tests/test_family_tail_restore_570.py:185` | T_TRANSPARENT_FIXTURE | RESTORE | `"memorial_text": "已出京赴陕",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 056 | `tests/test_fiscal_levy_effect.py:1576` | T_TRANSPARENT_FIXTURE | RESTORE | `[{"decision_key": row["decision_key"], "note": "姑候户部再核"}],` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 057 | `tests/test_gazette_author_1862.py:375` | T_TRANSPARENT_DISK_OR_READ | RESTORE | `seen["author_files"] = files` | 测试自写固定字节经 read_material/API/磁盘读回；独立输入透明搬运 |
| 058 | `tests/test_gazette_author_1862.py:376` | T_TRANSPARENT_DISK_OR_READ | RESTORE | `seen["author_files"] = files` | 测试自写固定字节经 read_material/API/磁盘读回；独立输入透明搬运 |
| 059 | `tests/test_gazette_author_1862.py:378` | T_TRANSPARENT_DISK_OR_READ | RESTORE | `seen["author_files"] = files` | 测试自写固定字节经 read_material/API/磁盘读回；独立输入透明搬运 |
| 060 | `tests/test_gazette_author_1862.py:439` | T_TRANSPARENT_DISK_OR_READ | RESTORE | `return json.dumps({"title": _TITLE, "report": _REPORT}, ensure_ascii=False)` | 测试自写固定字节经 read_material/API/磁盘读回；独立输入透明搬运 |
| 061 | `tests/test_grant_reconciliation_567.py:199` | T_TRANSPARENT_FIXTURE | RESTORE | `"memorial_text": "护行路已核关防，实银可期",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 062 | `tests/test_highlight_judge_544.py:227` | T_TRANSPARENT_FIXTURE | RESTORE | `done = next(e for e in events if e["type"] == "done")` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 063 | `tests/test_highlight_judge_544.py:272` | T_TRANSPARENT_FIXTURE | RESTORE | `assert seen_reply == ["臣先陈军务。"]` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 064 | `tests/test_highlight_judge_544.py:306` | T_TRANSPARENT_FIXTURE | RESTORE | `return ChatTurnResult(answer="臣陈辽饷。")` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 065 | `tests/test_highlight_judge_544.py:357` | T_TRANSPARENT_FIXTURE | RESTORE | `return ChatTurnResult(answer="臣遵旨。")` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 066 | `tests/test_impeachment_surge_655.py:162` | T_TRANSPARENT_FIXTURE | RESTORE | `"title": "  自由题名  ", "stage_text": "原样案情。",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 067 | `tests/test_mechanical_tail_1845.py:569` | T_TRANSPARENT_FIXTURE | RESTORE | `ending_outcome={"status": "emperor_abdicate", "summary": "退位"},` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 068 | `tests/test_month_call_recovery_1846.py:296` | T_TRANSPARENT_FIXTURE | RESTORE | `return "世界段已成文。"` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 069 | `tests/test_month_call_recovery_1846.py:575` | T_TRANSPARENT_FIXTURE | RESTORE | `return "世界段已成文。"` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 070 | `tests/test_month_chain_1847.py:704` | T_TRANSPARENT_FIXTURE | RESTORE | `this_decree` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 071 | `tests/test_month_chain_1847.py:776` | T_TRANSPARENT_FIXTURE | RESTORE | `"问前事实。"` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 072 | `tests/test_month_chain_1847.py:781` | T_TRANSPARENT_FIXTURE | RESTORE | `"问前事实。"` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 073 | `tests/test_month_chain_1847.py:2036` | T_TRANSPARENT_FIXTURE | RESTORE | `"world_text": "世界段原文·密报可读。",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 074 | `tests/test_month_chain_1847.py:2076` | T_TRANSPARENT_DISK_OR_READ | RESTORE | `fact_body = "文字事实正文：边材已动。\r\n同一条事实的第二行。  \r"` | 测试自写固定字节经 read_material/API/磁盘读回；独立输入透明搬运 |
| 075 | `tests/test_month_translate_1840.py:212` | T_TRANSPARENT_FIXTURE | RESTORE | `{"subject_kind": "character", "subject_id": person, "body": "人物先记一事"},` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 076 | `tests/test_month_translate_1840.py:213` | T_TRANSPARENT_FIXTURE | RESTORE | `{"subject_kind": "army", "subject_id": army, "body": "军队先记一事"},` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 077 | `tests/test_month_translate_1840.py:389` | T_TRANSPARENT_FIXTURE | RESTORE | `see old context` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 078 | `tests/test_month_translate_1840.py:456` | T_TRANSPARENT_FIXTURE | RESTORE | `"subject_kind": "character", "subject_id": person, "body": "前一段已落",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 079 | `tests/test_on_scene_immediate_write_1839.py:131` | T_TRANSPARENT_DISK_OR_READ | RESTORE | `arm_injury = "左臂中箭，血透重甲，犹力战不退"` | 测试自写固定字节经 read_material/API/磁盘读回；独立输入透明搬运 |
| 080 | `tests/test_on_scene_immediate_write_1839.py:134` | T_TRANSPARENT_DISK_OR_READ | RESTORE | `death_rumour = "关外传袁崇焕已死于宁远城下"` | 测试自写固定字节经 read_material/API/磁盘读回；独立输入透明搬运 |
| 081 | `tests/test_person_delta_adapter.py:236` | T_TRANSPARENT_FIXTURE | RESTORE | `"new_issues": [` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 082 | `tests/test_person_delta_adapter.py:241` | T_TRANSPARENT_FIXTURE | RESTORE | `"title": "安抚毛文龙·进行中",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 083 | `tests/test_pihong_dossier_1490.py:381` | T_TRANSPARENT_FIXTURE | RESTORE | `choice = {'decision_key': db.list_rescript_desk(int(state.turn))[0]['decision_ke` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 084 | `tests/test_pihong_dossier_1490.py:407` | T_TRANSPARENT_FIXTURE | RESTORE | `"""#1492 D 真 HTTP：合法能力对 + 撒谎 label/hint → 落库取服务端 option，客户端只留 note。"""` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 085 | `tests/test_pihong_dossier_1490.py:503` | T_TRANSPARENT_FIXTURE | RESTORE | `choice = {'decision_key': db.list_rescript_desk(int(state.turn))[0]['decision_ke` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 086 | `tests/test_pihong_dossier_1490.py:2015` | T_TRANSPARENT_FIXTURE | RESTORE | `def test_657_default_hold_preserves_red_pen_note(game):` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 087 | `tests/test_pihong_dossier_1490.py:2926` | T_TRANSPARENT_FIXTURE | RESTORE | `items = [{'title': '太仓亏空', 'context': '太仓见底，边饷催迫。', 'options': [raw['assignment_` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 088 | `tests/test_pihong_dossier_1490.py:2929` | T_TRANSPARENT_FIXTURE | RESTORE | `assignment = round_a['责户部清理钱粮亏短']` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 089 | `tests/test_pihong_dossier_1490.py:2945` | T_TRANSPARENT_FIXTURE | RESTORE | `grant = round_b['发内帑周转军国急用']` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 090 | `tests/test_pihong_dossier_1490.py:2955` | T_TRANSPARENT_FIXTURE | RESTORE | `assignment = round_a['责户部清理钱粮亏短']` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 091 | `tests/test_pihong_dossier_1490.py:3013` | T_TRANSPARENT_FIXTURE | RESTORE | `raw = _1778_raw_options()` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 092 | `tests/test_player_payload_1022.py:40` | T_TRANSPARENT_FIXTURE | RESTORE | `see old context` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 093 | `tests/test_public_projection_consistency_1830.py:170` | T_TRANSPARENT_DISK_OR_READ | RESTORE | `see old context` | 测试自写固定字节经 read_material/API/磁盘读回；独立输入透明搬运 |
| 094 | `tests/test_public_projection_consistency_1830.py:171` | T_TRANSPARENT_DISK_OR_READ | RESTORE | `see old context` | 测试自写固定字节经 read_material/API/磁盘读回；独立输入透明搬运 |
| 095 | `tests/test_public_projection_consistency_1830.py:172` | T_TRANSPARENT_DISK_OR_READ | RESTORE | `see old context` | 测试自写固定字节经 read_material/API/磁盘读回；独立输入透明搬运 |
| 096 | `tests/test_qa_b3_409_ux.py:245` | T_TRANSPARENT_FIXTURE | RESTORE | `return "邸报：已裁。"` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 097 | `tests/test_qa_s2_copy_prompts_1356_1402.py:126` | T_TRANSPARENT_FIXTURE | RESTORE | `(0, 1627, 9, "天启七年九月邸报\n\n一、真结算九月报文·payload 钉"),` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 098 | `tests/test_qa_t1_extraction_dual_source_1353.py:589` | T_TRANSPARENT_FIXTURE | RESTORE | `minister = next(iter(game.content.characters))` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 099 | `tests/test_relation_brew_636.py:435` | T_TRANSPARENT_FIXTURE | RESTORE | `甲句。\n乙句。\n乙二句。` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 100 | `tests/test_relation_brew_636.py:603` | T_TRANSPARENT_FIXTURE | RESTORE | `brew_fn.outputs = [_script(foundings=["越次一召，擢杨嗣昌于五品郎中。"], recent="原文一")]` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 101 | `tests/test_relation_read_640.py:129` | T_TRANSPARENT_FIXTURE | RESTORE | `def test_dto_shape_summary_plus_recent_context_with_backref(ledger):` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 102 | `tests/test_relation_read_640.py:130` | T_TRANSPARENT_FIXTURE | RESTORE | `def test_dto_shape_summary_plus_recent_context_with_backref(ledger):` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 103 | `tests/test_relation_read_640.py:171` | T_TRANSPARENT_FIXTURE | RESTORE | `杨嗣昌蒙知遇之恩` | 对照旧源码夹具种子；确定性调用输入或结构化字段 |
| 104 | `tests/test_relation_read_640.py:280` | T_TRANSPARENT_FIXTURE | RESTORE | `context="杨嗣昌与倪元璐初有细缝。", origin="seed:founding:yang-ni",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 105 | `tests/test_relation_seed_638.py:345` | T_TRANSPARENT_FIXTURE | RESTORE | `recent_context` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 106 | `tests/test_relation_store_632.py:161` | T_TRANSPARENT_FIXTURE | RESTORE | `context="二人当面相发明。",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 107 | `tests/test_rescript_draft_656.py:148` | T_TRANSPARENT_FIXTURE | RESTORE | `"context": "秦地赤旱千里，臣愚以为赈济不可缓。",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 108 | `tests/test_rescript_draft_656.py:300` | T_TRANSPARENT_FIXTURE | RESTORE | `"options": [` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 109 | `tests/test_secret_order_monthly_progress_566.py:209` | T_TRANSPARENT_FIXTURE | RESTORE | `"SELECT id,status,result FROM secret_orders WHERE id IN (?, ?)",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 110 | `tests/test_secret_order_monthly_progress_566.py:214` | T_TRANSPARENT_FIXTURE | RESTORE | `"memorial_text": "首批已出京",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 111 | `tests/test_secret_order_update.py:21` | T_TRANSPARENT_FIXTURE | RESTORE | `row = db.conn.execute("SELECT title, content FROM secret_orders WHERE id=?", (oi` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 112 | `tests/test_structured_decree_contract_1624.py:609` | T_TRANSPARENT_FIXTURE | RESTORE | `# 单条路径 draft_text=大臣回话；纠错轮正文漂移不得改写会话正文真源` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 113 | `tests/test_web_audience_night_498.py:209` | T_TRANSPARENT_FIXTURE | RESTORE | `"SELECT body FROM story_ledger_entries WHERE source_chat_turn_id=?", (ctid,),` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 114 | `tests/test_web_audience_night_498.py:387` | T_TRANSPARENT_FIXTURE | RESTORE | `"SELECT body FROM story_ledger_entries WHERE source_chat_turn_id=?",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 115 | `tests/test_web_chat_serialization_393.py:364` | T_TRANSPARENT_FIXTURE | RESTORE | `yield {"type": "done", "payload": {"answer": "臣已知悉。"}}` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 116 | `web/src/appDurableWiring.test.tsx:126` | T_TRANSPARENT_FIXTURE | RESTORE | `previous_summary: "天启七年九月邸报·试重开",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 117 | `web/src/appDurableWiring.test.tsx:181` | T_TRANSPARENT_FIXTURE | RESTORE | `杨嗣昌御前低语` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 118 | `web/src/appDurableWiring.test.tsx:255` | T_TRANSPARENT_FIXTURE | RESTORE | `{ role: "minister", speaker: minister.name, content: "臣已入殿", chat_turn_id: 1, be` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 119 | `web/src/appDurableWiring.test.tsx:255` | T_TRANSPARENT_FIXTURE | RESTORE | `{ role: "minister", speaker: minister.name, content: "臣已入殿", chat_turn_id: 1, be` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 120 | `web/src/appDurableWiring.test.tsx:347` | T_TRANSPARENT_FIXTURE | RESTORE | `if (path.endsWith("/api/secret_orders")) return jsonResp({ orders: [] });` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 121 | `web/src/appDurableWiring.test.tsx:1209` | T_TRANSPARENT_FIXTURE | RESTORE | `see old context` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 122 | `web/src/appDurableWiring.test.tsx:1910` | T_TRANSPARENT_FIXTURE | RESTORE | `辽东战守` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 123 | `web/src/appDurableWiring.test.tsx:1922` | T_TRANSPARENT_FIXTURE | RESTORE | `await vi.waitFor(() => expect(host.querySelector('[data-testid="decision-modal"]` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 124 | `web/src/appDurableWiring.test.tsx:2422` | T_TRANSPARENT_FIXTURE | RESTORE | `see old context` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 125 | `web/src/appDurableWiring.test.tsx:2601` | T_TRANSPARENT_FIXTURE | RESTORE | `see old context` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 126 | `web/src/appDurableWiring.test.tsx:2665` | T_TRANSPARENT_FIXTURE | RESTORE | `see old context` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 127 | `web/src/appDurableWiring.test.tsx:2670` | T_TRANSPARENT_FIXTURE | RESTORE | `see old context` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 128 | `web/src/appDurableWiring.test.tsx:2697` | T_TRANSPARENT_FIXTURE | RESTORE | `see old context` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 129 | `web/src/appDurableWiring.test.tsx:2714` | T_TRANSPARENT_FIXTURE | RESTORE | `see old context` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 130 | `web/src/appDurableWiring.test.tsx:2716` | T_TRANSPARENT_FIXTURE | RESTORE | `see old context` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 131 | `web/src/components/drawers.test.tsx:163` | T_TRANSPARENT_FIXTURE | RESTORE | `name: "登莱兵与水师",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 132 | `web/src/components/drawers.test.tsx:166` | T_NEG_FIXTURE | RESTORE | `arrears_text: "欠饷约60万两，数月军饷",` | 否定夹具字节/P4不裸数/撤回后不残留 |
| 133 | `web/src/components/drawers.test.tsx:167` | T_NEG_FIXTURE | RESTORE | `morale_text: "士气：尚稳",` | 否定夹具字节/P4不裸数/撤回后不残留 |
| 134 | `web/src/components/drawers.test.tsx:195` | T_NEG_FIXTURE | RESTORE | `arrears_text: "欠饷约15万两，约两月军饷",` | 否定夹具字节/P4不裸数/撤回后不残留 |
| 135 | `web/src/components/drawers.test.tsx:196` | T_NEG_FIXTURE | RESTORE | `arrears_text: "欠饷约15万两，约两月军饷",` | 否定夹具字节/P4不裸数/撤回后不残留 |
| 136 | `web/src/components/drawers.test.tsx:227` | T_NEG_FIXTURE | RESTORE | `arrears_text: "欠饷约60万两，数月军饷",` | 否定夹具字节/P4不裸数/撤回后不残留 |
| 137 | `web/src/components/drawers.test.tsx:228` | T_NEG_FIXTURE | RESTORE | `morale_text: "士气：不振",` | 否定夹具字节/P4不裸数/撤回后不残留 |
| 138 | `web/src/components/map.test.tsx:154` | T_NEG_FIXTURE | RESTORE | `士气：不振` | 否定夹具字节/P4不裸数/撤回后不残留 |
| 139 | `web/src/components/map.test.tsx:155` | T_NEG_FIXTURE | RESTORE | `欠饷不足十万两，约两月军饷` | 否定夹具字节/P4不裸数/撤回后不残留 |
| 140 | `web/src/components/modals.test.tsx:56` | T_TRANSPARENT_FIXTURE | RESTORE | `朕先问烛花一爆洪承畴后答` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 141 | `web/src/components/modals.test.tsx:457` | T_NEG_FIXTURE | RESTORE | `see old context` | 否定夹具字节/P4不裸数/撤回后不残留 |
| 142 | `web/src/components/modals.test.tsx:544` | T_TRANSPARENT_FIXTURE | RESTORE | `chat: [{ role: "user", content: "剿抚孰先？" }],` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 143 | `web/src/components/modals.test.tsx:579` | T_TRANSPARENT_FIXTURE | RESTORE | `{ role: "scene", speaker: "周延儒", content: "殿内 **烛影** 摇曳\n- 夜风入户", beat: "entranc` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 144 | `web/src/components/modals.test.tsx:580` | T_TRANSPARENT_FIXTURE | RESTORE | `{ role: "attendant", speaker: "王承恩", content: "**低声**：边报已至。", beat: "aside", aud` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 145 | `web/src/components/modals.test.tsx:606` | T_TRANSPARENT_FIXTURE | RESTORE | `{ role: "scene", speaker: "周延儒", content: "殿门徐启", beat: "entrance", audibility: ` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 146 | `web/src/components/modals.test.tsx:607` | T_TRANSPARENT_FIXTURE | RESTORE | `{ role: "user", speaker: "朕", content: "（搁笔）卿且直言。", beat: "dialogue", audibility` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 147 | `web/src/components/modals.test.tsx:608` | T_TRANSPARENT_FIXTURE | RESTORE | `{ role: "minister", speaker: "周延儒", content: "臣谨奏。", beat: "dialogue", audibilit` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 148 | `web/src/components/modals.test.tsx:609` | T_TRANSPARENT_FIXTURE | RESTORE | `{ role: "attendant", speaker: "曹化淳", content: "圣上，他有所隐瞒。", beat: "aside", audibi` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 149 | `web/src/components/modals.test.tsx:614` | T_TRANSPARENT_FIXTURE | RESTORE | `{ role: "attendant", speaker: "王承恩", content: "公开传话。", beat: "aside", audibility` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 150 | `web/src/components/modals.test.tsx:693` | T_TRANSPARENT_FIXTURE | RESTORE | `{ role: "minister", speaker: "洪承畴", content: "同夜他臣", chat_turn_id: 2 },` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 151 | `web/src/components/modals.test.tsx:694` | T_TRANSPARENT_FIXTURE | RESTORE | `{ role: "attendant", speaker: "王承恩", content: "旧轮迟到递话", chat_turn_id: 1, record_` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 152 | `web/src/components/modals.test.tsx:723` | T_TRANSPARENT_FIXTURE | RESTORE | `{ role: "minister", speaker: MINISTER_MOCK.name, content: "撤回前答复", chat_turn_id:` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 153 | `web/src/components/modals.test.tsx:912` | T_TRANSPARENT_FIXTURE | RESTORE | `{ role: "minister", speaker: MINISTER_MOCK.name, content: "非流式新答", chat_turn_id:` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 154 | `web/src/components/modals.test.tsx:940` | T_TRANSPARENT_FIXTURE | RESTORE | `杨嗣昌御前低语` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 155 | `web/src/components/modals.test.tsx:1291` | T_TRANSPARENT_FIXTURE | RESTORE | `{ role: "user", speaker: "朕", content: "辽饷何解？", beat: "dialogue", chat_turn_id: ` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 156 | `web/src/components/modals.test.tsx:1292` | T_TRANSPARENT_FIXTURE | RESTORE | `密令：整饬边备` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 157 | `web/src/components/modals.test.tsx:1293` | T_TRANSPARENT_FIXTURE | RESTORE | `臣领旨` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 158 | `web/src/components/modals.test.tsx:1292` | T_TRANSPARENT_FIXTURE | RESTORE | `密令：整饬边备` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 159 | `web/src/components/modals.test.tsx:1293` | T_TRANSPARENT_FIXTURE | RESTORE | `臣领旨` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 160 | `web/src/components/modals.test.tsx:1306` | T_TRANSPARENT_FIXTURE | RESTORE | `神色凝重` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 161 | `web/src/components/modals.test.tsx:1421` | T_TRANSPARENT_FIXTURE | RESTORE | `messages: [{ role: "user", content: nightId === 31 ? "甲夜奏对" : "乙夜奏对", chat_turn_` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 162 | `web/src/components/modals.test.tsx:1765` | T_TRANSPARENT_FIXTURE | RESTORE | `report: "**辽东军情**\n- 军前缺饷",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 163 | `web/src/components/modals.test.tsx:1766` | T_TRANSPARENT_FIXTURE | RESTORE | `report: "**辽东军情**\n- 军前缺饷",` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 164 | `web/src/components/settlementFaces.test.tsx:143` | T_TRANSPARENT_FIXTURE | RESTORE | `月初已结漕运` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 165 | `web/src/components/settlementGazettePanel.test.tsx:39` | T_TRANSPARENT_FIXTURE | RESTORE | `report={"十月邸报\n一、边报"}` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 166 | `web/src/components/settlementGazettePanel.test.tsx:40` | T_TRANSPARENT_FIXTURE | RESTORE | `attendantMessage="奴婢呈报。"` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 167 | `web/src/mindreadingDelivery.test.tsx:149` | T_TRANSPARENT_FIXTURE | RESTORE | `{ role: "scene", speaker: "", content: "新落账场景", chat_turn_id: 8 },` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 168 | `web/src/mindreadingDelivery.test.tsx:178` | T_TRANSPARENT_FIXTURE | RESTORE | `user:失败问话` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 169 | `web/src/mindreadingDelivery.test.tsx:179` | T_TRANSPARENT_FIXTURE | RESTORE | `user:保留问话` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 170 | `web/src/mindreadingDelivery.test.tsx:180` | T_TRANSPARENT_FIXTURE | RESTORE | `minister:保留答复` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 171 | `web/src/mindreadingDelivery.test.tsx:208` | T_TRANSPARENT_FIXTURE | RESTORE | `user:请奏` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 172 | `web/src/staleGuard.test.tsx:342` | T_TRANSPARENT_FIXTURE | RESTORE | `act(() => (host.querySelector("[data-testid=send]") as HTMLButtonElement).click(` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 173 | `web/src/staleGuard.test.tsx:391` | T_TRANSPARENT_FIXTURE | RESTORE | `(host.querySelector("[data-testid=issue]") as HTMLButtonElement).click();` | 夹具/mock/声明种子经通道原样读回或呈现 |
| 174 | `web/src/staleGuard.test.tsx:472` | T_TRANSPARENT_FIXTURE | RESTORE | `act(() => (host.querySelector("[data-testid=undo]") as HTMLButtonElement).click(` | 夹具/mock/声明种子经通道原样读回或呈现 |

## 裸 read_material 调用处置

| file:line | kind | note | code |
| --- | --- | --- | --- |
| `tests/test_character_knowledge_489.py:1411` | REACHABILITY | 列目录后读口可达烟测 | `read_material(prepared.root, archive_rel)` |
| `tests/test_material_directory_1830.py:55` | REACHABILITY | 路径在册+读口可达（不锁正文）；非删断言留下的空壳 | `read_material(prepared.root, rel)` |
| `tests/test_material_directory_1830.py:71` | REACHABILITY | 路径在册+读口可达（不锁正文）；非删断言留下的空壳 | `read_material(first.root, "INDEX.txt")` |
| `tests/test_material_directory_1830.py:72` | REACHABILITY | 路径在册+读口可达（不锁正文）；非删断言留下的空壳 | `read_material(second.root, "INDEX.txt")` |
| `tests/test_material_directory_1830.py:179` | PATH_CONFINEMENT | 路径越界/不存在应抛 | `read_material(prepared.root, "../outside.txt")` |
| `tests/test_material_directory_1830.py:199` | PATH_CONFINEMENT | 路径越界/不存在应抛 | `read_material(prepared.root, display)` |
| `tests/test_material_directory_1830.py:255` | REACHABILITY | 路径在册+读口可达（不锁正文）；非删断言留下的空壳 | `read_material(prepared.root, "INDEX.txt")` |
| `tests/test_candidate_supply_1893.py:116` | REACHABILITY | 列目录后读口可达烟测 | `read_material(prepared.root, CANDIDATE_REL)` |
| `tests/test_gazette_author_1862.py:440` | REACHABILITY | 路径在册+读口可达（不锁正文）；非删断言留下的空壳 | `read_material(prepared.root, "INDEX.txt")` |
| `tests/test_gazette_author_1862.py:446` | REACHABILITY | 列目录后读口可达烟测 | `read_material(prepared.root, experience)` |
| `tests/test_gazette_author_1862.py:457` | REACHABILITY | 路径在册+读口可达（不锁正文）；非删断言留下的空壳 | `read_material(world_tree.root, rel)` |
| `tests/test_gazette_author_1862.py:459` | REACHABILITY | 路径在册+读口可达（不锁正文）；非删断言留下的空壳 | `read_material(world_tree.root, board)` |
| `tests/test_world_materials_1834.py:46` | REACHABILITY | 列目录后读口可达烟测 | `read_material(prepared.root, "盘面/派系检举事实.txt")` |
| `tests/test_world_materials_1834.py:53` | REACHABILITY | 路径在册+读口可达（不锁正文）；非删断言留下的空壳 | `read_material(prepared.root, rel)` |
| `tests/test_world_materials_1834.py:156` | REACHABILITY | 列目录后读口可达烟测 | `read_material(prepared.root, affair_paths[0])` |
| `tests/test_world_materials_1834.py:167` | REACHABILITY | 路径在册+读口可达（不锁正文）；非删断言留下的空壳 | `read_material(first.root, "INDEX.txt")` |
| `tests/test_world_materials_1834.py:168` | REACHABILITY | 路径在册+读口可达（不锁正文）；非删断言留下的空壳 | `read_material(second.root, "INDEX.txt")` |
| `tests/test_world_materials_1834.py:292` | REACHABILITY | 路径在册+读口可达（不锁正文）；非删断言留下的空壳 | `read_material(prepared.root, "候选事件/INDEX.txt")` |
| `tests/test_world_materials_1834.py:294` | REACHABILITY | 路径在册+读口可达（不锁正文）；非删断言留下的空壳 | `read_material(prepared.root, rel)` |
| `tests/test_world_materials_1834.py:320` | REACHABILITY | 路径在册+读口可达（不锁正文）；非删断言留下的空壳 | `read_material(prepared.root, "请旨事项/INDEX.txt")` |
| `tests/test_world_materials_1834.py:329` | REACHABILITY | 路径在册+读口可达（不锁正文）；非删断言留下的空壳 | `read_material(prepared.root, rel)` |
| `tests/test_secret_order_payoff_1504.py:987` | REACHABILITY | 列目录后读口可达烟测 | `read_material(captured["root"], rel)` |
