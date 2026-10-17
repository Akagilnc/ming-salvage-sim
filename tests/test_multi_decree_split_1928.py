from __future__ import annotations
"""#1928：一句话里的几道旨各自成条、各自判决身份。

Seams:
- dispatch_declaration（组合任免+拨帑 → 两条独立暂存）
- close_night 收夜成案 → decree_ref_for_dossier 独立身份
- apply_dossier_promulgation 分别准驳 → 批红只接待裁者
"""

import json

from ming_sim.audience_night import close_night, open_night
from ming_sim.declaration_dispatch import dispatch_declaration
from ming_sim.decree_forecast import decree_ref_for_dossier
from ming_sim.settlement.dossier import apply_dossier_promulgation
from tests.readback_helpers import active_character_name as _minister


def _person(db, content) -> str:
    if "洪承畴" in getattr(content, "characters", {}):
        row = db.conn.execute(
            "SELECT name FROM characters WHERE name=? LIMIT 1", ("洪承畴",),
        ).fetchone()
        if row is not None:
            return "洪承畴"
    return _minister(db)


def _region_id(db, preferred: str = "shaanxi") -> str:
    row = db.conn.execute(
        "SELECT id FROM regions WHERE id=? LIMIT 1", (preferred,),
    ).fetchone()
    if row is not None:
        return str(row["id"])
    row = db.conn.execute("SELECT id FROM regions LIMIT 1").fetchone()
    assert row is not None
    return str(row["id"])


def test_combined_appointment_and_grant_stage_two_independent_pendings(game):
    """任免+拨帑即便合在一条声明里，也落两条独立 pending，各有 kind。"""
    db, state, content = game
    person = _person(db, content)
    region = _region_id(db)
    before = db.conn.execute("SELECT COUNT(*) c FROM pending_actions").fetchone()["c"]
    text = f"任{person}为三边总督，再拨银三十万两给陕西"
    result = dispatch_declaration(
        db, state,
        {"commissions": [{
            "text": text,
            "appointment": {
                "name": person, "office": "三边总督", "appoint_action": "任命",
                "region_id": region,
            },
            "grant": {
                "grant_action": "赈灾", "amount": 30, "account": "国库",
                "target_kind": "region", "target_id": region,
                "execution_surface": "immediate",
            },
        }]},
        minister_name=_minister(db),
    )
    assert result.commissions.rejected == []
    assert len(result.commissions.applied) == 2
    after = db.conn.execute("SELECT COUNT(*) c FROM pending_actions").fetchone()["c"]
    assert after - before == 2
    kinds = sorted(
        r["kind"] for r in db.conn.execute(
            "SELECT kind FROM pending_actions WHERE status='pending' ORDER BY id"
        ).fetchall()
    )
    assert kinds == ["directive", "office"]
    by_kind = {
        r["kind"]: json.loads(r["payload_json"])
        for r in db.conn.execute(
            "SELECT kind, payload_json FROM pending_actions WHERE status='pending'"
        ).fetchall()
    }
    assert by_kind["office"]["name"] == person
    assert by_kind["office"]["office"] == "三边总督"
    assert "grant_action" not in by_kind["office"]
    assert by_kind["directive"]["grant_action"] == "赈灾"
    assert int(by_kind["directive"]["amount"]) == 30
    # 拨帑载荷不得再带任免动作，避免收夜合挂成案。
    assert str(by_kind["directive"].get("appoint_action") or "") == ""


def test_two_commissions_each_own_pending(game):
    """转译已拆两条时：任命一条、拨款一条，各自一条 pending。"""
    db, state, content = game
    person = _person(db, content)
    region = _region_id(db)
    result = dispatch_declaration(
        db, state,
        {"commissions": [
            {
                "text": f"任{person}为三边总督",
                "appointment": {
                    "name": person, "office": "三边总督", "appoint_action": "任命",
                    "region_id": region,
                },
            },
            {
                "text": "再拨银三十万两给陕西",
                "grant": {
                    "grant_action": "赈灾", "amount": 30, "account": "国库",
                    "target_kind": "region", "target_id": region,
                    "execution_surface": "immediate",
                },
            },
        ]},
        minister_name=_minister(db),
    )
    assert result.commissions.rejected == []
    assert len(result.commissions.applied) == 2
    kinds = sorted(a["kind"] for a in result.commissions.applied)
    assert kinds == ["directive", "office"]


def test_close_night_gives_independent_judgment_identities(game):
    """收夜后两案卷 pending_action_id 不同，decree_ref 各自独立。"""
    db, state, content = game
    person = _person(db, content)
    region = _region_id(db)
    open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(
        db.conn.execute(
            "SELECT id FROM audience_nights WHERE status='open' ORDER BY id DESC LIMIT 1"
        ).fetchone()["id"]
    )
    result = dispatch_declaration(
        db, state,
        {"commissions": [{
            "text": f"任{person}为三边总督，再拨银三十万两给陕西",
            "appointment": {
                "name": person, "office": "三边总督", "appoint_action": "任命",
                "region_id": region,
            },
            "grant": {
                "grant_action": "赈灾", "amount": 30, "account": "国库",
                "target_kind": "region", "target_id": region,
                "execution_surface": "immediate",
            },
        }]},
        minister_name=_minister(db),
        night_id=night_id,
    )
    pending_ids = [int(a["id"]) for a in result.commissions.applied]
    assert len(pending_ids) == 2
    for pid in pending_ids:
        db.conn.execute(
            "UPDATE pending_actions SET night_approved=1 WHERE id=?", (pid,),
        )
    db.conn.commit()
    close_night(db, state, content=content)

    dossiers = [
        dict(r) for r in db.conn.execute(
            "SELECT id, action_type, pending_action_id, status "
            "FROM decree_dossiers WHERE pending_action_id IN (?, ?) ORDER BY id",
            (pending_ids[0], pending_ids[1]),
        ).fetchall()
    ]
    types = {str(d["action_type"]) for d in dossiers}
    assert "appointment" in types and "grant_allocation" in types
    pending_by_type = {
        str(d["action_type"]): int(d["pending_action_id"]) for d in dossiers
    }
    assert pending_by_type["appointment"] != pending_by_type["grant_allocation"]
    refs = {
        str(d["action_type"]): decree_ref_for_dossier(db, dict(d))
        for d in dossiers
    }
    assert refs["appointment"] != refs["grant_allocation"]
    assert refs["appointment"].startswith("pending-action:")
    assert refs["grant_allocation"].startswith("pending-action:")


def test_reject_grant_only_appointment_lands_grant_enters_rescript(game):
    """外廷只打回拨款：任命落职；拨款进批红待裁；任命不进批红。"""
    db, state, content = game
    person = _person(db, content)
    region = _region_id(db)
    open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(
        db.conn.execute(
            "SELECT id FROM audience_nights WHERE status='open' ORDER BY id DESC LIMIT 1"
        ).fetchone()["id"]
    )
    result = dispatch_declaration(
        db, state,
        {"commissions": [{
            "text": f"任{person}为三边总督，再拨银三十万两给陕西",
            "appointment": {
                "name": person, "office": "三边总督", "appoint_action": "任命",
                "region_id": region,
            },
            "grant": {
                "grant_action": "赈灾", "amount": 30, "account": "国库",
                "target_kind": "region", "target_id": region,
                "execution_surface": "immediate",
            },
        }]},
        minister_name=_minister(db),
        night_id=night_id,
    )
    for a in result.commissions.applied:
        db.conn.execute(
            "UPDATE pending_actions SET night_approved=1 WHERE id=?",
            (int(a["id"]),),
        )
    db.conn.commit()
    close_night(db, state, content=content)

    appt = db.conn.execute(
        "SELECT id FROM decree_dossiers WHERE action_type='appointment' "
        "AND target_id=? ORDER BY id DESC LIMIT 1",
        (person,),
    ).fetchone()
    grant = db.conn.execute(
        "SELECT id FROM decree_dossiers WHERE action_type='grant_allocation' "
        "AND target_id=? ORDER BY id DESC LIMIT 1",
        (region,),
    ).fetchone()
    assert appt is not None and grant is not None
    appt_id, grant_id = int(appt["id"]), int(grant["id"])

    state.metrics["国库"] = max(int(state.metrics.get("国库") or 0), 100)
    db.reign.save_game_state(state)

    apply_dossier_promulgation(
        db, state, appt_id, decision="promulgated", content=content,
    )
    apply_dossier_promulgation(
        db, state, grant_id, decision="rejected",
        blocked_layer="six_offices", reason="库银不足", content=content,
    )

    char = db.conn.execute(
        "SELECT office FROM characters WHERE name=?", (person,),
    ).fetchone()
    assert "三边总督" in str(char["office"] or "")

    appt_row = db.dossiers.get(appt_id)
    grant_row = db.dossiers.get(grant_id)
    assert str(appt_row["promulgation_decision"] or "") == "promulgated"
    assert not bool(appt_row.get("rescript_pending"))
    assert str(grant_row["promulgation_decision"] or "") == "rejected"
    assert bool(grant_row.get("rescript_pending"))

    from ming_sim.decree import _rescript_decisions
    decisions = _rescript_decisions(
        [
            {"dossier_id": appt_id, "decision": "promulgated"},
            {
                "dossier_id": grant_id, "decision": "rejected",
                "reason": "库银不足", "primary_opponents": [],
            },
        ],
        [appt_row, grant_row],
    )
    decision_ids = {int(d["event_id"].split(":")[1]) for d in decisions}
    assert decision_ids == {grant_id}


def test_draft_plus_grant_same_money_still_one_pending_one_ledger(game):
    """#1777 不复发：拨银…卿即拟旨 仍一道拨款，一条 pending，国库只拨一次。"""
    db, state, content = game
    region = _region_id(db)
    open_night(db, state, location="乾清宫", time_of_day="夜")
    night_id = int(
        db.conn.execute(
            "SELECT id FROM audience_nights WHERE status='open' ORDER BY id DESC LIMIT 1"
        ).fetchone()["id"]
    )
    before = db.conn.execute("SELECT COUNT(*) c FROM pending_actions").fetchone()["c"]
    text = "拨银十五万两赈陕西，卿即拟旨"
    result = dispatch_declaration(
        db, state,
        {"commissions": [{
            "text": text,
            "grant": {
                "grant_action": "赈灾", "amount": 15, "account": "国库",
                "target_kind": "region", "target_id": region,
                "execution_surface": "immediate",
            },
        }]},
        minister_name=_minister(db),
        night_id=night_id,
    )
    assert result.commissions.rejected == []
    assert len(result.commissions.applied) == 1
    after = db.conn.execute("SELECT COUNT(*) c FROM pending_actions").fetchone()["c"]
    assert after - before == 1
    pid = int(result.commissions.applied[0]["id"])
    db.conn.execute(
        "UPDATE pending_actions SET night_approved=1 WHERE id=?", (pid,),
    )
    db.conn.commit()
    close_night(db, state, content=content)

    grant_rows = [
        dict(r) for r in db.conn.execute(
            "SELECT id, action_type FROM decree_dossiers WHERE pending_action_id=?",
            (pid,),
        ).fetchall()
    ]
    assert len(grant_rows) == 1
    assert grant_rows[0]["action_type"] == "grant_allocation"

    state.metrics["国库"] = max(int(state.metrics.get("国库") or 0), 100)
    db.reign.save_game_state(state)
    apply_dossier_promulgation(
        db, state, int(grant_rows[0]["id"]),
        decision="promulgated", content=content,
    )
    moves = db.conn.execute(
        "SELECT delta FROM economy_ledger WHERE account='国库' "
        "AND target_id=? AND delta < 0 ORDER BY id",
        (region,),
    ).fetchall()
    assert len(moves) == 1
    assert int(moves[0]["delta"]) == -15


def test_audience_translate_prompt_splits_multi_decree_not_same_money(game):
    """转译提示：多道旨各自成条；同笔拨款不拆拟旨/拨帑/交办。"""
    from ming_sim.audience_translate import build_audience_translate_prompt

    prompt = build_audience_translate_prompt(
        emperor_message="任洪承畴为总督，再拨银三十万",
        reply="臣遵旨。",
        night_said=[],
        pending_summaries=[],
    )
    assert "每道各自一条 commission" in prompt or "各自一条 commission" in prompt
    assert "只出一条 commission，载荷挂在同一条上" not in prompt
    assert "不要把同一笔银拆成拟旨" in prompt or "不要拆成拟旨" in prompt
