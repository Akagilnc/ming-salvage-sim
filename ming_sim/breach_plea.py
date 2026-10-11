"""#623 / ADR 0075 挽留场——松手检测·哭谏·根基分档。

entry_kind = midcourse_breach_plea（坚持撤不另造第二 kind）。
stage_idx = 触发当回合 turn（同承诺先后两次松手各得独立哭谏条）。

kind 分派矩阵（法）：
- list_due_review_scenes：投影哭谏场面
- apply_pending_due_reviews：禁当 staged 终裁；沉默保留 pending
"""

from __future__ import annotations
from ming_sim.applier import parse_engine_payload_json
from ming_sim.staged_commitment import normalize_commitment_stages


import json
import logging
import re
from typing import Any, Dict, List, Optional, Sequence, Set

from ming_sim.models import (
    loads_effect_dict,
    _load_durable_json_object,
    require_persistent_string_list,
)
from ming_sim.participant_roster import decode_durable_participant_roster
from ming_sim.applier import durable_int, load_stored_list, load_stored_object
from ming_sim.models import loads_effect_dict
from ming_sim.staged_commitment import (
    TODO_STATUS_CONSUMED,
    TODO_STATUS_PENDING,
    load_commitment_stages,
)

logger = logging.getLogger(__name__)

ENTRY_KIND_BREACH_PLEA = "midcourse_breach_plea"

# 哭谏 todo.payload_json 判决痕迹（#626 path① 真源；不扩三态枚举）
PLEA_VERDICT_KEY = "verdict"
PLEA_VERDICT_PERSIST = "persist"
PLEA_VERDICT_EXPIRED = "expired"

BREACH_KIND_FUNDING = "funding_cutoff"
BREACH_KIND_MISAPPROPRIATION = "misappropriation"
BREACH_KIND_REMOVE_SPONSOR = "remove_sponsor"
BREACH_KIND_POLICY_REVERSAL = "policy_reversal"

BREACH_KIND_LABELS = {
    BREACH_KIND_FUNDING: "断供",
    BREACH_KIND_MISAPPROPRIATION: "挪用",
    BREACH_KIND_REMOVE_SPONSOR: "撤人",
    BREACH_KIND_POLICY_REVERSAL: "改弦",
}

# 坚持撤时触发 0056 毁约轨的松手类（0041③ 收权·罢差 / 撤人不触发）
_BREACH_KINDS_TRIGGER_0056 = frozenset({
    BREACH_KIND_FUNDING,
    BREACH_KIND_MISAPPROPRIATION,
    BREACH_KIND_POLICY_REVERSAL,
})

# 断供：当月实拨低于承诺月供的此比例 → 欠额达阈
_FUNDING_ARREARS_RATIO = 0.5


_DOSSIER_REF_RE = re.compile(r"^dossier:([1-9][0-9]*)(?::.*)?$")
_ISSUE_REF_RE = re.compile(r"^issue:([1-9][0-9]*)$")

_META_PREFIX = "breach_plea_meta:"


def parse_dossier_id(origin_ref: object) -> Optional[int]:
    """案卷 origin 回指唯一解析：``dossier:<正整数>``，允许后缀段（如 credit 边）。

    材料侧密令过滤与哭谏/信用/到期复核共用此口，禁平行再写一份。
    """
    text = str(origin_ref or "").strip()
    match = _DOSSIER_REF_RE.match(text)
    if not match:
        return None
    return int(match.group(1))


def parse_issue_id(origin_ref: object) -> Optional[int]:
    """issue:<id> — single strict regex copy; credit/due reuse this function."""
    text = str(origin_ref or "").strip()
    match = _ISSUE_REF_RE.match(text)
    if not match:
        return None
    return int(match.group(1))


def encode_plea_meta(meta: Dict[str, object]) -> str:
    """origin_context 承载机读元数据。"""
    payload = dict(meta or {})
    return _META_PREFIX + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def decode_plea_meta(origin_context: object) -> Dict[str, object]:
    """Machine-marked plea metadata is durable structure, not free prose.

    Missing prefix → no meta ({}). Prefixed but corrupt/non-object → raise.
    """
    text = str(origin_context or "")
    if not text.startswith(_META_PREFIX):
        return {}
    return parse_engine_payload_json(text[len(_META_PREFIX):])


def commitment_natural_due_turn(row: Any) -> int:
    """承诺自身 due：段表 max due，否则 end_turn；0=无到期上限。"""
    stages = normalize_commitment_stages(row["stages_json"])
    if stages:
        return max(int(s["due_turn"]) for s in stages)
    end_turn = int(row["end_turn"] or 0)
    return end_turn if end_turn > 0 else 0


def _commitment_origin_refs(row: Any, commitment_ref: int) -> Set[str]:
    refs: Set[str] = {f"issue:{int(commitment_ref)}"}
    origin = str(row["origin_ref"] or "").strip()
    if origin:
        refs.add(origin)
    return refs


def _sponsor_names_for_commitment(db: Any, row: Any) -> List[str]:
    names: List[str] = []
    # 承诺名册走共同权威；腐坏响亮，不 catch-to-[]（#1897 E1）。
    roster = decode_durable_participant_roster(row["participant_roster"])
    for item in roster:
        if item.get("tier") == "主办":
            cid = item["character_id"]
            if cid:
                names.append(cid)
    origin_ref = row["origin_ref"] or ""
    did = parse_dossier_id(origin_ref)
    if did is not None:
        # DossierStore.get 已响亮解码名册；再消费其结构化列表。
        dossier = db.dossiers.get(int(did))
        if dossier is not None:
            for item in decode_durable_participant_roster(
                dossier.get("participant_roster") or [],
                ):
                if item.get("tier") == "主办":
                    cid = str(item.get("character_id") or "").strip()
                    if cid and cid not in names:
                        names.append(cid)
            exec_id = str(dossier.get("executor_id") or "").strip()
            if exec_id and exec_id not in names:
                names.append(exec_id)
    return names


def _dedicated_accounts(row: Any) -> List[str]:
    """专款账户读口（真实 producer 可达）：

    1. tags 含「专款:X」——承诺立项 new_issues.tags 既有写口（prompt 钉专款标签）
    2. ongoing_effects.economy[].account——承诺月供账户即专款流向
    """
    accounts: List[str] = []
    seen: Set[str] = set()

    def _add(raw: object) -> None:
        acc = str(raw or "").strip()
        if acc and acc not in seen:
            seen.add(acc)
            accounts.append(acc)

    from ming_sim.db import _load_durable_str_list
    tags = _load_durable_str_list(row["tags"], surface="issues.tags")
    for tag in tags:
        t = tag.strip()
        if t.startswith("专款:"):
            _add(t.split(":", 1)[1].strip())

    ongoing = loads_effect_dict(row["ongoing_effects"] or "{}")
    economy = ongoing.get("economy") if isinstance(ongoing, dict) else None
    if isinstance(economy, list):
        for item in economy:
            if not isinstance(item, dict):
                raise ValueError(f"ongoing_effects.economy 成员须为对象，得 {type(item).__name__}")
            _add(item.get("account"))
    return accounts


def plea_kind_set(meta: Dict[str, object]) -> Set[str]:
    """merged 条所载松手类 = primary ∪ absorbed（persist 链统一读口）。"""
    kinds: Set[str] = set()
    primary = str(meta.get("breach_kind") or "").strip()
    if primary:
        kinds.add(primary)
    for kind in require_persistent_string_list(
        meta.get("absorbed_breach_kinds"), surface="breach_plea.meta", field="absorbed_breach_kinds",
    ):
        kinds.add(kind)
    return kinds


def find_pending_plea(
    db: Any,
    commitment_ref: int,
    *,
    breach_kind: str = "",
) -> Optional[Dict[str, object]]:
    """返回匹配的 pending 哭谏条；breach_kind 非空时按 primary∪absorbed 认。"""
    want = str(breach_kind or "").strip()
    for todo in db.dossiers.list_next_audience_todos(status=TODO_STATUS_PENDING):
        if str(todo.get("entry_kind") or "") != ENTRY_KIND_BREACH_PLEA:
            continue
        if int(todo.get("commitment_ref") or 0) != int(commitment_ref):
            continue
        if want:
            meta = decode_plea_meta(todo.get("origin_context"))
            if want not in plea_kind_set(meta):
                continue
        return todo
    return None


def has_pending_plea(
    db: Any,
    commitment_ref: int,
    *,
    breach_kind: str = "",
) -> bool:
    return find_pending_plea(db, commitment_ref, breach_kind=breach_kind) is not None


def _find_pending_plea_same_turn(
    db: Any, commitment_ref: int, turn: int,
) -> Optional[Dict[str, object]]:
    for todo in db.dossiers.list_next_audience_todos(status=TODO_STATUS_PENDING):
        if str(todo.get("entry_kind") or "") != ENTRY_KIND_BREACH_PLEA:
            continue
        if int(todo.get("commitment_ref") or 0) != int(commitment_ref):
            continue
        if int(todo.get("stage_idx") or 0) != int(turn):
            continue
        return todo
    return None


def _merge_plea_kind_into_todo(
    db: Any,
    todo: Dict[str, object],
    *,
    breach_kind: str,
    reason: str,
    target_dossier_id: int,
    extra: Optional[Dict[str, object]],
) -> int:
    """同回合第二类松手：显式并入既有 pending，log+meta 记全被吞类。"""
    meta = decode_plea_meta(todo.get("origin_context"))
    primary = str(meta.get("breach_kind") or "")
    absorbed_list = require_persistent_string_list(
        meta.get("absorbed_breach_kinds"), surface="breach_plea.meta", field="absorbed_breach_kinds",
    )
    kind = str(breach_kind or "").strip()
    if kind and kind != primary and kind not in absorbed_list:
        absorbed_list.append(kind)
        logger.info(
            "breach_plea merge: commitment=%s turn_todo=%s primary=%s absorbed+=%s",
            todo.get("commitment_ref"), todo.get("id"), primary, kind,
        )
    meta["absorbed_breach_kinds"] = absorbed_list
    # 保留首类 primary；补充理由/案卷
    incoming = str(reason or "")
    if incoming.strip() and not str(meta.get("reason") or "").strip():
        meta["reason"] = incoming
    elif incoming.strip():
        prev = str(meta.get("reason") or "")
        if incoming not in prev:
            meta["reason"] = f"{prev}；{incoming}"
    if int(target_dossier_id or 0) > 0 and int(meta.get("target_dossier_id") or 0) <= 0:
        meta["target_dossier_id"] = int(target_dossier_id)
    if extra:
        for k, v in extra.items():
            if k not in meta:
                meta[k] = v
    encoded = encode_plea_meta(meta)
    db.dossiers.write_merge_plea_kind_into_todo((encoded, int(todo["id"])))
    # criterion 保持首类标签；多类痕迹在 meta
    return int(todo["id"])


def write_breach_plea_todo(
    db: Any,
    state: Any,
    *,
    commitment_ref: int,
    breach_kind: str,
    reason: str = "",
    target_dossier_id: int = 0,
    extra: Optional[Dict[str, object]] = None,
) -> int:
    """松手当回合写挽留 todo。stage_idx=触发 turn。

    返回新建或并入的 todo id；承诺无效返回 0。
    同回合第二类：并入既有 pending（UNIQUE 不静默吞）。
    """
    row = db.issues.row(int(commitment_ref))
    if row is None or str(row["status"] or "") != "active":
        return 0
    if not str(row["commitment_kind"] or "").strip():
        return 0
    turn = int(getattr(state, "turn", 0) or 0)
    kind = str(breach_kind or "").strip()
    if kind not in BREACH_KIND_LABELS:
        raise ValueError(f"未知松手类型：{kind}")
    label = BREACH_KIND_LABELS[kind]
    due = commitment_natural_due_turn(row)
    due_turn = due if due > 0 else turn
    title = str(row["title"] or "")

    # 同回合已有条 → 并入（禁 UNIQUE+IGNORE 静默吞）
    existing = _find_pending_plea_same_turn(db, int(commitment_ref), turn)
    if existing is not None:
        existing_meta = decode_plea_meta(existing.get("origin_context"))
        existing_primary = str(existing_meta.get("breach_kind") or "")
        known = {existing_primary, *require_persistent_string_list(
            existing_meta.get("absorbed_breach_kinds"),
            surface="breach_plea.meta", field="absorbed_breach_kinds",
        )}
        if kind in known:
            # 同类幂等：返回既有 id
            return int(existing["id"])
        return _merge_plea_kind_into_todo(
            db, existing,
            breach_kind=kind,
            reason=str(reason) if str(reason or "").strip() else label,
            target_dossier_id=int(target_dossier_id or 0),
            extra=extra,
        )

    meta: Dict[str, object] = {
        "breach_kind": kind,
        "reason": str(reason) if str(reason or "").strip() else label,
        "target_dossier_id": int(target_dossier_id or 0),
        "commitment_title": title,
        "absorbed_breach_kinds": [],
    }
    if extra:
        for k, v in extra.items():
            if k not in meta:
                meta[k] = v
    todo_id = db.dossiers.insert_next_audience_todo(
        commitment_ref=int(commitment_ref),
        stage_idx=turn,  # 法：触发当回合 turn
        due_turn=int(due_turn),
        criterion_text=label,
        origin_context=encode_plea_meta(meta),
        status=TODO_STATUS_PENDING,
        entry_kind=ENTRY_KIND_BREACH_PLEA,
        created_turn=turn,
        commit=False,
    )
    if todo_id == 0:
        # 竞态/IGNORE：再读并入，不得返 0 掩蔽
        existing = _find_pending_plea_same_turn(db, int(commitment_ref), turn)
        if existing is not None:
            return _merge_plea_kind_into_todo(
                db, existing,
                breach_kind=kind,
                reason=str(reason) if str(reason or "").strip() else label,
                target_dossier_id=int(target_dossier_id or 0),
                extra=extra,
            )
        logger.warning(
            "breach_plea write returned 0 without pending row commitment=%s kind=%s",
            commitment_ref, kind,
        )
        return 0
    return int(todo_id or 0)


def project_breach_plea_scene(todo: Dict[str, object]) -> Dict[str, object]:
    meta = decode_plea_meta(todo.get("origin_context"))
    breach_kind = str(meta.get("breach_kind") or "")
    label = BREACH_KIND_LABELS.get(breach_kind, str(todo.get("criterion_text") or "松手"))
    return {
        "kind": "breach_plea",
        "entry_kind": ENTRY_KIND_BREACH_PLEA,
        "todo_id": int(todo["id"]),
        "commitment_ref": int(todo["commitment_ref"]),
        "stage_idx": int(todo["stage_idx"]),
        "due_turn": int(todo.get("due_turn") or 0),
        "breach_kind": breach_kind,
        "criterion_text": str(todo.get("criterion_text") or label),
        "commitment_title": str(meta.get("commitment_title") or ""),
        "reason": str(meta.get("reason") or ""),
        "absorbed_breach_kinds": require_persistent_string_list(
            meta.get("absorbed_breach_kinds"), surface="breach_plea.meta", field="absorbed_breach_kinds",
        ),
        "channel": "audience_pending",
    }


def reclaim_bundled_authorities(
    db: Any,
    state: Any,
    *,
    target_dossier_id: int,
    source_dossier_id: int,
) -> List[Dict[str, object]]:
    """捆带授权收回：授予源=被撤案卷 → authority_changes 收回（两道 fail-loud）。

    与 _apply_revoke_decree_verdict_effect 立即路径同核，禁复制分叉。
    """
    if int(target_dossier_id or 0) <= 0:
        return []
    bundled = db.characters.read_reclaim_bundled_authorities(
        (int(target_dossier_id),)
    )
    if not bundled:
        return []
    src = int(source_dossier_id or 0)
    if src <= 0:
        src = int(target_dossier_id)
    changes = [{
        "动作": "收回",
        "authority_id": int(b["id"]),
        "dossier_id": src,
    } for b in bundled]
    # 延迟 import 避循环
    from ming_sim.settlement import SettlementContext, settle_delta

    outcome = settle_delta(
        state, db, {"authority_changes": changes}, SettlementContext(),
    )
    for rejected in outcome.authority.rejected:
        raise ValueError(rejected.reason or "捆带授权收回被拒")
    if len(outcome.authority.applied) < len(changes):
        raise ValueError("捆带授权收回未完整落库")
    return list(outcome.authority.applied)


def stop_origin_commitment_ticks(
    db: Any,
    state: Any,
    *,
    target_dossier_id: int,
    reason: str,
    extra_issue_ids: Optional[Sequence[int]] = None,
) -> List[int]:
    """同源 active 承诺停 tick（与立即 revoke 路径同核）。

    只停带 commitment_kind 的承诺；不无差别取消 cancellable=never 的世界局势
    （ADR 0075 #1894／0154）。
    """
    stopped: List[int] = []
    if int(target_dossier_id or 0) > 0:
        origin_ref = f"dossier:{int(target_dossier_id)}"
        for iss in db.issues.read_stop_origin_commitment_ticks((origin_ref,)):
            if not str(iss["commitment_kind"] or "").strip():
                continue
            if str(iss["cancellable"] or "") == "never":
                continue
            iid = int(iss["id"])
            db.cancel_issue(state, iid, narrative=reason, commit=False)
            stopped.append(iid)
    for raw in extra_issue_ids or ():
        iid = int(raw)
        if iid <= 0 or iid in stopped:
            continue
        row_i = db.issues.read_stop_origin_commitment_ticks_issues((iid,))
        if row_i is None or str(row_i["status"]) != "active":
            continue
        if not str(row_i["commitment_kind"] or "").strip():
            continue
        if str(row_i["cancellable"] or "") == "never":
            continue
        db.cancel_issue(state, iid, narrative=reason, commit=False)
        stopped.append(iid)
    return stopped


def apply_persist_revoke_tail(
    db: Any,
    state: Any,
    *,
    target_dossier_id: int,
    reason: str,
    apply_0056: bool,
    commitment_ref: int = 0,
    authority_source_dossier_id: int = 0,
    revoke_dossier_id: int = 0,
) -> Dict[str, object]:
    """撤旨落地唯一收尾：0056 毁约代价 + 捆带授权收回 + 同源承诺停 tick。

    0056 只落名声账，案卷结案留给执行格判官本月的 ``dossier_executions``——
    撤令与坚持撤都不抢在模型声明前关案。``revoke_dossier_id`` 非零时另恢复
    该撤令案卷带来的 pay_order override（见 pay_order.restore_pay_order_override）。

    返回 guofu_from_0056：本调用 0056 实际写出的辜负边人名
    （供 0079 撤人边去重；跨承诺/跨案卷同人边不在此集合）。
    """
    breach_applied = False
    guofu_from_0056: Set[str] = set()
    did = int(target_dossier_id or 0)
    restored_overrides: List[Dict[str, object]] = []
    if did > 0 and int(revoke_dossier_id or 0) > 0:
        from ming_sim.pay_order import restore_pay_order_override
        restored_overrides = restore_pay_order_override(
            db,
            turn=int(state.turn),
            target_dossier_id=did,
            revoke_dossier_id=int(revoke_dossier_id),
            reason=reason,
        )
    if apply_0056 and did > 0:
        breach_applied = db.breach_decree_dossier(
                state, did, reason=reason, commit=False,
            )
        if breach_applied:
            # 0056 写 origin=dossier:{id}:breach；bind_origin_round 附 |round:T
            # 只收本调用刚落的边（breach_applied 门控 = 本调用实写）
            guofu_from_0056 = _guofu_targets_of_0056(
                db, dossier_id=did, turn=int(state.turn),
            )
    auth_rows: List[Dict[str, object]] = []
    if did > 0:
        auth_rows = reclaim_bundled_authorities(
            db, state,
            target_dossier_id=did,
            source_dossier_id=int(authority_source_dossier_id or did),
        )
    extra = [int(commitment_ref)] if int(commitment_ref or 0) > 0 else []
    stopped = stop_origin_commitment_ticks(
        db, state,
        target_dossier_id=did,
        reason=reason,
        extra_issue_ids=extra,
    )
    return {
        "breach_0056": breach_applied,
        "guofu_from_0056": guofu_from_0056,
        "authority_reclaims": auth_rows,
        "stopped_issue_ids": stopped,
        "restored_pay_order_overrides": restored_overrides,
    }


def _guofu_targets_of_0056(
    db: Any, *, dossier_id: int, turn: int,
) -> Set[str]:
    """本 dossier 本回合 0056 实写的皇帝→target 辜负边人名。

    仅匹配 origin 前缀 dossier:{dossier_id}:breach（bind_origin_round 附 |round:T）。
    不扫其它承诺/其它案卷的同人边——0079 去重不得据此吞跨案账。
    """
    did = int(dossier_id or 0)
    if did <= 0:
        return set()
    rows = db.person_logs.read_guofu_targets_of_0056((int(turn), f"dossier:{did}:breach%"))
    return {str(r["target"]) for r in rows if str(r["target"] or "").strip()}


def finalize_persist(
    db: Any,
    state: Any,
    todo: Dict[str, object],
) -> Dict[str, object]:
    """坚持撤：只落代码该落的账——0056 名声、捆带授权收回、同源承诺停 tick、消费 todo。

    分档、执行格终值与半途国势倒退归模型经 dossier_executions／metric 声明落
    （ADR 0075 #1894／P6）；本函数不得代判或抢先关案。
    """
    meta = decode_plea_meta(todo.get("origin_context"))
    breach_kind = str(meta.get("breach_kind") or "")
    # merged meta 账目（#623 r2/r3）：
    # - 0056：所载类集合 primary∪absorbed 任一属 _BREACH_KINDS_TRIGGER_0056 即触发一次
    # - 0079 撤人边：所载含 remove_sponsor 即落；仅与本 finalize 自己的 0056
    #   实写同人去重（tail.guofu_from_0056；origin 前缀 dossier:{id}:breach）。
    #   跨承诺/跨案卷同人边各落各账，UNIQUE 键含 origin 本就允许。
    kinds = plea_kind_set(meta)
    raw_reason = str(meta.get("reason") or todo.get("criterion_text") or "")
    reason = raw_reason if raw_reason.strip() else "坚持撤诺"
    commitment_ref = int(todo["commitment_ref"])
    row = db.issues.row(int(commitment_ref))
    origin_ref = str(row["origin_ref"] if row is not None else "")
    target_dossier_id = int(meta.get("target_dossier_id") or 0)
    revoke_dossier_id = int(meta.get("revoke_dossier_id") or 0)
    if target_dossier_id <= 0:
        parsed = parse_dossier_id(origin_ref)
        target_dossier_id = int(parsed or 0)

    apply_0056 = bool(kinds & _BREACH_KINDS_TRIGGER_0056)
    tail = apply_persist_revoke_tail(
        db, state,
        target_dossier_id=target_dossier_id,
        reason=reason,
        apply_0056=apply_0056,
        commitment_ref=commitment_ref,
        revoke_dossier_id=revoke_dossier_id,
    )
    breach_applied = bool(tail.get("breach_0056"))

    # 0079 信用事件：坚持=回绝哭谏
    # 所载含撤人 → 按主办集合落辜负；仅跳过本 finalize 0056 已实写同人
    # （不重复）；其它承诺/案卷同人边不在 already，不得吞（不遗漏）
    # 无撤人且无案卷且未走 0056 → 兜底辜负
    if BREACH_KIND_REMOVE_SPONSOR in kinds:
        sponsors = _sponsor_names_for_commitment(db, row) if row is not None else []
        already = set(tail.get("guofu_from_0056") or ())
        for person in sponsors:
            if person in already:
                continue
            db.record_relation_edge_event(
                source="皇帝", target=person, event_kind="辜负", context=reason,
                origin=f"issue:{commitment_ref}:breach_plea", turn=state.turn,
                year=state.year, period=state.period,
            )
    elif target_dossier_id <= 0 and not breach_applied:
        # 无案卷且未走 0056：兜底辜负
        sponsors = _sponsor_names_for_commitment(db, row) if row is not None else []
        for person in sponsors:
            db.record_relation_edge_event(
                source="皇帝", target=person, event_kind="辜负", context=reason,
                origin=f"issue:{commitment_ref}:breach_plea", turn=state.turn,
                year=state.year, period=state.period,
            )

    consumed = db.dossiers.mark_next_audience_todo_status(
        int(todo["id"]), TODO_STATUS_CONSUMED,
        payload_patch={PLEA_VERDICT_KEY: PLEA_VERDICT_PERSIST},
        commit=False,
    )
    return {
        "decision": "persist",
        "todo_id": int(todo["id"]),
        "commitment_ref": commitment_ref,
        "breach_kind": breach_kind,
        "breach_0056": breach_applied,
        "authority_reclaims": tail.get("authority_reclaims") or [],
        "consumed": bool(consumed),
    }


def expire_breach_pleas_on_due(
    db: Any, state: Any,
) -> List[Dict[str, object]]:
    """承诺 due 到 → 挽留条目 consumed/失效；不走坚持撤分档、不补 0056/事轴倒退。"""
    turn = int(getattr(state, "turn", 0) or 0)
    results: List[Dict[str, object]] = []
    for todo in db.dossiers.list_next_audience_todos(status=TODO_STATUS_PENDING):
        if str(todo.get("entry_kind") or "") != ENTRY_KIND_BREACH_PLEA:
            continue
        commitment_ref = int(todo["commitment_ref"])
        row = db.issues.row(int(commitment_ref))
        if row is None or str(row["status"] or "") != "active":
            db.dossiers.mark_next_audience_todo_status(
                int(todo["id"]), TODO_STATUS_CONSUMED,
                payload_patch={PLEA_VERDICT_KEY: PLEA_VERDICT_EXPIRED},
                commit=False,
            )
            results.append({
                "todo_id": int(todo["id"]),
                "expired": True,
                "reason": "commitment_inactive",
            })
            continue
        natural_due = commitment_natural_due_turn(row)
        if natural_due > 0 and natural_due <= turn:
            db.dossiers.mark_next_audience_todo_status(
                int(todo["id"]), TODO_STATUS_CONSUMED,
                payload_patch={PLEA_VERDICT_KEY: PLEA_VERDICT_EXPIRED},
                commit=False,
            )
            results.append({
                "todo_id": int(todo["id"]),
                "expired": True,
                "reason": "commitment_due",
                "due_turn": natural_due,
            })
    return results


# ── 四类松手检测 ──────────────────────────────────────────────────────


def _promised_monthly_amount(row: Any) -> int:
    ongoing = loads_effect_dict(row["ongoing_effects"] or "{}")
    economy = ongoing.get("economy")
    total = 0
    if economy is not None:
        if not isinstance(economy, list):
            raise ValueError(f"ongoing_effects.economy 须为数组，得 {type(economy).__name__}")
        for it in economy:
            if not isinstance(it, dict):
                continue
            delta = int(it.get("delta") or 0)
            if delta < 0:
                total += -delta
            elif delta > 0:
                total += delta
    return total


def _ledger_paid_this_turn(db: Any, origin_refs: Set[str], turn: int) -> int:
    if not origin_refs:
        return 0
    paid = 0
    for oref in origin_refs:
        for r in db.reign.read_ledger_paid_this_turn((oref, turn)):
            paid += abs(int(r["delta"] or 0))
    return paid


def _had_prior_funding(db: Any, origin_refs: Set[str], turn: int) -> bool:
    for oref in origin_refs:
        n = int(db.reign.read_had_prior_funding((oref, turn))["c"])
        if n > 0:
            return True
        n = db.fiscal_config.creation_count(oref)
        if n > 0:
            return True
    return False


def _fiscal_funding_cut_this_turn(
    db: Any, origin_refs: Set[str], turn: int,
) -> bool:
    """fiscal_removes/tombstones 或 fiscal 减额命中本承诺 origin。"""
    for oref in origin_refs:
        row = db.fiscal_config.read_fiscal_funding_cut_this_turn((oref, turn))
        if row is not None:
            return True
        # 减额至 0 或大幅削减
        ch = db.fiscal_config.reduction_at(oref, turn)
        if ch is not None:
            old_v, new_v = int(ch["old_value"]), int(ch["new_value"])
            if old_v > 0 and new_v <= 0:
                return True
            if old_v > 0 and new_v < old_v * _FUNDING_ARREARS_RATIO:
                return True
    return False


def _scan_funding_cutoff(db: Any, state: Any) -> List[int]:
    """断供：停拨（ongoing 空/fiscal 裁撤）或欠额达阈（当月实拨 < 承诺×阈）。"""
    written: List[int] = []
    turn = int(getattr(state, "turn", 0) or 0)
    for row in db.issues.read_list_active_commitments():
        cid = int(row["id"])
        if has_pending_plea(db, cid, breach_kind=BREACH_KIND_FUNDING):
            continue
        origin_refs = _commitment_origin_refs(row, cid)
        promised = _promised_monthly_amount(row)
        has_monthly = promised > 0
        prior = _had_prior_funding(db, origin_refs, turn)
        fiscal_cut = _fiscal_funding_cut_this_turn(db, origin_refs, turn)

        cutoff = False
        reason = "承诺月供停拨"
        if fiscal_cut and prior:
            cutoff = True
            reason = "承诺月供财政裁撤/减额达阈"
        elif not has_monthly and prior:
            cutoff = True
            reason = "承诺月供停拨"
        elif has_monthly and prior:
            paid = _ledger_paid_this_turn(db, origin_refs, turn)
            if paid < promised * _FUNDING_ARREARS_RATIO:
                cutoff = True
                reason = f"承诺月供欠额达阈（实拨{paid}/应{promised}）"

        if not cutoff:
            continue
        origin = str(row["origin_ref"] or "")
        tid = write_breach_plea_todo(
            db, state,
            commitment_ref=cid,
            breach_kind=BREACH_KIND_FUNDING,
            reason=reason,
            target_dossier_id=int(parse_dossier_id(origin) or 0),
        )
        if tid:
            written.append(tid)
    return written


def _scan_misappropriation(db: Any, state: Any) -> List[int]:
    """挪用：专款账户本回合被非本承诺流向支用（economy + fiscal 流向）。"""
    written: List[int] = []
    turn = int(getattr(state, "turn", 0) or 0)
    for row in db.issues.read_list_active_commitments():
        cid = int(row["id"])
        accounts = _dedicated_accounts(row)
        if not accounts:
            continue
        if has_pending_plea(db, cid, breach_kind=BREACH_KIND_MISAPPROPRIATION):
            continue
        origin_refs = _commitment_origin_refs(row, cid)
        diverted = False
        hit_account = ""
        for account in accounts:
            rows = db.reign.read_scan_misappropriation((turn, account))
            for mv in rows:
                oref = str(mv["origin_ref"] or "").strip()
                if oref in origin_refs:
                    continue
                # 非本承诺 origin（含空 origin）= 挪用
                diverted = True
                hit_account = account
                break
            if diverted:
                break
            # fiscal：他源对本承诺所立科目的非授权改动已在断供侧；此处看他源从专款账户支用
        if not diverted:
            continue
        origin = str(row["origin_ref"] or "")
        tid = write_breach_plea_todo(
            db, state,
            commitment_ref=cid,
            breach_kind=BREACH_KIND_MISAPPROPRIATION,
            reason=f"专款「{hit_account}」被挪作他用",
            target_dossier_id=int(parse_dossier_id(origin) or 0),
        )
        if tid:
            written.append(tid)
    return written


def _sponsor_dismissed(db: Any, name: str) -> bool:
    """罢：status 离岗。"""
    row = db.characters.field_row('status', name)
    if row is None:
        return True
    status = str(row["status"] or "")
    return status in {
        "dismissed", "dead", "exiled", "imprisoned", "retired", "offstage",
    }


def _sponsor_transferred(db: Any, name: str, commitment_row: Any) -> bool:
    """调：status 仍 active，但职务已变（相对承诺/案卷记录的主办职）。"""
    char = db.characters.read_sponsor_transferred((name,))
    if char is None:
        return False
    if str(char["status"] or "") != "active":
        return False
    current_office = str(char["office"] or "").strip()
    # character_offices 备档
    co = db.characters.read_sponsor_transferred_office_title((name,))
    if co is not None:
        current_office = str(co["office_title"] or current_office).strip() or current_office

    # 承诺 roster 只读结构化 office 身份；role 是自由职分，腐坏名册响亮。
    expected = ""
    roster = decode_durable_participant_roster(commitment_row["participant_roster"])
    for item in roster:
        if item["character_id"] != name:
            continue
        if item.get("tier") != "主办":
            continue
        expected = str(
            item.get("office") or item.get("role") or item.get("office_title") or ""
        ).strip()
        break

    # 案卷 executor office 快照（结构化 office 字段，非自由 role）
    if not expected:
        did = parse_dossier_id(commitment_row["origin_ref"] or "")
        if did is not None:
            drow = db.dossiers.read_sponsor_transferred((int(did),))
            if drow is not None and str(drow["executor_id"] or "") == name:
                payload = parse_engine_payload_json(drow["payload_json"])
                if isinstance(payload, dict):
                    expected = str(
                        payload.get("executor_office")
                        or payload.get("office")
                        or ""
                    ).strip()

    # office_change_records：有调任记录且当前 office 与承诺侧 office 身份不等
    oc = db.characters.read_sponsor_transferred_office_title_by_character_name((name,))
    if oc is not None and expected:
        latest = str(oc["office_title"] or "").strip()
        if latest and expected and latest != expected and current_office != expected:
            return True
    # Exact office-identity inequality only — no length/substring free-text classify.
    if expected and current_office and expected != current_office:
        # role 常是职分非官职名，仅当 expected 像官职（含于 current 或相等）才判
        if expected == current_office:
            return False
        # 若 expected 是短 role（承办/清丈）而非 office，不误判
        if len(expected) <= 4 and expected not in current_office:
            # 无可靠 office 快照时：看 office_change_records 是否在承诺 origin 之后有调任
            if oc is not None:
                # 有任何调任记录且 status active → 调
                # 过宽；要求 dossier 绑承诺同源
                did = parse_dossier_id(commitment_row["origin_ref"] or "")
                if did is not None:
                    linked = db.characters.read_sponsor_transferred_1(
                        (name, int(did))
                    )
                    if linked is not None:
                        return True
            return False
        return True
    return False


def _scan_remove_sponsor(db: Any, state: Any) -> List[int]:
    """撤人：主办罢/调（status 离岗 或 职务变动而仍 active）。"""
    written: List[int] = []
    for row in db.issues.read_list_active_commitments():
        cid = int(row["id"])
        if has_pending_plea(db, cid, breach_kind=BREACH_KIND_REMOVE_SPONSOR):
            continue
        sponsors = _sponsor_names_for_commitment(db, row)
        if not sponsors:
            continue
        removed: List[str] = []
        transferred: List[str] = []
        for s in sponsors:
            if _sponsor_dismissed(db, s):
                removed.append(s)
            elif _sponsor_transferred(db, s, row):
                transferred.append(s)
        hit = removed + transferred
        if not hit:
            continue
        origin = str(row["origin_ref"] or "")
        who = "、".join(hit[:3])
        kind_word = "罢调" if removed and transferred else ("罢" if removed else "调")
        tid = write_breach_plea_todo(
            db, state,
            commitment_ref=cid,
            breach_kind=BREACH_KIND_REMOVE_SPONSOR,
            reason=f"主办{who}{kind_word}，人亡政息",
            target_dossier_id=int(parse_dossier_id(origin) or 0),
            extra={
                "removed_sponsors": removed,
                "transferred_sponsors": transferred,
            },
        )
        if tid:
            written.append(tid)
    return written


def scan_and_write_breach_pleas(
    db: Any, state: Any,
) -> List[int]:
    """结算内扫描断供/挪用/撤人。

    明确撤令不经此场强制挽留（#1894）；改弦若已有他类松手 pending，由 cancels
    坚持撤 finalize。相反新旨：无可行机械判据（需语义对立），不静默缺省——见模块说明。
    """
    written: List[int] = []
    written.extend(_scan_funding_cutoff(db, state))
    written.extend(_scan_misappropriation(db, state))
    written.extend(_scan_remove_sponsor(db, state))
    return written


def _extract_ref_ids(items: object, *, prefixes: Sequence[str]) -> Set[int]:
    """统一 walker：从 list[dict] 抽 issue/dossier 引用 id。

    认 key 集合 + target_id 前缀 + origin_ref/来源引用；禁纯数字 target_id 误吞为 dossier。
    信用写端（#628）与哭谏识别共此单源，禁平行复制。
    """
    out: Set[int] = set()
    if not isinstance(items, list):
        return out
    id_keys_by_prefix = {
        "issue": ("issue_id", "id", "commitment_ref"),
        "dossier": ("dossier_id", "revoke_target_dossier_id"),
    }
    keys: Set[str] = set()
    for p in prefixes:
        keys.update(id_keys_by_prefix.get(p, ()))
    for it in items:
        if not isinstance(it, dict):
            continue
        for key in keys:
            raw = it.get(key)
            if raw in (None, ""):
                continue
            # issue walker 的裸 id 可能与 dossier_id 键冲突时仅在对应 prefix 下启用
            if key in {"id"} and "issue" not in prefixes:
                continue
            out.add(int(raw))
        tid = str(it.get("target_id") or "").strip()
        for p in prefixes:
            if tid.startswith(f"{p}:"):
                out.add(int(tid.split(":", 1)[1]))
        for key in ("origin_ref", "来源引用"):
            ref = str(it.get(key) or "").strip()
            for p in prefixes:
                if p == "issue":
                    m = _ISSUE_REF_RE.match(ref)
                    if m:
                        out.add(int(m.group(1)))
                elif p == "dossier":
                    m = _DOSSIER_REF_RE.match(ref)
                    if m:
                        out.add(int(m.group(1)))
    return out
