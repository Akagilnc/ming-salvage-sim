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
    db.record_dossier_decision(dossier["id"], decision)

    if decision == "promulgated":
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
        assert [x["动作"] for x in changes if not x.get("rejected")] == ["易主", "任命"]
        expected = ("ming", "游击将军", 50)
    else:
        expected = ("bandit_522", "张献忠流寇首领", 55)

    row = db.conn.execute(
        "SELECT power_id,office FROM characters WHERE name='张献忠'"
    ).fetchone()
    strength = db.conn.execute(
        "SELECT military_strength FROM powers WHERE id='bandit_522'"
    ).fetchone()["military_strength"]
    assert (row["power_id"], row["office"], strength) == expected


def test_pacification_rejects_dead_and_unknown_targets(game):
    db, _state, content = game
    _make_enemy(db, content)
    db.conn.execute("UPDATE characters SET status='dead' WHERE name='张献忠'")
    db.conn.commit()
    for target in ("张献忠", "并不存在的人"):
        with pytest.raises(ValueError, match="canonical target"):
            _stage_pacification(db, _state.turn, target)


def test_scripted_action_classes_are_mutually_exclusive(game):
    """#515 OWNER：锁结构化路由，不考真实 LLM 自然语言分类率。"""
    db, state, content = game
    _make_enemy(db, content)
    ctx = _stage_pacification(db, state.turn)
    payload = json.loads(db.list_pending_actions(state.turn)[0]["payload_json"])
    assert payload["dossier_action_type"] == "pacification"
    assert payload["target_id"] == "张献忠"

    # 既有兄弟 owner 的结构化种类不能被 pacification materializer 吞入。
    for kind in ("punishment", "military_order"):
        other = _ctx(db, ctx.character.name, [{"kind": kind, "target_id": "张献忠"}], state.turn)
        run_materialize_pipeline(other)
        assert "pending_action_id" not in other.out
    assert len([p for p in db.list_pending_actions(state.turn)
                if json.loads(p["payload_json"]).get("dossier_action_type") == "pacification"]) == 1
