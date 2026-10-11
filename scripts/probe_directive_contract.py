"""Structured dossier payloads for executable probe directives.

Probe decrees intentionally exercise the player month chain's narrative path.
Their stable probe identity is therefore an explicit narrative policy target;
the helper never reads or infers semantics from decree prose.
"""


from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - 仅供类型检查，运行时按需懒导入免循环
    from ming_sim.session import DirectiveView


def narrative_probe_dossier(probe_id: str, sequence: int = 1) -> dict[str, object]:
    probe = str(probe_id or "").strip()
    if not probe:
        raise ValueError("probe_id must be non-empty")
    index = int(sequence)
    if index <= 0:
        raise ValueError("probe directive sequence must be positive")
    return {
        "dossier_action_type": "policy",
        "target_kind": "issue",
        "target_id": f"probe:{probe}:{index}",
    }


def add_narrative_probe_directive(
    session: object,
    text: str,
    *,
    probe_id: str,
    sequence: int = 1,
    notes: str = "",
) -> "DirectiveView":
    """Create one probe directive through the engine write seam.

    #1902：拟诏台手写入口退役，会话层 add_directive 随之删除；探针改走
    ``db.issues.add_directive``（同一 turn_directives 表、同一 payload 形状）。返回
    会话层现役的 ``DirectiveView``（list_directives 的同一投影类型）——不另造
    同形视图，各探针脚本的 ``view.id`` 用法不变。
    """
    from ming_sim.session import DirectiveView

    directive_id = session.db.issues.add_directive(
        session.state.turn, session.state.year, session.state.period,
        None,
        text,
        "手动新增",
        notes=notes,
        dossier_payload=narrative_probe_dossier(probe_id, sequence),
    )
    return DirectiveView(
        id=directive_id, text=text, status="draft", source="手动新增", notes=notes,
    )
