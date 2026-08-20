"""召对夜内 P5 读心尾随（#499 / PRD #497 接缝义务②）。

读心依赖回话、必串于回话之后：回话先展示（done），读心在玩家阅读期由 chat_stream
worker 直接尾随生成（单一依赖任务，调用方随即等其结果——无需另起 executor/Future/
状态机）；就绪即经 SSE 浮现。后台 DB 写走 runtime write_gate（与月末并发 extractor /
后台召对 worker 同纪律）。不依赖回话输出的调用（动作意图分类等）由生产入口在各自
executor 上先于回话发出、跨越回话流式在飞、回话后消费一次。

本模块只提供纯函数（资格判定 + 完整读心尾随），不持有时序状态机。
"""

from __future__ import annotations

import threading
from typing import Any, Dict, Mapping, Optional


def mindreading_eligible(
    db: Any,
    content_characters: Mapping[str, Any],
    minister_name: str,
) -> Optional[str]:
    """若本轮可发读心，返回读心者姓名；否则 None。

    规则：存在唯一御前近臣位，且目标不是读心者本人。
    """
    from ming_sim.mindreading import current_inner_court_attendant_name

    reader = current_inner_court_attendant_name(db)
    if not reader:
        return None
    if reader == minister_name:
        return None
    if reader not in content_characters:
        return None
    if minister_name not in content_characters:
        return None
    return reader


def run_mindreading_for_turn(
    *,
    db: Any,
    state: Any,
    content_characters: Mapping[str, Any],
    minister_name: str,
    minister_reply: str,
    llm_config: Any,
    chat_turn_id: int,
    write_gate: threading.Lock,
    mindreading_agent: Any = None,
) -> Optional[Dict[str, Any]]:
    """完整读心尾随：资格判定 → 组材料 → 调模型 → 写库。失败上抛，不回滚回话。

    `write_gate` 必传：写库须走真实 runtime 写锁（与月末并发 extractor / 其它端点写同一把）。
    不设「临时新锁」回退——新锁与谁都不互斥，串行不了任何并发写。
    """
    from ming_sim.mindreading import (
        build_mindreading_materials,
        generate_mindreading_payload,
    )

    # 唯一资格判定入口（外层不再重复查询）
    reader_name = mindreading_eligible(db, content_characters, minister_name)
    if reader_name is None:
        return None
    reader = content_characters[reader_name]
    target = content_characters[minister_name]
    materials = build_mindreading_materials(
        db, state, reader, target, minister_reply,
    )
    payload = generate_mindreading_payload(
        materials, llm_config, mindreading_agent=mindreading_agent,
    )
    # #1474：空返回 = 无真增量缺席，不落库、不投递
    if not payload:
        return None
    if chat_turn_id:
        with write_gate:
            # 撤回安全（ADR 0038）：写前校验目标轮仍存活；failed/undone 不写孤儿，
            # 也不向玩家投递未落库的孤儿读心（无稳定记录身份 → 返 None）。
            if hasattr(db, "conn"):
                row = db.conn.execute(
                    "SELECT status FROM chat_turns WHERE id=?",
                    (int(chat_turn_id),),
                ).fetchone()
                if row is not None:
                    status = str(row["status"] if hasattr(row, "keys") else row[0] or "")
                    if status in {"failed", "undone"}:
                        return None
            record_id = db.record_mindreading(int(chat_turn_id), payload)
            # 附上持久记录身份，供 SSE 投递与前端 (chat_turn_id, id) 去重/归位。
            payload = {**payload, "id": int(record_id)}
    return payload
