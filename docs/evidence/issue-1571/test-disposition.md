# issue #1571 施工证据：案卷测试处置表（大理寺打回项重做）

- 票：issue #1571 / ADR 0151（案卷 store 摘取，`ming_sim/entities/dossier/`，窄 interface ~15 方法、无 facade、事务两态）
- HEAD：`e88cc29c28a91c28129b320588934aa12768792b`（分支 kimi/issue-1571；行号以该 HEAD 实读为准）
- 判词原话要点（一审打回项，逐句对应下文章节）：
  1. 普通公共读写可机械改径；内化的 decision/transition 测试须经真实 record_verdict/结算入口重投影，或删除只锁内部步骤的绿卡 → §2、§3.1；
  2. pending verdict 必须保留真实入口下的 atomic replace、rollback、跨连接 reopen → §3.2；
  3. 连坐必须保留真实 adapter→DB/state/关系边 tracer → §3.3；
  4. 删除监督/检举家族对 LLM/玩家文本做禁词扫描的测试与生产词表机制（`SUPERVISION_BANNED_PLAYER_TOKENS` / `assert_no_banned_tokens`，触犯盯生成物禁令），不得借「断言零变化」保留盯生成物 → §3.4；
  5. `tests/dossier_test_helpers.py` 只保留共享 fixture/真实入口，不得扩成新 facade → §3.5；
  6. 逐项审 raw SQL 是耐久态行为断言还是内部结构锁 → §4；
  7. AST 扫描显示 66 个测试文件含 concern 直调，内 1,449 个测试函数、538 个函数直接调用广口径 concern 方法 → §1 复核。
- 二审判词（run 01a04322-005c-7337-931b-18d69c935804，判 continue）追加项：
  8. **类4 测试与玩家面政策违规全扫**：法源 = CLAUDE.md 总纲 P6（LLM 输出不可篡改）/ P7（代码成句模板违宪）+ ADR 0150-D5-b（presentation_constraints 由代码管 LLM 措辞被 owner 点名）。原则 = **代码只供结构化事实交给 LLM，或仅做合法布局；删除全部生成物扫描、输出剥词、负向措辞控制和代码成句模板（生产根因 + 测试断言双向删除）**。上一版只删 supervision 一族，二审要求对 §1.3 的 66 文件所触及生产模块全扫，同构违规连生产根因一并入删除清单 → §3.4 已重写为全扫完整版；
  9. **commit 直调旧动词**：`commit=True`/`commit=False` 直调旧动词（`breach_decree_dossier` 等）的测试改走真实 adapter/真实入口，逐文件点名 → §3.3 末小节；
  10. **测试执行纪律**：每个纵切片只跑该片聚焦测试，最终收敛片后全量 `python -m pytest tests/ -q -n auto` 一次（与 pr-slices 口径对齐）→ §5。
- 三审判词（run 01a0437f-49dc-750e-ad69-7d7fb2dc906d，判 continue）追加项：
  11. **类4 `_cost_events`/`_sat` 处置闭合**：不得新增 cost-events 公共入口（40 项公开面无此入口，新增仅供测试的生产 API 违法），也不得回退多份同构裸 SQL helper；只在「append-only/幂等/恢复本身就是契约」的最短 tracer 保留直接 SQLite 耐久态观察（逐函数点名），其余 cost_events 断言改查真实 adapter 的领域结果（state.metrics/派系公开读/关系边/返回的效果意图 dataclass），重复 helper 全删 → §3.5 修订 + 新增 §3.6 逐点去向表；
  12. **类5 玩家面方案闭合**：S1-S5 疑似项逐项裁定（不接受「施工时人工定」），并对 §3.4 删除项逐条点名结构化事实的既有 LLM 消费口 → §3.4 裁定表 + 消费链闭合小节。
- 四审判词（run 01a043a5-b9e1-71b5-bd7d-08728bb92713，判 continue）追加项：
  13. **类2 玩家文本替代路径闭合**：S1 定案写死（同回合结构化拒收事实 → 既有王承恩递话 agent seam → turn_report attendant_message 槽；判决落库后、turn_report 组装前；LLM 失败不落代码兜底句）；P13 纠错重定（终值奏报无现成 LLM 口，最小新建挂 extractor 月报链 db.py:12781 候选装配）；P16/P17/P18/P22 按真实 seam 重指（beat_orchestration.py:234-240 `assemble_beat_inputs` → :328-332 open-beat LLM materials 槽；`current_audience_scene` due_review.py:370-375 筛选扩容；audience_night.py:841-850 旧拼接块整删）；测试证明 = 结构化字段进 LLM 材料/桩 provider 收到事实，不机械断言措辞 → §3.4 消费链闭合表已重写、§5 汇总同步。
- 五审判词（run 01a043ba-4375-7d34-b5ea-0bc5667f1ad0，判 continue）追加项：
  14. **S1 seam 重定 + P13 派生化 + 测试证据处方**：S1 上轮「复用 arrival attendant seam」作废（判词实读 decree.py:195-211 runner 只吃 arrivals{name,location,status}、agents.py:364-378 instructions 限定抵京名单）→ 改走如实列新件（并列 factory/runner 对）+ 失败语义改 fail-loud abort 沿 `resolve_settling_recovery` 重试；P13 删「待终奏机读标记」改派生候选（六审核窄：execution_outcome∈{degraded,transformed}；fulfilled/failed 不入候选、不新增终奏；七审补齐：普通+密令同谓词、不设 secret_order_id 排除；八审：结案判据=status='closed' ∧ closed_turn>0（closed_turn 单独≠结案，db.py:15580-15614），与长差支路 status 值域互斥不重叠），候选读面 db.py:12751 / 写口 db.py:12781 / extractor 注入点 simulation.py:1346 实读挂真链；测试处方（S1 主干/失败/companion 并列、P13、P16-18/P22、N1）与全节禁令明文 → §3.4 消费链闭合表 + §5。
- 九审判词（run 01a043f7-f3a5-788f-bab8-160660a68a23，判 continue）追加项：
  15. **玩家文本「全扫」遗漏补扫**：本票已触及接缝上的同构固定 scene 模板与死函数补入删除/改造清单——audience_night.py:946（入殿句）/:1546-1548（收朝句）/:2065（退下句）/:2100（留侍句）/:1533（「明发旨意：」前缀）+ beat_orchestration.py:337-389 `production_beat_generator` 死函数（生产调用 grep 为零），复扫自增 audience_night.py:886（随侍句）→ P23-P29 续排；法源 ADR 0046（入殿/退下 scene 内容特征化长出、非模板句）+ ADR 0035（故事账正文自由书写不以模板压扁）；统一接前轮定案 BeatInputs seam（typed tags/时地/人物结构化事实保留），失败沿既有 fail-loud、不建新 fallback；测试侧判词点名三点（test_beat_orchestration_503.py:602-622/:781-800、test_p4_guard_new_surfaces_547.py:188-220）+ 复扫命中四个等值 pin → T16-T22 续排；两文件整文复扫方法与结论写入 §3.4 全扫口径 → §3.4 P/T 清单 + 消费链闭合表 + §5 同步。
- 十审判词（run 01a0440d-1032-70f7-ae1b-35171dea46f1，判 continue）追加项：
  16. **P23-P29 路由纠偏 + CLI 同族复扫 + 计数同步**：废九审「统一 BeatInputs seam」口径（BeatInputs 仅 open/enter/exit/close 四种 beat，beat_orchestration.py:46-49）——P23 入殿走 discover_open_enter_tasks（:498-550）→ start_open_enter（:608-639）→ persist_chat_turn_scene（:553-557）回填；P24 收朝走 start_close（:680-702）→ close_night finalize；P25 退下走 start_exit（:641-666）调用侧回填；P26 留侍/P29 随侍无 registry/LLM 路由 → 删固定句根因、留 typed tags+空 body，不新增平行机制；P27 前缀删、原文直落；P28 死函数纯删。CLI terminal.py 复扫命中七处同族回显固定句（:363/:638/:658/:679/:683/:781/:785，含判词未点名的 :658/:679），全部与 P23/P25/P26 同事件 → 调用侧合并不另编号；CLI 测试面无 scene 句等值 pin、无新增 T。**计数定稿：生产 31（P1-P29 + S1 + N1）、测试 22（T1-T22）**；口径 = 同一玩家可见事件跨表面同构固定句归并根因 P 项计数一次，仅独立事件/机制续编新号 → §3.4 清单头 + §5 已同步。
- 十一审判词（run 01a0441f-eaea-71fd-973b-815f74c374e7，判 continue）追加项：
  17. **CLI 玩家可见投影缺口修正**：七处 CLI 固定回显（terminal.py:363/:638/:658/:679/:683/:781/:785）删除方向成立，但纯删除会让既有 LLM open/enter/exit/close scene 只落故事账、不向 CLI 玩家呈现（违 ADR 0046:5）→ 处置改「删固定副本 + 现有生成 scene 可见投影」：open/enter 经 :729 join 结果对象于 :768 打印位前按账序呈现、exit 经 :321 join 结果于 :658 等打印位呈现、close 经 TAG_CLOSE_NIGHT 账读面（audience_night.py:1545-1555 落账）于 :679 打印位呈现；不新增 LLM 路由/固定兜底句/文本扫描；P26 留侍/P29 随侍维持无生成机制现案（:363 删后留侍 CLI 不成句，有意明文）；测试只断 typed 路由/槽位/scene 事件标记进 CLI 输出路径；计数不变（生产 31/测试 22）→ §3.4 消费链表 + 全扫口径 + §5 同步。
- 十二审判词（run 01a04429-28a1-75e4-b05f-327b2f4356f5，判 escalate；御前问题 owner 裁「允许」）追加项：
  18. **首轮控制轮触发域扩展（owner 裁量授权）+ T22 修订 + 两处核对**：「不新增 LLM 路由」禁令仅禁新 generator/seam/fallback——CLI 首轮控制轮（dismiss/court_break/summon/stay，无大臣回话）在控制输入已知后补跑既有 attach/start_open_enter 链，入殿 scene 于下一次玩家交互前汇合并可见（ADR 0046:5），不恢复固定成句、不新建 generator/seam/fallback/beat kind → §3.4 消费链表 + P23 行 + 测试处方增补（断 start_open_enter 调用一次 + TAG_ENTER typed 账 + scene 事件标记进 CLI 输出路径）；T22 改为 test_relation_judge_634.py:527/:528 一并删除（:528 词符扫描盯自由生成物，违共享硬规 #13），typed 断言保留；notary 核对两处已落实：retry 轮（terminal.py:497-515，:501 join 后 :515 只打印 answer）补入同处方投影、账序表述改 list_ledger canonical 序（COALESCE(order_key, seq), id；audience_night.py:362-369）。
- 十三审判词（run 01a045fe-c803-7fb9-8383-e52b99909d8f，判 continue）追加项：
  19. **首轮控制轮 chat_turn 生命周期闭合**：attach 建 generating 无大臣回话轮（audience_night.py:2646-2730），收夜屏障按 `list_in_flight_chat_turns`（:960-975）等在飞轮、不再靠 timeout 放行（:978-1002）——控制轮不收口则 court_break 永久等待；owner 十二审只授权扩展触发域、不授权遗留永驻在飞轮 → 汇合+persist 后复用既有 `complete_rescript_summon_scaffold_turn` consumed 终态写点（db.py:9155-9173「非在飞终态唯一写点」）终结为 'consumed'，失败沿既有 abandon+fail，终结先于 stay/summon/dismiss 返回与 court_break 进屏障；不新建平行生命周期机制；测试改参数化真实 CLI 主干覆盖 dismiss/court_break/summon/stay 四输入、逐案加断 `list_in_flight_chat_turns` 为空 → §3.4 消费链表 + P23 行 + §5 同步。
- **断言零变化口径（三审修订）**：断言零变化只适用于纯迁移部分（机械改径/重投影/读面改径）；删除词表/剥词/固定玩家文本会改变可观察输出，属**合宪行为修正**——相关测试按新输出重写或删除，不得以「零变化」为由保留盯生成物/成句模板（spec/ADR 侧的「零行为变化/玩家无感」声明由主 agent 同步删除，不在本文件）。
- 复核方法：glob `tests/test_*.py` + grep 点名 + AST 实跑（`ast.parse` 全量；脚本口径见 §1.1，逐行数字均实跑产出，非抄判词）。

## 1. 全量清单复核（AST 实跑）

### 1.1 口径（哪些方法名算 concern 直调）

- **concern 方法集** = `GameDB`（`ming_sim/db.py`）案卷块方法：行区间 11971–17217（`_migrate_legacy_secret_order_dossiers` … `interrupt_dossiers_for_character`：颁布格/执行格状态机、双口径进展、否决网、监视检举卫星、连坐毁约、pending verdicts，含将留编排层的 verdict 物化私有步骤）+ 散落段 20235–20369（0073 实际进展读面）与 20385–20464（0053 参与人 roster 校验）。块内共 **114 个方法**；其中**公开方法 68 个**。
- **直调** = 测试函数（`tests/test_*.py` 内 `def/async def test_*`，含参数化）函数体内出现 `ast.Call` 且 `func` 为 `Attribute` 且 `attr ∈ concern 集`（不限 receiver）。helper 函数/模块级的间接调用不计入直调函数数（故 §3.1 的 59 个 call site > 直调函数口径——含 `_promulgated_origin` 这类 per-file helper）。
- **判词口径复算**：判词的 66/1,449/538 在「68 个公开方法 + 3 个被测试直调的私有方法」集合下精确复现——3 个私有 = `_normalize_directive_dossier_payload`（db.py:12082）、`_is_army_pay_grant_payload`（db.py:14062）、`_find_pacification_target`（db.py:12394）。

### 1.2 实测数 vs 判词数

| 口径 | 文件数 | 测试函数总数 | 直调函数数 | concern call sites |
|---|---|---|---|---|
| 判词 | 66 | 1,449 | 538 | — |
| 本复核·判词口径（68 公开 + 3 私有 = 71 名） | **66** | **1,449** | **538**（529 公开直调 + 9 私有直调） | 1,385 |
| 本复核·全块口径（114 名，含全部私有） | 67 | 1,466 | 539 | 1,390 |

三数全中（同一脚本三口径交叉跑批：A=114 名 67/1,466/539，B=68 公开 66/1,449/529，C=判词口径 66/1,449/538；A−B=10 个只调私有方法的函数，其中 9 个落在 66 文件内、判词口径已计入，故 529+9=538）。全块口径多出的 1 文件 = `tests/test_qa_c_p0_1380_1355.py`（唯一直调私有校验 `_validate_participant_roster_references` 的文件，db.py:20421；处置见 §2 表尾注），A−C 差恰为其唯一直调函数（:697）。concern 方法命中频次头部（函数数）：`get_decree_dossier`×166、`create_decree_dossier`×120、`apply_dossier_verdicts`×115、`list_decree_dossiers`×101、`apply_dossier_promulgation`×66、`list_economy_moves_for_dossier`×42、`get_dossier_for_secret_order`×40。

### 1.3 66 文件清单（按直调函数数降序）

| # | 文件 | 测试函数 | 直调函数 |
|---|---|---|---|
| 1 | tests/test_decree_dossiers_571.py | 94 | 88 |
| 2 | tests/test_promulgation_judge_561.py | 37 | 29 |
| 3 | tests/test_pay_order_override_653.py | 69 | 26 |
| 4 | tests/test_override_breach_costs_564.py | 21 | 21 |
| 5 | tests/test_execution_pressure_654.py | 46 | 20 |
| 6 | tests/test_army_pay_decree_1503.py | 18 | 16 |
| 7 | tests/test_promulgation_seam_560.py | 19 | 16 |
| 8 | tests/test_commitment_backlash_626.py | 14 | 14 |
| 9 | tests/test_dossier_links_559.py | 23 | 14 |
| 10 | tests/test_military_order_materialize_521.py | 19 | 14 |
| 11 | tests/test_punishment_materialize_517.py | 24 | 14 |
| 12 | tests/test_grant_allocation_materialize_518.py | 17 | 13 |
| 13 | tests/test_due_review_621.py | 21 | 12 |
| 14 | tests/test_secret_order_payoff_1504.py | 24 | 12 |
| 15 | tests/test_executor_routing_721.py | 28 | 11 |
| 16 | tests/test_secret_order_monthly_progress_566.py | 19 | 11 |
| 17 | tests/test_assignment_materialize_520.py | 18 | 10 |
| 18 | tests/test_pacification_materialize_522.py | 20 | 10 |
| 19 | tests/test_pihong_dossier_1490.py | 40 | 10 |
| 20 | tests/test_supervision_625.py | 16 | 10 |
| 21 | tests/test_execution_joint_liability_565.py | 12 | 9 |
| 22 | tests/test_referral_materialize_524.py | 16 | 9 |
| 23 | tests/test_refugee_loop_652.py | 21 | 9 |
| 24 | tests/test_dossier_endorsements_612.py | 11 | 8 |
| 24 | tests/test_dossier_reported_progress_619.py | 8 | 8 |
| 25 | tests/test_revoke_authority_materialize_523.py | 18 | 8 |
| 26 | tests/test_secret_dossier_participants_1252.py | 10 | 8 |
| 27 | tests/test_fiscal_beyond_intent_1260.py | 9 | 7 |
| 28 | tests/test_grant_reconciliation_567.py | 8 | 7 |
| 29 | tests/test_rescript_choices_563.py | 12 | 7 |
| 30 | tests/test_authorization_materialize_528.py | 12 | 6 |
| 31 | tests/test_breach_plea_623.py | 25 | 5 |
| 32 | tests/test_covert_levy_651.py | 19 | 5 |
| 33 | tests/test_faction_denunciation_627.py | 9 | 5 |
| 34 | tests/test_ledger_sim_recon_569.py | 9 | 5 |
| 35 | tests/test_pending_actions.py | 83 | 5 |
| 36 | tests/test_referral_materialize_524.py | 16 | 5 |
| 37 | tests/test_authority_ledger_611.py | 13 | 4 |
| 38 | tests/test_deformation_dual_rail_622.py | 9 | 4 |
| 39 | tests/test_session_cli_fallback.py | 84 | 4 |
| 40 | tests/test_character_knowledge_489.py | 69 | 3 |
| 41 | tests/test_extractor_slot_routing_629.py | 6 | 3 |
| 42 | tests/test_strategy_selection_568.py | 6 | 3 |
| 43 | tests/test_urge_lever_624.py | 23 | 3 |
| 44 | tests/test_audience_night_498.py | 17 | 2 |
| 45 | tests/test_driver.py | 44 | 2 |
| 46 | tests/test_execution_tenure_613.py | 11 | 2 |
| 47 | tests/test_family_tail_615.py | 2 | 2 |
| 48 | tests/test_impeachment_surge_655.py | 13 | 2 |
| 49 | tests/test_multi_directive_502.py | 17 | 2 |
| 50 | tests/test_p4_guard_new_surfaces_547.py | 5 | 2 |
| 51 | tests/test_surcharge_causal_chain_650.py | 28 | 2 |
| 52 | tests/test_web_audience_night_498.py | 8 | 2 |
| 53 | tests/test_advance_paths_atomic.py | 34 | 1 |
| 54 | tests/test_appointment_tenure_607.py | 6 | 1 |
| 55 | tests/test_audience_background.py | 20 | 1 |
| 56 | tests/test_credit_events_628.py | 4 | 1 |
| 57 | tests/test_decree_commitment_creation_136.py | 33 | 1 |
| 58 | tests/test_effect_origin_558.py | 13 | 1 |
| 59 | tests/test_family_tail_restore_570.py | 1 | 1 |
| 60 | tests/test_interim_path_materialize_529.py | 15 | 1 |
| 61 | tests/test_minister_context.py | 27 | 1 |
| 62 | tests/test_multi_intent_utterance_519.py | 6 | 1 |
| 63 | tests/test_office_rank_562.py | 18 | 1 |
| 64 | tests/test_pay_order_override_extraction_653.py | 4 | 1 |
| 65 | tests/test_relation_capture_633.py | 29 | 1 |
| 66 | tests/test_state_reload.py | 15 | 1 |

合计 1,449 测试函数 / 538 直调函数。另有 10 个文件仅经 helper 直调 `record_dossier_decision`/`transition_decree_dossier`（不在判词 66 口径内但 59+12 站点在内）→ §3.1 全覆盖。

## 2. 逐文件处置（66 文件）

处置类定义：**机械改径** = 调用点换名/换 import（GameDB→store/段适配器），布景与断言均不动（文件内 raw SQL 站点逐处定性见 §4，读断言改径不算拆分）；**重投影** = 布景含被内化步骤直调（`record_dossier_decision`/`transition_decree_dossier`/私有方法）或绕写径 SQL 置位，须改经真实 verdict/结算/批红/迁移入口重打布景，终断言不变；**删除** = 盯生成物或只锁内部步骤的绿卡；**部分拆分** = 同文件多类并存；**保留家族** = 判词点名保留的 pending verdict / 连坐 tracer 主体（调用面仍机械改径）。函数账 = 测试函数总数/直调函数数；代表行 = 直调函数实读代表（`函数名:行`）。

| # | 文件（账） | 处置 | 代表行与要点 |
|---|---|---|---|
| 1 | test_decree_dossiers_571.py（94/88） | **部分拆分** | 主体机械改径（create/get/list/`apply_dossier_verdicts` 公开面，如 :27/:58/:70 写界、:3383-3406 跨连接恢复审计、:3427-3484 rejection contract 均经 `apply_dossier_verdicts` 真实入口）；rdd×17/tdd×8 站点重投影（§3.1：:635/:714/:1395/:1414/:1590/:1637/:2319/:2351/:2888/:2959）；:351 `UPDATE status='closed'` 置位重投影（§4）。`record_dossier_execution` 自身契约组（:1395/:1414/:1590）属公开方法机械改径 |
| 2 | test_promulgation_judge_561.py（37/29） | **部分拆分** | 判官上下文/否决网机械改径（:22/:89/:125）；rdd:477 重投影（布景授权案卷顺颁，§3.1）；:160 INSERT 造颁布史组合 → 重投影（§4）；:428/:465 UPDATE 置位 → :465 为「重读后取新行」测试（:450-494）的对比布景，保留语义、改径或显式 fixture（§4）；pending verdict 读面 :381/:531/:534/:888/:1061/:1099/:1130/:1164/:1191/:1231 保留（§3.2） |
| 3 | test_pay_order_override_653.py（69/26） | **机械改径** | `apply_dossier_promulgation`×38 为真实顺颁/强颁路径（如 :290/:314/:359 golden），store 化后 = record_verdict + 段适配器物化缝，断言零变化 |
| 4 | test_override_breach_costs_564.py（21/21） | **部分拆分** | 连坐毁约 tracer 主体保留（§3.3，:36/:74/:164/:371/:444/:513/:545）；rdd×5（:126/:430/:433/:483/:484）重投影（§3.1）；:316-368 legacy 迁移 + 跨连接 reopen×2 + 幂等 → 保留（迁移契约，§3.2/§4）；:412 UPDATE decisions 置位、:475 UPDATE closed/closed_turn 置位 → 重投影（§4） |
| 5 | test_execution_pressure_654.py（46/20） | **部分拆分** | fan-out/locality 机械改径（:242/:312/:362 等）；:623 `test_normalize_payload_locality_and_target_kind` 直调私有 `_normalize_directive_dossier_payload` → 重投影（归一规则经 create 公共写界断 region_id/target_kind 落库；fail-loud 分支经真实暂存缝）；:222-239 `test_region_id_column_and_composite_indexes` PRAGMA/sqlite_master 结构锁 → 迁 store `ensure_schema` 契约测试（§4）；:452/:994/:1019/:1038 SQL 置位 → 重投影（§4） |
| 6 | test_army_pay_decree_1503.py（18/16） | **部分拆分** | 军饷 decree 机械改径（:133/:255/:292）；:209 `test_revise_away_from_xiexang_clears_pay_only_fields` 主体走真实暂存入口（`stage_grant_allocation_candidate`）保留，内嵌 `_is_army_pay_grant_payload` 私有谓词断言 → 改断落库 payload 耐久面（pending_actions.payload_json 已无 pay-only 字段），私有直调点删除 |
| 7 | test_promulgation_seam_560.py（19/16） | **保留家族** | pending verdict 家族全表保留（§3.2：:41 崩溃复用持久批次、:81 损坏判决恢复+全量回滚、:500 部分批次回滚、:527 atomic replace 原子回滚、:541 跨 turn 隔离）；save/get 两方法即 ADR 0151 决定 7 自主 commit 例外对，机械改径到 store 公开面；:114 损坏行 fixture 保留（§4） |
| 8 | test_commitment_backlash_626.py（14/14） | **保留家族** | backlash 触发 tracer 全表保留（§3.3：:157/:208/:251 AC1 触发、:341 AC2 持久、:695 跨恢复、:762 幂等）；`trigger_commitment_backlashes`（db.py:13838）为消费侧编排，施工归属按 ADR 边界（结算消费留段适配器），测试断言零变化。注：:813-957 `test_ac6_presentation_sentinel_distinct_from_625`（含 :906-915 avoid_phrases 断言、:923-925 BACKLASH 词表自 pin）按二审判词全扫入 §3.4 删除清单 |
| 9 | test_dossier_links_559.py（23/14） | **部分拆分** | 关联槽读写机械改径（:25/:42）；rdd×7（:169/:211/:255/:302/:494/:495/:542）重投影（§3.1：:494-495 的 rejected+withdrawn 须先打回再经真实批红链） |
| 10 | test_military_order_materialize_521.py（19/14） | **机械改径** | 军令状物化（:125/:175/:220），`apply_dossier_verdicts` 真实入口断言零变化 |
| 11 | test_punishment_materialize_517.py（24/14） | **部分拆分** | 物化主体机械改径（:87/:120/:131）；:385/:463 直调私有 `_normalize_directive_dossier_payload` 验 admission → 重投影经真实暂存/admission 缝（stage→materialize 的 fail-loud）；:833/:845/:892/:897 COUNT 断言改径读面（§4） |
| 12 | test_grant_allocation_materialize_518.py（17/13） | **机械改径** | 拨帑物化（:92/:136/:167），`list_economy_moves_for_dossier`/`apply_dossier_verdicts` 公开面 |
| 13 | test_due_review_621.py（21/12） | **部分拆分** | 到期复核四缝机械改径（:271/:311/:340）；helper `_promulgated_origin`:54 的 rdd 重投影（§3.1）；:358/:399/:500/:657 `UPDATE status` 置位（造 closed/executing 态）→ 重投影经 record_execution/复核真实入口（§4）；:114 cost_events 读、:317/:335/:344/:377 COUNT、:405/:419 id 集 → 耐久断言改径读面（§4） |
| 14 | test_secret_order_payoff_1504.py（24/12） | **机械改径** | 密令兑付/实际进展双轨读面（:165/:198/:233），`sum_dossier_actual_progress_units` 等公开读 |
| 15 | test_executor_routing_721.py（28/11） | **部分拆分** | 执行人路由机械改径（:91/:108/:125）；:247/:288/:306 SELECT by pending_action_id、:329-457 COUNT 组 → 耐久断言改径 get/list 读面（§4）；:493 参数化 `UPDATE decree_dossiers SET {column}` 任意列置位 → 内部结构锁，重投影或删除（§4） |
| 16 | test_secret_order_monthly_progress_566.py（19/11） | **机械改径** | 密令月度进展（:76/:170/:239） |
| 17 | test_assignment_materialize_520.py（18/10） | **机械改径** | 委任物化（:241/:264/:436）；:589/:891 SELECT execution_outcome/note/status → 改径 `get_decree_dossier`（§4） |
| 18 | test_pacification_materialize_522.py（20/10） | **部分拆分** | 招抚物化机械改径（:87/:106/:142）；rdd/tdd :823/:824 重投影（§3.1）；:696 `test_pacification_unqualified_name_does_not_create_false_ambiguity` 主体走真实 session 路径保留，两处 `_find_pacification_target` 私有直调断言（:704/:705）删除（`_mentioned_pacification_target` 真实缝已承载同行为，:707） |
| 19 | test_pihong_dossier_1490.py（40/10） | **部分拆分** | 批红票面机械改径（:173/:393/:905）；:1449 PRAGMA 负向闭集（`rescript_origin` 不在列）→ 迁 store `ensure_schema` 契约（§4）；:2685 SELECT decisions、:3135/:3154 COUNT → 耐久断言改径读面（§4） |
| 20 | test_supervision_625.py（16/10） | **部分拆分** | 监视读写机械改径（:240/:300/:321 等；直调 10 中含被删函数）；**删除 :578-635 `test_ac5_banned_tokens_absent_from_named_surfaces`（盯生成物，§3.4）**；:209-237 `test_ac1_presence_exposure_schema_pragma_and_no_dulling_cols` 列白名单等值锁（PRESENCE/EXPOSURE_ALLOWED_COLS，supervision.py:104-113）+ 全库禁列片段扫描（FORBIDDEN_DULLING_COL_FRAGMENTS，supervision.py:115）→ 迁 store `ensure_schema` 契约（§4；schema 面守门非盯生成物）；:474/:493 UPDATE executing、:508/:527 INSERT reconciliations 置位 → 重投影（§4） |
| 21 | test_execution_joint_liability_565.py（12/9） | **保留家族** | 连坐 tracer 全表保留（§3.3：`_close_via_adapter`:59-64 = `issue_engine.apply_score_extraction` 真实段适配器，断 decree_cost_events/`factions.satisfaction`/`get_relation_edge_events(event_kind="连坐")`/execution_note）；:427 `test_direct_record_dossier_execution_does_not_trigger_joint_liability` 边界 pin 保留（store 化后仍钉「裸写不扣连坐」）；:152 UPDATE executing 重放布景 → 重投影（§4）；:367 roster 注入为读端容异 fixture → 显式保留（理由见 §4） |
| 22 | test_referral_materialize_524.py（16/9） | **部分拆分** | 下议物化机械改径（:153/:207/:224）；:423/:435/:467/:523 直调私有 `_normalize_directive_dossier_payload` 验 admission → :467 与 staging 缝真实入口测试（:448 `test_responsible_bodies_personal_name_rejected_at_staging`）同规则重复者**删除**，其余重投影经真实 admission 缝 |
| 23 | test_refugee_loop_652.py（21/9） | **部分拆分** | 难民环机械改径（:291 等）；rdd×2（:121/:146）重投影（§3.1）；:115/:136 跨连接 tracer 保留（§3.2 末）；:451 DELETE reconciliations、:453 UPDATE closed_turn 置位 → 重投影（§4） |
| 24 | test_dossier_endorsements_612.py（11/8） | **机械改径** | 背书读写（:72/:139/:189）；:186/:213/:299/:722/:834 COUNT 断言改径 `list_dossier_endorsements`/`list_decree_dossiers` 读面（§4） |
| 25 | test_dossier_reported_progress_619.py（8/8） | **部分拆分** | 奏报进展读写机械改径（:77/:122/:152）；:115-119 PRAGMA 负向闭集（general 轨无 secret/track 列）→ 迁 store `ensure_schema` 契约（§4）；:103/:147/:167/:336 COUNT → 耐久断言改径 `list_dossier_progress`（§4） |
| 26 | test_revoke_authority_materialize_523.py（18/8） | **机械改径** | 收权物化（:127/:389/:449） |
| 27 | test_secret_dossier_participants_1252.py（10/8） | **部分拆分** | 密案参与人机械改径（:56/:101/:113）；:152 roster 重置为崩溃重放布景 → 保留 fixture 语义、改径或显式标注（§4） |
| 28 | test_fiscal_beyond_intent_1260.py（9/7） | **机械改径** | 逾制 tracer（:112/:180/:244） |
| 29 | test_grant_reconciliation_567.py（8/7） | **机械改径** | 护送对账（:84/:129/:153） |
| 30 | test_rescript_choices_563.py（12/7） | **部分拆分** | 批红抉择机械改径（:29/:145/:160；:29 真实密旨入口保留 §3.2）；rdd:207（hold 布景）重投影经真实批红链（§3.1）；:149 UPDATE payload、:216 SELECT decisions → §4 |
| 31 | test_authorization_materialize_528.py（12/6） | **机械改径** | 授权物化（:139/:214/:249） |
| 32 | test_breach_plea_623.py（25/5） | **机械改径** | 毁约陈情（:143/:247/:333）；:59 cost_events 读改径（§4） |
| 33 | test_covert_levy_651.py（19/5） | **部分拆分** | 隐征消费机械改径（:103/:149/:298）；raw SQL 集群 12 处（:25/:56/:133/:145/:156/:164/:173/:211/:506/:512/:530/:536）→ §4 逐项：置位重投影、造史（:506 force_promulgated 史）经真实判决+批红强颁入口重打、检举行（:530/:536）经 `accept_faction_denunciations` 真实入口重投影 |
| 34 | test_faction_denunciation_627.py（9/5） | **部分拆分** | 检举事实/承接机械改径（:245/:300/:355）；**删除 :494-610 `test_ac5_zero_template_banned_tokens_exposure_and_622`（盯生成物，§3.4）**；:95/:112/:121/:454 UPDATE 置位 → 重投影（§4）；:510-542 COUNT → 改径读面 |
| 35 | test_ledger_sim_recon_569.py（9/5） | **部分拆分** | 台账-模拟对账机械改径（:72/:105/:213）；:305 UPDATE 置位 → 重投影（§4） |
| 36 | test_pending_actions.py（83/5） | **机械改径** | pending 动作大表（:923/:990/:2041） |
| 37 | test_authority_ledger_611.py（13/4） | **部分拆分** | 授权台账机械改径（:96/:263）；rdd :34（helper `_eligible_dossier`）/:221 重投影（§3.1） |
| 38 | test_deformation_dual_rail_622.py（9/4） | **机械改径** | 变形双轨（:117/:257/:313）；:102 cost_events 读改径（§4）。注：:313-378 `test_ac6_sentinel_no_system_tokens_on_three_surfaces`（含 :110-111 模块级 `_BANNED_SURFACE_TOKENS` 别名）按二审全扫入 §3.4 删除清单 |
| 39 | test_session_cli_fallback.py（84/4） | **机械改径** | 会话回落（:521/:796/:889） |
| 40 | test_character_knowledge_489.py（69/3） | **部分拆分** | 认知投影机械改径（:853/:890）；:917 UPDATE roster 置位（:908 测试布景）→ 重投影或显式 fixture（§4） |
| 41 | test_extractor_slot_routing_629.py（6/3） | **部分拆分** | rdd×3（:103/:168/:209）重投影（§3.1）；:170 UPDATE executing 置位 → 重投影（§4） |
| 42 | test_strategy_selection_568.py（6/3） | **机械改径** | 战略选择（:157/:311/:379） |
| 43 | test_urge_lever_624.py（23/3） | **部分拆分** | 催办杠杆机械改径（:238/:302/:586）；helper `_promulgated_origin`:67 的 rdd 重投影（§3.1）；:648 cost_events 读改径（§4） |
| 44 | test_audience_night_498.py（17/2） | **机械改径** | 夜对（:339/:463，含重开恢复） |
| 45 | test_driver.py（44/2） | **机械改径** | driver 主链（:824/:1012） |
| 46 | test_execution_tenure_613.py（11/2） | **机械改径** | 执行任期（:253/:405） |
| 47 | test_family_tail_615.py（2/2） | **部分拆分** | :126/:275 两函数机械改径主体；helper `_grant_self_scope_authority`:70 的 rdd 重投影（§3.1）；:180 SELECT decisions 改径 `list_decree_dossier_decisions`（§4）；:353 pending 读面保留（§3.2）；:138-139 跨连接恢复保留；`_cost_events`/`_sat` import 随 §3.5 处置 |
| 48 | test_impeachment_surge_655.py（13/2） | **部分拆分** | 弹劾潮候选机械改径（:59/:95）；:26/:108 UPDATE closed/outcome 置位 → 重投影；:134 roster 注入 = 读端连坐投影 fixture **显式保留**（:120-124 docstring 自证：公共写界造不出「delegator 不占 participant 行」形状，钉 gather 读端上溯，§4）；:379/:382 closed_turn 置位 → 重投影（§4） |
| 49 | test_multi_directive_502.py（17/2） | **机械改径** | 多旨意（:148/:211） |
| 50 | test_p4_guard_new_surfaces_547.py（5/2） | **机械改径** | P4 面守门（:226/:361） |
| 51 | test_surcharge_causal_chain_650.py（28/2） | **部分拆分** | 加派因果链机械改径主体；rdd×3（helper `_decree`:62、:172、:479/:480）重投影（§3.1） |
| 52 | test_web_audience_night_498.py（8/2） | **机械改径** | web 夜对（:346/:636） |
| 53 | test_advance_paths_atomic.py（34/1） | **机械改径** | :868 |
| 54 | test_appointment_tenure_607.py（6/1） | **机械改径** | :106 任命任期回滚审计 |
| 55 | test_audience_background.py（20/1） | **机械改径** | :272 |
| 56 | test_credit_events_628.py（4/1） | **部分拆分** | :177 机械改径；:146 UPDATE roster 置位 → 重投影/fixture（§4）。注：:580-584 CREDIT 词表/扫描面 pin 块按二审全扫入 §3.4 删除清单（函数主体保留） |
| 57 | test_decree_commitment_creation_136.py（33/1） | **部分拆分** | :29 机械改径；helper `_promulgated_commitment_origin`:21 的 rdd 重投影（§3.1） |
| 58 | test_effect_origin_558.py（13/1） | **部分拆分** | :36 机械改径；helper `_promulgated_policy`:16/:17 的 rdd+tdd 重投影（§3.1） |
| 59 | test_family_tail_restore_570.py（1/1） | **部分拆分** | :75 机械改径主体；:135 UPDATE 置位 → 重投影（§4） |
| 60 | test_interim_path_materialize_529.py（15/1） | **机械改径** | :610 |
| 61 | test_minister_context.py（27/1） | **机械改径** | :583 |
| 62 | test_multi_intent_utterance_519.py（6/1） | **机械改径** | :168 |
| 63 | test_office_rank_562.py（18/1） | **部分拆分** | :73 机械改径；:265-291 break_rank 回填迁移 + 跨连接幂等 reopen → 保留（迁移契约）；:270 UPDATE payload 造 legacy 形状 = 迁移 fixture 保留（§4）；:33/:68/:87 读改径 |
| 64 | test_pay_order_override_extraction_653.py（4/1） | **机械改径** | :8 |
| 65 | test_relation_capture_633.py（29/1） | **部分拆分** | :387 机械改径；helper `_promulgated_dossier`:308 的 rdd 重投影（§3.1） |
| 66 | test_state_reload.py（15/1） | **机械改径** | :149 |
| — | test_qa_c_p0_1380_1355.py（17/1，判词 66 口径外，全块口径第 67 文件） | **删除或重投影** | :697-708 `test_roster_reject_emperor_has_human_tip` 直调私有 `_validate_participant_roster_references` 并锁异常提示措辞 → 只锁内部步骤的绿卡；行为已由 571:70 `test_dossier_roster_rejects_unknown_character_references_at_write_boundary` 公共写界覆盖 → **删除**（或重投影为经 `create_decree_dossier` 写界断 ValueError，不锁措辞） |

文件级汇总：**机械改径 30 文件 / 部分拆分 33 文件 / 保留家族 3 文件**（test_promulgation_seam_560、test_commitment_backlash_626、test_execution_joint_liability_565——626 内含 1 盯生成物函数删除 :813-957）+ 口径外删除 1 函数（qa_c_p0:697）。删除函数合计 4 个（625:578、627:494 盯生成物，524:467 同规则重复，qa_c_p0:697 私有校验绿卡）+ 522:704/:705 两点私有断言删除 + §3.4 二审全扫新增删除（626:813-957 整函数、622:313-378 整函数、628:580-584 删块、624:433-516 内两扫描块，及 66 口径外 629 六函数一 helper），均见 §3。

## 3. 点名家族专项

### 3.1 `record_dossier_decision`（59 站点）/ `transition_decree_dossier`（12 站点）重投影路径

生产外部零调用已实证：`grep record_dossier_decision|transition_decree_dossier ming_sim/` 仅中 db.py 内部——两方法已是内部子步骤：`record_dossier_decision` 被 `apply_dossier_promulgation` 内调（db.py:15648/:15713），`transition_decree_dossier` 被 `close_decree_dossier`（:15551）、`apply_dossier_promulgation`（:15733-16000）、各 `_apply_*_verdict_effect` 物化步骤（:16804-17197）与密令路（:21489/:21679）内调；db.py 之外的生产模块零调用。生产真实入口 = `decree.py:2525`（`apply_dossier_verdicts`，结算判决注入）与 `decree.py:2534`（`apply_dossier_promulgation`），批红 hold/withdrawn 真实入口 = `rescript_actions.apply_rescript_batch`（rescript_actions.py:1063，hold 子步骤 :962）与 decree.py:645/:651 的 `dossier_decision` 映射。store 化后两方法内化为 `record_verdict` 私有子步骤（ADR 0151 决定 5），59+12 站点全部按下表重投影或改径，无例外直调。

重投影路径映射（按布景语义分四类）：

- **P＝"promulgated" 布景** → 真实判决入口 `apply_dossier_verdicts(state, [{"dossier_id": id, "decision": "promulgated"}], content=…)`（生产同款，decree.py:2525）；store 落地后 = `record_verdict` + 段适配器物化。
- **R＝"rejected" 布景** → `rejected_verdict(...)` fixture（dossier_test_helpers.py:16）+ `apply_dossier_verdicts`。
- **H/W＝"hold"/"withdrawn" 布景** → 真实批红链：先 R 置 `rescript_pending=1`（`record_dossier_decision` 的内部前置，db.py:15487-15492 自证 hold/withdrawn 只可承接「打回＋批红待抉择」组合态），再经 `apply_rescript_batch`（rescript_actions.py:1063）真实抉择入口落 hold/withdrawn。
- **X＝transition→"executing" 布景** → `apply_dossier_promulgation`/`apply_dossier_verdicts` 一步落 executing（现行真实模式自证：test_execution_joint_liability_565.py:34-35 顺颁后 status 即 executing），或 `record_dossier_execution(outcome="executing")` 公开写面。

`record_dossier_decision` 59 站点逐文件账（行号实跑）：

| 文件 | 站点行 | 所属函数/helper | 语义 | 重投影 |
|---|---|---|---|---|
| test_decree_dossiers_571.py | :644 :916 :1401 :1420 :1500 :1532 :1575 :1596 :1643 :2093 :2970 | :635/:905/:1395/:1414/:1482/:1513/:1557/:1590/:1637/:2085/:2959 | P | P |
| 〃 | :2325+:2329 | test_held_dossier_reenters_only_for_next_month_rejudgment:2319 | R→H | R+H（真实批红链；行为断言=留中只可在下月重判不变） |
| 〃 | :2361+:2364 | test_promoted_held_dossier_exposes_only_current_verdict_to_simulator:2351 | R→H | R+H（同上） |
| 〃 | :2896+:2899 | test_withdrawn_rescript_records_closed_turn:2888 | R→W | R+W（真实批红收回；断言 closed_turn 不变） |
| test_dossier_links_559.py | :169 :211 :255 :302 :542 | :165/:206/:250/:297/:539 | P | P |
| 〃 | :494+:495 | test_withdrawn_rejected_dossier_is_not_referenceable:491 | R+W | R+W |
| test_override_breach_costs_564.py | :126 | test_midzhi_rejudgment_never_applies_party_satisfaction:117 | H | R+H |
| 〃 | :430+:433 | test_force_rejects_old_only_judge_reactions_atomically:426 | H→R | R+H 再 R（重判链） |
| 〃 | :483+:484 | test_active_commitment_can_breach_closed_issued_dossier_but_not_never_issued:461 | R+W | R+W |
| test_extractor_slot_routing_629.py | :103 :168 :209 | :84/:137/:190 | P | P |
| test_surcharge_causal_chain_650.py | :62(helper) :172 :479 :480 | `_decree`/:162/:475 | P | P |
| test_refugee_loop_652.py | :121 :146 | :115/:136 | P | P |
| test_promulgation_judge_561.py | :477 | test_gate_evidence_reloads_dossier_after_reconsideration_mutation:450 | P | P |
| test_rescript_choices_563.py | :207 | test_held_dossier_rejection_stigma_is_idempotent_across_months:201 | H | R+H（本文件即批红真实入口测试群，入口不动） |
| test_pacification_materialize_522.py | :823 | test_special_decree_origin_cannot_authorize_pacification_allegiance:808 | P | P |
| test_authority_ledger_611.py | :34(helper `_eligible_dossier`) :221 | —/test_authority_changes_rejects_ineligible_keeps_legal_peer:212 | P；R | P；R |
| test_effect_origin_558.py | :16(helper `_promulgated_policy`) | — | P | P |
| test_event_trigger_gate.py | :23(helper `_promulgated_dossier`) | — | P | P |
| test_person_delta_adapter.py | :30(helper `_promulgated_dossier`) | — | P | P |
| test_family_tail_615.py | :70(helper `_grant_self_scope_authority`) | — | P | P |
| test_relation_capture_633.py | :308(helper `_promulgated_dossier`) | — | P | P |
| test_urge_lever_624.py | :67(helper `_promulgated_origin`) | — | P | P |
| test_due_review_621.py | :54(helper `_promulgated_origin`) | — | P | P |
| test_decree_commitment_creation_136.py | :21(helper `_promulgated_commitment_origin`) | — | P | P |
| test_decree_commitment_schema_136.py | :16(helper `_promulgated_commitment_origin`) | — | P | P |
| test_decree_commitment_settlement_229.py | :18(helper `_promulgated_commitment_origin`) | — | P | P |
| test_issue_entities.py | :20(helper `_decree_origin`) | — | P | P |
| test_new_issues_section_rejections.py | :20(helper `_decree_origin`) | — | P | P |
| test_settle_channel_injection.py | :32(helper `_decree_origin`) | — | P | P |
| test_staged_commitment_620.py | :45(helper `_promulgated_origin`) | — | P | P |
| test_faction_brew_637.py | :398(helper `_eligible_dossier`) | — | P | P |
| test_presentation_p4_family_629.py | :169(helper `_policy_dossier`) | — | P | P |

`transition_decree_dossier` 12 站点：test_decree_dossiers_571.py :645/:719/:1402/:1421/:1597/:1644/:2977/:2979（:635/:714/:1395/:1414/:1590/:1637/:2959 七函数）、test_effect_origin_558.py:17(helper)、test_event_trigger_gate.py:24(helper)、test_pacification_materialize_522.py:824（:808）、test_person_delta_adapter.py:31(helper)——全部 X 类，随同函数 P 布景一并重投影。

绿卡审计结论：59+12 站点**无一以 record_dossier_decision/transition_decree_dossier 自身校验语义为断言对象**（无 `pytest.raises` 钉两方法内部分支），全部是布景——故本家族无「只锁内部步骤的绿卡」删除项，全部重投影；真正锁私有步骤的绿卡在 §2（654:623、517:385/:463、524:423/:435/:467/:523、1503:209、522:704/:705、qa_c_p0:697），逐点已给重投影或删除。布景重投影后断言零变化（P/R/H/W/X 终态由真实入口产生同形状耐久行）。

### 3.2 pending verdict 家族：真实入口下的 atomic replace / rollback / 跨连接 reopen 保留清单

生产机制：`save_pending_promulgation_verdicts`（db.py:16413，判词在 simulator 开工前落库、自主 commit——ADR 0151 决定 7 唯一例外）与 `get_pending_promulgation_verdicts`（db.py:16429）；真实链路 = `decree.resolve_directives` → provider → save → simulator/恢复读回。以下测试**全部保留**，调用面机械改径到 store 公开读面+两态写，断言零变化：

| 文件:行 | 函数 | 保留口径 |
|---|---|---|
| test_promulgation_seam_560.py:41 | test_public_resolve_seam_reuses_durable_batch_after_pre_simulation_crash | 崩溃可读回：真实 resolve 入口下持久批次复用、不重跑 provider（:77 `calls == [[dossier_id]]`） |
| 〃:81 | test_public_resolve_seam_wraps_corrupt_durable_verdict_on_real_recovery | rollback：损坏持久判决恢复 fail-loud（SettlementAbort stage=promulgation），game_state/metrics/dossier 全量回滚（:103-156 基线比对） |
| 〃:159 | test_public_resolve_seam_rejects_bad_shape_without_persisting | 坏形状不落库（:170 读面断言） |
| 〃:210/:241/:273/:296/:333/:366/:400/:441 | public_resolve_seam 拒收/审计八连 | 真实入口下 verdict 校验/拒收归因/rejection 审计 |
| 〃:470 | test_public_resolve_seam_rejects_incomplete_persisted_batch | 残缺持久批次 fail-loud（:482 save 布景 + :486 真实恢复入口） |
| 〃:500 | test_public_resolve_seam_rolls_back_partial_batch_persistence | rollback：真实入口下部分批次持久化中途失败全滚（:523 读面断言） |
| 〃:527 | test_turn_batch_replacement_rolls_back_atomically_on_partial_bad_row | **atomic replace**：同 turn 批次替换遇坏行原子回滚、原批次原样（:538）——直调 save/get 两方法即 store 两态例外面本身，改径后仍公开 |
| 〃:541 | test_public_resolve_seam_ignores_previous_turn_batch | turn 域隔离：上一 turn 批次不串扰 |
| test_promulgation_judge_561.py:531 | test_run_resolve_arm_recovers_settled_verdicts_from_history | 真实 run_resolve arm 从持久历史恢复已落判决（:531 save/:534 get） |
| 〃:381/:888/:1061/:1099/:1130/:1164/:1191/:1231 | 判官默认批次组 | get 读面断言（机械改径） |
| test_override_breach_costs_564.py:316 | test_legacy_persisted_reaction_severity_migrates_narrowly_and_idempotently | **跨连接 reopen**：GameDB 关开×2（:343-347）证迁移幂等收窄；:349 get 读回 + :353/:358 裸读 legacy 行（迁移 fixture 保留，§4） |
| test_rescript_choices_563.py:69 | test_real_midzhi_entry_reaches_provider_and_persists_stigma | 真实密旨入口持久留痕读回 |
| test_family_tail_615.py:353 | test_secret_order_0055_exempt_not_in_rescript_with_break_rank | 0055 豁免不入批红面读断言；:138-139 跨连接恢复链 |

跨连接 reopen 的另一独立家族（非 pending verdict 但同属耐久 tracer，保留）：test_refugee_loop_652.py:109/:129（`sqlite3.connect` 第二连接证加派耐久/外事务回滚）、571:3383（GameDB 重开断 rejection verdict 审计行）、562:265-291（回填迁移幂等重开×2）。

### 3.3 连坐/毁约家族：真实 adapter→DB/state/关系边 tracer 保留清单

生产挂载点（真实 adapter 链）：`issues.py:8195-8217`（段适配器内 `record_dossier_execution` → `apply_execution_joint_liability`）、`due_review.py:533/:555`（到期复核同链，due_review.py:506 注释自证「经既有 record_dossier_execution + 连坐挂载点（仅终值）」）、`breach_plea.py:738/:853/:877`（毁约写径）。以下 tracer **全表保留**；store 化后连坐**判定写**进 store（`apply_joint_liability` 判定写，ADR 0151 决定 2/5），结算消费留段适配器。tracer 断言面不动，但**直调 GameDB 案卷块旧动词的调用点须改走真实 adapter/真实入口**（二审类4 附：`commit=True`/`commit=False` 直调点逐文件点名见本节末小节）：

| 文件 | 函数（行） | tracer 面 |
|---|---|---|
| test_execution_joint_liability_565.py（12 全保留） | :67 fulfilled 零连坐；:90 终值三档参数化扣主办+降档委派人；:140 adapter 重放幂等；:165 引擎自判 failed 零连坐；:190 亡故连坐人免扣入说明；:217 显式 affected_parties 全键校验；:260 助理行次责零机械；:307 双角色主责优先；:349 连坐查询排知情留委派 FK；:383 在野存活委派人照扣；:399 execution_note 合并接口+恢复；:427 裸 record_dossier_execution 不触发连坐（**边界 pin**） | `_close_via_adapter`（:59-64）= `issue_engine.apply_score_extraction` 真实段适配器；断言三面：`decree_cost_events` 行（:39-43）、`factions.satisfaction` state（:53-56）、`get_relation_edge_events(event_kind="连坐")` 关系边（:79/:120-131/:146-162）+ execution_note（:133-134） |
| test_override_breach_costs_564.py（21 全保留，rdd 布景按 §3.1 重投影） | :36 强颁三代价无宦官反应；:56 typed direction 不锁文案；:74 密旨打回零派系扇出；:103 普通打回零反应；:117 密旨重判不扣派系；:141 代价幂等+恢复；:164 强颁/毁约各真实入口独立计费；:184 毁约排除陈旧派系；:199 毁约跳亡故录在野关系；:231 撤关联局势只毁源案卷一次；:269 公共 apply 形状校验先于写；:289 密旨 apply 不猜派；:316 迁移（§3.2）；:371 commit=True 毁约失败重载 state（:384 直调旧动词 → 改径，见末小节）；:391/:407/:426 强颁前置拒收组；:444 commit=False 毁约随外层回滚（:454 已经 `issues.apply_issue_tracker_output` 真实段适配器链，保留）；:461 活跃承诺可毁已结已颁案卷；:513 毁约扣权臣+关联派系一次；:545 批红抉择经颁布路径结算 | 真实入口 = `apply_dossier_promulgation` force、批红收回/承诺挽留坚持撤链（breach_plea）、cancel linked issue（`apply_issue_tracker_output`）→ cost_events/satisfaction/authority/关系边；`db.breach_decree_dossier` 直调点（:174/:192/:214/:384/:525/:526）全部改走上述真实 adapter/入口（末小节） |
| test_commitment_backlash_626.py（13 保留 + 1 删） | :157/:208/:251 AC1 三触发（毁约 verdict/终值 failed/变形暴露）；:307 未逾制不触发；:341 AC2 halfway 持久；:442 AC3 初启/生根不触发；:494/:555/:604 AC3 豁免组；:659 persist 盖章仍触发；:695 **跨恢复双态**；:762 幂等无门表扩张；:958 extractor 事实面 | `trigger_commitment_backlashes`（db.py:13838，消费侧编排→段适配器）→ metrics/DB 事实/恢复。**删 :813-957** `test_ac6_presentation_sentinel_distinct_from_625`（盯生成物哨兵 + avoid_phrases 断言，§3.4 T14） |
| 关联 tracer（同保留） | test_breach_plea_623.py（25/5，:143/:247/:333 毁约陈情三缝）；test_due_review_621.py:271/:311（复核经 adapter 写执行格）；test_impeachment_surge_655.py:59/:95（弹劾潮候选投影）；test_refugee_loop_652.py:115/:136（跨连接耐久） | 各经真实 adapter/结算入口 |

**commit 直调旧动词点名（二审判词类4 附，逐文件）**：

grep 口径：`tests/` 内 `commit=(True|False)` 共 307 处命中，其中绝大多数是段适配器/编排入口自身的合法两态参数（`apply_pending_due_reviews`、`scan_and_write_breach_pleas`、`finalize_persist`、`expire_breach_pleas_on_due`、`write_due_staged_commitment_todos`、`trigger_commitment_backlashes` 等——这些入口留编排层，commit 参数合法，不在点名范围）；点名范围 = 与被内化的 GameDB 案卷块旧动词（`breach_decree_dossier`/`apply_execution_joint_liability`/`_apply_override_costs`）的直调交集。生产签名实证：`breach_decree_dossier`（db.py:16164-16167，公开，`commit: bool = True`）、`apply_execution_joint_liability`（db.py:16319）、`_apply_override_costs`（db.py:16125，私有）。

| 文件:行 | 调用 | 所属函数 | 改径方向 |
|---|---|---|---|
| tests/test_override_breach_costs_564.py:174 | `db.breach_decree_dossier(state, dossier_id, reason="撤回成命")`（默认 commit=True） | :164 强颁/毁约各真实入口独立计费 | 经批红收回真实链或 cancel linked issue 段适配器重打毁约布景 |
| 〃:192 | `db.breach_decree_dossier(state, dossier_id)`（默认 commit=True） | :184 毁约排除陈旧派系 | 同上 |
| 〃:214 | `db.breach_decree_dossier(state, dossier_id)`（默认 commit=True） | :199 毁约跳亡故录在野关系 | 同上 |
| 〃:384 | `db.breach_decree_dossier(state, dossier_id)` | :371 `test_commit_true_breach_reloads_state_when_failure_follows_authority_mutation` | 经真实毁约入口，monkeypatch 失败注入点保留 |
| 〃:525-526 | `db.breach_decree_dossier` ×2（重复撤回幂等） | :513 毁约扣权臣+关联派系一次 | 同上 |
| tests/test_breach_plea_623.py:428 | `db.breach_decree_dossier(state, did, reason="重复", commit=True) is False` | :378 `test_persist_foundation_tiers`（幂等重复撤断言） | 经 `finalize_persist` 坚持撤真实链断幂等 |

零直调实证：`apply_execution_joint_liability` 与 `_apply_override_costs` 在 tests/ 全文零命中。判词点名的 564:444 `test_commit_false_breach_rolls_back_with_later_cancellation_failure` 实读不直调旧动词——:454 经 `issues.apply_issue_tracker_output` 真实段适配器 + 外层 `atomic(db)`，commit=False 语义由真实链承载，**保留不动**。

### 3.4 盯生成物/剥词/措辞管控/成句模板：全扫删除清单（二审重写版）

**删除理由**：对 LLM/玩家可见文本做禁词扫描 = 盯生成物，触 CLAUDE.md 探针铁律总纲 P6（LLM 输出不可篡改）/ P7（代码成句模板违宪）；`presentation_constraints` 由代码管 LLM 措辞 = ADR 0150-D5-b 被 owner 点名的违规形态。原则：**代码只供结构化事实交给 LLM，或仅做合法布局；删除全部生成物扫描、输出剥词、负向措辞控制和代码成句模板，生产根因与测试断言双向删除**。判词明列本项为「断言零变化」原则的例外，**不得借断言零变化保留**。

**全扫口径**：grep 模式 `banned|BANNED|forbidden|blacklist|_strip|avoid_phrases|presentation_constraints|禁词|剥词|replace(|scene_text=` + 固定句式特征，扫 ming_sim/ 下 §1.3 的 66 文件所触及案卷相关模块（supervision、credit_events、due_review、breach_plea、decree_vocabulary、commitment_backlash、urge_lever、covert_levy、covert_progress、issues、decree、execution_pressure、action_materialize、settlement_payload、session、cli_backend、db 案卷块）。上一版只处置 supervision 一族，本版把同构机制全部点名；行号均 HEAD e88cc29c 实读核实（判词点名处行号漂移见各条注）。**九审复扫补强（针对「已触及接缝上的同构固定 scene 模板」漏项）**：对 audience_night.py 与 beat_orchestration.py 两文件整文重扫——grep 模式 `or f"|or "[^"]*[一-鿿]|f"[^"]*[一-鿿]`（or 兜底句/中文 f-string）+ `body=f"|body = f"|body="中文"`（写故事账正文面）+ 测试面固定句等值 pin 反扫（`入殿。|退朝，召对到此|随侍在侧|告退。|留下听着|明发旨意：|召对启。`）。复扫结论：audience_night.py 其余中文 f-string 全部为 AudienceNightError/fail-loud 校验消息（:321/:468/:646-647/:705/:748/:755/:823/:918/:1080/:1293/:1495/:1977/:2403-2623 等，非玩家正文，合法）；:532 `or "近臣"` 为机读 speaker 缺省标签（非正文成句，合法）；:837 开夜兜底句已由 N1 覆盖；新命中仅 :886（随侍固定句，补 P29）；beat_orchestration.py 中文成句全部位于 production_beat_generator（:337-389）函数体内（:352/:369/:379/:385），随 P28 死函数删除，无其它漏项。**十审 CLI 调用侧复扫**：对 ming_sim/cli/terminal.py 整文扫同族模式（入殿/退下/留侍/留下听着/侍立/退朝/召对/告退中文固定句）——命中七处控制台回显固定句：:363（留侍）/:638（入殿+操作提示混合）/:658/:679/:683/:781/:785（退下、传入殿），全部与 P23/P25/P26 同事件（见各 P 项调用侧合并注）；复扫增 :658/:679 两点（判词点名仅 :363/:638/:683/:785）。同文件其余命中均为口令识别正则（:394-404）、UI 操作提示/系统提示（:74/:117/:126/:144/:646/:823/:1049——非叙事成句）、docstring/注释，不属本面。CLI 测试面无 scene 句等值 pin（test_cli_play_turn.py 的 capsys 断言全在密令重试 :423/结算提示 :545/:579 等系统提示；test_close_stay_command_526.py:210-247 只断 TAG_STAY_ATTEND/person_names/在场不变 typed 面，与 P26 保留面同向）→ CLI 侧无新增 T 条目。十一审：七处回显句处置由「纯删除」修正为「删固定副本 + 现有生成 scene 在原打印位按账序投影一次」（ADR 0046:5 玩家可见内容口径；投影点见 §3.4 消费链表 P23-P29 行），计数不变。

**生产机制删除/改造清单（P1-P29 共 29 条，九审补 P23-P29；十审 CLI 同族回显固定句七处并入 P23/P25/P26 调用侧、不另编号；另 S1/N1 两处三审裁定违宪成句删除/改造见下方裁定表——生产合计 31 条）**：

| # | 位置 | 机制 | 处置 |
|---|---|---|---|
| P1 | ming_sim/supervision.py:70-94 | `SUPERVISION_BANNED_PLAYER_TOKENS`（22 词：钝化/钝化度/陋规化/supervision_history/loophole_exposure(s)/consecutive_months/private_goods/same_faction_blind/transformation_tendency/dulling/dull_rate/dullness/denunciation_true/denunciation_false/faction_conflict_intensity/denunciation_quota/faction_denunciation/fork_exposure/veracity/true_denunciation/false_denunciation） | **删词表** |
| P2 | ming_sim/supervision.py:340-344 | `assert_no_banned_tokens`（住在生产模块的测试断言器，生产零调用） | **删除** |
| P3 | ming_sim/credit_events.py:60-71 | `CREDIT_BANNED_PLAYER_TOKENS`（10 词 origin 片段/机读键） | **删词表** |
| P4 | ming_sim/credit_events.py:74-82 | `CREDIT_BANNED_SCAN_SURFACES`（七扫描面清单，供测试扫生成物） | **删除** |
| P5 | ming_sim/credit_events.py:85-92 | `FOUNDATION_BANNED_PLAYER_TOKENS`（根基档/哭谏通道系统词 6 词） | **删词表** |
| P6 | ming_sim/credit_events.py:95-121 | `_family_p4_banned_tokens` 六族并集 + `FAMILY_P4_BANNED_PLAYER_TOKENS`（:121） | **删除**（各分量词表消亡后并集同删） |
| P7 | ming_sim/credit_events.py:124-129 | `assert_no_family_p4_banned_tokens`（七面共用哨兵） | **删除** |
| P8 | ming_sim/commitment_backlash.py:38-51 | `BACKLASH_BANNED_PLAYER_TOKENS`（12 词，含「反噬平息/坐大/涌现」bar 用语） | **删词表** |
| P9 | ming_sim/commitment_backlash.py:76-80 | `assert_no_backlash_banned_tokens`（判词 :38-81 含此，实读 assert 体 :76-80） | **删除** |
| P10 | ming_sim/commitment_backlash.py:146-155（宿主函数 `build_backlash_narrative_features` :99-157；判词 :99-155 基本命中） | `presentation_constraints.avoid_phrases`（["反噬平息","反噬坐大"]）+ `banned_system_tokens`（5 系统词）——代码管 LLM 措辞，ADR 0150-D5-b 点名形态 | **删 `presentation_constraints` 键**；函数余部（issue_id/commitment_ref/title/source_kind/metrics_delta 等结构化事实供给）保留 |
| P11 | ming_sim/decree_vocabulary.py:209-227 | `DEFORMATION_BANNED_PLAYER_TOKENS`（:209-213，11 词）+ `DEFORMATION_STRIP_PLAYER_TOKENS`（:215-227，生产静默剥离子集 + 三条自 pin assert） | **删词表 + 删剥离子集** |
| P12 | ming_sim/decree_vocabulary.py:231-235 | `URGE_TRUTH_BANNED_PLAYER_TOKENS`（10 词真伪底/失真引擎词） | **删词表** |
| P13 | ming_sim/decree_vocabulary.py:236-243 + :254-280（判词 :236-269，实读函数 `terminal_report_facade` 至 :280） | `_TERMINAL_REPORT_FACADE_BAND`/`_TERMINAL_REPORT_FACADE_MEMORIAL` 固定终值奏报文本（「已竣/将结」「所委各节均已依限办结，并无违误。」等） | **成句模板改结构化事实供给**（band/终值事实交 LLM 成文；变形复用末次陈词逻辑 :269-279 随门面函数一并处置） |
| P14 | ming_sim/due_review.py:43-55（import :24/:36 随清） | `_BANNED_PLAYER_TOKENS` 运行时静默剥离集（`AWAITING_DECISION`/`<<DECISION>>` 等 + DEFORMATION_STRIP + URGE_TRUTH + SUPERVISION 非汉字分量并集，:52-55 自 pin assert） | **删剥词集** |
| P15 | ming_sim/due_review.py:253-257（判词 :253-258 微漂移） | `_strip_banned` 运行时剥词器（replace 循环）；消费点 :282/:298 同删 | **删剥词** |
| P16 | ming_sim/due_review.py:260-282 | `_gap_and_statement` 固定拼句：「承办人陈词：…」「『…』一侧已见实账落地」等三分支果句模板 | **成句模板改结构化事实供给**（effects/reports/criterion 事实交 LLM） |
| P17 | ming_sim/due_review.py:296-300（宿主 `project_due_review_scene` :285 起；判词 :253-300 覆盖） | `phase_hint`（中途复命/到期复命）+ `origin_bit`（昔有「…」之约，今期已至。）固定拼接 scene_text | **成句模板改结构化事实供给**；:307-308 covert 暴露置空分支随场景重定性 |
| P18 | ming_sim/breach_plea.py:456-460（宿主 `project_breach_plea_scene` :445-482；判词 :445-478 未覆盖返回 dict 尾 :479-482） | 固定「主办哭谏：前诺『…』遭…，臣的信心一半是皇爷给的，求皇上收回成命。」默认 display 句式 | **删固定句**（display 由 meta 事实/LLM 供） |
| P19 | ming_sim/breach_plea.py:461-469 | `replace(token, "")` 剥词循环（DEFORMATION_STRIP + FOUNDATION_BANNED + `AWAITING_DECISION`/`<<DECISION>>`） | **删剥词** |
| P20 | ming_sim/urge_lever.py:28-32（判词未点名，全扫命中） | `_URGE_SCENE_BANNED = URGE_TRUTH_BANNED_PLAYER_TOKENS` 别名 + 编译剥词正则 `_URGE_SCENE_BANNED_RE` | **删除**（随 P12 词表消亡） |
| P21 | ming_sim/urge_lever.py:672-674（判词未点名，全扫命中） | `_strip_urge_banned` 剥词（正则 sub + 剜标点）；消费点 :690-691/:695/:701 同删 | **删剥词** |
| P22 | ming_sim/urge_lever.py:687-704（判词未点名，全扫命中） | `project_urge_audience_scene` 固定句式「操之过急之谏：…请陛下宽之。」/「求宽限：…同一话术，真伪待圣鉴。」 | **成句模板改结构化事实供给**（kind/criterion/origin/host 事实交 LLM） |
| P23 | ming_sim/audience_night.py:946（九审判词点名；宿主入殿账函数 :923-957，:941-942 注释自证非 scaffold 旧路径仍走固定句） | `body or f"{method}{name}入殿。"` 固定入殿句写故事账 | **成句模板改结构化事实供给**：删固定句；tags=[TAG_ENTER, method]/person_names/时地结构化事实保留，body 先落空垫位（empty_scaffold 先例 :943-944）。**真实路由（十审实读纠偏）**：`discover_open_enter_tasks`（beat_orchestration.py:498-550，:529-541 找回本 chat_turn 的 TAG_ENTER 账并从账 tags 复原真实 summon_method，:543-549 assemble BEAT_ENTER）→ `start_open_enter`（:608-639 原子 claim + submit）→ LLM 成文 → `persist_chat_turn_scene`（:553-557）回填同一条账；失败 fail-loud 不建 fallback（ADR 0046：入殿 scene 内容特征化长出、非模板句）。CLI 入殿回显固定句（terminal.py:638/:683/:785）= 同事件调用侧副本，随本项合并处置、不另编号；十一审：删副本同时在原打印位投影已生成 enter scene（:729 join 结果/账读面，见消费链表）；**十二审（escalate，owner 裁量「允许」）**：首轮控制轮（dismiss/court_break/summon/stay，无大臣回话）在控制输入已知后补跑既有 attach/start_open_enter 链，入殿 scene 于首次控制输入后的下一次玩家交互前汇合并可见（ADR 0046:5）；不得恢复固定成句、不得新建 generator/seam/fallback/beat kind；**十三审生命周期闭合**：attach 所建 generating 无回话轮（audience_night.py:2659）在 open/enter 汇合+persist 后复用 `complete_rescript_summon_scaffold_turn` consumed 写点（db.py:9155-9173）终结为 'consumed'，失败沿 abandon+fail，终结先于 stay/summon/dismiss 返回与 court_break 进屏障（:978-1002）——不收口则屏障永久等待 |
| P24 | ming_sim/audience_night.py:1546-1548（九审判词点名 :1547） | `close_body or ("王承恩代宣退朝，召对到此。" if auto else "退朝，召对到此。")` 固定收朝句写收夜 scene | **成句模板改结构化事实供给**：删固定句；TAG_CLOSE_NIGHT/TAG_AUTO_CLOSE typed tags 与时地保留。**真实路由（十审实读纠偏）**：`start_close`（beat_orchestration.py:680-702 assemble BEAT_CLOSE，entry_id=0 只产正文）→ registry join → close_night finalize 落账（:1545-1557 既有 TAG_CLOSE_NIGHT 幂等守门保留）；无 generator 留空、失败 fail-loud，不建 fallback |
| P25 | ming_sim/audience_night.py:2065（九审判词点名） | `body or f"帝令{name}退下，{name}告退。"` 固定退下句写玩家 scene | **成句模板改结构化事实供给**：删固定句；TAG_EXIT/person_names 保留，body 先落空。**真实路由（十审实读纠偏）**：调用侧经 `start_exit`（beat_orchestration.py:641-666 assemble BEAT_EXIT person/时地）→ LLM 成文回填该账（CLI 退下口令链 terminal.py:256 docstring 自证「垫位告退 + 唯一 scene registry 生成 exit 旁白」）；:2059-2060 兼容形参注释随真实接线更新；失败 fail-loud（ADR 0046 同法源）。CLI 退下回显固定句（terminal.py:658/:679/:683/:781/:785）= 同事件调用侧副本，随本项合并处置、不另编号；十一审：删副本同时在原打印位投影已生成 exit scene（:321 join 结果/persist 后账读面，见消费链表） |
| P26 | ming_sim/audience_night.py:2100（九审判词点名） | `body or f"帝令{name}留下听着，{name}殿侧侍立。"` 固定留侍句写玩家 scene | **删固定句根因（十审纠偏）**：当前无 BEAT_STAY/registry 路由（beat kinds 仅 open/enter/exit/close，beat_orchestration.py:46-49）→ 依复杂度法「删除优先于新增平行机制」：删固定句，留 TAG_STAY_ATTEND/person_names + 空 body（:2083 自证不进 _presence_delta、不制造进出事件），**不新增平行生成机制**；CLI 留侍回显固定句（terminal.py:363，同一 stay_attend 事件 :361-362 落账后的控制台回显）随本项调用侧合并删除、不另编号；十一审明文：:363 删后留侍事件 CLI 不再成句（无投影，有意处置） |
| P27 | ming_sim/audience_night.py:1533（九审判词点名 :1534，实读定码在 :1533） | `body=f"明发旨意：{...}"` 固定故事账前缀拼旨意原文 | **同缝定性处置**：删固定前缀；TAG_MINGFA + mingfa_publication_tag(directive_id) typed tags 保留（机读资格不丢）；旨意文本 `_pd['text']` 为既成文本直落，不再加码前缀（ADR 0035：故事账正文不以模板压扁） |
| P28 | ming_sim/beat_orchestration.py:337-389（九审判词点名） | `production_beat_generator` 完整固定开场/入殿/退下/收夜模板（:352/:369/:379/:385）；生产调用 grep 为零（仅测试直调/旁路哨兵与 :299 注释提及） | **删除根因**（死函数，删优于保留死兼容机制）；真实生产路径走 create_llm_beat_generator 同一 seam（:328-332），`run_beat_generator` 对空白 fail-loud 不变；:299 注释随清 |
| P29 | ming_sim/audience_night.py:886（九审复扫自增，判词未点名） | `f"{name}随侍在侧。"` 固定随侍句写故事账（非 scaffold 旧路径；:884-885 注释自证 registry 垫位路径已禁此固定句） | **删固定句根因（十审纠偏）**：standing roster 仅随 open_night 落账、无 LLM 路由 → 删固定句，仅留空 standing-roster 账（tags=[TAG_ENTER, TAG_STANDING_ROSTER]/person_names 保留），**不冒称进入 LLM、不新增生成机制** |

**疑似项逐项裁定（三审，法源 P6/P7 + ADR 0150-D5-b；裁定标准：字段进 LLM context=合法结构化事实，直接进玩家文本=违宪）**：

| # | 位置 | 机制 | 裁定（实读依据） |
|---|---|---|---|
| S1 | ming_sim/decree.py:2846-2847 | `narrative + "\n\n有司奏：所拟之事有窒碍未行者，已录档待酌。"` 固定句拼进 simulator 产物 narrative 并持久化进 turn_report | **违宪成句（P7）→ 删除**。实读：:2842-2845 注释自证「持久化进 turn_report（web/history/重读都见）」= 代码成句直进玩家可见面。替代路径四审定案（写死，不留备选）见下方消费链闭合表 S1 行 |
| S2 | ming_sim/breach_plea.py:602、ming_sim/issues.py:5958、ming_sim/issues.py:9563 | `advance_issue` narrative 默认固定文案落库（「办到一半撤诺，沉没投入化为负累」/「陛下欲罢，然此事非诏可消。」/「局势自有其势，本月按其本然推移。」）；`narrative` 参数链实读：db.py:19843 advance_issue 签名 :19852 → 落 issue_advances 行 | **合法保留**。实读消费链：issue_advances.narrative 唯一生产出口 = `issue_to_payload`（issues.py:1201-1207「上月推进.narrative」）→ 唯一消费者 simulation.py:686-696（simulator payload 组装）= 进 LLM context 的事实注记，不直接进玩家文本。三处默认值随之定性为结构化事实供给 |
| S3 | ming_sim/covert_levy.py:219 | `criterion_text="暗渠摊派揭破待裁", origin_context="案卷实况与奏报有异"` 固定短语进 next_audience_todo | **合法保留**。实读流向：todo → `project_due_review_scene`（due_review.py:302-308：covert_levy_exposure 场景 `scene_text=""` 置空，注释 :305-306 自证「由既有召对 LLM 以事实渲染」）→ 结构化字段（:331-332 origin_context/criterion_text）进召对 LLM context，决策消费口 action_materialize.py:2836。短标签事实进 LLM context，不进玩家文本 |
| S4 | ming_sim/covert_progress.py:170-178（`decide_secret_order_settlement` :153）、:327（`derive_monthly_covert_world_effects` :310）、:518-520（`apply_monthly_covert_actual_progress` :467） | note/reason 固定格式串（「表报有之、不翻实账」/「密令实办（态）：标题」/「机械实进度：…」） | **合法保留**。实读流向：:580 docstring 自证「机面 note 含 Σ 但不写入 result（P7）」——`settle_due_secret_orders`（:572-637）机面 note 只进 results 返回（:630），玩家正文由 :616 `player_facing_secret_order_close_text` 复用既有 LLM 产物（:191-205「不造模板」自证）；:327 reason 喂既有 applier（:318-321 注释自证）落事实行进 LLM context；:520 note 落 dossier_actual_progress 机读列。均为机读事实注记，不进玩家文本 |
| S5 | ming_sim/cli_backend.py:1078-1093 | `_strip_agent_narration` 剥自治 agent 输出开头英文 narration 行 | **out-of-scope**。实读：消费点 cli_backend.py:3593 属 CLI 自治 agent 桥接的展示兜底，与案卷 store 触及面无涉；66 文件中唯一 import cli_backend 的 test_session_cli_fallback.py 只测 `_cli_backend_fallback_actions`（:52 起），不触该函数。本票不处置；CLI 通道 P6 追问另票 |
| N1 | ming_sim/audience_night.py:837（三审实读新发现） | `open_body = body or f"{location}·{time_of_day}，召对启。"` 固定开夜兜底句，:850 拼接后落 audience_nights 开夜账（玩家可见） | **违宪成句兜底（P7）→ 删除/改造**。实读同文件已有 P7 先例：:834-835「垫位路径只许空 body；不叠复命场面、不用固定开夜句」、:1909「机器事实只在 tags；玩家可见句由既有 LLM 特征路径生成（P7）」。改造同款：无 body 时留空，location/time_of_day 作结构化事实交开夜 open-beat LLM（:839-840 注释自证 body 含 LLM open-beat） |

**消费链闭合（四审定稿、五审修订、九审补扫：逐项点名结构化事实进入哪个既有 LLM 入口；seam/调用顺序/失败语义写死，不留备选）**：

| 删除项 | 删除内容 | 消费链定案（实读 file:line） |
|---|---|---|
| S1（decree.py:2846-2847） | turn_report 固定提示句 | **五审重定（如实列新件，不冒称兼容）**。(a) 兼容性排查实读结论：agents.py 全扫 19 个 `create_*_agent`，无一输入面能吃拒收事实包——上轮主张的 arrival attendant seam 实读不兼容：`run_arrival_attendant_message`（decree.py:186-217）只重建 year/period + arrivals{name,location,status}（:197-209），`create_arrival_attendant_agent` instructions 限定抵京候旨名单（agents.py:364-378）；mindreading（agents.py:381）是召对读心，非 turn_report 附言位 → 走 (b)。**新增调用三问结论（判词已过，照录）**：真实失败 = P7 固定句与 ADR 0008 决定 5 法定提示冲突（固定句违宪、提示法定，不得回退固定句）；owner = turn_report.attendant_message 递话声部（槽位既有、归属明确）；仅删根因会丢 ADR 0008 提示 → LLM 替代必要。① 事实供给：decree.py 新增模块私有读面（:2654 `_has_durable_player_visible_rejection` 同查询的 list 版）——rejection_reports 本 turn、source∈{player_decree,hitl_decision}、`resimulation_invalidated=0` 的 section/category/reason 聚合，纯结构化零成句；② LLM 入口（**新件如实列**）：并列新增 `create_settlement_attendant_agent(llm_config)`（agents.py，与 :364-378 同构：王承恩递话声部、one-shot、`add_history_to_context=False`、`markdown=False`；instructions 改「用户给出本回合有司录档待酌的结构化拒收事实，据此向皇爷低声递话」）+ `run_settlement_attendant_message(llm_config, *, year, period, rejections, agent=None)`（decree.py，与 :186-217 同构，含 provider 异常译 LLMUnavailable 适配缝 :219-220 同款）——**不动抵京专用对，旧契约不破**；③ 调用顺序：settle_with_delta 内 applier flush 拒收落库完成（:2469 注释自证 flush 进 rejection_reports）→ :2846 判定点读事实包 → 新 runner 渲染附言 → 写入 `attendant_message` 槽 → :2861 `db.save_turn_report(...)` 同笔落库——判决落库后、turn_report 组装前；不经 simulator（phase1 :1384-1418 跑时拒收尚未发生，时序排除）；arrival companion 稿已占槽时（:1374-1395）附言作同槽第二段换行并列（两段均 LLM 产物，代码只做布局拼接=合法布局，companion 稿零删改 P6）；④ 失败语义（五审改）：**agent 失败/空文 = fail-loud abort**——abort 点 = 新 runner 调用处（settle_with_delta 写序列内、:2861 save_turn_report 前，空文照 :194 同款 LLMContractError 模式）；settle 整体在 atomic_and_reload 内 → 事务回滚、turn 不推进、月档不提交；重试入口 = `resolve_settling_recovery`（decree.py:1580，ADR 0008 S7「直入 apply」：ready context 已带 extracted，不重跑 simulator/extractor，直调 settle_with_delta 后半段，:1591-1598 docstring 自证）；「tlog 后继续推进」废除（违 ADR 0008 决定 5 与失败诚实）；重推演时旧拒收行 invalidated（error_pack.py:247），附言随重结算重新渲染。⑤ 测试处方：主干 = 造本回合 player/HITL rejection、无抵京 companion，桩拒收 agent 只记录收到的 section/category/reason；结算成功后**不读不比较 attendant_message 文本**，断 `db.list_monthly_archives()`（db.py:11190-11218）该 turn 的 typed `has_attendant is True` 且 turn 已推进；失败分支 = 桩 agent 抛错 → turn 未推进、月档未提交、resolve_context 仍可重试，**不得允许成功无提示**；companion 并列场景 = 机械测试只断两条 agent 路由均被调用 + 单一 has_attendant 槽存在，布局拼接由源码审查承接 |
| P10（commitment_backlash.py:146-155） | `presentation_constraints` 键 | **有现成口**：`build_backlash_narrative_features` 余部事实包 → simulation.py:861 / :1365 `commitment_backlash_facts` 进 simulator payload（626:916-921 测试自证该键入 payload） |
| P13（decree_vocabulary.py:236-243/:254-280） | 固定终值奏报 band/memorial | **方案重定（五审）：四审「待终奏机读标记 + 新建必覆条目」改为纯派生**——判词实读确认四审仍留一处发明：②「落待终奏机读标记」需新写字段/状态，违反最小新建；且月报链已有可派生谓词，不必落标记。**派生方案**：终奏缺口候选 = decree_dossiers 行 **status='closed'** ∧ closed_turn>0 ∧ **execution_outcome ∈ {degraded, transformed}**（status/closed_turn/execution_outcome 列 schema db.py:1513/:1515 实读）∧ 无 is_terminal 奏报行（dossier_progress 行判定，同表现有查询模式），纯读面派生、零新写。**结案判据修正（八审）**：「closed_turn>0」单独不等于已结案——`record_dossier_execution`（db.py:15580-15614）对任何 outcome≠'executing' 都写 closed_turn=turn（:15610），是否结案由独立参数 close 决定（仅 close=True 才调 close_decree_dossier，:15614-15615）；closed_turn>0 且 status='executing' 是合法行（既有布景 tests/test_covert_levy_651.py:149-154：outcome='transformed'、close=False，随后继续读 fork）→ 谓词必含 status='closed'。**谓词收窄（六审）**：原稿「execution_outcome 非空」会把 fulfilled/failed 结案也纳入月度终奏——越界；被删 terminal_report_facade 原本只在 degraded/transformed 分支被调（notary 实读确认：全仓仅 issues.py:8204-8214 / due_review.py:537-547 两调用点，:8204/:537 均以 `outcome in {"degraded","transformed"}` 守门），扩张违反 spec Out of Scope「案卷新语义/新行为不在本票」→ 收窄为仅 degraded/transformed。**明文边界：fulfilled/failed 结案不因本票新增终奏；若要给它们加终奏须另获产品授权，不得夹带。****真链实读**（替换四审错误引用）：候选读面 = db.py:12751-12779 `list_monthly_dossier_progress_nudges`（现仅密令长差 JOIN secret_orders + tags∩{护行，稽核}，扩 union 一类终奏缺口条目谓词=上述派生条件，普通+密令同谓词、**不设 secret_order_id 排除**）；**候选域补齐（七审）**：原稿「secret_order_id IS NULL」会把已结案 degraded/transformed **密令**案卷挤出候选——原 terminal_report_facade 两调用点（issues.py:8204-8214 / due_review.py:537-547）只按 outcome 守门、无密令排除；既有密令长差月报支路（db.py:12753-12766）又只收 status∈{promulgated,executing} + secret_order active + deadline_span≥2 + tags∩{护行，稽核}，已结案密令案卷两边都进不去 → 误删原行为域，故移除密令排除（ADR 0073 依据：所有带执行判定面的案卷均可挂奏报轨，不以密令/普通划分资格）。**不重叠论证（八审重写）**：终奏缺口支路要求 status='closed'，长差密令支路要求 status∈{promulgated,executing}——status 值域互斥（结案≠在办），两支路真正不重叠、不重复成奏；写口/admission = db.py:12781-12824（:12792-12811 fail-loud 守门，缺必覆条目即 raise）；extractor 注入点 = simulation.py:1342-1346（personnel_secret 档房 `slim["monthly_dossier_reports"]`，:1344-1345 authorized secret rail）；settle 触发点 = decree.py:2720-2722（结算段调 extractor 链）。**落点**：① 删 terminal_report_facade 固定文案（band 映射 :236-243、固定 memorial :240-243/:266-267、「办结」fallback）——此点同四审不变；② 两同步写调用点（issues.py:8204-8214、due_review.py:537-547）改为只落执行格终值，**不落任何机读标记**（删四审②后半）；③ 候选装配扩 union（上引读面），终奏缺口条目（普通+密令同谓词）与密令长差同槽进月报 prompt，输入面只喂承办人视角结构化事实（dossier_id/criterion/末次非终值陈词引用/月度进展带；**变形案不喂判官真值与执行格 outcome**——0073 奏报轨假象/变形两轨分叉由输入面事实筛选承载），LLM 产终奏 band+memorial，经既有写口落 is_terminal=True 行（turn 落结案 turn=closed_turn，保 0073 时序契约）；④ transformed 复用末次陈词逻辑（:269-279）改为输入面事实引用（喂回 extractor 作假象载体），不再由代码直接落库；⑤ 失败语义：extractor 缺终奏必覆条目 → admission fail-loud（:12792-12811 同款）→ settle abort 整体回滚 → `resolve_settling_recovery`（decree.py:1580）重试，不落固定兜底。附带点：due_review.py:548-553 中段奏报「在办」固定词 + 机读 note 入 memorial_text 属同链同处置（随本方案一并改由 LLM 链成文或删）。**测试处方（五审）**：走真实 settle/extractor 主干——degraded/transformed 结案 settle 后断 typed `is_terminal=True` 奏报行存在、turn=结案 turn、origin/routing 正确（不读不比较 memorial 文本）；**候选谓词正反例（六审加普通正例/反例、七审加密令正例）**：degraded/transformed 普通案卷结案且缺终奏 → 断其入候选槽（正例）；degraded/transformed **密令**案卷结案且缺终奏 → 断其入候选槽（密令正例，守原行为域不误删）；fulfilled/failed 结案（普通与密令同）→ 断其**不入候选、不新增终奏**（反例，守 spec Out of Scope 边界）；degraded/transformed + close=False + status='executing' 的普通与密令案卷 → 断**不进入终奏缺口候选**（八审反例；满足长差条件的密令只进既有长差支路一次，不重复）；extractor 缺必覆条目时断 settle fail-loud 回滚、resolve_context 可重试（不允许「成功但无终奏」）；桩 extractor 测试只查允许/禁止结构化键（有 dossier_id/criterion/末次陈词引用，无判官真值/执行格 outcome 键），不锁措辞 |
| P16/P17（due_review.py:260-282/:296-300） | 「承办人陈词」拼句 + phase_hint/origin_bit 固定拼接 | **按真实 seam 重指（四审纠错）**：audience_night.py:841-850 只是收集拼接 scene_text（非 LLM 输入），该收集拼接块**整删**。真实结构化入口 = `assemble_beat_inputs`（beat_orchestration.py:177-257）：BEAT_OPEN 时 :234-240 经 `current_audience_scene` 取场景 dict → BeatInputs.audience_scenes（:255）→ `create_llm_beat_generator` 的 materials["**待呈御前的结构化场面事实**"]（:328-332）→ open-beat LLM `agent.run`（:332）。接线方案：① `current_audience_scene`（due_review.py:370-375）筛选扩容——现仅放 covert_levy_exposure/shortfall_reopened，改为同时放普通 due_review 与 breach_plea 场景（`list_due_review_scenes` :349-365 已有结构化 dict :324-346），并汇合 urge 场景（`list_urge_audience_scenes` urge_lever.py:719-728），audience_scenes 槽由单场景 tuple 扩为多场景；② scene dict 只留结构化字段（origin/criterion/mid_stage/branch/dossier_id/army_pay_fact/decision 等），代码拼的 scene_text/gap_text/statement_text 键删除；③ 调用顺序 = 开夜 `generate_open_beat_body`（beat_orchestration.py:393-410）→ assemble → LLM 成文开夜正文（复命/哭谏/谏宽限场面由 LLM 从事实长出）；④ **测试处方（五审）** = 桩 beat_generator 只断 BeatInputs.audience_scenes 的 typed/JSON 事实键与路由（dossier_id/criterion_text 等键存在、无 pending 时槽空、due_review/breach_plea/urge 三路汇合进同一多场景槽）；开夜正文通用生成 transport（materials 槽 → agent.run，beat_orchestration.py:328-332）引用既有 498 家族测试承接，本项不复制正文级生成测试；禁止比较生成文本、禁词扫描、固定句缺席断言、措辞锁 |
| P18（breach_plea.py:456-460） | 固定「主办哭谏…」句式 | **同 P16 真实 seam**：plea meta 事实（breach_kind/label/absorbed/title，`decode_plea_meta` breach_plea.py:448-455 既有结构化）经 `list_due_review_scenes`（due_review.py:365）→ `current_audience_scene` 扩容 → BeatInputs.audience_scenes → open-beat LLM（beat_orchestration.py:330-332）；display/scene_text 键删除；**测试处方（五审）**同 P16/P17：只断 audience_scenes 内 plea meta 事实键与路由，正文 transport 由 498 家族承接，不复制、不锁措辞 |
| P22（urge_lever.py:687-704） | 「操之过急之谏/求宽限」固定句式 | **同 P16 真实 seam**：urge 事实（kind/criterion/origin/host，project_urge_audience_scene 返回 dict 结构化部保留）经 `list_urge_audience_scenes`（urge_lever.py:719-728）汇入 `current_audience_scene` → BeatInputs.audience_scenes → open-beat LLM（beat_orchestration.py:330-332）；代码 scene_text 键删除；**测试处方（五审）**同 P16/P17：只断 audience_scenes 内 urge 事实键与路由，正文 transport 由 498 家族承接，不复制、不锁措辞 |
| N1（audience_night.py:837，三审裁定删除/改造） | 固定开夜兜底句 | **有现成口（四审坐实）**：开夜正文的真实生成口即 `generate_open_beat_body`（beat_orchestration.py:393-410）→ open-beat LLM（:286-334）；无 body 时留空（:834-835 垫位先例），location/time_of_day 已由 assemble_beat_inputs 作结构化材料（:244-245 时辰/地点键、:326-327 当期年月）进 LLM，不需代码成句。**测试处方（五审）**：删除「固定句存在/缺席」机械断言；以源码审查（audience_night.py:837 兜底句已删）+ 既有 empty scaffold 结构状态测试（audience_night.py:833-835 无 body 时留空垫位）承接，不断言任何文本 |
| P23/P24/P25（入殿/收朝/退下固定句）+ P26/P29（留侍/随侍）+ P27（明发前缀）+ P28（死函数） | 同族固定 scene 句 + 前缀 + 死函数模板族 | **按真实生命周期分写（十审纠偏，废九审统一口径——BeatInputs 只有 open/enter/exit/close 四种 beat，beat_orchestration.py:46-49）**：P23 入殿 = 空垫位账（typed tags/person_names/时地保留）→ `discover_open_enter_tasks`（:498-550，:535-541 从账 tags 复原真实 summon_method）→ `start_open_enter`（:608-639）→ LLM 成文 → `persist_chat_turn_scene`（:553-557）回填同一条账；P24 收朝 = `start_close`（:680-702，entry_id=0 只产正文）→ registry join → close_night finalize 落账；P25 退下 = typed TAG_EXIT 空账 → 调用侧 `start_exit`（:641-666）→ LLM 成文回填。P26 留侍 / P29 随侍：**无 registry/LLM 路由**（留侍无 BEAT_STAY；standing roster 仅随 open_night 落账）→ 删固定句根因、留 typed tags/person_names + 空 body，不新增平行生成机制、不冒称进入 LLM（复杂度法：删除优先于新增）。P27 明发前缀删除后旨意原文直落（既成文本，无新增成文需求）。P28 死函数（生产调用 grep 为零）纯删除、无消费链待闭合。**CLI 处置（十一审纠偏：删固定副本 + 现有生成 scene 可见投影）**：ADR 0046:5 定 scene 与大臣回话同属本轮玩家可见内容、整轮汇合后呈现——纯删除会让既有 LLM scene 只落故事账、不向 CLI 玩家呈现。七处固定回显句删除，同时在原打印位把已生成 scene 按账序呈现一次（不新增 LLM 路由、固定兜底句、文本扫描）：open/enter = terminal.py:729 `join_chat_turn_scene` 的 scene_generated 结果对象（与 minister reply 同事务 persist，:731-735）→ :768 打印 answer 前按 list_ledger canonical 序（COALESCE(order_key, seq), id；audience_night.py:362-369）呈现；exit = :321 `join_chat_turn_scene` 的 generated 结果对象（:321-323 persist 后）→ :658 dismiss 打印位呈现（:683/:785 同族打印位同法；:781 tool dismiss 由 session.chat 单缝落账，:780 注释自证，投影经 persist 后 list_ledger 账序读面取 TAG_EXIT scene）；close = court_break 收夜成功（:665-674 close_fn/auto_close_open_night → start_close → close_night finalize 落 TAG_CLOSE_NIGHT 账，audience_night.py:1545-1555）→ :679 打印位经账读面取 close scene 呈现。P26 留侍/P29 随侍维持现案：只留 typed tags/person_names + 空 body，不新建生成机制；:363 固定句删后留侍事件 CLI 不再成句（无投影，有意处置，明文）。**首轮控制轮触发域扩展（十二审 escalate，owner 裁量「允许」——「不新增 LLM 路由」禁令仅禁新 generator/seam/fallback）**：CLI 首轮控制轮（dismiss/court_break/summon/stay，无大臣回话）在控制输入已知后补跑**既有** attach/start_open_enter 链（terminal.py:703-712 同款），与 exit/close 汇合投影；施工要求 = 入殿 scene 在首次控制输入后的下一次玩家交互前已汇合并可见（ADR 0046:5）；不得恢复固定成句、不得新建 generator/seam/fallback/beat kind。**生命周期闭合（十三审）**：attach 建的是 generating 无大臣回话轮（audience_night.py:2646-2730，:2659 docstring 自证），收夜屏障 `wait_in_flight_clear`（:978-1002）按 `list_in_flight_chat_turns`（:960-975：generating 或无 minister_message 的 active 轮=在飞，不再靠 timeout 放行）——控制轮不收口则 court_break 进屏障永久等待（owner 十二审只授权扩展触发域、不授权遗留永驻在飞轮）→ open/enter（及相应 exit）汇合+persist 后，复用既有 `complete_rescript_summon_scaffold_turn` consumed 终态写点（db.py:9155-9173「非在飞终态唯一写点」，守门谓词 status='generating' ∧ user_message_id IS NULL 恰合首轮控制轮形状）把控制轮终结为既有 'consumed' 态；失败沿既有 `abandon_chat_turn_scene`（session.py:1534-1536 registry drain 不落库）+ `fail_chat_turn`（db.py:9423 起，带回滚）；终结必须发生在 stay 继续、summon/dismiss 返回、court_break 进入 close 屏障之前；不新建 generator/registry/fallback/beat kind 或平行生命周期机制。**retry 轮覆盖（十二审 notary 核对补）**：terminal.py:497-515 中断重试成功路 :497 start_chat_turn_scene → :501 join → :503-505 persist 后 :515 只打印 answer → 同处方投影（:501 join 结果于 :515 打印位前按 canonical 序呈现）。失败语义：各 beat 链沿 `run_beat_generator`（:260）空白 fail-loud，不建新 fallback。**测试处方（十一审，四轮次各一条形状）**：open/enter = 桩 generator 产 scene 后断 :729 join 结果/账读面含对应 (entry_id, body) 且 CLI 输出路径收到该 scene 事件标记（不比较正文）；exit = 断 :321 join 结果含 TAG_EXIT 账 entry_id 且 dismiss 打印位输出来自该 join 结果/账读面；close = 断收夜后 TAG_CLOSE_NIGHT 账存在且 :679 打印位输出来自该账读面；留侍 = 断 typed TAG_STAY_ATTEND 账 + 空 body 且 CLI 不成句（无投影，有意）。全部只断 typed 路由/槽位/事件标记，禁止等值锁固定句、比较生成文本（全节禁令明文适用）。**测试处方增补（十二审立、十三审改参数化）**：参数化真实 CLI 主干覆盖 dismiss/court_break/summon/stay 四种首轮控制输入，逐案断：既有 start_open_enter 恰调用一次、TAG_ENTER typed 账存在、scene 事件进入 CLI 投影、控制处理后 `list_in_flight_chat_turns`（audience_night.py:960-975）为空（不比较正文）；retry 轮（terminal.py:497-515）同形断 :501 join 结果进 CLI 输出路径 |

**测试禁令（五审明文，本表全节适用）**：本节所有 LLM 替代路径（S1/P13/P16/P17/P18/P22/N1 及挂 498 家族的生成链）的测试**一律禁止**：① 比较桩或真实 provider 的输出文本；② 禁词/措辞扫描；③ 固定句存在或缺席的机械断言；④ 文本条数或措辞锁。**允许的断言面** = typed/JSON 结构化键（允许键存在、禁止键缺席）、路由与槽位归属、fail-loud/回滚/重试状态、行存在性与机读字段值（is_terminal/turn/origin/has_attendant 等）。

**核实后保留（同形但非违规，点名免误删）**：

| 位置 | 机制 | 保留理由 |
|---|---|---|
| ming_sim/settlement_payload.py:433-441 | `_strip_player_internal_fields` 递归删结构键（item/report_section/report_category） | 结构化事实供给的字段裁剪（合法布局），不改措辞 |
| ming_sim/db.py:9867-9876 | `_BANNED_STORY_FIELDS` 背书项故事字段拒收 | 写界结构校验（拒收非篡改） |
| ming_sim/action_materialize.py:2458-2460、ming_sim/db.py:12319-12321 | payload 禁携带 owner/assignee 字段拒收 | 同上 |
| ming_sim/supervision.py:96-117 | `DENUNCIATION/PRESENCE/EXPOSURE_ALLOWED_COLS` + `FORBIDDEN_DULLING_COL_FRAGMENTS` | schema 列白名单守门（PRAGMA 面），非文本扫描；随 §4 迁 store `ensure_schema` 契约 |
| ming_sim/decree.py:1819/:1823（前缀常量 import :111-112） | `DECISION_NARRATIVE_PREFIX`/`CHEAT_NARRATIVE_PREFIX` 拼接 | HITL 输入侧标注（喂 extractor 的指令通道），非输出措辞管控 |
| ming_sim/session.py:659/:2134 | `_strip_secret_amendment_prefix` | 玩家输入前缀解析（输入侧），非 LLM 输出篡改 |
| ming_sim/execution_pressure.py:630-633 | `\t`/`\n` 等 replace 转义 | TSV 序列化转义，与文本政策无关 |
| tests/test_execution_joint_liability_565.py:136-137 | execution_note 不露 strong/weak 枚举的内联负断言 | 固定系统词泄漏守门，非词表扫描机制（前版已定性，维持） |

**测试删除清单（T1-T22 共 22 条，逐函数/逐块；十审 CLI 面无新增——无 scene 句等值 pin，见 §3.4 全扫口径十审段）**：

| # | 位置 | 函数/内容 | 处置 |
|---|---|---|---|
| T1 | tests/test_supervision_625.py:578-635 | `test_ac5_banned_tokens_absent_from_named_surfaces` 整函数（:601-635 对 scene_text 三面/memorial_text/settle narrative/turn_report/knowledge_items 五面禁词扫描 + 词表自 pin）；import :49/:52 随删 | **整函数删除** |
| T2 | tests/test_faction_denunciation_627.py:494-610 | `test_ac5_zero_template_banned_tokens_exposure_and_622` 整函数（:527 扫 memorial_text、:565 扫 knowledge_items、:572 词表自 pin）；docstring :11、import :32-33 随删；:577-580 `DENUNCIATION_ALLOWED_COLS` PRAGMA 夹带随函数删除后由 store `ensure_schema` 契约重发（§4） | **整函数删除** |
| T3 | tests/test_presentation_p4_family_629.py:64-79 | `test_urge_due_review_truth_banned_single_source`（钉词表单源互指 + `_BANNED_PLAYER_TOKENS` 成员） | **整函数删除** |
| T4 | 〃:82-101 | `test_deformation_banned_lifted_to_production_single_source`（钉 DEFORMATION 词表/剥离子集 + t622 别名互指） | **整函数删除** |
| T5 | 〃:104-141 | `test_family_p4_banned_covers_five_categories_and_seven_surfaces`（五族词表覆盖钉 + 七扫描面钉；一审版仅删监督臂，二审全扫后整删） | **整函数删除** |
| T6 | 〃:205-419 | `_collect_seven_surfaces` helper（盯生成物 scaffolding：组装七面供扫描；仅 T7/T8 两调用点，:432/:462） | **整 helper 删除** |
| T7 | 〃:422-452 | `test_family_p4_seven_surfaces_scan_production_artifacts_clean`（判词点名 :422-480 之一；:436-438 七面 `assert_no_family_p4_banned_tokens` 扫描） | **整函数删除** |
| T8 | 〃:455-480 | `test_family_p4_seven_surfaces_red_when_banned_token_injected`（判词点名之二；:470-477 注入禁词须变红的哨兵自检） | **整函数删除** |
| T9 | 〃:483-538 | `test_due_review_preserves_diegetic_fenjie_phrase`（钉剥词器不剜 diegetic「与喀尔喀分界而治」；剥词机制（P15）消亡即失义，且 :537 负向钉生成物文本） | **整函数删除** |
| T10 | 〃:541-570 | `test_urge_lever_due_review_import_order_both_succeed`（子进程钉 `URGE_TRUTH_BANNED_PLAYER_TOKENS` 再导出对象同一性） | **整函数删除**（词表消亡后无对象可钉） |
| T11 | 〃 import 块 | :6 docstring 行、:23/:29-32/:35/:37/:41-42/:52/:55 import（BACKLASH/CREDIT/FAMILY_P4/DEFORMATION/URGE_TRUTH/`_BANNED_PLAYER_TOKENS`/SUPERVISION/`_URGE_SCENE_BANNED` 各词表与哨兵） | **随机制删除清理** |
| T12 | tests/test_deformation_dual_rail_622.py:313-378 | `test_ac6_sentinel_no_system_tokens_on_three_surfaces`（:365-370 面1 列扫描 + :373-375 面2 公开渲染扫描）；import :17、模块级别名 :110-111 随删；:377-378 执行格真值断言（机面）若需留存改挂他函数 | **整函数删除** |
| T13 | tests/test_credit_events_628.py:580-584 | `test_idempotent_narrative_restore_write_only_banned` 内词表/扫描面 pin 块（:581-584）；import :18-19 随删；函数主体（幂等恢复行为）保留 | **删块** |
| T14 | tests/test_commitment_backlash_626.py:813-957 | `test_ac6_presentation_sentinel_distinct_from_625` 整函数（:895-903 `assert_no_backlash_banned_tokens` payload 扫描、:906-915 `presentation_constraints`/`avoid_phrases` 断言、:923-925 词表自 pin、:929-931 `inspect.getsource` 源码钉） | **整函数删除** |
| T15 | tests/test_urge_lever_624.py:433-516 | `test_grace_plea_payload_truth_hidden_from_player_ac6` 内两扫描块：:462-476（`banned` 词组扫 urge_scenes/`project_urge_audience_scene` 输出）与 :503-512（扫 `project_due_review_scene`/`list_due_review_scenes` 输出）；结构断言（:457-460、:501 payload 键存在性）保留 | **删两块**；`project_urge_audience_scene` import（:47）随 P22 改造定去留 |
| T16 | tests/test_beat_orchestration_503.py:602-622（九审判词点名） | `test_production_beat_generator_open_close_fallback_no_night_hardcode` 整函数：:607/:610/:616/:619 等值锁死函数固定开/收句 + 「夜」负断言 | **整函数删除**（随 P28 死函数根因删除） |
| T17 | tests/test_beat_orchestration_503.py:781-800（九审判词点名） | `test_web_auto_close_uses_session_beat_generator`：:790-793 以死函数作旁路哨兵（monkeypatch 抛 AssertionError）；:787-789/:795 session._beat_generator 路由断言为合法行为 | **重投影**：删 monkeypatch 死函数哨兵（哨兵对象消亡即失义），保留并改断 session 生成器路由收到 BEAT_CLOSE + typed 键（只断路由/结构化键，不比较生成文本） |
| T18 | tests/test_p4_guard_new_surfaces_547.py:188-220（九审判词点名） | :188 直接消费死函数产物落账、:212 `_assert_no_character_sentinel_leak(enter_body)` 扫描其输出；import :19 | **重投影**：enter_body 改经真实 LLM seam（桩 create_llm_beat_generator 只断 BeatInputs 结构化事实键）；:212 扫描面随死函数消亡删除；import :19 随删；:208-211 其余三面哨兵与 :214-223 结构断言保留 |
| T19 | tests/test_beat_orchestration_503.py:581-599（九审复扫命中，判词未点名） | `test_no_generator_keeps_deterministic_fallback` 整函数：:590 等值锁 N1 开夜兜底句「乾清宫·戌时，召对启。」、:598 等值锁 P24 收夜兜底句「退朝，召对到此。」 | **整函数删除**（前提「无 generator=确定性兜底」随 N1/P24 改造消亡；新行为由空垫位结构状态 + seam 路由断言承接） |
| T20 | tests/test_beat_orchestration_503.py:623-630（九审复扫命中，判词未点名） | `test_auto_close_fallback_body_no_night_hardcode` 整函数：:629 等值锁 P24 auto 兜底句「王承恩代宣退朝，召对到此。」 | **整函数删除**（随 P24 改造） |
| T21 | tests/test_beat_orchestration_503.py:765-777（九审复扫命中，判词未点名） | `test_web_start_chat_turn_wires_session_beat_generator`：:773 等值锁 P23 固定入殿句「宣入{name}入殿。」、:776 负向不等断言随固定句消亡失义 | **删两断言 + 重投影**：:773 改断 typed tags（TAG_ENTER/method）与 person_names；函数主体（session generator 接线契约，docs/test-cleanup-audit-1185.md:737 已裁定 keep）保留 |
| T22 | tests/test_relation_judge_634.py:527-528（九审复扫命中 :527；十二审 notary 夹带修订补 :528） | :527 等值锁 P24 收夜固定句「退朝，召对到此。」+ :528 对 `close_entry["body"]` 的 `"events"`/`"["` 词符扫描——两断言连续作用于自由生成物正文，非 typed 泄漏边界验证，违共享硬规 #13 与锚定宪法（实读 :521-528 复核：:521 closed typed 状态、:522 关系边、:523-526 TAG_CLOSE_NIGHT 账存在均为合法 typed 断言） | **:527 与 :528 一并删除**；:521-:526 typed 断言（closed 状态/关系边计数/TAG_CLOSE_NIGHT 账存在）保留 |

**边界备注（三审定稿，替代一审「他族另票不动」与二审「疑似人工定」旧注）**：删除原则覆盖全部六族词表与全部剥词/成句模板，不再存在「他族另票」保留面——一审末注所列 DEFORMATION/URGE_TRUTH/CREDIT/FOUNDATION/BACKLASH 各族词表及其测试断言已全部入上表（P3-P12、T3-T15）。处置例外 = 「核实后保留」八项 + S2/S3/S4 裁定合法保留（实读自证进 LLM context/机读列，不进玩家文本）+ S5 out-of-scope；S1/N1 裁定违宪入删除/改造（消费链见上表）。

### 3.5 tests/dossier_test_helpers.py（65 行）逐函数定性

| 行 | 函数 | 定性 | 处置 |
|---|---|---|---|
| :1-5 | `_cost_events(db, dossier_id)` | **裸 SQL 读访问器**（直读 decree_cost_events），非 fixture 非真实入口；且 565:39/623:55/621:110 各有同名本地定义（624:648 为内联裸读），helpers 版非单源 | **删除**；调用方（test_family_tail_615.py:11、test_override_breach_costs_564.py:9 import）去向三审定稿：**不得新增 cost-events 公共入口、不得回退本地 helper**——契约裸读点函数内内联 SQL，其余改查领域结果，逐点见 §3.6 |
| :8-13 | `_sat(db, table, name)` | **裸 SQL 读访问器**（classes/factions.satisfaction），与案卷无关的通用断言捷径 | **删除**；改 GameDB 既有公开读 `faction_satisfaction`（db.py:6529）/`class_rows`（db.py:6560）等价断言；调用方 564:9、615:11、pihong:2651（逐点见 §3.6） |
| :16-52 | `rejected_verdict(...)` | **共享 fixture**（构造结构化 rejected verdict dict，docstring 自证「four named duplicates」共用；18 文件 import 实证） | **保留**（fixture）；类型形状随 store verdict 契约走，不增行为封装 |
| :55-65 | `promulgate_proposed_appointments(db, state, content, registry=None)` | **真实入口封装**（`list_decree_dossiers` 读 + `apply_dossier_verdicts` 公共判决入口，6 文件 import：test_recommendations.py:10、test_pending_actions.py:35、test_executor_routing_721.py:23、test_recommendation_edges_635.py:11、test_qa_c_p0_1380_1355.py:19、test_session_cli_fallback.py:31） | **保留**；内部两调用随 store/段适配器机械改径；红线：不得再长出新行为封装（helper facade = 换地方站的壳，ADR 0151 决定 10） |

### 3.6 `_cost_events`/`_sat` 逐点去向（三审类4 定稿，不留「或」）

**两条违法选项排除**：40 项公开面无 cost_events 入口——新增仅供测试的生产 API 违法；回退本地定义 = 恢复多份同构裸 SQL——同样违法。定稿 = 契约裸读点函数内内联 + 其余全部改查真实 adapter 领域结果 + 重复 helper 全删（dossier_test_helpers.py:1-13、565:39-56、621:110-114、623:55-59 四份 `_cost_events`/`_sat` 定义全删）。

**甲、保留直接 SQLite 耐久态观察（append-only/幂等/恢复本身就是契约的最短 tracer，逐函数点名）**：

| 文件：函数（起始行；裸读点） | 观察表 | 断言内容 | 为什么该断言就是契约本身 |
|---|---|---|---|
| test_execution_joint_liability_565.py `test_adapter_replay_is_idempotent_on_joint_liability_rows`（:140；裸读 :144/:157） | decree_cost_events | adapter 重放前后行集逐行相等 | append-only 幂等 = 被测契约本身；satisfaction 终值无法区分「重放被闸」与「双扣恰好抵回」 |
| 〃 `test_execution_note_merge_interface_and_restore`（:399；裸读 :413/:422） | decree_cost_events | 跨连接 reopen（GameDB 关开）后行集与关闭前一致 | 跨连接恢复可读性 = 契约本身 |
| test_override_breach_costs_564.py `test_costs_are_idempotent_and_survive_restore`（:141；裸读 :148/:153/:159） | decree_cost_events | 重复 force 被状态闸拒后计数不膨胀 + 跨连接恢复计数一致 | 幂等 + 恢复双契约（函数名自证） |
| test_due_review_621.py `test_final_stage_terminal_close_joint_liability_at_most_once`（:467；裸读 :493-495/:512-515） | decree_cost_events | 连坐门闩 cost_kind=liability 恰一行；布景重放（:499-507）二次复核再入后行集相等 | "at_most_once" 幂等门闩 = 契约本身 |
| test_breach_plea_623.py `test_persist_foundation_tiers`（:378；裸读 :425/:429） | decree_cost_events | 坚持撤落 breach 代价；重复撤返 False 且行集不膨胀 | 重复撤幂等 = 契约本身 |
| test_family_tail_615.py `test_break_rank_appointment_rescript_td4_tracer`（:126；裸读 :241-257） | decree_cost_events | 跨连接恢复连接上跑真实 `settle_with_delta` 批红 tracer 后读回代价流水（override/-5 或空集） | 恢复后耐久读回 = 该 tracer 契约一部分；:253 注释自证 metrics 绝对值被 settle 他步触动（confounded），领域结果不可替 |

上述六函数裸读改**函数内内联 SQL**（不共享 helper）；同函数内 `_sat` 分量仍改公开读（见乙）。

**乙、改查真实 adapter 领域结果（其余全部调用点，逐文件）**：

- **`_sat` 全部站点 → 既有公开读** `db.faction_satisfaction(name)`（db.py:6529）/ `db.class_rows()`（db.py:6560）（既有 API，非新增）：
  - test_execution_joint_liability_565.py 本地 `_sat`（:53）+ 调用 :70-71/:77-78/:95-97/:104/:106/:108-109/:195-196/:200/:205/:248/:254/:280-281/:287-288/:325-326/:330-331/:387/:391；
  - test_override_breach_costs_564.py（helpers import）:39/:44-46/:66-67/:70-71/:79-80/:84-85/:96-97/:108-109/:112-113/:123-124/:136-137/:172/:176/:210/:218/:299-300/:558-559/:561-562/:604-605；
  - test_family_tail_615.py :152/:201/:262（`restored` 即 GameDB 实例，公开读直接可用）；
  - test_pihong_dossier_1490.py :2671-2672/:2682-2683。
- **`_cost_events` 零断言（`== []`）→ 领域结果**（`faction_satisfaction` 不变 / `state.metrics` 不变 / `get_relation_edge_events(event_kind="连坐")` 无边，按各函数断言面择用）：565:76/:186/:237/:434；621:306/:460；623:244/:282/:364/:478/:572/:634；564:86/:114/:125/:138/:510/:564；615:202（restored 上公开读）。
- **`_cost_events` 内容/计数断言 → 领域结果**（逐派系 satisfaction delta / state.metrics delta / 关系边 / adapter 返回的效果意图 dataclass）：564:48/:98/:178/:195/:220/:253/:498/:533/:607-611；623:979/:1004/:1035/:1074（毁约落代价 → state.metrics 皇威/民心 delta）；623:161/:174（当回合无损已由同函数 :170 案卷状态 + :173 issue active + :175 皇威不变覆盖，此两点删冗余）。
- **内联裸读**：test_urge_lever_624.py:648、test_deformation_dual_rail_622.py:102 → 同改领域结果（§4 对应行同步修订）。

## 4. raw SQL 逐处定性（测试直写/直读案卷 13 表）

口径：**耐久态行为断言**（断言对象=真实入口产出的持久行/计数/跨连接可读性）→ 保留，改径 store 公开读面（get/list_*；跨连接/恢复场景可留裸读）；**内部结构锁**（绕写径 UPDATE/INSERT/DELETE 置位布景、PRAGMA/索引形状断言）→ 重投影经真实入口重打布景，或删除（纯形状锁迁 store `ensure_schema` 契约）；**迁移/读端容异 fixture**（公共写径造不出的 legacy/异常形状，测试对象=迁移幂等或读端上溯）→ 显式保留并标注。13 表 = ADR 0151 决定 2 的 12 表 + 检举卫星 `faction_denunciations`。

| 文件:行 | SQL | 定性 | 处置 |
|---|---|---|---|
| dossier_test_helpers.py:3 | SELECT decree_cost_events | 读访问器 | 随 §3.5 删除 |
| test_assignment_materialize_520.py:589/:891 | SELECT execution_outcome/note/status | 耐久断言 | 改径 `get_decree_dossier` |
| test_breach_plea_623.py:59 | SELECT decree_cost_events（本地 `_cost_events`） | 混合：幂等比对 + 零/内容断言 | 本地 helper 删除；:425/:429 幂等比对改函数内内联裸读（§3.6 甲）；零/内容断言改领域结果（§3.6 乙） |
| test_character_knowledge_489.py:917 | UPDATE participant_roster（:908 测试布景） | 置位 | 重投影经 `append_decree_dossier_participants` 或显式 fixture |
| test_covert_levy_651.py:25/:164/:211/:512 | UPDATE status/promulgation_decision | 置位 | 重投影经判决/执行真实入口 |
| 〃:56/:133/:156/:173 | INSERT decree_dossier_links | 置位 | 重投影经 `add_dossier_links` |
| 〃:145 | DELETE decree_dossier_links | 置位 | 重投影（造无关联态用新建案卷） |
| 〃:506 | INSERT decree_dossier_decisions（force_promulgated 史，:497 测试） | 造史绕写径 | 重投影经 rejected verdict + 批红强颁真实入口 |
| 〃:530/:536 | INSERT faction_denunciations（:519 测试） | 置位 | 重投影经 `accept_faction_denunciations` 真实承接入口 |
| test_credit_events_628.py:146 | UPDATE participant_roster（:135 测试布景） | 置位 | 重投影/fixture |
| test_decree_dossiers_571.py:351 | UPDATE status='closed'（:336 测试布景） | 置位 | 重投影经 close/执行真实入口 |
| test_deformation_dual_rail_622.py:102 | SELECT decree_cost_events | 耐久断言 | 改查领域结果（§3.6 乙，无 cost-events 公共入口） |
| test_dossier_endorsements_612.py:186/:213/:299/:722 | SELECT COUNT decree_dossier_endorsements | 耐久断言 | 改径 `list_dossier_endorsements` |
| 〃:834 | SELECT COUNT decree_dossiers WHERE pending_action_id | 耐久断言 | 改径 `list_decree_dossiers` |
| test_dossier_reported_progress_619.py:103/:147/:167/:336 | SELECT COUNT dossier_reported_progress | 耐久断言（物轨 vs 私轨分离） | 改径 `list_dossier_progress` |
| 〃:115-119 | PRAGMA table_info(dossier_reported_progress) 负向闭集（无 secret/track 列） | 结构锁载语义 | 迁 store `ensure_schema` 契约测试 |
| test_due_review_621.py:114 | SELECT decree_cost_events | 混合：幂等门闩 + 零断言 | 本地 helper 删除；:467 函数 :493-495/:512-515 门闩幂等改函数内内联裸读（§3.6 甲）；:306/:460 零断言改领域结果（§3.6 乙） |
| 〃:317/:335/:344/:377/:405/:419 | SELECT COUNT/SELECT id decree_dossiers | 耐久断言（不新建案卷） | 改径 `list_decree_dossiers` |
| 〃:358/:399 | UPDATE status='closed',execution_outcome='fulfilled'（:340/:385 测试布景） | 置位 | 重投影经 `record_dossier_execution(close=True)` |
| 〃:500/:657 | UPDATE status='executing' | 置位 | 重投影经执行真实入口 |
| test_execution_arrival_673.py:31（66 口径外文件） | UPDATE status='executing',region_id | 置位 | 重投影 |
| test_execution_joint_liability_565.py:41 | SELECT decree_cost_events（本地 `_cost_events`） | 混合：append-only 幂等/恢复比对 + 零断言 | 本地 helper 删除；:144/:157（幂等）与 :413/:422（跨连接恢复）保留函数内内联裸读（§3.6 甲）；:76/:186/:237/:434 零断言改领域结果（§3.6 乙） |
| 〃:152 | UPDATE status='executing'（:140 重放布景） | 置位 | 重投影（重放幂等可用真实入口二次结案路径） |
| 〃:367 | UPDATE participant_roster 注入（:349 测试） | **读端容异 fixture** | 显式保留：公共写界 `db._validate_dossier_delegations`（565:14 注释）拒造「知情作委派人」形状，测试对象=读端 `list_execution_liability_parties` 上溯投影 |
| test_execution_pressure_654.py:222-239 | PRAGMA table_info + sqlite_master 索引（region_id 列 + 复合唯一索引） | 结构锁（索引 SQL 文本） | 迁 store `ensure_schema` 契约（复合唯一的行为语义已由 :242 fan-out 幂等行为测试覆盖） |
| 〃:452/:994 | UPDATE status='executing',region_id / status='executing' | 置位 | 重投影 |
| 〃:1019/:1038 | UPDATE status='closed' | 置位 | 重投影 |
| 〃:804/:816/:938/:941/:1148/:1155/:1511/:1518 | SELECT COUNT decree_dossiers（含真实收夜成案入口前后比对 :1510-1518） | 耐久断言 | 改径读面/保留 |
| test_executor_routing_721.py:247/:288/:306 | SELECT id/payload_json WHERE pending_action_id | 耐久断言 | 改径 `get_decree_dossier`/`list_decree_dossiers` |
| 〃:329/:336/:343/:379/:380/:398/:399/:457 | SELECT COUNT（好项落/坏项不落） | 耐久断言 | 改径读面 |
| 〃:493 | UPDATE decree_dossiers SET {column} 参数化任意列 | 内部结构锁 | 重投影（按 column 逐点找真实写径）或删除 |
| test_extractor_slot_routing_629.py:170 | UPDATE status='executing' | 置位 | 重投影 |
| test_faction_denunciation_627.py:95/:112/:121/:454 | UPDATE status/execution_outcome | 置位 | 重投影经执行/结案真实入口 |
| 〃:510/:514/:538/:542 | SELECT COUNT decree_dossiers | 耐久断言 | 改径读面 |
| test_family_tail_615.py:180 | SELECT primary_opponents_json FROM decree_dossier_decisions | 耐久断言 | 改径 `list_decree_dossier_decisions`（返回已解析 primary_opponents） |
| test_family_tail_restore_570.py:135 | UPDATE status/promulgation_decision（:75 恢复测试布景） | 置位 | 重投影 |
| test_impeachment_surge_655.py:26/:108 | UPDATE status/execution_outcome | 置位 | 重投影 |
| 〃:134 | UPDATE participant_roster 注入（:120-124 docstring 自证） | **读端容异 fixture** | 显式保留：写界要求委派人占主办/协办行，测试对象=gather 读端按 delegator_id 上溯 |
| 〃:379/:382 | UPDATE closed_turn（/participant_roster） | 置位（窗口外/清空名簿布景） | 重投影；:382  roster 分量同 :134 定性 |
| test_ledger_sim_recon_569.py:305 | UPDATE status='executing' | 置位 | 重投影 |
| test_mutiny_actual_residence_659.py:79（66 口径外文件） | UPDATE status='executing',region_id | 置位 | 重投影 |
| test_office_rank_562.py:33/:68/:87 | SELECT 行/payload_json | 耐久断言 | 改径 `get_decree_dossier` |
| 〃:265/:270/:280/:287 | SELECT/UPDATE payload_json（:261 测试） | **迁移 fixture**：:270 造 break_rank 缺失 legacy 形状 → 跨连接重开×2 断回填幂等 | 保留（迁移契约）；随 store `ensure_schema` 迁移组归置 |
| test_override_breach_costs_564.py:88/:305/:354/:359 | SELECT affected_parties_json | 耐久断言 | 改径 `list_decree_dossier_decisions` |
| 〃:324/:328/:333 | INSERT decisions/pending_promulgation_verdicts 造 legacy severity 形状（:316 测试） | **迁移 fixture**（公共写径拒绝 legacy 形状，db.py 迁移消费端自证） | 保留；跨连接 reopen 部分见 §3.2 |
| 〃:412 | UPDATE decisions SET affected_parties_json='{}' | 置位 | 重投影（造空 parties 态经真实 verdict 入口变体） |
| 〃:475 | UPDATE status/closed_turn/interruption_reason | 置位 | 重投影经 close/interrupt 真实入口 |
| test_pihong_dossier_1490.py:1449 | PRAGMA table_info 负向闭集（rescript_origin 不在列，A12 契约） | 结构锁载语义 | 迁 store `ensure_schema` 契约 |
| 〃:2685 | SELECT affected_parties_json | 耐久断言 | 改径读面 |
| 〃:3135/:3154 | SELECT COUNT decree_dossiers | 耐久断言 | 改径读面 |
| test_presentation_p4_family_629.py:171（66 口径外直调，helper 布景） | UPDATE status='executing' | 置位 | 重投影 |
| test_promulgation_judge_561.py:160 | INSERT decree_dossier_decisions 造七组合颁布史（:145 `test_promulgation_history_only_projects_forced_and_midzhi_markers`） | 造史绕写径 | 重投影经 rejected verdict + 批红四动作真实入口逐条产生（断言 `build_promulgation_judge_context` 历史投影不变） |
| 〃:428 | UPDATE target_kind='',target_id='' | 置位（无靶布景） | 重投影或显式 fixture |
| 〃:465 | UPDATE payload_json/executor（:450 重载测试） | **对比布景**：行为=重读后取新行（:487-493 stale vs fresh 对照） | 保留语义；置位改径编辑真实入口（directive edit 路径）或显式 fixture |
| test_promulgation_seam_560.py:114 | UPDATE pending_promulgation_verdicts 造损坏 JSON（:81 测试） | **容错 fixture**（写径有校验造不出损坏行） | 显式保留（恢复容错契约固有） |
| 〃:154 | SELECT verdict_json | 耐久断言（断言对象=损坏行原样留存） | 保留（与 fixture 一体） |
| test_punishment_materialize_517.py:833/:845/:892/:897 | SELECT COUNT decree_dossiers | 耐久断言 | 改径读面 |
| test_recommendation_edges_635.py:285 | SELECT COUNT decree_dossiers | 耐久断言 | 改径读面 |
| test_refugee_loop_652.py:451/:453 | DELETE reconciliations / UPDATE closed_turn | 置位 | 重投影 |
| test_rescript_choices_563.py:149 | UPDATE payload_json='{}' | 置位 | 重投影/fixture |
| 〃:216 | SELECT turn,decision FROM decree_dossier_decisions | 耐久断言 | 改径 `list_decree_dossier_decisions` |
| test_faction_denunciation_627.py:577-580 | sqlite_master + PRAGMA 列集等值（DENUNCIATION_ALLOWED_COLS，supervision.py:96-102） | 结构锁（**位于被删函数 :494-610 内**） | 随函数删除后由 store `ensure_schema` 契约测试重发（列白名单契约不丢） |
| test_rescript_draft_656.py:1182（66 口径外文件） | PRAGMA table_info + 索引（rescript_origin 负向 + origin_ref partial unique） | 结构锁载语义 | 迁 store `ensure_schema` 契约 |
| test_secret_dossier_participants_1252.py:152 | UPDATE participant_roster 重置（:113 崩溃重放布景） | **重放布景 fixture** | 保留语义；改径或显式标注（行为=重放重新 append，:148-160） |
| test_supervision_625.py:474/:493 | UPDATE status='executing'（:465 AC4 统一在场门布景） | 置位 | 重投影经执行真实入口 |
| 〃:209-237 | sqlite_master 表存在 + PRAGMA 列集等值（PRESENCE/EXPOSURE_ALLOWED_COLS）+ 全库禁列片段（FORBIDDEN_DULLING_COL_FRAGMENTS） | 结构锁（schema 面守门，非盯生成物） | 迁 store `ensure_schema` 契约测试 |
| 〃:508/:527 | INSERT decree_dossier_reconciliations（同测试对账路布景） | 置位 | 重投影经 `record_monthly_grant_reconciliations` 真实月结入口 |
| test_urge_lever_624.py:648 | SELECT decree_cost_events | 耐久断言 | 改查领域结果（§3.6 乙，无 cost-events 公共入口） |

汇总（按 SQL 站点计，共 130 处；另 dossier_test_helpers.py:3 随 §3.5 删除）：读断言改径 62 处；置位/造史重投影 49 处；迁移/读端容异/容错 fixture 显式保留 13 处（7 组：565:367、655:134、562:265-291 迁移回填、564:324-333 legacy 造形、560:114/:154 损坏行容错、1252:152 重放布景、561:465 重载对照）；PRAGMA/索引/列集结构锁迁 schema 契约 6 处（619:115、654:222、1490:1449、656:1182、625:209-237、627:577-580——625 经表名常量、627 在被删函数内，两者grep 字面量不可见，补实读命中）。

## 5. 汇总

- 判词三数复核全中：**66 文件 / 1,449 测试函数 / 538 直调函数**（§1.2 口径明载；全块口径 67/1,466/539，差异=qa_c_p0 一文件 + 判词私有白名单只收 3 名）。
- 逐文件处置（§2）：机械改径 30 / 部分拆分 33 / 保留家族 3；删除函数 4（625:578 盯生成物、627:494 盯生成物、524:467 同规则重复绿卡、qa_c_p0:697 私有校验绿卡）+ 522:704/:705 两点私有断言删除。
- record_dossier_decision 59 站点 / transition_decree_dossier 12 站点全部给重投影路径（P/R/H/W/X 四类映射 §3.1），本家族无内部步骤绿卡删除项。
- pending verdict 家族保留清单 22 个函数（atomic replace=560:527、rollback=560:81/:500、跨连接 reopen=564:316 + 恢复链 560:41/561:531，§3.2）；连坐/毁约 tracer 保留 46+ 函数（565 全 12、564 全 21、626 保留 13 删 :813-957 + 关联文件，§3.3）。
- 盯生成物/剥词/措辞管控/成句模板（§3.4 二审重写 + 三审裁定 + 九审补扫 + 十审纠偏）：生产删除/改造 **31 条**（P1-P29 六族词表与哨兵全删、`presentation_constraints` 键删、due_review/breach_plea/urge_lever/decree_vocabulary 成句模板改结构化事实供给、audience_night 六处固定 scene 句 + beat_orchestration 死函数 + S1 decree.py:2847、N1 audience_night.py:837 两处三审裁定违宪成句；CLI terminal.py 同族回显固定句七处按调用侧合并入 P23/P25/P26、不另编号）+ 核实保留 8 项 + S2/S3/S4 裁定合法保留、S5 out-of-scope；测试删除 **22 条**（T1-T22：11+4 整函数/整 helper/删块/import 清理 + 九审 T16-T22 含判词点名 629:422-480 两函数与 beat_orchestration_503 死函数三点）。**计数口径（十审定）**：同一玩家可见事件（入殿/退下/留侍/收朝/明发）跨表面（故事账/CLI 控制台回显/死函数模板）的同构固定句归并入该事件根因 P 项、计数一次，调用侧/表面副本不独立编号；仅独立事件或独立机制才续编新号。
- commit 直调旧动词（§3.3 末小节）：`breach_decree_dossier` 直调 7 站点（564:174/:192/:214/:384/:525/:526 + 623:428）改走真实 adapter/真实入口；`apply_execution_joint_liability`/`_apply_override_costs` tests/ 零直调实证；564:444 实读已经真实段适配器链，保留。
- **测试执行纪律（二审修订，与 pr-slices 口径对齐）**：每个纵切片只跑该片聚焦测试，不做每片全量；最终收敛片后全量 `python -m pytest tests/ -q -n auto` 一次收口（与 CI 同参）。
- dossier_test_helpers.py：删 `_cost_events`/`_sat` 两裸 SQL 访问器，留 `rejected_verdict`（fixture）/`promulgate_proposed_appointments`（真实入口封装）（§3.5）。
- raw SQL 131 处逐处定性：62 读断言改径 / 49 置位重投影 / 13 fixture 保留（7 组）/ 6 schema 契约迁移 + helpers:3 删除（§4）；其中 5 处 decree_cost_events 读面（565:41、621:114、622:102、623:59、624:648）三审改口径 = 无 cost-events 公共入口，契约点内联裸读、其余改领域结果（§3.6）。
- **`_cost_events`/`_sat` 闭合（三审类4，§3.6）**：四份 helper 定义全删；保留直接 SQLite 仅 6 函数（565:140/:399、564:141、621:467、623:378、615:126——append-only/幂等/跨连接恢复即契约本身，函数内内联）；`_sat` 全站点改既有公开读 `faction_satisfaction`/`class_rows`；其余零/内容断言改领域结果。
- **玩家面裁定（三审类5 + 四审类2 + 五审修订 + 九审补扫 + 十审纠偏，§3.4）**：S1 违宪删除、N1（audience_night.py:837 固定开夜兜底句）违宪删除/改造、S2/S3/S4 实读裁定合法保留（进 LLM context/机读列）、S5 out-of-scope；消费链**五审定稿**——S1 定案（五审重定）= 拒收事实包（decree.py:2654 同查询 list 版）→ **并列新增** `create_settlement_attendant_agent`（agents.py，与 :364-378 同构）+ `run_settlement_attendant_message`（decree.py，与 :186-217 同构）→ `attendant_message` 槽随 save_turn_report（decree.py:2861）同笔落库；上轮「复用抵京 attendant seam」作废（实读输入面不兼容）；失败语义 = **fail-loud abort**：settle 事务回滚、turn 不推进、月档不提交，经 `resolve_settling_recovery`（decree.py:1580）重试，不落兜底句；P13（五审派生化）= 删「待终奏机读标记」，终奏缺口候选纯派生（decree_dossiers status='closed' ∧ closed_turn>0 ∧ execution_outcome∈{degraded,transformed} ∧ 无 is_terminal 奏报行，schema db.py:1513/:1515；**六审核窄**——fulfilled/failed 结案不因本票新增终奏，须另获产品授权不得夹带；**七审候选域补齐**——普通+密令同谓词、不设 secret_order_id 排除（原 terminal_report_facade 无密令排除，排除会误删已结案密令案卷的终奏；ADR 0073：带执行判定面的案卷均可挂奏报轨）；**八审结案判据**——closed_turn>0≠已结案（db.py:15580-15614 对非 executing outcome 均写 closed_turn=:15610，结案由 close 参数独立决定 :15614-15615；close=False 在办行合法，tests/test_covert_levy_651.py:149-154），谓词必含 status='closed'，与长差支路 status∈{promulgated,executing} 值域互斥、真正不重叠），候选读面 db.py:12751-12779 扩 union → 写口/守门 db.py:12781-12824（:12792-12811 fail-loud）→ extractor 注入 simulation.py:1342-1346 → settle 触发 decree.py:2720-2722，变形假象由输入面筛选承载，缺必覆 fail-loud → 回滚 → resolve_settling_recovery 重试；P16/P17/P18/P22 = `current_audience_scene`（due_review.py:370-375）筛选扩容 → `assemble_beat_inputs`（beat_orchestration.py:234-240）→ open-beat LLM materials 槽（:328-332），audience_night.py:841-850 旧 scene_text 拼接块整删。**测试处方（五审）** = 只断 typed/JSON 结构化键、路由与槽位、fail-loud/回滚/重试状态、行存在性与机读字段值；生成正文 transport 引用既有 498 家族、不复制测试；全节禁令明文（禁比较桩输出/禁词扫描/固定句存在缺席断言/文本条数措辞锁）见 §3.4 消费链表后。**九审补扫（§3.4）**：本票已触及接缝上的同构固定 scene 模板与死函数补入清单——P23-P27/P29（audience_night.py:946 入殿句/:1546-1548 收朝句/:2065 退下句/:2100 留侍句/:1533「明发旨意：」前缀/:886 随侍句）成句模板改结构化事实供给，P28（beat_orchestration.py:337-389 `production_beat_generator` 死函数，生产调用 grep 为零）删除根因；法源 ADR 0046（入殿/退下 scene 特征化长出、非模板句）+ ADR 0035（故事账正文不以模板压扁）；消费链统一接前轮定案 BeatInputs seam（typed tags/person_names/时地保留 → assemble_beat_inputs → create_llm_beat_generator materials → LLM 成文），无 generator 留空垫位、失败 fail-loud 不建新 fallback；测试 T16-T22（判词点名三点 + 复扫命中四个固定句等值 pin）随根因删除或重投影断 typed 键/路由，禁令明文同节适用。**十审纠偏**：废九审统一 seam 口径——P23 入殿/P24 收朝/P25 退下分走 start_open_enter/start_close/start_exit 真实链（beat_orchestration.py:498-550/:680-702/:641-666，回填或 finalize 落账），P26 留侍/P29 随侍无 registry/LLM 路由 → 删固定句根因、留 typed tags+空 body、不新增平行机制；CLI terminal.py 七处同族回显固定句（:363/:638/:658/:679/:683/:781/:785）并入 P23/P25/P26 调用侧、不另编号；计数定稿生产 31/测试 22（口径见上条）。**十一审投影修正**：CLI 七处由纯删除改为「删固定副本 + 现有生成 scene 可见投影」——open/enter 经 terminal.py:729 join 结果对象于 :768 打印位前呈现、exit 经 :321 join 结果于 :658/:679/:683/:781/:785 打印位呈现、close 经 TAG_CLOSE_NIGHT 账读面于 :679 打印位呈现（ADR 0046:5：scene 属本轮玩家可见内容，纯删会造成 CLI 投影缺口）；P26/P29 维持无生成机制现案，:363 删后留侍 CLI 不成句（有意）；测试只断 typed 路由/槽位/scene 事件标记进 CLI 输出路径，不比较正文；计数不变。**十三审生命周期闭合**：attach 所建 generating 无回话控制轮不收口会让收夜屏障（audience_night.py:978-1002，不再靠 timeout 放行）永久等待——open/enter（及相应 exit）汇合+persist 后复用既有 `complete_rescript_summon_scaffold_turn` consumed 写点（db.py:9155-9173）终结为 'consumed'，失败沿 abandon（session.py:1534-1536）+ fail（db.py:9423 起），终结先于 stay 继续/summon/dismiss 返回/court_break 进屏障；测试参数化四种首轮控制输入逐案断 start_open_enter 恰一次 + TAG_ENTER 账 + scene 投影 + `list_in_flight_chat_turns` 为空。
- **断言零变化口径**：仅适用纯迁移部分；玩家文本生成路径的删除属合宪行为修正，相关测试按新输出重写或删除（文件头部口径条）。
