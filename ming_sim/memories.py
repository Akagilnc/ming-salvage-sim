"""事件记忆生成：把诏书与月末推演结果压成渐进式记忆卡。"""

from __future__ import annotations

import json
import re
from typing import Dict, Iterable, List, Optional

from agno.agent import Agent

from ming_sim.agents import parse_agent_json, run_agent_text
from ming_sim.db import GameDB
from ming_sim.models import GameState
from ming_sim.token_stats import tlog


def _short(text: object, limit: int = 80) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(s) <= limit:
        return s
    return s[: limit - 1] + "…"


def _title(text: object, limit: int = 20) -> str:
    s = _short(text, limit)
    return s or "旧事记忆"


def _directive_summary(text: str) -> str:
    s = re.sub(r"奉天承运皇帝诏曰[:：]?", "", text or "").strip()
    s = s.replace("钦此。", "").replace("钦此", "").strip()
    return _short(s, 80)


def _tags(*values: object) -> List[str]:
    out: List[str] = []
    for value in values:
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            items = value
        else:
            items = [value]
        for item in items:
            tag = str(item or "").strip()
            if tag and tag not in out:
                out.append(tag[:40])
    return out


def _source(
    db: GameDB,
    memory_id: int,
    source_kind: str,
    source_id: object,
    excerpt: object,
    **locator: object,
) -> None:
    db.add_event_memory_source(
        memory_id,
        source_kind=source_kind,
        source_id=str(source_id or ""),
        excerpt=_short(excerpt, 200),
        locator={k: v for k, v in locator.items() if v not in ("", None)},
    )


def _actors(directives: Iterable[object]) -> List[str]:
    seen: List[str] = []
    for row in directives:
        actor = str(row["actor"] or "").strip()
        if actor and actor not in seen:
            seen.append(actor)
    return seen


def _primary_actor(directives: Iterable[object]) -> str:
    actors = _actors(directives)
    return actors[0] if len(actors) == 1 else ""


def _issue_source_id(prefix: str, item: Dict[str, object]) -> str:
    issue_id = item.get("issue_id") or item.get("title") or "unknown"
    return f"{prefix}:{issue_id}"


def _significant_change(change: Dict[str, object]) -> bool:
    delta = change.get("delta")
    if isinstance(delta, int) and abs(delta) >= 8:
        return True
    field = str(change.get("field") or "")
    # arrears 单位=累计欠饷万两；任何 delta（哪怕 ±1 万两）都视为人物关键记忆事件
    if field in {"arrears", "unrest", "military_pressure", "stance", "last_action", "status"}:
        return True
    return delta is None and field in {"natural_disaster", "human_disaster", "status", "last_action"}


def _write_actor_memory(
    db: GameDB,
    state: GameState,
    actor: str,
    event_type: str,
    title: str,
    cause: str,
    process: str,
    outcome: str,
    sentiment: str,
    importance: int,
    tags: List[str],
    source_kind: str,
    source_id: str,
    narrative: str,
    decree_text: str,
) -> int:
    if not actor:
        return 0
    memory_id = db.upsert_event_memory(
        state,
        subject_type="character",
        subject_id=actor,
        event_type=event_type,
        title=_title(title),
        cause=_short(cause),
        process=_short(process),
        outcome=_short(outcome),
        sentiment=sentiment,
        importance=importance,
        tags=_tags(actor, tags),
        source_kind=source_kind,
        source_id=source_id,
    )
    if memory_id:
        _source(db, memory_id, "decree", state.turn, decree_text, turn=state.turn, field="decree_text")
        if narrative:
            _source(db, memory_id, "simulation_narrative", state.turn, narrative, turn=state.turn, field="narrative")
    return memory_id


def _row_to_dict(row: object) -> Dict[str, object]:
    return {key: row[key] for key in row.keys()}


_SOURCE_KINDS = {
    "directive",
    "decree",
    "simulation_narrative",
    "extractor_output",
    "issue",
    "chat_message",
    "turn_report",
    "system",
}

_TURN_SOURCE_KINDS = {"decree", "simulation_narrative", "extractor_output", "turn_report"}
_TURN_SOURCE_SENTINELS = {
    "",
    "decree",
    "simulation_narrative",
    "extractor_output",
    "turn_report",
    "narrative",
    "current_turn",
    "turn",
}


def _normalize_source_kind(value: object) -> str:
    source_kind = str(value or "system").strip()
    return source_kind if source_kind in _SOURCE_KINDS else "system"


def _normalize_source_id(source_kind: str, source_id: object, state: GameState) -> str:
    raw = str(source_id or "").strip()
    if source_kind in _TURN_SOURCE_KINDS and raw in _TURN_SOURCE_SENTINELS:
        return str(state.turn)
    if source_kind == "directive" and raw.startswith("#"):
        raw = raw[1:]
    if source_kind == "issue" and raw.startswith("#"):
        raw = raw[1:]
    return raw or str(state.turn)


def _normalize_locator(locator: object, source_kind: str, source_id: str, state: GameState) -> Dict[str, object]:
    loc = locator if isinstance(locator, dict) else {}
    out: Dict[str, object] = {}
    if source_kind in _TURN_SOURCE_KINDS:
        out["turn"] = int(source_id) if str(source_id).isdigit() else state.turn
    elif source_kind == "directive":
        out["directive_id"] = int(source_id) if str(source_id).isdigit() else source_id
    elif source_kind == "issue":
        out["issue_id"] = int(source_id) if str(source_id).isdigit() else source_id
    elif source_kind == "chat_message":
        out["chat_id"] = source_id
    allowed_fields = {
        "directive": {"text", "notes", "status"},
        "decree": {"decree_text"},
        "simulation_narrative": {"narrative"},
        "extractor_output": {
            "extractor_output",
            "issue_summary",
            "office_changes",
            "character_status_changes",
            "region_changes",
            "army_changes",
            "faction_delta",
        },
        "issue": {"issue", "issue_summary", "advances", "new_issues", "closes"},
        "turn_report": {"report"},
        "chat_message": {"content"},
        "system": {"system"},
    }
    field = str(loc.get("field") or "").strip()
    if field in allowed_fields.get(source_kind, set()):
        out["field"] = field
    elif source_kind == "decree":
        out["field"] = "decree_text"
    elif source_kind == "simulation_narrative":
        out["field"] = "narrative"
    elif source_kind == "extractor_output":
        out["field"] = "extractor_output"
    return out


def _normalize_memory_item(item: object, state: GameState) -> Optional[Dict[str, object]]:
    if not isinstance(item, dict):
        return None
    subject_type = str(item.get("subject_type") or "").strip()
    subject_id = str(item.get("subject_id") or "").strip()
    event_type = str(item.get("event_type") or "").strip()
    source_kind = _normalize_source_kind(item.get("source_kind"))
    source_id = _normalize_source_id(source_kind, item.get("source_id"), state)
    if not subject_type or not subject_id or not event_type or not source_id:
        return None
    try:
        importance = int(item.get("importance") or 3)
    except (TypeError, ValueError):
        importance = 3
    expires_raw = item.get("expires_turn")
    try:
        expires_turn = int(expires_raw) if expires_raw not in (None, "", "null") else None
    except (TypeError, ValueError):
        expires_turn = None
    tags = item.get("tags") if isinstance(item.get("tags"), list) else []
    sources = item.get("sources") if isinstance(item.get("sources"), list) else []
    return {
        "subject_type": subject_type,
        "subject_id": subject_id,
        "event_type": event_type,
        "title": _title(item.get("title")),
        "cause": _short(item.get("cause")),
        "process": _short(item.get("process")),
        "outcome": _short(item.get("outcome")),
        "sentiment": str(item.get("sentiment") or "neutral"),
        "importance": max(1, min(5, importance)),
        "tags": _tags(tags),
        "source_kind": source_kind,
        "source_id": source_id,
        "expires_turn": expires_turn,
        "sources": sources,
    }


def _write_llm_memories(db: GameDB, state: GameState, data: Dict[str, object]) -> int:
    count = 0
    for raw in data.get("memories") or []:
        item = _normalize_memory_item(raw, state)
        if not item:
            continue
        memory_id = db.upsert_event_memory(
            state,
            subject_type=str(item["subject_type"]),
            subject_id=str(item["subject_id"]),
            event_type=str(item["event_type"]),
            title=str(item["title"]),
            cause=str(item["cause"]),
            process=str(item["process"]),
            outcome=str(item["outcome"]),
            sentiment=str(item["sentiment"]),
            importance=int(item["importance"]),
            tags=list(item["tags"]),
            source_kind=str(item["source_kind"]),
            source_id=str(item["source_id"]),
            expires_turn=item["expires_turn"],  # type: ignore[arg-type]
        )
        if not memory_id:
            continue
        tlog(f"[memory/write] id={memory_id} subject={item['subject_id']} event={item['event_type']} "
             f"title={item['title']!r} importance={item['importance']} source={item['source_kind']}:{item['source_id']}")
        tlog(f"[MEM-IO/memory/write/BODY] id={memory_id} "
             f"cause={item['cause']!r} process={item['process']!r} outcome={item['outcome']!r} "
             f"sentiment={item['sentiment']} tags={item['tags']} expires_turn={item['expires_turn']}")
        for src in item["sources"]:  # type: ignore[index]
            if not isinstance(src, dict):
                continue
            source_kind = _normalize_source_kind(src.get("source_kind") or item["source_kind"])
            source_id = _normalize_source_id(source_kind, src.get("source_id") or item["source_id"], state)
            db.add_event_memory_source(
                memory_id,
                source_kind=source_kind,
                source_id=source_id,
                excerpt=_short(src.get("excerpt"), 200),
                locator=_normalize_locator(src.get("locator"), source_kind, source_id, state),
            )
        count += 1
    db.prune_event_memories_for_turn(state.turn, per_subject=3)
    tlog(f"[memory/extractor] llm_written={count}")
    return count


def extract_event_memories_with_agent(
    agent: Agent,
    db: GameDB,
    state: GameState,
    directives: List[object],
    decree_text: str,
    narrative: str,
    extractor_output: str,
    applied: Dict[str, object],
) -> int:
    payload = {
        "turn": {"year": state.year, "period": state.period, "turn": state.turn},
        "directives": [_row_to_dict(row) for row in directives],
        "decree_text": decree_text,
        "narrative": narrative,
        "applied": applied,
        "extractor_output": extractor_output,
        "instruction": "提取渐进式事件记忆摘要卡和来源摘录。",
    }
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=False)
    tlog(f"[MEM-IO/memory-extractor/INPUT] ({len(payload_json)}字):\n{payload_json}")
    raw = run_agent_text(agent, payload_json, tag="memory-extractor")
    tlog(f"[MEM-IO/memory-extractor/OUTPUT] ({len(raw)}字):\n{raw}")
    data = parse_agent_json(raw, "记忆抽取")
    return _write_llm_memories(db, state, data)


def extract_chat_memories_for_minister(
    agent: Agent,
    db: GameDB,
    state: GameState,
    minister_name: str,
    chat_history: List[Dict[str, str]],
) -> int:
    """用 LLM 从单个大臣当月召对提取承诺/建议/情报记忆，写入 event_memory。"""
    if not chat_history:
        return 0
    tlog(f"[chat-memory] minister={minister_name} msgs={len(chat_history)} turn={state.turn}")
    payload = {
        "turn": {"year": state.year, "period": state.period, "turn": state.turn},
        "minister_name": minister_name,
        "chat_history": chat_history,
        "instruction": "提取本次召对的结构化记忆卡，只写有实质内容的承诺/建议/情报，闲聊跳过。",
    }
    payload_json = json.dumps(payload, ensure_ascii=False, sort_keys=False)
    tlog(f"[MEM-IO/chat-memory/INPUT] minister={minister_name} ({len(payload_json)}字):\n{payload_json}")
    raw = run_agent_text(agent, payload_json, tag="chat-memory")
    tlog(f"[MEM-IO/chat-memory/OUTPUT] minister={minister_name} ({len(raw)}字):\n{raw}")
    data = parse_agent_json(raw, "对话记忆抽取")
    mem_list = data.get("memories") or []
    tlog(f"[chat-memory] parsed memories={len(mem_list)}: "
         + str([(m.get("event_type"), m.get("title")) for m in mem_list if isinstance(m, dict)]))
    # source_kind 强制为 chat_message，source_id 强制为 minister_name:turn
    for item in mem_list:
        if isinstance(item, dict):
            item["source_kind"] = "chat_message"
            item["source_id"] = f"{minister_name}:{state.turn}"
    return _write_llm_memories(db, state, data)


def extract_all_chat_memories(agent: Agent, db: GameDB, state: GameState) -> int:
    """对当月所有有过召对的大臣各跑一次记忆提取，单个失败不阻断。"""
    chat_by_minister = db.get_chat_messages_for_turn(state.turn)
    total = 0
    for minister_name, history in chat_by_minister.items():
        try:
            n = extract_chat_memories_for_minister(agent, db, state, minister_name, history)
            total += n
        except Exception as exc:
            tlog(f"[chat-memory] minister={minister_name} 失败，跳过：{exc}")
    tlog(f"[chat-memory] total_written={total}")
    return total


def record_event_memories_from_resolution(
    db: GameDB,
    state: GameState,
    directives: List[object],
    decree_text: str,
    narrative: str,
    extractor_output: str,
    applied: Dict[str, object],
) -> None:
    """从本回合正式诏书与已落地推演结果生成事件记忆。

    只做规则提取，不调用 LLM；不明确归因时写 court/region/army/faction 记忆。
    """
    tlog(f"[memory/fallback] rule extraction turn={state.turn}")
    actor_names = _actors(directives)
    actor = _primary_actor(directives)

    # 1) 大臣拟旨被采纳并颁行。
    for row in directives:
        row_actor = str(row["actor"] or "").strip()
        source = str(row["source"] or "")
        if not row_actor or source != "大臣拟旨":
            continue
        memory_id = db.upsert_event_memory(
            state,
            "character",
            row_actor,
            "edict_result",
            "拟旨被采纳",
            cause=_directive_summary(str(row["text"] or "")),
            process="皇帝采纳并写入本月诏书",
            outcome="已颁行，待后续见效",
            sentiment="positive",
            importance=3,
            tags=_tags("诏书", "拟旨", row_actor, row["event_id"], row["event_title"]),
            source_kind="directive",
            source_id=str(row["id"]),
        )
        _source(db, memory_id, "directive", row["id"], row["text"], directive_id=row["id"], field="text")
        _source(db, memory_id, "decree", state.turn, decree_text, turn=state.turn, field="decree_text")

    issue_summary = applied.get("issue_summary") or {}

    # 2) issue 新立/推进/结案/失败。
    for item in issue_summary.get("new_issues") or []:
        if not isinstance(item, dict) or item.get("rejected"):
            continue
        issue_id = item.get("issue_id")
        title = str(item.get("title") or "新立事项")
        target_actor = actor
        if target_actor:
            memory_id = _write_actor_memory(
                db, state, target_actor, "issue_progress", title,
                "本月诏书强推新政", "此事立为长期局势",
                f"事项#{issue_id}进入在办，后续须看推进成败",
                "neutral", 3, _tags("诏书", "事项", f"#{issue_id}", title),
                "issue", f"new:{issue_id}", narrative, decree_text,
            )
            _source(db, memory_id, "issue", issue_id, json.dumps(item, ensure_ascii=False), issue_id=issue_id)
        else:
            memory_id = db.upsert_event_memory(
                state, "court", "朝廷", "issue_progress", title,
                "本月诏书强推新政", "此事立为长期局势",
                f"事项#{issue_id}进入在办", "neutral", 3,
                _tags("诏书", "事项", f"#{issue_id}", title),
                "issue", f"new:{issue_id}",
            )
            _source(db, memory_id, "issue", issue_id, json.dumps(item, ensure_ascii=False), issue_id=issue_id)

    for item in issue_summary.get("advances") or []:
        if not isinstance(item, dict):
            continue
        issue_id = item.get("issue_id")
        title = str(item.get("title") or f"事项#{issue_id}推进")
        from_value = int(item.get("from_value") or 0)
        to_value = int(item.get("to_value") or 0)
        delta = to_value - from_value
        abs_delta = abs(delta)
        if abs_delta <= 0:
            continue
        importance = 2 if abs_delta <= 5 else (3 if abs_delta <= 15 else 4)
        target_actor = actor
        subject_type = "character" if target_actor else "court"
        subject_id = target_actor or "朝廷"
        memory_id = db.upsert_event_memory(
            state, subject_type, subject_id, "issue_progress", _title(title),
            cause="本月诏书推动旧事",
            process=_short(item.get("narrative") or item.get("stage_text") or "局势有推进"),
            outcome=f"进度{from_value}→{to_value}，{_short(item.get('stage_text'), 40)}",
            sentiment="positive" if delta > 0 else "negative",
            importance=importance,
            tags=_tags("诏书", "事项", f"#{issue_id}", title, actor_names),
            source_kind="issue",
            source_id=f"advance:{issue_id}:{state.turn}",
        )
        _source(db, memory_id, "issue", issue_id, json.dumps(item, ensure_ascii=False), issue_id=issue_id)
        _source(db, memory_id, "simulation_narrative", state.turn, item.get("narrative") or narrative, turn=state.turn)

    for item in issue_summary.get("closes") or []:
        if not isinstance(item, dict):
            continue
        issue_id = item.get("issue_id")
        reason = str(item.get("reason") or "")
        title = str(item.get("title") or f"事项#{issue_id}结案")
        event_type = "issue_success" if reason == "resolved" else "issue_failure"
        sentiment = "positive" if reason == "resolved" else "negative"
        subject_type = "character" if actor else "court"
        subject_id = actor or "朝廷"
        memory_id = db.upsert_event_memory(
            state, subject_type, subject_id, event_type, _title(title),
            cause="旧事至本月见分晓",
            process=_short(item.get("narrative") or "邸报明文结案"),
            outcome="已办成" if reason == "resolved" else "已失败或失控",
            sentiment=sentiment,
            importance=5,
            tags=_tags("事项", f"#{issue_id}", title, actor_names),
            source_kind="issue",
            source_id=f"close:{issue_id}:{state.turn}",
        )
        _source(db, memory_id, "issue", issue_id, json.dumps(item, ensure_ascii=False), issue_id=issue_id)
        _source(db, memory_id, "simulation_narrative", state.turn, item.get("narrative") or narrative, turn=state.turn)

    # 3) 任免惩处。
    for item in applied.get("office_changes") or []:
        if not isinstance(item, dict) or item.get("rejected"):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        new_office = str(item.get("new_office") or "")
        kind = str(item.get("kind") or "")
        memory_id = db.upsert_event_memory(
            state, "character", name, "appointment", "官职变更",
            cause=_short(item.get("reason") or "诏书任命"),
            process="朝廷本月调整任用",
            outcome=f"{'新任' if kind == 'appoint' else '调任'}{new_office}",
            sentiment="positive",
            importance=4,
            tags=_tags("任命", name, new_office, actor_names),
            source_kind="system",
            source_id=f"office:{name}:{state.turn}",
        )
        _source(db, memory_id, "extractor_output", state.turn, json.dumps(item, ensure_ascii=False), turn=state.turn, field="office_changes")
        if actor and actor != name:
            _write_actor_memory(
                db, state, actor, "appointment", f"{name}官职变更",
                "本月诏书或推演涉及任用", f"{name}获朝廷调整任用",
                f"{name}现为{new_office}", "mixed", 2,
                _tags("任命", name, new_office), "system", f"office-witness:{name}:{state.turn}",
                narrative, decree_text,
            )

    for item in applied.get("character_status_changes") or []:
        if not isinstance(item, dict) or item.get("rejected"):
            continue
        name = str(item.get("name") or "").strip()
        status = str(item.get("status") or "")
        if not name:
            continue
        importance = 5 if status in {"imprisoned", "exiled", "dead"} else 4
        memory_id = db.upsert_event_memory(
            state, "character", name, "punishment", "身后处分",
            cause=_short(item.get("reason") or "邸报明文处置"),
            process="朝廷本月改变其政治处境",
            outcome=f"状态转为{status}",
            sentiment="negative",
            importance=importance,
            tags=_tags("处分", name, status, actor_names),
            source_kind="system",
            source_id=f"status:{name}:{state.turn}",
        )
        _source(db, memory_id, "extractor_output", state.turn, json.dumps(item, ensure_ascii=False), turn=state.turn, field="character_status_changes")
        if actor and actor != name:
            _write_actor_memory(
                db, state, actor, "punishment", f"{name}被处置",
                "本月诏书或推演牵涉人事处分", f"{name}被朝廷处置",
                f"{name}状态转为{status}", "mixed", importance,
                _tags("处分", name, status), "system", f"status-witness:{name}:{state.turn}",
                narrative, decree_text,
            )

    # 4) 地区、军队、势力显著变化。
    for faction, delta in (applied.get("faction_delta") or {}).items():
        try:
            d = int(delta)
        except (TypeError, ValueError):
            continue
        if abs(d) < 8:
            continue
        memory_id = db.upsert_event_memory(
            state, "faction", str(faction), "edict_result", "派系风向变化",
            cause="本月诏书与推演影响朝局",
            process=f"{faction}对朝廷观感明显变化",
            outcome=f"满意度{'+' if d > 0 else ''}{d}",
            sentiment="positive" if d > 0 else "negative",
            importance=3,
            tags=_tags("派系", faction, actor_names),
            source_kind="simulation",
            source_id=f"faction:{faction}:{state.turn}",
        )
        _source(db, memory_id, "extractor_output", state.turn, f"{faction}{d:+d}", turn=state.turn, field="faction_delta")
        if actor:
            _write_actor_memory(
                db, state, actor, "edict_result", f"{faction}风向变化",
                "本月诏书后朝局牵动派系", f"{faction}满意度变化",
                f"{faction}{d:+d}", "mixed", 2,
                _tags("派系", faction), "simulation", f"actor-faction:{faction}:{state.turn}",
                narrative, decree_text,
            )

    for subject_type, key, changes, label in (
        ("region", "region", applied.get("region_changes") or [], "地区变化"),
        ("army", "army", applied.get("army_changes") or [], "军队变化"),
    ):
        for change in changes:
            if not isinstance(change, dict) or not _significant_change(change):
                continue
            subject_id = str(change.get(key) or "").strip()
            if not subject_id:
                continue
            field_label = str(change.get("label") or change.get("field") or "")
            delta = change.get("delta")
            outcome = f"{field_label}{'+' if isinstance(delta, int) and delta > 0 else ''}{delta}" if isinstance(delta, int) else f"{field_label}改为{change.get('new')}"
            memory_id = db.upsert_event_memory(
                state, subject_type, subject_id, "edict_result", label,
                cause=_short(change.get("reason") or "月末推演"),
                process=f"{subject_id}{field_label}发生显著变化",
                outcome=outcome,
                sentiment="negative" if isinstance(delta, int) and delta < 0 else "mixed",
                importance=3,
                tags=_tags(label, subject_id, field_label, actor_names),
                source_kind="simulation",
                source_id=f"{subject_type}:{subject_id}:{change.get('field')}:{state.turn}",
            )
            _source(db, memory_id, "extractor_output", state.turn, json.dumps(change, ensure_ascii=False), turn=state.turn)
            if actor:
                _write_actor_memory(
                    db, state, actor, "edict_result", f"{subject_id}{label}",
                    "本月诏书后盘面变化", f"{subject_id}{field_label}变化",
                    outcome, "mixed", 2,
                    _tags(label, subject_id, field_label), "simulation",
                    f"actor-{subject_type}:{subject_id}:{change.get('field')}:{state.turn}",
                    narrative, decree_text,
                )

    db.prune_event_memories_for_turn(state.turn, per_subject=3)
