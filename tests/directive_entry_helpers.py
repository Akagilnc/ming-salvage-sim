"""#1902：拟诏台手写入口退役后的测试数据准备。

这不是玩家现役入口。玩家拟旨只从召对来。抽取与投影走成案补交同一对核：
`extract_draft_intent_with_roster_heal` + `project_draft_extract_to_directive_payload`。
不在册以 `ValueError(fact)` 上抛，与 `resubmit_draft_admission_payload` 同形。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional


def live_draft_payload(
    text: str,
    llm_config: Any = None,
    *,
    existing_mode: object = None,
    db: Any = None,
    content: Any = None,
):
    """成案补交那条抽取核：抽取后投影。空载短路与异常降级包装已删。"""
    from ming_sim.cli_backend import (
        UnknownParticipantEscalate,
        extract_draft_intent_with_roster_heal,
        project_draft_extract_to_directive_payload,
    )

    directive_text = str(text or "").strip()
    prompt = f"请据此拟旨，并从以下已成旨文抽取结构，不得改写：\n{directive_text}"
    try:
        captured = extract_draft_intent_with_roster_heal(
            prompt,
            directive_text,
            llm_config=llm_config,
            db=db,
            content=content,
        )
    except UnknownParticipantEscalate as exc:
        raise ValueError(exc.fact) from exc
    return project_draft_extract_to_directive_payload(
        captured,
        decree_text=directive_text,
        existing_mode=existing_mode,
        db=db,
        content=content,
    )


def stage_draft_directive(
    session: Any,
    text: str,
    *,
    db: Any = None,
    content: Any = None,
    llm_config: Any = None,
    notes: str = "",
    dossier_payload: Any = None,
):
    """摆一条 draft。未给 payload 时经现役抽取核取结构，再落库。"""
    target_db = db if db is not None else getattr(session, "db", None)
    target_content = content if content is not None else getattr(session, "content", None)
    config = llm_config if llm_config is not None else getattr(session, "llm_config", None)
    payload = dossier_payload
    if payload is None:
        payload = live_draft_payload(
            text,
            config,
            db=target_db,
            content=target_content,
        )
    directive_id = target_db.add_directive(
        session.state, None, text, "手动新增", notes=notes, dossier_payload=payload,
    )
    return SimpleNamespace(id=directive_id, text=text, status="draft")


def stage_draft_directive_or_raise(session: Any, text: str, **kwargs) -> Optional[int]:
    """同 stage_draft_directive，但落库拒收（参与人不在册等）以 ValueError 上抛。"""
    return stage_draft_directive(session, text, **kwargs).id
