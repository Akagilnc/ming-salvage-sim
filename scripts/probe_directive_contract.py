"""Structured dossier payloads for executable probe directives.

Probe decrees intentionally exercise narrative simulator/extractor behavior.
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


def add_narrative_probe_directive(
    session: object,
    text: str,
    *,
    probe_id: str,
    sequence: int = 1,
    notes: str = "",
) -> object:
    """Create one probe directive through GameSession's strict public seam."""
    return session.add_directive(
        text,
        notes=notes,
        dossier_payload=narrative_probe_dossier(probe_id, sequence),
    )
