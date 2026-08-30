# SETTLEMENT_FLOW.md — 月末结算管线（driver 调引擎的顺序）

**真相源**：`ming_sim/decree.py:resolve_directives + _settle_after_narrative`，可复用核为 `pre_settle` + `settle_with_delta`（driver 与真实流程同核，ADR 0004）。
**事务边界与崩溃恢复**：见 `docs/adr/0008-settlement-applier-contract-and-transaction-boundary.md`（v0.8.0.0 起）。一句话：前半段 `pre_settle` 提交后保持已落，后半段 `settle_with_delta` 整段单一 `applier.atomic`、全有或全无。
原版是 simulator/extractor 两步 LLM；探针 step1 我**一次产 delta**，driver 把两步合一。

## #571 S1 案卷颁布关（当前实码顺序）

`pre_settle` 提交后，结算读取 DB 中的 `proposed` 案卷作为待判集；有待判案卷时只调用一次批量颁布判官，并要求 verdict 覆盖全集。随后将已颁与本回合可执行的案卷过滤进 simulator/extractor：被拒案卷的效果文本不进入执行输入。若判决产生批红动作，先保存 rescript 决策并暂停；皇帝选择后，verdict/rescript 与 pending actions 在 `settle_with_delta` 的同一 atomic 中应用。无诏推进若存在待判案卷，也走同一判决与原子应用链，不绕过颁布关。批红三选＝强颁（中旨，代价 0056）／收回（零皇威/派系代价）／留中（押后下月再判）。密令与内库内批豁免颁布关（应允即落地，0055）；经外廷受判类在 `commit_pending_actions` 只物化案卷、效果经颁布判决后落。

打回判决沿用同一 verdict/历史 seam，并严格携带：`blocked_layer` 三值之一（`cabinet_drafting` / `palace_rescript` / `six_offices`）、非空 `primary_opponents` typed 清单（每项须且仅为 `{"kind":"faction","key":<在册派系>}`）、`gatekeeper_id`（null 或在册人物 id）、非空缘由及完整 `criteria_snapshot`。快照只保存判决时的皇威档位、涉事任别、在持授权 id、背书条目 id；盘面后来变化不回写、不重算历史。部院与场外 class 不能成为主否决方。

判决结构或引用非法时，整批不进入 pending/history/案卷状态，按 `SettlementAbort(stage="promulgation")` 响亮中止；原 verdict 及原因沿用 `RejectionCollector → rejection_reports` 留痕。阻力数值字段均拒收；合法 typed 数值/布尔位仅包括正整数 `dossier_id`、快照中的正整数 `endorsement_entry_ids`，以及 bool `midzhi_unpromulgatable`。不新增 verdict 审计表。

这段只描述 #571 S1 与 #609 已实现的案卷判决与执行闸；其它案卷扩展不属于本契约。

## S1 结算顺序（按调用先后）

```
[step1：召见 / 拟旨阶段]
  driver 读盘 → 我演大臣对话 → 我帮玩家拟旨

[颁诏后开始结算]
  1. before_turn = state.turn                    # 记下推进不变式的基线

  ── 前半段：pre_settle + 占位 context 同一外层 atomic；提交后保持已落 ──
  2. pre_settle(state, db, content=, registry=, scene_registry=)
     # 内层事务被外层 atomic 并入（flat 可重入）
     # #542 scene_registry：调用方既有 ChatTurnSceneRegistry（session._scene_registry）；
     #   resolve_directives / pre_settle 只转发，不在此新建第二 registry/executor。
     a0. auto_close_open_night(db, state, ..., scene_registry=)
         # #498 颁诏遇开夜→顺势自动收夜（王承恩代宣）
         ↳ 在 atomic 外单独调用，收夜自有写与错误包，不与结算事务半嵌（#1353 / ADR 0149）：
           **过月=session 单写者票据队列屏障**（`SessionWriteQueue.barrier`）：
           尾随腿（抽取/读心/高亮）起跑领 turn key 票，LLM 并行在外，写库经
           `TicketedWriteGate`/`run` 按票序执行；屏障排在已领票之后，前序未清不跑。
           在飞回话：工人落终态即续跑（K10a 不把健康腿伪造成失败）；真挂死由
           provider/worker 硬超时落失败终态后 vacate，屏障只等终态——禁 elapsed 伪判。
           欠账抽取并入过月 drain/catch_up（玩家无感；统一重试耗尽才走失败单源）；
           背书：一夜一批 single-flight owner 去重（队列只管写序，不建第二套 dedup）；
           已绑定→续跑；真失败 fail-closed 保持 OPEN（禁第二次 LLM / contended 409）。
           见 `ming_sim/session_write_queue.py` + `audience_night.py` + `audience_extraction.py`。
         ↳ #542 收夜 scene 生命周期（调用方 registry 所有）：
           start_close_scene_on_registry（不立即 join）→ 与 endorsement 并行 →
           终局写入前 join_close_scene_on_registry（join-before-finalize）；
           失败 abandon/fail_chat_turn 后原样上抛，夜保持 OPEN、不进 settling。
           无 scene_registry/无 start_close 能力或无 beat_generator 时不提交 close Future。
     a. db.commit_pending_actions(...)            # 动作闸门：聊天暂存的结构化写动作批量落库（driver 路无暂存=no-op）
        # 〔ADR 0055/ADR 0057 interim：经外廷受判类此步改为只物化案卷、效果结算判决后落（颁布判官），见 ADR 0055〕
     b. apply_historical_fiscal_rates(state, db)  # #259 饷率事件前置：同 tick 置结局 + 改 settle.p
        ↳ 仅处理 category="fiscal_levy" 的历史事件；shadow stub 的结局须经事件白名单归一
          （辽饷升/剿饷开征/练饷开征：{已准, 已驳}，剿饷议停：{已停, 仍征}），不可归一则 fail-loud。
        ↳ set-to-target 写省级 `settle.p.{三饷应征, 起运定额}`，并持久化
          `settle._meta.{正赋起运基线, 辽饷九厘基线, 剿饷基线, 练饷基线}`；
          幂等、不逐月叠加。
        ↳ 必须先于 `settle_province_tick`，让饷率当月生效；后置通用事件终态 pass
          读到已 terminal 的饷率事件后自然跳过，防重复处理。
     c. apply_fixed_period_flows(db, state)       # 月度财政 tick
        ↳ compute_budget_lines 的定额项（旧档 legacy 为田赋/辽饷/盐税/商税；新档 substrate_hub
          为省级起运 + 盐税解京 + 商税解京，并显式列太仓亏空/京运边饷 hub/官俸/宫廷/…）
        ↳ 军饷按存档级 `fiscal_engine` 分流（预算行共用 `budget_key=army_pay`，
          `name` 只供呈现；落账跳过与摘要取数认 key 不咬显示名，#1366）：
          - `legacy` 老档：预算行 name=「各军军饷」、金额=`sum(army_needed)`；
            逐军从国库扣发，ledger category 仍为「各军军饷」；国库不足挂 `armies.arrears`。
          - `substrate_hub` 新档：旧全局「各军军饷」流水为 0，不再双付；预算分列
            中央军饷拟拨与京运补拟拨，只陈列结算前应拟支的两项来源，不受国库余额
            截断，也不预演或显示未来精确损耗。结算时再按本月开账国库能力跑
            `边饷hub` outbound，京运给各省 grant 与中央份额共用同一个 hub tier，写
            `中央军饷`、`central_pay_arrears`、中央欠饷容器与 `C_京运克扣/C_京运运损`；
            国库报告从既有 ledger/container 呈现已执行的国库实拨、实际到达、途中损耗。
            省份额随后由省级 substrate 写 `province_pay_arrears`，仍用 **应发 =
            ceil(manpower × salary_rate / 10000)**（#44，0 兵=0 饷）。
        ↳ 逐建筑 condition × output_amount → 国库/内库
        ↳ 我那座金矿(+800)/银行(+300)/帝国航空(+10皇威) 在这一步生效
        ↳ #66/#266/#261 省级财政基座与跨省 hub：动态 substrate spine 通过
          `GameDB.settle_ming_province_substrate_ticks()` 一次扫描 Ming 省 fiscal payload，
          推进 `controlled_by='ming'` 且有 `fiscal.settle` key 的省；失地自然出列，
          明控但无 settle 的省不创建基座。
          有效 fiscal 容器按 `settle` key 选择；解析失败、非 dict 容器、`settle.st/p`
          形状错误和 settle_tick 守恒错误会作为逐省 outcome 隔离并写 tlog。
          其它 bridge bug 继续 fail-loud。
          陕西 seed 已按 #266 重标到史实量级（正赋/辽饷九厘/军饷/官俸/宗禄/逋赋/火耗/起运定额），
          末态逐月演化+落库并 tlog 打印实征/起运/火耗/末态欠账；新档将省级起运、盐税、商税先写
          hub 容器，再按太仓损耗拆 `C_太仓挪用/C_太仓纯亏空` 后净额入国库。省/中央军饷欠账接入
          per-source 容器；基座显式坏态在 cutover 档 fail-loud，老 shadow 隔离只保留给非 cutover
          兼容路径。
        ⚠️ 我的 economy_moves 不要重复这些固定项！
     d. apply_event_terminal_states(state, db)    # 事件终态写路径（候选读取本身只读）
        ↳ 声明了 trigger_end_* 且未 `open_window` 的事件，超过最晚时点会先记 `event_triggers.terminal_state=expired`
        ↳ 人物核心主体已永久死亡则记 obsolete；人物核心门已被玩家处理掉则记 avoided
        ↳ 该步与 pre_settle 外层事务合并提交；嵌套事务内不提前 commit，回滚时终态写入一并回滚
     e. auto_trigger_seed_issues(state, db)       # 程序硬触发（必须在我产邸报前）
        ↳ trigger_gate 达标 + auto_trigger=True 的 seed event / historical event 先处理
        ↳ 已有终态或刚被上一步记成 expired 的事件退出候选 / 硬触发流，防止史实节点晚弹或重入
        ↳ situation 转 issue；node/ending 只记 event_triggers，并可落 effect_on_trigger
        ↳ 出现在本月候选清单 / 硬触发清单里供我推演引用
     f. db.auto_submit_due_secret_orders(state)   # #1504：到期只打期限戳，保持 active（结案在 settle 尾对账）
     g. turn_phase = settling + save_state        # 同事务收尾：「前半段已完成」相位锚
     幂等守门：相位已在 FRONT_HALF_DONE_PHASES（settling/awaiting_decision/…）时直接
     return，不二次落财政；崩在内部 = 全回滚 = 相位未变 = 重进干净重跑。

  3. db.save_resolve_context(decree_text, ready=0) # 诏书原文占位真源：跨进程恢复不丢玩家手改稿
     与 2 同一外层 atomic 提交：settling 相位与 context 行同生共死（回滚时一并 reload 刷内存）。
     driver 与引擎共用 `prepare_resolve_front_half`：`driver prepare` 写入 ready=0（含 transit_arrivals handoff），
     外部据已提交盘面产叙事+delta 后再 `driver settle --delta` 升 ready=1（见 8.5）。

  4. chapter_memories = db.list_chapter_memories(upto_turn=state.turn, recent=6)
     secret_orders = group_secret_orders_for_sim(active 行)  # 密令只进「在办」；#1504 结案不靠 pending 核议
     secret_orders = augment_secret_orders_with_due_commitments(secret_orders, db, state)
       ↳ form③ 承诺（有 end_turn、无 ongoing_effects）到期时写入「待核议」分组（entry_kind=due_commitment）
       ↳ #883 分流：分组只喂 personnel_secret extractor 独立 rail；
         simulator 公共轨只派生扁平 due_commitments（永不预读密令正文）
     previous_summary = db.previous_turn_summary(state.turn)

  5. [我产邸报 narrative]  ← 季末讲官身份，照 season_simulator.md 的章法
     - 拆 decree_text 成独立旨意逐条推演
     - 钱粮三要素「源→目标，金额」
     - 公共轨可见 due_commitments（到期待裁承诺），不预读 secret_orders
     - 末尾可追 <<DECISION>>...<<END>> HITL 决策块（≤5 个）

  6. narrative, decisions = parse_decision_blocks(narrative)
     如果 decisions 非空（HITL 暂停，三件同一事务原子落库）：
       atomic { db.save_resolve_context(...) ; db.save_pending_decisions(...)
                ; turn_phase = awaiting_decision + save_state }
       return ResolveResult(awaiting=True)  # 暂停等亲裁，state.turn 不动
     否则继续 phase2

  --- phase2（无 HITL 或亲裁后续跑）---

  7. effective_narrative = (DECISION_PREFIX + decision_text + "\n" if decision)
                         + (CHEAT_PREFIX   + cheat_text    + "\n" if cheat)
                         + narrative

  8. [我产 delta JSON]  ← 档房书办身份，按 DELTA_SCHEMA.md 产
     - 单份合并（不分四模块），driver 喂给 apply_score_extraction
     - 产物 shape 畸形（非 dict / 损坏 JSON / 未知顶层字段）→ write_error_pack 落五件套
       诊断包 + 抛 SettlementAbort 响亮中止（不再静默吞）；重试 = 重跑 simulator/extractor

  8.5 persist_resolve_context(db, before_turn, extracted, ...)
     - 先过 validate_delta_shape（毒 payload 不得钉进重试真源），再存 ready=1
     - 跨进程恢复的重跑真源：崩溃后直接重放落库，不再花一次 LLM 重推演
     - driver 路（两阶段，禁一站式）：
       1) `run_prepare` → 共享 `prepare_resolve_front_half`（pre_settle + ready=0 + transit_arrivals）
       2) 外部产 narrative+delta（可读已提交盘面与 arrivals handoff）
       3) `run_settle` 只消费同 turn settling+ready=0：合并案卷键∪既有 transit_arrivals → ready=1 → settle_with_delta
       未 prepare 的 settle 响亮失败且零写；settling+ready=1 崩溃重入只读 context，不二次 tick

  ── 后半段 settle_with_delta：整段单一 atomic 事务，9–16 全有或全无 ──
  9. db.commit_pending_actions(..., registry=None)  # 正常路通常为 no-op；覆盖恢复/重抽路的新暂存动作
     affected_people += db.apply_dossier_verdicts(..., registry=None)
     affected_people += db.apply_dossier_promulgation(..., registry=None)
     applied = apply_score_extraction(db, state, delta, content=content, registry=None)
     ↳ #672 任命并传召：pending/案卷先保存未激活的同源传召；任命真正落成后才在
       同一 outer atomic 内激活该传召并按在册出发地启程。任命失败则整笔回滚，不留在途半写。
     ↳ #1583 任命案卷物化前，先以本批结算开始时的盘面统一校验所有荐人快照；
       通过后按稳定案卷序依次物化，不再被同批前序任免造成的中间态误拒。批外真陈旧快照仍拒。
     ↳ verdict/批红返回的受影响人物只在 9–16 全部提交成功后刷新 registry；事务内不碰缓存。
     ↳ 内部 _sanitize → _merge → 分发到 region/army/building/economy/issue/character 各 apply_*
     ↳ 未知顶层字段响亮中止；9 个结算 section 的脏项（坏值/缺 id/非法 enum）逐项拒收
       落 `rejection_reports`（坏一项不带走整批，不再印 [WARN]），commit 成功后镜像到
       rejections.jsonl 副本。机制细节（RejectionCollector / attempt / 桥接）见 ADR 0008 PR2。
     ↳ 返回 applied.issue_summary.advances → 用来算 touched_ids

  10. db.record_log(narrative[:1200]) + db.save_turn_report(narrative)

  11. touched_ids = {a.issue_id for a in applied.issue_summary.advances}
      apply_issue_inertia_and_ongoing(db, state, touched_ids=touched_ids,
                                      applied_person_changes=inertia_person_changes)
      ↳ 全部 active issue 走惯性漂 / ongoing_effects 月支（touched_ids 入参保留但已不按它跳过——
        见 issues.py `_ = touched_ids`；本月被推进的 issue 也吃惯性，避免漏算）
      ↳ 承诺 issue 跳过普通 inertia：按 `commitment_kind` 走 stop_condition / end_turn / ongoing_effects
        专用闭环；补饷类月度效果喂 arrears 还款池，form② 到期写 expire，form③ 到期待裁后
        通过 close_issues(reason=acknowledged) ACK 收尾。
      ↳ inertia 追加的玩家可见人物变更并进 applied.issue_summary.applied_person_changes
        （下方 12 留痕 + 13 chapter memory 都读 applied，须先合并再存/记，否则两者漏 inertia 人物变更）

  12. db.save_turn_extraction(...)                  # inertia 合并后才存：玩家明细 / 时间线含 inertia 人物变更

  13. [我产 chapter memory {body, tags}]  ← 起居注史官身份
      → record_chapter_memory(state, {body, tags})  # 必须在结局判定前；记的 applied 已含 inertia 人物变更

  14. clear_gated_legacies(db, state)              # 开局负面修正按 clear_gate 程序判定消除

  15. 结局三级判定（state.ended=False 时才判，已 ended 跳过省 token）：
      a) 叙事型：applied.victory_status / 退位 / 自尽 → ENDING_NARRATIVE
      b) 数值型：京畿失守等 → context.victory_status()
      c) 到期型：state.turn >= TIMEOUT_TURN(240) → ENDING_TIMEOUT
      若 ended=True → [我产 ending summary]，db.save_ending_summary(...)

  16. db.mark_directives_issued(state)
      state.next_period()
      assert state.turn == before_turn + 1          # 推进不变式（先验后写，失败时重试真源还在）
      state.turn_phase = summoning                  # settling 随推进复位，同笔 save_state
      db.save_state(state)
      db.clear_resolve_context(before_turn)         # 写序列最后一笔：清重试真源（防下月 double-apply）
      （state.clamp() 在 issues.py 各 apply 路内部调，不在此尾）

  ── 9–16 任一步崩 → 整段 SQLite 回滚 + reload_state_from_db 刷内存 → 原异常链上抛 ──
```

## 无诏推进（玩家退朝未下旨）

#1274 QA J-1 / owner B-2：无旨月 = decrees=[] 的**正常月**，禁止 16ms 快跳。
日历走一个月，朝政也必须发生（simulator 邸报 / 种子局势 / 议题惯性 / 结局判定全链）。

```
session.advance_without_decree / POST /api/decree/advance_without_edict:
  有草案/pending → resolve_turn（同颁诏）
  无草案 → resolve_turn(allow_empty_decree=True, source=system_simulation)
           → accept_settlement_period + auto_close_open_night(..., scene_registry=)
           → resolve_directives(directives=[], decree_text="")
           → pre_settle + simulator + settle_with_delta   # ADR 0004 同核
  # #1274 r1：decree.advance_without_edict 空壳已删；prep（快照+收夜）归 resolve_turn。
  # #498 退朝遇开夜顺势自动收夜；#542 scene_registry 调用方所有（session._scene_registry）
```

#1467：无 hitl_min_decisions 配额；无旨月 simulator 仍可产局势决策 → 批红；真零决策则既有空批/all-decided 链路走通。
批量跳 N 月 = 另票 #1425，本片不做。

## 关系酿制腿（#636/#637/#642；月末增量重酿）

**真相源**：`decree.settle_with_delta` 单点拥有 start/join/drain 生命周期；腿本体＝`relation_brew.MonthEndRelationBrewLeg`（`prepare` → `brew` → `persist`）。派系态势摘要（#637）与关系摘要同批同命，不另开第二编排腿。

### 生产序（与无依赖后处理重叠）

1. **本月边事件集定型**：`_settle_after_extract_body` 内 apply/extractor 落库完成后，在 chapter/ending 等后处理之前触发 `start_relation_brew`。
2. **durable claim（认领先行）**：`MonthEndRelationBrewLeg.prepare` 在结算事务内按 `select_brew_targets`（该 settled 年月新增边事件 id>水位 ∨ durable pending）选中有向对；入选即 `claim_relation_brew_targets` 把 pending 落盘——与本月边事件同生共死。pending **不靠**失败后 catch 补记。
3. **备料**：对每个已选中有向对收集水位上 `new_events`；经 `relation_read.load_relation_history_before` 读取严格早于 settled 年月的**完整**历史事件（#642 锚④ coda 回流水，零语义筛选/裁剪），由 `build_brew_input` 装配为确定性 JSON（旧摘要段 + new_events + prior_events + 年月）。
4. **brew Future**：`brew()`（零 DB 的 LLM 相）提交到 `settle_with_delta` 唯一受管 Future，与无依赖的 chapter/ending 重叠等待。
5. **settle atomic commit**：整个后半段写序列（含 claim 与本月边事件）随 `atomic_and_reload` 提交；`next_period` 推进后 state 已指下一月，酿制落款仍用 settled 年月快照。
6. **join → persist**：提交成功后 join Future；`persist()` 将摘要写入与 pending 清除放在同一 DB 事务原子落定。单条 LLM 调用/输出契约失败→降级留痕（保旧摘要 + 事件已在流水 + pending 在册），不阻塞结算。

### 失败 / pending 恢复

| 窗口 | 后果 |
|---|---|
| 结算 atomic 回滚（commit 前） | 本月边事件与 claim 同消；酿制 Future 排空丢弃，产物一律作废 |
| 单条 LLM/契约失败 | 保旧摘要；事件仍在流水；pending 在册；下月补酿 |
| **commit 后 → join 后 → persist 前**中断（#642 R2） | 边事件仍在；旧摘要字节不变（无半新摘要）；durable pending 在册；再次结算补酿恰一次、pending 清除、摘要落定；边 id 不双增、水位不回拨 |
| persist 内 apply/mark DB 错 | 响亮上抛（ADR 0005/0008），不伪装成 LLM 单条失败 |

**禁止**：把召对口/seed 口写成「结算 extractor 一步」；禁止文档或实现对酿制输出做字数 clamp（CLAUDE.md P6 / ADR 0142）。普通读面仍是「摘要＋最近事件」五字段 DTO（`project_relation_ledger`）；完整历史只进 coda 酿制输入。

## 崩溃 / 中止恢复（ADR 0008 PR1，v0.8.0.0）

重开档（或同进程重试）按相位分流（`session.py` 恢复入口）：

- `awaiting_decision` → 幂等返回已存决策点等亲裁，不二跑 simulator。
- `settling` + ready=1 的 resolve_context → `resolve_settling_recovery` 直入后半段重放落库，**不重跑贵的 simulator/extractor**；诏书原文从存档真源回填。
- `settling` + 无 ready context（崩在推演期）→ 落回正常流程重跑推演；`pre_settle` 被 settling 守门跳过=财政不二落。
- settling 恢复窗口内**冻结改盘操作**：
  - 下旨草案/撤回/跳过等 7 个入口（`session._refuse_if_settling`；web 对应端点 409，CLI 打印恢复指引并留在本回合交互循环不重印回合头）。
  - 全部聊天侧新写入一并冻（`_proposal_blocked` 总闸）：任免候选暂存（`_stage_appointment_candidate`）、编外人物登记、密令房 tool 四个 action（issue/progress/submit/rush，`tools.py` dispatcher 一处冻）、CLI 前缀密令 upsert——这些写入在 settle 重试事务边界外，重放中止回滚不会回滚它们。
  - 自然语言抽取的**新暂存动作**短路不入档（抽取器 LLM 调用一并跳过）——窗内新 stage 会被重试 settle 的 commit_pending_actions 落进「保存的 delta 推演时并不知道」的旧回合。
  - 窗**前**已暂存的 pending 不受影响：对话确认（应允延迟提交/拒绝丢弃）保持可用，仍随 settle 事务统一提交。
- ready 但值级坏掉的 payload 反复重放失败 → 「重新推演」逃生口 `error_pack.clear_for_resimulation`：把 context **降级为非 ready**（保留邸报字段），不删行，崩溃循环切断。
- 每次中止落一份五件套错误包（DB 快照/上下文/错误链/manifest/拒收记录），**永不覆盖旧包**。

## 不变式 / 雷区

- **顺序不能改**：`auto_trigger_seed_issues` 必须在产邸报前；`apply_issue_inertia_and_ongoing` 必须在 `save_turn_extraction` + `chapter memory` 之前（inertia 追加的玩家可见人物变更要先并进 `applied` 再存 / 记，否则玩家明细与起居注漏 inertia 人物变更）；`chapter memory` 必须在结局判定前。（注：`apply_issue_inertia_and_ongoing` 的 `touched_ids=` 入参已不再用作跳过过滤——`issues.py` 内 `_ = touched_ids`、惯性漂吃全部 active issue；decree 仍按 advances 计算并传入只为保留调用签名，非不变式。）
- **assert turn==before_turn+1**：phase2 完整跑完必须推进一回合，没推进就是 bug。
- **HITL 暂停时不要推进**：return awaiting=True 时 state.turn 不动，玩家亲裁后续跑 phase2 才推。
- **结算只判一次结局**：state.ended=True 后保持不动，继续推月只走 fixed flows。
- **推进尾唯一正轨**：只有 simulator 成功并完成 extractor 后，`settle_with_delta` 才在 atomic 内同笔做完「清 resolve_context → next_period → 相位复位 summoning → save_state」。simulator 异常不进 extractor、不产邸报、不推进，保留 `settling` 供原月重试；并行 companion 若已成功则只存 ready=0 递话 checkpoint。#1274：无旨月推进只经 settle_with_delta（decree.advance_without_edict 空壳已删）。
- **回滚后必 reload**：事务回滚只回 SQLite，内存副作用（metrics 直加 / 脏 settling 相位）必须 `reload_state_from_db` 刷净——脏 settling 被 pre_settle 守门跳过=下月财政永久丢。atomic 体内禁止 reload（读到未提交脏写）；嵌套时只有最外层回滚后才重载。
- **毒 payload 不入真源**：`persist_resolve_context` 前必过 `validate_delta_shape`；shape 垃圾走 SettlementAbort+错误包，不许静默吞、也不许钉进 ready=1 重试真源。
- **settling 可见 ⟹ context 行可见**：settling 相位与 resolve_context 行（引擎/driver 共用 prepare 的 ready=0 占位）必须同一事务提交；driver settle 再把 ready=0 升 ready=1。prepare 不许拆成两笔——拆了就是「相位卡 settling、恢复入口无米下锅、玩家手改旨意原文蒸发」。

## 已知接口层（确定性↔我，别让我自己数数）

- `ming_sim.memories.effect_brief(applied)` — 把 delta 聚合成一句话「国库+200、了结局势X、人事调整：…」
- `ming_sim.memories.build_timeline(db)` — 重建历史时间线
- `ming_sim.agents.build_simulator_context(payload)` — 盘面→TSV 文本（喂给我读盘）

这三个函数零 agno 依赖，driver 直接调用。

## 真相源对照

| 文件 | 看什么 |
|---|---|
| `ming_sim/decree.py` | `resolve_directives` + `_settle_after_narrative` 编排；可复用核 `pre_settle` / `settle_with_delta`；二者均转发调用方 `scene_registry`（#542）；`resolve_settling_recovery` / `persist_resolve_context` 恢复机械；月末关系酿制 Future 的 start/join/drain |
| `ming_sim/relation_brew.py` | `MonthEndRelationBrewLeg` prepare/brew/persist；`select_brew_targets` / `build_brew_input`（含 #642 prior_events） |
| `ming_sim/relation_read.py` | `project_relation_ledger` 五字段读面；`load_relation_history_before` coda 历史读缝 |
| `ming_sim/session_write_queue.py` | per-session 单写者有序票据队列（#1353 / ADR 0149）：尾随领票、写经 `TicketedWriteGate`/`run`、过月=`barrier`、失败空放行、撤回 `cancel_key`；屏障只等工人终态（K10a 无 elapsed 熔断） |
| `ming_sim/audience_night.py` | `auto_close_open_night` / `close_night`：颁诏 / 退朝遇开夜时顺势自动收夜（#498）；在飞只依工人终态续跑（K10a）；欠账并入过月 drain；`scene_registry` 调用方所有，start→并行→终局前 join，失败 OPEN fail-closed |
| `ming_sim/audience_extraction.py` | 收夜 endorsement 批：一夜一批 single-flight 去重；真失败 fail-closed 保持 OPEN，禁第二次 LLM；写序归队列票据 |
| `ming_sim/beat_orchestration.py` | `ChatTurnSceneRegistry` + `start_close_scene_on_registry` / `join_close_scene_on_registry`：收夜 scene 进既有 registry，不自建第二 executor（#542） |
| `ming_sim/applier.py` | `atomic` 事务边界（`_SuspendableConnection`：内层 commit 暂停、executescript 拒绝、嵌套深度计数）+ `RejectionCollector` 拒收留痕契约 |
| `ming_sim/error_pack.py` | `write_error_pack` 五件套诊断包 / `clear_for_resimulation` 重新推演逃生口 |
| `ming_sim/session.py` | settling/awaiting 恢复分流入口 + 恢复窗口冻结（`_refuse_if_settling` 7 入口；`_proposal_blocked` 即时写/新暂存总闸） |
| `ming_sim/tools.py` | 密令房 tool dispatcher 的恢复窗冻结（issue/progress/submit/rush 四 action 一处冻） |
| `ming_sim/flows.py` | `apply_fixed_period_flows` `compute_budget_lines` |
| `ming_sim/issues.py` | `apply_score_extraction` `apply_issue_inertia_and_ongoing` `auto_trigger_seed_issues` `clear_gated_legacies` `validate_delta_shape` |
| `ming_sim/context.py` | `victory_status()` 结局判定 / `ENDING_*` 常量 |
| `docs/adr/0008-settlement-applier-contract-and-transaction-boundary.md` | 事务边界 / 恢复语义 / 错误包的设计真源 |
