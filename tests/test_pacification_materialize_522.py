"""#522 招抚：真实候选、案卷与既有 #190 人物变更纵切。"""

from types import SimpleNamespace
import json

import pytest

import ming_sim.action_materialize  # noqa: F401 -- installs package catalog
from ming_sim import issues
from ming_sim.action_clusters import candidates_from_classifier_payload
from ming_sim.action_materialize import MaterializeCtx, run_materialize_pipeline


def _ctx(db, character, candidates, turn):
    return MaterializeCtx(
        session=SimpleNamespace(db=db, state=SimpleNamespace(turn=turn)),
        character=SimpleNamespace(name=character, office_type="文官"),
        player_message="招抚张献忠归顺朝廷。",
        reply="臣请招抚张献忠，归顺后授游击将军。",
        message_text="招抚张献忠归顺朝廷。",
        explicit_prefixed=False, has_directive=False, pend_for_minister=[], out={},
        intent=None, intent_kind="none", llm_config=None, intent_candidates=candidates,
    )


def _stage_pacification(db, turn, target="张献忠"):
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    candidate = candidates_from_classifier_payload(
        {"kind": "pacification", "target_id": target}, soft=False,
    )
    ctx = _ctx(db, actor, candidate, turn)
    run_materialize_pipeline(ctx)
    return ctx


def _rejected_verdict(dossier_id):
    return {
        "dossier_id": dossier_id, "decision": "rejected",
        "blocked_layer": "six_offices",
        "primary_opponents": [{"kind": "faction", "key": "东林"}],
        "gatekeeper_id": None, "reason": "科臣封驳。",
        "affected_parties": [{"kind": "faction", "key": "东林", "severity": "不满"}],
        "midzhi_unpromulgatable": False,
        "criteria_snapshot": {
            "imperial_authority_band": "偏弱", "involved_office_types": ["言官"],
            "authorization_ids": [], "endorsement_entry_ids": [],
        },
    }


def _make_enemy(db, content, name="张献忠", power_id="bandit_522"):
    db.conn.execute(
        """INSERT INTO powers
        (id,name,kind,leader,stance,leverage,satisfaction,military_strength,cohesion,
         supply,agenda,status,last_action,aliases)
        VALUES (?,?,'内乱',?,'敌对',25,20,55,30,22,'招抚纵切','小股啸聚','','[]')""",
        (power_id, "招抚纵切测试股", name),
    )
    db.conn.execute(
        "UPDATE characters SET power_id=?,status='active',office=?,office_type='外臣' WHERE name=?",
        (power_id, f"{name}流寇首领", name),
    )
    ch = content.characters[name]
    ch.power_id, ch.status, ch.office, ch.office_type = power_id, "active", f"{name}流寇首领", "外臣"
    db.conn.commit()


def test_enemy_pacification_forms_proposed_dossier_without_world_effect(game):
    db, state, content = game
    _make_enemy(db, content)
    before = dict(db.conn.execute(
        "SELECT power_id,office FROM characters WHERE name='张献忠'"
    ).fetchone())

    ctx = _stage_pacification(db, state.turn)
    assert ctx.out["pending_action_id"]
    db.commit_pending_actions(state, content=content)

    dossier = next(d for d in db.list_decree_dossiers(status="proposed")
                   if d["action_type"] == "pacification")
    assert dossier["target_id"] == "张献忠"
    assert dict(db.conn.execute(
        "SELECT power_id,office FROM characters WHERE name='张献忠'"
    ).fetchone()) == before, "成案前不得在 materializer 改世界"


@pytest.mark.parametrize("decision", ["rejected", "promulgated"])
def test_pacification_verdict_controls_existing_190_effect_path(game, decision):
    db, state, content = game
    _make_enemy(db, content)
    ctx = _stage_pacification(db, state.turn)
    db.commit_pending_actions(state, content=content)
    dossier = next(d for d in db.list_decree_dossiers(status="proposed")
                   if d["action_type"] == "pacification")
    verdict = ({"dossier_id": dossier["id"], "decision": "promulgated"}
               if decision == "promulgated" else _rejected_verdict(dossier["id"]))
    db.apply_dossier_verdicts(state, [verdict], content=content)

    origin = f"dossier:{dossier['id']}"
    applied = issues.apply_score_extraction(db, state, {"人物变更": [
        {"name": "张献忠", "origin_ref": origin, "动作": "易主",
         "new_power": "ming", "方式": "主动归附",
         "反噬": {"bandit_522": {"military_strength": -5, "reason": "受抚散众"}},
         "reason": "受抚归明"},
        {"name": "张献忠", "origin_ref": origin, "动作": "任命",
         "office": "游击将军", "reason": "旨授游击将军"},
    ]}, content=content)
    changes = [x for x in applied["applied_person_changes"] if x.get("name") == "张献忠"]
    accepted = [x["动作"] for x in changes if not x.get("rejected")]
    if decision == "promulgated":
        assert accepted == ["易主", "任命"]
        expected = ("ming", "游击将军", 50)
    else:
        assert accepted == []
        expected = ("bandit_522", "张献忠流寇首领", 55)

    row = db.conn.execute(
        "SELECT power_id,office FROM characters WHERE name='张献忠'"
    ).fetchone()
    strength = db.conn.execute(
        "SELECT military_strength FROM powers WHERE id='bandit_522'"
    ).fetchone()["military_strength"]
    assert (row["power_id"], row["office"], strength) == expected


@pytest.mark.parametrize(
    ("target", "mark_dead"),
    [("张献忠", True), ("并不存在的人", False)],
    ids=["dead", "unknown"],
)
def test_pacification_rejects_dead_and_unknown_targets(game, target, mark_dead):
    db, state, content = game
    _make_enemy(db, content)
    if mark_dead:
        db.conn.execute("UPDATE characters SET status='dead' WHERE name='张献忠'")
        db.conn.commit()
    person_before = dict(db.conn.execute(
        "SELECT power_id,status,office,office_type FROM characters WHERE name='张献忠'"
    ).fetchone())
    power_before = dict(db.conn.execute(
        "SELECT * FROM powers WHERE id='bandit_522'"
    ).fetchone())

    ctx = _stage_pacification(db, state.turn, target)
    pending_id = ctx.out["pending_action_id"]
    assert pending_id
    assert db.commit_pending_actions(state, content=content) == []

    pending = db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (pending_id,)
    ).fetchone()
    assert pending["status"] == "failed"
    assert not [d for d in db.list_decree_dossiers()
                if d["action_type"] == "pacification"]
    assert dict(db.conn.execute(
        "SELECT power_id,status,office,office_type FROM characters WHERE name='张献忠'"
    ).fetchone()) == person_before
    assert dict(db.conn.execute(
        "SELECT * FROM powers WHERE id='bandit_522'"
    ).fetchone()) == power_before


def test_scripted_action_classes_are_mutually_exclusive(game):
    """#515 OWNER：锁结构化路由，不考真实 LLM 自然语言分类率。"""
    db, state, content = game
    _make_enemy(db, content)
    ctx = _stage_pacification(db, state.turn)
    payload = json.loads(db.list_pending_actions(state.turn)[0]["payload_json"])
    assert payload["dossier_action_type"] == "pacification"
    assert payload["target_id"] == "张献忠"

    # 惩处由既有 dossier owner 成案，不借道 action-cluster classifier。
    punishment_id = db.create_decree_dossier(
        state, action_type="punishment", decree_text="命查其罪",
        target_kind="character", target_id="张献忠",
        executor_kind="character", executor_id=ctx.character.name,
    )
    punishment = db.get_decree_dossier(punishment_id)
    assert punishment["action_type"] == "punishment"

    # 军令由既有结构化旨稿 owner 成案，并保留合法承办人与外部旨稿。
    directive_id = db.add_directive(
        state, None, "命整军进剿", "脚本化判词", actor=ctx.character.name,
        dossier_payload={
            "dossier_action_type": "military_order",
            "target_kind": "region", "target_id": "shaanxi",
            "assignee": ctx.character.name, "deadline_months": 3,
        },
    )
    db.ensure_dossiers_for_draft_directives(state)
    directive = next(d for d in db.list_directives(state) if d["id"] == directive_id)
    military = db.get_dossier_for_directive(directive_id)
    assert json.loads(directive["dossier_payload_json"])["dossier_action_type"] == "military_order"
    assert military["action_type"] == "military_order"
    assert military["executor_id"] == ctx.character.name

    dossiers = db.list_decree_dossiers()
    assert {d["action_type"] for d in dossiers if d["id"] in {
        punishment_id, military["id"],
    }} == {"punishment", "military_order"}
    assert len([d for d in dossiers if d["action_type"] == "pacification"]) == 0
    assert len([p for p in db.list_pending_actions(state.turn)
                if json.loads(p["payload_json"]).get("dossier_action_type") == "pacification"]) == 1
