# F3 删除侧成员表（手读可核，相对 52809cdf3）

比对基线：`52809cdf3`。每行 source/channel 对照源码；禁止泛称 fixture / 仅写 answer 或 SELECT id。

成员总数：**175**；RESTORE：**175**；KEEP_DELETED：**0**

| i | 位置 | class | disposition | source | channel | basis |
| --- | --- | --- | --- | --- | --- | --- |
| 000 | `tests/test_army_card_status_1501.py:181` | T_CONTENT_SEED | RESTORE | content/armies.json guanning.status / test _GUANNING_STATUS="宁锦守线尚可，欠饷严重，主动大举出击风险极高。" | db.army_report(limit=20) includes row.status | DB seed status 原句进共享报告；非 arrears 夹具字节透明输送 |
| 001 | `tests/test_army_card_status_1501.py:213` | T_CONTENT_SEED | RESTORE | same content/armies.json guanning.status / _GUANNING_STATUS | db.army_detail("guanning") | DB seed status 原句进详情通道 |
| 002 | `tests/test_army_display_173.py:129` | T_FIXED_UI_FIELD | RESTORE | UPDATE armies SET arrears=12.5 (numeric; test does not write "欠饷约15万两") | db.army_payload()→_army_arrears_report_text→_approx_wanliang(12.5) | 固定 UI/字段生成：数值欠饷经近似万两格式化；不可冒称夹具正文透明输送 |
| 003 | `tests/test_audience_continuous_507.py:50` | T_FIXTURE_ARG | RESTORE | _public(db,nid,"徐光启","徐光启奏：宜用洪承畴督师陕西。") | an.audience_scene_recap(db,"毕自严",night_id=nid) | 公开 ledger 夹具句经 recap 原样引用 |
| 004 | `tests/test_audience_continuous_507.py:72` | T_FIXTURE_ARG | RESTORE | _public(db,nid,"徐光启","徐光启方入奏水利。") | an.audience_scene_recap(db,"徐光启",night_id=nid) | 入殿后公开句进本人 recap |
| 005 | `tests/test_audience_continuous_507.py:99` | T_FIXTURE_ARG | RESTORE | _public(db,nid,"徐光启","徐光启奏：陕西糜烂，非洪承畴不可。") | an.audience_scene_recap(db,"毕自严",night_id=nid) | 连场公开句进侍立者 recap |
| 006 | `tests/test_audience_restore_505.py:216` | T_FIXTURE_ARG | RESTORE | _land_full_turn(...,"四轮问对之一","臣愚见如此。") | reopen→build_chat_projection user contents | 落库问话经恢复投影读回 |
| 007 | `tests/test_audience_restore_505.py:217` | T_FIXTURE_ARG | RESTORE | _land_full_turn answer "臣愚见如此。" | reopen→build_chat_projection minister contents | 落库回话经恢复投影读回 |
| 008 | `tests/test_audience_restore_505.py:292` | T_MOCK_RETURN | RESTORE | _RetrySession.chat→ChatTurnResult(answer="臣重奏：剿为先。") | rt.retry_interrupted_reply→payload["answer"] | 重试 mock 回话进 payload |
| 009 | `tests/test_audience_restore_505.py:332` | T_FIXTURE_ARG | RESTORE | _land_full_turn(...,"退朝","臣遵旨。") | rt.retry_interrupted_reply→payload["answer"] | 已落库回话在 post_reply 恢复路径返回 |
| 010 | `tests/test_audience_restore_505.py:335` | T_FIXTURE_ARG | RESTORE | same _land_full_turn "臣遵旨。" | SELECT content FROM chat_messages WHERE role=minister | DB 回话列与夹具一致 |
| 011 | `tests/test_audience_restore_505.py:452` | T_MOCK_RETURN | RESTORE | _RetrySession.chat→ChatTurnResult(answer="臣重奏：剿为先。") | rt.retry_interrupted_reply(minister) | 无指定 turn 重试同一 mock |
| 012 | `tests/test_audience_scroll_539.py:263` | T_FIXTURE_ARG | RESTORE | append_night_chat(...,"边情如何？","边关尚稳。") + prior replies | GET /api/audience/scroll dialogue contents | 夜卷 API contents＝夹具问答复 |
| 013 | `tests/test_audience_scroll_539.py:268` | T_FIXTURE_ARG | RESTORE | append_night_chat replies "臣请据实核账。","边关尚稳。" | scroll messages role=scene with chat_turn_id | scene 载体原样 |
| 014 | `tests/test_audience_scroll_539.py:513` | T_FIXTURE_ARG | RESTORE | append_night_chat(...,"杨嗣昌","本夜问话","本夜答复",10) | db.build_chat_projection("杨嗣昌") | 仅当前开夜投影 |
| 015 | `tests/test_audience_translate_1837.py:476` | T_MOCK_RETURN | RESTORE | SimpleNamespace(content="臣等遵旨。",tools=[]) | r2.answer from _scene_turn | mock 回话进 answer |
| 016 | `tests/test_audience_translate_1837.py:739` | T_MOCK_RETURN | RESTORE | FakeAgent.run→SimpleNamespace(content="臣在。") in test_translate_call_failure… | sess.scene_chat→result.answer | 转译失败前 mock 回话；本轮补回原测 |
| 017 | `tests/test_audience_translate_1837.py:739` | T_MOCK_RETURN | RESTORE | same FakeAgent content="臣在。" (duplicate enum row) | same result.answer | 与 016 同条 |
| 018 | `tests/test_audience_translate_1837_reopen.py:369` | T_DISK_OR_READ | RESTORE | query="去查那件未见于词表的事，原话留档。" | read_material(prepared.root, 人物/<attendant>/经历.txt) | 自写固定字节经材料树读回 |
| 019 | `tests/test_audience_translation_1838.py:346` | T_DECLARATION_SEED | RESTORE | edge declaration context="当殿为赈灾站台" | relation_edge_events.context | 声明 context 落库 |
| 020 | `tests/test_breach_plea_623.py:381` | T_DECLARATION_SEED | RESTORE | commissions[0].text="前旨作废，撤回成命" | pending_actions.payload_json["text"] | 撤令正文进暂存 payload |
| 021 | `tests/test_cli_backend.py:467` | T_MOCK_RETURN | RESTORE | yield _Delta(reasoning_content="先核辽饷账目…") | run_agent_stream_text on_thinking | thinking 增量进回调 |
| 022 | `tests/test_cli_play_turn.py:470` | T_MOCK_RETURN | RESTORE | SettlementResult(...,report="留中案卷本月重判月报") | capsys stdout play_turn | mock 月报进 CLI 输出 |
| 023 | `tests/test_cli_runner_error_typed_1299.py:89` | T_MOCK_RETURN | RESTORE | monkeypatch _call_cli→("臣遵旨，边事容臣细奏。",1) | captured["text"] | CLI 正常回包原文 |
| 024 | `tests/test_declaration_dispatch_1835.py:76` | T_DECLARATION_SEED | RESTORE | textual_facts body "抱恙数日，仍可视事" | textual_facts.readable_materials(character) | textual_facts.body 原样 |
| 025 | `tests/test_declaration_dispatch_1835.py:219` | T_DECLARATION_SEED | RESTORE | declaration body "如实记事" | readable_materials after dispatch | textual_facts.body 原样 |
| 026 | `tests/test_declaration_dispatch_1835.py:747` | T_DECLARATION_SEED | RESTORE | staged bodies "旨三：后到之旨","旨一：暂存中" | settle_staged→readable_materials | textual_facts.body 原样 |
| 027 | `tests/test_declaration_dispatch_1835.py:762` | T_DECLARATION_SEED | RESTORE | same staged bodies | readable_materials after second settle | textual_facts.body 原样 |
| 028 | `tests/test_declaration_dispatch_1835.py:791` | T_DECLARATION_SEED | RESTORE | stage body "旨三：首次暂存" | readable_materials | textual_facts.body 原样 |
| 029 | `tests/test_declaration_dispatch_1835.py:808` | T_DECLARATION_SEED | RESTORE | same "旨三：首次暂存" | readable_materials after restage | textual_facts.body 原样 |
| 030 | `tests/test_decree_commitment_settlement_229.py:1444` | T_FIXTURE_ARG | RESTORE | narrative="皇帝已复试孙承宗，此承诺已由圣裁处理。" | commitment.resolution_summary | 裁决 narrative 进 summary |
| 031 | `tests/test_decree_dossiers_571.py:536` | T_MOCK_RETURN | RESTORE | dossier_test_helpers.rejected_verdict(reason="科臣封驳。") | get_decree_dossier.promulgation_reason | 封驳 reason 落库 |
| 032 | `tests/test_decree_dossiers_571.py:1082` | T_UI_LABEL | RESTORE | manual directive JSON key "参与人" | terminal.review_directives capsys | 固定校验字段名回显 |
| 033 | `tests/test_decree_dossiers_571.py:1621` | T_ENGINE_NOTE | RESTORE | grant amount=10 treasury=5 underfund path | execution_note contains 不足额 | 引擎欠拨固定词 |
| 034 | `tests/test_decree_dossiers_571.py:1621` | T_ENGINE_NOTE | RESTORE | same underfund path (dup) | execution_note 不足额 | 同 033 |
| 035 | `tests/test_decree_dossiers_571.py:1996` | T_ENGINE_NOTE | RESTORE | allocation amount=10 note composer | execution_note 应拨10两 | 引擎对账句 |
| 036 | `tests/test_decree_dossiers_571.py:1997` | T_ENGINE_NOTE | RESTORE | expected_actual from debit oracle | execution_note f"实拨{abs(expected_actual)}两" | 引擎实拨句 |
| 037 | `tests/test_decree_dossiers_571.py:2115` | T_FIXTURE_ARG | RESTORE | record_dossier_execution(...,"押解到陕",...) | execution_note | 执行记注参数原样 |
| 038 | `tests/test_deepseek_thinking_disable_1797.py:209` | T_MOCK_RETURN | RESTORE | reasoning_content="思考过程甲" | joined stream text | reasoning_content 拼接 |
| 039 | `tests/test_deepseek_thinking_disable_1797.py:210` | T_MOCK_RETURN | RESTORE | reasoning="中转 reasoning 正文" | joined stream text | reasoning 拼接 |
| 040 | `tests/test_dossier_reported_progress_619.py:95` | T_FIXTURE_ARG | RESTORE | progress memorial_text list fixture | list history memorial_text | 进度全史原样 |
| 041 | `tests/test_dossier_reported_progress_619.py:140` | T_FIXTURE_ARG | RESTORE | "memorial_text":"首批已出关619" | rows[0] memorial_text | 单条 memorial |
| 042 | `tests/test_dossier_reported_progress_619.py:146` | T_FIXTURE_ARG | RESTORE | same memorial in dossier_progress_json | json.loads(...)[0] memorial_text | JSON 列原样 |
| 043 | `tests/test_dossier_reported_progress_619.py:237` | T_FIXTURE_ARG | RESTORE | degraded path memorial_text write | deg[0] memorial_text truthy | 降级侧路非空 memorial |
| 044 | `tests/test_dossier_reported_progress_619.py:252` | T_FIXTURE_ARG | RESTORE | note="名实已乖" | transformed note/memorial | 终态 note |
| 045 | `tests/test_dossier_reported_progress_619.py:306` | T_FIXTURE_ARG | RESTORE | continued memorial_text list | cont memorial_text list | 续报列表 |
| 046 | `tests/test_event_trigger_gate.py:1418` | T_CONTENT_SEED | RESTORE | content/events.json wuyin.summary …本局按盘面软判… | event summary field | 内容种子 summary |
| 047 | `tests/test_event_trigger_gate.py:1421` | T_CONTENT_SEED | RESTORE | content/events.json wuyin.precondition …卢象升生死由软判… | event precondition | 内容种子 precondition |
| 048 | `tests/test_event_trigger_gate.py:1422` | T_CONTENT_SEED | RESTORE | content/events.json songshan.summary …本局按盘面软判援锦主帅… | event summary | 内容种子 summary |
| 049 | `tests/test_execution_joint_liability_565.py:405` | T_FIXTURE_ARG | RESTORE | merge_execution_note(...,"对账差额：应拨十两实拨三两") | execution_note | merge 参数原样 |
| 050 | `tests/test_faction_brew_637.py:139` | T_CONTENT_SEED | RESTORE | default stance_segment "朝局如常。" for 皇党 | get_faction_stance_summary("皇党") | 未酿制默认段 |
| 051 | `tests/test_faction_brew_637.py:140` | T_CONTENT_SEED | RESTORE | default stance_segment "朝局如常。" for 阉党 | get_faction_stance_summary("阉党") | 未酿制默认段 |
| 052 | `tests/test_faction_brew_637.py:174` | T_MOCK_RETURN | RESTORE | _dual_brew_fn_factory(stance="东林因钱谦益蒙召对而势涨。") | summary.stance_segment | brew mock stance |
| 053 | `tests/test_faction_brew_637.py:232` | T_MOCK_RETURN | RESTORE | _dual_brew_fn_factory(stance="皇党内因温周之隙而生嫌隙。") | get_faction_stance_summary("皇党") | brew mock stance |
| 054 | `tests/test_faction_brew_637.py:277` | T_MOCK_RETURN | RESTORE | brew override final "皇党因杨嗣昌被驳而渐离。" (prior "皇党旧文。") | get_faction_stance_summary("皇党") | 后酿覆盖 |
| 055 | `tests/test_family_tail_restore_570.py:185` | T_FIXTURE_ARG | RESTORE | memorials "已出京赴陕","已抵西安" | continued memorial_text list | 家族尾进度文案 |
| 056 | `tests/test_fiscal_levy_effect.py:1576` | T_FIXTURE_ARG | RESTORE | held petition note="姑候户部再核" | next world-segment supply text | 留中批注供料 |
| 057 | `tests/test_gazette_author_1862.py:375` | T_DISK_OR_READ | RESTORE | _PUBLIC_FACT const via textual_facts | seen["author_files"][按月实况] | 作者材料含公开事实字节 |
| 058 | `tests/test_gazette_author_1862.py:376` | T_DISK_OR_READ | RESTORE | _PLAIN_DOSSIER_FACT const | seen["author_files"][按月实况] | 普通案卷事实字节 |
| 059 | `tests/test_gazette_author_1862.py:378` | T_DISK_OR_READ | RESTORE | _PRIVATE_KEEP const | seen["author_files"][经历.txt] | 经历低语字节搬运 |
| 060 | `tests/test_gazette_author_1862.py:439` | T_DISK_OR_READ | RESTORE | mock json report=_REPORT | read_material(公开说法/邸报/*) | mock 邸报经材料树读回 |
| 061 | `tests/test_grant_reconciliation_567.py:199` | T_FIXTURE_ARG | RESTORE | "memorial_text":"护行路已核关防，实银可期" | progress[0] memorial_text | 对账 memorial |
| 062 | `tests/test_highlight_judge_544.py:227` | T_MOCK_RETURN | RESTORE | done payload answer="臣陈辽饷。" | SSE done payload | 高亮完成回话 |
| 063 | `tests/test_highlight_judge_544.py:272` | T_MOCK_RETURN | RESTORE | reply fixture "臣先陈军务。" | seen_reply list | 回话捕获列表 |
| 064 | `tests/test_highlight_judge_544.py:306` | T_MOCK_RETURN | RESTORE | ChatTurnResult(answer="臣陈辽饷。") | payload["answer"] | mock ChatTurnResult |
| 065 | `tests/test_highlight_judge_544.py:357` | T_MOCK_RETURN | RESTORE | ChatTurnResult(answer="臣遵旨。") | payload["answer"] | mock ChatTurnResult |
| 066 | `tests/test_impeachment_surge_655.py:162` | T_DECLARATION_SEED | RESTORE | stage_text="原样案情。" | issues.stage_text | 声明 stage_text |
| 067 | `tests/test_mechanical_tail_1845.py:569` | T_MOCK_RETURN | RESTORE | run_agent_text→"补配后总评" (ending_outcome summary="退位" overridden) | ending["summary"] | 补配 mock 总评 |
| 068 | `tests/test_month_call_recovery_1846.py:296` | T_MOCK_RETURN | RESTORE | world()→"世界段已成文。" in exhaustion test | month_chain.world_text | 世界段 mock 暂存；本轮补回 |
| 069 | `tests/test_month_call_recovery_1846.py:575` | T_MOCK_RETURN | RESTORE | world()→"世界段已成文。" in sibling test | month_chain.world_text | 同 mock 另一恢复案 |
| 070 | `tests/test_month_chain_1847.py:704` | T_FIXTURE_ARG | RESTORE | this_decree.decree_text non-empty seed | payload["this_decree"]["decree_text"] | 供料含本旨正文 |
| 071 | `tests/test_month_chain_1847.py:776` | T_DECLARATION_SEED | RESTORE | forecast text "问前事实。" | segments list | 问前事实段 |
| 072 | `tests/test_month_chain_1847.py:781` | T_DECLARATION_SEED | RESTORE | same "问前事实。" | forecast_text_for(ref) | forecast_text |
| 073 | `tests/test_month_chain_1847.py:2036` | T_FIXTURE_ARG | RESTORE | world_text="世界段原文·密报可读。" | feed["world_segment"] | 密报供料 |
| 074 | `tests/test_month_chain_1847.py:2076` | T_DISK_OR_READ | RESTORE | fact_body="文字事实正文：边材已动。\r\n同一条事实的第二行。  \r" | carrier via read_material/feed | 自写固定字节含\r |
| 075 | `tests/test_month_translate_1840.py:212` | T_DECLARATION_SEED | RESTORE | bodies "人物先记一事","人物再记一事" | readable_materials character | 人物事实按序 |
| 076 | `tests/test_month_translate_1840.py:213` | T_DECLARATION_SEED | RESTORE | bodies "军队先记一事","军队再记一事" | readable_materials army | 军队事实按序 |
| 077 | `tests/test_month_translate_1840.py:389` | T_DECLARATION_SEED | RESTORE | region/affair textual_facts in same fixture block | readable_materials region/affair | 多主体事实 |
| 078 | `tests/test_month_translate_1840.py:456` | T_DECLARATION_SEED | RESTORE | body "前一段已落" | readable_materials after later segment | 前段仍在 |
| 079 | `tests/test_on_scene_immediate_write_1839.py:131` | T_DISK_OR_READ | RESTORE | arm_injury="左臂中箭，血透重甲，犹力战不退" | read_material(.../按月实况.txt) | 当殿事实读回 |
| 080 | `tests/test_on_scene_immediate_write_1839.py:134` | T_DISK_OR_READ | RESTORE | death_rumour="关外传袁崇焕已死于宁远城下" | read_material(.../公开说法/...) | 公开说法读回 |
| 081 | `tests/test_person_delta_adapter.py:236` | T_DECLARATION_SEED | RESTORE | new_issues title="安抚毛文龙·进行中" | applied issue_summary title | 适配器 title |
| 082 | `tests/test_person_delta_adapter.py:241` | T_DECLARATION_SEED | RESTORE | same title | issues.title column | 落库 title |
| 083 | `tests/test_pihong_dossier_1490.py:381` | T_FIXTURE_ARG | RESTORE | choice note='准销。' | stored_choice.note | 批红 note |
| 084 | `tests/test_pihong_dossier_1490.py:407` | T_FIXTURE_ARG | RESTORE | choice note='准。先济关宁边饷。' | stored choice.note | 客户端只留 note |
| 085 | `tests/test_pihong_dossier_1490.py:503` | T_FIXTURE_ARG | RESTORE | choice note='准销。' | stored note | 批红 note |
| 086 | `tests/test_pihong_dossier_1490.py:2015` | T_FIXTURE_ARG | RESTORE | default hold note='着再议。' | batch.items[0].choice.note | 留中保留 note |
| 087 | `tests/test_pihong_dossier_1490.py:2926` | T_FIXTURE_ARG | RESTORE | _1778_raw_options labels 责户部清理钱粮亏短/发内帑周转军国急用 | desk options labels | 选项 label 列表 |
| 088 | `tests/test_pihong_dossier_1490.py:2929` | T_FIXTURE_ARG | RESTORE | round_a label set from raw fixture | set(round_a) | 首轮选项集合 |
| 089 | `tests/test_pihong_dossier_1490.py:2945` | T_FIXTURE_ARG | RESTORE | round_b labels 发内帑…/特旨慰谕九边 | set(round_b) | 次轮选项 |
| 090 | `tests/test_pihong_dossier_1490.py:2955` | T_FIXTURE_ARG | RESTORE | midzhi filtered label 责户部清理钱粮亏短 | set(round_midzhi) | 过滤后选项 |
| 091 | `tests/test_pihong_dossier_1490.py:3013` | T_FIXTURE_ARG | RESTORE | _1778 grant label only | drafts[0].options labels | 草稿选项 |
| 092 | `tests/test_player_payload_1022.py:40` | T_FIXTURE_ARG | RESTORE | _HistoryDB archive/context/directives fixtures (report/decree_text/directives notes) | web_app.api_history_turn(9) → payload exact equality | 夹具叙事字段经历史 API 整包原样透明输送；已删顶替用平行结构断言 |
| 093 | `tests/test_public_projection_consistency_1830.py:170` | T_DISK_OR_READ | RESTORE | original public saying fixture (陕西赈务) | disk Path.read_text | 磁盘原文 |
| 094 | `tests/test_public_projection_consistency_1830.py:171` | T_DISK_OR_READ | RESTORE | same original | read_material direct | 直接读口 |
| 095 | `tests/test_public_projection_consistency_1830.py:172` | T_DISK_OR_READ | RESTORE | same original | tools API read_material | API 读口 |
| 096 | `tests/test_qa_b3_409_ux.py:245` | T_MOCK_RETURN | RESTORE | return "邸报：已裁。" | payload["report"] | mock 邸报 |
| 097 | `tests/test_qa_s2_copy_prompts_1356_1402.py:126` | T_FIXTURE_ARG | RESTORE | turn_reports seed containing 真结算九月报文 | payload["previous_summary"] | 历史邸报摘要 |
| 098 | `tests/test_qa_t1_extraction_dual_source_1353.py:589` | T_FIXTURE_ARG | RESTORE | chat_messages content fixture list | SELECT content FROM chat_messages | 双源消息 contents |
| 099 | `tests/test_relation_brew_636.py:435` | T_FIXTURE_ARG | RESTORE | merge inputs 甲句。/乙句。/乙二句。 | merged string | 酿制合并字节 |
| 100 | `tests/test_relation_brew_636.py:603` | T_MOCK_RETURN | RESTORE | brew_fn.outputs recent="原文一" | first["recent_segment"] | mock recent_segment |
| 101 | `tests/test_relation_read_640.py:129` | T_FIXTURE_ARG | RESTORE | apply_relation_brew_result(founding_segment="越次一召，擢杨嗣昌于五品郎中。") | project_relation_ledger summary | 奠基段进 summary |
| 102 | `tests/test_relation_read_640.py:130` | T_FIXTURE_ARG | RESTORE | apply_relation_brew_result(recent_segment="杨嗣昌蒙知遇之恩，复命时记得皇爷上月简拔。") | summary in dto_shape | 近况段进 summary；本轮补回 dto_shape |
| 103 | `tests/test_relation_read_640.py:171` | T_FIXTURE_ARG | RESTORE | same recent_segment | judge_face summary | 判官面近况段 |
| 104 | `tests/test_relation_read_640.py:280` | T_FIXTURE_ARG | RESTORE | history context="二人当面言和，暂释前隙。" | load_relation_history_before prior[2].context | 历史流 context |
| 105 | `tests/test_relation_seed_638.py:345` | T_FIXTURE_ARG | RESTORE | seed recent_context "后事。（天启六年二月）" | dto["recent_context"] | 种子 recent_context |
| 106 | `tests/test_relation_store_632.py:161` | T_FIXTURE_ARG | RESTORE | store context="二人当面相发明。" | rows[0]["context"] | store 读回 |
| 107 | `tests/test_rescript_draft_656.py:148` | T_FIXTURE_ARG | RESTORE | draft context="秦地赤旱千里，臣愚以为赈济不可缓。" | first["context"] | 票拟 context |
| 108 | `tests/test_rescript_draft_656.py:300` | T_FIXTURE_ARG | RESTORE | options[1].hint=" 所拂者小农 " | drafts[0].options[1].hint | hint 空白保留 |
| 109 | `tests/test_secret_order_monthly_progress_566.py:209` | T_ENGINE_NOTE | RESTORE | terminal composer "人物终态：dead；途中病故" | secret_orders.result | 引擎终态句 |
| 110 | `tests/test_secret_order_monthly_progress_566.py:214` | T_ENGINE_NOTE | RESTORE | same terminal phrase | terminal memorial_text | 终态进 memorial |
| 111 | `tests/test_secret_order_update.py:21` | T_FIXTURE_ARG | RESTORE | update content="改为月月内库百万、半年通计六百万" | secret_orders.content | 密令正文改写 |
| 112 | `tests/test_structured_decree_contract_1624.py:609` | T_MOCK_RETURN | RESTORE | draft_text/mock reply "臣遵拟。" | result["draft_text"] | 拟旨 draft_text |
| 113 | `tests/test_web_audience_night_498.py:209` | T_FIXTURE_ARG | RESTORE | story ledger body from chat turn fixture | story_ledger_entries.body | 账身挂钩 |
| 114 | `tests/test_web_audience_night_498.py:387` | T_FIXTURE_ARG | RESTORE | retry bodies ["臣领旨。"] | source_segments_after_retry | 重试后账身 |
| 115 | `tests/test_web_chat_serialization_393.py:364` | T_MOCK_RETURN | RESTORE | SSE done answer="臣已知悉。" | chat_result["answer"] | 序列化回话 |
| 116 | `web/src/appDurableWiring.test.tsx:126` | T_FIXTURE_ARG | RESTORE | previous_summary:"天启七年九月邸报·试重开" | host.textContent | 重开摘要 |
| 117 | `web/src/appDurableWiring.test.tsx:181` | T_FIXTURE_ARG | RESTORE | fixture "杨嗣昌御前低语" | host.textContent | 低语进 UI |
| 118 | `web/src/appDurableWiring.test.tsx:255` | T_FIXTURE_ARG | RESTORE | minister content:"臣已入殿" | waitFor host.textContent | 入殿句进 App 投影 |
| 119 | `web/src/appDurableWiring.test.tsx:255` | T_FIXTURE_ARG | RESTORE | same "臣已入殿" (dup) | same waitFor | 同 118 |
| 120 | `web/src/appDurableWiring.test.tsx:347` | T_FIXTURE_ARG | RESTORE | turn-8 fixture containing "边务如何" | [data-audience-turn-id="8"] | 指定 turn 正文 |
| 121 | `web/src/appDurableWiring.test.tsx:1209` | T_FIXTURE_ARG | RESTORE | advancedState.issues title=MIDCOURSE_ISSUE after gazette dismiss (settlement_display=false) | host.textContent after 朕知道了 closes gazette | 旧注「新月盘面可见半程局势（已非核账）」：结算完后半程局势应显示，非核账期负向泄漏案 |
| 122 | `web/src/appDurableWiring.test.tsx:1910` | T_FIXTURE_ARG | RESTORE | decision issue title "辽东战守" | modal.textContent | 议题 title |
| 123 | `web/src/appDurableWiring.test.tsx:1922` | T_FIXTURE_ARG | RESTORE | same "辽东战守" | decision-modal after remount | 重挂后 title |
| 124 | `web/src/appDurableWiring.test.tsx:2422` | T_FIXTURE_ARG | RESTORE | settlementBaseState.closed_this_turn title=SNAP_CLOSED | host.textContent while settlement_display=true (readonly closed_issues) | 核账期半程议题不可见，但上月已结 SNAP_CLOSED 只读面应可见 |
| 125 | `web/src/appDurableWiring.test.tsx:2601` | T_FIXTURE_ARG | RESTORE | settlementBaseState.closed_this_turn title=SNAP_CLOSED | host.textContent at closed_issues end-of-case check | closed_issues 只读可达正向契约；与 not.toContain(MIDCOURSE) 并存，非互相替代 |
| 126 | `web/src/appDurableWiring.test.tsx:2665` | T_FIXTURE_ARG | RESTORE | last_attendant_message=SNAP_ATTENDANT fixture | [data-testid=gazette-attendant].textContent | 上月固定夹具递话原样展示（#671 App 接线） |
| 127 | `web/src/appDurableWiring.test.tsx:2670` | T_FIXTURE_ARG | RESTORE | settlementBaseState.closed_this_turn title=SNAP_CLOSED | host.textContent alongside not.toContain(MIDCOURSE) in gazette case | 递话案同屏：半程议题零泄漏 + 上月已结正向可见 |
| 128 | `web/src/appDurableWiring.test.tsx:2697` | T_FIXTURE_ARG | RESTORE | last_attendant_message=SNAP_ATTENDANT (attendant-only gazette case) | [data-testid=gazette-attendant].textContent | 仅有递话时木牌仍原样展示 SNAP_ATTENDANT；现行源码已含正向 toContain |
| 129 | `web/src/appDurableWiring.test.tsx:2714` | T_FIXTURE_ARG | RESTORE | settlementBaseState.issues title=MIDCOURSE_ISSUE with settlement_display=false | host.textContent in 月完后 case | 月完后局势半程面重现；现行源码已含正向 toContain |
| 130 | `web/src/appDurableWiring.test.tsx:2716` | T_FIXTURE_ARG | RESTORE | settlementBaseState.closed_this_turn title=SNAP_CLOSED with settlement_display=false | host.textContent in 月完后 case | 月完后上月已结一并恢复；现行源码已含正向 toContain |
| 131 | `web/src/components/drawers.test.tsx:163` | T_FIXTURE_ARG | RESTORE | Army props name:"登莱兵与水师" | ArmyDrawer host.textContent | 军名进抽屉 |
| 132 | `web/src/components/drawers.test.tsx:166` | T_NEG_FIXTURE | RESTORE | arrears_text:"欠饷约60万两，数月军饷" | host.textContent.not.toContain | P7 arrears_text 不直显 |
| 133 | `web/src/components/drawers.test.tsx:167` | T_NEG_FIXTURE | RESTORE | morale_text:"士气：尚稳" | host.textContent.not.toContain | P7 morale_text 不直显 |
| 134 | `web/src/components/drawers.test.tsx:195` | T_NEG_FIXTURE | RESTORE | arrears_text:"欠饷约15万两，约两月军饷" | host.textContent.not.toContain | P7 分数欠饷文案不直显 |
| 135 | `web/src/components/drawers.test.tsx:196` | T_NEG_FIXTURE | RESTORE | same arrears_text suffix 约两月军饷 | host.textContent.not.toContain | P7 月数后缀不直显 |
| 136 | `web/src/components/drawers.test.tsx:227` | T_NEG_FIXTURE | RESTORE | arrears_text:"欠饷约60万两，数月军饷" with status sentence | host.textContent.not.toContain | status 路径亦不直显 |
| 137 | `web/src/components/drawers.test.tsx:228` | T_NEG_FIXTURE | RESTORE | morale_text:"士气：不振" | host.textContent.not.toContain | P7 morale_text 不直显 |
| 138 | `web/src/components/map.test.tsx:154` | T_NEG_FIXTURE | RESTORE | map morale_text "士气：不振" | host.textContent.not.toContain | 地图驻军不直显 |
| 139 | `web/src/components/map.test.tsx:155` | T_NEG_FIXTURE | RESTORE | map arrears_text "欠饷不足十万两，约两月军饷" | host.textContent.not.toContain | 地图不直显 |
| 140 | `web/src/components/modals.test.tsx:56` | T_FIXTURE_ARG | RESTORE | display concat 朕先问烛花一爆洪承畴后答 | host.textContent.toBe | 有机 markdown 清理后整串 |
| 141 | `web/src/components/modals.test.tsx:457` | T_NEG_FIXTURE | RESTORE | forbid /臣.*叩见|恭请圣安/ | stage.textContent.not.toMatch | 禁止叩见套话 |
| 142 | `web/src/components/modals.test.tsx:544` | T_FIXTURE_ARG | RESTORE | chat user content "剿抚孰先？" | note.textContent | 用户问话 |
| 143 | `web/src/components/modals.test.tsx:579` | T_FIXTURE_ARG | RESTORE | scene "殿内 **烛影** 摇曳\n- 夜风入户" |  .chat-message.scene p | markdown 场景 |
| 144 | `web/src/components/modals.test.tsx:580` | T_FIXTURE_ARG | RESTORE | attendant "**低声**：边报已至。" | .chat-message.attendant p | markdown 低语 |
| 145 | `web/src/components/modals.test.tsx:606` | T_FIXTURE_ARG | RESTORE | scene "殿门徐启" | .chat-message.scene | 入场 scene |
| 146 | `web/src/components/modals.test.tsx:607` | T_FIXTURE_ARG | RESTORE | user "（搁笔）卿且直言。" | .turn-segment.user p | 用户段 |
| 147 | `web/src/components/modals.test.tsx:608` | T_FIXTURE_ARG | RESTORE | minister "臣谨奏。" | .turn-segment.minister | 大臣段 |
| 148 | `web/src/components/modals.test.tsx:609` | T_FIXTURE_ARG | RESTORE | aside "圣上，他有所隐瞒。" | .turn-segment.aside | aside |
| 149 | `web/src/components/modals.test.tsx:614` | T_FIXTURE_ARG | RESTORE | attendant "公开传话。" | .turn-segment.attendant:not(.aside) | 公开传话 |
| 150 | `web/src/components/modals.test.tsx:693` | T_FIXTURE_ARG | RESTORE | minister "同夜他臣" | document.body | 同夜他臣 |
| 151 | `web/src/components/modals.test.tsx:694` | T_FIXTURE_ARG | RESTORE | attendant "旧轮迟到递话" | document.body | 迟到递话 |
| 152 | `web/src/components/modals.test.tsx:723` | T_FIXTURE_ARG | RESTORE | minister "撤回前答复" | document.body before withdraw | 撤回前可见 |
| 153 | `web/src/components/modals.test.tsx:912` | T_FIXTURE_ARG | RESTORE | minister "非流式新答" | document.body | 非流式回话 |
| 154 | `web/src/components/modals.test.tsx:940` | T_FIXTURE_ARG | RESTORE | "杨嗣昌御前低语" | document.body | 低语 |
| 155 | `web/src/components/modals.test.tsx:1291` | T_FIXTURE_ARG | RESTORE | user "辽饷何解？" | document.body | 一夜卷问话 |
| 156 | `web/src/components/modals.test.tsx:1292` | T_FIXTURE_ARG | RESTORE | user "密令：整饬边备。" | document.body (cases that still assert at ~1035) | 密令问话 |
| 157 | `web/src/components/modals.test.tsx:1293` | T_FIXTURE_ARG | RESTORE | minister "臣领旨。" | document.body | 回话 |
| 158 | `web/src/components/modals.test.tsx:1292` | T_FIXTURE_ARG | RESTORE | dup 密令：整饬边备 | document.body | 同 156 |
| 159 | `web/src/components/modals.test.tsx:1293` | T_FIXTURE_ARG | RESTORE | dup 臣领旨 | document.body | 同 157 |
| 160 | `web/src/components/modals.test.tsx:1306` | T_FIXTURE_ARG | RESTORE | attendant "他神色凝重。" | document.body | 低语神色 |
| 161 | `web/src/components/modals.test.tsx:1421` | T_FIXTURE_ARG | RESTORE | archive "乙夜奏对"/"甲夜奏对" | AudienceArchiveModal text | 归档夜正文 |
| 162 | `web/src/components/modals.test.tsx:1765` | T_FIXTURE_ARG | RESTORE | report "**辽东军情**\n- 军前缺饷" | ReportModal | 邸报标题 |
| 163 | `web/src/components/modals.test.tsx:1766` | T_FIXTURE_ARG | RESTORE | report bullet 军前缺饷 | ReportModal | 邸报条目 |
| 164 | `web/src/components/settlementFaces.test.tsx:143` | T_FIXTURE_ARG | RESTORE | "月初已结漕运" | settlementFaces host | 结算面文案 |
| 165 | `web/src/components/settlementGazettePanel.test.tsx:39` | T_FIXTURE_ARG | RESTORE | report={"十月邸报\n一、边报"} | pre.memorial-text | gazette panel 原文 |
| 166 | `web/src/components/settlementGazettePanel.test.tsx:40` | T_FIXTURE_ARG | RESTORE | attendantMessage="奴婢呈报。" | [data-testid=gazette-attendant] | 呈报人话语 |
| 167 | `web/src/mindreadingDelivery.test.tsx:149` | T_FIXTURE_ARG | RESTORE | scene "新落账场景" turn 8 | document.body | 新场景 |
| 168 | `web/src/mindreadingDelivery.test.tsx:178` | T_FIXTURE_ARG | RESTORE | rows "user:失败问话" | rows() | 失败问话 |
| 169 | `web/src/mindreadingDelivery.test.tsx:179` | T_FIXTURE_ARG | RESTORE | rows "user:保留问话" | rows() | 保留问话 |
| 170 | `web/src/mindreadingDelivery.test.tsx:180` | T_FIXTURE_ARG | RESTORE | rows "minister:保留答复" | rows() | 保留答复 |
| 171 | `web/src/mindreadingDelivery.test.tsx:208` | T_FIXTURE_ARG | RESTORE | rows "user:请奏" | rows() | 请奏 |
| 172 | `web/src/staleGuard.test.tsx:342` | T_FIXTURE_ARG | RESTORE | notice "甲：已离开实时回话" | [data-testid=notice] | 陈旧守卫提示 |
| 173 | `web/src/staleGuard.test.tsx:391` | T_FIXTURE_ARG | RESTORE | decisions "辽东战守" | [data-testid=decisions] | 议题按钮文案 |
| 174 | `web/src/staleGuard.test.tsx:472` | T_FIXTURE_ARG | RESTORE | panel text "甲：已撤回" after withdraw in staleGuard fixture | host.querySelector("[data-testid=panel]").textContent | 撤回后面板文案＝夹具固定句 |
