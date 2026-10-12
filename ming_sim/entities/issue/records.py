"""issue 立项/推进/承诺结算的写侧实现：由 issues.py 清算迁入（ADR 0150 决定 8）。"""

from __future__ import annotations
from ming_sim.applier import parse_engine_payload_json

import ming_sim.issues as issues
import ming_sim.entities.issue.effects as issue_effects
import ming_sim.entities.issue.event_terminal as event_terminal

import json
import re
import sqlite3
from typing import Dict, List, Optional

from ming_sim.constants import (
    GATE_TABLES,
)
from ming_sim.db import (
    GameDB,
)
from ming_sim.applier import Provenance, RejectionCollector
from ming_sim.strict_types import strict_int as _strict_int
from ming_sim.models import Event, GameState, effect_dict_has_work, loads_effect_dict


COMMITMENT_KIND_UNTIL_STOP = "until_stop"


def _issue_condition_text(raw: object) -> str:
    """普通叙事原文落库；判空只在调用方局部副本上 strip（#1897 E2）。"""
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, (dict, list)):
        return json.dumps(raw, ensure_ascii=False, separators=(",", ":"))
    return str(raw)


def _normalize_commitment_kind(raw: object) -> str:
    value = str(raw or "").strip().lower()
    if value == COMMITMENT_KIND_UNTIL_STOP:
        return COMMITMENT_KIND_UNTIL_STOP
    return ""


def _validate_commitment_stop_condition(
    raw: object, state: GameState, db: GameDB
) -> str:
    from ming_sim.exceptions import DeclarationDataError

    if not isinstance(raw, dict) or not raw:
        raise DeclarationDataError("stop_condition 须为非空 dict")
    for key, cond in raw.items():
        if not isinstance(key, str) or not key.strip():
            raise DeclarationDataError(f"stop_condition key 非法：{key!r}")
        key = key.strip()
        if "." not in key or key.split(".", 1)[0] not in GATE_TABLES:
            raise DeclarationDataError(f"stop_condition key 须带表前缀：{key!r}")
        if not isinstance(cond, str) or not cond.strip():
            raise DeclarationDataError(
                f"stop_condition value 须把比较算符写在字符串 value 内：{cond!r}"
            )
        cond_text = cond.strip()
        sm = re.match(r"^(==|!=|in=)\s*(.+)$", cond_text)
        if sm and (
            sm.group(1) == "in=" or not re.match(r"^-?\d+$", sm.group(2).strip())
        ):
            if issues._eval_gate_key_str(key, db) is None:
                raise DeclarationDataError(f"stop_condition key 无法寻址：{key!r}")
            continue
        if not re.match(r"^(>=|<=|>|<|==)\s*-?\d+$", cond_text):
            raise DeclarationDataError(f"stop_condition value 非法：{cond!r}")
        if issues._eval_gate_key(key, state.metrics, db) is None:
            raise DeclarationDataError(f"stop_condition key 无法寻址：{key!r}")
    return _issue_condition_text(raw)


def _canonical_issue_origin(db: GameDB, row: sqlite3.Row) -> str:
    """Resolve and authorize one parent issue origin before applying its children.

    Propagate a stored origin_ref when it already authorizes (dossier:/affair:/
    盘面自发). Otherwise follow the issue's affair pointer — ADR 0154: consequences
    without a dossier point at the affair directly. Only true board-spontaneous
    when neither parent is available. No dossier-only rewrite bridge.
    """
    stored_ref = str(row["origin_ref"] or "").strip()
    if stored_ref and db.effect_origin_rejection(stored_ref) is None:
        return stored_ref
    affair_id = int(row["affair_id"] or 0)
    if affair_id:
        origin_ref = db.affairs.origin_ref(affair_id)
    else:
        origin_ref = "盘面自发"
    rejection = db.effect_origin_rejection(origin_ref)
    if rejection:
        raise ValueError(
            f"issue #{row['id']} canonical origin 非法：{rejection['reason']}"
        )
    return origin_ref


def _commitment_stop_gate(row: sqlite3.Row) -> Dict[str, str]:
    """只读显式 stop_condition JSON；不再从 resolve_condition 散文解码。"""
    from ming_sim.models import _load_durable_json_object
    raw = row["stop_condition"]
    if raw == "":
        return {}  # Schema stores a missing stop gate as empty text.
    gate = _load_durable_json_object(raw, surface="issues.stop_condition")
    for key, cond in gate.items():
        if not isinstance(cond, str):
            raise ValueError(f"issues.stop_condition[{key!r}] 须为字符串，得 {type(cond).__name__}")
    return dict(gate)


def _commitment_remaining_from_gate(
    gate: Dict[str, str],
    state: GameState,
    db: GameDB,
) -> Optional[float]:
    remaining = 0.0
    found = False
    for key, cond in gate.items():
        cond_text = str(cond or "").strip()
        m = re.match(r"^(>=|<=|>|<|==)\s*(-?\d+)$", cond_text)
        if not m:
            continue
        val = issues._eval_gate_key(str(key), state.metrics, db)
        if val is None:
            continue
        val_num = float(val)
        op, target = m.group(1), int(m.group(2))
        if op == "<=":
            need = max(0.0, val_num - target)
        elif op == "<":
            need = 0.0 if val_num < target else float(int(val_num - target) + 1)
        elif op == ">=":
            need = max(0.0, target - val_num)
        elif op == ">":
            need = 0.0 if val_num > target else float(int(target - val_num) + 1)
        else:
            need = abs(val_num - target)
        remaining += need
        found = True
    return remaining if found else None


def _latest_commitment_paid_total(db: GameDB, issue_id: int) -> int:
    rows = db.issues.read_latest_commitment_paid_total((issue_id,))
    for row in rows:
        payload = parse_engine_payload_json(
            row["metric_delta"],
        )
        # No progress field on this advance → keep scanning (legal absence → final 0).
        if "commitment_progress" not in payload:
            continue
        progress = payload.get("commitment_progress")
        # Present but not an object = durable shape fault; do not skip-wash to 0 (F39).
        # Missing/empty paid_total → 0 (legal default). Present non-int is shape fault.
        raw = progress.get("paid_total", 0)
        if raw is None or raw == "":
            return 0
        try:
            return int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"commitment_progress.paid_total 非整数：{raw!r}"
            ) from exc
    return 0


def _commitment_gate_references_arrears(row: sqlite3.Row) -> bool:
    return any(".arrears" in str(key) for key in _commitment_stop_gate(row))


def _commitment_arrears_gate_army_ids(row: sqlite3.Row) -> List[str]:
    ids: List[str] = []
    for key in _commitment_stop_gate(row):
        text = str(key)
        match = re.fullmatch(r"army\.([^.]+)\.arrears(?:\.sum)?", text)
        if not match:
            continue
        for army_id in match.group(1).split("|"):
            army_id = army_id.strip()
            if army_id and army_id not in ids:
                ids.append(army_id)
    return ids


def _invalid_monthly_person_rating_reason(effect: Dict[str, object]) -> str:
    raw = effect.get("人物变更")
    if not isinstance(raw, list):
        return ""
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("人物") or "").strip()
        action = str(item.get("动作") or item.get("action") or "").strip()
        if not name or action != "评定":
            continue
        loyalty = item.get("loyalty")
        if isinstance(loyalty, bool) or not isinstance(loyalty, int) or loyalty == 0:
            return "人物变更.评定 loyalty 须为非零整数增量"
    return ""


def _person_change_has_unsupported_monthly_work(raw: object) -> bool:
    if not isinstance(raw, list):
        return False
    for item in raw:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("人物") or "").strip()
        action = str(item.get("动作") or item.get("action") or "").strip()
        if name and action and action != "评定":
            return True
    return False


def _unsupported_monthly_ongoing_fields(effect: Dict[str, object]) -> List[str]:
    unsupported: List[str] = []
    for key in (
        "buildings",
        "new_armies",
        "character_status_changes",
        "character_power_changes",
        "power_renames",
        "legacy",
    ):
        if effect_dict_has_work({key: effect.get(key)}):
            unsupported.append(key)
    if _person_change_has_unsupported_monthly_work(effect.get("人物变更")):
        unsupported.append("人物变更(月度仅支持评定)")
    return unsupported


def _monthly_ongoing_effects_has_work(raw: object) -> bool:
    effect = loads_effect_dict(raw)
    if not effect:
        return False
    checks = (
        effect_dict_has_work({"metrics": effect.get("metrics")}),
        effect_dict_has_work({"economy": effect.get("economy")}),
        effect_dict_has_work({"factions": effect.get("factions")}),
        effect_dict_has_work({"class_delta": effect.get("class_delta")}),
        effect_dict_has_work({"region_delta": effect.get("region_delta")}),
        effect_dict_has_work({"army_delta": effect.get("army_delta")}),
        effect_dict_has_work({"power_updates": effect.get("power_updates")}),
        effect_dict_has_work({"人物变更": effect.get("人物变更")}),
    )
    return any(checks)


def _ack_due_commitment_issue(
    db: GameDB,
    state: GameState,
    row: sqlite3.Row,
    *,
    narrative: str = "",
) -> sqlite3.Row:
    issue_id = int(row["id"])
    from_value = int(row["bar_value"])
    summary = narrative or "到期待裁承诺已由皇帝裁决确认。"
    db.issues.update(
        issue_id,
        {
            "status": "dropped",
            "resolution_summary": summary,
            "closed_turn": state.turn,
            "last_advance_turn": state.turn,
        },
    )
    db.issues.insert_advance(
        (
            issue_id,
            state.turn,
            "commitment_ack",
            "",
            0,
            from_value,
            from_value,
            "",
            "",
            summary,
            "{}",
        )
    )
    return db.issues.row(issue_id)


def event_to_issue(
    db: GameDB, state: GameState, ev: Event
) -> Optional[int]:
    """把一个预设 event（EVENTS / SEED_EVENTS）落成一条 situation issue。供推演判定触发后调用。

    饷率事件不立局势、不记触发。结局只经御批写口。
    effect_on_trigger 在此单次消费；容忍拒收与人物结果经可选 sink 回传调用方。

    去重分两类：
    - 无 trigger_gate（开局局势）：查任意状态同源 issue，立过则永不重立。
    - 有 trigger_gate（条件触发危机）：只查 active 同源 issue，结案/撤销后 gate 再达标可重新触发。
    """
    if issues._is_fiscal_levy_event(ev):
        return None
    if ev.trigger_gate:
        if db.issues.read_find_active_issue_by_origin(('event_pool', ev.id)) is not None:
            return None
    else:
        if db.issues.read_find_any_issue_by_origin(('event_pool', ev.id)) is not None:
            return None
    # 初值由 severity 推一个偏中性的 bar
    bar = max(20, min(60, 50 - int(ev.severity / 5)))
    # 默认 ongoing + inertia 五档（+10/+5/0/-5/-10），按 kind 取
    ongoing: Dict[str, object] = {}
    inertia = -5
    # 终结一锤子永久数值：达成（bar→100）落 effect_on_resolve，崩坏（bar→0 或 LLM 判失败）落
    # effect_on_fail。与 ongoing 过程效果区分——过程是每月漂移，终结是定局后的永久民心/皇威增减。
    polarity = (
        "neg"  # neg=负面危机（平息回血/崩坏重创）；pos=正面机遇（把握加成/错失轻微）
    )
    # 5 个原 metric（边防/民变/党争/执行/瞒报）已废除，ongoing_effects 按 kind 改用
    # 民心/皇威 或留空让 LLM 在推进时自定。结构性影响由 region/army/external/class delta 承担。
    if ev.kind in ("天灾", "灾情", "饥荒"):
        ongoing = {
            "metrics": {"民心": -2},
            "economy": [
                {
                    "account": "国库",
                    "delta": -8,
                    "category": "赈济损耗",
                    "reason": ev.title,
                }
            ],
        }
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
    # 终结效果真源在 situation_drift（#1901 局势漂移腿）；此处直接取，不另造转接壳。
    from ming_sim.situation_drift import situation_terminal_effects

    effect_resolve, effect_fail = situation_terminal_effects(
        ev.kind, int(ev.severity), polarity
    )
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
        effect_fail = (ev.effect_on_fail)
    # insert 的代码/DB 真异常上抛（ADR 0008 决定1 / ADR 0005 fail-loud），与 decree 路径
    # （apply_issue_tracker_output 的 new_issues 段）一致；旧 `except Exception: WARN; return None`
    # 把真异常吞成 None、调用方记普通 rejected，正是 #14/#63 catalog「该落没落无人知」实例
    # （cmr ni r7 codex high）。两种 None 来源已在上方分开：幂等去重经 find_*_by_origin 在此 try
    # 之外 early-return None（正常跳过），故此处无需也不应再兜真异常。
    issue_id = db.insert_issue(
        state,
        kind="situation",
        title=ev.title,
        origin_kind="event_pool",
        origin_ref=ev.id,
        bar_value=bar,
        bar_good_meaning=ev.bar_good_meaning or "已平",
        bar_bad_meaning=ev.bar_bad_meaning or "失控",
        inertia=inertia,
        stage_text=ev.stage_text or ev.summary,
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
        commit=False,
    )
    db.mark_event_triggered(state, ev.id, source="event_pool", commit=False)
    event_terminal.apply_event_cascading_invalidations(state, db)
    return issue_id


def _normalize_cancellable(raw: object) -> str:
    """Admit only the closed cancellable enum.

    #1847: empty → by_progress; unknown free wording must not silently admit.
    """
    val = str(raw or "").strip().lower()
    if not val:
        return "by_progress"
    if val in ("decree", "never", "by_progress"):
        return val
    raise ValueError(f"cancellable 非法：{raw!r}")


def _compute_inertia(ni: Dict[str, object]) -> int:
    """从 expected_months 算 inertia。整数字段用 _strict_int 严格转换
    （拒 bool/float/非数/inf/nan，与 new_issues 其它整数字段一致）——脏值抛
    ValueError/OverflowError，由唯一调用方 apply_issue_tracker_output 的预校验 try 拒整项。
    不接纳旧 new_issues.inertia 平行输入。"""
    em_raw = ni.get("expected_months")
    if em_raw is None:
        return 0
    em = _strict_int(em_raw)  # bool/float（含 inf/nan）/非数 → ValueError
    if em == 0:
        return 0
    return max(-10, min(10, round(100 / em)))


def auto_trigger_seed_issues_in_atomic(
    state: GameState, db: GameDB, collector: RejectionCollector,
) -> List[Dict[str, object]]:
    """auto_trigger_seed_issues 的事务体；由外层函数或月链逐旨后消费点统一提交/回滚。"""
    c = issues._ctx()
    terminal_states = issues._event_terminal_states(db)
    triggered: List[Dict[str, object]] = []
    for ev in [*c.events, *c.seed_events]:
        historical_event = any(ev is item for item in c.events)
        if not ev.auto_trigger:
            continue
        terminal_state = terminal_states.get(ev.id)
        # #1892：任何已落终态（已发/避过/过期/作废）都不再重发——结案后复发等于
        # 同一世界事件被发两次，违「读已落终态不再重发」。
        if terminal_state:
            continue
        if issues._event_window_expired(ev, state):
            db.mark_event_expired(state, ev.id, commit=False)
            terminal_states[ev.id] = "expired"
            continue
        # trigger_gate 为空 = 开局即立的局势，只由 seed_opening_crises 立一次，绝不在此重立。
        # （空 gate 会被 _gate_passed 判为恒真，必须显式排除，否则每回合都试图重立。）
        if ev in c.seed_events and not ev.trigger_gate:
            continue
        if not issues._event_window_open(ev, state):
            continue
        if not issues._gate_passed(ev.trigger_gate, state.metrics, db):
            continue
        apply_trigger_effect = historical_event or (
            ev.event_type != "situation" and not db.issues.has_event_triggered(ev.id)
        )
        if apply_trigger_effect and ev.effect_on_trigger:
            rejected = issue_effects._apply_issue_entities(
                db,
                state,
                ev.effect_on_trigger,
                f"事件#{ev.id}触发",
                content=c,
                source=Provenance.system_simulation,
            )
            for rejection in rejected:
                rejection.item = {"event_id": ev.id, "effect": rejection.item}
                collector.record("event_trigger", rejection, int(state.turn))
        if ev.event_type != "situation":
            # 非 situation（node/ending）不转 issue，仅记触发避免重复
            if apply_trigger_effect:
                db.mark_event_triggered(state, ev.id, commit=False)
                triggered.append({"id": ev.id, "title": ev.title, "kind": ev.event_type})
            continue
        issue_id = event_to_issue(db, state, ev)
        created_issue = issue_id is not None
        if historical_event and issue_id is None:
            # 同源软 issue 已在（存档迁移残留）而事件终态未落：event_to_issue 早退未消费
            # 核心事实，此处补落一次并记终态（#1892 终态与实况同落、只落一次）。
            row = (
                db.issues.read_find_active_issue_by_origin(('event_pool', ev.id))
                if ev.trigger_gate
                else db.issues.read_find_any_issue_by_origin(('event_pool', ev.id))
            )
            if row is None:
                raise RuntimeError(f"历史事件 {ev.id} 未建局势且无法找到同源 issue")
            issue_id = int(row["id"])
            if not apply_trigger_effect and ev.effect_on_trigger:
                rejected = issue_effects._apply_issue_entities(
                    db,
                    state,
                    ev.effect_on_trigger,
                    f"事件#{ev.id}触发",
                    content=c,
                    source=Provenance.system_simulation,
                )
                for rejection in rejected:
                    rejection.item = {"event_id": ev.id, "effect": rejection.item}
                    collector.record("event_trigger", rejection, int(state.turn))
            db.mark_event_triggered(state, ev.id, commit=False)
        elif historical_event:
            db.mark_event_triggered(state, ev.id, commit=False)
        if issue_id is not None:
            triggered.append({"id": ev.id, "title": ev.title, "issue_id": issue_id})
            action = "硬立项" if created_issue else "补记"
            print(f"[AUTO-TRIGGER] gate 达标{action} #{issue_id} {ev.title}（{ev.trigger_gate}）")
    event_terminal.apply_event_cascading_invalidations(state, db)
    return triggered
