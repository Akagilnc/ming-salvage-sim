"""Issue 系统的事件门闩求值与触发编排（L6）。落库业务实现已迁入 entities（ADR 0150 决定 8）：
财政加派 ming_sim.entities.fiscal.levy、暗渠撤销 entities.fiscal.covert_neutralize、
密令披露 entities.secret_order.disclosure、issue 写侧 entities.issue.records、事件终态写侧 entities.issue.event_terminal、开局 legacy entities.issue.legacy。

通过 bind_content() 注入 GameContent（取 EVENTS/SEED_EVENTS/EVENT_BY_ID）。
"""

from __future__ import annotations
from ming_sim.applier import parse_engine_payload_json

import json
import re
from typing import Dict, List, Optional

from ming_sim.applier import (
    RejectionCollector,
    atomic,
    mirror_rejections_after_commit,
)
from ming_sim.error_pack import rejections_jsonl_path
from ming_sim.constants import (
    REGION_SCORE_FIELDS, REGION_QUANTITY_FIELDS, REGION_TEXT_FIELDS,
    ARMY_SCORE_FIELDS, ARMY_QUANTITY_FIELDS, ARMY_TEXT_FIELDS, BUILDING_SCORE_FIELDS,
    BUILDING_QUANTITY_FIELDS, POWER_SCORE_FIELDS, POWER_TEXT_FIELDS,
    CHARACTER_TEXT_FIELDS, GATE_TABLES,
)
from ming_sim.content import GameContent
from ming_sim.db import (
    GameDB,
    _LEVERAGE_FACTIONS,
)
from ming_sim.exceptions import SettlementAbort
from ming_sim.models import Event, GameState
from ming_sim.participant_roster import project_execution_liability_parties

from ming_sim.settlement.preflight import _validate_strategic_foreign_node_outcome_targets

import ming_sim.entities.issue.records as issue_records

_content: Optional[GameContent] = None


# 给建筑/地区落库做 event 关联用的占位事件（issue 结案触发的副作用无真实 event）。


def bind_content(content: GameContent) -> None:
    global _content
    _validate_strategic_foreign_node_outcome_targets(content)
    _content = content


def _ctx() -> GameContent:
    if _content is None:
        raise RuntimeError("issues.bind_content() 未调用：GameContent 未注入。")
    return _content


def _event_issue_refs(db: GameDB) -> set:
    refs: set = set()
    for r in db.issues.read_event_issue_refs():
        if r["origin_ref"]:
            refs.add(r["origin_ref"])
    return refs


def _event_trigger_refs(db: GameDB) -> set:
    return set(_event_terminal_states(db))


def _event_terminal_states(db: GameDB) -> Dict[str, str]:
    states: Dict[str, str] = {}
    for r in db.issues.read_event_terminal_states():
        terminal_state = str(r["terminal_state"] or "")
        if r["event_id"] and terminal_state:
            states[str(r["event_id"])] = terminal_state
    return states


def _event_terminal_records(db: GameDB) -> Dict[str, Dict[str, str]]:
    """只读事件终态；财政不由历史批语重建或重放征收决定。"""
    records: Dict[str, Dict[str, str]] = {}
    for r in db.issues.read_event_terminal_records(()):
        terminal_state = str(r["terminal_state"] or "")
        if r["event_id"] and terminal_state:
            records[str(r["event_id"])] = {
                "terminal_state": terminal_state,
                "terminal_reason": str(r["terminal_reason"] or ""),
            }
    return records


FISCAL_LEVY_EVENT_CATEGORY = "fiscal_levy"
# #650/0089 明渠：下旨加派逐省累积账（万两/月，负额停征/蠲免、钳 ≥0）。
# 与 #649 饷率 seed 同址（settle._meta），restore 只读 DB 无损接续（P1）。


def list_fiscal_levy_petitions_due(
    state: GameState, db: GameDB,
) -> List[Dict[str, object]]:
    """#1891：本月可呈的请饷／议停事件（纯读，不写账）。

    交付对象是 #1843 既有月末世界段 run：过月模型读这份名单与当月军费材料，自行
    决定成不成陈情、要不要上疏。引擎只供事实，不代答（P6）。

    资格只在这里判一次：窗口开、门过、未过期、未终态。已呈待批（批红页上仍有该事件
    请旨行）不再重触发为首次事件。

    ``presentation_due`` 是**权限事实**而非措辞：首次到点、尚未呈过的应呈请
    （True）；已呈过、被留中的由大臣自决是否再上疏（False）。原事件、原疏与亲笔
    批语随 ``prior_petition`` 带回，供后续世界段读同一持久事实（#1891 读端闭环），
    代码不代它再顶一次旧疏。名单顺序就是交接键：世界段按这个顺序写请旨块，
    不回显事件 id（ADR 0115）。
    """
    awaiting = _fiscal_levy_petitions_awaiting_verdict(db)
    answered = _fiscal_levy_answered_petitions(db)
    due: List[Dict[str, object]] = []
    for ev in gather_fiscal_levy_petitions(state, db):
        if ev.id in awaiting:
            continue
        from ming_sim.entities.fiscal.levy import _fiscal_levy_require_labels
        _fiscal_levy_require_labels(ev, state)
        held = ev.id in answered
        due.append({
            "event_id": ev.id,
            "title": ev.title,
            "summary": ev.summary,
            "audiences": list(getattr(ev, "audiences", []) or []),
            "terminal_reason_labels": list(getattr(ev, "terminal_reason_labels", []) or []),
            "re_presentation": held,
            "presentation_due": not held,
            **({"prior_petition": answered[ev.id]} if held else {}),
        })
    return due


def _fiscal_levy_petitions_awaiting_verdict(db: GameDB) -> set[str]:
    """已呈上批红页、尚未裁定的饷率事件：其请旨行仍是 pending。

    请旨身份前缀真源 = month_chain；此处局部导入以免与月链成模块环。
    已答（decided，含留中）的行本回合留在盘面上作答复留痕，不算「待裁」——
    否则留中后该事件永不再回名单，大臣就再没有上疏的机会。
    """
    from ming_sim.month_chain import _LEVY_PETITION_PREFIX

    awaiting: set[str] = set()
    for row in db.issues.read_fiscal_levy_petitions_awaiting_verdict():
        event_id = str(row["event_id"] or "").strip()
        if event_id.startswith(_LEVY_PETITION_PREFIX):
            awaiting.add(event_id[len(_LEVY_PETITION_PREFIX):])
    return awaiting


def _fiscal_levy_answered_petitions(db: GameDB) -> Dict[str, Dict[str, object]]:
    """已呈未裁的旧疏与批语；只供世界材料，不授予当次裁断资格。

    与材料目录共读 record_event_petition_answer 的持久记录；本回合授权另读已答行。
    """
    metadata = {"event_id", "turn", "year", "period", "terminal_state", "terminal_reason", "petition"}
    return {
        str(row["event_id"]): {
            "title": str(row["petition"].get("title") or ""),
            "context": str(row["petition"].get("context") or ""),
            "rescript": {key: value for key, value in row.items() if key not in metadata},
        }
        for row in db.issues.list_event_petition_records()
        if not row["terminal_state"]
    }


_EVENT_GATE_KEY_RE = re.compile(r"^event\.([^.]+)\.(triggered|terminal_state|terminal_reason)$")


def _numeric_predicate_accepts(op: str, candidate: int, value: int) -> bool:
    if op == ">=":
        return candidate >= value
    if op == "<=":
        return candidate <= value
    if op == ">":
        return candidate > value
    if op == "<":
        return candidate < value
    if op == "==":
        return candidate == value
    return False


def _event_triggered_numeric_dependency_kind(op: str, value: int) -> str:
    """Classify event.<id>.triggered predicates over the boolean ledger domain {0, 1}."""
    accepts_false = _numeric_predicate_accepts(op, 0, value)
    accepts_true = _numeric_predicate_accepts(op, 1, value)
    if accepts_true and not accepts_false:
        return "positive"
    if accepts_false and not accepts_true:
        return "negative"
    if accepts_false and accepts_true:
        return "both"
    return "neither"


def _event_dependency_ids(ev: Event) -> set[str]:
    ids: set[str] = set()
    for key in (ev.trigger_gate or {}):
        m = _EVENT_GATE_KEY_RE.match(str(key))
        if m:
            ids.add(m.group(1))
    return ids


_EVENT_DEPENDENCY_GRAPH_VALIDATION_CACHE: set[tuple[tuple[str, tuple[str, ...]], ...]] = set()


def _validate_event_dependency_graph_acyclic(content: GameContent, state: GameState) -> None:
    raw_graph: Dict[str, set[str]] = {
        ev.id: _event_dependency_ids(ev)
        for ev in [*content.events, *content.seed_events]
        if getattr(ev, "id", "")
    }
    graph = {eid: {dep for dep in deps if dep in raw_graph} for eid, deps in raw_graph.items() if deps}
    cache_key = tuple(sorted((eid, tuple(sorted(deps))) for eid, deps in graph.items()))
    if cache_key in _EVENT_DEPENDENCY_GRAPH_VALIDATION_CACHE:
        return

    visiting: set[str] = set()
    visited: set[str] = set()
    stack: List[str] = []

    def dfs(eid: str) -> None:
        if eid in visiting:
            cycle = stack[stack.index(eid):] + [eid] if eid in stack else [eid, eid]
            raise SettlementAbort(
                f"事件链依赖存在环：{' -> '.join(cycle)}",
                turn=state.turn,
                stage="event_chain_config",
            )
        if eid in visited:
            return
        visiting.add(eid)
        stack.append(eid)
        for dep in sorted(graph.get(eid, set())):
            dfs(dep)
        stack.pop()
        visiting.remove(eid)
        visited.add(eid)

    for eid in sorted(graph):
        dfs(eid)
    _EVENT_DEPENDENCY_GRAPH_VALIDATION_CACHE.add(cache_key)


def _event_chain_impossible_reason(ev: Event, terminal_records: Dict[str, Dict[str, str]], state: GameState) -> str:
    allowed_states: Dict[str, set[str]] = {}
    forbidden_states: Dict[str, set[str]] = {}
    allowed_outcomes: Dict[str, set[str]] = {}
    forbidden_outcomes: Dict[str, set[str]] = {}

    def _format_values(values: set[str]) -> str:
        return "|".join(sorted(values))

    def allow_states(upstream_id: str, state_names: set[str], *, raw_key: object, raw_cond: str) -> None:
        if not state_names:
            return
        existing = allowed_states.get(upstream_id)
        if existing is None:
            allowed_states[upstream_id] = set(state_names)
            return
        narrowed = existing & state_names
        if not narrowed:
            raise SettlementAbort(
                "事件链正向终态门互相矛盾："
                f"{upstream_id} 已要求 {{{_format_values(existing)}}}，"
                f"又要求 {{{_format_values(state_names)}}}（{raw_key} {raw_cond}）",
                turn=state.turn,
                stage="event_chain_config",
            )
        allowed_states[upstream_id] = narrowed

    def allow_state(upstream_id: str, state_name: str, *, raw_key: object, raw_cond: str) -> None:
        allow_states(upstream_id, {state_name}, raw_key=raw_key, raw_cond=raw_cond)

    def allow_outcomes(upstream_id: str, outcomes: set[str], *, raw_key: object, raw_cond: str) -> None:
        if not outcomes:
            return
        existing = allowed_outcomes.get(upstream_id)
        if existing is None:
            allowed_outcomes[upstream_id] = set(outcomes)
            return
        narrowed = existing & outcomes
        if not narrowed:
            raise SettlementAbort(
                "事件链正向结局门互相矛盾："
                f"{upstream_id} 已要求 {{{_format_values(existing)}}}，"
                f"又要求 {{{_format_values(outcomes)}}}（{raw_key} {raw_cond}）",
                turn=state.turn,
                stage="event_chain_config",
            )
        allowed_outcomes[upstream_id] = narrowed

    def forbid_state(upstream_id: str, state_name: str) -> None:
        forbidden_states.setdefault(upstream_id, set()).add(state_name)

    for raw_key, raw_cond in (ev.trigger_gate or {}).items():
        m = _EVENT_GATE_KEY_RE.match(str(raw_key))
        if not m:
            continue
        upstream_id, field = m.group(1), m.group(2)
        cond = str(raw_cond).strip()
        if field == "triggered":
            num = re.match(r"^(>=|<=|>|<|==)\s*(-?\d+)$", cond)
            if not num:
                continue
            op, value = num.group(1), int(num.group(2))
            dependency_kind = _event_triggered_numeric_dependency_kind(op, value)
            if dependency_kind == "positive":
                allow_state(upstream_id, "triggered", raw_key=raw_key, raw_cond=cond)
            elif dependency_kind == "negative":
                forbid_state(upstream_id, "triggered")
            elif dependency_kind == "neither":
                raise SettlementAbort(
                    f"事件链 triggered 门在布尔域 {{0,1}} 上永不满足：{raw_key} {cond}",
                    turn=state.turn,
                    stage="event_chain_config",
                )
            continue
        text = re.match(r"^(==|!=|in=)\s*(.+)$", cond)
        if not text:
            continue
        op, value = text.group(1), text.group(2).strip()
        values = {part.strip() for part in value.split("|") if part.strip()}
        if field == "terminal_state":
            if op in ("==", "in="):
                allow_states(upstream_id, values, raw_key=raw_key, raw_cond=cond)
            elif op == "!=":
                forbidden_states.setdefault(upstream_id, set()).update(values)
        elif field == "terminal_reason":
            # Outcome labels are frozen only for triggered events; a positive outcome
            # predicate therefore implies terminal_state == triggered.
            if op in ("==", "in="):
                allow_state(upstream_id, "triggered", raw_key=raw_key, raw_cond=cond)
                allow_outcomes(upstream_id, values, raw_key=raw_key, raw_cond=cond)
            elif op == "!=":
                forbidden_outcomes.setdefault(upstream_id, set()).update(values)

    for upstream_id in sorted(_event_dependency_ids(ev)):
        record = terminal_records.get(upstream_id)
        if not record:
            continue
        state_val = record["terminal_state"]
        outcome = record["terminal_reason"]
        allowed = allowed_states.get(upstream_id, set())
        if allowed and state_val not in allowed:
            if allowed == {"triggered"}:
                return f"上游事件 {upstream_id} 已入非触发终态：{state_val}"
            return f"上游事件 {upstream_id} 终态不满足门：{state_val}"
        forbidden_states_for_upstream = forbidden_states.get(upstream_id, set())
        if state_val in forbidden_states_for_upstream:
            if forbidden_states_for_upstream == {"triggered"}:
                return f"上游事件 {upstream_id} 已触发"
            return f"上游事件 {upstream_id} 已入禁用终态：{state_val}"
        allowed_outcome_values = allowed_outcomes.get(upstream_id, set())
        if allowed_outcome_values and outcome and outcome not in allowed_outcome_values:
            return f"上游事件 {upstream_id} 已发其他结局：{outcome}"
        forbidden = forbidden_outcomes.get(upstream_id, set())
        if forbidden and state_val == "triggered" and outcome in forbidden:
            return f"上游事件 {upstream_id} 已发禁用结局：{outcome}"
    return ""


def _spawned_event_refs(db: GameDB) -> set:
    refs = _event_issue_refs(db)
    refs.update(_event_trigger_refs(db))
    return refs


def _event_window_open(ev: Event, state: GameState) -> bool:
    """Return True when the current date is inside an event's optional trigger window."""
    if ev.trigger_year > 0:
        if state.year < ev.trigger_year:
            return False
        if state.year == ev.trigger_year and ev.trigger_month > 0 and state.period < ev.trigger_month:
            return False
    if ev.open_window:
        return True
    if ev.trigger_end_year > 0:
        if state.year > ev.trigger_end_year:
            return False
        if state.year == ev.trigger_end_year and ev.trigger_end_month > 0 and state.period > ev.trigger_end_month:
            return False
    return True


def _event_outcome_label(raw_outcomes: object, event_id: str) -> str:
    if not isinstance(raw_outcomes, dict):
        return ""
    raw = raw_outcomes.get(event_id)
    if isinstance(raw, dict):
        raw = raw.get("结局") or raw.get("outcome") or raw.get("label")
    return str(raw or "").strip()


def _merge_first_event_outcome(
    current: Dict[str, object], incoming: object, event_id: str,
) -> list[dict[str, object]]:
    """信封只写入自己的 event_id。

    空归属、或键不属于本信封的非空结局，不写，并作为未归属声明交调用方拒收。
    同键首笔胜，后写不覆盖，也不算拒收；显式非法首笔留给闭集校验，不由后笔洗白。
    """
    unowned: list[dict[str, object]] = []
    if not isinstance(incoming, dict):
        return unowned
    eid = str(event_id or "").strip()
    for key, value in incoming.items():
        key_s = str(key).strip()
        if not eid or key_s != eid:
            if _event_outcome_label({key_s: value}, key_s):
                unowned.append({key_s: value})
            continue
        if not isinstance(current, dict) or eid in current:
            continue
        current[eid] = value
    return unowned


def gather_fiscal_levy_petitions(state: GameState, db: GameDB) -> List[Event]:
    """#1892 J5：三饷（category=fiscal_levy）到点请旨的候选——交既有世界段成陈情。

    亲裁权在皇帝，故这些事件**不进** gather_candidate_events（那里是交模型代选
    「是否发生」的人物事件池）。本函数只判「该不该呈皇帝」，判门与人物候选同一
    真源（窗口/前提门/已落终态）；不写终态、不代批。奏疏由世界段呈上，亲裁准驳
    当回合经 apply_petition_event_outcome 置定结局。留中不写终态，事项仍在本候选里。
    征收由下一月 pre_settle 的饷率通道按已落终态重算。
    """
    c = _ctx()
    spawned = _spawned_event_refs(db)
    petitions: List[Event] = []
    for ev in c.events:
        if getattr(ev, "category", "") != FISCAL_LEVY_EVENT_CATEGORY:
            continue
        if ev.id in spawned or ev.trigger_year <= 0:
            continue
        if _event_window_expired(ev, state) or not _event_window_open(ev, state):
            continue
        if not _gate_passed(ev.trigger_gate, state.metrics, db):
            continue
        petitions.append(ev)
    return petitions


def petition_outcome_is_admissible(
    state: GameState, db: GameDB, event_id: str, content: Optional[GameContent],
) -> bool:
    """该事件是否可由本回合的亲裁答复置定结局（#1892 亲裁语义落账）。

    资格只认本回合绑定原事件的已答请饷行，且终态仍空。
    历史留中答复是世界材料，不是当次亲裁授权。
    """
    eid = str(event_id or "").strip()
    if not eid:
        return False
    resolved = content if content is not None else _ctx()
    event = resolved.event_by_id.get(eid) if resolved is not None else None
    if event is None or getattr(event, "category", "") != FISCAL_LEVY_EVENT_CATEGORY:
        return False
    if db.issues.event_terminal_state(eid):
        return False
    return eid in _fiscal_levy_answered_event_ids(db, int(state.turn))


def _closed_outcome_labels(content: Optional[GameContent], event_id: str) -> frozenset[str]:
    """封闭结局集只认事件自身声明；写口与供料共用这一份，不另存枚举。"""
    ev = content.event_by_id.get(str(event_id or "").strip()) if content is not None else None
    raw = getattr(ev, "terminal_reason_labels", None) or []
    return frozenset(str(label).strip() for label in raw if str(label).strip())


def strategic_event_outcome_labels(event_id: str) -> frozenset[str]:
    """某战略事件在既有写口接受的闭合结局标签；空集 = 该事件不收 事件结局。

    供料侧（materials 候选事实）与落库侧共用这一份，读侧不另立标签表（#1893）。
    """
    from ming_sim.settlement.preflight import _is_strategic_foreign_node_event

    ev = _ctx().event_by_id.get(event_id)
    if ev is None or not _is_strategic_foreign_node_event(ev):
        return frozenset()
    return _closed_outcome_labels(_ctx(), event_id)


def _event_window_expired(ev: Event, state: GameState) -> bool:
    """Return True once the current date is past an event's explicit latest point."""
    if ev.open_window:
        return False
    if ev.trigger_end_year <= 0:
        return False
    if state.year > ev.trigger_end_year:
        return True
    if ev.trigger_end_month > 0 and state.year == ev.trigger_end_year and state.period > ev.trigger_end_month:
        return True
    return False


def _dead_person_core_subjects(ev: Event, db: GameDB) -> List[str]:
    dead: List[str] = []
    for name in getattr(ev, "person_core_subjects", []) or []:
        row = db.characters.field_row('status', str(name))
        if row is not None and str(row["status"] or "") == "dead":
            dead.append(str(name))
    return dead


def _person_core_avoided_reason(ev: Event, state: GameState, db: GameDB) -> str:
    subjects = [str(name) for name in (getattr(ev, "person_core_subjects", []) or []) if str(name)]
    if not subjects:
        return ""
    gate = ev.trigger_gate or {}
    subject_prefixes = tuple(f"character.{name}." for name in subjects)
    subject_gate = {
        key: cond
        for key, cond in gate.items()
        if any(str(key).startswith(prefix) for prefix in subject_prefixes)
    }
    if not subject_gate:
        return ""
    if _gate_passed(subject_gate, state.metrics, db):
        return ""
    return f"人物核心前提已被玩家处理：{', '.join(subjects)}"


_GATE_AGG_FUNCS = {
    "max": max,
    "min": min,
    "sum": sum,
    "avg": lambda xs: sum(xs) / max(1, len(xs)),
}


_CHARACTER_NUMERIC_GATE_FIELDS = (
    "loyalty",
    "ability",
    "integrity",
    "courage",
    "birth_year",
    "historical_death_year",
    "historical_death_month",
    "debut_year",
    "debut_month",
    "status_changed_turn",
)
_GATE_NUMERIC_SQL_FIELDS = {
    "region": set(REGION_SCORE_FIELDS + REGION_QUANTITY_FIELDS + ("city_level", "cannon")),
    "army": set(ARMY_SCORE_FIELDS + ARMY_QUANTITY_FIELDS),
    "building": set(BUILDING_SCORE_FIELDS + BUILDING_QUANTITY_FIELDS),
    "power": set(POWER_SCORE_FIELDS),
    "faction": {"satisfaction", "leverage"},
    "character": set(_CHARACTER_NUMERIC_GATE_FIELDS),
    "class": {"population", "satisfaction", "leverage"},
    "event": {"triggered"},
}
_GATE_TEXT_SQL_FIELDS = {
    "region": set(REGION_TEXT_FIELDS),
    "army": set(ARMY_TEXT_FIELDS),
    "power": set(POWER_TEXT_FIELDS),
    "character": set(CHARACTER_TEXT_FIELDS),
    "event": {"terminal_state", "terminal_reason"},
}
_GATE_SQL_FIELDS = {
    table: set(fields) | set(_GATE_TEXT_SQL_FIELDS.get(table, set()))
    for table, fields in _GATE_NUMERIC_SQL_FIELDS.items()
}
for _table, _fields in _GATE_TEXT_SQL_FIELDS.items():
    _GATE_SQL_FIELDS.setdefault(_table, set()).update(_fields)


def _gate_sql_field(table: str, field: str, key: str, *, kind: str) -> str:
    allowed = _GATE_SQL_FIELDS.get(table)
    if allowed is None or field not in allowed:
        raise ValueError(f"trigger_gate key「{key}」字段无效：{table}.{field}")
    typed_allowed = _GATE_NUMERIC_SQL_FIELDS if kind == "numeric" else _GATE_TEXT_SQL_FIELDS
    if field not in typed_allowed.get(table, set()):
        label = "非数值" if kind == "numeric" else "非文本"
        raise ValueError(f"trigger_gate key「{key}」字段{label}（比较类型不匹配）：{table}.{field}")
    return field


def _eval_gate_key(key: str, metrics: Dict[str, int], db: GameDB) -> Optional[float]:
    """把 gate key 解析成一个数值。形式：
      - 'metric_name'                           → metrics[key]
      - 'region.<id>.<field>'                   → regions 表
      - 'region.<id1>|<id2>|.<field>.<agg>'     → 多省聚合 (max/min/avg/sum)
      - 'army.<id>.<field>' / 多军 + agg
      - 'building.<id>.<field>' / 多建筑 + agg
      - 'power.<id>.<field>' / 多 + agg
      - 'character.<name>.<field>' / 多人物 + agg
      - 'event.<id>.terminal_state'               → event_triggers 表文本门专用
      - 'class.<name>.<field>'                  → classes 表全国汇总 (region_id='')
      - 'class.<name>@<region>.<field>'         → classes 表省级
      - 'class.<name>@<r1>|<r2>|.<field>.<agg>' → 多省同阶级聚合
      - 'event.<id>.triggered'                  → event_triggers 账，已发=1 未发=0
    解析失败/数据缺失返回 None（gate 视为不通过，由调用方处理）。
    """
    if "." not in key:
        if key in metrics:
            return int(metrics[key])
        return None
    parts = key.split(".")
    table = parts[0]
    if table not in GATE_TABLES:
        return None
    # 末段可能是 agg，先抽出
    agg = None
    if parts[-1] in _GATE_AGG_FUNCS:
        agg = parts[-1]
        parts = parts[:-1]
    if len(parts) < 3:
        return None
    field = parts[-1]
    id_segment = ".".join(parts[1:-1])
    field = _gate_sql_field(table, field, key, kind="numeric")
    if table == "class" and "@" in id_segment and "|" in id_segment.split("@", 1)[1]:
        # 简写：class.<name>@<r1>|<r2>|<r3>.<field> → 展开成 [name@r1, name@r2, name@r3]
        cname, rest = id_segment.split("@", 1)
        ids = [f"{cname}@{r}" for r in rest.split("|") if r]
    else:
        ids = id_segment.split("|") if "|" in id_segment else [id_segment]
        ids = [x for x in ids if x]
    if not ids:
        return None
    # class 表的 id 是 name 或 name@region；其它表 id 就是行 id
    values: List[float] = []
    for cid in ids:
        row = None
        try:
            if table == "event":
                if cid not in db.content.event_by_id:
                    return None
                values.append(1 if db.issues.has_event_terminal_state(cid, "triggered") else 0)
                continue
            if table == "class":
                cname, rid = cid.split("@", 1) if "@" in cid else (cid, "")
                row = db.classes.field_row(field, cname, rid)
            else:
                row = {
                    "region": db.regions,
                    "army": db.armies,
                    "building": db.buildings,
                    "power": db.powers,
                    "faction": db.factions,
                    "character": db.characters,
                }[table].field_row(field, cid)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"gate key 持久读失败：{key}") from exc
        if row is None:
            return None
        # NULL is the documented absent gate value; other conversion failures
        # belong to the stored value, not to a fabricated content error.
        if row[0] is None:
            return None
        values.append(float(row[0]))
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    if agg is None:
        # 多 id 但没指明聚合 → 默认 min（最严苛，要全部满足）
        agg = "min"
    return _GATE_AGG_FUNCS[agg](values)


def _eval_gate_key_str(key: str, db: GameDB) -> Optional[str]:
    """取一个文本型字段值（如 region.<id>.controlled_by → 'ming'/'houjin'）。
    仅支持单 id 的 region/army/power/character/event 文本字段；解析失败返回 None。
    """
    parts = key.split(".")
    if len(parts) != 3:
        return None
    table, cid, field = parts
    field = _gate_sql_field(table, field, key, kind="text")
    if table == "event":
        row = db.issues.read_eval_gate_key_str_owned((cid,), field).fetchone()
    else:
        store = {
            "region": db.regions, "army": db.armies,
            "power": db.powers, "character": db.characters,
        }.get(table)
        if store is None:
            return None
        row = store.field_row(field, cid)
    if row is None:
        return None
    return str(row[0])


def _gate_passed(gate: Dict[str, str], metrics: Dict[str, int], db: GameDB) -> bool:
    """trigger_gate 全部条件满足才返回 True。条件形如 '<=240'（数值）或 '==ming'（文本相等）。
    key 形式见 _eval_gate_key。gate=None（content JSON 显式 null）视同空门、恒过，不 .items()
    AttributeError 崩候选收集（PR#107 gemini；集中守 None，seed/历史两分支共用此函数同得保护）。
    """
    for key, cond in (gate or {}).items():
        cond = str(cond).strip()  # 非字符串条件值(JSON 漏引号写成 60/True)先 str 强转，不 .strip() 崩（PR#107 gemini）
        # 文本相等 / 枚举：==<word> / !=<word> / in=a|b（RHS 非纯数字）
        sm = re.match(r"^(==|!=|in=)\s*(.+)$", cond)
        if sm and (sm.group(1) == "in=" or not re.match(r"^-?\d+$", sm.group(2).strip())):
            sop, sval = sm.group(1), sm.group(2).strip()
            cur = _eval_gate_key_str(key, db)
            if cur is None:
                return False
            if sop == "==" and cur != sval:
                return False
            if sop == "!=" and cur == sval:
                return False
            if sop == "in=" and cur not in {part.strip() for part in sval.split("|") if part.strip()}:
                return False
            continue
        m = re.match(r"^(>=|<=|>|<|==)\s*(-?\d+)$", cond)
        if not m:
            return False
        op, num = m.group(1), int(m.group(2))
        val = _eval_gate_key(key, metrics, db)
        if val is None:
            return False
        if op == ">=" and not val >= num:
            return False
        if op == "<=" and not val <= num:
            return False
        if op == ">" and not val > num:
            return False
        if op == "<" and not val < num:
            return False
        if op == "==" and not val == num:
            return False
    return True


def gather_impeachment_surge_candidates(state: GameState, db: GameDB) -> List[Dict[str, object]]:
    """Project canonical dynamic candidates from transformed dossier facts.

    Other disaster legs deliberately have no adapter until their owning producers
    provide a durable occurrence and responsibility interface.
    """
    facts = db.build_faction_denunciation_facts()
    situations = {
        str(item.get("faction") or ""): item
        for item in facts.get("faction_situations", [])
        if isinstance(item, dict)
    }
    personas_by_faction: Dict[str, List[Dict[str, object]]] = {}
    for item in facts.get("character_personas", []):
        if isinstance(item, dict):
            personas_by_faction.setdefault(str(item.get("faction") or ""), []).append(item)

    rows = db.dossiers.read_gather_impeachment_surge_candidates(
        (max(0, int(state.turn) - 1), int(state.turn))
    )
    candidates: List[Dict[str, object]] = []
    for row in rows:
        did = int(row["id"])
        # #622/#1260 单源：仅有旨外 durable 的变形才构成 deformation_exposure。
        if not db.dossier_has_beyond_intent(did):
            continue
        roster = json.loads(str(row["participant_roster"] or "[]"))
        if not isinstance(roster, list) or any(not isinstance(item, dict) for item in roster):
            raise ValueError("持久案卷参与人须为对象列表")
        if not roster:
            continue
        participant_ids = [
            str(item.get("character_id") or "").strip()
            for item in roster if isinstance(item, dict) and str(item.get("character_id") or "").strip()
        ]
        if len(participant_ids) != len(roster) or not participant_ids:
            raise ValueError(f"案卷#{did} participant_roster 含无效成员")
        liability = project_execution_liability_parties(roster)
        responsible_ids = [
            str(item.get("character_id") or "").strip() for item in liability
            if str(item.get("character_id") or "").strip()
        ]
        if not responsible_ids:
            continue
        # 存在门只看责任集；知情/协办离场不得 any() 否决整卷。
        placeholders = ",".join("?" for _ in responsible_ids)
        chars = db.characters.named_status_rows(responsible_ids)
        char_by_name = {str(item["name"]): item for item in chars}
        if any(
            name not in char_by_name
            or str(char_by_name[name]["status"] or "") != "active"
            or not str(char_by_name[name]["faction"] or "").strip()
            for name in responsible_ids
        ):
            continue
        responsible_factions = list(dict.fromkeys(
            str(char_by_name[name]["faction"]) for name in responsible_ids
        ))
        # 闭集：在朝 participant ∪ 在朝 responsible（含仅 delegator_id 连坐）。
        union_ids = list(dict.fromkeys([*participant_ids, *responsible_ids]))
        missing = [name for name in union_ids if name not in char_by_name]
        if missing:
            missing_ph = ",".join("?" for _ in missing)
            for item in db.characters.named_status_rows(missing):
                char_by_name[str(item["name"])] = item
        eligible_target_ids = [
            name for name in union_ids
            if name in char_by_name
            and str(char_by_name[name]["status"] or "") == "active"
            and str(char_by_name[name]["faction"] or "").strip()
        ]
        if not eligible_target_ids:
            continue
        fork_state = db.read_dossier_fork_state(did)
        beyond_intent_effects = [
            dict(effect)
            for effect in db.list_dossier_durable_effects(did)
            if bool(effect.get("beyond_intent"))
        ]
        origin_ref = f"commitment:{did}:deformation_exposure"
        for faction in sorted(_LEVERAGE_FACTIONS):
            if (
                faction in responsible_factions
                or db.factions.faction_leverage(faction) < 60
            ):
                continue
            situation = situations.get(faction)
            personas = personas_by_faction.get(faction, [])
            if not situation or not personas:
                continue
            if db.issues.read_gather_impeachment_surge_candidates(
                (origin_ref, faction)
            ):
                continue
            candidate_id = f"impeachment_surge:{origin_ref}:{faction}"
            decree_text = str(row["decree_text"] or "")
            execution_note = str(row["execution_note"] or "")
            candidates.append({
                "id": candidate_id,
                "origin_kind": "impeachment_surge",
                "origin_ref": origin_ref,
                "source_kind": "deformation_exposure",
                "occurred_turn": int(row["closed_turn"]),
                "faction_id": faction,
                "faction_persona": {
                    "faction_situations": [dict(situation)],
                    "character_personas": [dict(item) for item in personas],
                },
                "eligible_target_ids": eligible_target_ids,
                "participant_ids": participant_ids,
                "responsible_person_ids": responsible_ids,
                "responsible_faction_ids": responsible_factions,
                "dossier_id": did,
                "decree_text": str(row["decree_text"] or ""),
                "execution_note": str(row["execution_note"] or ""),
                "execution_outcome": str(row["execution_outcome"] or "").strip(),
                "beyond_intent": True,
                "reported_bands": list(fork_state.get("reported_bands") or []),
                "actual_effect_count": int(fork_state.get("actual_effect_count") or 0),
                "beyond_intent_effects": beyond_intent_effects,
            })
    return candidates


def gather_candidate_events(state: GameState, db: GameDB) -> List[Event]:
    """程序筛选：历史锚定事件按 trigger 时间到点、seed 情势按 trigger_gate 达标，
    都排除已触发过的。返回的候选清单交推演 agent 因果判定是否真触发。

    #1892/#1893 分工：进本清单 = 交模型在月末世界段里挑的人物事件。三饷
    （``fiscal_levy``）是皇帝亲裁的加派决策，由答后转译／``apply_petition_event_outcome``
    落 ``事件结局``，其加不加不是模型能代批的事，故永不入人物候选（ADR 0020）。
    """
    c = _ctx()
    spawned = _spawned_event_refs(db)
    candidates: List[Event] = []
    # 历史锚定 EVENTS：到点（含错过补出）即进候选
    for ev in c.events:
        if ev.id in spawned or ev.trigger_year <= 0:
            continue
        if _is_fiscal_levy_event(ev):
            continue
        if _event_window_expired(ev, state):
            continue
        if ev.auto_trigger:
            continue
        dead_subjects = _dead_person_core_subjects(ev, db)
        if dead_subjects:
            continue
        if not _event_window_open(ev, state):
            continue
        # 历史事件带结构化前提门时也须达标（与 seed 情势同门）：纯日历窗口会放行前提已不成立
        # 的事件误触发（#12 毛文龙：已安抚/效顺仍按年月弹出）。无 gate（空 dict）→ 恒过、行为不变。
        if not _gate_passed(ev.trigger_gate, state.metrics, db):
            avoided_reason = _person_core_avoided_reason(ev, state, db)
            if avoided_reason:
                continue
            continue
        candidates.append(ev)
    # seed 情势：trigger_gate 阈值达标即进候选
    for ev in c.seed_events:
        if ev.id in spawned:
            continue
        if _is_fiscal_levy_event(ev):
            continue
        if _event_window_expired(ev, state):
            continue
        # auto_trigger 事件只能由程序硬触发，绝不进 LLM 候选池
        if ev.auto_trigger:
            continue
        if not _event_window_open(ev, state):
            continue
        if _gate_passed(ev.trigger_gate, state.metrics, db):
            candidates.append(ev)
    return candidates


def auto_trigger_seed_issues(state: GameState, db: GameDB) -> List[Dict[str, object]]:
    """程序硬触发：seed_events 中标了 auto_trigger 的，trigger_gate 达标即由程序直接
    立 issue，绕过 LLM 因果判定（不进候选池等 extractor 决定）。event_to_issue 自带去重，
    已触发过返回 None 自动跳过。返回本回合硬触发的清单（供日志/邸报告知）。

    放在结算链 simulator 之前调用，使硬立的 issue 当回合即进盘面、被邸报叙述。"""
    collector = RejectionCollector()
    with atomic(db):
        triggered = issue_records.auto_trigger_seed_issues_in_atomic(state, db, collector)
        collector.flush_to_db(db)
    mirror_rejections_after_commit(db, collector, rejections_jsonl_path)
    return triggered


# 离散时长档：LLM 只能给这几档（防乱填）；映射到月。

# 月固定收支项的合法账户 / 方向白名单（fiscal_creates 枚举守门，集中一处；
# applier 是唯一的枚举守门（cleaner 只做 direction 同义词映射等无损规范化,cmr S3 r2）。


# 校验「二级非 dict 会让 apply 在**逐 entity 写 DB 的中途崩**,留下部分已写 + 回合照推 = 半落库」
# 的字段。这三者 apply 都逐项 UPDATE/INSERT,前面的 entity 先落库、坏的 entity 崩:
#   - region_delta / army_delta:apply 裸调,崩直接抛穿;
#   - power_updates:落库编排器虽裹 try/except,但只接住异常不回滚——前面已写的 power
#     行仍被后续 record_log/save_turn 提交 = 半落库(CMR R2 codex)。prompt 里 power_updates 恒为
#     嵌套 dict,无扁平标量形态,故二级非 dict = 真畸形,校验前置拦截正确。
# **不**列入（交给各自 adapter 按契约处理）:faction_delta 吃旧扁平 int
# {"阉党": -10}（prompt 允许、合法）；class_delta 的扁平 item 不合法，由 adapter 逐项
# `invalid_enum` 拒收（#564），而非 validate 层当 nested-dict shape 拒收。


FISCAL_LEVY_RESCRIPT_SOURCE = "fiscal_levy_rescript"

def _is_fiscal_levy_event(ev: object) -> bool:
    """category=fiscal_levy。结局不走候选池、硬触发或通用终态通道。"""
    return getattr(ev, "category", "") == FISCAL_LEVY_EVENT_CATEGORY

def _is_fiscal_levy_petition_event(ev: Event) -> bool:
    """#1891：交 #1847 请旨、结局由御批经转译置定的三饷请饷／议停事件。

    与战略事件同一结局声明通道（事件结局 + 事件账唯一写口），只是资格门不同：
    战略事件走 event_pool 候选与 trigger_gate；请饷／议停走本月交接的 petition-due
    名单，且此刻必须「已呈待裁或已答未裁」——没呈过的没有御批可译。
    """
    return (
        _is_fiscal_levy_event(ev)
        and bool(getattr(ev, "terminal_reason_labels", None))
    )

def _fiscal_levy_answered_rows(db: GameDB, turn: int) -> List[Dict[str, object]]:
    """本段已答的请饷／议停行：真实事件 id 与已落原批语。资格的唯一读口。

    资格＝该回合批红页上已答（decided，含留中）且带请饷前缀的行。呈过而未答、
    或上一段的旧留中行，不在此列。前缀真源 = month_chain；此处局部导入以免成环。
    """
    from ming_sim.month_chain import _LEVY_PETITION_PREFIX

    rows: List[Dict[str, object]] = []
    for row in db.issues.read_fiscal_levy_answered_rows((int(turn),)):
        event_id = str(row["event_id"] or "")
        if not event_id.startswith(_LEVY_PETITION_PREFIX):
            continue
        choice = parse_engine_payload_json(
            row["choice_json"],
        )
        rows.append({
            "event_id": event_id[len(_LEVY_PETITION_PREFIX):],
            "rescript": choice,
        })
    return rows

def _fiscal_levy_answered_event_ids(db: GameDB, turn: int) -> set[str]:
    """本段已答复的请饷／议停事件真实 id——结局声明的唯一资格门。

    行来自 ``_fiscal_levy_answered_rows``。转译供料名单由同一行派生。
    """
    return {str(row["event_id"]) for row in _fiscal_levy_answered_rows(db, turn)}
