"""召对夜级背书绑定（#612 / ADR 0070）。

会签/当面站台/御笔手敕在收夜的最终案卷 identity 与
surviving source turns 快照完成后，夜级**一次** endorsement-only 批量绑定；LLM 不持
DB transaction / runtime write gate；成功后短事务原子落背书，再允许判官/明发/效果/CLOSED。
失败保持 OPEN、保留 draft identity、无需重 consent，重试幂等。

背书批失败时 fail-closed 收夜。
"""

from __future__ import annotations

import json
import threading
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ming_sim.audience_night import (
    NIGHT_STATUS_CLOSING,
    AudienceNightError,
    get_night,
    night_endorsement_bound,
    persons_present_tonight,
    write_audience_error_pack,
)
from ming_sim.exceptions import LLMUnavailable
from ming_sim.llm_model import extract_agent_text

_ENDORSEMENT_FORMS = frozenset({"会签", "当面站台", "御笔手敕"})


class ExtractionShapeError(AudienceNightError):
    """抽取输出垃圾 shape：响亮失败、可发包（不静默丢戏，AC3）。"""


def _parse_dossier_id(raw: Mapping[str, Any], *, idx: int) -> int:
    dossier_id = raw.get("dossier_id")
    dossier_ref = raw.get("dossier_ref")
    direct = (
        not isinstance(dossier_id, bool)
        and isinstance(dossier_id, int)
        and dossier_id > 0
        and dossier_ref is None
    )
    ref_direct = (
        dossier_id is None
        and isinstance(dossier_ref, Mapping)
        and set(dossier_ref) == {"dossier_id"}
        and not isinstance(dossier_ref.get("dossier_id"), bool)
        and isinstance(dossier_ref.get("dossier_id"), int)
        and dossier_ref["dossier_id"] > 0
    )
    if not (direct or ref_direct):
        raise ExtractionShapeError(
            f"第 {idx} 条 endorsement 案卷引用非法",
            code="endorsement_bad_shape", detail={"index": idx},
        )
    return int(dossier_id if direct else dossier_ref["dossier_id"])


def parse_endorsement_batch(raw: Any) -> List[Dict[str, Any]]:
    """校验夜级 endorsement-only 批 envelope；单项畸形不整批失败。

    Envelope 不可用（空/非 JSON/非对象/含 facts/缺 endorsements/非数组）→
    ExtractionShapeError 整批失败。单项字段畸形原样保留，由 settle 既有 rejection
    channel 拒收，合法 sibling 仍可落。能解析时把输入 ref.dossier_id 展平为
    dossier_id（输出不保留 dossier_ref）。
    """
    data: Any = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise ExtractionShapeError(
                "背书批输出为空文本", code="endorsement_bad_shape",
                detail={"raw": raw},
            )
        try:
            data = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise ExtractionShapeError(
                f"背书批输出非合法 JSON：{exc}", code="endorsement_bad_shape",
                detail={"raw": raw},
            ) from None
    if not isinstance(data, Mapping):
        raise ExtractionShapeError(
            f"背书批输出须为对象，得到 {type(data).__name__}",
            code="endorsement_bad_shape",
            detail={"type": type(data).__name__},
        )
    if "facts" in data:
        raise ExtractionShapeError(
            "背书批不得输出 facts（story/presence 属普通抽取）",
            code="endorsement_bad_shape",
            detail={"keys": sorted(str(k) for k in data.keys())},
        )
    if "endorsements" not in data:
        raise ExtractionShapeError(
            "背书批输出缺 endorsements 字段",
            code="endorsement_bad_shape",
            detail={"keys": sorted(str(k) for k in data.keys())},
        )
    container = data["endorsements"]
    if not isinstance(container, list):
        raise ExtractionShapeError(
            f"endorsements 须为数组，得到 {type(container).__name__}",
            code="endorsement_bad_shape",
            detail={"type": type(container).__name__},
        )
    items: List[Dict[str, Any]] = []
    for idx, item in enumerate(container):
        if not isinstance(item, Mapping):
            # settle 既有 rejection channel 认非对象项。
            items.append({"raw": repr(item)})
            continue
        out = dict(item)
        try:
            out["dossier_id"] = _parse_dossier_id(item, idx=idx)
            out.pop("dossier_ref", None)
        except ExtractionShapeError:
            # 单项案卷引用非法 → 留给 settle 拒收，不拖垮 sibling。
            pass
        items.append(out)
    return items






def extract_endorsements_for_night(
    *,
    dossier_candidates: Sequence[Mapping[str, Any]],
    source_turns: Sequence[Mapping[str, Any]],
    llm_config: Any,
    extractor_agent: Any = None,
) -> List[Dict[str, Any]]:
    """夜级 endorsement-only 批抽取；无候选或无 surviving 材料 → []（不调 LLM）。"""
    if not dossier_candidates or not source_turns:
        return []
    agent = extractor_agent
    if agent is None:
        if llm_config is None:
            raise LLMUnavailable("当前会话没有可用的模型配置")
        from ming_sim.agents import create_endorsement_extractor_agent

        agent = create_endorsement_extractor_agent(llm_config)
    materials = {
        "可背书案卷": [
            {
                "ref": dict(row["ref"]),
                "decree_text": str(row.get("decree_text") or ""),
            }
            for row in dossier_candidates
        ],
        "surviving_source_turns": [
            {
                "source_chat_turn_id": int(row["source_chat_turn_id"]),
                "minister_name": str(row.get("minister_name") or ""),
                "皇帝问话": str(row.get("emperor_text") or ""),
                "回话原文": str(row.get("minister_reply") or ""),
                "已落普通账": list(row.get("ordinary_facts") or []),
            }
            for row in source_turns
        ],
    }
    output = extract_agent_text(
        agent.run(json.dumps(materials, ensure_ascii=False))
    )
    if not output or not str(output).strip():
        raise LLMUnavailable("背书抽取员返回空文本")
    return parse_endorsement_batch(output)


# One process-local single-flight table for the night endorsement batch.
_single_flight_guard = threading.Lock()
_single_flight_ownership: Dict[tuple[Any, ...], list[Any]] = {}


def _claim_single_flight(key: tuple[Any, ...]) -> tuple[Optional[threading.Lock], bool]:
    """Process-local finite single-flight.

    Only the caller that creates the slot owns a new attempt. Contending callers
    must not block on the in-flight owner; they return immediately so the path
    stays finite and retryable. No Future/result store. The slot is reclaimed
    when the last holder leaves.

    New owner lock is acquired **inside** `_single_flight_guard` before the slot
    is published, so no contender can observe an unlocked freshly-created owner.

    Returns (lock, owned). owned=True means this caller runs the work. lock is
    None on contention (caller must not release).
    """
    with _single_flight_guard:
        slot = _single_flight_ownership.get(key)
        if slot is None:
            owner = threading.Lock()
            owner.acquire()
            _single_flight_ownership[key] = [owner, 1]
            return owner, True
        slot[1] += 1
        owner = slot[0]
        if owner.acquire(blocking=False):
            # Previous owner released; caller rechecks terminal status, does not
            # start a parallel attempt (owned=False).
            return owner, False
        slot[1] -= 1
        if slot[1] <= 0:
            _single_flight_ownership.pop(key, None)
        return None, False


def _release_single_flight(key: tuple[Any, ...], owner: threading.Lock) -> None:
    owner.release()
    with _single_flight_guard:
        slot = _single_flight_ownership.get(key)
        if slot is None or slot[0] is not owner:
            return
        slot[1] -= 1
        if slot[1] <= 0:
            _single_flight_ownership.pop(key, None)




def _night_flight_key(db: Any, night_id: int) -> tuple[Any, ...]:
    return ("night", id(db), int(night_id))


def _is_endorsement_bound(db: Any, night_id: int) -> bool:
    return night_endorsement_bound(get_night(db, int(night_id)))




def run_endorsement_batch_for_night(
    *,
    db: Any,
    night_id: int,
    llm_config: Any,
    write_gate: Any,
    extractor_agent: Any = None,
    join_timeout_s: float | None = None,
    late_action_ids: Optional[Sequence[int]] = None,
) -> Dict[str, Any]:
    """收夜或迟到补批共用 endorsement-only 入口：LLM 在锁外，落库在短事务。

    - 正常批以收夜游标、迟到批以待补项标记判定完成，重试幂等。
    - 无候选或无 surviving turns → 确定性 skip 并标完成。
    - LLM 去重走既有 per-night single-flight（防双跑）；写序由 session 队列屏障覆盖
      （#1353：删除争用 join 舞步）。争用/前 owner 已释放 → 只重读 bound 终态。
    - LLM/shape 失败 → 抛 AudienceNightError（调用方 fail-closed 保持 OPEN；K10b）。
    """
    del join_timeout_s  # 签名兼容；队列屏障后不再 join 争用
    nid = int(night_id)
    late_ids = sorted({int(i) for i in late_action_ids or ()})
    if late_action_ids is not None and not late_ids:
        return {"status": "done", "night_id": nid, "already": True, "ids": []}

    def bound() -> bool:
        if late_action_ids is None:
            return _is_endorsement_bound(db, nid)
        return not db.conn.execute(
            f"SELECT 1 FROM pending_actions WHERE night_id=? AND status='committed' "
            f"AND late_endorsement_pending=1 AND id IN ({','.join('?' for _ in late_ids)})",
            (nid, *late_ids),
        ).fetchone()

    if bound():
        return {"status": "done", "night_id": nid, "already": True, "ids": []}

    flight_key = _night_flight_key(db, nid)
    owner: Optional[threading.Lock] = None
    try:
        # single-flight 只防双跑 LLM；写序归 session 队列。争用/已释放 → 重读终态。
        owner, owned = _claim_single_flight(flight_key)
        if owner is None or not owned:
            if bound():
                return {"status": "done", "night_id": nid, "already": True, "ids": []}
            raise AudienceNightError(
                f"收夜背书批未落定（night_id={nid}）",
                code="endorsement_not_bound",
                detail={"night_id": nid},
            )

        if bound():
            return {"status": "done", "night_id": nid, "already": True, "ids": []}

        inputs = db.list_endorsement_batch_inputs(
            nid, action_ids=late_ids if late_action_ids is not None else None,
        )
        candidates = list(inputs.get("candidates") or [])
        source_turns = list(inputs.get("turns") or [])

        if not candidates or not source_turns:
            # 与有候选分支共用落定点：正常推进游标，迟到清待补标记并补明发。
            with write_gate:
                if not bound():
                    if late_action_ids is None:
                        db.settle_endorsement_batch(nid, [])
                    else:
                        db.settle_endorsement_batch(nid, [], late_action_ids=late_ids)
            return {
                "status": "skipped",
                "night_id": nid,
                "ids": [],
                "reason": "no_candidates_or_turns",
            }

        # LLM: must run with no DB transaction and no runtime write gate held.
        try:
            items = extract_endorsements_for_night(
                dossier_candidates=candidates,
                source_turns=source_turns,
                llm_config=llm_config,
                extractor_agent=extractor_agent,
            )
        except Exception as exc:
            code = getattr(exc, "code", "endorsement_extract_failed")
            message = f"收夜背书批抽取失败（{code}）：{exc}"
            pack = write_audience_error_pack(
                kind="endorsement_extract_failed",
                message=message,
                detail={"night_id": nid, "code": code},
            )
            raise AudienceNightError(
                message,
                code="endorsement_extract_failed",
                error_pack_path=pack,
                detail={"night_id": nid, "code": code},
            ) from exc

        try:
            with write_gate:
                # Re-check after LLM: another path may have bound via cursor.
                if bound():
                    return {"status": "done", "night_id": nid, "already": True, "ids": []}
                if late_action_ids is None:
                    ids = db.settle_endorsement_batch(nid, items)
                else:
                    ids = db.settle_endorsement_batch(
                        nid, items, late_action_ids=late_ids,
                    )
        except Exception as exc:
            code = getattr(exc, "code", "endorsement_settle_failed")
            message = f"收夜背书批落库失败（{code}）：{exc}"
            pack = write_audience_error_pack(
                kind="endorsement_settle_failed",
                message=message,
                detail={"night_id": nid, "code": code},
            )
            raise AudienceNightError(
                message,
                code="endorsement_settle_failed",
                error_pack_path=pack,
                detail={"night_id": nid, "code": code},
            ) from exc

        return {
            "status": "done",
            "night_id": nid,
            "ids": ids,
            "count": len(ids),
        }
    finally:
        if owner is not None:
            _release_single_flight(flight_key, owner)
