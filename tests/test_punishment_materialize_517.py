"""#517 惩处·宥赦：真实候选、案卷与 ADR 0055 判决后人物效果。

Seams:
- commit_pending_actions（收夜落案卷，不成效果）
- apply_dossier_verdicts（0055 顺颁才落机械效果）
- typed 惩处交办不经任免分类器（「拿问去职」不得折罢免）
- reload_state_from_db（只读 DB 无损接续）
"""

from __future__ import annotations

import inspect
import json
from types import SimpleNamespace

import pytest

import ming_sim.action_materialize  # noqa: F401 -- installs package catalog
import ming_sim.action_materialize as am
import web_app
from ming_sim.action_clusters import candidates_from_classifier_payload
from ming_sim.decree import reload_state_from_db
from ming_sim.models import CourtContext
from ming_sim.declaration_dispatch import dispatch_declaration
from tests.dossier_test_helpers import rejected_verdict as _rejected_verdict




def _active_ming(db, content, *, exclude=""):
    return next(
        ch for ch in content.characters.values()
        if getattr(ch, "office_type", "") not in ("后宫", "宗藩")
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
        and ch.name != exclude
        and str(getattr(ch, "office", "") or "").strip()
    )




def _close_night_dossier(db, state, content, pending_id):
    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    return next(
        d for d in db.list_decree_dossiers()
        if d["pending_action_id"] == pending_id
    )




@pytest.mark.parametrize("disposition", ["办人", "压下"])
def test_active_impeachment_disposition_flows_from_translation_to_dossier(game, disposition):
    """#660：转译声明的 typed 处置直达案卷；办人目标由声明选择而非 roster 顺序决定。"""
    db, state, content = game
    actor = _active_ming(db, content)
    first = _active_ming(db, content, exclude=actor.name)
    selected = next(
        ch for ch in content.characters.values()
        if ch.name not in {actor.name, first.name}
        and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
        and str(getattr(ch, "office", "") or "").strip()
    )
    faction = db.conn.execute("SELECT name FROM factions ORDER BY name LIMIT 1").fetchone()["name"]
    issue_id = db.insert_issue(
        state, kind="situation", title="御史发难", origin_kind="impeachment_surge",
        origin_ref="commitment:660:deformation_exposure", faction_hint=faction,
        target_roster=[first.name, selected.name],
    )
    from ming_sim.knowledge import build_character_knowledge

    knowledge = build_character_knowledge(db, state, actor.name)
    projected = next(row for row in knowledge["issues"] if row["id"] == issue_id)
    assert projected["target_roster"] == [first.name, selected.name]

    from ming_sim.audience_night import open_night
    from ming_sim.audience_translate import normalize_audience_declaration
    from ming_sim.declaration_dispatch import dispatch_declaration

    night = open_night(db, state)
    declaration = normalize_audience_declaration({"commissions": [{
        "text": "照此处置。",
        "punishment": {
            "punish_action": "拿问下狱" if disposition == "办人" else "无",
            "target_id": selected.name if disposition == "办人" else "",
            "issue_id": issue_id, "issue_disposition": disposition,
        },
    }]})
    result = dispatch_declaration(
        db, state, declaration, minister_name=actor.name, night_id=int(night["id"]),
    )
    assert result.commissions.rejected == []
    pending_id = result.commissions.applied[0]["id"]
    pending = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()["payload_json"])
    assert pending["text"] == "照此处置。"
    assert pending["issue_id"] == issue_id
    assert pending["issue_disposition"] == disposition
    assert pending["target_id"] == (selected.name if disposition == "办人" else str(issue_id))

    dossier = _close_night_dossier(db, state, content, pending_id)
    before_authority = state.metrics["皇威"]
    before_sat = db.faction_satisfaction(faction)
    db.apply_dossier_verdicts(
        state, [{"dossier_id": dossier["id"], "decision": "promulgated"}], content=content,
    )
    assert db.conn.execute("SELECT status FROM issues WHERE id=?", (issue_id,)).fetchone()["status"] == "resolved"
    assert db.get_character_status(selected.name)[0] == ("imprisoned" if disposition == "办人" else "active")
    assert db.get_character_status(first.name)[0] == "active"
    assert state.metrics["皇威"] == before_authority - (disposition == "压下")
    assert db.faction_satisfaction(faction) == before_sat - (disposition == "压下")


def test_impeachment_disposition_without_positive_issue_id_stages_nothing(game):
    db, state, content = game
    actor = _active_ming(db, content)
    target = _active_ming(db, content, exclude=actor.name)
    before = db.conn.execute("SELECT COUNT(*) FROM pending_actions").fetchone()[0]
    for malformed_id in (0, -1):
        db.conn.execute(
            "INSERT INTO issues(id,kind,title,origin_kind,origin_turn,target_roster) "
            "VALUES(?,?,?,?,?,?)",
            (malformed_id, "situation", "异常弹劾", "impeachment_surge", state.turn,
             json.dumps([target.name], ensure_ascii=False)),
        )

    for issue_id in (None, 0, -1):
        assert am.stage_punishment_candidate(
            db, state.turn, actor.name, text="照此处置。", target_id=target.name,
            punish_action="拿问下狱", issue_id=issue_id, issue_disposition="办人",
        ) == 0

    assert db.conn.execute("SELECT COUNT(*) FROM pending_actions").fetchone()[0] == before


@pytest.mark.parametrize(("disposition", "punish_action"), [
    ("办人", "廷杖"),
    ("压下", "拿问下狱"),
])
def test_impeachment_admission_rejects_noncanonical_action(
    game, disposition, punish_action,
):
    db, state, content = game
    actor = _active_ming(db, content)
    target = _active_ming(db, content, exclude=actor.name)

    pending_id = db.stage_directive_candidate(state.turn, actor.name, payload={
        "text": "照此处置。", "actor": actor.name,
        "dossier_action_type": "punishment", "target_id": target.name,
        "punish_action": punish_action, "issue_id": 1,
        "issue_disposition": disposition,
    })
    db.commit_pending_actions(state, content=content, action_ids=[pending_id])
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (pending_id,),
    ).fetchone()["status"] == "failed"
    assert not any(
        row["pending_action_id"] == pending_id for row in db.list_decree_dossiers()
    )


def test_prestaged_impeachment_punishments_skip_person_writes_after_first_closes_issue(game):
    """#660：同 issue 预暂存两案；首案结案后第二案在人物写前幂等返回。"""
    db, state, content = game
    actor = _active_ming(db, content)
    targets = [
        ch for ch in content.characters.values()
        if ch.name != actor.name and db.resolve_power_id(ch) == "ming"
        and db.get_character_status(ch.name)[0] == "active"
        and str(getattr(ch, "office", "") or "").strip()
    ][:2]
    issue_id = db.insert_issue(
        state, kind="situation", title="御史发难", origin_kind="impeachment_surge",
        origin_ref="commitment:660:prestage", target_roster=[ch.name for ch in targets],
    )
    dossiers = []
    for target in targets:
        pending_id = am.stage_punishment_candidate(
            db, state.turn, actor.name, text="照此处置。", target_id=target.name,
            punish_action="拿问下狱", issue_id=issue_id, issue_disposition="办人",
        )
        dossiers.append(_close_night_dossier(db, state, content, pending_id))
    db.apply_dossier_verdicts(state, [
        {"dossier_id": dossier["id"], "decision": "promulgated"} for dossier in dossiers
    ], content=content)
    assert db.get_character_status(targets[0].name)[0] == "imprisoned"
    assert db.get_character_status(targets[1].name)[0] == "active"
    assert db.conn.execute(
        "SELECT COUNT(*) FROM person_logs WHERE person_name=?",
        (targets[1].name,)
    ).fetchone()[0] == 0












def _scene_punishment(db, state, actor, target, *, category=""):
    result = dispatch_declaration(db, state, {"commissions": [{
        "text": f"臣请将{target.name}拿问下狱，请陛下定夺准驳。",
        "punishment": {"punish_action": "拿问下狱", "target_id": target.name,
                       "transaction_category": category},
    }]}, minister_name=actor.name)
    assert result.commissions.rejected == []
    return result.commissions.applied[0]["id"]


def test_scene_punishment_stages_then_close_night(game):
    """场景惩处暂存；收夜落案卷后 imprisoned 仍待判决。"""
    db, state, content = game
    actor = _active_ming(db, content)
    target = _active_ming(db, content, exclude=actor.name)
    pending_id = _scene_punishment(db, state, actor, target, category="缉拿")
    assert pending_id
    assert db.get_character_status(target.name)[0] == "active"
    dossier = _close_night_dossier(db, state, content, pending_id)
    assert dossier["action_type"] == "punishment"
    assert db.get_character_status(target.name)[0] == "active"
    db.apply_dossier_verdicts(
        state,
        [{"dossier_id": dossier["id"], "decision": "promulgated"}],
        content=content,
    )
    assert db.get_character_status(target.name)[0] == "imprisoned"


def test_scene_confirm_accept_does_not_imprison(game):
    """应允只过确认闸，不得在判决前落下狱。"""
    db, state, content = game
    actor = _active_ming(db, content)
    target = _active_ming(db, content, exclude=actor.name)
    pending_id = _scene_punishment(db, state, actor, target)
    approved = dispatch_declaration(db, state, {"promises": [{
        "action_id": pending_id, "decision": "应允",
    }]}, minister_name=actor.name)
    assert approved.promises.rejected == []
    assert approved.promises.applied[0]["action_id"] == pending_id
    assert db.get_character_status(target.name)[0] == "active"
    assert content.characters[target.name].status == "active"






def test_punishment_admission_rejects_missing_blank_or_illegal_action(game):
    """类2：admission 对缺失/空白/非法 punish_action 响亮拒绝。"""
    db, state, content = game
    target = _active_ming(db, content)
    base = {
        "text": f"将{target.name}拿问下狱。",
        "actor": target.name,
        "dossier_action_type": "punishment",
        "target_kind": "character",
        "target_id": target.name,
        "mode": "ordinary",
    }
    with pytest.raises(ValueError, match="punish_action"):
        db._normalize_directive_dossier_payload(
            dict(base), content=content, current_turn=state.turn,
        )
    with pytest.raises(ValueError, match="punish_action"):
        db._normalize_directive_dossier_payload(
            {**base, "punish_action": "   "},
            content=content, current_turn=state.turn,
        )
    with pytest.raises(ValueError, match="punish_action"):
        db._normalize_directive_dossier_payload(
            {**base, "punish_action": "抄家"},
            content=content, current_turn=state.turn,
        )
    ok = db._normalize_directive_dossier_payload(
        {**base, "punish_action": "拿问下狱"},
        content=content, current_turn=state.turn,
    )
    assert ok["punish_action"] == "拿问下狱"




# ── #517 r2 四类 ──────────────────────────────────────────────






def test_fine_admission_requires_positive_amount(game):
    """r2 类1：罚俸缺正数 amount 不得成案（normalize + stage 双缝）。"""
    db, state, content = game
    target = _active_ming(db, content)
    base = {
        "text": f"罚{target.name}俸银八十两。",
        "actor": target.name,
        "dossier_action_type": "punishment",
        "target_kind": "character",
        "target_id": target.name,
        "punish_action": "罚俸",
        "mode": "ordinary",
    }
    for bad in ({}, {"amount": 0}, {"amount": -8}, {"amount": "八十"}):
        with pytest.raises(ValueError, match="amount|罚俸"):
            db._normalize_directive_dossier_payload(
                {**base, **bad}, content=content, current_turn=state.turn,
            )

    ok = db._normalize_directive_dossier_payload(
        {**base, "amount": 80}, content=content, current_turn=state.turn,
    )
    assert ok["amount"] == 80

    # stage 缝：非法/缺额不得写入 pending
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    before = db.list_pending_actions(state.turn, minister_name=actor)
    for amount in (None, 0, -3, "坏"):
        pending_id = am.stage_punishment_candidate(
            db, state.turn, actor,
            text=f"罚{target.name}俸。",
            target_id=target.name,
            punish_action="罚俸",
            amount=amount,
        )
        assert pending_id == 0
    after = db.list_pending_actions(state.turn, minister_name=actor)
    assert len(after) == len(before)

    staged = am.stage_punishment_candidate(
        db, state.turn, actor,
        text=f"罚{target.name}俸银八十两。",
        target_id=target.name,
        punish_action="罚俸",
        amount=80,
    )
    assert staged > 0
    payload = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (staged,),
    ).fetchone()["payload_json"])
    assert payload["amount"] == 80






@pytest.mark.parametrize(
    ("action", "amount", "category", "admitted"),
    [
        ("拿问下狱", None, "缉拿", True),
        ("拿问下狱", None, "修仙", False),
        ("罚俸", 80, "", True),
        ("罚俸", None, "", False),
    ],
)
def test_declared_punishment_keeps_typed_admission(game, action, amount, category, admitted):
    """现役交办分派沿用惩处准入，不把不合法案降成泛用拟旨。"""
    from ming_sim.audience_night import open_night
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    target = _active_ming(db, content)
    night = open_night(db, state)
    punishment = {"target_id": target.name, "punish_action": action}
    if amount is not None:
        punishment["amount"] = amount
    if category:
        punishment["transaction_category"] = category
    before = {int(p["id"]) for p in db.list_pending_actions(state.turn)}
    result = dispatch_declaration(
        db, state, {"commissions": [{"text": "按惩处交办办理", "punishment": punishment}]},
        minister_name="", night_id=int(night["id"]),
    )
    new = [p for p in db.list_pending_actions(state.turn) if int(p["id"]) not in before]
    if admitted:
        assert len(result.commissions.applied) == len(new) == 1
        payload = json.loads(new[0]["payload_json"])
        assert payload["dossier_action_type"] == "punishment"
        assert payload["punish_action"] == action
        assert payload["target_id"] == target.name
        if amount is not None:
            assert int(payload["amount"]) == amount
    else:
        assert result.commissions.applied == []
        assert result.commissions.rejected
        assert new == []
