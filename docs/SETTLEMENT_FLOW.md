# SETTLEMENT_FLOW.md — 月末结算管线（driver 调引擎的顺序）

**真相源**：`ming_sim/decree.py:resolve_directives + _settle_after_narrative`，可复用核为 `pre_settle` + `settle_with_delta`（driver 与真实流程同核，ADR 0004）。
**事务边界与崩溃恢复语义**（v0.8.0.0 起）见 `docs/adr/0008-settlement-applier-contract-and-transaction-boundary.md`：前半段 `pre_settle` 自带事务提交后**保持已落**（设计明文，非缺陷）；后半段 `settle_with_delta` 整段单一 `applier.atomic` 事务，**全有或全无**。
原版是 simulator/extractor 两步 LLM；探针 step1 我**一次产 delta**，driver 把两步合一。

## 完整顺序（按调用先后）

```
[step1：召见 / 拟旨阶段]
  driver 读盘 → 我演大臣对话 → 我帮玩家拟旨

[颁诏后开始结算]
  1. before_turn = state.turn                    # 记下推进不变式的基线

  ── 前半段 pre_settle：自带单事务；提交后效果**保持已落**（中止重试不回滚=设计明文）──
  2. pre_settle(state, db, content=, registry=)
     a. db.commit_pending_actions(...)            # 动作闸门：聊天暂存的结构化写动作批量落库（driver 路无暂存=no-op）
     b. apply_fixed_period_flows(db, state)       # 月度财政 tick
        ↳ compute_budget_lines 的定额项（田赋/辽饷/盐税/商税/官俸/宫廷/…）
        ↳ 逐军 arrears tick / 逐建筑 condition × output_amount → 国库/内库
        ↳ 我那座金矿(+800)/银行(+300)/帝国航空(+10皇威) 在这一步生效
        ⚠️ 我的 economy_moves 不要重复这些固定项！
     c. auto_trigger_seed_issues(state, db)       # 程序硬触发（必须在我产邸报前）
        ↳ trigger_gate 达标 + auto_trigger=True 的 seed event 直接立成 issue
        ↳ 出现在本月候选清单里供我推演引用
     d. db.auto_submit_due_secret_orders(state)   # 到期密令转核议（原在 resolve_directives，已挪入此事务）
     e. turn_phase = settling + save_state        # 同事务收尾：「前半段已完成」相位锚
     幂等守门：相位已在 FRONT_HALF_DONE_PHASES（settling/awaiting_decision/…）时直接
     return，不二次落财政；崩在内部 = 全回滚 = 相位未变 = 重进干净重跑。

  3. db.save_resolve_context(decree_text, ready=0) # 诏书原文占位真源：跨进程恢复不丢玩家手改稿
     （driver 路无此占位，settle 前直接 persist_resolve_context 存 ready=1，见 8.5）

  4. chapter_memories = db.list_chapter_memories(upto_turn=state.turn, recent=6)
     secret_orders = db.list_secret_orders(status in (active, pending_review))
     previous_summary = db.previous_turn_summary(state.turn)

  5. [我产邸报 narrative]  ← 季末讲官身份，照 season_simulator.md 的章法
     - 拆 decree_text 成独立旨意逐条推演
     - 钱粮三要素「源→目标，金额」
     - 末尾可追 <<DECISION>>...<<END>> HITL 决策块（≤5 个）

  6. narrative, decisions = parse_decision_blocks(narrative)
     如果 decisions 非空（HITL 暂停，三件**同一事务**原子落库——崩在窗口里不留半套状态）：
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

  8.5 persist_resolve_context(db, before_turn, extracted, ...)   # ADR 0008 S2
     - 先过 validate_delta_shape（毒 payload 不得钉进重试真源），再存 ready=1
     - 跨进程恢复的重跑真源：崩溃后直接重放落库，不再花一次 LLM 重推演
     - driver 路同位同义（run_settle 在 pre_settle 后、settle_with_delta 前调）

  ── 后半段 settle_with_delta：整段单一 atomic 事务，9–15 全有或全无 ──
  9. applied = apply_score_extraction(db, state, delta, content=content, registry=None)
     ↳ 内部 _sanitize → _merge → 分发到 region/army/building/economy/issue/character 各 apply_*
     ↳ 白名单外字段仍被沉默裁掉，关键违规印 [INFO]/[WARN]
       （applier.RejectionCollector 拒收留痕契约层已立，apply 各分支接线见 issue #14）
     ↳ 返回 applied.issue_summary.advances → 用来算 touched_ids

  10. db.record_log(narrative[:1200]) + db.save_turn_report(narrative) + db.save_turn_extraction(...)

  11. [我产 chapter memory {body, tags}]  ← 起居注史官身份
      → record_chapter_memory(state, {body, tags})  # 必须在结局判定前

  12. touched_ids = {a.issue_id for a in applied.issue_summary.advances}
      apply_issue_inertia_and_ongoing(db, state, touched_ids=touched_ids)
      ↳ 未被本月触动的 issue 才走惯性漂 / ongoing_effects 月支

  13. clear_gated_legacies(db, state)              # 开局负面修正按 clear_gate 程序判定消除

  14. 结局三级判定（state.ended=False 时才判，已 ended 跳过省 token）：
      a) 叙事型：applied.victory_status / 退位 / 自尽 → ENDING_NARRATIVE
      b) 数值型：京畿失守等 → context.victory_status()
      c) 到期型：state.turn >= TIMEOUT_TURN(240) → ENDING_TIMEOUT
      若 ended=True → [我产 ending summary]，db.save_ending_summary(...)

  15. db.mark_directives_issued(state)
      state.next_period()
      assert state.turn == before_turn + 1          # 推进不变式（先验后写，失败时重试真源还在）
      state.turn_phase = summoning                  # settling 随推进复位，同笔 save_state
      db.save_state(state)
      db.clear_resolve_context(before_turn)         # 写序列最后一笔：清重试真源（防下月 double-apply）
      （state.clamp() 在 issues.py 各 apply 路内部调，不在此尾）

  ── 9–15 任一步崩 → 整段 SQLite 回滚 + reload_state_from_db 刷内存 → 原异常链上抛 ──
```

## 无诏推进（玩家退朝未下旨）

```
advance_without_edict(state, db, *, content=None, registry=None):
  前半段已完成（turn_phase ∈ FRONT_HALF_DONE_PHASES）→ 直接 raise：
    结算欠账不可退朝跳过，只能续跑 / 重新推演（awaiting 态则先亲裁）——ADR 0008 决定 6
  否则整条推进尾包单事务 atomic：
    db.commit_pending_actions(...)                # 聊天暂存动作先落库，否则成孤儿
    apply_fixed_period_flows(db, state)           # 只走固定 tick
    db.record_log(...)
    db.clear_resolve_context(state.turn)          # 清 stale 重试真源
    state.next_period() ; turn_phase = summoning ; db.save_state(state)
  崩 → 回滚 + reload_state_from_db 刷内存 → 链上抛
```

不结算、不推 issue 惯性、不判结局——保留给"这个月没事，朕退朝"的情况。

## 崩溃 / 中止恢复（ADR 0008 PR1，v0.8.0.0）

重开档（或同进程重试）按相位分流（`session.py` 恢复入口）：

- `awaiting_decision` → 幂等返回已存决策点等亲裁，不二跑 simulator。
- `settling` + ready=1 的 resolve_context → `resolve_settling_recovery` 直入后半段重放落库，**不重跑贵的 simulator/extractor**；诏书原文从存档真源回填。
- `settling` + 无 ready context（崩在推演期）→ 落回正常流程重跑推演；`pre_settle` 被 settling 守门跳过=财政不二落。
- settling 恢复窗口内**冻结改盘操作**（下旨草案/撤回/跳过等 7 个入口，`session._refuse_if_settling`；web 对应端点 409，CLI 打印恢复指引）。
- ready 但值级坏掉的 payload 反复重放失败 → 「重新推演」逃生口 `error_pack.clear_for_resimulation`：把 context **降级为非 ready**（保留邸报字段），不删行，崩溃循环切断。
- 每次中止落一份五件套错误包（DB 快照/上下文/错误链/manifest/拒收记录），**永不覆盖旧包**。

## 不变式 / 雷区

- **顺序不能改**：`auto_trigger_seed_issues` 必须在产邸报前；`chapter memory` 必须在结局判定前；`apply_issue_inertia_and_ongoing(touched_ids=)` 中 touched_ids 必须来自 `applied.issue_summary.advances`。
- **assert turn==before_turn+1**：phase2 完整跑完必须推进一回合，没推进就是 bug。
- **HITL 暂停时不要推进**：return awaiting=True 时 state.turn 不动，玩家亲裁后续跑 phase2 才推。
- **结算只判一次结局**：state.ended=True 后保持不动，继续推月只走 fixed flows。
- **三条推进尾同款**（settle_with_delta / advance_without_edict / simulator 失败 fallback）：各自 atomic 内同笔做完「清 resolve_context → next_period → 相位复位 summoning → save_state」，缺一条就是恢复入口的雷。
- **回滚后必 reload**：事务回滚只回 SQLite，内存副作用（metrics 直加 / 脏 settling 相位）必须 `reload_state_from_db` 刷净——脏 settling 被 pre_settle 守门跳过=下月财政永久丢。atomic 体内禁止 reload（读到未提交脏写）；嵌套时只有最外层回滚后才重载。
- **毒 payload 不入真源**：`persist_resolve_context` 前必过 `validate_delta_shape`；shape 垃圾走 SettlementAbort+错误包，不许静默吞、也不许钉进 ready=1 重试真源。

## 已知接口层（确定性↔我，别让我自己数数）

- `ming_sim.memories.effect_brief(applied)` — 把 delta 聚合成一句话「国库+200、了结局势X、人事调整：…」
- `ming_sim.memories.build_timeline(db)` — 重建历史时间线
- `ming_sim.agents.build_simulator_context(payload)` — 盘面→TSV 文本（喂给我读盘）

这三个函数零 agno 依赖，driver 直接调用。

## 真相源对照

| 文件 | 看什么 |
|---|---|
| `ming_sim/decree.py` | `resolve_directives` + `_settle_after_narrative` 编排；可复用核 `pre_settle` / `settle_with_delta`；`advance_without_edict`；`resolve_settling_recovery` / `persist_resolve_context` 恢复机械 |
| `ming_sim/applier.py` | `atomic` 事务边界（`_SuspendableConnection`：内层 commit 暂停、executescript 拒绝、嵌套深度计数）+ `RejectionCollector` 拒收留痕契约 |
| `ming_sim/error_pack.py` | `write_error_pack` 五件套诊断包 / `clear_for_resimulation` 重新推演逃生口 |
| `ming_sim/session.py` | settling/awaiting 恢复分流入口 + 恢复窗口冻结（`_refuse_if_settling`） |
| `ming_sim/flows.py` | `apply_fixed_period_flows` `compute_budget_lines` |
| `ming_sim/issues.py` | `apply_score_extraction` `apply_issue_inertia_and_ongoing` `auto_trigger_seed_issues` `clear_gated_legacies` `validate_delta_shape` |
| `ming_sim/context.py` | `victory_status()` 结局判定 / `ENDING_*` 常量 |
| `docs/adr/0008-settlement-applier-contract-and-transaction-boundary.md` | 事务边界 / 恢复语义 / 错误包的设计真源 |
