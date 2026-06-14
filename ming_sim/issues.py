"""Issue 系统：候选事件、issue 立项/推进/结案、tracker 输出落地、inertia 漂移。L6。

通过 bind_content() 注入 GameContent（取 EVENTS/SEED_EVENTS/EVENT_BY_ID）。
"""

from __future__ import annotations

import json
import re
import sqlite3
from typing import Any, Dict, List, Optional

from ming_sim.constants import (
    TURN_UNIT, REGION_SCORE_FIELDS, ARMY_SCORE_FIELDS, FISCAL_SCORE_FIELDS,
    REGION_FIELD_ALIASES, ARMY_FIELD_ALIASES,
)
from ming_sim.content import GameContent
from ming_sim.context import victory_status
from ming_sim.db import GameDB, infer_office_type_from_office, normalize_office
from ming_sim.flows import (
    ISSUE_METRIC_KEYS,
    ISSUE_METRIC_LOCK_CAPS,
    _apply_class_dict,
    _apply_economy_list,
    _apply_faction_dict,
    _apply_metric_dict,
)
from ming_sim.models import Event, GameState
from ming_sim.person_archive_contract import (
    PERSON_ALLEGIANCE_CHANGE_WAYS,
    PERSON_IDENTITY_TITLES,
    normalize_reason_code,
    resolve_person_transition,
)
from ming_sim.person_delta_adapter import normalize_person_changes
from ming_sim.token_stats import tlog

_content: Optional[GameContent] = None

# 给建筑/地区落库做 event 关联用的占位事件（issue 结案触发的副作用无真实 event）。
_ISSUE_PSEUDO_EVENT = Event(
    id="issue_resolution", title="局势结案", kind="月末", summary="",
    urgency=0, severity=0, credibility=100, interests=[], audiences=[],
)


def bind_content(content: GameContent) -> None:
    global _content
    _content = content


def _ctx() -> GameContent:
    if _content is None:
        raise RuntimeError("issues.bind_content() 未调用：GameContent 未注入。")
    return _content


def _apply_issue_buildings(
    db: GameDB,
    state: GameState,
    ops: object,
    pseudo_event: Event,
    reason: str,
) -> List[Dict[str, object]]:
    """落地 issue effect 里的 buildings 段：建筑随局势结案而新建/改数值/废止。

    每项 op 一个 dict，`action` ∈ create/modify/remove：
      - create：`region_id`/`name`/`category` 必填，其余可选（level/condition/maintenance/risk/output_metric/output_amount/status）
      - modify：`building_id` 必填 + 增量字段（走 apply_building_deltas）
      - remove：`building_id` 必填
    建筑的新建/变更唯一入口——不存在顶层 building_delta/new_buildings。
    """
    applied: List[Dict[str, object]] = []
    if not isinstance(ops, list):
        return applied
    for op in ops:
        if not isinstance(op, dict):
            continue
        action = str(op.get("action") or "").lower()
        try:
            if action == "create":
                bid = db.add_building(
                    state,
                    region_id=str(op.get("region_id") or ""),
                    name=str(op.get("name") or ""),
                    category=str(op.get("category") or ""),
                    level=int(op.get("level", 1)),
                    condition=int(op.get("condition", 60)),
                    maintenance=int(op.get("maintenance", 0)),
                    risk=int(op.get("risk", 30)),
                    output_metric=str(op.get("output_metric") or ""),
                    output_amount=int(op.get("output_amount", 0)),
                    status=str(op.get("status") or ""),
                    origin="issue",
                )
                applied.append({"action": "create", "building_id": bid,
                                 "name": str(op.get("name") or "")})
            elif action == "modify":
                bid = str(op.get("building_id") or "")
                fields = {k: v for k, v in op.items()
                          if k not in ("action", "building_id")}
                fields.setdefault("reason", reason)
                ch = db.apply_building_deltas(state, pseudo_event, None, "档房", {bid: fields})
                applied.append({"action": "modify", "building_id": bid, "changes": ch})
            elif action == "remove":
                bid = str(op.get("building_id") or "")
                ok = db.remove_building(state, bid, reason=reason)
                applied.append({"action": "remove", "building_id": bid, "removed": ok})
            else:
                print(f"[WARN] issue effect buildings: action 非法 '{action}'，跳过。")
        except Exception as exc:
            print(f"[WARN] issue effect buildings 落库失败：{exc}；op={op}")
    return applied


def issue_to_payload(row: sqlite3.Row, recent_advances: List[sqlite3.Row]) -> Dict[str, object]:
    """喂给推演 agent 的事项精简视图：状态、进度、效果、最近一次推进。"""
    keys = row.keys() if hasattr(row, "keys") else []
    resolve_cond = row["resolve_condition"] if "resolve_condition" in keys else ""
    fail_cond = row["fail_condition"] if "fail_condition" in keys else ""
    return {
        "issue_id": int(row["id"]),
        "kind": row["kind"],
        "title": row["title"],
        "状态": row["stage_text"],
        "进度": int(row["bar_value"]),
        "局势走向": int(row["inertia"]),
        f"当前每{TURN_UNIT}效果": json.loads(row["ongoing_effects"] or "{}"),
        "失败效果": json.loads(row["effect_on_fail"] or "{}"),
        "成功效果": json.loads(row["effect_on_resolve"] or "{}"),
        "结案条件": resolve_cond or "(未填)",
        "失败条件": fail_cond or "(未填)",
        "cancellable": row["cancellable"],
        f"上{TURN_UNIT}推进": (
            {
                "delta_bar": int(recent_advances[0]["delta_bar"]),
                "narrative": recent_advances[0]["narrative"],
            }
            if recent_advances else None
        ),
    }


def _spawned_event_refs(db: GameDB) -> set:
    refs: set = set()
    for r in db.conn.execute("SELECT origin_ref FROM issues WHERE origin_kind='event_pool'").fetchall():
        if r["origin_ref"]:
            refs.add(r["origin_ref"])
    for r in db.conn.execute("SELECT event_id FROM event_triggers").fetchall():
        if r["event_id"]:
            refs.add(r["event_id"])
    return refs


def _event_window_open(ev: Event, state: GameState) -> bool:
    """Return True when the current date is inside an event's optional trigger window."""
    if ev.trigger_year > 0:
        if state.year < ev.trigger_year:
            return False
        if state.year == ev.trigger_year and ev.trigger_month > 0 and state.period < ev.trigger_month:
            return False
    if ev.trigger_end_year > 0:
        if state.year > ev.trigger_end_year:
            return False
        if state.year == ev.trigger_end_year and ev.trigger_end_month > 0 and state.period > ev.trigger_end_month:
            return False
    return True


_GATE_AGG_FUNCS = {
    "max": max,
    "min": min,
    "sum": sum,
    "avg": lambda xs: sum(xs) // max(1, len(xs)),
}


def _eval_gate_key(key: str, metrics: Dict[str, int], db: GameDB) -> Optional[int]:
    """把 gate key 解析成一个 int 值。形式：
      - 'metric_name'                           → metrics[key]
      - 'region.<id>.<field>'                   → regions 表
      - 'region.<id1>|<id2>|.<field>.<agg>'     → 多省聚合 (max/min/avg/sum)
      - 'army.<id>.<field>' / 多军 + agg
      - 'building.<id>.<field>' / 多建筑 + agg
      - 'power.<id>.<field>' / 多 + agg
      - 'class.<name>.<field>'                  → classes 表全国汇总 (region_id='')
      - 'class.<name>@<region>.<field>'         → classes 表省级
      - 'class.<name>@<r1>|<r2>|.<field>.<agg>' → 多省同阶级聚合
    解析失败/数据缺失返回 None（gate 视为不通过，由调用方处理）。
    """
    if "." not in key:
        if key in metrics:
            return int(metrics[key])
        return None
    parts = key.split(".")
    table = parts[0]
    if table not in ("region", "army", "building", "power", "class", "faction"):
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
    values: List[int] = []
    for cid in ids:
        row = None
        if table == "region":
            row = db.conn.execute(f"SELECT {field} FROM regions WHERE id = ?", (cid,)).fetchone()
        elif table == "army":
            row = db.conn.execute(f"SELECT {field} FROM armies WHERE id = ?", (cid,)).fetchone()
        elif table == "building":
            row = db.conn.execute(f"SELECT {field} FROM buildings WHERE id = ?", (cid,)).fetchone()
        elif table == "power":
            row = db.conn.execute(f"SELECT {field} FROM powers WHERE id = ?", (cid,)).fetchone()
        elif table == "faction":
            # factions 表主键是 name（中文，如 阉党），field 取 leverage/satisfaction
            row = db.conn.execute(f"SELECT {field} FROM factions WHERE name = ?", (cid,)).fetchone()
        elif table == "class":
            if "@" in cid:
                cname, rid = cid.split("@", 1)
            else:
                cname, rid = cid, ""
            row = db.conn.execute(
                f"SELECT {field} FROM classes WHERE name = ? AND region_id = ?",
                (cname, rid),
            ).fetchone()
        if row is None:
            return None
        try:
            values.append(int(row[0]))
        except (TypeError, ValueError):
            return None
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
    仅支持单 id 的 region/army/power 文本字段；解析失败返回 None。
    """
    parts = key.split(".")
    if len(parts) != 3:
        return None
    table, cid, field = parts
    sql = {
        "region": f"SELECT {field} FROM regions WHERE id = ?",
        "army": f"SELECT {field} FROM armies WHERE id = ?",
        "power": f"SELECT {field} FROM powers WHERE id = ?",
    }.get(table)
    if sql is None:
        return None
    row = db.conn.execute(sql, (cid,)).fetchone()
    if row is None:
        return None
    return str(row[0])


def _gate_passed(gate: Dict[str, str], metrics: Dict[str, int], db: GameDB) -> bool:
    """trigger_gate 全部条件满足才返回 True。条件形如 '<=240'（数值）或 '==ming'（文本相等）。
    key 形式见 _eval_gate_key。
    """
    for key, cond in gate.items():
        cond = cond.strip()
        # 文本相等：==<word> / !=<word>（RHS 非纯数字）
        sm = re.match(r"^(==|!=)\s*(.+)$", cond)
        if sm and not re.match(r"^-?\d+$", sm.group(2).strip()):
            sop, sval = sm.group(1), sm.group(2).strip()
            cur = _eval_gate_key_str(key, db)
            if cur is None:
                return False
            if sop == "==" and cur != sval:
                return False
            if sop == "!=" and cur == sval:
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


def gather_candidate_events(state: GameState, db: GameDB) -> List[Event]:
    """程序筛选：历史锚定事件按 trigger 时间到点、seed 情势按 trigger_gate 达标，
    都排除已触发过的。返回的候选清单交推演 agent 因果判定是否真触发。"""
    c = _ctx()
    spawned = _spawned_event_refs(db)
    candidates: List[Event] = []
    # 历史锚定 EVENTS：到点（含错过补出）即进候选
    for ev in c.events:
        if ev.id in spawned or ev.trigger_year <= 0:
            continue
        if not _event_window_open(ev, state):
            continue
        # 历史事件带结构化前提门时也须达标（与 seed 情势同门）：纯日历窗口会放行前提已不成立
        # 的事件误触发（#12 毛文龙：已安抚/效顺仍按年月弹出）。无 gate（空 dict）→ 恒过、行为不变。
        if not _gate_passed(ev.trigger_gate, state.metrics, db):
            continue
        candidates.append(ev)
    # seed 情势：trigger_gate 阈值达标即进候选
    for ev in c.seed_events:
        if ev.id in spawned:
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
    c = _ctx()
    triggered: List[Dict[str, object]] = []
    for ev in c.seed_events:
        if not ev.auto_trigger:
            continue
        # trigger_gate 为空 = 开局即立的局势，只由 seed_opening_crises 立一次，绝不在此重立。
        # （空 gate 会被 _gate_passed 判为恒真，必须显式排除，否则每回合都试图重立。）
        if not ev.trigger_gate:
            continue
        if not _event_window_open(ev, state):
            continue
        if not _gate_passed(ev.trigger_gate, state.metrics, db):
            continue
        if ev.event_type != "situation":
            # 非 situation（node/ending）不转 issue，仅记触发避免重复
            if db.find_any_issue_by_origin("event_pool", ev.id) is None:
                db.mark_event_triggered(state, ev.id)
                triggered.append({"id": ev.id, "title": ev.title, "kind": ev.event_type})
            continue
        issue_id = event_to_issue(db, state, ev)
        if issue_id is not None:
            triggered.append({"id": ev.id, "title": ev.title, "issue_id": issue_id})
            print(f"[AUTO-TRIGGER] gate 达标硬立项 #{issue_id} {ev.title}（{ev.trigger_gate}）")
    return triggered


def _bar_ascii(value: int, width: int = 20) -> str:
    value = max(0, min(100, int(value)))
    pos = int(round(value / 100 * (width - 1)))
    return "●" + ("━" * pos) + "○" + ("━" * (width - 1 - pos))


def _format_issue_ongoing(ongoing_raw: str) -> str:
    """简短描述每月固定影响。"""
    try:
        eff = json.loads(ongoing_raw or "{}")
    except Exception:
        return ""
    parts: List[str] = []
    metrics = eff.get("metrics") or {}
    for key, val in metrics.items():
        if isinstance(val, (int, float)) and val:
            parts.append(f"{key}{'+' if val > 0 else ''}{int(val)}")
    for econ in eff.get("economy") or []:
        if isinstance(econ, dict):
            delta = econ.get("delta")
            acc = econ.get("account")
            if isinstance(delta, (int, float)) and delta and acc:
                parts.append(f"{acc}{'+' if delta > 0 else ''}{int(delta)}万")
    return "、".join(parts)


def _format_inertia(inertia: int) -> str:
    if inertia > 0:
        return f"自然推进 +{inertia}/{TURN_UNIT}"
    if inertia < 0:
        return f"自然恶化 {inertia}/{TURN_UNIT}"
    return "势均力敌"


def show_active_issues(db: GameDB) -> None:
    issues = db.list_active_issues()
    if not issues:
        return
    initiatives = [i for i in issues if i["kind"] == "initiative"]
    situations = [i for i in issues if i["kind"] == "situation"][:12]
    print(f"─── 待办事项 (系统 {len(situations)}/12  玩家 {len(initiatives)}/10) ───")

    def _print_row(row, label: str) -> None:
        bar = _bar_ascii(int(row["bar_value"]))
        print(f"{label} #{row['id']} {row['title']}")
        print(f"  {row['bar_bad_meaning']:6s} {bar} {row['bar_good_meaning']:6s}  bar={int(row['bar_value']):3d}  {row['stage_text']}")
        inertia = int(row["inertia"])
        ongoing_txt = _format_issue_ongoing(row["ongoing_effects"] or "{}")
        line_parts = [_format_inertia(inertia)]
        if ongoing_txt:
            line_parts.append(f"每{TURN_UNIT}固定：{ongoing_txt}")
        print(f"  {' | '.join(line_parts)}")

    for row in situations:
        cancel_tag = "不可撤" if row["cancellable"] == "never" else ("唯由进度" if row["cancellable"] == "by_progress" else "可撤旨")
        _print_row(row, f"[系统/{cancel_tag}]")
    for row in initiatives:
        _print_row(row, "[玩家/可撤旨]")
    print()


def event_to_issue(db: GameDB, state: GameState, ev: Event) -> Optional[int]:
    """把一个预设 event（EVENTS / SEED_EVENTS）落成一条 situation issue。供推演判定触发后调用。

    去重分两类：
    - 无 trigger_gate（开局局势）：查任意状态同源 issue，立过则永不重立。
    - 有 trigger_gate（条件触发危机）：只查 active 同源 issue，结案/撤销后 gate 再达标可重新触发。
    """
    if ev.trigger_gate:
        if db.find_active_issue_by_origin("event_pool", ev.id) is not None:
            return None
    else:
        if db.find_any_issue_by_origin("event_pool", ev.id) is not None:
            return None
    # 初值由 severity 推一个偏中性的 bar
    bar = max(20, min(60, 50 - int(ev.severity / 5)))
    # 默认 ongoing + inertia 五档（+10/+5/0/-5/-10），按 kind 取
    ongoing: Dict[str, object] = {}
    inertia = -5
    # 终结一锤子永久数值：达成（bar→100）落 effect_on_resolve，崩坏（bar→0 或 LLM 判失败）落
    # effect_on_fail。与 ongoing 过程效果区分——过程是每月漂移，终结是定局后的永久民心/皇威增减。
    polarity = "neg"  # neg=负面危机（平息回血/崩坏重创）；pos=正面机遇（把握加成/错失轻微）
    # 5 个原 metric（边防/民变/党争/执行/瞒报）已废除，ongoing_effects 按 kind 改用
    # 民心/皇威 或留空让 LLM 在推进时自定。结构性影响由 region/army/external/class delta 承担。
    if ev.kind in ("天灾", "灾情", "饥荒"):
        ongoing = {"metrics": {"民心": -2}, "economy": [{"account": "国库", "delta": -8, "category": "赈济损耗", "reason": ev.title}]}
        inertia = -10
    elif ev.kind in ("人祸", "兵变", "流寇", "民变", "抗税"):
        ongoing = {"metrics": {"民心": -2}}
        inertia = -10
    elif ev.kind in ("外族", "边事"):
        ongoing = {"metrics": {"皇威": -1}}
        inertia = -5
    elif ev.kind in ("党争", "朝议"):
        ongoing = {}
        inertia = -5
    elif ev.kind in ("丰收", "祥瑞", "民和"):
        ongoing = {"metrics": {"民心": 2}}
        inertia = +10
        polarity = "pos"
    elif ev.kind in ("友邦", "归附", "盟约"):
        ongoing = {"metrics": {"皇威": 1}}
        inertia = +5
        polarity = "pos"
    elif ev.kind in ("良策", "试点", "献宝", "科技"):
        inertia = +5
        polarity = "pos"
    elif ev.kind in ("战机", "敌乱"):
        ongoing = {"metrics": {"皇威": 1}}
        inertia = +10
        polarity = "pos"
    effect_resolve, effect_fail = _situation_terminal_effects(ev.kind, int(ev.severity), polarity)
    # 精调字段优先：合并自 opening_crises 的手调危机带 bar/ongoing/effect/meaning，直接用其值；
    # 缺省（0/空）则用上面按 severity/kind 推导的默认。
    if ev.bar_value:
        bar = ev.bar_value
    if ev.ongoing_effects:
        ongoing = ev.ongoing_effects
    if ev.issue_inertia:
        inertia = ev.issue_inertia
    if ev.effect_on_resolve:
        effect_resolve = ev.effect_on_resolve
    if ev.effect_on_fail:
        effect_fail = ev.effect_on_fail
    try:
        return db.insert_issue(
            state,
            kind="situation",
            title=ev.title,
            origin_kind="event_pool",
            origin_ref=ev.id,
            bar_value=bar,
            bar_good_meaning=ev.bar_good_meaning or "已平",
            bar_bad_meaning=ev.bar_bad_meaning or "失控",
            inertia=inertia,
            stage_text=ev.stage_text or ev.summary[:80],
            severity=int(ev.severity),
            region_hint=ev.region_hint,
            faction_hint=",".join(ev.interests[:2]),
            tags=ev.issue_tags or [ev.kind],
            ongoing_effects=ongoing,
            cancellable="never",
            effect_on_resolve=effect_resolve,
            effect_on_fail=effect_fail,
            resolve_condition=ev.resolve_condition,
            fail_condition=ev.fail_condition,
        )
    except Exception as exc:
        print(f"[WARN] 事件 {ev.title} 立项失败：{exc}；跳过。")
        return None


# 会崩坏的局势：人为可控、有明确「彻底失败」时刻——镇压不住/边镇沦陷/朝局崩坏。
# 它们 bar 能跌到 0、status 转 failed 终结，落 effect_on_fail 一锤子永久重创。
# 不在此集合的（天灾/饥荒等不可控天象、正面机遇）无失败态：bar 下限 1、永不 failed、
# effect_on_fail 留空，伤害全靠 ongoing_effects 持续累积。db.advance_issue 据 effect_on_fail
# 是否非空来判能否崩坏，故此处「会崩坏」与「非空 fail effect」必须一致。
_COLLAPSIBLE_KINDS = frozenset({
    "人祸", "兵变", "流寇", "民变", "抗税", "党争", "朝议", "外族", "边事",
})


def _situation_terminal_effects(kind: str, severity: int, polarity: str):
    """situation 终结一锤子永久效果。按 severity 推量级（轻 50 / 中 65 / 重 80）。
    resolve：达成（bar→100）落永久回血/加成，所有 situation 都有。
    fail：仅「会崩坏」局势（_COLLAPSIBLE_KINDS）有，崩坏（bar→0）落永久重创，幅度重于回血。
    民心/皇威由 kind 倾向决定（边事/外族偏皇威，灾害/民变偏民心，余者两者兼得）。"""
    mag = 1 if severity < 55 else (2 if severity < 70 else 3)
    if kind in ("外族", "边事", "友邦", "归附", "盟约", "战机", "敌乱"):
        axis = "皇威"
    elif kind in ("天灾", "灾情", "饥荒", "人祸", "兵变", "流寇", "民变", "抗税", "丰收", "祥瑞", "民和"):
        axis = "民心"
    else:
        axis = "both"

    def _metrics(amount: int) -> Dict[str, int]:
        if axis == "both":
            half = max(1, abs(amount) // 2)
            s = 1 if amount > 0 else -1
            return {"民心": s * half, "皇威": s * half}
        return {axis: amount}

    resolve_amt = (3 if polarity == "neg" else 4) * mag
    effect_resolve = {"metrics": _metrics(resolve_amt)}
    effect_fail = {"metrics": _metrics(-5 * mag)} if kind in _COLLAPSIBLE_KINDS else {}
    return effect_resolve, effect_fail


def _normalize_cancellable(raw: object) -> str:
    """LLM 偶发臆造 cancellable 值（by_policy 之类），归一到合法白名单。"""
    val = str(raw or "").strip().lower()
    if val in ("decree", "never", "by_progress"):
        return val
    # 常见臆造映射
    if val in ("by_policy", "policy"):
        return "decree"
    if val in ("none", "no", "false"):
        return "never"
    if val in ("yes", "true", "auto"):
        return "by_progress"
    return "by_progress"  # 默认


def _compute_inertia(ni: Dict[str, object]) -> int:
    """从 expected_months 算 inertia；兼容旧 inertia 直接填的写法。"""
    em_raw = ni.get("expected_months")
    if em_raw is not None:
        try:
            em = int(em_raw)
        except (TypeError, ValueError):
            em = 0
        if em != 0:
            inertia = round(100 / em)
            return max(-10, min(10, inertia))
    # 兼容旧字段
    return max(-10, min(10, int(ni.get("inertia") or 0)))


# 离散时长档：LLM 只能给这几档（防乱填）；映射到月。
_LEGACY_DURATION_MONTHS = {"1年": 12, "2年": 24, "永久": -1}
_LEGACY_ACCOUNT_KEYS = ("国库", "内库", "民心", "皇威")  # 全局可被 % 修正的四项
_LEGACY_PCT_CAP = 5  # 单条帝国修正对某维度的百分比上限，防幅度过大

# 月固定收支项的合法账户 / 方向白名单（fiscal_creates 枚举守门，集中一处；
# applier 是唯一的枚举守门（cleaner 只做 direction 同义词映射等无损规范化,cmr S3 r2）。
_FISCAL_ACCOUNTS = ("国库", "内库")
_FISCAL_DIRECTIONS = ("income", "expense")


def _clamp_pct(v: object) -> Optional[int]:
    try:
        pct = int(v)
    except (TypeError, ValueError):
        return None
    if pct == 0:
        return None
    return max(-_LEGACY_PCT_CAP, min(_LEGACY_PCT_CAP, pct))


def _spawn_legacy_from_effect(
    db: GameDB,
    state: GameState,
    effect: Dict[str, object],
    issue_id: int,
    issue_title: str,
) -> Optional[Dict[str, object]]:
    """结案 effect 里若带 legacy（帝国修正）段，落 legacies 表。返回落地摘要供日志。
    legacy schema:
      {"name": str,
       "duration": "1年"|"2年"|"永久",
       "modifiers": {                         # 各维度带符号百分比修正符
         "国库": +10, "内库": -5,                    # 账户增量
         "regions": {"shaanxi": {"unrest": -20}},   # 地区分数字段（仅 REGION_SCORE_FIELDS）
         "armies":  {"jizhou": {"morale": 15}}      # 军队分数字段（仅 ARMY_SCORE_FIELDS）
       },
       "narrative_hint": str}
    各 pct 带符号整数；落账时同维度累加，base>=0 ×(1+net/100)、base<0 ×(1-net/100)。
    缺字段/非法档/空 effect 一律跳过（不抛断）；地区/军队非法字段或不存在 id 由落账层忽略。
    """
    legacy = effect.get("legacy")
    if not isinstance(legacy, dict):
        return None
    name = str(legacy.get("name") or "").strip() or f"{issue_title}遗留"
    dur_key = str(legacy.get("duration") or "2年").strip()
    duration = _LEGACY_DURATION_MONTHS.get(dur_key)
    if duration is None:
        print(f"[WARN] legacy 时长档非法 '{dur_key}'，按 2年 处理。")
        duration = 24
    raw_eff = legacy.get("modifiers") or {}
    modifiers: Dict[str, object] = {}
    if isinstance(raw_eff, dict):
        for k in _LEGACY_ACCOUNT_KEYS:
            pct = _clamp_pct(raw_eff.get(k))
            if pct is not None:
                modifiers[k] = pct
        for scope, allowed, aliases in (
            ("regions", REGION_SCORE_FIELDS + FISCAL_SCORE_FIELDS, REGION_FIELD_ALIASES),
            ("armies", ARMY_SCORE_FIELDS, ARMY_FIELD_ALIASES),
        ):
            block = raw_eff.get(scope)
            if not isinstance(block, dict):
                continue
            scope_out: Dict[str, Dict[str, int]] = {}
            for entity_id, fields in block.items():
                if not isinstance(fields, dict):
                    continue
                fields_out: Dict[str, int] = {}
                for raw_field, v in fields.items():
                    field = aliases.get(str(raw_field).strip(), str(raw_field).strip())
                    if field not in allowed:
                        print(f"[INFO] legacy '{name}' {scope} 字段 '{raw_field}' 非法/不可修正，跳过。")
                        continue
                    pct = _clamp_pct(v)
                    if pct is not None:
                        fields_out[field] = pct
                if fields_out:
                    scope_out[str(entity_id)] = fields_out
            if scope_out:
                modifiers[scope] = scope_out
    if not modifiers:
        print(f"[INFO] legacy '{name}' 无有效 modifiers，跳过。")
        return None
    new_id = db.insert_legacy(
        state,
        name=name,
        modifiers=modifiers,
        narrative_hint=str(legacy.get("narrative_hint") or "")[:200],
        duration_months=duration,
        source_issue_id=issue_id,
    )
    summary = {
        "legacy_id": new_id, "name": name,
        "duration_months": duration, "modifiers": modifiers,
    }
    dur_label = "永久" if duration < 0 else f"{duration}月"
    print(f"[帝国修正] 局势#{issue_id}「{issue_title}」落「{name}」({dur_label}) {modifiers}")
    return summary


def _apply_issue_entities(
    db: GameDB,
    state: GameState,
    effect: Dict[str, object],
    label: str,
    content=None,
    registry=None,
    llm_config: Any = None,
    applied_person_changes: Optional[List[Dict[str, object]]] = None,
) -> List[Dict[str, object]]:
    """国策结案的实体后果：建军 / 补兵改属性 / 人物状态(死/流放/下狱/罢/致仕)。
    全局严格、不静默——非法 delta 直接抛错中断当回合，绝不无声丢失。
    （effect_on_resolve 原本只支持 metrics/economy/buildings/legacy，这里补 army/人事两线。）"""
    # ADR 0008 决定 1（PR2-S2）后,底层 db 方法对 LLM 脏项改「逐项拒收留痕」而非
    # raise——国策结案路（本函数）把拒收项升级回 ValueError 中断当回合，**仅限历史上
    # 本就 raise 的类别**（查无此军/owner 幻觉/缺必填等）。历史上 print-skip 或静默
    # 走默认的案（army 非法字段/重复无 manpower/重复非整/可选脏值/非 dict 项）带
    # issue_strict=False 标——容忍不升级,否则历史可活的脏数据变成新的崩月路
    # （cmr S2 r1）。两类都留拒收记录,不无声丢。
    tolerated: List[Dict[str, object]] = []
    def effective_content():
        return content if content is not None else _ctx()

    def _raise_on_rejected(results, what: str) -> None:
        strict = [r for r in (results or [])
                  if isinstance(r, dict) and r.get("rejected")
                  and r.get("issue_strict", True)]
        if strict:
            reasons = "；".join(str(r.get("reason") or "") for r in strict)
            raise ValueError(f"{label} {what} 非法（全局严格，不静默）：{reasons}")
        # 容忍项（issue_strict=False）留痕不蒸发（cmr S2 r2,2/2:改前是 print,
        # 不留比 print 更静默）：收集返回,tracker-output 路挂 issue_summary 进
        # rejection_reports,inertia 路由 caller tlog。
        tolerated.extend(
            {**r, "label": label}
            for r in (results or [])
            if isinstance(r, dict) and r.get("rejected") and not r.get("issue_strict", True)
        )

    new_armies = effect.get("new_armies")
    if isinstance(new_armies, list) and new_armies:
        _raise_on_rejected(
            db.create_armies_from_extraction(state, new_armies, actor=label), "建军"
        )
    army_delta = effect.get("army_delta")
    if isinstance(army_delta, dict) and army_delta:
        pseudo = type("E", (), {"id": "issue", "title": label})()
        _raise_on_rejected(
            db.apply_army_deltas(state, pseudo, None, label, army_delta), "补兵/改属性"
        )
    raw_person_changes = effect.get("人物变更")
    if raw_person_changes is not None:
        if not isinstance(raw_person_changes, list):
            raise ValueError(f"{label} 人物变更 非法（全局严格，不静默）：必须是 list")
        for idx, it in enumerate(raw_person_changes):
            if not isinstance(it, dict):
                raise ValueError(f"{label} 人物变更 非法（全局严格，不静默）：第 {idx} 项非 dict")
    person_changes = normalize_person_changes({"人物变更": raw_person_changes or []})
    csc = effect.get("character_status_changes")
    if not person_changes and isinstance(csc, list) and csc:
        for it in csc:
            if not isinstance(it, dict):
                # 全局严格（不静默）：非 dict 项直接抛错，不无声丢（CMR F7）。
                raise ValueError(f"{label} character_status_changes 含非法非 dict 项：{it!r}")
        status_person_changes = normalize_person_changes({"character_status_changes": csc})
        for item in status_person_changes:
            if isinstance(item, dict):
                item.pop("legacy_gate", None)
        results = _apply_person_changes(
            db,
            state,
            status_person_changes,
            content=effective_content(),
            registry=registry,
            llm_config=llm_config,
            source="system_simulation",
            derived_from=label,
        )
        _raise_on_rejected(results, "character_status_changes")
        if applied_person_changes is not None:
            applied_person_changes.extend(results)
    if person_changes:
        results = _apply_person_changes(
            db,
            state,
            person_changes,
            content=effective_content(),
            registry=registry,
            llm_config=llm_config,
            source="system_simulation",
            derived_from=label,
        )
        _raise_on_rejected(results, "人物变更")
        if applied_person_changes is not None:
            applied_person_changes.extend(results)
    return tolerated


# #45/#46（M1 状态可信链路）：国策结案实体后果强制配对守门。语义命中练军/募营/调将却无
# new_armies/office_changes、或命月经费/俸/饷却无月度 economy 时响亮告警，堵「只推进度条、
# 实体后果只活邸报」的半落库（#45 太学府月经费没立账、#46 天雄军没建军籍真踩坑）。
# warn-only：列入结果供 surface、不阻断结算；检查国策自身 effect_on_resolve/ongoing_effects
# 是否带应有实体（正解就该挂在这两处、enrich 也如此填），不跨引顶层、保持纯函数可测。
_MILITARY_RAISE_PHRASES = (
    "练军", "练兵", "练成", "募营", "募兵", "募军", "建军", "新军", "成军",
    "团练", "编练", "立营", "组建", "扩军",
)
_MILITARY_MOVE_PHRASES = ("调将", "调防", "移镇", "督师", "镇守", "调任主将")
_FISCAL_RECURRING_PHRASES = (
    "月经费", "经费", "月俸", "俸禄", "岁俸", "军饷", "粮饷", "月饷", "岁支",
    "廪", "养兵", "养廉", "月银",
)


def _has_economy_entry(d: object) -> bool:
    """是否含「flows 会真正立账」的月度 economy 项：account∈(国库,内库) + delta 经 int() 强转非零
    ——与 flows._apply_economy_list 同口径（它只对 国库/内库 立账、`int(delta or 0)` 强转、跳过
    零额/非数/它账）。空壳/它账/零额/非数不算配对，数字串 delta 同 flows 认账（CMR codex+claude）。"""
    if not isinstance(d, dict):
        return False
    for item in d.get("economy") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("account") or "") not in ("国库", "内库"):
            continue
        try:
            delta = int(item.get("delta") or 0)
        except (TypeError, ValueError):
            continue
        if delta != 0:
            return True
    return False


def _initiative_resolve_pairing_warnings(
    title: str, tags: object, ongoing_effects: object, effect: object,
) -> List[str]:
    """国策结案实体后果强制配对守门（#45/#46）——仅在 initiative 结案处调用。
    返回缺配对的告警串列表（空=无缺漏）。warn-only，调用方 surface、不阻断。"""
    tag_list = tags if isinstance(tags, (list, tuple)) else []
    blob = str(title or "") + " " + " ".join(str(t) for t in tag_list)
    effect = effect if isinstance(effect, dict) else {}
    warns: List[str] = []

    # 练军/募营 须落 new_armies；调将 须落人物变更——分别判，不混为一谈（练军只挂调任仍缺军籍、
    # 调将只挂建军仍缺主将调任，混判会互相消音，CMR codex）。office_changes 是 ADR 0009 死键、
    # _apply_issue_entities 不读，不纳入 has_office（纳入会消音本该响的告警，CMR gemini）。
    needs_army = any(p in blob for p in _MILITARY_RAISE_PHRASES)
    needs_office = any(p in blob for p in _MILITARY_MOVE_PHRASES)
    if needs_army or needs_office:
        has_army = bool(effect.get("new_armies")) or bool(effect.get("army_delta"))
        has_office = bool(effect.get("人物变更") or effect.get("character_status_changes"))
        if needs_army and not has_army:
            warns.append(
                f"军事国策「{str(title)[:16]}」结案无 new_armies 配对（练军/募营疑未建军籍，#46）"
            )
        if needs_office and not has_office:
            warns.append(
                f"军事国策「{str(title)[:16]}」结案无人物变更配对（调将疑未落主将调任，#46）"
            )

    if any(p in blob for p in _FISCAL_RECURRING_PHRASES):
        # 只查国策自身 effect/ongoing 的月度 economy；顶层 fiscal_creates 不在本纯函数视野内，
        # 故告警文案不声称查了它——若另经 fiscal_creates 立账可忽略本提示（CMR claude）。
        if not _has_economy_entry(effect) and not _has_economy_entry(ongoing_effects):
            warns.append(
                f"经制国策「{str(title)[:16]}」结案无月度 economy 配对"
                "（疑月经费/俸饷未立常设月支；若已另经 fiscal_creates 立账可忽略，#45）"
            )
    return warns


def _emit_pairing_warnings(new_row, effect: object, sink: Optional[List[str]] = None) -> None:
    """在 initiative 结案处调配对守门：tlog 响亮告警（#14/#27 风格）；sink 给定时再收进供
    程序 surface（inertia 自然结案路只 tlog、不收 sink）。仅对 kind=initiative 生效；
    row 字段缺失/JSON 畸形一律安全降级、不阻断结算。"""
    def _g(key, default):
        try:
            return new_row[key]
        except (KeyError, IndexError, TypeError):
            return default
    if str(_g("kind", "") or "") != "initiative":
        return
    try:
        tags = json.loads(_g("tags", "[]") or "[]")
    except (TypeError, ValueError):
        tags = []
    try:
        ongoing = json.loads(_g("ongoing_effects", "{}") or "{}")
    except (TypeError, ValueError):
        ongoing = {}
    for w in _initiative_resolve_pairing_warnings(str(_g("title", "") or ""), tags, ongoing, effect):
        tlog(f"[pairing] {w}")
        if sink is not None:
            sink.append(w)


def apply_issue_tracker_output(
    db: GameDB,
    state: GameState,
    tracker_output: Dict[str, object],
    llm_config: Any = None,
    content=None,
) -> Dict[str, object]:
    touched_ids: set = set()
    applied_advances: List[Dict[str, object]] = []
    pairing_warnings: List[str] = []  # #45/#46 国策结案实体后果强制配对告警（warn-only）
    applied_new: List[Dict[str, object]] = []
    applied_cancels: List[Dict[str, object]] = []
    # issue 实体后果的容忍拒收项（issue_strict=False）——挂进返回 summary,
    # S0 桥接一层下探自动收进 rejection_reports（留痕不蒸发,cmr S2 r2）。
    entity_rejections: List[Dict[str, object]] = []
    issue_person_changes: List[Dict[str, object]] = []
    event_by_id = _ctx().event_by_id

    # 1) advances
    for adv in tracker_output.get("advances", []) or []:
        try:
            issue_id = int(adv.get("issue_id"))
        except (TypeError, ValueError):
            continue
        delta_bar = int(adv.get("delta_bar") or 0)
        inertia_delta = int(adv.get("inertia_delta") or 0)
        stage_text = str(adv.get("stage_text") or "")[:120]
        narrative = str(adv.get("narrative") or "")[:400]
        metric_delta_raw = adv.get("metric_delta") or {}
        applied_metrics = _apply_metric_dict(state, metric_delta_raw if isinstance(metric_delta_raw, dict) else {}, db=db)
        new_row = db.advance_issue(
            state, issue_id,
            trigger_kind="decree",
            delta_bar=delta_bar,
            stage_text=stage_text,
            narrative=narrative,
            metric_delta=applied_metrics,
            inertia_delta=inertia_delta,
        )
        if new_row is None:
            continue
        touched_ids.add(issue_id)
        # 终结结算：bar 自然推到 100/0 触发的 resolved/failed，与 close_issues 一样落终结效果（含建筑）
        if new_row["status"] == "resolved":
            effect = json.loads(new_row["effect_on_resolve"] or "{}")
            _emit_pairing_warnings(new_row, effect, pairing_warnings)
            _apply_metric_dict(state, effect.get("metrics") or {}, db=db)
            _apply_economy_list(db, state, effect.get("economy") or [])
            _apply_faction_dict(db, effect.get("factions") or {})
            _apply_issue_buildings(db, state, effect.get("buildings"), _ISSUE_PSEUDO_EVENT, f"局势#{issue_id}结案")
            entity_rejections.extend(
                _apply_issue_entities(
                    db,
                    state,
                    effect,
                    f"局势#{issue_id}结案",
                    content=content,
                    llm_config=llm_config,
                    applied_person_changes=issue_person_changes,
                ))
            _spawn_legacy_from_effect(db, state, effect, issue_id, str(new_row["title"]))
        elif new_row["status"] == "failed":
            effect = json.loads(new_row["effect_on_fail"] or "{}")
            _apply_metric_dict(state, effect.get("metrics") or {}, db=db)
            _apply_economy_list(db, state, effect.get("economy") or [])
            _apply_faction_dict(db, effect.get("factions") or {})
            _apply_issue_buildings(db, state, effect.get("buildings"), _ISSUE_PSEUDO_EVENT, f"局势#{issue_id}失败")
            entity_rejections.extend(
                _apply_issue_entities(
                    db,
                    state,
                    effect,
                    f"局势#{issue_id}失败",
                    content=content,
                    llm_config=llm_config,
                    applied_person_changes=issue_person_changes,
                ))
            _spawn_legacy_from_effect(db, state, effect, issue_id, str(new_row["title"]))
        applied_advances.append({
            "issue_id": issue_id,
            "title": new_row["title"],
            "from_value": int(new_row["bar_value"]) - delta_bar,
            "to_value": int(new_row["bar_value"]),
            "stage_text": new_row["stage_text"],
            "status": new_row["status"],
            "narrative": narrative,
        })

    # 2) new_issues：接两种来源——
    #    decree     —— 玩家诏书强推，由 LLM 给字段新立 issue
    #    event_pool —— 预设事件（EVENTS/SEED_EVENTS）被推演判定触发，按预设 event 立 issue
    #    其它来源一律拒。
    initiative_active = db.count_active_initiatives()
    for ni in tracker_output.get("new_issues", []) or []:
        title = str(ni.get("title") or "")
        origin_kind = str(ni.get("origin_kind") or "").lower()
        if origin_kind == "event_pool":
            # 预设事件触发：id 必须是真实预设 event，照预设字段立 issue（不用 LLM 给的字段）
            event_id = str(ni.get("id") or ni.get("origin_ref") or "").strip()
            ev = event_by_id.get(event_id)
            if ev is None:
                print(f"[INFO] new_issue 已拒：event_pool id={event_id!r} 非预设事件，疑似臆造。")
                applied_new.append({"title": title or event_id, "rejected": True, "reason": "event_pool id 非预设事件"})
                continue
            if getattr(ev, "auto_trigger", False):
                # auto_trigger 事件只能程序硬触发，LLM 不准从候选池立项
                print(f"[INFO] new_issue 已拒：event {event_id} 标了 auto_trigger，只能程序硬触发。")
                applied_new.append({"title": ev.title, "rejected": True, "reason": "auto_trigger 事件仅程序可触发"})
                continue
            if ev.event_type != "situation":
                db.mark_event_triggered(state, ev.id)
                print(f"[INFO] new_issue 已拒：事件 {event_id} 为 {ev.event_type}，不转 issue。")
                applied_new.append({"title": ev.title, "rejected": False, "reason": f"event_type={ev.event_type} 已记为触发"})
                continue
            issue_id = event_to_issue(db, state, ev)
            if issue_id is None:
                applied_new.append({"title": ev.title, "rejected": True, "reason": "事件已触发过或落库失败"})
            else:
                applied_new.append({"issue_id": issue_id, "kind": "situation", "title": ev.title, "rejected": False})
            continue
        if origin_kind != "decree":
            print(f"[INFO] new_issue 已拒：'{title}'（origin_kind={origin_kind!r}，仅接 decree / event_pool）。")
            applied_new.append({"title": title, "rejected": True, "reason": "来源非 decree/event_pool 不许新立"})
            continue
        kind = str(ni.get("kind") or "initiative")
        if kind == "initiative" and initiative_active >= 10:
            applied_new.append({"title": title, "rejected": True, "reason": "已有十事在办，朝廷分身乏术，难再添新工。"})
            continue
        # LLM 可能把效果字段给成非 dict（字符串/数组）；isinstance 守门归 {}，
        # 不让 dict("乱填") 抛 ValueError 越过单条拒绝、崩整月落库（codexB-P1）。
        def _eff_dict(v):
            return v if isinstance(v, dict) else {}
        ongoing_eff = _eff_dict(ni.get("ongoing_effects"))
        resolve_eff = _eff_dict(ni.get("effect_on_resolve"))
        fail_eff = _eff_dict(ni.get("effect_on_fail"))
        # 校验：国策必须有「办成回报」。CLI 后端(agy)一贯不填效果字段（实测 0/4），
        # 空则聚焦补全，保证「国策跑完有实质后果」(A 方案)；floor 兜底，绝不入空壳。
        if kind == "initiative" and not resolve_eff:
            from ming_sim.cli_backend import cli_backend_active, enrich_initiative_effects
            if cli_backend_active(llm_config):
                try:
                    enr = enrich_initiative_effects(title, str(ni.get("stage_text") or ""), llm_config=llm_config)
                    resolve_eff = enr.get("effect_on_resolve") or resolve_eff
                    ongoing_eff = enr.get("ongoing_effects") or ongoing_eff
                    fail_eff = enr.get("effect_on_fail") or fail_eff
                    print(f"[issue/enrich] 国策「{title[:16]}」补效果 resolve={bool(resolve_eff)} ongoing={bool(ongoing_eff)}")
                except Exception as exc:
                    print(f"[issue/enrich] 补全失败，沿用空效果：{exc}")
                # floor 在 try 外：即便 enrich 抛错或没补上，CLI 后端国策也绝不入空壳（codexB）。
                if not resolve_eff:
                    resolve_eff = {"metrics": {"民心": 1}}
        try:
            issue_id = db.insert_issue(
                state,
                kind=kind,
                title=title[:60] or "无名事项",
                origin_kind="decree",
                origin_ref=str(ni.get("origin_ref") or ""),
                bar_value=int(ni.get("bar_value", 25)),
                bar_good_meaning=str(ni.get("bar_good_meaning") or "已成"),
                bar_bad_meaning=str(ni.get("bar_bad_meaning") or "废止"),
                inertia=_compute_inertia(ni),
                stage_text=str(ni.get("stage_text") or "")[:120],
                severity=int(ni.get("severity") or 50),
                region_hint=str(ni.get("region_hint") or ""),
                faction_hint=str(ni.get("faction_hint") or ""),
                tags=list(ni.get("tags") or []),
                ongoing_effects=ongoing_eff,
                cancellable=_normalize_cancellable(ni.get("cancellable")),
                cancel_cost=dict(ni.get("cancel_cost") or {}),
                effect_on_resolve=resolve_eff,
                effect_on_fail=fail_eff,
                resolve_condition=str(ni.get("resolve_condition") or "")[:300],
                fail_condition=str(ni.get("fail_condition") or "")[:300],
            )
            if kind == "initiative":
                initiative_active += 1
            applied_new.append({"issue_id": issue_id, "kind": kind, "title": title, "rejected": False})
        except Exception as exc:
            print(f"[WARN] new_issue 落库失败：{exc}；跳过 {title}")

    # 3) closes（LLM 主动结案/失败，不看 bar 门槛）
    applied_closes: List[Dict[str, object]] = []
    for cl in tracker_output.get("close_issues", []) or []:
        try:
            issue_id = int(cl.get("issue_id"))
        except (TypeError, ValueError):
            continue
        reason = str(cl.get("reason") or "").strip().lower()
        if reason not in ("resolved", "failed"):
            print(f"[WARN] close_issues: reason 非法 '{reason}'，跳过 issue {issue_id}")
            continue
        narrative = str(cl.get("narrative") or "")[:400]
        try:
            new_row = db.close_issue(state, issue_id, reason=reason, narrative=narrative)
        except Exception as exc:
            print(f"[WARN] close_issue 落库失败：{exc}；跳过 issue {issue_id}")
            continue
        if new_row is None:
            continue
        touched_ids.add(issue_id)
        # 终结效果：以 issue 立项时预设的 effect 为底，叠加 LLM 在本次结案项 cl 里现给的 effect。
        # 现给优先——event_pool 预设 issue（如阉党之祸）立项时 effect 多为空，帝国修正只能结案当下给。
        if reason == "resolved":
            effect = json.loads(new_row["effect_on_resolve"] or "{}")
            cl_effect = cl.get("effect_on_resolve")
        else:
            effect = json.loads(new_row["effect_on_fail"] or "{}")
            cl_effect = cl.get("effect_on_fail")
        if isinstance(cl_effect, dict):
            # 浅合并：metrics/economy/factions/buildings/legacy 等顶层段，现给覆盖预设
            effect = {**effect, **cl_effect}
        if reason == "resolved":
            _emit_pairing_warnings(new_row, effect, pairing_warnings)
        _apply_metric_dict(state, effect.get("metrics") or {}, db=db)
        _apply_economy_list(db, state, effect.get("economy") or [])
        _apply_faction_dict(db, effect.get("factions") or {})
        building_ops = _apply_issue_buildings(
            db, state, effect.get("buildings"),
            _ISSUE_PSEUDO_EVENT, f"局势#{issue_id}{'结案' if reason == 'resolved' else '失败'}",
        )
        close_person_changes: List[Dict[str, object]] = []
        entity_rejections.extend(_apply_issue_entities(
            db,
            state,
            effect,
            f"局势#{issue_id}{'结案' if reason == 'resolved' else '失败'}",
            content=content,
            llm_config=llm_config,
            applied_person_changes=close_person_changes,
        ))
        issue_person_changes.extend(close_person_changes)
        _spawn_legacy_from_effect(db, state, effect, issue_id, str(new_row["title"]))
        close_record = {
            "issue_id": issue_id,
            "title": new_row["title"],
            "reason": reason,
            "narrative": narrative,
            "building_ops": building_ops,
        }
        if close_person_changes:
            close_record["applied_person_changes"] = close_person_changes
        applied_closes.append(close_record)

    # 4) cancels
    for cn in tracker_output.get("cancels", []) or []:
        try:
            issue_id = int(cn.get("issue_id"))
        except (TypeError, ValueError):
            continue
        row = db.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
        if row is None or row["status"] != "active":
            continue
        if row["cancellable"] != "decree":
            # 不可撤：当作 advance 处理（皇威 -2）
            db.advance_issue(
                state, issue_id,
                trigger_kind="decree",
                delta_bar=0,
                stage_text=row["stage_text"],
                narrative=str(cn.get("narrative") or "陛下欲罢，然此事非诏可消。")[:400],
                metric_delta={"皇威": -2},
            )
            state.metrics["皇威"] = max(0, int(state.metrics.get("皇威", 0)) - 2)
            touched_ids.add(issue_id)
            applied_cancels.append({
                "issue_id": issue_id, "rejected": True, "title": row["title"],
                # 拒收行必须带人读原因（ADR 0008 决定 5）；此拒收有部分落库副作用
                # （已转强推+皇威-2），category 区分于纯丢弃（cmr S0 r2）。
                "reason": "此事非诏可消（不可撤国策），已转强行推进并损皇威 2 点。",
                "category": "non_cancellable_converted",
            })
            continue
        # 可撤：应用 applied_cost
        cost = cn.get("applied_cost") or {}
        if isinstance(cost, dict):
            _apply_metric_dict(state, cost.get("metrics") or {}, db=db)
            _apply_economy_list(db, state, cost.get("economy") or [])
            _apply_faction_dict(db, cost.get("factions") or {})
        db.cancel_issue(
            state, issue_id,
            narrative=str(cn.get("narrative") or "")[:400],
            applied_cost=cost if isinstance(cost, dict) else {},
        )
        touched_ids.add(issue_id)
        applied_cancels.append({"issue_id": issue_id, "rejected": False, "title": row["title"]})

    state.clamp()
    return {
        "advances": applied_advances,
        "new_issues": applied_new,
        "closes": applied_closes,
        "cancels": applied_cancels,
        "entity_rejections": entity_rejections,
        "applied_person_changes": issue_person_changes,
        "touched_ids": sorted(touched_ids),
        "pairing_warnings": pairing_warnings,
    }


# 独占实职关键词：office 分项以此结尾者视为「一人一缺」，须顶替去重。
# 群体职（大学士/侍郎/郎中/主事/御史/翰林等）不在内，可多员并存。
_EXCLUSIVE_OFFICE_SUFFIXES = (
    "首辅", "次辅", "尚书", "总督", "巡抚", "总兵", "督师", "经略", "提督",
)


def _is_exclusive_office(part: str) -> bool:
    """office 单个分项是否独占实职。南京XX为留都缺，与京职互不冲突，单独算一缺。"""
    return any(part.endswith(suf) for suf in _EXCLUSIVE_OFFICE_SUFFIXES)


def _displace_duplicate_offices(
    db: GameDB, content: Optional[GameContent], new_holder: str, new_office: str
) -> List[str]:
    """新任者 new_holder 拿到 new_office 后，把其中每个独占实职分项从其他 active 官员
    office 里剔除，避免双缺官。返回被腾出的 (旧任者:职) 描述列表。
    纯按 office 文字匹配——不依赖 court_role，对存量档同样生效。"""
    new_parts = [p for p in normalize_office(new_office).split(",") if _is_exclusive_office(p)]
    if not new_parts:
        return []
    displaced: List[str] = []
    rows = db.conn.execute(
        "SELECT name, office FROM characters WHERE status='active' AND power_id='ming' AND name!=?",
        (new_holder,),
    ).fetchall()
    for row in rows:
        holder_parts = [p.strip() for p in str(row["office"]).split(",") if p.strip()]
        kept = [p for p in holder_parts if p not in new_parts]
        if len(kept) == len(holder_parts):
            continue  # 此人不占同名独缺
        for lost in (p for p in holder_parts if p in new_parts):
            displaced.append(f"{row['name']}:{lost}")
        fully_displaced = not kept
        new_holder_office = "听用候铨" if fully_displaced else ",".join(kept)
        # 剔掉一个分项后,保留官职对应的 office_type 可能变了(如剔「兵部尚书」后只剩「左都御史」=都察院)。
        # 若独占实职被完全腾空,旧任仍 active,但其名分必须落入人才池的「听用候铨」,
        # 不能留下 active + 空 office 的半身份（ADR 0009 S5）。
        old_type_row = db.conn.execute(
            "SELECT office_type FROM characters WHERE name=?", (row["name"],)).fetchone()
        old_type = old_type_row["office_type"] if old_type_row else ""
        new_type = (
            "身名分"
            if fully_displaced
            else infer_office_type_from_office(new_holder_office, old_type, db.llm_config)
        )
        if fully_displaced:
            db.conn.execute(
                "UPDATE characters SET office=?, office_type=?, status_reason=?, reason_code=?, "
                "transit_to='' WHERE name=?",
                (new_holder_office, new_type, "被顶替", "被顶替", row["name"]),
            )
        else:
            db.conn.execute(
                "UPDATE characters SET office=?, office_type=? WHERE name=?",
                (new_holder_office, new_type, row["name"]),
            )
        if content is not None and row["name"] in content.characters:
            ch = content.characters[row["name"]]
            ch.office = new_holder_office
            ch.office_type = new_type
            if fully_displaced:
                ch.status_reason = "被顶替"
                ch.reason_code = "被顶替"
                ch.transit_to = ""
    db.conn.commit()
    return displaced


def _snapshot_person_write_state(db: GameDB, content: Optional[GameContent]):
    character_rows = [
        dict(row)
        for row in db.conn.execute(
            "SELECT name, status, office, office_type, status_reason, "
            "status_changed_turn, reason_code, transit_to FROM characters"
        ).fetchall()
    ]
    office_rows = [
        dict(row)
        for row in db.conn.execute(
            "SELECT character_name, office_title, office_type, source, updated_at "
            "FROM character_offices"
        ).fetchall()
    ]
    content_rows = {}
    if content is not None:
        content_rows = {
            name: {
                "status": ch.status,
                "office": ch.office,
                "office_type": ch.office_type,
                "transit_to": ch.transit_to,
                "status_reason": getattr(ch, "status_reason", ""),
                "reason_code": getattr(ch, "reason_code", ""),
            }
            for name, ch in content.characters.items()
        }
    return character_rows, office_rows, content_rows


def _restore_person_write_state(db: GameDB, content: Optional[GameContent], snapshot) -> None:
    character_rows, office_rows, content_rows = snapshot
    db.conn.execute("DELETE FROM character_offices")
    snapshot_names = {str(row["name"]) for row in character_rows}
    if snapshot_names:
        placeholders = ",".join("?" for _ in snapshot_names)
        db.conn.execute(
            f"DELETE FROM characters WHERE name NOT IN ({placeholders})",
            tuple(snapshot_names),
        )
    else:
        db.conn.execute("DELETE FROM characters")
    db.conn.executemany(
        "UPDATE characters SET status=?, office=?, office_type=?, status_reason=?, "
        "status_changed_turn=?, reason_code=?, transit_to=? WHERE name=?",
        [
            (
                row["status"],
                row["office"],
                row["office_type"],
                row["status_reason"],
                row["status_changed_turn"],
                row["reason_code"],
                row["transit_to"],
                row["name"],
            )
            for row in character_rows
        ],
    )
    db.conn.executemany(
        "INSERT INTO character_offices "
        "(character_name, office_title, office_type, source, updated_at) "
        "VALUES (?, ?, ?, ?, ?)",
        [
            (
                row["character_name"],
                row["office_title"],
                row["office_type"],
                row["source"],
                row["updated_at"],
            )
            for row in office_rows
        ],
    )
    db.conn.commit()
    if content is not None:
        for name in list(content.characters):
            if name not in content_rows:
                del content.characters[name]
        for name, values in content_rows.items():
            ch = content.characters.get(name)
            if ch is None:
                continue
            ch.status = values["status"]
            ch.office = values["office"]
            ch.office_type = values["office_type"]
            ch.transit_to = values["transit_to"]
            ch.status_reason = values.get("status_reason", "")
            ch.reason_code = values.get("reason_code", "")


# 校验「二级非 dict 会让 apply 在**逐 entity 写 DB 的中途崩**,留下部分已写 + 回合照推 = 半落库」
# 的字段。这三者 apply 都逐项 UPDATE/INSERT,前面的 entity 先落库、坏的 entity 崩:
#   - region_delta / army_delta:apply 裸调,崩直接抛穿;
#   - power_updates:apply_score_extraction 虽裹 try/except,但只接住异常不回滚——前面已写的 power
#     行仍被后续 record_log/save_turn 提交 = 半落库(CMR R2 codex)。prompt 里 power_updates 恒为
#     嵌套 dict,无扁平标量形态,故二级非 dict = 真畸形,校验前置拦截正确。
# **不**列入(apply 各自容忍,validate 不该更严):faction_delta(吃旧扁平 int {"阉党": -10},prompt 允许)、
# class_delta(对非 dict `continue` 静默跳,不写)。
_NESTED_DICT_FIELDS = frozenset({"region_delta", "army_delta", "power_updates"})


def validate_delta_shape(extracted: dict) -> None:
    """canonical delta 各顶层字段容器类型必须匹配 schema(dict/list),实体模块二级值必须是 dict,
    否则**任何 DB 改动前**抛 ValueError——畸形值直送 apply 会在结算中途崩 `.items()`,叠加非
    原子结算 = 半落库(违反 P1 落库铁律;cmr RT-1 / Gemini PR#50 R2)。driver 在 pre_settle 前
    调一次防 pre_settle 半改;落库核 apply_score_extraction 自身也调一次防 apply 内部半落库。
    彻底原子化的事务边界(原 issue #3)已由 ADR 0008 落地(v0.8.0.0,见 applier.atomic):结算写
    序列整体包单事务、崩则全回滚。本校验仍保留为廉价**前置**防线——在动 DB 前就拦畸形 delta,
    省去事务回滚成本并给出更精确的字段级报错。"""
    from ming_sim.simulation import EMPTY_EXTRACTION  # 懒 import 避 issues↔simulation 循环
    for key, value in extracted.items():
        if key not in EMPTY_EXTRACTION:
            raise ValueError(
                f"未知 delta 顶层字段「{key}」(canonicalize 后)；疑拼写错(如 地区变更↔地区变化)，"
                "apply 不会消费它 = 静默无效。请改用合法 key。"
            )
        if value is None:
            # None = 字段缺省/LLM 输出 null;apply 用 `.get(key) or {}`/`or []` 当空 no-op,
            # 校验同样放行(别比 apply 更严,否则合法 null 会被误拒,Gemini R1)。
            continue
        expected = EMPTY_EXTRACTION[key]
        if isinstance(expected, dict) and not isinstance(value, dict):
            raise ValueError(f"delta 字段 {key} 必须是 object(dict)，实得 {type(value).__name__}")
        if isinstance(expected, list):
            if not isinstance(value, list):
                raise ValueError(f"delta 字段 {key} 必须是 array(list)，实得 {type(value).__name__}")
            # schema 里所有 list 字段都是 list-of-dict(economy_moves/new_armies/fiscal_*/issue_*/
            # appointments/character_*/secret_order_* 等);apply 逐项 item.get() 落库,非 dict 项会
            # 中途崩 → 部分已写半落库。落库前校验每项是 dict(CMR R3 gemini)。
            for i, item in enumerate(value):
                if not isinstance(item, dict):
                    raise ValueError(
                        f"delta 字段 {key}[{i}] 必须是 object(dict)，实得 {type(item).__name__}"
                    )
        if key in _NESTED_DICT_FIELDS:
            for ent, sub in value.items():
                if not isinstance(sub, dict):
                    raise ValueError(
                        f"delta 字段 {key}.{ent} 必须是 object(dict)，实得 {type(sub).__name__}"
                    )


def apply_office_appointment(
    db: GameDB,
    state: GameState,
    content,
    registry,
    name: str,
    new_office: str,
    *,
    reason: str = "",
    new_office_type: str = "",
    faction: str = "中立",
    llm_config: Any = None,
) -> Dict[str, object]:
    """朝臣任命/调任的【唯一落地核】：在册且未死 → 改 active + 授官 + 顶替去重 + 同步内存/registry；
    不在册 → apply_appointment 建新档。extractor 的 office_changes 与 CLI 自然语言任免 commit
    共用此核，杜绝两份会漂的 copy（CMR R2 reground）。后宫纳妃语义不同，不走此核（见 appointments）。
    返回结果 dict（rejected / kind=transfer|appoint / displaced 等）。"""
    name = str(name or "").strip()
    new_office = str(new_office or "").strip()
    if not name or not new_office:
        return {"name": name, "new_office": new_office, "rejected": True, "reason": "name 或 new_office 空"}
    # 别名归一：自然语言/LLM 可能用别名（韩老、温首辅…），解析到在册大臣的规范 key，
    # 否则 in_roster 按确切 key 漏判 → 误走新建档被 apply_appointment 拒（CMR R3 gemini）。
    # _find_existing_minister 仅匹配在册 active 非后宫非 candidate 的大明大臣，命中才改名；
    # candidate/不在册返 None → name 不变（candidate 仍由 in_roster 确切 key 命中走激活分支）。
    if content is not None:
        from ming_sim.session import _find_existing_minister
        canon = _find_existing_minister(content, name)
        if canon:
            name = canon
    in_roster = content is not None and name in content.characters
    cur_status = db.get_character_status(name)[0] if in_roster else ""
    if in_roster:
        if cur_status == "dead":
            return {"name": name, "new_office": new_office, "rejected": True, "reason": "人物已故，不能重新启用"}
        old_office = content.characters[name].office
        snapshot = _snapshot_person_write_state(db, content)
        try:
            if cur_status != "active":
                db.set_character_status(state, name, "active", reason[:200] or "诏书任命")
            db.set_character_office(
                name, new_office, new_office_type,
                source=reason[:60] or "诏书调任", llm_config=llm_config,
            )
            if cur_status == "active":
                db.conn.execute(
                    "UPDATE characters SET status_reason='', reason_code='' WHERE name=?",
                    (name,),
                )
                db.conn.commit()
            displaced_parts = _displace_duplicate_offices(db, content, name, new_office)
            ch = content.characters[name]
            ch.status = "active"
            # 三面同步（决定6）：DB 写已定 status_reason/reason_code（active 路上方清空；
            # 非 active 起复路由 set_character_status 写入起复缘由）——回读刷回内存 Character，
            # 否则非 active 起复后内存滞留旧削籍/下狱缘由，DB 与内存不一致（5b r3 codex-b R1）。
            _reason_row = db.conn.execute(
                "SELECT status_reason, reason_code FROM characters WHERE name=?", (name,)
            ).fetchone()
            if _reason_row is not None:
                ch.status_reason = str(_reason_row["status_reason"] or "")
                ch.reason_code = str(_reason_row["reason_code"] or "")
            ch.office = normalize_office(new_office)
            ch.office_type = infer_office_type_from_office(ch.office, new_office_type or ch.office_type, llm_config)
            if registry is not None:
                registry.refresh(name)
                # 被顶替者 office/office_type 也变了,一并刷 Agent,免本回合后续用陈旧身份/工具(线上 gemini)。
                for dp in displaced_parts:
                    registry.refresh(dp.split(":")[0])
        except Exception as exc:
            _restore_person_write_state(db, content, snapshot)
            return {"name": name, "new_office": new_office, "rejected": True, "reason": f"落库失败：{exc}"}
        return {
            "name": name, "old_status": cur_status, "old_office": old_office, "new_office": new_office,
            "kind": "transfer", "reason": reason,
            **({"displaced": displaced_parts} if displaced_parts else {}),
        }
    # ── 新任：建新档（apply_appointment 对在册者会拒，故仅不在册走到这）──
    if content is None:
        return {"name": name, "new_office": new_office, "rejected": True, "reason": "无 content，跳过建档"}
    from ming_sim.session import apply_appointment  # 延迟导入避循环
    appt = {"name": name, "office": new_office, "faction": faction, "reason": reason, "approved": True}
    # 建档抛错(DB 锁/唯一约束/注册失败)不得上抛崩月末结算致半落库(P1 铁律);
    # 与 in_roster 分支同样兜成 rejected、把 exc 记进 reason(不静默吞)(线上 gemini high)。
    snapshot = _snapshot_person_write_state(db, content)
    try:
        appointed, _ = apply_appointment(db, state, content, registry, appt, llm_config=llm_config)
        if appointed:
            # 新任也按 office 文字去重(与 transfer 分支对称):新人占独占实职,从他人剔同名分项,
            # 免占缺旧任者留旧官成双缺官(CMR R4：去 replaces 后新任分支漏了顶替)。
            # displaced 统一取 _displace_duplicate_offices 的 List[str](apply_appointment 的单名
            # displaced 在去 replaces 后恒空,留着会让本字段时而 str 时而 list,故弃)(线上 gemini)。
            displaced_parts = _displace_duplicate_offices(db, content, appointed, new_office)
            # 被顶替者一并刷 Agent(新任者 apply_appointment 内已注册)(线上 gemini)。
            if registry is not None:
                for dp in displaced_parts:
                    registry.refresh(dp.split(":")[0])
            return {"name": appointed, "new_office": new_office, "kind": "appoint", "reason": reason,
                    **({"displaced": displaced_parts} if displaced_parts else {})}
    except Exception as exc:
        _restore_person_write_state(db, content, snapshot)
        return {"name": name, "new_office": new_office, "rejected": True, "kind": "appoint",
                "reason": f"落库失败：{exc}；原 status={cur_status or '不在册'}"}
    # apply_appointment 返回假值（查重拒/approved false/字段空——现均改库前早退）：防御性还原快照、
    # 与 except 路对称，确保此分支在任何 apply_appointment 行为下都不留半落库（P1 第一铁律，线上 gemini R3）。
    _restore_person_write_state(db, content, snapshot)
    return {"name": name, "new_office": new_office, "rejected": True, "kind": "appoint",
            "reason": f"建档失败（查重/字段不合）；原 status={cur_status or '不在册'}"}


def _apply_person_changes(
    db: GameDB,
    state: GameState,
    changes: List[Dict[str, object]],
    content=None,
    registry=None,
    llm_config: Any = None,
    source: str = "system_simulation",
    derived_from: str = "",
    allow_legacy_partial_power: bool = False,
) -> List[Dict[str, object]]:
    def rejected(
        item: Dict[str, object],
        reason: str,
        category: str,
        *,
        status: str | None = None,
    ) -> Dict[str, object]:
        result: Dict[str, object] = {
            "name": str(item.get("name") or "").strip(),
            "动作": str(item.get("动作") or "").strip(),
            "rejected": True,
            "reason": reason,
            "category": category,
            "item": dict(item),
        }
        if status is not None:
            result["status"] = status
        return result

    def character_row(name: str):
        return db.conn.execute(
            "SELECT name, status, office, office_type, power_id, status_reason, "
            "status_changed_turn, reason_code, transit_to FROM characters WHERE name=?",
            (name,),
        ).fetchone()

    def log_applied(result: Dict[str, object], item: Dict[str, object]) -> None:
        if result.get("rejected"):
            return
        name = str(result.get("name") or "").strip()
        action = str(result.get("动作") or result.get("action") or "").strip()
        if not name or not action:
            return
        if db.conn.execute("SELECT 1 FROM characters WHERE name=?", (name,)).fetchone() is None:
            return
        summary = (
            str(result.get("reason") or item.get("reason") or "")
            or str(result.get("new_office") or result.get("office") or "")
            or str(result.get("status") or result.get("new_power") or result.get("transit_to") or "")
        )
        normalized = {
            key: value
            for key, value in result.items()
            if key not in {"rejected", "category", "item"}
        }
        db.record_person_log(
            state,
            name,
            action,
            payload_summary=summary,
            derived_from=str(result.get("derived_from") or derived_from or ""),
            normalized=normalized,
            source=source,
        )

    def identity_title_for_allegiance(item: Dict[str, object], new_power: str) -> str:
        title = str(item.get("new_title") or item.get("title") or "").strip()
        if title:
            return title if title in PERSON_IDENTITY_TITLES else ""
        way = str(item.get("方式") or item.get("way") or "").strip()
        if new_power == "ming" or way == "主动归附":
            return "归附"
        return "降臣"

    def displaced_talent_pool_results(displaced_parts: object) -> List[Dict[str, object]]:
        if not isinstance(displaced_parts, list):
            return []
        results: List[Dict[str, object]] = []
        for part in displaced_parts:
            name_part = str(part).split(":", 1)[0].strip()
            if not name_part:
                continue
            row = character_row(name_part)
            if row is None:
                continue
            if str(row["office"] or "") != "听用候铨" or str(row["reason_code"] or "") != "被顶替":
                continue
            results.append(
                {
                    "name": name_part,
                    "动作": "处置",
                    "status": "active",
                    "reason": "被顶替",
                    "reason_code": "被顶替",
                    "office": "听用候铨",
                    "office_type": "身名分",
                    "derived_from": "被顶替",
                }
            )
        return results

    applied: List[Dict[str, object]] = []
    person_statuses = {
        "active",
        "candidate",
        "offstage",
        "dismissed",
        "imprisoned",
        "exiled",
        "retired",
        "dead",
    }
    disposition_statuses = person_statuses - {"active", "candidate"}
    for item in changes:
        name = str(item.get("name") or "").strip()
        action = str(item.get("动作") or "").strip()
        if not name or not action:
            applied.append(rejected(item, "name 或 动作 缺失", "missing_field"))
            continue

        if action in {"处置", "罢黜"}:
            status = "dismissed" if action == "罢黜" else str(item.get("status") or "").strip()
            reason_text = str(item.get("reason") or item.get("status_reason") or "")
            if status not in person_statuses:
                applied.append(rejected(item, "status 非白名单", "invalid_enum", status=status))
                continue
            if status not in disposition_statuses:
                applied.append(
                    rejected(
                        item,
                        "处置 不直接迁入 active/candidate，走任命/册封级联",
                        "invalid_transition",
                        status=status,
                    )
                )
                continue
            if content is not None and name not in content.characters:
                applied.append(rejected(item, "非既有人物", "hallucinated_id", status=status))
                continue
            row = db.conn.execute("SELECT name FROM characters WHERE name=?", (name,)).fetchone()
            if row is None:
                applied.append(rejected(item, "非既有人物", "hallucinated_id", status=status))
                continue
            cur_status, _ = db.get_character_status(name)
            if item.get("legacy_gate") and cur_status != "active":
                reject_reason = f"当前非 active（{cur_status}）"
                if cur_status == "dead" and status != "dead":
                    reject_reason = "dead 无 status 出边"
                applied.append(
                    rejected(
                        item,
                        reject_reason,
                        "invalid_transition",
                        status=status,
                    )
                )
                continue
            reason_code = normalize_reason_code(item.get("reason_code"))
            transition = resolve_person_transition(
                cur_status,
                action,
                reason_code=reason_code,
            )
            if transition.startswith("reject:"):
                reject_reason = f"{cur_status} 无 {action} 出边"
                if cur_status == "dead" and status != "dead":
                    reject_reason = "dead 无 status 出边"
                applied.append(
                    rejected(
                        item,
                        reject_reason,
                        transition.removeprefix("reject:") or "invalid_transition",
                        status=status,
                    )
                )
                continue
            db.set_character_status(
                state,
                name,
                status,
                reason_text,
                reason_code=reason_code if reason_code else None,
            )
            if content is not None and name in content.characters:
                ch = content.characters[name]
                ch.status = status
                ch.status_reason = reason_text
                ch.reason_code = str(reason_code or "")
                if status in {"offstage", "dismissed", "imprisoned", "exiled", "retired", "dead"}:
                    ch.office = ""
                    ch.transit_to = ""
            result = {
                "name": name,
                "动作": action,
                "status": status,
                "reason": reason_text,
            }
            if reason_code:
                result["reason_code"] = reason_code
            applied.append(result)
            log_applied(result, item)
            continue

        if action in {"任命", "调任"}:
            # 别名归一须在 hallucinated_id 闸前：extractor 可能用在册大臣 alias（韩阁老→韩爌），
            # 仅按确切 key 判在册会把别名任命误拒成 hallucinated_id、玩家指令丢失（旧 office_changes
            # 路直调含归一的 apply_office_appointment 无此退化）。与下游归一同源（线上 codex R3 P2）。
            if content is not None:
                from ming_sim.session import _find_existing_minister
                _canon = _find_existing_minister(content, name)
                if _canon:
                    name = _canon
            if content is not None and name not in content.characters:
                applied.append(rejected(item, "非既有人物", "hallucinated_id"))
                continue
            row = character_row(name)
            if row is None:
                applied.append(rejected(item, "非既有人物", "hallucinated_id"))
                continue
            current_office = str(row["office"] or "").strip()
            current_office_type = str(row["office_type"] or "").strip()
            current_title_kind = (
                "身名分"
                if not current_office
                or current_office_type == "身名分"
                or current_office in PERSON_IDENTITY_TITLES
                else "职名分"
            )
            transition = resolve_person_transition(
                str(row["status"] or "active"),
                action,
                reason_code=str(row["reason_code"] or item.get("reason_code") or ""),
                current_title_kind=current_title_kind,
            )
            if transition.startswith("reject:"):
                applied.append(
                    rejected(
                        item,
                        f"{row['status']} 无 {action} 出边",
                        transition.removeprefix("reject:") or "invalid_transition",
                    )
                )
                continue
            derive_label = transition.removeprefix("derive:") if transition.startswith("derive:") else ""
            effective_action = transition.removeprefix("normalize:") if transition.startswith("normalize:") else action
            new_office = str(item.get("office") or item.get("new_office") or "")
            if not new_office.strip():
                result = rejected(item, "name 或 new_office 空", "missing_field")
                result["new_office"] = new_office
                if transition.startswith("normalize:"):
                    result["normalized"] = f"{action}->{effective_action}"
                applied.append(result)
                continue
            if content is None:
                result = {
                    "动作": effective_action,
                    **apply_office_appointment(
                        db,
                        state,
                        content,
                        registry,
                        name,
                        new_office,
                        reason=str(item.get("reason") or ""),
                        new_office_type=str(item.get("office_type") or item.get("new_office_type") or ""),
                        faction=str(item.get("faction") or "中立"),
                        llm_config=llm_config,
                    ),
                }
                if transition.startswith("normalize:"):
                    result["normalized"] = f"{action}->{effective_action}"
                applied.append(result)
                continue
            row_power_id = str(row["power_id"] or "").strip()
            content_power_id = ""
            if content is not None and name in content.characters:
                content_power_id = str(getattr(content.characters[name], "power_id", "") or "").strip()
            effective_power_id = row_power_id or content_power_id or "ming"
            if effective_power_id != "ming":
                result = rejected(
                    item,
                    f"{name}不属大明朝廷，不能授予大明官职",
                    "invalid_transition",
                )
                result["new_office"] = new_office.strip()
                if transition.startswith("normalize:"):
                    result["normalized"] = f"{action}->{effective_action}"
                applied.append(result)
                continue
            if derive_label:
                release_status = "offstage" if derive_label in {"放归", "赦还"} else "active"
                # 必要前置（放归/赦还）执行 status 迁移原语（→offstage 居家），再由任命级联置 active。
                # 政治标记（起复/昭雪/夺情）为纯审计记录、不迁移 status（决定4）——status→active+绑名分
                # 由下面 apply_office_appointment 原子完成，避免「先置 active、名分未绑」的中间态（不变式1 全程成立）。
                if derive_label in {"放归", "赦还"}:
                    db.set_character_status(
                        state,
                        name,
                        release_status,
                        derive_label,
                        reason_code="",
                    )
                    if content is not None and name in content.characters:
                        ch = content.characters[name]
                        ch.status = release_status
                        ch.office = ""
                        ch.transit_to = ""
                release_result = {
                    "name": name,
                    "动作": "处置",
                    "status": release_status,
                    "reason": derive_label,
                    "derived_from": derive_label,
                }
            result = apply_office_appointment(
                db,
                state,
                content,
                registry,
                name,
                new_office,
                reason=str(item.get("reason") or ""),
                new_office_type=str(item.get("office_type") or item.get("new_office_type") or ""),
                faction=str(item.get("faction") or "中立"),
                llm_config=llm_config,
            )
            wrapped = {"动作": effective_action, **result}
            if derive_label:
                wrapped["derived_from"] = derive_label
                if wrapped.get("rejected"):
                    db.conn.execute(
                        "UPDATE characters SET status=?, office=?, office_type=?, "
                        "status_reason=?, status_changed_turn=?, reason_code=?, transit_to=? "
                        "WHERE name=?",
                        (
                            row["status"],
                            row["office"],
                            row["office_type"],
                            row["status_reason"],
                            row["status_changed_turn"],
                            row["reason_code"],
                            row["transit_to"],
                            name,
                        ),
                    )
                    db.conn.commit()
                    if content is not None and name in content.characters:
                        ch = content.characters[name]
                        ch.status = str(row["status"] or "")
                        ch.office = str(row["office"] or "")
                        ch.office_type = str(row["office_type"] or ch.office_type)
                        ch.transit_to = str(row["transit_to"] or "")
                        # 对称 DB 侧回滚（上方 UPDATE 已还原全 7 字段）：内存也还原缘由/码，
                        # 守三面同步（决定6），免前置步刷过内存缘由后此路回滚留脏值（PR#106 R2 gemini）。
                        ch.status_reason = str(row["status_reason"] or "")
                        ch.reason_code = str(row["reason_code"] or "")
                else:
                    applied.append(release_result)
                    log_applied(release_result, item)
            elif transition.startswith("normalize:"):
                wrapped["normalized"] = f"{action}->{effective_action}"
            applied.append(wrapped)
            log_applied(wrapped, item)
            for displacement_result in displaced_talent_pool_results(wrapped.get("displaced")):
                applied.append(displacement_result)
                log_applied(displacement_result, item)
            continue

        if action == "易主":
            way = str(item.get("方式") or item.get("way") or "").strip()
            backlash = item.get("反噬", item.get("backlash"))
            legacy_partial = allow_legacy_partial_power and bool(item.get("legacy_partial"))
            if not way:
                applied.append(rejected(item, "易主 缺 方式", "missing_field"))
                continue
            if way not in PERSON_ALLEGIANCE_CHANGE_WAYS and not legacy_partial:
                applied.append(rejected(item, "易主 方式非白名单", "invalid_enum"))
                continue
            if not isinstance(backlash, dict):
                applied.append(rejected(item, "易主 缺 反噬", "missing_field"))
                continue
            if any(not isinstance(raw_changes, dict) for raw_changes in backlash.values()):
                applied.append(rejected(item, "易主 反噬 项必须是 object(dict)", "invalid_enum"))
                continue
            row = character_row(name)
            if row is None:
                applied.append(rejected(item, "非既有人物", "hallucinated_id"))
                continue
            transition = resolve_person_transition(
                str(row["status"] or "active"),
                action,
                reason_code=str(row["reason_code"] or item.get("reason_code") or ""),
            )
            if transition.startswith("reject:"):
                applied.append(
                    rejected(
                        item,
                        f"{row['status']} 无 {action} 出边",
                        transition.removeprefix("reject:") or "invalid_transition",
                    )
                )
                continue
            requested_new_power = str(item.get("new_power") or "")
            new_title = identity_title_for_allegiance(item, requested_new_power)
            if not new_title:
                applied.append(
                    rejected(
                        item,
                        "易主 new_title 非身名分白名单",
                        "invalid_enum",
                    )
                )
                continue
            power_results = db.apply_character_power_changes(
                [
                    {
                        "name": name,
                        "new_power": requested_new_power,
                        "reason": str(item.get("reason") or ""),
                    }
                ]
            )
            if not power_results:
                applied.append(rejected(item, "易主 未产生变更", "noop"))
                continue
            accepted_power_results = [r for r in power_results if not r.get("rejected")]
            if not accepted_power_results:
                for result in power_results:
                    wrapped = {"动作": action, "方式": way, "反噬": backlash, **result}
                    if wrapped.get("rejected"):
                        wrapped["item"] = dict(item)
                    applied.append(wrapped)
                continue
            backlash_results = db.apply_power_deltas(state, backlash) if backlash else []
            for result in power_results:
                new_power = str(result.get("new_power") or "")
                if (
                    not result.get("rejected")
                    and content is not None
                    and result.get("name") in content.characters
                ):
                    ch = content.characters[str(result["name"])]
                    ch.power_id = new_power
                    ch.office = new_title
                    ch.office_type = "身名分"
                    ch.status = "active"
                    ch.transit_to = ""
                    ch.reason_code = ""
                    ch.status_reason = str(item.get("reason") or "")
                # 易主后人仍 active（在新主任事，持身名分=降臣/归附），不变式1 不破；清原 reason_code/
                # status_reason（如陷虏「松山兵败被执」）——已投敌、不再是本朝在押，旧因不能滞留（决定3）；
                # status_changed_turn 记本回合（易主即状态变更）。
                db.conn.execute(
                    "UPDATE characters SET office=?, office_type=?, status='active', "
                    "reason_code='', status_reason=?, status_changed_turn=?, transit_to='' WHERE name=?",
                    (new_title, "身名分", str(item.get("reason") or ""), state.turn, name),
                )
                db.conn.commit()
                wrapped = {"动作": action, "方式": way, "反噬": backlash, **result}
                wrapped["new_title"] = new_title
                if any(r.get("rejected") for r in backlash_results if isinstance(r, dict)):
                    wrapped["backlash_results"] = backlash_results
                applied.append(wrapped)
                log_applied(wrapped, item)
            continue

        if action == "册封":
            if content is None:
                applied.append(rejected(item, "无 content，跳过册封", "missing_ref"))
                continue
            office = str(item.get("office") or item.get("位号") or "").strip()
            office_type = str(item.get("office_type") or item.get("官署类别") or "后宫").strip()
            if office_type != "后宫":
                applied.append(rejected(item, "册封 仅适用于后宫 office_type", "invalid_transition"))
                continue
            from ming_sim.session import _find_candidate_by_name, apply_appointment

            if _find_candidate_by_name(content, name) is None:
                if item.get("legacy_appointment"):
                    applied.append(rejected(item, "册封建档被拒", "appointment_rejected"))
                else:
                    applied.append(rejected(item, "非既有 candidate", "hallucinated_id"))
                continue

            approved = item.get("approved", item.get("准许", True))
            appointed, displaced = apply_appointment(
                db,
                state,
                content,
                registry,
                {
                    "name": name,
                    "office": office,
                    "office_type": "后宫",
                    "faction": "后宫",
                    "reason": str(item.get("reason") or ""),
                    "approved": approved,
                },
                llm_config=llm_config,
            )
            if appointed:
                result: Dict[str, object] = {
                    "name": appointed,
                    "动作": action,
                    "office": office,
                    "office_type": "后宫",
                    "reason": str(item.get("reason") or ""),
                }
                if displaced:
                    result["displaced"] = displaced
                applied.append(result)
                log_applied(result, item)
            else:
                applied.append(rejected(item, "册封建档被拒", "appointment_rejected"))
            continue

        if action == "行止":
            new_location = str(item.get("location") or "").strip()
            transit_to = str(item.get("transit_to") or "").strip()
            if not new_location and not transit_to:
                applied.append(rejected(item, "location 或 transit_to 缺失", "missing_field"))
                continue
            if content is not None and name not in content.characters:
                applied.append(rejected(item, "非既有人物", "hallucinated_id"))
                continue
            row = db.conn.execute(
                "SELECT status, location FROM characters WHERE name=?", (name,)
            ).fetchone()
            if row is None:
                applied.append(rejected(item, "非既有人物", "hallucinated_id"))
                continue
            if row["status"] != "active":
                applied.append(
                    rejected(item, "行止 仅适用于 active 人物", "invalid_transition")
                )
                continue
            for field_name, region_id in (
                ("location", new_location),
                ("transit_to", transit_to),
            ):
                if not region_id:
                    continue
                region_row = db.conn.execute(
                    "SELECT 1 FROM regions WHERE id=?", (region_id,)
                ).fetchone()
                if region_row is None:
                    applied.append(
                        rejected(item, f"{field_name} 地区不存在", "missing_ref")
                    )
                    break
            else:
                location = new_location or str(row["location"] or "")
                db.conn.execute(
                    "UPDATE characters SET location=?, transit_to=? WHERE name=?",
                    (location, transit_to, name),
                )
                db.conn.commit()
                if content is not None and name in content.characters:
                    ch = content.characters[name]
                    ch.location = location
                    ch.transit_to = transit_to
                applied.append(
                    result := {
                        "name": name,
                        "动作": action,
                        "location": location,
                        "transit_to": transit_to,
                    }
                )
                log_applied(result, item)
            continue

        applied.append(
            rejected(item, "人物变更动作写路径未接", "invalid_transition")
        )
    return applied


def _legacy_person_report_section(result: Dict[str, object]) -> str:
    item = result.get("item")
    source = item if isinstance(item, dict) else result
    action = str(source.get("动作") or source.get("action") or result.get("动作") or "").strip()
    if source.get("legacy_gate"):
        return "character_status_changes"
    if source.get("legacy_partial"):
        return "character_power_changes"
    if source.get("legacy_spillover"):
        return "office_changes"
    if action == "册封":
        return "appointments"
    if action in {"任命", "调任"}:
        return "office_changes"
    return ""


def apply_score_extraction(
    db: GameDB,
    state: GameState,
    extracted: Dict[str, object],
    content=None,
    registry=None,
    llm_config: Any = None,
) -> Dict[str, object]:
    """落地结算 agent 输出的 JSON 到 state 与 db。

    content/registry：若传入则处理 `appointments`——把诏书任命的新人建档入朝。
    缺省则跳过（向后兼容老调用）。"""
    # 0) 落库前校验容器/二级类型,畸形值崩前拦住,不让前面字段半落库(#57)。
    validate_delta_shape(extracted)
    new_person_changes = normalize_person_changes({"人物变更": extracted.get("人物变更") or []})
    legacy_person_changes = [] if new_person_changes else normalize_person_changes({
        "appointments": extracted.get("appointments") or [],
        "character_status_changes": extracted.get("character_status_changes") or [],
        "character_power_changes": extracted.get("character_power_changes") or [],
        "office_changes": extracted.get("office_changes") or [],
    })
    person_changes = new_person_changes or legacy_person_changes
    use_legacy_person_keys = not person_changes

    def _annotate_legacy_person_rejections(results: List[Dict[str, object]]) -> None:
        for result in results:
            if isinstance(result, dict) and result.get("rejected"):
                report_section = _legacy_person_report_section(result)
                if report_section:
                    result["report_section"] = report_section
                    if (
                        report_section == "character_power_changes"
                        and result.get("category") == "hallucinated_id"
                    ):
                        result["report_category"] = "missing_ref"

    applied_person_changes: List[Dict[str, object]] = []
    # 1) metric_delta
    applied_metric = _apply_metric_dict(state, extracted.get("metric_delta") or {}, db=db)
    # 2) economy_moves
    applied_economy = _apply_economy_list(db, state, extracted.get("economy_moves") or [])
    # 3) faction_delta + class_delta（朝堂派系 + 社会阶级；联动靠 LLM，不在代码做）
    applied_factions = _apply_faction_dict(db, extracted.get("faction_delta") or {})
    applied_classes = _apply_class_dict(db, extracted.get("class_delta") or {})
    # 4) new_armies → region_delta / army_delta (复用旧 db 方法)
    region_deltas_raw = extracted.get("region_delta") or {}
    army_deltas_raw = extracted.get("army_delta") or {}
    new_armies_raw = extracted.get("new_armies") or []

    pseudo_event = Event(
        id="season",
        title="月末整体推演",
        kind="月末",
        summary="",
        urgency=0,
        severity=0,
        credibility=100,
        interests=[],
        audiences=[],
    )
    region_changes: List[Dict[str, object]] = []
    army_changes: List[Dict[str, object]] = []
    created_armies: List[Dict[str, object]] = []
    # 先建军：避免同回合 army_delta 引用新军被跳过。
    # ADR 0008 决定 1（PR2-S2）：LLM 脏数据（查无此地/此军、字段非法、值不可解析）在
    # 三个 db 方法内逐项拒收留痕（返回列表含 {"rejected": True, ...}，桥接自动收进
    # rejection_reports），好项照落、坏一项不带走整批；代码异常（bug 类）仍上抛到 settle
    # 层回滚整批，绝不吞。clamp 语义（城防炮 city_level×8、随军炮 cap12、火器 0-100）不变。
    if isinstance(new_armies_raw, list) and new_armies_raw:
        created_armies = db.create_armies_from_extraction(state, new_armies_raw, actor="档房")
    if isinstance(region_deltas_raw, dict) and region_deltas_raw:
        region_changes = db.apply_region_deltas(state, pseudo_event, None, "档房", region_deltas_raw)
    if isinstance(army_deltas_raw, dict) and army_deltas_raw:
        army_changes = db.apply_army_deltas(state, pseudo_event, None, "档房", army_deltas_raw)

    # 注：建筑的新建/变更/废止不走顶层字段，全由 issue 的 effect_on_resolve /
    #     effect_on_fail 里的 `buildings` 段在局势结案时落地（见 _apply_issue_buildings）。

    # 5) power_updates：非明势力三项简表（威望/实力/经济）落库
    # ADR 0008 决定 1:不再整段吞——LLM 脏数据(未知 power id/字段非法)在
    # apply_power_deltas 内逐项拒收留痕(返回列表含 {"rejected": True, ...});
    # 代码异常(KeyError/AttributeError 等)上抛到 settle 层回滚整批,绝不吞。
    power_updates_raw = extracted.get("power_updates") or {}
    power_changes: List[Dict[str, object]] = []
    if isinstance(power_updates_raw, dict) and power_updates_raw:
        power_changes = db.apply_power_deltas(state, power_updates_raw)

    # 6) issue_advances / new_issues / close_issues / cancels (复用旧 tracker 落地)
    issue_summary = apply_issue_tracker_output(db, state, {
        "advances": extracted.get("issue_advances") or [],
        "new_issues": extracted.get("new_issues") or [],
        "close_issues": extracted.get("close_issues") or [],
        "cancels": extracted.get("cancels") or [],
    }, llm_config=llm_config, content=content)
    if new_person_changes:
        applied_person_changes.extend(
            _apply_person_changes(
                db,
                state,
                new_person_changes,
                content=content,
                registry=registry,
                llm_config=llm_config,
            )
        )
    elif legacy_person_changes:
        legacy_applied_person_changes = _apply_person_changes(
            db,
            state,
            legacy_person_changes,
            content=content,
            registry=registry,
            llm_config=llm_config,
            allow_legacy_partial_power=True,
        )
        _annotate_legacy_person_rejections(legacy_applied_person_changes)
        applied_person_changes.extend(legacy_applied_person_changes)

    def _norm_int_leaf(v):
        """无损整数串归一（cmr S3 r10,2/2）：strip 后能精确 int 的 str 转 int,
        其余原样返回。无损归一在 cleaner（引擎路）与此处（driver 路）各一次,
        **判定语义只在 applier**（ship-pre r1 措辞修正:cleaner 残留的同式转换
        与本函数同结果,见 S3 disposition「无害重复」）。"""
        if isinstance(v, str):
            try:
                return int(v.strip())
            except ValueError:
                return v
        return v

    # 6.4) fiscal_removes：推演彻底裁撤月固定收支项（罢税/裁俸），优先级最高，先于 creates/changes。
    #      含 dynamic（田赋/辽饷/盐税/商税/皇庄），后果玩家自负。删 base+rate 两行。
    applied_fiscal_removes: List[Dict[str, object]] = []
    for remove in extracted.get("fiscal_removes") or []:
        key = str(remove.get("key") or "").strip()
        if not key:
            # 空 key = 脏项,记拒留痕(不再纯静默 continue;ADR 决定 1 / S3)。
            applied_fiscal_removes.append({
                "rejected": True, "reason": "fiscal_removes 缺 key,无法定位裁撤目标。",
                "category": "invalid_enum", "item": remove,
            })
            continue
        if db._stem_of(key) == "":
            # 多重后缀垃圾 key = 非法,与 create 段同口径 invalid_enum——误标
            # missing_ref「不存在」会让机读聚合失真（cmr S3 r10）。
            applied_fiscal_removes.append({
                "rejected": True, "reason": f"裁撤 key「{key}」非法（多重 _base/_rate 后缀）。",
                "category": "invalid_enum", "item": remove,
            })
            continue
        removed_key = db.remove_fiscal_item(key)
        if removed_key is None:
            # 查无此项 = 正常业务拒绝,逐项拒收留痕(不再 print 静默跳;ADR 决定 1 / S3)。
            applied_fiscal_removes.append({
                "rejected": True, "reason": f"裁撤目标「{key}」不存在,跳过。",
                "category": "missing_ref", "item": remove,
            })
            continue
        applied_fiscal_removes.append({
            "key": removed_key, "reason": str(remove.get("reason") or ""),
        })

    # 6.5) fiscal_creates：推演凭空新立月固定收支项（税是其一种）。先于 fiscal_changes，
    #      使同{月}「新立关税 + 立即调率」可一气落地。
    applied_fiscal_creates: List[Dict[str, object]] = []
    for create in extracted.get("fiscal_creates") or []:
        key = str(create.get("key") or "").strip()
        account = str(create.get("account") or "").strip()
        # direction 同义词在唯一守门人处归一（cmr S3 r9:归一放 driver 不经过的
        # cleaner 层=同输入两判;DELTA_SCHEMA 明言吃中文别名）。表与 cleaner 共用
        # simulation._DIRECTION_NORMALIZE（懒 import 避循环）。
        from ming_sim.simulation import _DIRECTION_NORMALIZE
        direction_raw = str(create.get("direction") or "").strip()
        direction = _DIRECTION_NORMALIZE.get(direction_raw, direction_raw)
        # key 空 / account / direction 非法 = 脏枚举,原先纯静默 continue,改记拒留痕
        # （ADR 决定 1 / S3；「在场即须合法」对称 S1/S2）。
        if not key or account not in _FISCAL_ACCOUNTS or direction not in _FISCAL_DIRECTIONS:
            applied_fiscal_creates.append({
                "rejected": True,
                "reason": f"新立项枚举非法（key={key!r} account={account!r} direction={direction!r}）。",
                "category": "invalid_enum", "item": create,
            })
            continue
        # init_value 缺省/null = 0 合法；在场脏值（字符串/float/bool/负值）显式拒，不静默归 0。
        # bool 是 int 子类，先于 int 判（对称 S1/S2）。
        init_raw = _norm_int_leaf(create.get("init_value"))  # 无损整数串归一（cmr S3 r10）
        if init_raw is None:
            init_value = 0
        elif isinstance(init_raw, bool) or not isinstance(init_raw, int) or init_raw < 0:
            # 负值同拒：静默 clamp 0 = 又一面「凭空建零值项」（cmr S3 r3）。
            applied_fiscal_creates.append({
                "rejected": True,
                "reason": f"新立项「{key}」初值 init_value 非法（{init_raw!r}，须非负整数），不静默归 0。",
                "category": "invalid_enum", "item": create,
            })
            continue
        else:
            init_value = init_raw
        # display 缺省=归一 stem（与落库同源——raw key 去 _base 会把「关税_rate」
        # 显示成「关税_rate」,cmr S3 r11;DELTA_SCHEMA 契约「缺省=key 去后缀」）。
        display = str(create.get("display") or "").strip() or (db._stem_of(key) or key)
        new_key = db.create_fiscal_item(
            key, account, direction, display, init_value,
            note=str(create.get("reason") or "")[:120],
        )
        if new_key is None:
            # 已存在 / db 拒 = 正常业务拒绝,逐项拒收留痕（不再 print 静默跳）。
            applied_fiscal_creates.append({
                "rejected": True,
                "reason": f"新立项「{key}」已存在或被落库拒绝,跳过。",
                "category": "invalid_enum", "item": create,
            })
            continue
        applied_fiscal_creates.append({
            "key": new_key, "account": account, "direction": direction,
            "display": display, "init_value": max(0, init_value),
            "reason": str(create.get("reason") or ""),
        })

    # 7) fiscal_changes：调整月度固定收支系数
    applied_fiscal: List[Dict[str, object]] = []
    for change in extracted.get("fiscal_changes") or []:
        key = str(change.get("key") or "").strip()
        if not key:
            # 空 key = 脏项,先于一切无操作短路记拒——否则 delta 0/null 的空 key 项
            # 被短路吞掉无痕（与 falsy 短路同类序错,cmr S3 r2）。
            applied_fiscal.append({
                "rejected": True,
                "reason": "调率项缺 key,无法定位科目。",
                "category": "invalid_enum", "item": change,
            })
            continue
        if db._stem_of(key) == "":
            # 多重后缀垃圾 key 与 create/remove 同口径 invalid_enum——标 missing_ref
            # 「不存在」会让机读聚合失真（ship-pre r5,三段补齐）。
            applied_fiscal.append({
                "rejected": True,
                "reason": f"调率 key「{key}」非法（多重 _base/_rate 后缀）。",
                "category": "invalid_enum", "item": change,
            })
            continue
        delta_raw = _norm_int_leaf(change.get("delta"))  # 无损整数串归一（cmr S3 r10）
        # delta 缺省 = 无操作,静默放过不记拒（免得每月刷无意义拒收行）。
        if delta_raw is None:
            continue
        # 脏值判定必须先于「==0 无操作」短路——False==0 / 0.0==0 为真,放后面会把
        # 脏 bool/float 静默吞掉（cmr S3 r1,顺序与 S1 对称）。
        # delta 在场但脏（字符串/float/bool）= LLM 脏数据,原裸 int() 静默 continue（吞），
        # 改显式拒留痕；bool 是 int 子类,先于 int 判（对称 S1/S2 / S3）。
        if isinstance(delta_raw, bool) or not isinstance(delta_raw, int):
            applied_fiscal.append({
                "rejected": True,
                "reason": f"调率 delta 非整数（{delta_raw!r}），不静默吞。",
                "category": "invalid_enum", "item": change,
            })
            continue
        if delta_raw == 0:
            # 显式 int 0 = 无操作（脏值已在上方拒掉,此处只剩真 int;空 key 已在循环顶记拒）。
            continue
        delta = delta_raw
        current = db.get_fiscal_config().get(key)
        if current is None:
            # 未知 key = 正常业务拒绝,逐项拒收留痕（不再 print 静默跳）。
            applied_fiscal.append({
                "rejected": True, "reason": f"调率目标「{key}」不存在,跳过。",
                "category": "missing_ref", "item": change,
            })
            continue
        new_val = max(0, current + delta)
        db.set_fiscal_config(key, new_val)
        # dynamic 税（辽饷/盐税/商税/田赋）实收走 region.fiscal，改 fiscal_config 不生效；
        # 按 new/old 比例同步缩放各省实收字段，使调额当真改变下月入账。皇庄读 config，无需联动。
        stem = db._stem_of(key)
        if stem in db._DYNAMIC_REGION_FIELD or stem == "田赋":
            ratio = (new_val / current) if current > 0 else (1.0 if new_val == 0 else 0.0)
            if stem == "田赋":
                db.scale_tian_fu(ratio)
            else:
                db.apply_dynamic_fiscal_scale(stem, ratio)
        applied_fiscal.append({
            "key": key, "old": current, "new": new_val, "delta": delta,
            "reason": str(change.get("reason") or ""),
        })

    # 8) appointments：仅收「后宫纳妃」（office_type=后宫）。朝臣的新任/调任已统一
    #    并入 office_changes（section 10），LLM 误把朝臣塞这里的项一律转去 office_changes 处理。
    applied_appointments: List[Dict[str, object]] = []
    spillover_office_changes: List[Dict[str, object]] = []
    if use_legacy_person_keys and content is not None:
        from ming_sim.session import apply_appointment  # 延迟导入避循环
        for item in extracted.get("appointments") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("office_type") or "").strip() != "后宫":
                # 朝臣项转交 office_changes：name + new_office 形态
                spillover_office_changes.append({
                    "name": str(item.get("name") or ""),
                    "new_office": str(item.get("office") or ""),
                    "faction": str(item.get("faction") or "中立"),
                    "reason": str(item.get("reason") or ""),
                })
                continue
            name, displaced = apply_appointment(db, state, content, registry, item, llm_config=llm_config)
            if name:
                applied_appointments.append({
                    "name": name,
                    "office": str(item.get("office") or ""),
                    "faction": str(item.get("faction") or "中立"),
                    "reason": str(item.get("reason") or ""),
                    "displaced": displaced,
                })
            else:
                rejected_name = str(item.get("name") or "").strip()
                if rejected_name:
                    approved = bool(item.get("approved", True))
                    applied_appointments.append({
                        "name": rejected_name,
                        "office": str(item.get("office") or ""),
                        "rejected": True,
                        # reason=拒收原因（apply_appointment 不回传具体因，枚举已知拒因；
                        # LLM 的任命理由另存 appointment_reason，不顶替拒因——cmr S0 r3）。
                        "reason": ("未获准（approved=false）" if not approved
                                   else "纳妃建档被拒（重名/已在册/字段不合）"),
                        "category": "appointment_rejected",
                        "appointment_reason": str(item.get("reason") or ""),
                        "approved": approved,
                    })

    # 9) character_status_changes：LLM 判定的既有大臣去向（罢/狱/流/致仕/死）
    applied_status_changes: List[Dict[str, object]] = []
    valid_status = {"dismissed", "imprisoned", "exiled", "retired", "dead", "offstage"}
    for item in (extracted.get("character_status_changes") or []) if use_legacy_person_keys else []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        status = str(item.get("status") or "").strip().lower()
        reason = str(item.get("reason") or "").strip()
        if not name or status not in valid_status:
            applied_status_changes.append({
                "name": name, "status": status, "rejected": True,
                "reason": "name 空 或 status 非白名单",
            })
            continue
        if content is not None and name not in content.characters:
            applied_status_changes.append({
                "name": name, "status": status, "rejected": True,
                "reason": "非既有大臣或妃嫔（新任走 appointments）",
            })
            continue
        cur_status, _ = db.get_character_status(name)
        if cur_status != "active":
            applied_status_changes.append({
                "name": name, "status": status, "rejected": True,
                "reason": f"当前非 active（{cur_status}）",
            })
            continue
        try:
            db.set_character_status(state, name, status, reason)
        except Exception as exc:
            applied_status_changes.append({
                "name": name, "status": status, "rejected": True, "reason": f"落库失败：{exc}",
            })
            continue
        # 同步 content 内存对象：去职即削职，与 db 清空 office 保持一致
        if content is not None and name in content.characters:
            ch = content.characters[name]
            ch.status = status
            if status in {"offstage", "dismissed", "imprisoned", "exiled", "retired", "dead"}:
                ch.office = ""
            ch.transit_to = ""
        applied_status_changes.append({
            "name": name, "status": status, "reason": reason,
        })

    # 9b) character_power_changes：人物易主（降将/叛臣/归正）
    # ADR 0008 决定 1:不再整段吞——脏数据(查无此人/未知 power/缺字段)在
    # apply_character_power_changes 内逐项拒收留痕;代码异常上抛到 settle 回滚。
    applied_power_changes: List[Dict[str, object]] = db.apply_character_power_changes(
        (extracted.get("character_power_changes") or []) if use_legacy_person_keys else []
    )

    # 10) office_changes：朝臣官职变更——统一吃「新任（建档）」与「调任（改职）」。
    #     extractor 不再分新任/调任，代码按 name 在不在册自判：
    #       在册且未死 → 任命/调任；不在册 → 建新档。
    #     后宫纳妃仍走 appointments（语义不同，见 section 8）。
    #     落地核统一为 apply_office_appointment（与 CLI 自然语言任免 commit 共用，CMR R2 reground）。
    applied_office_changes: List[Dict[str, object]] = []
    # office_changes 本体 + 从 appointments 转来的朝臣项（spillover）
    office_change_items = (
        list(extracted.get("office_changes") or []) + spillover_office_changes
        if use_legacy_person_keys
        else []
    )
    for item in office_change_items:
        if not isinstance(item, dict):
            continue
        applied_office_changes.append(apply_office_appointment(
            db, state, content, registry,
            str(item.get("name") or ""), str(item.get("new_office") or ""),
            reason=str(item.get("reason") or ""),
            new_office_type=str(item.get("new_office_type") or ""),
            faction=str(item.get("faction") or "中立"),
            llm_config=llm_config,
        ))

    # 11) secret_order_updates：推演写 active 密令副作用（泄漏/反弹）到 sim_note。结案不走这里。
    applied_secret_orders: List[Dict[str, object]] = []
    for item in extracted.get("secret_order_updates") or []:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("order_id")
        sim_note = str(item.get("sim_note") or item.get("result") or "").strip()
        if raw_id is None or not sim_note:
            applied_secret_orders.append({"order_id": raw_id, "rejected": True,
                                          "reason": "order_id 或 sim_note 缺失"})
            continue
        try:
            real_id = int(raw_id)
        except (TypeError, ValueError):
            applied_secret_orders.append({"order_id": raw_id, "rejected": True, "reason": "order_id 非整数"})
            continue
        try:
            db.update_secret_order_sim_note(
                real_id, sim_note, year=state.year, period=state.period
            )
            print(f"[secret_order] 推演副作用 id={real_id} note={sim_note[:60]!r}")
            applied_secret_orders.append({"order_id": real_id, "sim_note": sim_note})
        except Exception as exc:
            applied_secret_orders.append({"order_id": real_id, "rejected": True, "reason": str(exc)})

    # 12) secret_order_closes：推演给 pending_review 密令最终判定（done/failed），落库结案。
    applied_secret_closes: List[Dict[str, object]] = []
    for item in extracted.get("secret_order_closes") or []:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("order_id")
        status = str(item.get("status") or "").strip().lower()
        result_text = str(item.get("result") or "").strip()
        if status not in {"done", "failed"}:
            applied_secret_closes.append({"order_id": raw_id, "rejected": True,
                                          "reason": f"status 必须 done/failed，得到 {status!r}"})
            continue
        if raw_id is None or not result_text:
            applied_secret_closes.append({"order_id": raw_id, "rejected": True,
                                          "reason": "order_id 或 result 缺失"})
            continue
        try:
            real_id = int(raw_id)
        except (TypeError, ValueError):
            applied_secret_closes.append({"order_id": raw_id, "rejected": True, "reason": "order_id 非整数"})
            continue
        # 仅 pending_review 状态才允许结案；active 不能跳级，done/failed 已结案不重复
        order = db.get_secret_order(real_id)
        if order is None:
            applied_secret_closes.append({"order_id": real_id, "rejected": True, "reason": "密令不存在"})
            continue
        if order["status"] != "pending_review":
            applied_secret_closes.append({"order_id": real_id, "rejected": True,
                                          "reason": f"当前状态 {order['status']}，非 pending_review，不予结案"})
            continue
        try:
            db.close_secret_order(real_id, status, result_text, state.turn)
            print(f"[secret_order] 推演结案 id={real_id} status={status} result={result_text[:60]!r}")
            applied_secret_closes.append({"order_id": real_id, "status": status, "result": result_text})
        except Exception as exc:
            applied_secret_closes.append({"order_id": real_id, "rejected": True, "reason": str(exc)})

    state.clamp()
    return {
        "metric_delta": applied_metric,
        "economy_moves": applied_economy,
        "faction_delta": applied_factions,
        "class_delta": applied_classes,
        "region_changes": region_changes,
        "army_changes": army_changes,
        "created_armies": created_armies,
        "power_changes": power_changes,
        "issue_summary": issue_summary,
        "world_advance": extracted.get("world_advance") or {},
        "fiscal_changes": applied_fiscal,
        "fiscal_creates": applied_fiscal_creates,
        "fiscal_removes": applied_fiscal_removes,
        "appointments": applied_appointments,
        "person_changes": person_changes,
        "applied_person_changes": applied_person_changes,
        "character_status_changes": applied_status_changes,
        "character_power_changes": applied_power_changes,
        "office_changes": applied_office_changes,
        "secret_order_updates": applied_secret_orders,
        "secret_order_closes": applied_secret_closes,
        "pairing_warnings": (issue_summary or {}).get("pairing_warnings") or [],
        "victory_status": _resolve_victory(db, state, extracted),
    }


def _resolve_victory(db: GameDB, state: GameState, extracted: Dict[str, object]) -> Dict[str, object]:
    """结局判定：叙事型（崇祯退位/自尽，extractor 抽 emperor_fate）优先于数值型（京畿失守）。
    20 年到期（timeout）在 decree 结局收口判，不在此。"""
    fate = extracted.get("emperor_fate")
    if fate in ("abdicate", "suicide"):
        if fate == "abdicate":
            return {"status": "emperor_abdicate", "summary": "崇祯帝退位逊国，大明皇统中绝。"}
        return {"status": "emperor_suicide", "summary": "崇祯帝自尽殉国，煤山一缢，大明社稷俱亡。"}
    return victory_status(db, state)


def apply_issue_inertia_and_ongoing(
    db: GameDB,
    state: GameState,
    touched_ids: Optional[set] = None,
    applied_person_changes: Optional[List[Dict[str, object]]] = None,
) -> List[Dict[str, object]]:
    """返回 inertia 自然结案路产生的容忍拒收项——settle 在 inertia 之后补收进
    收集器(桥接跑在 inertia 前,只 tlog 等于这条路脱离 rejection_reports 管线,
    与 tracker-close 路同输入两判;ship-pre r1)。"""
    # inertia 是每月自然漂移基础量，对所有进行中 issue 都生效（含本月被 advance 触动的）。
    # advance 的 delta_bar 是皇帝本月实旨推动的额外量，与 inertia 叠加，互不顶替。
    _ = touched_ids  # 保留入参不破坏调用方；inertia 漂移不再按它跳过
    inertia_rejections: List[Dict[str, object]] = []
    active = db.list_active_issues()
    # 累计单月 metric 落账，用于上限 clamp
    period_metric_acc: Dict[str, int] = {}

    for row in active:
        issue_id = int(row["id"])
        bar = int(row["bar_value"])
        inertia = int(row["inertia"])

        # 1) inertia 漂移：每月对所有进行中 issue 都走一格
        if inertia != 0:
            new_bar = max(0, min(100, bar + inertia))
            actual = new_bar - bar
            if actual != 0:
                new_row = db.advance_issue(
                    state, issue_id,
                    trigger_kind="inertia",
                    delta_bar=actual,
                    stage_text=row["stage_text"],
                    narrative="局势自有其势，本月按其本然推移。",
                    metric_delta={},
                )
                if new_row is None:
                    continue
                if new_row["status"] == "resolved":
                    effect = json.loads(new_row["effect_on_resolve"] or "{}")
                    _emit_pairing_warnings(new_row, effect)  # inertia 路只 tlog（#45/#46）
                    _apply_metric_dict(state, effect.get("metrics") or {}, db=db)
                    _apply_economy_list(db, state, effect.get("economy") or [])
                    _apply_faction_dict(db, effect.get("factions") or {})
                    _apply_issue_buildings(db, state, effect.get("buildings"), _ISSUE_PSEUDO_EVENT, f"局势#{issue_id}结案")
                    # 与 tracker advance/close 路径一致：自然结案也落实体后果 + 帝国修正，
                    # 否则靠 inertia 推到 100 的 issue 会丢 new_armies/army_delta/人物状态/legacy（codexB-P1）。
                    for _tr in _apply_issue_entities(
                        db,
                        state,
                        effect,
                        f"局势#{issue_id}结案",
                        applied_person_changes=applied_person_changes,
                    ):
                        tlog(f"[issue-entities] 容忍拒收：{_tr.get('reason')}")
                        inertia_rejections.append(_tr)
                    _spawn_legacy_from_effect(db, state, effect, issue_id, str(new_row["title"]))
                    continue
                elif new_row["status"] == "failed":
                    effect = json.loads(new_row["effect_on_fail"] or "{}")
                    _apply_metric_dict(state, effect.get("metrics") or {}, db=db)
                    _apply_economy_list(db, state, effect.get("economy") or [])
                    _apply_faction_dict(db, effect.get("factions") or {})
                    _apply_issue_buildings(db, state, effect.get("buildings"), _ISSUE_PSEUDO_EVENT, f"局势#{issue_id}失败")
                    for _tr in _apply_issue_entities(
                        db,
                        state,
                        effect,
                        f"局势#{issue_id}失败",
                        applied_person_changes=applied_person_changes,
                    ):
                        tlog(f"[issue-entities] 容忍拒收：{_tr.get('reason')}")
                        inertia_rejections.append(_tr)
                    _spawn_legacy_from_effect(db, state, effect, issue_id, str(new_row["title"]))
                    continue
                row = db.conn.execute("SELECT * FROM issues WHERE id=?", (issue_id,)).fetchone()
                if row is None:
                    continue
                bar = int(row["bar_value"])

        # 2) ongoing_effects：bar 高时折扣
        ongoing = json.loads(row["ongoing_effects"] or "{}")
        if not ongoing:
            continue
        # 折扣系数：bar 越高（越好）越少扣
        # bar=0~40 → 100%, bar=40~80 → 60%, bar=80~100 → 30%
        if bar >= 80:
            scale = 0.3
        elif bar >= 40:
            scale = 0.6
        else:
            scale = 1.0

        # metrics
        metric_part: Dict[str, int] = {}
        for k, v in (ongoing.get("metrics") or {}).items():
            if k not in ISSUE_METRIC_KEYS:
                continue
            try:
                raw = int(v)
            except (TypeError, ValueError):
                continue
            scaled = int(round(raw * scale))
            if scaled == 0:
                continue
            cap = ISSUE_METRIC_LOCK_CAPS.get(k, 5)
            already = period_metric_acc.get(k, 0)
            remaining = cap - abs(already)
            if remaining <= 0:
                continue
            if scaled > 0:
                allowed = min(scaled, remaining)
            else:
                allowed = max(scaled, -remaining)
            if allowed == 0:
                continue
            state.metrics[k] = int(state.metrics.get(k, 0)) + allowed
            period_metric_acc[k] = already + allowed
            metric_part[k] = allowed

        # economy
        economy_part = _apply_economy_list(db, state, ongoing.get("economy") or [])

        if metric_part or economy_part:
            db.conn.execute(
                """
                INSERT INTO issue_advances (
                    issue_id, turn, trigger_kind, delta_bar,
                    from_value, to_value, narrative, metric_delta
                ) VALUES (?, ?, 'ongoing', 0, ?, ?, ?, ?)
                """,
                (
                    issue_id, state.turn, bar, bar,
                    f"持续效果落账 (折扣 {int(scale*100)}%)",
                    json.dumps({"metrics": metric_part, "economy": economy_part}, ensure_ascii=False),
                ),
            )
            db.conn.commit()

    state.clamp()
    return inertia_rejections


# ── 开局负面帝国修正：不立 issue、不进推演，靠 clear_gate 程序判定消除 ──────────────

def clear_gated_legacies(db: GameDB, state: GameState) -> List[str]:
    """每月调一次：取所有 active 且带 clear_gate 的 legacy，gate 达标即置 'cleared'。
    返回被消除的 legacy 名称列表（供叙事/提示用，不强制使用）。"""
    rows = db.conn.execute(
        "SELECT id, name, clear_gate, narrative_hint FROM legacies "
        "WHERE status='active' AND clear_gate != '' AND clear_gate != '{}'"
    ).fetchall()
    cleared: List[str] = []
    for row in rows:
        try:
            gate = json.loads(str(row["clear_gate"] or "{}"))
        except (ValueError, TypeError):
            gate = {}
        if not gate:
            continue
        if _gate_passed(gate, state.metrics, db):
            db.conn.execute("UPDATE legacies SET status='cleared' WHERE id=?", (int(row["id"]),))
            cleared.append(str(row["name"]))
    if cleared:
        db.conn.commit()
        db._legacy_mod_cache = None  # active 集变了，修正符缓存失效
    return cleared


def sync_opening_legacies(db: GameDB, state: GameState) -> None:
    """开局负面帝国修正落库/校准。新档与读档都调（在 session.__init__ load_state 之后）：
    - 已达 clear_gate：不补；若残留 active 则置 cleared。
    - 未达标：该 legacy_key 不存在 active 行则 insert（永久 duration=-1，仅靠 gate 消除）。
    一个函数覆盖新档（全补）/旧档（补缺）/达标档（不补/清残）。"""
    for leg in _ctx().opening_legacies:
        passed = _gate_passed(leg.clear_gate, state.metrics, db)
        existing = db.conn.execute(
            "SELECT id FROM legacies WHERE legacy_key=? AND status='active'",
            (leg.key,),
        ).fetchone()
        if existing is not None:
            db.conn.execute(
                """UPDATE legacies
                   SET name=?, modifiers=?, narrative_hint=?, clear_gate=?
                   WHERE legacy_key=? AND status='active'""",
                (
                    leg.name,
                    json.dumps(leg.modifiers, ensure_ascii=False),
                    leg.narrative_hint,
                    json.dumps(leg.clear_gate, ensure_ascii=False),
                    leg.key,
                ),
            )
            db.conn.commit()
            db._legacy_mod_cache = None
        if passed:
            if existing is not None:
                db.conn.execute(
                    "UPDATE legacies SET status='cleared' WHERE legacy_key=? AND status='active'",
                    (leg.key,),
                )
                db.conn.commit()
                db._legacy_mod_cache = None
            continue
        # 未达标且无 active 行 → 补上
        if existing is None:
            db.insert_legacy(
                state,
                name=leg.name,
                modifiers=leg.modifiers,
                narrative_hint=leg.narrative_hint,
                duration_months=-1,
                clear_gate=leg.clear_gate,
                legacy_key=leg.key,
            )
