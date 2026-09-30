"""#1902：拟诏台手写入口（CLI add/edit、Web POST|PATCH /api/directives）退役后的拟旨夹具。

旧入口做的事只有两件：走共享抽取核 ``cli_backend.capture_manual_directive_payload``
拿结构，再落一条 draft。两端入口退役后，会话层的 ``GameSession.add_directive`` /
``update_directive`` 也随之零生产调用方而删，落库改走引擎面 ``db.add_directive``
（成案准入补交 ``session._resubmit_draft_admission_failures`` 仍用同一抽取核）。
本夹具即这两步的现役路径，被测契约（抽取结构／属地／参与人／准入补交）一条不少。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Optional


def stage_draft_directive(
    session: Any,
    text: str,
    *,
    db: Any = None,
    content: Any = None,
    llm_config: Any = None,
    notes: str = "",
):
    """共享抽取核 → 会话写入面，落一条 draft 旨意（等价旧 Web POST /api/directives）。"""
    from ming_sim.cli_backend import capture_manual_directive_payload

    target_db = db if db is not None else getattr(session, "db", None)
    target_content = content if content is not None else getattr(session, "content", None)
    config = llm_config if llm_config is not None else getattr(session, "llm_config", None)
    payload = capture_manual_directive_payload(
        text,
        config,
        **({"db": target_db, "content": target_content} if target_content is not None else {}),
    )
    directive_id = target_db.add_directive(
        session.state, None, text, "手动新增", notes=notes, dossier_payload=payload,
    )
    return SimpleNamespace(id=directive_id, text=text, status="draft")


def stage_draft_directive_or_raise(session: Any, text: str, **kwargs) -> Optional[int]:
    """同 stage_draft_directive，但业务拒收（参与人不在册等）以 ValueError 上抛。

    旧入口把它包成 HTTP 409；入口退役后调用方直接接 ValueError。
    """
    return stage_draft_directive(session, text, **kwargs).id
