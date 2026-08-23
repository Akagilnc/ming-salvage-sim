"""#634 召对口写端：召对判官当场识别并记边事件（与回话并行）——ADR 0082。

时序契约（ADR 0082 唯一 canonical）：
- 判官每拍读「至当前已完成的对话轮」（玩家消息＋此前各轮回话），派发始终与回话
  生成并行（P5 零额外等待）；本轮回话中新生的事件由下一拍或收夜扫尾捕获。
- 判官带已判水位：逐轮 ``relation_judge_status`` 标记即水位（无平行水位表）；
  每拍只判水位之后的新完成轮；收夜扫尾只补残段。落库经 canonical 写口
  ``record_relation_edge_event`` 的 UNIQUE 幂等——同一当面事件跨拍重看不重复记账。
- 边事件 origin 含源轮绑定：``召对判官|chat_turn:{轮 id}``＋写口附 ``|round:N``；
  撤回该轮＝删该轮边事件（ADR 0038 白名单③）＋undone 轮天然出窗（水位回退）；
  在飞判官拍写入前校验目标轮存活，撤回不得被补跑复活。
- 判官输入面单一接缝：``relation_read.project_relation_ledger(viewer=None)``
  全知机面（ID-12），禁平行表/第二套序列化/缓存；DTO 五字段白名单照抄 #640 冻结文本。
- 判官漏判不阻塞召对主链：LLM 边界失败 → 降级留痕、窗口保持开放候下一机会；
  无互动零事件零副作用。

方向/基数引用 #633 票面修正案 canonical 表（单一真源，不复制规则文本）：施动者→
受动者、每有序施受对恰一行、多方事件=牵头→各参与方各一行（r2 F2）。
"""

from __future__ import annotations

import logging
import threading
from contextlib import nullcontext
from typing import Any, Dict, List, Mapping, Optional

from ming_sim.applier import atomic
from ming_sim.exceptions import LLMContractError, LLMUnavailable
from ming_sim.llm_model import extract_agent_text
from ming_sim.relations import (
    MINISTER_EDGE_KINDS,
    SUMMON_EDGE_ORIGIN_PREFIX,
    validate_edge_kind,
)

logger = logging.getLogger(__name__)

# 模块级 single-flight：防同库两拍并发判同一窗口双跑 LLM/重复写（写序归 write gate）。
_single_flight_lock = threading.Lock()
_in_flight: Dict[int, Any] = {}


def summon_edge_origin(chat_turn_id: int) -> str:
    """#634 召对口唯一 origin 拼装器：``{前缀}|chat_turn:{轮 id}``。

    写口 bind_origin_round 再附 ``|round:N``（N=当前回合）：round 段承担 TD-1 回指，
    chat_turn 段是撤回按轮删的唯一源轮绑定真源（ADR 0038 白名单③）。禁在调用侧
    另拼第二套 origin。"""
    return f"{SUMMON_EDGE_ORIGIN_PREFIX}|chat_turn:{int(chat_turn_id)}"


def _transcript_line(turn_row: Mapping[str, Any]) -> str:
    """单轮对话的判官读面：皇帝问话＋该轮回话原文。"""
    return (
        f"— 轮 #{int(turn_row.get('id') or 0)} · {turn_row.get('minister_name') or ''} —\n"
        f"皇帝：{turn_row.get('user_message') or '（问话未存）'}\n"
        f"{turn_row.get('minister_name') or ''}：{turn_row.get('minister_message') or ''}"
    )


def build_relation_judge_prompt(db: Any, turn_rows: List[Mapping[str, Any]]) -> str:
    """组判官输入面：已完成对话记录＋账本全知机面（ID-12 单一接缝）。

    全知机面必须显式传 ``viewer=None``（#640 冻结契约）；角色裁切面绝不在此混用。
    有账列 DTO 可见内容（summary/recent_context/updated_at_period），无账给显式
    缺席标记——有账与无账行为可辨，不静默空白。"""
    from ming_sim import relation_read

    transcript = "\n\n".join(_transcript_line(row) for row in turn_rows)
    ledger = relation_read.project_relation_ledger(db, viewer=None)
    if ledger:
        lines = [
            f"- {dto['source']} → {dto['target']}｜摘要：{dto['summary'] or '（无摘要）'}｜"
            f"近况：{dto['recent_context'] or '（无近况）'}｜更新：{dto['updated_at_period']}"
            for dto in ledger
        ]
        ledger_face = "\n".join(lines)
    else:
        ledger_face = "（当前无关系账记录。）"
    return (
        "下面是本次召对至今已完成的对话记录，以及当前关系账全知机面（判官专用）。\n"
        "请从中识别**当面发生的**大臣↔大臣边事件（当面站台作保／表态／结怨／协作等），\n"
        "只记对话里真实演出的情节：不虚构、不引申、不从旧账翻旧账。\n\n"
        "【召对对话记录（至当前已完成轮）】\n"
        f"{transcript}\n\n"
        "【关系账全知机面（判官专用）】\n"
        f"{ledger_face}\n\n"
        "【输出】只输出一个 JSON object；每项的源轮必须是该事件实际发生的轮号：\n"
        '{"events":[{"源轮":12,"施动者":"甲","受动者":"乙","类目":"站台","语境":"一句话记该当面事件"}]}\n'
        "类目限：站台、结怨、协作、联名、荐引、恩义、使绊、连坐、把柄。\n"
        "施动者→受动者为事件方向；多方事件由牵头者对各方各出一项；"
        "受动者可为字符串数组。\n"
        "没有当面互动时输出 {\"events\":[]}。不要解释、不要 JSON 以外任何文字。"
    )


def parse_relation_judge_output(raw: str) -> List[Any]:
    """硬格式 JSON → events 项列表；形状垃圾上抛 LLMContractError（降级留痕，非静默零事件）。"""
    text = str(raw or "").strip()
    from ming_sim.agents import parse_agent_json

    data = parse_agent_json(text, "召对关系判官")
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise LLMContractError("召对关系判官输出缺 events 数组")
    return list(data["events"])


def _canonical_turn_id(value: Any) -> int:
    """Accept only JSON integers or their canonical unsigned decimal spelling."""
    if isinstance(value, bool):
        raise ValueError("源轮必须为本窗口对话轮 id")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value and value == str(int(value)) and value.isdecimal():
        return int(value)
    raise ValueError("源轮必须为 canonical 十进制整数")


def _resolve_one_event(
    db: Any, state: Any, item: Any, allowed_endpoint_names: Any,
    window_turn_ids: set[int], turn_rows: Mapping[int, Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """校验并落库单个判官事件项；坏项 ValueError 上抛（逐项拒收留痕，好项不受牵连）。

    校验语义与 #633 结算口同构（端点闭集、F1 字节原样、r2 F2 有序对展开）；
    来源拼装器换用 summon_edge_origin（源轮绑定到触发轮 id）。"""
    if not isinstance(item, Mapping):
        raise ValueError("判官事件项必须为对象")
    raw_turn_id = item.get("源轮", item.get("chat_turn_id"))
    # 单轮窗口不存在归因歧义，兼容模型偶发漏字段；多轮窗口必须明确源轮，绝不再
    # 统一绑到最大轮。
    if raw_turn_id is None and len(window_turn_ids) == 1:
        chat_turn_id = next(iter(window_turn_ids))
    else:
        chat_turn_id = _canonical_turn_id(raw_turn_id)
    if chat_turn_id not in window_turn_ids:
        raise ValueError(f"源轮不在本次判读窗口：{chat_turn_id!r}")
    origin = summon_edge_origin(chat_turn_id)
    kind = validate_edge_kind(item.get("类目") or item.get("kind"))
    if kind not in MINISTER_EDGE_KINDS:
        raise ValueError(f"召对口只收大臣侧类目，得 {kind!r}（君臣类目归 0079 写端）")
    raw_source = item["施动者"] if item.get("施动者") is not None else item.get("source")
    if not isinstance(raw_source, str):
        raise ValueError("施动者不能为空" if raw_source is None else "施动者必须为字符串")
    source = raw_source.strip()
    if not source:
        raise ValueError("施动者不能为空")
    raw_targets = item["受动者"] if item.get("受动者") is not None else item.get("target")
    if isinstance(raw_targets, str):
        candidates = [raw_targets]
    elif isinstance(raw_targets, list) and all(isinstance(t, str) for t in raw_targets):
        candidates = list(raw_targets)
    else:
        raise ValueError("受动者必须为字符串或字符串列表")
    seen: set[str] = set()
    targets: List[str] = []
    for candidate in candidates:
        name = candidate.strip()
        if not name:
            raise ValueError("受动者不能为空")
        if name == source:
            raise ValueError(f"受动者不能为施动者自身：{source!r}")
        if name not in seen:
            seen.add(name)
            targets.append(name)
    if not targets:
        raise ValueError("受动者不能为空")
    raw_context = item["语境"] if item.get("语境") is not None else item.get("context")
    if not isinstance(raw_context, str):
        raise ValueError("边事件语境不能为空" if raw_context is None else "语境必须为字符串")
    if not raw_context.strip():
        raise ValueError("边事件语境不能为空")
    illegal = [name for name in [source, *targets] if name not in allowed_endpoint_names]
    if illegal:
        raise ValueError(
            f"边端点须为当前在朝合格大臣（幻觉名/错字/不在名册者拒收）：{illegal!r}"
        )
    out: List[Dict[str, Any]] = []
    for target in targets:
        source_turn = turn_rows[chat_turn_id]
        edge_id = int(db.record_relation_edge_event(
            source=source, target=target, event_kind=kind,
            context=raw_context, origin=origin,
            turn=int(source_turn.get("turn") or 0),
            year=int(source_turn.get("year") or 0),
            period=int(source_turn.get("period") or 0),
        ))
        out.append({
            "source": source, "target": target, "event_kind": kind,
            "origin": origin, "edge_id": edge_id,
        })
    return out


def run_summon_relation_judge(
    db: Any,
    state: Any,
    *,
    llm_config: Any = None,
    write_gate: Any = None,
    agent: Any = None,
    night_id: Optional[int] = None,
    allowed_endpoint_names: Optional[set[str]] = None,
) -> Dict[str, Any]:
    """一拍判官腿：解窗 → 组面 → LLM → 逐项落库 → 标水位。

    DB 读（窗口/对话/账面/存活复查/写入/标记）一律短持 ``write_gate``（共享 conn
    禁闸外裸读，#1353 同纪律）；LLM 在闸外（与抽取同形）。返回：

    - ``{"skipped": "no_window"}``——窗口为空，零 LLM 零副作用；
    - ``{"skipped": "judge_in_flight"}``——同库已有判官拍在飞；
    - ``{"skipped": "turn_retired"}``——写入前存活复查发现窗口内有轮被撤/失败，
      整批零写入零标记（ADR 0038 终结异步残余）；
    - ``{"degraded": reason}``——判官 LLM 失败/坏输出，响亮降级留痕、窗口保持开放
      （漏判不阻塞召对主链，ADR 0005 不宽吞：logger.warning 留痕）；
    - 正常——``{"judged_turn_ids", "origin", "edges", "written", "rejected"}``。
    """
    key = id(db)
    with _single_flight_lock:
        if key in _in_flight:
            return {"skipped": "judge_in_flight"}
        _in_flight[key] = db
    try:
        gate = write_gate if write_gate is not None else nullcontext()
        # 1. 解窗（短持 gate）
        with gate:
            window = (
                db.list_unjudged_completed_chat_turns(night_id=night_id)
                if hasattr(db, "list_unjudged_completed_chat_turns") else []
            )
        if not window:
            return {"skipped": "no_window"}
        batch_night_id = int(window[0].get("night_id") or 0)
        # Prompt context includes already-judged preceding turns, while only `window`
        # remains eligible for output/watermark.
        with gate:
            context_rows = (
                db.list_relation_judge_context(batch_night_id, max(int(r["id"]) for r in window))
                if hasattr(db, "list_relation_judge_context") else window
            )
            hydrated = [_hydrate_turn(db, row) for row in context_rows]
            prompt = build_relation_judge_prompt(db, hydrated)
        # 3. LLM 在闸外；失败降级留痕不抛（漏判不阻塞主链）。
        # llm_config 未配置且未注入替身 → 零 LLM 快速降级（与「无票零 LLM」同纪律）。
        try:
            local_agent = agent
            if local_agent is None:
                if not llm_config:
                    raise LLMUnavailable("llm_config 未配置", code="relation_judge_offline")
                from ming_sim.agents import create_relation_judge_agent

                local_agent = create_relation_judge_agent(llm_config)
            output = local_agent.run(prompt)
            raw = extract_agent_text(output) if output is not None else ""
            if not raw and output is not None and hasattr(output, "content"):
                raw = str(getattr(output, "content") or "")
            items = parse_relation_judge_output(raw)
        except (LLMContractError, LLMUnavailable, TypeError, ValueError) as exc:
            logger.warning("relation judge degraded (contract/unavailable): %s", exc)
            return {"degraded": str(exc), "judged_turn_ids": []}
        except Exception as exc:
            logger.warning("relation judge degraded: %s", exc, exc_info=True)
            return {"degraded": str(exc), "judged_turn_ids": []}
        # 4. 存活复查＋落库＋标水位（短持 gate；同一 gate 内原子观察）
        with gate:
            survivors = _live_window_turns(db, window)
            if len(survivors) != len(window):
                return {"skipped": "turn_retired"}
            window_turn_ids = {int(row["id"]) for row in window}
            # Eligibility is a source-night fact, not the mutable live court roster.
            allowed = set(allowed_endpoint_names or ())
            allowed.update(str(row.get("minister_name") or "") for row in context_rows)
            if batch_night_id > 0:
                from ming_sim.audience_night import persons_entered_tonight
                entered = persons_entered_tonight(db, batch_night_id)
                allowed.update(entered)
            else:
                # Old pre-night saves have no persisted attendance ledger.
                allowed.update(row["name"] for row in db.current_court_roster_rows(state))
            turn_rows = {int(row["id"]): row for row in window}
            written: List[Dict[str, Any]] = []
            rejected: List[Dict[str, Any]] = []
            # 边写与水位是一个恢复单元：任一异常须同时回滚，不能留下已落边、未进水位
            # 的 crash gap。canonical writer 内部 commit 由 atomic 暂停。
            with atomic(db):
                blocked_turn_ids: set[int] = set()
                block_all = False
                for item in items:
                    attributed_id: Optional[int] = None
                    if isinstance(item, Mapping):
                        raw_id = item.get("源轮", item.get("chat_turn_id"))
                        if raw_id is None and len(window_turn_ids) == 1:
                            attributed_id = next(iter(window_turn_ids))
                        else:
                            try:
                                candidate = _canonical_turn_id(raw_id)
                                if candidate in window_turn_ids:
                                    attributed_id = candidate
                            except ValueError:
                                pass
                    try:
                        written.extend(_resolve_one_event(
                            db, state, item, allowed, window_turn_ids, turn_rows,
                        ))
                    except (TypeError, ValueError) as exc:
                        if attributed_id is None:
                            block_all = True
                        else:
                            blocked_turn_ids.add(attributed_id)
                        rejected.append({
                            "rejected": True, "category": "invalid_relation_event",
                            "reason": str(exc), "source_turn_id": attributed_id,
                            "item": dict(item) if isinstance(item, Mapping) else repr(item),
                        })
                done_ids = set() if block_all else window_turn_ids - blocked_turn_ids
                db.mark_relation_judge_done(done_ids)
        return {
            "judged_turn_ids": sorted(done_ids),
            "origins": sorted({row["origin"] for row in written}),
            "edges": len(written),
            "written": written,
            "rejected": rejected,
        }
    finally:
        with _single_flight_lock:
            _in_flight.pop(key, None)


def _hydrate_turn(db: Any, row: Mapping[str, Any]) -> Dict[str, Any]:
    """窗口轮补对话原文：按 user/minister message id 取 chat_messages 内容。"""
    out = dict(row)
    out.setdefault("user_message", "")
    out.setdefault("minister_message", "")
    if not hasattr(db, "conn"):
        return out
    for key, column in (("user_message_id", "user_message"), ("minister_message_id", "minister_message")):
        mid = int(row.get(key) or 0)
        if mid > 0:
            mrow = db.conn.execute(
                "SELECT content FROM chat_messages WHERE id = ?", (mid,),
            ).fetchone()
            if mrow is not None:
                out[column] = str(mrow["content"])
    return out


def _live_window_turns(db: Any, window: List[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """写入前存活复查（ADR 0038 终结异步残余）：只认仍 active 且回话绑定的轮。"""
    live: List[Dict[str, Any]] = []
    for row in window:
        rrow = db.conn.execute(
            "SELECT status, minister_message_id FROM chat_turns WHERE id = ?",
            (int(row["id"]),),
        ).fetchone()
        if rrow is None:
            continue
        status = str(rrow["status"])
        mid = int(rrow["minister_message_id"] or 0)
        if status == "active" and mid > 0 and mid == int(row.get("minister_message_id") or 0):
            live.append(dict(row))
    return live
