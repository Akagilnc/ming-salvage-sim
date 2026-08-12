from ming_sim.strict_types import REJECTION_SNAPSHOT_KEYS


_REJECTION_SNAPSHOT_DEFAULTS = {
    "imperial_authority_band": "偏弱",
    "appointment_tenure": "",
    "authorization_ids": [],
    "endorsement_entry_ids": [],
}


def rejected_verdict(dossier_id, authority_band="偏弱", *, midzhi=False):
    """构造与生产 typed contract 同形的打回判决，避免测试快照各自漂移。"""
    snapshot_values = {
        **_REJECTION_SNAPSHOT_DEFAULTS,
        "imperial_authority_band": authority_band,
    }
    assert REJECTION_SNAPSHOT_KEYS <= snapshot_values.keys()
    verdict = {
        "dossier_id": dossier_id,
        "decision": "rejected",
        "blocked_layer": "six_offices",
        "primary_opponents": [{"kind": "faction", "key": "东林"}],
        "gatekeeper_id": None,
        "reason": "科臣封驳。",
        "criteria_snapshot": {
            key: snapshot_values[key] for key in REJECTION_SNAPSHOT_KEYS
        },
        "affected_parties": [
            {"kind": "faction", "key": "东林", "severity": "不满"},
        ],
    }
    if midzhi:
        verdict["midzhi_unpromulgatable"] = True
    return verdict


def promulgate_proposed_appointments(db, state, content, registry=None):
    """测试经公共判决入口顺颁当前全部 proposed 任命案卷。"""
    verdicts = [
        {"dossier_id": row["id"], "decision": "promulgated"}
        for row in db.list_decree_dossiers(status="proposed")
        if row["action_type"] == "appointment"
    ]
    db.apply_dossier_verdicts(
        state, verdicts, content=content, registry=registry,
    )
