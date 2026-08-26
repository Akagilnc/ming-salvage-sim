"""Shared strict scalar contracts for structured machine payloads."""

from ming_sim.appointment_tenure import APPOINTMENT_TENURES
from ming_sim.qualitative import POWER_BANDS


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
# Membership set derived from qualitative.POWER_BANDS (皇威/势力同词表).
IMPERIAL_AUTHORITY_BANDS = frozenset(POWER_BANDS)


def validate_affected_parties(
    affected: object, *, faction_names: object, class_names: object,
) -> None:
    """Validate typed signed reactions; extra explanatory keys remain allowed."""
    if not isinstance(affected, list) or not all(
        isinstance(item, dict)
        and {"kind", "key", "direction", "intensity"}.issubset(item)
        and item.get("kind") in {"faction", "class"}
        and isinstance(item.get("key"), str)
        and item["key"] in (faction_names if item.get("kind") == "faction" else class_names)
        and item.get("direction") in {"positive", "negative"}
        and item.get("intensity") in {"weak", "strong"}
        for item in affected
    ):
        raise ValueError("affected_parties 须为在册 typed signed 反应清单")


def validate_verdict_affected_parties(
    verdict: object, mode: str, *, faction_names: object, class_names: object,
) -> None:
    """Enforce the mode/decision reaction shape at every public verdict seam.

    #657 §C.8 later-wins：mode=midzhi 不猜/不强制 affected_parties（顺颁与打回皆然）；
    ordinary 打回仍须非空 typed 清单；ordinary 顺颁必须省略。
    """
    if not isinstance(verdict, dict):
        raise ValueError("案卷 verdict 须为对象")
    decision = verdict.get("decision")
    present = "affected_parties" in verdict
    if mode == "midzhi":
        # 中旨接缝不消费该字段；若 LLM 夹带则仅校验形状（下游剥离/不落库）。
        if present and verdict.get("affected_parties") not in (None, []):
            validate_affected_parties(
                verdict.get("affected_parties"),
                faction_names=faction_names, class_names=class_names,
            )
        return
    required = decision == "rejected"
    if required and (not present or not verdict.get("affected_parties")):
        raise ValueError("打回判决的 affected_parties 必须为非空 typed 清单")
    if not required and present:
        raise ValueError("普通顺颁判决必须省略 affected_parties")
    validate_affected_parties(
        verdict.get("affected_parties", []),
        faction_names=faction_names, class_names=class_names,
    )


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
    # 缺省/空清单在此过形状；ordinary 非空要求由 validate_verdict_affected_parties 承担。
    # midzhi 打回可无 affected_parties（#657 §C.8 不猜派）。
    affected = verdict.get("affected_parties", [])
    if affected is None:
        affected = []
    try:
        validate_affected_parties(
            affected, faction_names=faction_names, class_names=class_names,
        )
    except ValueError:
        typed_affected = False
    else:
        typed_affected = True
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
