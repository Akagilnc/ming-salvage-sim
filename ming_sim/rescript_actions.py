"""批红案头：普通 decision / 0055 案卷三选。

公开 API：canonical_choice / validate_request_keys / validate_all / apply_rescript_batch
旧急务六动作、预写、层 A mapper、兼容壳已退役。
禁模块内持 write_gate；禁 resolve_context 承载本批 choices。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ming_sim.decree import atomic_and_reload
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
    """确定性规范化 choice：decision/0055 案头字段；旧急务专属键不接收。"""
    if not isinstance(raw, dict):
        raise ValueError("choice 须为 object")
    out: Dict[str, object] = {}
    decision_key = str(raw.get("decision_key") or "").strip()
    if decision_key:
        _parse_decision_key(decision_key)
        out["decision_key"] = decision_key
    action = str(raw.get("action") or raw.get("dossier_decision") or "").strip()
    if action:
        out["action"] = action
    for key in ("label", "hint", "note"):
        if key in raw and raw[key] is not None:
            out[key] = str(raw[key]) if not isinstance(raw[key], (int, float, bool)) else raw[key]
            if isinstance(out[key], bool):
                out[key] = str(out[key])
    if "dossier_id" in raw and raw["dossier_id"] is not None and raw["dossier_id"] != "":
        try:
            out["dossier_id"] = int(raw["dossier_id"])  # type: ignore[arg-type]
        except (TypeError, ValueError) as exc:
            raise ValueError(f"choice.dossier_id 非法：{raw['dossier_id']!r}") from exc
    if "dossier_decision" in raw and raw["dossier_decision"] is not None:
        out["dossier_decision"] = str(raw["dossier_decision"])
    if "dossier_id" in raw and "dossier_id" not in out:
        pair = parse_rescript_capability_pair(raw)
        if pair is not None:
            out["dossier_id"] = pair[0]
            out["dossier_decision"] = pair[1]
            out.setdefault("action", pair[1])
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
) -> ValidatedBatch:
    """Validate-all（内存，零写库）。现役只受理 kind=decision：普通 HITL 与 0055 三选。"""
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
    *,
    content: Any = None,
) -> ApplyResult:
    """单 DB 事务：decision 行 choice + decided（普通 HITL / 0055 三选）。"""
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
