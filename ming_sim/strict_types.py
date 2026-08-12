"""Shared strict scalar contracts for structured machine payloads."""

from ming_sim.appointment_tenure import APPOINTMENT_TENURES


def strict_int(raw: object, *, accept_numeric_strings: bool = True) -> int:
    """Reject bools/floats; optionally retain legacy acceptance of integer strings."""
    if isinstance(raw, bool) or isinstance(raw, float):
        raise ValueError("value must be an integer")
    if not accept_numeric_strings and not isinstance(raw, int):
        raise ValueError("value must be an integer")
    try:
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("value must be an integer") from exc


REJECTION_VERDICT_KEYS = frozenset({
    "dossier_id", "decision", "blocked_layer", "primary_opponents",
    "gatekeeper_id", "reason", "affected_parties", "criteria_snapshot",
    "midzhi_unpromulgatable", "legal_reason_code",
})
REJECTION_SNAPSHOT_KEYS = frozenset({
    "imperial_authority_band", "appointment_tenure",
    "authorization_ids", "endorsement_entry_ids",
})
IMPERIAL_AUTHORITY_BANDS = frozenset({"极弱", "偏弱", "中等", "偏强", "强盛"})


def validate_rejection_verdict(
    verdict: object,
    blocked_layers: object,
    *,
    faction_names: object,
    class_names: object,
    character_ids: object,
) -> None:
    """Validate the complete ADR 0066 shape against authoritative DB identities."""
    if not isinstance(verdict, dict):
        raise ValueError("打回判决须为对象")
    opponents = verdict.get("primary_opponents")
    snapshot = verdict.get("criteria_snapshot")
    string_list = lambda value: (isinstance(value, list) and all(
        isinstance(item, str) and bool(item.strip()) for item in value
    ))
    faction_opponents = (
        isinstance(opponents, list)
        and bool(opponents)
        and all(
            isinstance(item, dict)
            and set(item) == {"kind", "key"}
            and item.get("kind") == "faction"
            and isinstance(item.get("key"), str)
            and bool(item["key"].strip())
            and item["key"] in faction_names
            for item in opponents
        )
    )
    endorsement_ids = snapshot.get("endorsement_entry_ids") if isinstance(snapshot, dict) else None
    dossier_id = verdict.get("dossier_id")
    affected = verdict.get("affected_parties")
    typed_affected = (
        isinstance(affected, list)
        and all(
            isinstance(item, dict)
            and set(item) == {"kind", "key", "severity"}
            and item.get("kind") in {"faction", "class"}
            and isinstance(item.get("key"), str)
            and item["key"] in (
                faction_names if item.get("kind") == "faction" else class_names
            )
            and item.get("severity") in {"大怒", "不满"}
            for item in affected
        )
    )
    if (
        not set(verdict).issubset(REJECTION_VERDICT_KEYS)
        or isinstance(dossier_id, bool) or not isinstance(dossier_id, int) or dossier_id <= 0
        or ("midzhi_unpromulgatable" in verdict
            and not isinstance(verdict["midzhi_unpromulgatable"], bool))
        or ("legal_reason_code" in verdict
            and (not isinstance(verdict["legal_reason_code"], str)
                 or verdict["legal_reason_code"] != ""))
        or not typed_affected
        or verdict.get("blocked_layer") not in blocked_layers
        or not faction_opponents
        or "gatekeeper_id" not in verdict
        or (verdict.get("gatekeeper_id") is not None and
            (not isinstance(verdict["gatekeeper_id"], str)
             or not verdict["gatekeeper_id"].strip()
             or verdict["gatekeeper_id"] not in character_ids))
        or not isinstance(verdict.get("reason"), str) or not verdict["reason"].strip()
        or not isinstance(snapshot, dict) or set(snapshot) != REJECTION_SNAPSHOT_KEYS
        or snapshot.get("imperial_authority_band") not in IMPERIAL_AUTHORITY_BANDS
        or snapshot.get("appointment_tenure") not in APPOINTMENT_TENURES | {""}
        or not string_list(snapshot.get("authorization_ids"))
        or not isinstance(endorsement_ids, list)
        or any(isinstance(item, bool) or not isinstance(item, int) or item <= 0
               for item in endorsement_ids)
    ):
        raise ValueError("打回判决缺少关口、主否决方、缘由或完整 typed 判据快照")
