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
        facts.append({
            "person_names": [n.strip() for n in person_names_raw if n.strip()],
            "audibility": str(audibility),
            "body": body.strip(),
            "tags": [t for t in tags_raw if t],
            "presence_effect": str(presence_effect),
        })
    return facts


def extract_story_facts(
    reply: str,
    *,
    minister_name: str,
    present_names: Sequence[str],
    llm_config: Any,
    extractor_agent: Any = None,
) -> List[Dict[str, Any]]:
    """调抽取员把一段完整回话结构化成故事事实；空回话返回 []。

    垃圾 shape → ExtractionShapeError（响亮）；模型不可用 → LLMUnavailable。
    """
    text = str(reply or "").strip()
    if not text:
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
        "回话原文": text,
    }
    output = extract_agent_text(
        agent.run(json.dumps(materials, ensure_ascii=False))
    )
    if not output or not str(output).strip():
        raise LLMUnavailable("抽取员返回空文本")
    return parse_extraction_facts(output)


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
) -> Dict[str, Any]:
    """一轮叙事抽取落账尾随：幂等水位判 → 抽取 → 原子落账；失败 → 响亮错误包 + 待补。

    - 已 'done' → 幂等跳过（补跑不重复，AC6）。
    - 垃圾 shape / 模型失败 → 写错误包 + `mark_story_extraction_pending`，**不回滚对话、不抛**
      （回话已 done；返回 status='pending' 携错误包路径供玩家原地重试，AC3/AC8）。
    - 成功 → `settle_story_extraction` 单事务全有或全无（AC7），返回 status='done'。

    `write_gate` 必传：落账走真实 runtime 写锁（与月末并发 extractor / 其它端点写同一把）。
    """
    cid = int(chat_turn_id)
    if not cid or not str(reply or "").strip():
        return {"status": "skipped", "chat_turn_id": cid}
    if db.get_story_extract_status(cid) == "done":
        return {"status": "done", "chat_turn_id": cid, "already": True}

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
        )
    except Exception as exc:
        code = getattr(exc, "code", "extraction_failed")
        pack = write_audience_error_pack(
            kind="extraction_failed",
            message=f"叙事抽取失败（{code}）：{exc}",
            detail={
                "chat_turn_id": cid,
                "night_id": int(night_id),
                "minister_name": minister_name,
                "code": code,
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

    with write_gate:
        # 二次幂等复查（持锁后）：另一并发补跑可能已落账。
        if db.get_story_extract_status(cid) == "done":
            return {"status": "done", "chat_turn_id": cid, "already": True}
        entry_ids = db.settle_story_extraction(
            cid, int(night_id), facts, int(source_night_seq),
        )
    return {
        "status": "done",
        "chat_turn_id": cid,
        "entry_ids": entry_ids,
        "fact_count": len(facts),
    }


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
    for row in rows:
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
        )
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
