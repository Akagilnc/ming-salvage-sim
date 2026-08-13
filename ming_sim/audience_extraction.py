"""召对夜内叙事抽取落账（#501 / ADR 0035·0036）。

大臣回话**演完后**抽取显著故事事实落账（站台作保/自行退至殿侧等开放标签；递话/读心类
御前内容标私）——同邸报→delta 模式。已持久化的回话是抽取重试真源：回话在、账未抽 →
补跑抽取，不回滚对话；两个 store 永不分叉（ADR 0036）。

崩溃一致性纪律：
- **单轮多条账原子落账**（`db.settle_story_extraction` 走 `atomic`）——写一半崩溃 → 补跑
  不重复（水位二元：已抽/未抽）。
- **垃圾 shape / 抽取失败 → 响亮错误包 + 待补**（不静默丢戏），永不进启动致命路径。
- **补跑失败不锁档**：`catch_up_pending_extractions` 从不抛，逐轮尽力补、失败标待补。
- **收夜前清空待补**：`drain_pending_before_close` 强制同步补跑一次，仍有待补 → fail-closed。

本模块只提供纯函数 + 编排入口，不持时序状态机；写库须走真实 runtime write_gate。
"""

from __future__ import annotations

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Mapping, Optional, Sequence

from ming_sim.audience_night import (
    AUDIBILITY_PRIVATE,
    AUDIBILITY_PUBLIC,
    PRESENCE_EFFECTS,
    AudienceNightError,
    get_open_night,
    persons_present_tonight,
    write_audience_error_pack,
)
from ming_sim.exceptions import LLMUnavailable
from ming_sim.llm_model import extract_agent_text

_AUDIBILITIES = frozenset({AUDIBILITY_PUBLIC, AUDIBILITY_PRIVATE})


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
    """校验并规整抽取事实列表；任一条对不上契约即响亮拒收（AC3）。

    合法事实：body 非空字符串；audibility ∈ {殿上公开,御前低语}（缺省公开）；
    presence_effect ∈ {'',enter,exit}；person_names/tags 为字符串数组。
    空 facts（无显著情节）合法——返回 []。
    """
    container = _coerce_facts_container(raw)
    facts: List[Dict[str, Any]] = []
    for idx, item in enumerate(container):
        if not isinstance(item, Mapping):
            raise ExtractionShapeError(
                f"第 {idx} 条抽取事实非对象：{type(item).__name__}",
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
        endorsement_raw = item.get("endorsement")
        endorsement = None
        if endorsement_raw is not None:
            if not isinstance(endorsement_raw, Mapping):
                raise ExtractionShapeError(
                    f"第 {idx} 条 endorsement 须为对象",
                    code="extraction_bad_shape", detail={"index": idx},
                )
            dossier_id = endorsement_raw.get("dossier_id")
            dossier_ref = endorsement_raw.get("dossier_ref")
            direct = (not isinstance(dossier_id, bool) and isinstance(dossier_id, int)
                      and dossier_id > 0 and dossier_ref is None)
            ref_direct = (
                dossier_id is None and isinstance(dossier_ref, Mapping)
                and set(dossier_ref) == {"dossier_id"}
                and not isinstance(dossier_ref.get("dossier_id"), bool)
                and isinstance(dossier_ref.get("dossier_id"), int)
                and dossier_ref["dossier_id"] > 0
            )
            form = endorsement_raw.get("form")
            imperial = endorsement_raw.get("imperial", False)
            endorser_id = endorsement_raw.get("endorser_id", "")
            if (not (direct or ref_direct) or form not in {"会签", "当面站台", "御笔手敕"}
                    or not isinstance(imperial, bool) or not isinstance(endorser_id, str)):
                raise ExtractionShapeError(
                    f"第 {idx} 条 endorsement 字段非法",
                    code="extraction_bad_shape", detail={"index": idx},
                )
            endorsement = {
                "dossier_id": dossier_id if direct else dossier_ref["dossier_id"],
                "form": form, "endorser_id": endorser_id.strip(), "imperial": imperial,
            }
        facts.append({
            "person_names": [n.strip() for n in person_names_raw if n.strip()],
            "audibility": str(audibility),
            "body": body.strip(),
            "tags": [t for t in tags_raw if t],
            "presence_effect": str(presence_effect),
            **({"endorsement": endorsement} if endorsement is not None else {}),
        })
    return facts


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
    dossier_candidates: Optional[Sequence[Mapping[str, Any]]] = None,
    emperor_text: str = "",
) -> List[Dict[str, Any]]:
    """调抽取员把一轮君臣对话结构化成故事事实；问话与回话皆空返回 []。

    垃圾 shape → ExtractionShapeError（响亮）；模型不可用 → LLMUnavailable。
    皇帝问话与大臣回话同入一次抽取材料——不二次调用、不按皇威抑制已说出口的事实。
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
        "可背书案卷": [
            {"ref": dict(row["ref"]), "decree_text": str(row.get("decree_text") or "")}
            for row in (dossier_candidates or [])
        ],
    }
    output = extract_agent_text(
        agent.run(json.dumps(materials, ensure_ascii=False))
    )
    if not output or not str(output).strip():
        raise LLMUnavailable("抽取员返回空文本")
    # A malformed LLM item is a per-item rejection, not a reason to discard valid
    # siblings.  Keep the rejected raw item for the DB transaction's established
    # applied/rejected channel; unsplittable top-level output still fails loudly.
    container = _coerce_facts_container(output)
    facts: List[Dict[str, Any]] = []
    for idx, item in enumerate(container):
        try:
            facts.extend(parse_extraction_facts({"facts": [item]}))
        except ExtractionShapeError as exc:
            # Only an otherwise valid fact with a malformed endorsement is dirty
            # per-item data. Other #501 shape failures remain loud and retryable.
            if not isinstance(item, Mapping) or "endorsement" not in item:
                raise
            parse_extraction_facts({"facts": [{k: v for k, v in item.items() if k != "endorsement"}]})
            facts.append({
                "_rejected_story_fact": dict(item),
                "_rejection_reason": f"第 {idx} 条：{exc}",
            })
    return facts


_turn_ownership_guard = threading.Lock()
_turn_ownership: Dict[tuple[int, int], threading.Lock] = {}


def _extraction_owner(db: Any, chat_turn_id: int) -> threading.Lock:
    """Process-local single-flight ownership for one persisted audience turn.

    The durable done watermark prevents repeat settlement, while this lock also prevents
    two racing owners (reply trailer and close-night drain) from both invoking the LLM
    before either has reached that watermark.
    """
    key = (id(db), int(chat_turn_id))
    with _turn_ownership_guard:
        return _turn_ownership.setdefault(key, threading.Lock())


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
    _settle_barrier: Any = None,
) -> Dict[str, Any]:
    """一轮叙事抽取落账尾随：幂等水位判 → 抽取 → 原子落账；失败 → 响亮错误包 + 待补。

    - 已 'done' → 幂等跳过（补跑不重复，AC6）。
    - 空白完整回话 ≡ 无显著情节 → 直接标 done（无需 LLM），不占永久待补阻塞 drain（AC10）。
    - 垃圾 shape / 模型失败 / **落账失败** → 写错误包 + `mark_story_extraction_pending`，
      **不回滚对话、绝不抛穿**（settle 与 extract 同失败语义，保「补跑从不抛」，AC3/AC8）；
      返回 status='pending' 携错误包路径供玩家原地重试。
    - 成功 → `settle_story_extraction` 单事务全有或全无（AC7），返回 status='done'。

    `write_gate` 必传：落账走真实 runtime 写锁（与月末并发 extractor / 其它端点写同一把）。
    """
    cid = int(chat_turn_id)
    if not cid:
        if _settle_barrier is not None:
            _settle_barrier()
        return {"status": "skipped", "chat_turn_id": cid}

    # The trailer and close-night drain can race across the approved-directive handoff.
    # Own the whole status→LLM→settle turn, not merely its final DB write, so exactly one
    # real extraction occurs. The waiter observes the durable done watermark afterward.
    with _extraction_owner(db, cid):
        if db.get_story_extract_status(cid) == "done":
            if _settle_barrier is not None:
                _settle_barrier()
            return {"status": "done", "chat_turn_id": cid, "already": True}

        # 皇帝问话从本轮已链接的 user_message 读取（生产路径落库真源）；与回话同入一次抽取。
        question_text = _user_message_for_turn(db, cid)

        # 问话与回话皆空：无 LLM 亦可确定性收敛为 done（空 facts）——禁止 skipped 永久占水位（L4）。
        if not str(reply or "").strip() and not question_text.strip():
            if _settle_barrier is not None:
                _settle_barrier()
            return _settle_or_pending(
                db, write_gate, cid=cid, night_id=night_id, minister_name=minister_name,
                facts=[], source_night_seq=source_night_seq, fact_count=0,
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
                dossier_candidates=db.list_endorsement_candidates(int(night_id)),
                emperor_text=question_text,
            )
        except Exception as exc:
            if _settle_barrier is not None:
                _settle_barrier()
            return _pending_with_pack(
                db, write_gate, cid=cid, night_id=night_id,
                minister_name=minister_name, exc=exc, stage="extract",
            )

        if _settle_barrier is not None:
            _settle_barrier()
        return _settle_or_pending(
            db, write_gate, cid=cid, night_id=night_id, minister_name=minister_name,
            facts=facts, source_night_seq=source_night_seq,
            fact_count=sum(1 for fact in facts if "_rejected_story_fact" not in fact),
        )


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
) -> Dict[str, Any]:
    """持锁落账 + 二次幂等复查；落账失败与抽取失败同语义（pack+pending，不抛穿 catch_up）。"""
    try:
        with write_gate:
            # 二次幂等复查（持锁后）：另一并发补跑可能已落账。
            if db.get_story_extract_status(cid) == "done":
                return {"status": "done", "chat_turn_id": cid, "already": True}
            entry_ids = db.settle_story_extraction(
                cid, int(night_id), facts, int(source_night_seq),
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
    """#501：回话 done 后尾随叙事抽取落账——Web / CLI 共用单一入口。

    非召对夜轮（night_id<=0）不入故事账。`run_extraction_for_turn` 契约上**从不抛**；
    本函数亦**从不抛**：chat_turns 查询等意外故障 → 标待补 + 返回 None，不回滚回话
    （ADR 0005 / 0036）。调用方（Web 后台线程 / CLI 同步）只负责在回话已持久化后调用。
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
        # ADR 0070 references only existing dossiers. If this turn has approved a
        # directive which close-night will materialize, leave its extraction
        # watermark untouched; close_night drains it once after dossier creation.
        if db.list_night_approved_pending(night_id, kind="directive"):
            return {"status": "deferred", "chat_turn_id": int(chat_turn_id)}
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
        # run_extraction_for_turn 契约从不抛；到此=查询等意外。不静默：标待补候补跑。
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
) -> Dict[str, Any]:
    """补跑抽取：对已持久化但账未抽（''/'pending'）的回话逐轮尽力补跑（ADR 0036）。

    **从不抛**——补跑失败不锁档（AC8），失败轮标待补、恢复照常续；返回汇总供调用方展示。
    补跑落账时序键绑源对话轮原始时序（settle 内用 source_night_seq），不用补跑执行时刻（AC11）。
    """
    rows = db.list_unextracted_replies(night_id=night_id)
    extracted = 0
    pending = 0

    settle_condition = threading.Condition()
    next_settle = 0

    def _run(item: tuple[int, Mapping[str, Any]]) -> Dict[str, Any]:
        index, row = item

        def _await_order() -> None:
            nonlocal next_settle
            with settle_condition:
                settle_condition.wait_for(lambda: next_settle == index)
                next_settle += 1
                settle_condition.notify_all()

        return run_extraction_for_turn(
            db=db,
            minister_name=str(row.get("minister_name") or ""),
            reply=str(row.get("reply") or ""),
            chat_turn_id=int(row.get("chat_turn_id") or 0),
            night_id=int(row.get("night_id") or 0),
            source_night_seq=int(row.get("night_seq") or 0),
            llm_config=llm_config,
            write_gate=write_gate,
            extractor_agent=extractor_agent,
            _settle_barrier=_await_order,
        )

    indexed_rows = list(enumerate(rows))
    # Use the same proven backend-safety seam as the monthly extractors.  map
    # preserves source order; each turn still owns one call, while the write gate
    # serializes atomic settlements.  Unsafe API/non-codex backends stay serial.
    from ming_sim.cli_backend import cli_backend_parallel_safe
    if len(rows) > 1 and cli_backend_parallel_safe(llm_config):
        with ThreadPoolExecutor(max_workers=len(rows), thread_name_prefix="audience-extract") as pool:
            results = list(pool.map(_run, indexed_rows))
    else:
        results = [_run(item) for item in indexed_rows]
    for result in results:
        status = result.get("status")
        if status == "done":
            extracted += 1
        elif status == "pending":
            pending += 1
    return {"extracted": extracted, "pending": pending, "scanned": len(rows)}


def drain_pending_before_close(
    *,
    db: Any,
    llm_config: Any,
    write_gate: threading.Lock,
    night_id: int,
    extractor_agent: Any = None,
) -> None:
    """收夜是史实书写边界（ADR 0036 线上 R3）：收夜前强制同步补跑一次清空待补。

    仍有待补（持续畸形/接口故障）→ **fail-closed 中止收夜**（夜保持开、显眼错误包可重试，
    同在飞超时熔断语义）；补跑成功则收夜继续。
    """
    catch_up_pending_extractions(
        db=db,
        llm_config=llm_config,
        write_gate=write_gate,
        night_id=int(night_id),
        extractor_agent=extractor_agent,
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
    """便捷入口：对当前开夜执行收夜前清空待补（无开夜则 no-op）。"""
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
