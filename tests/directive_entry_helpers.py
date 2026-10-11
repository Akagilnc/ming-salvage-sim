"""#1902：拟诏台手写入口退役后的测试数据准备。

这不是玩家现役入口，也不抽取。玩家拟旨只从召对来；抽取与拒收契约走
``resubmit_draft_admission_payload``。此处只把调用方给出的结构化 payload 落成 draft。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Mapping


def stage_draft_directive(
    session: Any,
    text: str,
    *,
    notes: str = "",
    dossier_payload: Mapping[str, Any],
):
    """摆一条 draft。结构必须由调用方显式给出，此处不抽取、不投影。"""
    if not isinstance(dossier_payload, Mapping) or not dossier_payload:
        raise TypeError("stage_draft_directive 须显式 dossier_payload")
    target_db = getattr(session, "db", None)
    directive_id = target_db.add_directive(
        session.state, None, text, "手动新增", notes=notes,
        dossier_payload=dict(dossier_payload),
    )
    return SimpleNamespace(id=directive_id, text=text, status="draft")
