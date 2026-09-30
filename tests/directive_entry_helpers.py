"""#1902：拟诏台手写入口（CLI add/edit、Web POST|PATCH /api/directives）退役后的**测试数据准备**。

**这不是玩家现役入口。** 两端手拟新旨入口已退役，玩家拟旨只从召对来（#1772）；
仓内已无任何生产调用方走「手拟抽取 → 直接落 draft」这条链（`GameSession.add_directive`
/ `update_directive` 随之删，落库走引擎面 `db.add_directive`）。

仍在用的共享抽取核是 **成案准入补交** 那条：`session._resubmit_draft_admission_failures`
→ `cli_backend.resubmit_draft_admission_payload`（按旧代码名整删会打断现役准入补交，
故 `capture_manual_directive_payload` 作为其共用归一逻辑保留，非退役物）。

因此本模块只提供**旧草稿场景的直接数据库准备**：把一条 draft 摆到库里，好让测
抽取结构／属地／参与人／成案准入补交。调用点须自己说明是在准备旧稿数据，
禁把这里的准备动作当成玩家入口来宣称。
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
    """**测试数据准备**：经共享抽取核取结构，再落一条 draft。

    这是旧草稿场景的摆库动作，不是玩家入口（旧入口退役前等价 Web POST
    /api/directives）。要验玩家拟旨行为，须走召对话轮的真实落库路径。
    """
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
    """同 stage_draft_directive，但落库拒收（参与人不在册等）以 ValueError 上抛。"""
    return stage_draft_directive(session, text, **kwargs).id
