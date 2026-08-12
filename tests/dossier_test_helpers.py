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
