"""Structured dossier payloads for executable probe directives.

Probe decrees intentionally exercise the player month chain's narrative path.
Their stable probe identity is therefore an explicit narrative policy target;
the helper never reads or infers semantics from decree prose.
"""


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


class _ProbeDirective:
    """探针用的轻量草案视图（会话层 DirectiveView 已随手写入口退役而删）。"""

    __slots__ = ("id", "text", "status", "source", "notes")

    def __init__(self, directive_id: int, text: str, notes: str):
        self.id = directive_id
        self.text = text
        self.status = "draft"
        self.source = "手动新增"
        self.notes = notes


def add_narrative_probe_directive(
    session: object,
    text: str,
    *,
    probe_id: str,
    sequence: int = 1,
    notes: str = "",
) -> "_ProbeDirective":
    """Create one probe directive through the engine write seam.

    #1902：拟诏台手写入口退役，会话层 add_directive 随之删除；探针改走
    ``db.add_directive``（同一 turn_directives 表、同一 payload 形状），回一个
    与旧 DirectiveView 同形的轻量视图，各探针脚本的 ``view.id`` 用法不变。
    """
    directive_id = session.db.add_directive(
        session.state,
        None,
        text,
        "手动新增",
        notes=notes,
        dossier_payload=narrative_probe_dossier(probe_id, sequence),
    )
    return _ProbeDirective(directive_id, text, notes)
