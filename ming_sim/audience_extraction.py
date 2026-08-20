"""召对夜内叙事抽取落账（#501 / ADR 0035·0036）与夜级背书绑定（#612 / ADR 0070）。

普通 story/presence：大臣回话演完后**即时**抽取落账（同邸报→delta）。已持久化回话是
抽取重试真源：回话在、账未抽 → 补跑抽取，不回滚对话（ADR 0036）。

背书（会签/当面站台/御笔手敕）：**不**混入普通抽取。收夜在最终案卷 identity 与
surviving source turns 快照完成后，夜级**一次** endorsement-only 批量绑定；LLM 不持
DB transaction / runtime write gate；成功后短事务原子落背书，再允许判官/明发/效果/CLOSED。
失败保持 OPEN、保留 draft identity、无需重 consent，重试幂等。

崩溃一致性纪律：
- **单轮多条账原子落账**（`db.settle_story_extraction` 走 `atomic`）。
- **垃圾 shape / 抽取失败 → 响亮错误包 + 待补**（普通事实）；背书批失败 → fail-closed 收夜。
- **补跑失败不锁档**：`catch_up_pending_extractions` 从不抛；只补普通 story/presence。
- **收夜前清空普通待补**：`drain_pending_before_close`；仍有待补 → fail-closed。

本模块只提供纯函数 + 编排入口，不持时序状态机；写库须走真实 runtime write_gate。
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ming_sim.audience_night import (
    AUDIBILITY_PRIVATE,
    AUDIBILITY_PUBLIC,
    NIGHT_STATUS_CLOSING,
    PRESENCE_EFFECTS,
    AudienceNightError,
    get_night,
    get_open_night,
    night_endorsement_bound,
    persons_present_tonight,
    write_audience_error_pack,
)
from ming_sim.exceptions import LLMUnavailable
from ming_sim.llm_model import extract_agent_text

_AUDIBILITIES = frozenset({AUDIBILITY_PUBLIC, AUDIBILITY_PRIVATE})
_ENDORSEMENT_FORMS = frozenset({"会签", "当面站台", "御笔手敕"})


class ExtractionShapeError(AudienceNightError):
    """抽取输出垃圾 shape：响亮失败、可发包（不静默丢戏，AC3）。"""


def _coerce_facts_container(raw: Any) -> List[Any]:
    """把模型输出（JSON 文本 / dict / list）归一成 facts 列表；结构对不上即响亮拒收。"""
    data: Any = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            raise ExtractionShapeError(
                "抽取输出为空文本", code="extraction_bad_shape",
                detail={"raw": raw},
            )
        try:
            data = json.loads(text)
        except (TypeError, ValueError) as exc:
            raise ExtractionShapeError(
                f"抽取输出非合法 JSON：{exc}", code="extraction_bad_shape",
                detail={"raw": raw},
            ) from None
    if isinstance(data, Mapping):
        if "facts" not in data:
            raise ExtractionShapeError(
                "抽取输出缺 facts 字段", code="extraction_bad_shape",
                detail={"keys": sorted(str(k) for k in data.keys())},
            )
        data = data["facts"]
    if not isinstance(data, list):
        raise ExtractionShapeError(
            f"facts 须为数组，得到 {type(data).__name__}",
            code="extraction_bad_shape",
            detail={"type": type(data).__name__},
        )
    return data


def parse_extraction_facts(raw: Any) -> List[Dict[str, Any]]:
    """校验并规整普通故事事实列表；任一条对不上契约即响亮拒收（AC3）。

    合法事实：body 非空字符串；audibility ∈ {殿上公开,御前低语}（缺省公开）；
    presence_effect ∈ {'',enter,exit}；person_names/tags 为字符串数组。
    空 facts（无显著情节）合法——返回 []。
    不含 endorsement（背书走夜级 endorsement-only 批处理）。
    """
    container = _coerce_facts_container(raw)
    facts: List[Dict[str, Any]] = []
    for idx, item in enumerate(container):
        if not isinstance(item, Mapping):
            raise ExtractionShapeError(
                f"第 {idx} 条抽取事实非对象：{type(item).__name__}",
                code="extraction_bad_shape", detail={"index": idx},
            )
        if "endorsement" in item:
            raise ExtractionShapeError(
                f"第 {idx} 条普通事实不得含 endorsement（背书走夜级批处理）",
                code="extraction_bad_shape", detail={"index": idx},
            )
        body = item.get("body")
        if not isinstance(body, str) or not body.strip():
            raise ExtractionShapeError(
                f"第 {idx} 条抽取事实缺正文 body",
                code="extraction_bad_shape", detail={"index": idx},
            )
        audibility = item.get("audibility") or AUDIBILITY_PUBLIC
        if audibility not in _AUDIBILITIES:
            raise ExtractionShapeError(
                f"第 {idx} 条可闻性非法：{audibility!r}",
                code="extraction_bad_shape", detail={"index": idx},
            )
        presence_effect = item.get("presence_effect") or ""
        if presence_effect not in PRESENCE_EFFECTS:
            raise ExtractionShapeError(
                f"第 {idx} 条在场效果非法：{presence_effect!r}",
                code="extraction_bad_shape", detail={"index": idx},
            )
        person_names_raw = item.get("person_names") or []
        if not isinstance(person_names_raw, list) or not all(
            isinstance(n, str) for n in person_names_raw
        ):
            raise ExtractionShapeError(
                f"第 {idx} 条 person_names 须为字符串数组",
                code="extraction_bad_shape", detail={"index": idx},
            )
        tags_raw = item.get("tags") or []
        if not isinstance(tags_raw, list) or not all(
            isinstance(t, str) for t in tags_raw
        ):
            raise ExtractionShapeError(
                f"第 {idx} 条 tags 须为字符串数组",
                code="extraction_bad_shape", detail={"index": idx},
            )
        facts.append({
            "person_names": [n.strip() for n in person_names_raw if n.strip()],
            "audibility": str(audibility),
            "body": body.strip(),
            "tags": [t for t in tags_raw if t],
            "presence_effect": str(presence_effect),
        })
    return facts


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


def _user_message_for_turn(db: Any, chat_turn_id: int) -> str:
    """读本轮已链接的皇帝问话原文；无链接/无正文 → 空串。"""
    if not chat_turn_id or not hasattr(db, "conn"):
        return ""
    row = db.conn.execute(
        """
        SELECT m.content AS content
        FROM chat_turns t
        LEFT JOIN chat_messages m ON m.id = t.user_message_id
        WHERE t.id = ?
        """,
        (int(chat_turn_id),),
    ).fetchone()
    if row is None:
        return ""
    return str(row["content"] or "")


def extract_story_facts(
    reply: str,
    *,
    minister_name: str,
    present_names: Sequence[str],
    llm_config: Any,
    extractor_agent: Any = None,
    emperor_text: str = "",
) -> List[Dict[str, Any]]:
    """调抽取员把一轮君臣对话结构化成普通故事事实；问话与回话皆空返回 []。

    垃圾 shape → ExtractionShapeError（响亮）；模型不可用 → LLMUnavailable。
    皇帝问话与大臣回话同入一次抽取材料——不二次调用。不含可背书案卷/endorsement。
    """
    reply_text = str(reply or "").strip()
    question_text = str(emperor_text or "").strip()
    if not reply_text and not question_text:
        return []
    agent = extractor_agent
    if agent is None:
        if llm_config is None:
            raise LLMUnavailable("当前会话没有可用的模型配置")
        from ming_sim.agents import create_audience_extractor_agent

        agent = create_audience_extractor_agent(llm_config)
    materials = {
        "回话大臣": minister_name,
        "当前在场": list(present_names),
        "皇帝问话": question_text,
        "回话原文": reply_text,
    }
    output = extract_agent_text(
        agent.run(json.dumps(materials, ensure_ascii=False))
    )
    if not output or not str(output).strip():
        raise LLMUnavailable("抽取员返回空文本")
    return parse_extraction_facts(output)


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


# One process-local single-flight table shared by turn extraction and night
# endorsement batch. Keys distinguish domains: ("turn", db_id, turn_id) /
# ("night", db_id, night_id).
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


# #1353：收夜 OPEN 期有限 join 预算（与 wait_in_flight 同量级；不另起状态机）。
DEFAULT_EXTRACT_JOIN_S = 30.0


def _join_single_flight(key: tuple[Any, ...], timeout_s: float) -> bool:
    """有限 join 在飞 owner：不启动工作、不建 Future。

    True = 无 owner 或 owner 已在时限内结束（调用方须重读 DB 真源）。
    False = 超时仍在飞。超时路径不得 pop 仍持锁 owner 的槽。
    """
    with _single_flight_guard:
        slot = _single_flight_ownership.get(key)
        if slot is None:
            return True
        owner = slot[0]
        slot[1] += 1
    acquired = False
    try:
        acquired = bool(owner.acquire(timeout=max(0.0, float(timeout_s))))
        return acquired
    finally:
        if acquired:
            _release_single_flight(key, owner)
        else:
            with _single_flight_guard:
                slot = _single_flight_ownership.get(key)
                if slot is not None and slot[0] is owner:
                    slot[1] -= 1
                    # owner 仍在飞时 ref 至少为 1；仅当我们是最后旁观者且槽已空才 pop
                    if slot[1] <= 0:
                        _single_flight_ownership.pop(key, None)


def _turn_flight_key(db: Any, chat_turn_id: int) -> tuple[Any, ...]:
    return ("turn", id(db), int(chat_turn_id))


def _night_flight_key(db: Any, night_id: int) -> tuple[Any, ...]:
    return ("night", id(db), int(night_id))


def join_pending_turn_extractions(
    db: Any,
    *,
    night_id: int,
    timeout_s: float | None = None,
) -> None:
    """#1353 OPEN 期汇合普通抽取：对 list_unextracted 各轮 single-flight owner 有限 join。

    只作 join 信号；结果只读 `chat_turns.extract_status`（调用方/drain 重读）。
    不启动新抽取、不建 Future/第二欠账表。超时不抛——真欠账由后续 drain fail-closed。
    """
    if timeout_s is None:
        timeout_s = DEFAULT_EXTRACT_JOIN_S
    if not hasattr(db, "list_unextracted_replies"):
        return
    rows = db.list_unextracted_replies(night_id=int(night_id)) or []
    if not rows:
        return
    deadline = time.monotonic() + max(0.0, float(timeout_s))
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        cid = int(row.get("chat_turn_id") or 0)
        if cid <= 0:
            continue
        if hasattr(db, "get_story_extract_status") and db.get_story_extract_status(cid) == "done":
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        _join_single_flight(_turn_flight_key(db, cid), remaining)


def has_inflight_turn_extractions(db: Any, *, night_id: int) -> bool:
    """#1353：list_unextracted 中是否仍有活的 turn single-flight owner。

    供 close 在 write_gate 临界区内与 OPEN→CLOSING 冻结同锁复查；不阻塞、不建 Future。
    True = 至少一轮 owner 锁仍被持有（join 后新 admission 的窗口样本）。
    """
    if not hasattr(db, "list_unextracted_replies"):
        return False
    rows = db.list_unextracted_replies(night_id=int(night_id)) or []
    if not rows:
        return False
    with _single_flight_guard:
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            cid = int(row.get("chat_turn_id") or 0)
            if cid <= 0:
                continue
            if (
                hasattr(db, "get_story_extract_status")
                and db.get_story_extract_status(cid) == "done"
            ):
                continue
            slot = _single_flight_ownership.get(_turn_flight_key(db, cid))
            if slot is None:
                continue
            owner = slot[0]
            # 非阻塞探测：拿得到锁 ⇒ owner 已释放（非在飞）；立即还回。
            if owner.acquire(blocking=False):
                owner.release()
                continue
            return True
    return False


def _is_endorsement_bound(db: Any, night_id: int) -> bool:
    return night_endorsement_bound(get_night(db, int(night_id)))


def run_extraction_for_turn(
    *,
    db: Any,
    minister_name: str,
    reply: str,
    chat_turn_id: int,
    night_id: int,
    source_night_seq: int,
    llm_config: Any,
    write_gate: threading.Lock,
    present_names: Optional[Sequence[str]] = None,
    extractor_agent: Any = None,
    allow_closing: bool = False,
) -> Dict[str, Any]:
    """一轮普通叙事抽取落账尾随：幂等水位判 → 抽取 → 原子落账；失败 → 响亮错误包 + 待补。

    - 已 'done' → 幂等跳过（补跑不重复，AC6）。
    - 空白完整回话 ≡ 无显著情节 → 直接标 done（无需 LLM）。
    - 垃圾 shape / 模型失败 / **落账失败** → 写错误包 + `mark_story_extraction_pending`，
      **不回滚对话、绝不抛穿**；返回 status='pending'。
    - 成功 → `settle_story_extraction` 单事务全有或全无（AC7），返回 status='done'。
    - 不处理 endorsement（夜级批处理）。

    `write_gate` 必传：落账走真实 runtime 写锁。

    #1353：admission（CLOSING 拒新 + claim single-flight + done 水位）与 close 冻结同持
    write_gate，使 join→freeze 窗内新 owner 要么被 gate 内 inflight 复查看见，要么在
    冻结后直接拒入（不跑 LLM、不假 settle 失败）；LLM 仍在 gate 外。
    """
    cid = int(chat_turn_id)
    if not cid:
        return {"status": "skipped", "chat_turn_id": cid}

    flight_key = _turn_flight_key(db, cid)
    owner: Optional[threading.Lock] = None
    try:
        # Admission under the same runtime write_gate close uses to freeze CLOSING.
        with write_gate:
            night = get_night(db, int(night_id)) if int(night_id or 0) > 0 else None
            if (
                night is not None
                and str(night.get("status") or "") == NIGHT_STATUS_CLOSING
                and not allow_closing
            ):
                # 冻结后再拒新 owner；不 claim、不 LLM。真欠账由 close drain（allow_closing）清。
                return {
                    "status": "pending",
                    "chat_turn_id": cid,
                    "rejected_closing": True,
                }
            owner, owned = _claim_single_flight(flight_key)
            if owner is None:
                return {"status": "pending", "chat_turn_id": cid, "contended": True}
            if not owned:
                status = db.get_story_extract_status(cid)
                return {
                    "status": "done" if status == "done" else "pending",
                    "chat_turn_id": cid,
                    "already": status == "done",
                }
            if db.get_story_extract_status(cid) == "done":
                return {"status": "done", "chat_turn_id": cid, "already": True}

        question_text = _user_message_for_turn(db, cid)

        if not str(reply or "").strip() and not question_text.strip():
            return _settle_or_pending(
                db, write_gate, cid=cid, night_id=night_id, minister_name=minister_name,
                facts=[], source_night_seq=source_night_seq, fact_count=0,
                allow_closing=allow_closing,
            )

        if present_names is None:
            try:
                present_names = sorted(persons_present_tonight(db, int(night_id)))
            except Exception:
                present_names = []

        try:
            facts = extract_story_facts(
                reply,
                minister_name=minister_name,
                present_names=present_names or [],
                llm_config=llm_config,
                extractor_agent=extractor_agent,
                emperor_text=question_text,
            )
        except Exception as exc:
            return _pending_with_pack(
                db, write_gate, cid=cid, night_id=night_id,
                minister_name=minister_name, exc=exc, stage="extract",
            )

        return _settle_or_pending(
            db, write_gate, cid=cid, night_id=night_id, minister_name=minister_name,
            facts=facts, source_night_seq=source_night_seq,
            fact_count=len(facts),
            allow_closing=allow_closing,
        )
    finally:
        if owner is not None:
            _release_single_flight(flight_key, owner)


def run_endorsement_batch_for_night(
    *,
    db: Any,
    night_id: int,
    llm_config: Any,
    write_gate: Any,
    extractor_agent: Any = None,
) -> Dict[str, Any]:
    """收夜 endorsement-only 批：LLM 在 write_gate 外；短事务原子落背书。

    - 已 bound → 幂等跳过。
    - 无候选或无 surviving turns → 确定性 skip 并标 bound。
    - 争用 → 有限返回（不阻塞、不建 Future）。
    - LLM/shape 失败 → 抛 AudienceNightError（调用方 fail-closed 保持 OPEN）。
    """
    nid = int(night_id)
    if _is_endorsement_bound(db, nid):
        return {"status": "done", "night_id": nid, "already": True, "ids": []}

    flight_key = _night_flight_key(db, nid)
    owner, owned = _claim_single_flight(flight_key)
    if owner is None:
        raise AudienceNightError(
            f"收夜背书批处理争用中（night_id={nid}），请稍后重试。",
            code="endorsement_batch_contended",
            detail={"night_id": nid},
        )
    try:
        if not owned:
            if _is_endorsement_bound(db, nid):
                return {"status": "done", "night_id": nid, "already": True, "ids": []}
            raise AudienceNightError(
                f"收夜背书批处理争用中（night_id={nid}），请稍后重试。",
                code="endorsement_batch_contended",
                detail={"night_id": nid},
            )
        if _is_endorsement_bound(db, nid):
            return {"status": "done", "night_id": nid, "already": True, "ids": []}

        inputs = db.list_endorsement_batch_inputs(nid)
        candidates = list(inputs.get("candidates") or [])
        source_turns = list(inputs.get("turns") or [])

        if not candidates or not source_turns:
            # Same short path as settle: advance CLOSE_STEP_ENDORSEMENT_BOUND.
            with write_gate:
                if not _is_endorsement_bound(db, nid):
                    db.settle_endorsement_batch(nid, [])
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
                if _is_endorsement_bound(db, nid):
                    return {"status": "done", "night_id": nid, "already": True, "ids": []}
                ids = db.settle_endorsement_batch(nid, items)
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
        _release_single_flight(flight_key, owner)


def _pending_with_pack(
    db: Any, write_gate: threading.Lock, *,
    cid: int, night_id: int, minister_name: str, exc: BaseException, stage: str,
) -> Dict[str, Any]:
    """抽取/落账失败的统一响亮降级：写错误包 + 标待补 + 返回 pending（绝不抛，ADR 0005/0036）。"""
    code = getattr(exc, "code", f"{stage}_failed")
    verb = "落账" if stage == "settle" else "抽取"
    pack = write_audience_error_pack(
        kind="extraction_failed",
        message=f"叙事{verb}失败（{code}）：{exc}",
        detail={
            "chat_turn_id": cid,
            "night_id": int(night_id),
            "minister_name": minister_name,
            "code": code,
            "stage": stage,
        },
    )
    with write_gate:
        db.mark_story_extraction_pending(cid)
    return {
        "status": "pending",
        "chat_turn_id": cid,
        "error_pack_path": pack,
        "code": code,
    }


def _settle_or_pending(
    db: Any, write_gate: threading.Lock, *,
    cid: int, night_id: int, minister_name: str,
    facts: Sequence[Mapping[str, Any]], source_night_seq: int, fact_count: int,
    allow_closing: bool = False,
) -> Dict[str, Any]:
    """持锁落账 + 二次幂等复查；落账失败与抽取失败同语义（pack+pending，不抛穿 catch_up）。"""
    try:
        with write_gate:
            if db.get_story_extract_status(cid) == "done":
                return {"status": "done", "chat_turn_id": cid, "already": True}
            entry_ids = db.settle_story_extraction(
                cid, int(night_id), facts, int(source_night_seq),
                allow_closing=bool(allow_closing),
            )
    except Exception as exc:
        return _pending_with_pack(
            db, write_gate, cid=cid, night_id=night_id,
            minister_name=minister_name, exc=exc, stage="settle",
        )
    return {
        "status": "done",
        "chat_turn_id": cid,
        "entry_ids": entry_ids,
        "fact_count": fact_count,
    }


def trail_extraction_after_reply(
    *,
    db: Any,
    minister_name: str,
    minister_reply: str,
    chat_turn_id: int,
    llm_config: Any,
    write_gate: threading.Lock,
    extractor_agent: Any = None,
) -> Optional[Dict[str, Any]]:
    """#501：回话 done 后尾随普通叙事抽取落账——Web / CLI 共用单一入口。

    非召对夜轮（night_id<=0）不入故事账。`run_extraction_for_turn` 契约上**从不抛**；
    本函数亦**从不抛**。普通 story/presence **即时**抽取，不因 approved pending 延迟。
    """
    try:
        reply = str(minister_reply or "")
        if not chat_turn_id or not hasattr(db, "conn"):
            return None
        row = db.conn.execute(
            "SELECT night_id, night_seq FROM chat_turns WHERE id = ?",
            (int(chat_turn_id),),
        ).fetchone()
        if row is None:
            return None
        night_id = int(row["night_id"] or 0)
        if night_id <= 0:
            return None
        return run_extraction_for_turn(
            db=db,
            minister_name=minister_name,
            reply=reply,
            chat_turn_id=int(chat_turn_id),
            night_id=night_id,
            source_night_seq=int(row["night_seq"] or 0),
            llm_config=llm_config,
            write_gate=write_gate,
            extractor_agent=extractor_agent,
        )
    except Exception:
        try:
            with write_gate:
                if hasattr(db, "mark_story_extraction_pending"):
                    db.mark_story_extraction_pending(int(chat_turn_id))
        except Exception:
            pass
        return None


def catch_up_pending_extractions(
    *,
    db: Any,
    llm_config: Any,
    write_gate: threading.Lock,
    night_id: Optional[int] = None,
    extractor_agent: Any = None,
    allow_closing: bool = False,
    on_event=None,
) -> Dict[str, Any]:
    """补跑普通抽取：对已持久化但账未抽（''/'pending'）的回话逐轮尽力补跑（ADR 0036）。

    **从不抛**——补跑失败不锁档（AC8）。只补 story/presence，不触发夜级 endorsement batch。
    allow_closing 仅 close_night ordinary drain 显式开启。
    #1312：可选 on_event(kind, data) 推既有 stage 形分段进度（与 settle on_event 同款）。
    """
    rows = db.list_unextracted_replies(night_id=night_id)
    extracted = 0
    pending = 0
    total = len(rows)

    def _emit(kind: str, data: str) -> None:
        if on_event is None:
            return
        try:
            on_event(kind, data)
        except Exception:  # noqa: BLE001 — 进度回调失败不得阻断补跑
            pass

    # Source turns are semantically ordered: later turns consume already-settled
    # presence/ledger. Cross-turn catch-up therefore stays serial.
    for index, row in enumerate(rows, start=1):
        minister = str(row.get("minister_name") or "") or "臣工"
        _emit("stage", f"补写召对账本（{index}/{total}）·{minister}")
        result = run_extraction_for_turn(
            db=db,
            minister_name=str(row.get("minister_name") or ""),
            reply=str(row.get("reply") or ""),
            chat_turn_id=int(row.get("chat_turn_id") or 0),
            night_id=int(row.get("night_id") or 0),
            source_night_seq=int(row.get("night_seq") or 0),
            llm_config=llm_config,
            write_gate=write_gate,
            extractor_agent=extractor_agent,
            allow_closing=bool(allow_closing),
        )
        status = result.get("status")
        if status == "done":
            extracted += 1
        elif status == "pending":
            pending += 1
    return {
        "extracted": extracted,
        "pending": pending,
        "scanned": len(rows),
    }


def drain_pending_before_close(
    *,
    db: Any,
    llm_config: Any,
    write_gate: threading.Lock,
    night_id: int,
    extractor_agent: Any = None,
) -> None:
    """收夜是史实书写边界（ADR 0036）：收夜前强制同步补跑普通待补一次。

    仍有待补 → **fail-closed 中止收夜**。不含 endorsement batch。
    close-owned：显式 allow_closing，使 CLOSING 下 ordinary residue 可落账。
    """
    catch_up_pending_extractions(
        db=db,
        llm_config=llm_config,
        write_gate=write_gate,
        night_id=int(night_id),
        extractor_agent=extractor_agent,
        allow_closing=True,
    )
    remaining = db.count_pending_story_extractions(night_id=int(night_id))
    if remaining > 0:
        rows = db.list_unextracted_replies(night_id=int(night_id))
        ids = [int(r.get("chat_turn_id") or 0) for r in rows]
        message = (
            "收夜中止：本夜仍有未抽取落账的回话（待补），"
            f"chat_turn_ids={ids}。夜保持开启，可原地重试补跑。"
        )
        pack = write_audience_error_pack(
            kind="pending_extraction",
            message=message,
            detail={"night_id": int(night_id), "chat_turn_ids": ids},
        )
        raise AudienceNightError(
            message,
            code="pending_extraction",
            error_pack_path=pack,
            detail={"night_id": int(night_id), "chat_turn_ids": ids},
        )


def drain_pending_before_open_night_close(
    *,
    db: Any,
    llm_config: Any,
    write_gate: threading.Lock,
    extractor_agent: Any = None,
) -> None:
    """便捷入口：对当前开夜执行收夜前清空普通待补（无开夜则 no-op）。"""
    night = get_open_night(db)
    if night is None:
        return
    drain_pending_before_close(
        db=db,
        llm_config=llm_config,
        write_gate=write_gate,
        night_id=int(night["id"]),
        extractor_agent=extractor_agent,
    )
