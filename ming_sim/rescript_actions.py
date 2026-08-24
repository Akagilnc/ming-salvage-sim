"""#657 批红案头 C1 ＋ 六动作领域写（唯一新模块）。

公开 API（不得再拆第二模块）：
  canonical_choice / validate_all / run_prewrite_llms /
  apply_rescript_batch / clear_return_revise_choice_anchors

边界：
- validate_all / run_prewrite_llms：内存零 DB 写；prewrite 在 write_gate 外
- apply_rescript_batch：单 DB 事务纯代码；由 ① 持 gate 时调用
- 清锚：phase2 成功后由 ③ 调用 clear_return_revise_choice_anchors
- 禁模块内持 write_gate；禁 resolve_context 承载本批 choices
"""

from __future__ import annotations

import concurrent.futures
import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ming_sim.action_materialize import (
    GRANT_HONORIFICS,
    GRANT_MONEY_ACTIONS,
    _assignment_absolute_end_turn,
    _grant_target,
    _resolve_xiexang_army_id,
    punish_actions_effective,
)
from ming_sim.applier import atomic
from ming_sim.authority_privileges import AUTHORITY_PRIVILEGE_SET
from ming_sim.credit_events import KIND_BETRAY, write_credit_event
from ming_sim.decree_vocabulary import (
    RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES,
    RESCRIPT_ROUTABLE_ACTION_TYPES,
    TARGET_KINDS,
    derive_draft_capability,
)
from ming_sim.settlement_payload import (
    decision_has_rescript_capability,
    parse_rescript_capability_pair,
)

# 急务六动作（层 B）
RESCRIPT_DESK_ACTIONS = frozenset({
    "follow_draft", "return_revise", "midzhi", "deliberate", "hold", "summon",
})
_TERMINAL_ACTIONS = frozenset({
    "follow_draft", "midzhi", "deliberate", "hold", "summon",
})

_DecisionKey = str  # "{kind}:{source_turn}:{idx}"


def _parse_decision_key(key: object) -> Tuple[str, int, int]:
    raw = str(key or "").strip()
    parts = raw.split(":")
    if len(parts) != 3:
        raise ValueError(f"非法 decision_key：{raw!r}")
    kind, turn_s, idx_s = parts
    if kind not in {"rescript_draft", "decision"}:
        raise ValueError(f"非法 decision_key.kind：{kind!r}")
    try:
        return kind, int(turn_s), int(idx_s)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"非法 decision_key 数字段：{raw!r}") from exc


def _stable_json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_choice(raw: object) -> Dict[str, object]:
    """确定性规范化 choice：键序固定、缺省填协议默认、decision_key/action/capability 必在。"""
    if not isinstance(raw, dict):
        raise ValueError("choice 须为 object")
    out: Dict[str, object] = {}
    # 保留并规范化已知键
    decision_key = str(raw.get("decision_key") or "").strip()
    if decision_key:
        _parse_decision_key(decision_key)
        out["decision_key"] = decision_key
    action = str(raw.get("action") or raw.get("dossier_decision") or "").strip()
    if action:
        out["action"] = action
    # capability
    cap = str(raw.get("draft_capability") or "").strip()
    if cap:
        out["draft_capability"] = cap
    # 通用展示/批红字段
    for key in (
        "label", "hint", "note",
        "action_type", "assignee_name", "name",
        "target_kind", "target_id", "transaction_category",
        "locality_scope", "region_id", "title", "commitment_kind",
        "stop_condition", "station", "office",
        "grant_action", "account", "cadence", "execution_surface",
        "appoint_action", "appointment_tenure", "punish_action",
        "privilege", "summon_target",
        "holder_id", "assignee_id", "assignee",
    ):
        if key in raw and raw[key] is not None:
            out[key] = str(raw[key]) if not isinstance(raw[key], (int, float, bool)) else raw[key]
            if isinstance(out[key], bool):
                out[key] = str(out[key])
    for key in ("end_turn", "deadline_months", "due_turn", "amount",
                "dossier_id", "applied_from_revision_round", "revision_round"):
        if key in raw and raw[key] is not None and raw[key] != "":
            try:
                out[key] = int(raw[key])  # type: ignore[arg-type]
            except (TypeError, ValueError) as exc:
                raise ValueError(f"choice.{key} 非法：{raw[key]!r}") from exc
    # dossier 批红能力对原样保留
    if "dossier_decision" in raw and raw["dossier_decision"] is not None:
        out["dossier_decision"] = str(raw["dossier_decision"])
    if "dossier_id" in raw and "dossier_id" not in out:
        pair = parse_rescript_capability_pair(raw)
        if pair is not None:
            out["dossier_id"] = pair[0]
            out["dossier_decision"] = pair[1]
            out.setdefault("action", pair[1])
    # 缺省 label
    out.setdefault("label", str(raw.get("label") or ""))
    out.setdefault("hint", str(raw.get("hint") or ""))
    return out


def _row_key(row: Mapping[str, object]) -> _DecisionKey:
    if row.get("decision_key"):
        return str(row["decision_key"])
    kind = str(row.get("kind") or "decision")
    turn = int(row.get("source_turn") if row.get("source_turn") is not None else row.get("turn") or 0)
    idx = int(row.get("idx") or 0)
    return f"{kind}:{turn}:{idx}"


def _choice_empty(choice: object) -> bool:
    if choice is None:
        return True
    if isinstance(choice, str) and not choice.strip():
        return True
    if isinstance(choice, dict) and not choice:
        return True
    return False


def _choices_equal(a: object, b: object) -> bool:
    try:
        ca = canonical_choice(a) if isinstance(a, dict) else None
        cb = canonical_choice(b) if isinstance(b, dict) else None
    except ValueError:
        return False
    if ca is None or cb is None:
        return False
    return _stable_json(ca) == _stable_json(cb)


def _is_applied_revise_anchor(row: Mapping[str, object], choice: Mapping[str, object]) -> bool:
    """行上 choice 显示本轮 return_revise 已应用（round 已 +1、prior 已 append）。"""
    if str(choice.get("action") or "") != "return_revise":
        return False
    if str(row.get("status") or "") != "pending":
        return False
    applied_from = choice.get("applied_from_revision_round")
    try:
        applied_from_i = int(applied_from) if applied_from is not None else -1
    except (TypeError, ValueError):
        return False
    # 应用后 revision_round 应为 applied_from + 1
    return int(row.get("revision_round") or 0) == applied_from_i + 1


def _option_by_capability(row: Mapping[str, object]) -> Dict[str, Dict[str, object]]:
    out: Dict[str, Dict[str, object]] = {}
    for opt in row.get("options") or []:
        if not isinstance(opt, dict):
            continue
        cap = str(opt.get("draft_capability") or "").strip()
        if not cap:
            # 允许服务端即时派生
            try:
                cap = derive_draft_capability(opt)
            except Exception:
                continue
        out[cap] = opt
    return out


@dataclass
class ValidatedItem:
    decision_key: str
    kind: str
    source_turn: int
    idx: int
    row: Dict[str, object]
    choice: Dict[str, object]
    already_applied: bool = False
    needs_revise_llm: bool = False
    needs_deliberate_llm: bool = False


@dataclass
class ValidatedBatch:
    items: List[ValidatedItem] = field(default_factory=list)
    # 新鲜批 P 内急务缺 action → 落印时机械 hold 的 keys
    default_hold_keys: List[str] = field(default_factory=list)

    def by_key(self) -> Dict[str, ValidatedItem]:
        return {it.decision_key: it for it in self.items}


@dataclass
class PrewriteResults:
    revise_by_key: Dict[str, List[Dict[str, object]]] = field(default_factory=dict)
    deliberate_by_key: Dict[str, Dict[str, object]] = field(default_factory=dict)


@dataclass
class ApplyResult:
    applied_keys: List[str] = field(default_factory=list)
    skipped_keys: List[str] = field(default_factory=list)
    summon_keys: List[str] = field(default_factory=list)
    revise_keys: List[str] = field(default_factory=list)


def validate_all(
    desk_rows: Sequence[Mapping[str, object]],
    request_choices: object,
    *,
    default_hold_missing: bool = True,
) -> ValidatedBatch:
    """① Validate-all（内存，零写库）。

    - 键∈desk；无重复
    - applied-revise 锚先于 capability∈当前 options
    - decided 精确匹配→已应用；decided 不匹配/空→整批拒
    - desk 外/非法→整批拒
    - 新鲜批 P 内急务缺 action → 仅落印时机械 hold（记入 default_hold_keys）
    """
    desk_by_key: Dict[str, Dict[str, object]] = {}
    for row in desk_rows:
        if not isinstance(row, Mapping):
            raise ValueError("desk 行非法")
        key = _row_key(row)
        if key in desk_by_key:
            raise ValueError(f"desk 重复键：{key}")
        desk_by_key[key] = dict(row)

    # 规范化 request：list[{decision_key,...}] 或 dict[decision_key→choice]
    choice_map: Dict[str, Dict[str, object]] = {}
    if isinstance(request_choices, Mapping):
        iterable: Iterable[object] = [
            {**dict(v), "decision_key": k} if isinstance(v, Mapping) else v
            for k, v in request_choices.items()
        ]
    elif isinstance(request_choices, Sequence) and not isinstance(request_choices, (str, bytes)):
        iterable = request_choices
    else:
        raise ValueError("request_choices 须为 list 或 dict")

    for raw in iterable:
        if not isinstance(raw, Mapping):
            raise ValueError("choice 须为 object")
        key = str(raw.get("decision_key") or "").strip()
        if not key:
            raise ValueError("choice 缺 decision_key")
        if key in choice_map:
            raise ValueError(f"重复 decision_key：{key}")
        if key not in desk_by_key:
            raise ValueError(f"decision_key 不在当前 desk：{key}")
        choice_map[key] = canonical_choice(dict(raw))

    batch = ValidatedBatch()
    for key, row in desk_by_key.items():
        status = str(row.get("status") or "pending")
        stored_choice = row.get("choice")
        req = choice_map.get(key)

        # decided 行
        if status == "decided":
            if req is None:
                raise ValueError(f"decided 行缺请求 choice：{key}")
            if _choice_empty(stored_choice) or not _choices_equal(stored_choice, req):
                raise ValueError(f"decided 行 choice 不匹配：{key}")
            batch.items.append(ValidatedItem(
                decision_key=key,
                kind=str(row.get("kind") or "decision"),
                source_turn=int(row.get("source_turn") if row.get("source_turn") is not None else row.get("turn") or 0),
                idx=int(row.get("idx") or 0),
                row=row,
                choice=req,
                already_applied=True,
            ))
            continue

        # pending 行
        kind = str(row.get("kind") or "decision")
        if req is None:
            if kind == "rescript_draft" and default_hold_missing:
                # 新鲜批缺 action → 机械 hold（落印时）
                hold_choice = canonical_choice({
                    "decision_key": key,
                    "action": "hold",
                    "label": "留中",
                    "hint": "",
                })
                batch.default_hold_keys.append(key)
                batch.items.append(ValidatedItem(
                    decision_key=key,
                    kind=kind,
                    source_turn=int(row.get("source_turn") if row.get("source_turn") is not None else row.get("turn") or 0),
                    idx=int(row.get("idx") or 0),
                    row=row,
                    choice=hold_choice,
                ))
                continue
            # decision 行缺请求：非急务，不默认 hold；若 desk 含 decision 则必须提交
            raise ValueError(f"pending 行缺请求 choice：{key}")

        action = str(req.get("action") or "").strip()

        # 已应用 return_revise 锚（先于 capability∈当前 options）
        if not _choice_empty(stored_choice) and isinstance(stored_choice, dict):
            if _is_applied_revise_anchor(row, stored_choice):
                if _choices_equal(stored_choice, req):
                    batch.items.append(ValidatedItem(
                        decision_key=key,
                        kind=kind,
                        source_turn=int(row.get("source_turn") if row.get("source_turn") is not None else row.get("turn") or 0),
                        idx=int(row.get("idx") or 0),
                        row=row,
                        choice=req,
                        already_applied=True,
                    ))
                    continue
                raise ValueError(f"已应用 revise 锚与请求不一致：{key}")

        # dossier 批红 decision 行（#1490）
        if kind == "decision" and decision_has_rescript_capability(row):
            options = [o for o in (row.get("options") or []) if isinstance(o, dict)]
            option_by_pair = {}
            for option in options:
                pair = parse_rescript_capability_pair(option)
                if pair is not None:
                    option_by_pair[pair] = option
            selected = parse_rescript_capability_pair(req)
            if selected is None or selected not in option_by_pair:
                raise ValueError("批红选择必须是本案提供的强颁、收回或留中选项")
            matched = option_by_pair[selected]
            rebuilt = canonical_choice({
                "decision_key": key,
                "label": matched.get("label"),
                "hint": matched.get("hint") or "",
                "dossier_id": selected[0],
                "dossier_decision": selected[1],
                "action": selected[1],
                "note": req.get("note"),
            })
            batch.items.append(ValidatedItem(
                decision_key=key,
                kind=kind,
                source_turn=int(row.get("source_turn") if row.get("source_turn") is not None else row.get("turn") or 0),
                idx=int(row.get("idx") or 0),
                row=row,
                choice=rebuilt,
            ))
            continue

        # 普通 decision（打回三选等）：按 label 匹配 option
        if kind == "decision":
            labels = {
                str(o.get("label") or ""): o
                for o in (row.get("options") or [])
                if isinstance(o, dict)
            }
            label = str(req.get("label") or "").strip()
            if label not in labels:
                raise ValueError(f"decision 选项不在当前 options：{key}")
            matched = labels[label]
            rebuilt = canonical_choice({
                "decision_key": key,
                "label": matched.get("label"),
                "hint": matched.get("hint") or "",
                "note": req.get("note"),
                "action": action or "decision",
            })
            batch.items.append(ValidatedItem(
                decision_key=key,
                kind=kind,
                source_turn=int(row.get("source_turn") if row.get("source_turn") is not None else row.get("turn") or 0),
                idx=int(row.get("idx") or 0),
                row=row,
                choice=rebuilt,
            ))
            continue

        # 急务六动作
        if action not in RESCRIPT_DESK_ACTIONS:
            raise ValueError(f"非法急务动作：{action!r}")

        if action == "follow_draft":
            cap = str(req.get("draft_capability") or "").strip()
            by_cap = _option_by_capability(row)
            if not cap or cap not in by_cap:
                raise ValueError(f"stale 或缺失 draft_capability：{key}")
            opt = by_cap[cap]
            merged = canonical_choice({**opt, **req, "decision_key": key, "action": "follow_draft"})
            batch.items.append(ValidatedItem(
                decision_key=key, kind=kind,
                source_turn=int(row.get("source_turn") if row.get("source_turn") is not None else row.get("turn") or 0),
                idx=int(row.get("idx") or 0),
                row=row, choice=merged,
            ))
            continue

        if action == "midzhi":
            # 字段从 choice 显式
            at = str(req.get("action_type") or "").strip()
            if at not in RESCRIPT_ROUTABLE_ACTION_TYPES:
                raise ValueError(f"midzhi.action_type 非七类 routable：{at!r}")
            batch.items.append(ValidatedItem(
                decision_key=key, kind=kind,
                source_turn=int(row.get("source_turn") if row.get("source_turn") is not None else row.get("turn") or 0),
                idx=int(row.get("idx") or 0),
                row=row, choice=req,
            ))
            continue

        if action == "return_revise":
            # 锚：applied_from_revision_round + 旧 capability（可选）
            round_now = int(row.get("revision_round") or 0)
            req.setdefault("applied_from_revision_round", round_now)
            if int(req.get("applied_from_revision_round") or -1) != round_now:
                # 若非已应用路径，请求锚须对应当前 round
                if not (_choices_equal(stored_choice, req) and _is_applied_revise_anchor(row, req)):
                    # 允许未带 cap 的改票请求；强制对齐 round
                    req["applied_from_revision_round"] = round_now
            batch.items.append(ValidatedItem(
                decision_key=key, kind=kind,
                source_turn=int(row.get("source_turn") if row.get("source_turn") is not None else row.get("turn") or 0),
                idx=int(row.get("idx") or 0),
                row=row, choice=req,
                needs_revise_llm=True,
            ))
            continue

        if action == "deliberate":
            batch.items.append(ValidatedItem(
                decision_key=key, kind=kind,
                source_turn=int(row.get("source_turn") if row.get("source_turn") is not None else row.get("turn") or 0),
                idx=int(row.get("idx") or 0),
                row=row, choice=req,
                needs_deliberate_llm=True,
            ))
            continue

        if action == "hold":
            batch.items.append(ValidatedItem(
                decision_key=key, kind=kind,
                source_turn=int(row.get("source_turn") if row.get("source_turn") is not None else row.get("turn") or 0),
                idx=int(row.get("idx") or 0),
                row=row, choice=req,
            ))
            continue

        if action == "summon":
            target = str(req.get("summon_target") or "").strip()
            if not target:
                raise ValueError(f"summon 缺 summon_target：{key}")
            batch.items.append(ValidatedItem(
                decision_key=key, kind=kind,
                source_turn=int(row.get("source_turn") if row.get("source_turn") is not None else row.get("turn") or 0),
                idx=int(row.get("idx") or 0),
                row=row, choice=req,
            ))
            continue

        raise ValueError(f"未处理动作：{action}")

    # 请求中不得有 desk 外键（已在上面检查）；返回
    return batch


def run_prewrite_llms(
    batch: ValidatedBatch,
    *,
    revise_runner: Optional[Callable[[ValidatedItem], List[Dict[str, object]]]] = None,
    deliberate_runner: Optional[Callable[[ValidatedItem], Dict[str, object]]] = None,
    max_workers: int = 8,
) -> PrewriteResults:
    """写前并行 LLM（事务外·gate 外）。任一失败整批中止零写。

    已应用行不重跑。不建 registry/结果表/长期池。
    """
    revise_items = [it for it in batch.items if it.needs_revise_llm and not it.already_applied]
    deliberate_items = [it for it in batch.items if it.needs_deliberate_llm and not it.already_applied]
    results = PrewriteResults()
    if not revise_items and not deliberate_items:
        return results

    errors: List[BaseException] = []

    def _run_revise(it: ValidatedItem) -> Tuple[str, List[Dict[str, object]]]:
        if revise_runner is None:
            raise RuntimeError("return_revise 需要 revise_runner")
        return it.decision_key, list(revise_runner(it))

    def _run_deliberate(it: ValidatedItem) -> Tuple[str, Dict[str, object]]:
        if deliberate_runner is None:
            raise RuntimeError("deliberate 需要 deliberate_runner")
        out = deliberate_runner(it)
        if not isinstance(out, dict):
            raise ValueError("deliberate LLM 输出须为 object")
        return it.decision_key, out

    # 一次短生命周期 pool：全部 start → wait → join
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        futs = []
        for it in revise_items:
            futs.append(("revise", pool.submit(_run_revise, it)))
        for it in deliberate_items:
            futs.append(("deliberate", pool.submit(_run_deliberate, it)))
        for kind, fut in futs:
            try:
                key, payload = fut.result()
            except BaseException as exc:  # noqa: BLE001 — 任一腿失败整批中止
                errors.append(exc)
                continue
            if kind == "revise":
                results.revise_by_key[key] = payload  # type: ignore[assignment]
            else:
                results.deliberate_by_key[key] = payload  # type: ignore[assignment]
    if errors:
        raise RuntimeError(f"prewrite LLM 失败（整批中止零写）：{errors[0]}") from errors[0]
    return results


def map_rescript_option_or_choice(
    fields: Mapping[str, object],
    *,
    mode: str = "ordinary",
    db: Any = None,
    content: Any = None,
    state: Any = None,
) -> Dict[str, object]:
    """七类 mapper（C.2–C.7）：option/choice → 预 normalize payload。

    类特定显式闸在 normalize 前完成；返回的 payload 供
    ``db._normalize_directive_dossier_payload`` 唯一结构边界使用。
    """
    src = dict(fields)
    action_type = str(src.get("action_type") or "").strip()
    if action_type not in RESCRIPT_ROUTABLE_ACTION_TYPES:
        raise ValueError(f"action_type 非七类 routable：{action_type!r}")

    target_kind = str(src.get("target_kind") or "").strip()
    target_id = str(src.get("target_id") or "").strip()
    if target_kind not in TARGET_KINDS:
        raise ValueError(f"target_kind 非法：{target_kind!r}")
    if not target_id:
        raise ValueError("target_id 不可空")

    label = str(src.get("label") or "").strip()
    note = str(src.get("note") or "").strip()
    decree_text = note if note else label
    assignee_name = str(src.get("assignee_name") or src.get("assignee") or "").strip()
    locality_scope = str(src.get("locality_scope") or "none").strip() or "none"
    region_id = str(src.get("region_id") or "").strip()

    payload: Dict[str, object] = {
        "dossier_action_type": action_type,
        "mode": "midzhi" if mode == "midzhi" else "ordinary",
        "target_kind": target_kind,
        "target_id": target_id,
        "locality_scope": locality_scope,
        "region_id": region_id,
        "label": label,
        "hint": str(src.get("hint") or ""),
    }
    if assignee_name:
        payload["assignee_id"] = assignee_name
        payload["assignee_name"] = assignee_name

    current_turn = int(getattr(state, "turn", 0) or 0)

    if action_type == "assignment":
        cat = str(src.get("transaction_category") or "").strip()
        if not cat and not assignee_name:
            raise ValueError("assignment 缺 transaction_category 与主办")
        if cat:
            payload["transaction_category"] = cat
        title = str(src.get("title") or label or "").strip()
        if title:
            payload["title"] = title[:80]
        ck = str(src.get("commitment_kind") or "无").strip() or "无"
        payload["commitment_kind"] = ck
        stop = str(src.get("stop_condition") or "").strip()
        if ck == "until_stop" and not stop:
            raise ValueError("until_stop 缺 stop_condition")
        if stop:
            payload["stop_condition"] = stop
        end_turn = _assignment_absolute_end_turn(
            current_turn, src.get("end_turn"), src.get("deadline_months"),
        )
        if end_turn:
            payload["end_turn"] = end_turn

    elif action_type == "military_order":
        if target_kind != "army":
            raise ValueError("military_order.target_kind 必须为 army")
        if db is not None:
            row = db.conn.execute(
                "SELECT id FROM armies WHERE id=?", (target_id,),
            ).fetchone()
            if row is None:
                raise ValueError(f"military_order 假军：{target_id!r}")
        if not assignee_name:
            raise ValueError("military_order 缺 assignee_name")
        payload["assignee_id"] = assignee_name
        payload["name"] = assignee_name
        station = str(src.get("station") or "").strip()
        if station:
            payload["station"] = station
        else:
            due = 0
            try:
                due = int(src.get("due_turn") or 0)
            except (TypeError, ValueError):
                due = 0
            months = 0
            try:
                months = int(src.get("deadline_months") or 0)
            except (TypeError, ValueError):
                months = 0
            if months > 0:
                due = current_turn + months
            if due <= current_turn:
                raise ValueError("military_order 无 station 时须有效未来 due")
            payload["due_turn"] = due
        office = str(src.get("office") or "").strip()
        if office:
            payload["office"] = office
        cat = str(src.get("transaction_category") or "").strip()
        if cat:
            payload["transaction_category"] = cat

    elif action_type == "grant_allocation":
        ga = str(src.get("grant_action") or "").strip()
        if not ga:
            raise ValueError("grant_allocation 缺 grant_action")
        payload["grant_action"] = ga
        # account 处理序（mapper 内，normalize 前）
        raw_account = str(src.get("account") or "").strip()
        if ga == "发内帑":
            account = "内库"
        elif ga in GRANT_MONEY_ACTIONS:
            if raw_account and raw_account not in {"国库", "内库"}:
                raise ValueError(f"grant 非法 account：{raw_account!r}")
            account = raw_account if raw_account in {"国库", "内库"} else "国库"
        else:
            account = ""
        payload["account"] = account
        g_kind, g_tid = _grant_target({
            "grant_action": ga,
            "name": str(src.get("name") or assignee_name or ""),
            "target_id": target_id,
        })
        # 协饷必须真 army
        if ga == "协饷":
            army_id = g_tid
            if db is not None:
                army_id = _resolve_xiexang_army_id(db, g_tid) or ""
            if not army_id:
                raise ValueError("协饷 target 须为真实 army id")
            payload["target_kind"] = "army"
            payload["target_id"] = army_id
            target_kind, target_id = "army", army_id
        else:
            payload["target_kind"] = g_kind or target_kind
            payload["target_id"] = g_tid or target_id
            target_kind = str(payload["target_kind"])
            target_id = str(payload["target_id"])
        if ga in GRANT_HONORIFICS:
            if not target_id:
                raise ValueError("honorific 缺 name/target")
            payload["execution_surface"] = "terminal"
            payload["name"] = target_id
        else:
            try:
                amount = int(src.get("amount") or 0)
            except (TypeError, ValueError):
                amount = 0
            if amount <= 0:
                raise ValueError("grant 金钱缺正 amount")
            payload["amount"] = amount
            cadence = str(src.get("cadence") or "").strip() or "一次性"
            payload["cadence"] = cadence
            if ga == "协饷" and cadence == "一次性":
                payload["execution_surface"] = "immediate"
            else:
                surface = str(src.get("execution_surface") or "in_transit").strip()
                payload["execution_surface"] = surface or "in_transit"
            if target_kind == "character":
                payload["name"] = target_id

    elif action_type == "appointment":
        appoint_action = str(src.get("appoint_action") or "").strip()
        if appoint_action not in {"任命", "罢免"}:
            raise ValueError("appoint_action 须为任命或罢免")
        office = str(src.get("office") or "").strip()
        name = str(src.get("name") or target_id or "").strip()
        if not name:
            raise ValueError("appointment 缺 name/target")
        if appoint_action == "任命" and not office:
            raise ValueError("任命缺 office")
        # 罢免：目标须 active 明臣
        if appoint_action == "罢免" and db is not None:
            row = db.conn.execute(
                "SELECT status, power_id FROM characters WHERE name=?", (name,),
            ).fetchone()
            if row is None or str(row["status"]) != "active" or str(row["power_id"] or "") != "ming":
                raise ValueError("罢免目标须为 active 明臣")
        payload["appoint_action"] = appoint_action
        payload["_office_action"] = appoint_action
        payload["office"] = office
        payload["name"] = name
        payload["target_kind"] = "character"
        payload["target_id"] = name
        tenure = str(src.get("appointment_tenure") or "").strip()
        if tenure:
            payload["appointment_tenure"] = tenure
        # emitted action_type
        if appoint_action == "罢免":
            payload["dossier_action_type"] = "dismiss_assignment"
            action_type = "dismiss_assignment"

    elif action_type == "punishment":
        pa = str(src.get("punish_action") or "").strip()
        if pa not in punish_actions_effective():
            raise ValueError(f"非法 punish_action：{pa!r}")
        name = str(src.get("name") or target_id or "").strip()
        if not name:
            raise ValueError("punishment 缺 name/target")
        payload["punish_action"] = pa
        payload["name"] = name
        payload["target_kind"] = "character"
        payload["target_id"] = name
        if pa == "罚俸":
            try:
                amount = int(src.get("amount") or 0)
            except (TypeError, ValueError):
                amount = 0
            if amount <= 0:
                raise ValueError("罚俸须正 amount")
            payload["amount"] = amount
        else:
            # 其它动作不得正 amount
            try:
                amount = int(src.get("amount") or 0)
            except (TypeError, ValueError):
                amount = 0
            if amount > 0:
                raise ValueError("非罚俸不得带正 amount")

    elif action_type == "authorization":
        holder = ""
        for k in ("holder_id", "assignee_id", "assignee", "name", "assignee_name"):
            holder = str(src.get(k) or "").strip()
            if holder:
                break
        if not holder:
            raise ValueError("authorization 四键皆空")
        canonical = holder
        if content is not None and db is not None:
            from ming_sim.session import _find_existing_minister
            canonical = _find_existing_minister(content, holder, db) or ""
            if not canonical:
                raise ValueError(f"authorization holder 无法解析：{holder!r}")
        priv = str(src.get("privilege") or "").strip()
        if priv in {"", "无"}:
            priv = "便宜行事"
        if priv not in AUTHORITY_PRIVILEGE_SET:
            raise ValueError(f"非法 privilege：{priv!r}")
        payload["privilege"] = priv
        payload["holder_id"] = canonical
        payload["assignee_id"] = canonical
        payload["name"] = canonical
        # scope 由 normalize 从 target 派生；此处预填
        payload["scope"] = f"{target_kind}:{target_id}"

    elif action_type == "pacification":
        if target_kind != "character":
            raise ValueError("pacification.target_kind 必须 character")
        name = str(src.get("name") or target_id or "").strip()
        if not name:
            raise ValueError("pacification 缺 target")
        if db is not None:
            matched = db._find_pacification_target(content, name)
            if not matched:
                raise ValueError(f"pacification 非合法内乱 leader：{name!r}")
            name = matched
        payload["name"] = name
        payload["target_kind"] = "character"
        payload["target_id"] = name

    # C.5 name sync for character-ish
    emitted = str(payload.get("dossier_action_type") or action_type)
    if emitted not in RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES:
        raise ValueError(f"emitted action_type 非闭集：{emitted!r}")
    if emitted in {"appointment", "dismiss_assignment", "punishment"} or (
        emitted == "grant_allocation"
        and str(payload.get("grant_action") or "") in {"赏赉", "发内帑", "加衔", "荫叙"}
    ):
        payload["name"] = str(payload.get("target_id") or payload.get("name") or "")

    payload["_decree_text"] = decree_text
    payload["_emitted_action_type"] = emitted
    return payload


def _create_from_mapped(
    db: Any,
    state: Any,
    content: Any,
    mapped: Mapping[str, object],
    *,
    status: str,
    mode: str,
) -> List[int]:
    payload = dict(mapped)
    decree_text = str(payload.pop("_decree_text", "") or "")
    emitted = str(payload.pop("_emitted_action_type", "") or payload.get("dossier_action_type") or "")
    payload["mode"] = mode
    payload["dossier_action_type"] = emitted
    normalized = db._normalize_directive_dossier_payload(
        payload, content=content, current_turn=int(getattr(state, "turn", 0) or 0),
    )
    executor_kind = ""
    executor_id = ""
    assignee = str(normalized.get("assignee_id") or "").strip()
    if assignee:
        executor_kind = "character"
        executor_id = assignee
    due_turn = 0
    try:
        due_turn = int(normalized.get("due_turn") or 0)
    except (TypeError, ValueError):
        due_turn = 0
    return list(db.create_decree_dossiers(
        state,
        action_type=emitted,
        decree_text=decree_text or str(normalized.get("label") or emitted),
        target_kind=str(normalized.get("target_kind") or ""),
        target_id=str(normalized.get("target_id") or ""),
        executor_kind=executor_kind,
        executor_id=executor_id,
        payload=normalized,
        status=status,
        due_turn=due_turn,
        commit=False,
    ))


def _apply_hold(db: Any, state: Any, item: ValidatedItem) -> None:
    """留中：write_credit_event(辜负) + 惯性结算既有缝（本步只记账信用）。"""
    actor = str(item.row.get("actor_name") or "").strip()
    if not actor:
        # 无上疏者则只落 choice，不强制信用边
        return
    origin = f"rescript_hold:{item.decision_key}"
    write_credit_event(
        db, state,
        person=actor,
        event_kind=KIND_BETRAY,
        context=str(item.row.get("title") or item.choice.get("label") or "留中"),
        origin=origin,
    )


def _apply_deliberate(
    db: Any,
    state: Any,
    item: ValidatedItem,
    prewrite: PrewriteResults,
) -> None:
    will = prewrite.deliberate_by_key.get(item.decision_key)
    if not isinstance(will, dict):
        raise ValueError(f"deliberate 缺 prewrite 意愿：{item.decision_key}")
    title = str(will.get("title") or item.row.get("title") or "廷议").strip()
    body = str(will.get("body") or will.get("stance") or will.get("text") or "").strip()
    if not body:
        raise ValueError("deliberate LLM 意愿正文为空")
    origin = f"rescript_deliberate:{item.decision_key}"
    # 既有 origin 去重
    existing = db.conn.execute(
        "SELECT id FROM issues WHERE origin_ref=? LIMIT 1", (origin,),
    ).fetchone()
    if existing is not None:
        return
    db.insert_issue(
        state,
        kind="situation",
        title=title,
        origin_kind="rescript_deliberate",
        origin_ref=origin,
        stage_text=body,
        commit=False,
    )


def _apply_return_revise(
    db: Any,
    item: ValidatedItem,
    prewrite: PrewriteResults,
) -> None:
    new_options = prewrite.revise_by_key.get(item.decision_key)
    if not isinstance(new_options, list) or not new_options:
        raise ValueError(f"return_revise 缺 prewrite 新 options：{item.decision_key}")
    # 确保新 options 带 capability
    stamped: List[Dict[str, object]] = []
    for opt in new_options:
        if not isinstance(opt, dict):
            raise ValueError("改票 option 非 object")
        # 允许仅 label/hint 的改票输出——不强制层 A 全键（改票 LLM 单行模式）
        if "draft_capability" not in opt:
            opt = dict(opt)
            opt["draft_capability"] = derive_draft_capability(opt)
        stamped.append(opt)
    old_round = int(item.row.get("revision_round") or 0)
    old_options = item.row.get("options") or []
    prior = list(item.row.get("prior_options_json") or [])
    if not isinstance(prior, list):
        prior = []
    prior = list(prior) + [old_options]
    # CAS 含旧 revision_round
    cur = db.conn.execute(
        "UPDATE pending_decisions SET revision_round = ?, options_json = ?, "
        "prior_options_json = ?, choice_json = ?, status = 'pending' "
        "WHERE turn = ? AND idx = ? AND kind = ? AND revision_round = ? "
        "AND status = 'pending'",
        (
            old_round + 1,
            json.dumps(stamped, ensure_ascii=False),
            json.dumps(prior, ensure_ascii=False),
            json.dumps(item.choice, ensure_ascii=False),
            item.source_turn,
            item.idx,
            item.kind,
            old_round,
        ),
    )
    if cur.rowcount != 1:
        raise ValueError(f"return_revise CAS 失败：{item.decision_key}")


def _cas_decided(db: Any, item: ValidatedItem) -> None:
    choice_json = json.dumps(item.choice, ensure_ascii=False)
    # 行级 CAS：pending → decided，且 choice 仍空或可被本事务首写
    cur = db.conn.execute(
        "UPDATE pending_decisions SET choice_json = ?, status = 'decided' "
        "WHERE turn = ? AND idx = ? AND kind = ? AND status = 'pending'",
        (choice_json, item.source_turn, item.idx, item.kind),
    )
    if cur.rowcount != 1:
        # 可能已 decided 且精确匹配——由 already_applied 路径处理；此处响亮失败
        raise ValueError(f"行级 CAS 失败（非 pending）：{item.decision_key}")


def apply_rescript_batch(
    db: Any,
    state: Any,
    batch: ValidatedBatch,
    prewrite: PrewriteResults,
    *,
    content: Any = None,
) -> ApplyResult:
    """单 DB 事务纯代码：choice_json + 行级 CAS + 五动作/summon→decided。

    summon 本步只 CAS→decided+choice；不写成功正文 ledger。
    任一条失败 → 回滚（含 choice）。禁 save/clear 触碰 rescript_draft。
    禁任何 resolve_context 键承载本批 choices。
    """
    result = ApplyResult()
    with atomic(db):
        for item in batch.items:
            if item.already_applied:
                result.skipped_keys.append(item.decision_key)
                if str(item.choice.get("action") or "") == "summon":
                    result.summon_keys.append(item.decision_key)
                if str(item.choice.get("action") or "") == "return_revise":
                    result.revise_keys.append(item.decision_key)
                continue

            action = str(item.choice.get("action") or "").strip()
            kind = item.kind

            if kind == "decision":
                # decision 行：写 choice + decided（#1490 / 普通 HITL）
                _cas_decided(db, item)
                event_id = str(item.row.get("event_id") or "").strip()
                if event_id and not event_id.startswith("dossier:"):
                    try:
                        db.record_event_decision_choice(
                            state, event_id, item.choice, commit=False,
                        )
                    except Exception:
                        # 事件账可选；不阻断批红主路径
                        pass
                result.applied_keys.append(item.decision_key)
                continue

            # 急务
            if action == "return_revise":
                _apply_return_revise(db, item, prewrite)
                result.applied_keys.append(item.decision_key)
                result.revise_keys.append(item.decision_key)
                continue

            if action == "follow_draft":
                mapped = map_rescript_option_or_choice(
                    item.choice, mode="ordinary", db=db, content=content, state=state,
                )
                _create_from_mapped(
                    db, state, content, mapped, status="proposed", mode="ordinary",
                )
                _cas_decided(db, item)
                result.applied_keys.append(item.decision_key)
                continue

            if action == "midzhi":
                mapped = map_rescript_option_or_choice(
                    item.choice, mode="midzhi", db=db, content=content, state=state,
                )
                _create_from_mapped(
                    db, state, content, mapped, status="proposed", mode="midzhi",
                )
                _cas_decided(db, item)
                result.applied_keys.append(item.decision_key)
                continue

            if action == "deliberate":
                _apply_deliberate(db, state, item, prewrite)
                _cas_decided(db, item)
                result.applied_keys.append(item.decision_key)
                continue

            if action == "hold":
                _apply_hold(db, state, item)
                _cas_decided(db, item)
                result.applied_keys.append(item.decision_key)
                continue

            if action == "summon":
                # 本片只 CAS→decided+choice；领域消费片3
                target = str(item.choice.get("summon_target") or "").strip()
                if not target:
                    raise ValueError("summon_target 为空")
                # 预校验 can_summon：人物存在即可（深度校验片3）
                if content is not None:
                    from ming_sim.session import _find_existing_minister
                    canon = _find_existing_minister(content, target, db)
                    if not canon:
                        # 允许非大臣名（边将等）——至少非空
                        pass
                    else:
                        item.choice["summon_target"] = canon
                _cas_decided(db, item)
                result.applied_keys.append(item.decision_key)
                result.summon_keys.append(item.decision_key)
                continue

            raise ValueError(f"未知动作：{action}")
    return result


def clear_return_revise_choice_anchors(
    db: Any,
    applied_revise_keys: Sequence[str],
) -> None:
    """phase2 全程成功后：对本批已应用 return_revise 行清空 choice_json。

    唯一清锚动作；无 consumed_epoch。五动作 decided 行保留 choice_json。
    """
    for key in applied_revise_keys:
        kind, turn, idx = _parse_decision_key(key)
        db.conn.execute(
            "UPDATE pending_decisions SET choice_json = '{}' "
            "WHERE turn = ? AND idx = ? AND kind = ? AND status = 'pending'",
            (turn, idx, kind),
        )
    # 调用方持锁窗内决定是否 commit；此处不强制 commit 以融入 ③ 事务
