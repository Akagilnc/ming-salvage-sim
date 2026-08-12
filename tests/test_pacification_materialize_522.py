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


@pytest.mark.parametrize("target", ["李自成", "张献忠", "王嘉胤"])
def test_canonical_bandit_pacification_forms_proposed_dossier_without_world_effect(game, target):
    db, state, content = game
    _activate_canonical_bandit(db, content, target)
    before = dict(db.conn.execute(
        "SELECT power_id,office FROM characters WHERE name=?", (target,)
    ).fetchone())

    ctx = _stage_pacification(db, state.turn, target)
    assert ctx.out["pending_action_id"]
    db.commit_pending_actions(state, content=content)

    dossier = next(d for d in db.list_decree_dossiers(status="proposed")
                   if d["action_type"] == "pacification")
    assert dossier["target_id"] == target
    assert dict(db.conn.execute(
        "SELECT power_id,office FROM characters WHERE name=?", (target,)
    ).fetchone()) == before, "成案前不得在 materializer 改世界"


def test_old_save_legacy_bandits_leader_admits_wang(game):
    """旧档 leader='王嘉胤等' 经 init_schema 规范化后，canonical 头目可成案且零世界效果。"""
    db, state, content = game
    db.conn.execute("UPDATE powers SET leader='王嘉胤等' WHERE id='bandits'")
    db.conn.commit()

    db.init_schema()
    assert db.conn.execute(
        "SELECT leader FROM powers WHERE id='bandits'"
    ).fetchone()["leader"] == "王嘉胤"

    wang_before = dict(db.conn.execute(
        "SELECT power_id,office FROM characters WHERE name='王嘉胤'"
    ).fetchone())
    ctx = _stage_pacification(db, state.turn, "王嘉胤")
    assert ctx.out["pending_action_id"]
    db.commit_pending_actions(state, content=content)
    dossier = next(d for d in db.list_decree_dossiers(status="proposed")
                   if d["action_type"] == "pacification")
    assert dossier["target_id"] == "王嘉胤"
    assert dict(db.conn.execute(
        "SELECT power_id,office FROM characters WHERE name='王嘉胤'"
    ).fetchone()) == wang_before


@pytest.mark.parametrize(
    "case",
    [
        "foreign_enemy",
        "same_faction_non_leader",
        "dead",
        "unknown",
        "neutral",
        "pro_ming",
    ],
)
def test_pacification_rejects_ineligible_targets_without_world_effect(game, case):
    """真实入口→commit 失败→无案卷→观察人物/势力零世界效果；覆盖敌国/同股非首领/死亡/未知/中立/倾明。"""
    db, state, content = game
    target, person, power_id = _prepare_ineligible_case(db, content, case)
    person_before = dict(db.conn.execute(
        "SELECT * FROM characters WHERE name=?", (person,)
    ).fetchone())
    power_before = dict(db.conn.execute(
        "SELECT * FROM powers WHERE id=?", (power_id,)
    ).fetchone())

    ctx = _stage_pacification(db, state.turn, target)
    pending_id = ctx.out["pending_action_id"]
    assert pending_id
    assert db.commit_pending_actions(state, content=content) == []
    assert db.conn.execute(
        "SELECT status FROM pending_actions WHERE id=?", (pending_id,)
    ).fetchone()["status"] == "failed"
    assert not [d for d in db.list_decree_dossiers()
                if d["action_type"] == "pacification"]
    assert dict(db.conn.execute(
        "SELECT * FROM characters WHERE name=?", (person,)
    ).fetchone()) == person_before
    assert dict(db.conn.execute(
        "SELECT * FROM powers WHERE id=?", (power_id,)
    ).fetchone()) == power_before


@pytest.mark.parametrize("decision", ["rejected", "promulgated"])
def test_pacification_verdict_controls_existing_190_effect_path(game, decision):
    db, state, content = game
    _activate_canonical_bandit(db, content)
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
         "反噬": {"bandit_zhang_xianzhong": {"military_strength": -5, "reason": "受抚散众"}},
         "reason": "受抚归明"},
        {"name": "张献忠", "origin_ref": origin, "动作": "任命",
         "office": "游击将军", "reason": "旨授游击将军"},
    ]}, content=content)
    changes = [x for x in applied["applied_person_changes"] if x.get("name") == "张献忠"]
    accepted = [x["动作"] for x in changes if not x.get("rejected")]
    if decision == "promulgated":
        assert accepted == ["易主", "任命"]
        expected = ("ming", "游击将军", 19)
    else:
        assert accepted == []
        expected = ("bandit_zhang_xianzhong", "边兵,潜在流寇首领", 24)

    row = db.conn.execute(
        "SELECT power_id,office FROM characters WHERE name='张献忠'"
    ).fetchone()
    strength = db.conn.execute(
        "SELECT military_strength FROM powers WHERE id='bandit_zhang_xianzhong'"
    ).fetchone()["military_strength"]
    assert (row["power_id"], row["office"], strength) == expected


@pytest.mark.parametrize(
    ("classified", "draft_payload", "expected"),
    [
        ({"kind": "pacification", "target_id": "张献忠"}, None, "pacification"),
        ({"kind": "draft"}, {
            "dossier_action_type": "punishment", "target_kind": "character",
        }, "punishment"),
        ({"kind": "draft"}, {
            "dossier_action_type": "military_order", "target_kind": "region",
            "target_id": "shaanxi", "deadline_months": 3,
        }, "military_order"),
    ],
    ids=["pacification", "punishment", "military_order"],
)
def test_scripted_action_classes_are_mutually_exclusive(
    game, monkeypatch, classified, draft_payload, expected,
):
    """三类均由 #515 判词入口消费，并只交给本类既有 owner。"""
    db, state, content = game
    _activate_canonical_bandit(db, content)
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    payload = dict(draft_payload or {})
    payload.setdefault("target_id", actor)
    payload.setdefault("assignee", actor)
    monkeypatch.setattr(
        "ming_sim.cli_backend.extract_draft_intent",
        lambda *a, **k: {
            "draft_action": "拟旨", "draft_text": "脚本化旨稿",
            "target_candidate": "", **payload,
        },
    )
    candidates = candidates_from_classifier_payload(classified, soft=False)
    ctx = _ctx(db, actor, candidates, state.turn)
    run_materialize_pipeline(ctx)

    pending_id = ctx.out["pending_action_id"]
    pending_payload = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,)
    ).fetchone()["payload_json"])
    assert pending_payload["dossier_action_type"] == expected
    assert db.commit_pending_actions(state, content=content)
    produced = [d["action_type"] for d in db.list_decree_dossiers()]
    assert produced == [expected]
    assert all(produced.count(kind) == (1 if kind == expected else 0)
               for kind in ("pacification", "punishment", "military_order"))
