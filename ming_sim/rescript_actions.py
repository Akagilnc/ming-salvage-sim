"""批红案头：普通 decision / 0055 案卷三选 + 共享 option 映射。

公开 API：
  canonical_choice / validate_request_keys / validate_all /
  apply_rescript_batch / map_rescript_option_or_choice

旧急务六动作、return_revise/deliberate 预写与清锚已随失供协议退役。
禁模块内持 write_gate；禁 resolve_context 承载本批 choices。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ming_sim.action_materialize import (
    GRANT_HONORIFICS,
    _assignment_absolute_end_turn,
    _grant_target,
    punish_actions_effective,
    require_grant_allocation_shape,
)
from ming_sim.authority_privileges import AUTHORITY_PRIVILEGE_SET
from ming_sim.credit_events import KIND_BETRAY, write_credit_event
from ming_sim.decree import atomic_and_reload
from ming_sim.decree_vocabulary import (
    DOSSIER_ACTION_TYPES,
    PARTICIPANT_ROSTER_KEY,
    RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES,
    TARGET_KINDS,
)
from ming_sim.settlement_payload import (
    bind_decision_options,
    decision_has_rescript_capability,
    parse_rescript_capability_pair,
)

_DecisionKey = str  # "{kind}:{source_turn}:{idx}"


def _parse_decision_key(key: object) -> Tuple[str, int, int]:
    raw = str(key or "").strip()
    parts = raw.split(":")
    if len(parts) != 3:
        raise ValueError(f"非法 decision_key：{raw!r}")
    kind, turn_s, idx_s = parts
    if kind != "decision":
        raise ValueError(f"非法 decision_key.kind：{kind!r}")
    try:
        return kind, int(turn_s), int(idx_s)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"非法 decision_key 数字段：{raw!r}") from exc


def _stable_json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def project_preferred_hitl_choice(decision: Mapping[str, object]) -> Dict[str, object]:
    """验收探针的首选项投影：普通 decision 首 option 原样（补 decision_key）。"""
    options = decision.get("options") or []
    first = options[0] if options else {}
    if not isinstance(first, dict):
        first = {"label": str(first or "")}
    item = dict(first)
    dk = str(decision.get("decision_key") or "").strip()
    if not dk:
        kind = str(decision.get("kind") or "decision").strip() or "decision"
        turn = decision.get("source_turn", decision.get("turn"))
        idx = decision.get("idx")
        if turn is not None and idx is not None:
            dk = f"{kind}:{int(turn)}:{int(idx)}"
    if dk:
        item.setdefault("decision_key", dk)
    return item


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
    # 通用展示/批红字段（标识/自由文本串；stop_condition 走唯一保真缝，禁 str(dict)）
    from ming_sim.rescript_draft import normalize_stop_condition
    for key in (
        "label", "hint", "note",
        "action_type", "assignee_name", "name",
        "target_kind", "target_id", "transaction_category",
        "locality_scope", "region_id", "title", "commitment_kind",
        "station", "office",
        "grant_action", "account", "cadence", "execution_surface", "purpose",
        "appoint_action", "appointment_tenure", "punish_action",
        "privilege", "summon_target",
        "holder_id", "assignee_id", "assignee",
    ):
        if key in raw and raw[key] is not None:
            out[key] = str(raw[key]) if not isinstance(raw[key], (int, float, bool)) else raw[key]
            if isinstance(out[key], bool):
                out[key] = str(out[key])
    if "stop_condition" in raw and raw["stop_condition"] is not None:
        out["stop_condition"] = normalize_stop_condition(raw["stop_condition"])
    for key in ("end_turn", "deadline_months", "due_turn", "amount",
                "dossier_id", "applied_from_revision_round", "revision_round"):
        if key in raw and raw[key] is not None and raw[key] != "":
            try:
                out[key] = int(raw[key])  # type: ignore[arg-type]
            except (TypeError, ValueError) as exc:
                raise ValueError(f"choice.{key} 非法：{raw[key]!r}") from exc
    # #1778 决定 3：参与名单是结构化列表，原样保留（str() 会把它压成字面量）
    if isinstance(raw.get(PARTICIPANT_ROSTER_KEY), list):
        out[PARTICIPANT_ROSTER_KEY] = raw[PARTICIPANT_ROSTER_KEY]
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




@dataclass
class ValidatedItem:
    decision_key: str
    kind: str
    source_turn: int
    idx: int
    row: Dict[str, object]
    choice: Dict[str, object]
    already_applied: bool = False


@dataclass
class ValidatedBatch:
    items: List[ValidatedItem] = field(default_factory=list)


@dataclass
class PrewriteResults:
    """旧 revise/deliberate 预写容器；现役为空壳，保留 apply 签名。"""


@dataclass
class ApplyResult:
    applied_keys: List[str] = field(default_factory=list)
    skipped_keys: List[str] = field(default_factory=list)


def validate_request_keys(
    desk_rows: Sequence[Mapping[str, object]],
    request_choices: object,
) -> Tuple[Dict[str, Dict[str, object]], Dict[str, Dict[str, object]]]:
    """①-a 请求索引校验（内存，零写库）。

    - 键∈desk；无重复；choice 缺 decision_key 或引用 desk 外键→整批拒
    - 仅校验 envelope/key membership，不比较/采纳 choice 内容
    - 返回 (desk_by_key, choice_map) 供 validate_all 续接完整校验
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
        choice_map[key] = dict(raw)

    return desk_by_key, choice_map


def validate_all(
    desk_rows: Sequence[Mapping[str, object]],
    request_choices: object,
    *,
    default_hold_missing: bool = True,
    can_summon: Optional[object] = None,
) -> ValidatedBatch:
    """Validate-all（内存，零写库）。

    现役只受理 kind=decision：普通 HITL 与 0055 案卷三选。
    default_hold_missing / can_summon 保留签名兼容，急务缺省 hold/召见已退役。
    """
    del default_hold_missing, can_summon
    desk_by_key, choice_map = validate_request_keys(desk_rows, request_choices)
    choice_map = {key: canonical_choice(raw) for key, raw in choice_map.items()}
    for key, choice in choice_map.items():
        row = desk_by_key[key]
        if (
            str(row.get("kind") or "decision") == "decision"
            and not (
                str(row.get("event_id") or "").startswith("dossier:")
                and decision_has_rescript_capability(row)
            )
        ):
            choice["action"] = "decision"

    batch = ValidatedBatch()
    for key, row in desk_by_key.items():
        status = str(row.get("status") or "pending")
        stored_choice = row.get("choice")
        req = choice_map.get(key)
        kind = str(row.get("kind") or "decision")
        source_turn = int(
            row.get("source_turn") if row.get("source_turn") is not None else row.get("turn") or 0
        )
        idx = int(row.get("idx") or 0)

        if kind != "decision":
            raise ValueError(f"已退役案头 kind：{kind!r} key={key}")

        if status == "decided":
            if req is None:
                raise ValueError(f"decided 行缺请求 choice：{key}")
            if _choice_empty(stored_choice) or not _choices_equal(stored_choice, req):
                raise ValueError(f"decided 行 choice 不匹配：{key}")
            batch.items.append(ValidatedItem(
                decision_key=key, kind=kind, source_turn=source_turn, idx=idx,
                row=row, choice=req, already_applied=True,
            ))
            continue

        if req is None:
            raise ValueError(f"pending 行缺请求 choice：{key}")

        # dossier 批红 decision 行（#1490 / 0055 法定三选）
        if (
            str(row.get("event_id") or "").startswith("dossier:")
            and decision_has_rescript_capability(row)
        ):
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
                decision_key=key, kind=kind, source_turn=source_turn, idx=idx,
                row=row, choice=rebuilt,
            ))
            continue

        # 普通 decision：票拟按 label 命中。请旨另许仅有亲笔 note 的答复。
        from ming_sim.month_chain import (
            _DECREE_QUESTION_PREFIX, _LEVY_PETITION_PREFIX, _WORLD_QUESTION_PREFIX,
        )

        event_id = str(row.get("event_id") or "")
        label = str(req.get("label") or "")
        note = str(req.get("note") or "")
        if (
            not label.strip()
            and note.strip()
            and (
                event_id.startswith(_DECREE_QUESTION_PREFIX)
                or event_id.startswith(_WORLD_QUESTION_PREFIX)
                or event_id.startswith(_LEVY_PETITION_PREFIX)
            )
        ):
            batch.items.append(ValidatedItem(
                decision_key=key, kind=kind, source_turn=source_turn, idx=idx,
                row=row, choice=req,
            ))
            continue
        labels = bind_decision_options(row.get("options") or [])
        if label not in labels:
            raise ValueError(f"decision 选项不在当前 options：{key}")
        batch.items.append(ValidatedItem(
            decision_key=key, kind=kind, source_turn=source_turn, idx=idx,
            row=row, choice=req,
        ))

    return batch


def run_prewrite_llms(
    batch: ValidatedBatch,
    *,
    revise_runner: Optional[object] = None,
    deliberate_runner: Optional[object] = None,
    max_workers: int = 8,
) -> PrewriteResults:
    """旧急务 revise/deliberate 预写已退役；保留空壳签名。"""
    del batch, revise_runner, deliberate_runner, max_workers
    return PrewriteResults()


def map_rescript_option_or_choice(
    fields: Mapping[str, object],
    *,
    mode: str = "ordinary",
    db: Any = None,
    content: Any = None,
    state: Any = None,
) -> Dict[str, object]:
    """逐类 mapper（C.2–C.7）：option/choice → 预 normalize payload。

    类特定显式闸在 normalize 前完成；返回的 payload 供
    ``db._normalize_directive_dossier_payload`` 唯一结构边界使用。
    #1778：受理值域＝库级全集；无类特定分支的类型按原类型直落一份案卷。
    """
    src = dict(fields)
    action_type = str(src.get("action_type") or "").strip()
    if action_type not in DOSSIER_ACTION_TYPES:
        raise ValueError(f"action_type 非库级全集：{action_type!r}")
    incoming_action_type = action_type

    target_kind = str(src.get("target_kind") or "").strip()
    target_id = str(src.get("target_id") or "").strip()
    if target_kind not in TARGET_KINDS:
        raise ValueError(f"target_kind 非法：{target_kind!r}")
    if not target_id:
        raise ValueError("target_id 不可空")

    # P6：自由文本 strip 仅判空；payload/decree_text 落原文
    label_raw = str(src.get("label") or "")
    note_raw = str(src.get("note") or "")
    decree_text = note_raw if note_raw.strip() else label_raw
    label = label_raw
    assignee_name = str(src.get("assignee_name") or src.get("assignee") or "").strip()
    region_id = str(src.get("region_id") or "").strip()

    payload: Dict[str, object] = {
        "dossier_action_type": action_type,
        "mode": "midzhi" if mode == "midzhi" else "ordinary",
        "target_kind": target_kind,
        "target_id": target_id,
        "region_id": region_id,
        "label": label,
        "hint": str(src.get("hint") or ""),
    }
    # §C.8 可选 provenance：payload 普通字段写 decision_key（非第二幂等真源）。
    # midzhi 必须带既有 decision identity，供频度按 distinct identity 计数。
    decision_key = str(src.get("decision_key") or "").strip()
    if mode == "midzhi":
        if not decision_key:
            raise ValueError("midzhi 缺 decision_key（既有 decision identity）")
        payload["decision_key"] = decision_key
    elif decision_key:
        payload["decision_key"] = decision_key
    if assignee_name:
        payload["assignee_id"] = assignee_name
        payload["assignee_name"] = assignee_name
    # #1778 决定 3/5：拟票大臣写的参与名单原样随载荷走到成案点钉进案卷；
    # 归一/存在性由 create_decree_dossiers 的 0053 单一校验口负责，此处不重判。
    roster = src.get(PARTICIPANT_ROSTER_KEY)
    if isinstance(roster, list) and roster:
        payload[PARTICIPANT_ROSTER_KEY] = roster

    current_turn = int(getattr(state, "turn", 0) or 0)

    if action_type == "assignment":
        cat = str(src.get("transaction_category") or "").strip()
        if not cat and not assignee_name:
            raise ValueError("assignment 缺 transaction_category 与主办")
        if cat:
            payload["transaction_category"] = cat
        title_raw = str(src.get("title") or label or "")
        if title_raw.strip():
            if len(title_raw) > 80:
                raise ValueError(f"assignment title 超 80 字：{len(title_raw)}")
            payload["title"] = title_raw  # 原文；超长响亮拒绝，不截断
        ck = str(src.get("commitment_kind") or "无").strip() or "无"
        payload["commitment_kind"] = ck
        from ming_sim.rescript_draft import normalize_stop_condition
        stop = normalize_stop_condition(src.get("stop_condition"))
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
        station = str(src.get("station") or "")
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
        # #1620：金额/account shape 唯一权威 require_grant_allocation_shape（层 A 同缝）
        shaped = require_grant_allocation_shape(
            grant_action=src.get("grant_action"),
            amount=src.get("amount"),
            account=src.get("account"),
        )
        ga = str(shaped["grant_action"])
        account = str(shaped["account"])
        payload["grant_action"] = ga
        payload["account"] = account
        g_kind, g_tid = _grant_target({
            "grant_action": ga,
            "name": str(src.get("name") or assignee_name or ""),
            "target_id": target_id,
            "target_kind": str(src.get("target_kind") or target_kind or ""),
        })
        # 协饷必须真 army；五字段走单一权威接缝，禁止默认国库/army/purpose。
        if ga == "协饷":
            from ming_sim.action_materialize import (
                canonicalize_xiexang_army_target,
                require_explicit_xiexang_fields,
            )
            explicit = require_explicit_xiexang_fields(
                amount=shaped.get("amount", src.get("amount")),
                account=account,
                purpose=str(src.get("purpose") or ""),
                target_kind=g_kind,
                target_id=g_tid,
                cadence=str(src.get("cadence") or ""),
            )
            army_id = str(explicit["target_id"])
            if db is not None:
                army_id = canonicalize_xiexang_army_target(db, army_id)
            elif not army_id:
                raise ValueError("协饷 target 须为真实 army id")
            payload["target_kind"] = "army"
            payload["target_id"] = army_id
            payload["purpose"] = explicit["purpose"]
            payload["amount"] = explicit["amount"]
            payload["account"] = explicit["account"]
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
            payload["amount"] = int(shaped["amount"])
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
        name = str(src.get("name") or "").strip()
        # 单一边界：name 与 target_id 皆非空且不一致 → 整批拒（禁静默择一改写）
        if name and target_id and name != target_id:
            raise ValueError(
                f"appointment/dismiss name 与 target_id 冲突：{name!r} vs {target_id!r}"
            )
        name = name or target_id
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
        name = str(src.get("name") or "").strip()
        # 与 appointment 同形：双非空且不一致 → 整批拒（禁静默 name or target_id 改写）
        if name and target_id and name != target_id:
            raise ValueError(
                f"punishment name 与 target_id 冲突：{name!r} vs {target_id!r}"
            )
        name = name or target_id
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
        name = str(src.get("name") or "").strip()
        # 与 appointment/punishment 同形：双非空且不一致 → 整批拒
        if name and target_id and name != target_id:
            raise ValueError(
                f"pacification name 与 target_id 冲突：{name!r} vs {target_id!r}"
            )
        name = name or target_id
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
    # #1778 决定 1「批了必须成案」：未改写的类型按原类型成案（值域＝库级全集）；
    # emitted 闭集只管映射终点（罢免→dismiss_assignment），不再当准入闸。
    allowed_emitted = (
        DOSSIER_ACTION_TYPES if emitted == incoming_action_type
        else RESCRIPT_EMITTED_DOSSIER_ACTION_TYPES
    )
    if emitted not in allowed_emitted:
        raise ValueError(f"emitted action_type 非法：{emitted!r}")
    if emitted in {"appointment", "dismiss_assignment", "punishment"} or (
        emitted == "grant_allocation"
        and str(payload.get("grant_action") or "") in {"赏赉", "发内帑", "加衔", "荫叙"}
    ):
        payload["name"] = str(payload.get("target_id") or payload.get("name") or "")

    # #1624：共同契约组装 locality/region/承办；禁止按 target_kind 覆盖已给 scope
    from ming_sim.structured_decree import assemble_structured_decree, apply_assembled_to_payload
    assembled = assemble_structured_decree(
        {
            **payload,
            **src,
            "action_type": emitted,
            "target_kind": payload.get("target_kind") or target_kind,
            "target_id": payload.get("target_id") or target_id,
        },
        validate=True,
    )
    apply_assembled_to_payload(payload, assembled)
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


def apply_imperial_deliberation_push(
    db: Any,
    state: Any,
    *,
    target_dossier_id: int,
    directive_identity: str,
    decree_text: str = "",
    mode: str | None = None,
    commit: bool = False,
) -> int:
    """自由下旨御笔强推 stalled 廷议：复用案卷 + 御笔手敕 + stalled→backed。

    directive_identity＝本次自由下旨 durable identity（decision_key provenance）。
    mode 为 push 载荷已归一的 mode 真源；写入原案卷 payload.mode，禁第二存储。
    """
    did = int(target_dossier_id)
    dkey = str(directive_identity or "").strip()
    if not dkey:
        raise ValueError("御笔强推缺 directive identity")
    row = db.get_decree_dossier(did)
    if row is None:
        raise ValueError(f"御笔强推目标案卷不存在：{did}")
    if str(row.get("status") or "") != "proposed":
        raise ValueError(f"御笔强推只接 proposed 案卷：{did}")
    payload = row.get("payload")
    if not isinstance(payload, dict):
        payload = json.loads(str(row.get("payload_json") or "{}"))
    if not isinstance(payload, dict):
        raise ValueError("廷议案卷 payload 非对象")
    if str(payload.get("deliberation_state") or "") != "stalled":
        raise ValueError(f"御笔强推只接 stalled 廷议：{did}")
    origin = f"dossier:{did}"
    issue = db.conn.execute(
        "SELECT id, status FROM issues WHERE origin_ref=? AND status='active' LIMIT 1",
        (origin,),
    ).fetchone()
    if issue is None:
        raise ValueError(f"御笔强推要求 active issue origin_ref={origin}")
    new_payload = dict(payload)
    new_payload["deliberation_state"] = "backed"
    if mode is not None:
        # 贯穿既有 mode 真源（payload.mode）；普通缺省 ordinary 亦显式落库
        new_payload["mode"] = db._normalize_dossier_mode(mode)
    if decree_text and not str(new_payload.get("imperial_push_note") or ""):
        new_payload["imperial_push_note"] = str(decree_text)
    db.update_decree_dossier_payload(did, new_payload, commit=False)
    db.add_dossier_endorsement(
        did,
        form="御笔手敕",
        endorser_id="",
        imperial=True,
        decision_key=dkey,
        source_chat_turn_id=0,
        commit=False,
    )
    # #658：stalled→backed 同事务终结 origin_ref 投影 issue，禁 durable ledger 自相矛盾
    db.close_issue(
        state,
        int(issue["id"]),
        reason="resolved",
        narrative=str(decree_text or new_payload.get("title") or "御笔强推"),
        commit=False,
    )
    if commit:
        db.conn.commit()
    return did


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
    """单 DB 事务：decision 行 choice + decided（普通 HITL / 0055 三选）。"""
    del prewrite
    result = ApplyResult()
    with atomic_and_reload(db, state, content=content):
        for item in batch.items:
            if item.already_applied:
                result.skipped_keys.append(item.decision_key)
                continue
            if item.kind != "decision":
                raise ValueError(f"已退役案头 kind：{item.kind!r}")
            _cas_decided(db, item)
            event_id = str(item.row.get("event_id") or "").strip()
            from ming_sim.month_chain import (
                _DECREE_QUESTION_PREFIX, _LEVY_PETITION_PREFIX, _WORLD_QUESTION_PREFIX,
            )
            if event_id.startswith(_LEVY_PETITION_PREFIX):
                db.record_event_petition_answer(
                    state, event_id[len(_LEVY_PETITION_PREFIX):], item.choice,
                    {
                        "title": str(item.row.get("title") or ""),
                        "context": str(item.row.get("context") or ""),
                        "options": [
                            str(opt.get("label") or "")
                            for opt in (item.row.get("options") or []) if isinstance(opt, dict)
                        ],
                    },
                    commit=False,
                )
                result.applied_keys.append(item.decision_key)
                continue
            if (
                event_id
                and not event_id.startswith("dossier:")
                and not event_id.startswith(_WORLD_QUESTION_PREFIX)
                and not event_id.startswith(_DECREE_QUESTION_PREFIX)
            ):
                db.record_event_decision_choice(
                    state, event_id, item.choice, commit=False,
                )
            result.applied_keys.append(item.decision_key)
    return result


