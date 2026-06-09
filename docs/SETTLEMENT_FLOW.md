# SETTLEMENT_FLOW.md — 月末结算管线（driver 调引擎的顺序）

**真相源**：`ming_sim/decree.py:resolve_directives + _settle_after_narrative`。
原版是 simulator/extractor 两步 LLM；探针 step1 我**一次产 delta**，driver 把两步合一。

## 完整顺序（按调用先后）

```
[step1：召见 / 拟旨阶段]
  driver 读盘 → 我演大臣对话 → 我帮玩家拟旨

[颁诏后开始结算]
  1. before_turn = state.turn                    # 记下推进不变式的基线

  2. apply_fixed_period_flows(db, state)          # 月度财政 tick
     ↳ compute_budget_lines 的定额项（田赋/辽饷/盐税/商税/官俸/宫廷/…）
     ↳ 逐军 arrears tick / 逐建筑 condition × output_amount → 国库/内库
     ↳ 我那座金矿(+800)/银行(+300)/帝国航空(+10皇威) 在这一步生效
     ⚠️ 我的 economy_moves 不要重复这些固定项！

  3. auto_trigger_seed_issues(db, state, content) # 程序硬触发（必须在我产邸报前）
     ↳ trigger_gate 达标 + auto_trigger=True 的 seed event 直接立成 issue
     ↳ 出现在本月候选清单里供我推演引用

  4. chapter_memories = db.list_chapter_memories(upto_turn=state.turn, recent=6)
     auto_submit_due_secret_orders(db, state)
     secret_orders = db.list_secret_orders(status in (active, pending_review))
     previous_summary = db.previous_turn_summary(state.turn)

  5. [我产邸报 narrative]  ← 季末讲官身份，照 season_simulator.md 的章法
     - 拆 decree_text 成独立旨意逐条推演
     - 钱粮三要素「源→目标，金额」
     - 末尾可追 <<DECISION>>...<<END>> HITL 决策块（≤5 个）

  6. narrative, decisions = parse_decision_blocks(narrative)
     如果 decisions 非空：
       db.save_resolve_context(...)
       db.save_pending_decisions(...)
       return ResolveResult(awaiting=True, report="")  # 暂停等亲裁
     否则继续 phase2

  --- phase2（无 HITL 或亲裁后续跑）---

  7. effective_narrative = (DECISION_PREFIX + decision_text + "\n" if decision)
                         + (CHEAT_PREFIX   + cheat_text    + "\n" if cheat)
                         + narrative

  8. [我产 delta JSON]  ← 档房书办身份，按 DELTA_SCHEMA.md 产
     - 单份合并（不分四模块），driver 喂给 apply_score_extraction

  9. applied = apply_score_extraction(db, state, delta, content=content, registry=None)
     ↳ 内部 _sanitize → _merge → 分发到 region/army/building/economy/issue/character 各 apply_*
     ↳ 不合法字段会被沉默裁掉，关键违规印 [INFO]/[WARN]
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
      state.clamp()
      state.next_period()
      db.save_state(state)
      assert state.turn == before_turn + 1          # 推进不变式
```

## 无诏推进（玩家退朝未下旨）

```
advance_without_edict(state, db):
  apply_fixed_period_flows(db, state)             # 只走固定 tick
  db.record_log(...) ; print(...)
  state.next_period()
  db.save_state(state)
```

不结算、不推 issue 惯性、不判结局——保留给"这个月没事，朕退朝"的情况。

## 不变式 / 雷区

- **顺序不能改**：`auto_trigger_seed_issues` 必须在产邸报前；`chapter memory` 必须在结局判定前；`apply_issue_inertia_and_ongoing(touched_ids=)` 中 touched_ids 必须来自 `applied.issue_summary.advances`。
- **assert turn==before_turn+1**：phase2 完整跑完必须推进一回合，没推进就是 bug。
- **HITL 暂停时不要推进**：return awaiting=True 时 state.turn 不动，玩家亲裁后续跑 phase2 才推。
- **结算只判一次结局**：state.ended=True 后保持不动，继续推月只走 fixed flows。

## 已知接口层（确定性↔我，别让我自己数数）

- `ming_sim.memories.effect_brief(applied)` — 把 delta 聚合成一句话「国库+200、了结局势X、人事调整：…」
- `ming_sim.memories.build_timeline(db)` — 重建历史时间线
- `ming_sim.agents.build_simulator_context(payload)` — 盘面→TSV 文本（喂给我读盘）

这三个函数零 agno 依赖，driver 直接调用。

## 真相源对照

| 文件 | 看什么 |
|---|---|
| `ming_sim/decree.py` | `resolve_directives` + `_settle_after_narrative` + `advance_without_edict` 的步骤顺序 |
| `ming_sim/flows.py` | `apply_fixed_period_flows` `compute_budget_lines` |
| `ming_sim/issues.py` | `apply_score_extraction` `apply_issue_inertia_and_ongoing` `auto_trigger_seed_issues` `clear_gated_legacies` |
| `ming_sim/context.py` | `victory_status()` 结局判定 / `ENDING_*` 常量 |
