"""#628 credit write rail: cascade echoes must not invert 弃卒/包庇."""

from __future__ import annotations

from ming_sim.credit_events import KIND_BACK, KIND_SCAPEGOAT
from ming_sim.issues import apply_score_extraction


def _credit_edges(db, *, event_kind=None):
    sql = "SELECT * FROM relation_edge_events WHERE 1=1"
    params = []
    if event_kind is not None:
        sql += " AND event_kind=?"
        params.append(event_kind)
    sql += " ORDER BY id"
    return [dict(r) for r in db.conn.execute(sql, params).fetchall()]


def _executing_dossier(db, state, *, token: str, roster):
    did = db.create_decree_dossier(
        state,
        action_type="policy",
        decree_text=f"信用级联噪声·{token}",
        target_kind="issue",
        target_id=token,
        participants=roster,
    )
    db.apply_dossier_promulgation(state, did, "promulgated")
    return did


def _transformed_dossier(db, state, *, token: str, roster):
    did = _executing_dossier(db, state, token=token, roster=roster)
    db.record_dossier_execution(
        did, "transformed", f"名实已乖·{token}", int(state.turn),
        close=True, commit=True,
    )
    return did


def test_fanggui_reappointment_is_not_scapegoat(game):
    """下狱主办经任命级联放归：不得把派生 处置+offstage 当成惩卒而写弃卒保车。"""
    db, state, content = game
    roster = [
        {
            "character_id": "倪元璐", "tier": "主办", "role": "清丈",
            "delegator_id": "徐光启",
        },
        {"character_id": "徐光启", "tier": "协办", "role": "坐镇"},
    ]
    did = _transformed_dossier(db, state, token="fanggui-noise", roster=roster)
    db.set_character_status(state, "倪元璐", "imprisoned", "先已下狱", commit=True)

    before = len(_credit_edges(db, event_kind=KIND_SCAPEGOAT))
    applied = apply_score_extraction(
        db, state,
        {"人物变更": [{
            "name": "倪元璐", "动作": "任命",
            "office": "翰林院侍读", "office_type": "翰林院",
            "reason": "着即放归供职",
            "origin_ref": f"dossier:{did}",
        }]},
        content=content,
    )
    pcs = applied.get("applied_person_changes") or []
    assert any(
        isinstance(r, dict) and not r.get("rejected") and r.get("name") == "倪元璐"
        for r in pcs
    ), "放归任命本身须落格，否则本断言空壳"
    sg = [
        e for e in _credit_edges(db, event_kind=KIND_SCAPEGOAT)
        if f"dossier:{did}:credit:scapegoat" in str(e["origin"])
    ]
    assert sg == [], "放归级联不得写成弃卒保车"
    assert len(_credit_edges(db, event_kind=KIND_SCAPEGOAT)) == before


def test_displacement_echo_is_not_cover(game):
    """独占实职被顶替：派生 处置+active+被顶替 不得写成包庇撑腰。"""
    db, state, content = game
    db.conn.execute(
        "UPDATE characters SET office=?, office_type=?, status='active', "
        "power_id='ming', reason_code='' WHERE name=?",
        ("兵部尚书", "文官", "孙承宗"),
    )
    db.conn.commit()
    did = _transformed_dossier(
        db, state, token="displace-noise",
        roster=[{"character_id": "孙承宗", "tier": "主办", "role": "承办"}],
    )
    before = [
        e for e in _credit_edges(db, event_kind=KIND_BACK)
        if e["target"] == "孙承宗" and f"dossier:{did}:credit:cover" in str(e["origin"])
    ]
    applied = apply_score_extraction(
        db, state,
        {"人物变更": [{
            "name": "袁崇焕", "动作": "任命",
            "office": "兵部尚书", "office_type": "文官",
            "reason": "另简督师，承宗解兵柄",
            "origin_ref": f"dossier:{did}",
        }]},
        content=content,
    )
    pcs = applied.get("applied_person_changes") or []
    assert any(
        isinstance(r, dict)
        and not r.get("rejected")
        and r.get("name") == "袁崇焕"
        for r in pcs
    ), "顶替任命本身须落格，否则本断言空壳"
    cover = [
        e for e in _credit_edges(db, event_kind=KIND_BACK)
        if e["target"] == "孙承宗" and f"dossier:{did}:credit:cover" in str(e["origin"])
    ]
    assert cover == before, "被顶替派生行不得写成包庇撑腰"
