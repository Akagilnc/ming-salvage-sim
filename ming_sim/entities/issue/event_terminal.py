"""事件终态与级联的落账写侧：由 issues.py 清算迁入（ADR 0150 决定 8）。

门闩求值、依赖图校验与候选收集仍留在 issues（求值器非落库段）；本模块只写事件账
（终态、级联作废、亲裁结局）。外层收集器与镜像编排仍归 issues.auto_trigger_seed_issues。
"""

from __future__ import annotations

from typing import Dict, List

import ming_sim.issues as issues
import ming_sim.entities.fiscal.levy as fiscal_levy
from ming_sim.db import GameDB
from ming_sim.exceptions import SettlementAbort
from ming_sim.models import GameState


def apply_event_cascading_invalidations(
    state: GameState,
    db: GameDB,
) -> List[Dict[str, object]]:
    """Invalidate downstream historical events whose event-chain gates are now impossible.

    Only frozen event terminal/outcome ledger facts are invalidation grounds.  Other
    trigger_gate clauses (regions, locations, offices, etc.) remain soft gates and
    are deliberately ignored here because they may flip later.
    """
    content = issues._ctx()
    issues._validate_event_dependency_graph_acyclic(content, state)
    terminalized: List[Dict[str, object]] = []
    terminal_records = issues._event_terminal_records(db)

    while True:
        changed = False
        for ev in [*content.events, *content.seed_events]:
            if not getattr(ev, "id", "") or ev.id in terminal_records:
                continue
            if not issues._event_dependency_ids(ev):
                continue
            reason = issues._event_chain_impossible_reason(ev, terminal_records, state)
            if not reason:
                continue
            db.mark_event_obsolete(
                state,
                ev.id,
                reason=reason,
                source="event_chain_invalidated",
                commit=False,
            )
            row = db.issues.active_by_origin("event_pool", ev.id)
            if row is not None:
                db.cancel_issue(state, int(row["id"]), narrative=f"事件链作废：{reason}", commit=False)
            item: Dict[str, object] = {"id": ev.id, "title": ev.title, "terminal_state": "obsolete", "reason": reason}
            terminalized.append(item)
            terminal_records[ev.id] = {"terminal_state": "obsolete", "terminal_reason": reason}
            changed = True
        if not changed:
            break

    return terminalized


def apply_petition_event_outcome(
    state: GameState,
    db: GameDB,
    event_id: str,
    raw_label: object,
) -> Dict[str, object]:
    """亲裁语义落账的**单一写口**：把转译出的结局标签置成事件终态（#1892 / ADR 0153:5）。

    契约：

    - **事件须在可呈窗口内**：三饷只有到点才上疏（issues._event_window_open），窗口外
      的事项没有可供皇帝亲裁的既成事实，此时置定结局等于替皇帝凭空批一疏。窗口外
      响亮拒绝，不静默放过。
    - 标签只在事件自身声明的封闭集 ``terminal_reason_labels`` 内归一；归一不了就
      :class:`SettlementAbort` 响亮失败（ADR 0014：绝不兜底写未支撑值），不猜、不兜。
    - **留中不写终态**：raw_label 为空即「本疏已答而事件未终」，调用方不得以任何形式
      把它塞进终局标签集——留中不是结局标签。
    - 已落其它终态（expired/avoided/obsolete）的事件不被翻成 triggered；终态不可逆。

    写口只此一处：批红链路不直接写 ``terminal_reason``，原始选项标签不得旁路代批。
    """
    eid = str(event_id or "").strip()
    event = fiscal_levy._fiscal_levy_event_by_id(eid) if eid else None
    if event is None:
        raise SettlementAbort(
            f"亲裁结局事件不存在：{eid}", turn=int(state.turn), stage="fiscal_levy_config",
        )
    if not issues._event_window_open(event, state):
        raise SettlementAbort(
            f"亲裁结局事件不在可呈窗口内：{eid}", turn=int(state.turn), stage="fiscal_levy_config",
        )
    raw = str(raw_label or "").strip()
    if not raw:
        # 留中：本疏已答，事件未终。不写终态，也不另开一条留中账。
        # 已呈原文与原批语在 record_event_petition_answer 的 choice_json 里。
        return {"id": eid, "settled": False, "terminal_state": "", "terminal_reason": ""}
    existing = db.issues.event_terminal_state(eid)
    if existing == "triggered":
        # 一事件一裁断（ADR 0115:3 first-wins）：结局已落定即不可翻。
        return {
            "id": eid, "settled": False, "terminal_state": "triggered",
            "terminal_reason": issues._event_terminal_records(db).get(eid, {}).get("terminal_reason", ""),
        }
    if existing:
        return {
            "id": eid, "settled": False, "terminal_state": existing,
            "terminal_reason": issues._event_terminal_records(db).get(eid, {}).get("terminal_reason", ""),
        }
    label = fiscal_levy._fiscal_levy_normalized_terminal_reason_or_abort(event, raw, state)
    db.mark_event_triggered(
        state, eid, source=issues.FISCAL_LEVY_RESCRIPT_SOURCE, terminal_reason=label, commit=False,
    )
    if eid == fiscal_levy._LIAO_LEVY_RISE_EVENT_ID and label == "已准":
        fiscal_levy._fiscal_levy_reinstate_abolished(
            db, state, fiscal_levy._FISCAL_LEVY_LIAO_KEYS,
            origin_ref=f"event:{eid}", reason="升率获准，重新开征辽饷",
        )
    apply_event_cascading_invalidations(state, db)
    return {
        "id": eid, "settled": True, "terminal_state": "triggered", "terminal_reason": label,
    }


def apply_event_terminal_states(
    state: GameState,
    db: GameDB,
) -> List[Dict[str, object]]:
    """Persist deterministic event terminal states from the current board position."""
    c = issues._ctx()
    terminal_refs = issues._event_trigger_refs(db)
    terminalized: List[Dict[str, object]] = []

    for ev in c.events:
        if issues._is_fiscal_levy_event(ev):
            continue
        if ev.id in terminal_refs or ev.trigger_year <= 0:
            continue
        if issues._event_window_expired(ev, state):
            db.mark_event_expired(state, ev.id, commit=False)
            terminal_refs.add(ev.id)
            terminalized.append({"id": ev.id, "title": ev.title, "terminal_state": "expired"})
            continue
        dead_subjects = issues._dead_person_core_subjects(ev, db)
        if dead_subjects:
            reason = f"人物核心主体永久死亡：{', '.join(dead_subjects)}"
            db.mark_event_obsolete(state, ev.id, reason=reason, commit=False)
            terminal_refs.add(ev.id)
            terminalized.append({"id": ev.id, "title": ev.title, "terminal_state": "obsolete"})
            continue
        if not issues._event_window_open(ev, state):
            continue
        if not issues._gate_passed(ev.trigger_gate, state.metrics, db):
            avoided_reason = issues._person_core_avoided_reason(ev, state, db)
            if avoided_reason:
                db.mark_event_avoided(state, ev.id, reason=avoided_reason, commit=False)
                terminal_refs.add(ev.id)
                terminalized.append({"id": ev.id, "title": ev.title, "terminal_state": "avoided"})

    for ev in c.seed_events:
        if issues._is_fiscal_levy_event(ev):
            continue
        if ev.id in terminal_refs:
            continue
        if issues._event_window_expired(ev, state):
            db.mark_event_expired(state, ev.id, commit=False)
            terminal_refs.add(ev.id)
            terminalized.append({"id": ev.id, "title": ev.title, "terminal_state": "expired"})

    terminalized.extend(apply_event_cascading_invalidations(state, db))

    return terminalized
