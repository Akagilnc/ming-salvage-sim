def _cost_events(db, dossier_id):
    return [dict(row) for row in db.conn.execute(
        "SELECT * FROM decree_cost_events WHERE dossier_id=? ORDER BY id",
        (int(dossier_id),),
    ).fetchall()]


def _sat(db, table, name):
    return db.conn.execute(
        f"SELECT satisfaction FROM {table} WHERE name=? ORDER BY region_id LIMIT 1"
        if table == "classes" else f"SELECT satisfaction FROM {table} WHERE name=?",
        (name,),
    ).fetchone()[0]


def rejected_verdict(
    dossier_id,
    authority_band="偏弱",
    *,
    midzhi=False,
    gatekeeper_id=None,
    reason="科臣封驳。",
    intensity="weak",
):
    """Configurable rejected-verdict fixture shared by the four named duplicates.

    Preserves per-suite differences via kwargs; keeps the current typed
    direction/intensity reaction contract (not the retired severity shape).
    """
    verdict = {
        "dossier_id": dossier_id,
        "decision": "rejected",
        "blocked_layer": "six_offices",
        "primary_opponents": [{"kind": "faction", "key": "东林"}],
        "gatekeeper_id": gatekeeper_id,
        "reason": reason,
        "criteria_snapshot": {
            "imperial_authority_band": authority_band,
            "appointment_tenure": "",
            "authorization_ids": [],
            "endorsement_entry_ids": [],
        },
        "affected_parties": [
            {
                "kind": "faction", "key": "东林",
                "direction": "negative", "intensity": intensity,
            },
        ],
    }
    if midzhi:
        verdict["midzhi_unpromulgatable"] = True
    return verdict


def promulgate_proposed_appointments(db, state, content, registry=None):
    """测试经公共判决入口顺颁当前全部 proposed 任命案卷。"""
    verdicts = [
        {
            "dossier_id": row["id"], "decision": "promulgated",
            **({"affected_parties": [{
                "kind": "faction", "key": "皇党",
                "direction": "positive", "intensity": "weak",
            }]} if row["mode"] == "midzhi" else {}),
        }
        for row in db.list_decree_dossiers(status="proposed")
        if row["action_type"] == "appointment"
    ]
    db.apply_dossier_verdicts(
        state, verdicts, content=content, registry=registry,
    )
