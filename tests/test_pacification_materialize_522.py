"""#522 招抚：真实候选、案卷与既有 #190 人物变更纵切。"""

from types import SimpleNamespace
import json

import pytest

import ming_sim.action_materialize  # noqa: F401 -- installs package catalog
from ming_sim import issues
from ming_sim.action_clusters import candidates_from_classifier_payload
from tests.dossier_test_helpers import rejected_verdict as _rejected_verdict






def _activate_canonical_bandit(db, content, name="张献忠"):
    """Apply the production debut transition without rewriting power authority."""
    db.conn.execute("UPDATE characters SET status='active' WHERE name=?", (name,))
    content.characters[name].status = "active"
    db.conn.commit()


def _make_non_enemy(db, content, stance, name="张献忠", power_id="bandit_522"):
    db.conn.execute(
        """INSERT INTO powers
        (id,name,kind,leader,stance,leverage,satisfaction,military_strength,cohesion,
         supply,agenda,status,last_action,aliases)
        VALUES (?,?,'内乱',?,?,25,20,55,30,22,'招抚负向测试','小股啸聚','','[]')""",
        (power_id, "不可招抚测试股", name, stance),
    )
    db.conn.execute(
        "UPDATE characters SET power_id=?,status='active',office_type='外臣' WHERE name=?",
        (power_id, name),
    )
    ch = content.characters[name]
    ch.power_id, ch.status, ch.office_type = power_id, "active", "外臣"
    db.conn.commit()


def _prepare_ineligible_case(db, content, case):
    """Return (target, observe_person, observe_power_id) for one ineligible root."""
    if case == "foreign_enemy":
        return "皇太极", "皇太极", "houjin"
    if case == "same_faction_non_leader":
        db.conn.execute("UPDATE characters SET power_id='bandits' WHERE name='皇太极'")
        db.conn.commit()
        return "皇太极", "皇太极", "bandits"
    if case == "dead":
        _activate_canonical_bandit(db, content)
        db.conn.execute("UPDATE characters SET status='dead' WHERE name='张献忠'")
        db.conn.commit()
        return "张献忠", "张献忠", "bandit_zhang_xianzhong"
    if case == "unknown":
        _activate_canonical_bandit(db, content)
        return "并不存在的人", "张献忠", "bandit_zhang_xianzhong"
    if case in {"neutral", "pro_ming"}:
        stance = "中立" if case == "neutral" else "倾明"
        _make_non_enemy(db, content, stance)
        return "张献忠", "张献忠", "bandit_522"
    raise AssertionError(f"unknown ineligible case: {case}")














def _yi_zhu_item(name, origin, *, power_id):
    return {
        "name": name,
        "origin_ref": origin,
        "动作": "易主",
        "new_power": "ming",
        "方式": "主动归附",
        "反噬": {power_id: {"military_strength": -1, "reason": "受抚"}},
        "reason": "受抚归明",
    }










@pytest.mark.parametrize("target,accepted", [
    ("张献忠", True), ("八大王", True), ("不存在的人", False),
])
def test_translated_pacification_uses_canonical_target_or_rejects(game, target, accepted):
    from ming_sim.audience_night import open_night
    from ming_sim.audience_translate import normalize_audience_declaration
    from ming_sim.declaration_dispatch import dispatch_declaration

    db, state, content = game
    _activate_canonical_bandit(db, content)
    night = open_night(db, state)
    declaration = normalize_audience_declaration({"commissions": [{
        "text": "准予招抚。", "pacification": {"target_id": target},
    }]})
    result = dispatch_declaration(
        db, state, declaration, minister_name="殿上", night_id=int(night["id"]),
    )
    assert bool(result.commissions.applied) is accepted
    assert bool(result.commissions.rejected) is not accepted
    if accepted:
        row = db.conn.execute(
            "SELECT payload_json FROM pending_actions WHERE id=?",
            (result.commissions.applied[0]["id"],),
        ).fetchone()
        payload = json.loads(row["payload_json"])
        assert payload["dossier_action_type"] == "pacification"
        assert payload["target_id"] == "张献忠"
    else:
        assert not db.list_pending_actions(state.turn)














def test_special_decree_origin_cannot_authorize_pacification_allegiance(game):
    """C3：generic special_decree 不得授权招抚式易主。"""
    db, state, content = game
    _activate_canonical_bandit(db, content)
    before = dict(db.conn.execute(
        "SELECT power_id, office FROM characters WHERE name='张献忠'"
    ).fetchone())
    dossier_id = db.create_decree_dossier(
        state,
        action_type="special_decree",
        decree_text="着从权处置流寇。",
        target_kind="policy",
        target_id="narrative-special",
        payload={"mode": "ordinary", "text": "着从权处置流寇。"},
    )
    db.record_dossier_decision(dossier_id, "promulgated")
    db.transition_decree_dossier(dossier_id, "executing")
    applied = issues.apply_score_extraction(db, state, {"人物变更": [
        _yi_zhu_item("张献忠", f"dossier:{dossier_id}", power_id="bandit_zhang_xianzhong"),
    ]}, content=content)
    row = next(x for x in applied["applied_person_changes"] if x.get("name") == "张献忠")
    assert row.get("rejected")
    assert dict(db.conn.execute(
        "SELECT power_id, office FROM characters WHERE name='张献忠'"
    ).fetchone()) == before
