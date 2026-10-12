# #1504 typed covert-task contract fixtures (applier-native 万亩 / 实务事功).

TYPED_COVERT_TASK = {
    "kind": "清丈",
    "axes": ["实务事功"],
    "direction": 1,
    "delivery": {
        "unit": "万亩", "target_units": 1.0, "effect_sign": 1,
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
    "交付单位": "万亩",
    "交付目标": 1,
    "效果符号": 1,
    "地区": "henan",
    "地区字段": "registered_land",
    "地区目标值": "421",
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
    外层月链验证由玩家过月测试承担，不在此另写平行路径。
    """
    # #657 §C.8：midzhi 亦不附 affected_parties（不猜派）。
    verdicts = [
        {"dossier_id": row["id"], "decision": "promulgated"}
        for row in db.dossiers.list_dossiers(status="proposed")
        if row["action_type"] == "appointment"
    ]
    apply_dossier_verdicts(db, state, verdicts, content=content)

def promulgated_policy_origin(db, state, token: str) -> str:
    """已颁布案卷的 origin_ref（``new_issues`` 承诺项须有合法 decree 来源）。

    案卷只用作来源锚，调用方不依赖它的执行面，故只颁布不推进。
    """
    dossier_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=f"分段承诺：{token}",
        target_kind="issue",
        target_id=token,
        payload={"token": token},
    )
    assert dossier_id > 0
    db.dossiers.record_dossier_decision(dossier_id, "promulgated")
    return f"dossier:{dossier_id}"

def create_issue_with_effect(db, state, title: str, effect: dict, *, content=None):
    """Create a policy issue through the live tracker, anchored to a promulgated dossier."""
    from ming_sim.entities.issue.tracker import apply_issue_tracker_output

    origin = promulgated_policy_origin(db, state, title)
    created = apply_issue_tracker_output(db, state, {"new_issues": [{
        "origin_kind": "decree", "origin_ref": origin, "title": title,
        "kind": "initiative", "effect_on_resolve": effect,
    }]}, content=content)
    return created["new_issues"][0]["issue_id"]

def close_issue_with_effect(db, state, title: str, effect: dict, *, content=None):
    """Resolve the policy issue; callers testing a close failure use its creation seam."""
    from ming_sim.entities.issue.tracker import apply_issue_tracker_output

    issue_id = create_issue_with_effect(db, state, title, effect, content=content)
    return apply_issue_tracker_output(db, state, {
        "close_issues": [{"issue_id": issue_id, "reason": "resolved"}],
    }, content=content)

def executing_owned_policy(db, state, *, token: str, holder: str = ""):
    if not holder:
        holder = ming_character_name(db)
    dossier_id = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=f"清丈差务·{token}",
        target_kind="issue",
        target_id=token,
        executor_kind="character",
        executor_id=holder,
        participants=[
            {"character_id": holder, "tier": "主办", "role": "清丈"},
        ],
        payload={"mode": "ordinary", "text": token},
    )
    apply_dossier_promulgation(db, state, dossier_id, "promulgated")
    assert db.dossiers.get(dossier_id)["status"] == "executing"
    return dossier_id, holder

def executing_rostered_policy(db, state, *, token: str, roster=None, decree_text=None):
    """复用信用写端的执行前置，调用方保留真实旨文和责任人名册。"""
    if roster is None:
        roster = [
            {"character_id": "倪元璐", "tier": "主办", "role": "清丈"},
        ]
    did = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=decree_text if decree_text is not None else f"信用写端·{token}",
        target_kind="issue",
        target_id=token,
        participants=roster,
    )
    apply_dossier_promulgation(db, state, did, "promulgated")
    assert db.dossiers.get(did)["status"] == "executing"
    return did

def executing_staged_policy(db, state, *, token: str, host: str = "倪元璐"):
    return executing_rostered_policy(
        db, state, token=token, decree_text=f"清丈差务·{token}",
        roster=[
            {"character_id": host, "tier": "主办", "role": "清丈"},
            {"character_id": "徐光启", "tier": "协办", "role": "坐镇"},
        ],
    )

def subject_policy_dossier(
    db, state, *, owner: str, token: str = "subj", decree_text=None,
):
    did = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=decree_text if decree_text is not None else f"清丈{token}",
        target_kind="issue",
        target_id=f"land-{token}",
        executor_kind="character",
        executor_id=owner,
        participants=[{"character_id": owner, "tier": "主办"}],
    )
    apply_dossier_promulgation(db, state, did, "promulgated")
    return did

def executing_subject_policy(
    db, state, *, owner: str, token: str = "subj", decree_text=None,
):
    did = subject_policy_dossier(
        db, state, owner=owner, token=token, decree_text=decree_text,
    )
    db.conn.execute(
        "UPDATE decree_dossiers SET status='executing' WHERE id=?", (did,),
    )
    db.conn.commit()
    return did

def audit_policy_dossier(
    db, state, *, auditor: str, subject_id: int, token: str = "audit", note=None,
):
    """稽核方案卷（新 id）→ 稽核 → 被稽案卷（旧 id）。须后建以保证 id 更大。"""
    aid = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=f"稽核{token}",
        target_kind="issue",
        target_id=f"audit-{token}",
        executor_kind="character",
        executor_id=auditor,
        participants=[{"character_id": auditor, "tier": "主办"}],
    )
    apply_dossier_promulgation(db, state, aid, "promulgated")
    db.dossiers.add_links(aid, [{
        "target_dossier_id": int(subject_id),
        "relation_type": SUPERVISION_RELATION,
        "note": note if note is not None else f"稽核案卷{subject_id}",
    }])
    return aid

def recorded_executing_policy(
    db, state, decree_text="兴修水利", *, target_kind="issue", target_id="origin-558",
):
    dossier_id = db.create_decree_dossier(
        state, action_type="policy", decree_text=decree_text,
        target_kind=target_kind, target_id=target_id,
    )
    db.dossiers.record_dossier_decision(dossier_id, "promulgated")
    db.dossiers.transition(dossier_id, "executing")
    return dossier_id

from ming_sim.supervision import SUPERVISION_RELATION

from tests.readback_helpers import ming_character_name

from ming_sim.settlement.dossier import apply_dossier_promulgation, apply_dossier_verdicts
