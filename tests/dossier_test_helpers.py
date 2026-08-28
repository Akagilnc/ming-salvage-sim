# #1504 typed covert-task contract fixtures (applier-native 亩 / 实务事功).
TYPED_COVERT_TASK = {
    "kind": "清丈",
    "axes": ["实务事功"],
    "direction": 1,
    "delivery": {
        "unit": "亩", "target_units": 1.0,
        "region": "henan", "field": "registered_land", "target": "421",
    },
}
def create_test_secret_order(db, state, minister, title, content, tags, **kwargs):
    """Canonical neutral contract for tests whose behavior is unrelated to delivery semantics."""
    kwargs.setdefault("covert_task", TYPED_COVERT_TASK)
    return db.create_secret_order(state, minister, title, content, tags, **kwargs)


TYPED_COVERT_EXTRACT = {
    "差务": "清丈",
    "价值轴": ["实务事功"],
    "方向": 1,
    "交付单位": "亩",
    "交付目标": 1,
}


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


def promulgate_proposed_appointments(db, state, content):
    """测试经公共判决入口顺颁当前全部 proposed 任命案卷。

    物化只走 DB/content（registry=None）；需要 commit 后 agent refresh 的
    证明改经真实 settle_with_delta 外层入口，不保留平行旧路径。
    """
    # #657 §C.8：midzhi 亦不附 affected_parties（不猜派）。
    verdicts = [
        {"dossier_id": row["id"], "decision": "promulgated"}
        for row in db.list_decree_dossiers(status="proposed")
        if row["action_type"] == "appointment"
    ]
    db.apply_dossier_verdicts(state, verdicts, content=content)
