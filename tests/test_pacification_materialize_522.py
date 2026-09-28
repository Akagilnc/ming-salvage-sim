"""#522 招抚：真实候选、案卷与既有 #190 人物变更纵切。"""

from types import SimpleNamespace
import json

import pytest

import ming_sim.action_materialize  # noqa: F401 -- installs package catalog
from ming_sim import issues
from ming_sim.action_clusters import candidates_from_classifier_payload
from ming_sim.action_materialize import MaterializeCtx, run_materialize_pipeline
from tests.dossier_test_helpers import rejected_verdict as _rejected_verdict


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
    """顺颁经 ADR 0055 物化接缝自动交 #190 易主；打回零效果。不得手工注入人物变更。"""
    db, state, content = game
    _activate_canonical_bandit(db, content)
    before = dict(db.conn.execute(
        "SELECT power_id, office FROM characters WHERE name='张献忠'"
    ).fetchone())
    power_before = dict(db.conn.execute(
        "SELECT * FROM powers WHERE id='bandit_zhang_xianzhong'"
    ).fetchone())
    ctx = _stage_pacification(db, state.turn)
    db.commit_pending_actions(state, content=content)
    dossier = next(d for d in db.list_decree_dossiers(status="proposed")
                   if d["action_type"] == "pacification")
    verdict = ({"dossier_id": dossier["id"], "decision": "promulgated"}
               if decision == "promulgated" else _rejected_verdict(dossier["id"]))
    db.apply_dossier_verdicts(state, [verdict], content=content)

    row = db.conn.execute(
        "SELECT power_id, office FROM characters WHERE name='张献忠'"
    ).fetchone()
    power_after = dict(db.conn.execute(
        "SELECT * FROM powers WHERE id='bandit_zhang_xianzhong'"
    ).fetchone())
    if decision == "promulgated":
        assert row["power_id"] == "ming"
        assert row["office"] == "归附"
        # 顺颁反噬须按 #190 给目标原势力真实失方削弱并落账（非空对象）。
        assert power_after["id"] == power_before["id"]
        expected_strength = max(0, int(power_before["military_strength"]) - 1)
        assert int(power_after["military_strength"]) == expected_strength
        log = db.conn.execute(
            "SELECT field, delta, reason, origin_ref FROM power_logs "
            "WHERE power_id=? AND field='military_strength' "
            "ORDER BY id DESC LIMIT 1",
            ("bandit_zhang_xianzhong",),
        ).fetchone()
        assert log is not None
        assert int(log["delta"]) == expected_strength - int(power_before["military_strength"])
        assert "受抚" in str(log["reason"] or "")
        assert str(log["origin_ref"] or "").startswith("dossier:")
    else:
        assert dict(row) == before
        assert power_after == power_before


@pytest.mark.parametrize(
    ("classified", "draft_payload", "expected"),
    [
        ({"kind": "pacification", "target_id": "张献忠"}, None, "pacification"),
        ({"kind": "draft"}, {
            "dossier_action_type": "punishment", "target_kind": "character",
            "punish_action": "拿问下狱",
        }, "punishment"),
        ({"kind": "draft"}, {
            "dossier_action_type": "military_order", "target_kind": "army",
            "target_id": "guanning", "deadline_months": 3,
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


def _promulgate_pacification(db, state, content, target="张献忠"):
    _activate_canonical_bandit(db, content, target)
    ctx = _stage_pacification(db, state.turn, target)
    db.commit_pending_actions(state, content=content)
    dossier = next(
        d for d in db.list_decree_dossiers(status="proposed")
        if d["action_type"] == "pacification" and d["target_id"] == target
    )
    db.apply_dossier_verdicts(
        state, [{"dossier_id": dossier["id"], "decision": "promulgated"}], content=content,
    )
    return dossier


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


def test_pacification_effect_rejects_mismatched_target_binds_canonical(game):
    """C1：招抚案卷只可易主 canonical target；顺颁自动易主绑定 target，错配拒、其它 origin 不变。"""
    db, state, content = game
    _activate_canonical_bandit(db, content, "李自成")
    li_before = dict(db.conn.execute(
        "SELECT power_id, office FROM characters WHERE name='李自成'"
    ).fetchone())
    zhang_before = dict(db.conn.execute(
        "SELECT power_id, office FROM characters WHERE name='张献忠'"
    ).fetchone())
    assert zhang_before["power_id"] != "ming"

    dossier = _promulgate_pacification(db, state, content, "张献忠")
    origin = f"dossier:{dossier['id']}"

    # 顺颁自动物化：仅 canonical target 易主
    assert db.conn.execute(
        "SELECT power_id FROM characters WHERE name='张献忠'"
    ).fetchone()["power_id"] == "ming"
    assert dict(db.conn.execute(
        "SELECT power_id, office FROM characters WHERE name='李自成'"
    ).fetchone()) == li_before

    crossed = issues.apply_score_extraction(db, state, {"人物变更": [
        _yi_zhu_item("李自成", origin, power_id="bandit_li_zicheng"),
    ]}, content=content)
    crossed_row = next(
        x for x in crossed["applied_person_changes"] if x.get("name") == "李自成"
    )
    assert crossed_row.get("rejected"), "错配目标不得借招抚案卷易主"
    assert dict(db.conn.execute(
        "SELECT power_id, office FROM characters WHERE name='李自成'"
    ).fetchone()) == li_before

    # 盘面自发仍可走既有 #190 路径（非案卷 origin 不受本绑定约束）
    _activate_canonical_bandit(db, content, "李自成")
    db.conn.execute(
        "UPDATE characters SET power_id='bandit_li_zicheng', office='流寇首领' WHERE name='李自成'"
    )
    db.conn.commit()
    content.characters["李自成"].power_id = "bandit_li_zicheng"
    spontaneous = issues.apply_score_extraction(db, state, {"人物变更": [
        _yi_zhu_item("李自成", "盘面自发", power_id="bandit_li_zicheng"),
    ]}, content=content)
    spont_row = next(
        x for x in spontaneous["applied_person_changes"] if x.get("name") == "李自成"
    )
    assert not spont_row.get("rejected")


@pytest.mark.parametrize(
    ("player_message", "intent_mode", "expected_mode"),
    [
        ("中旨直发招抚张献忠归顺朝廷。", "midzhi", "midzhi"),
        ("招抚张献忠归顺朝廷。", None, "ordinary"),
        ("招抚张献忠归顺朝廷。", "midzhi", "midzhi"),
    ],
    ids=["typed_midzhi", "ordinary_default", "classifier_mode"],
)
def test_pacification_preserves_declared_mode(game, player_message, intent_mode, expected_mode):
    """C2：招抚候选保留 classifier 的 typed 颁布方式。"""
    db, state, content = game
    _activate_canonical_bandit(db, content)
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    raw = {"kind": "pacification", "target_id": "张献忠"}
    if intent_mode is not None:
        raw["mode"] = intent_mode
    candidates = candidates_from_classifier_payload(raw, soft=False)
    ctx = MaterializeCtx(
        session=SimpleNamespace(db=db, state=SimpleNamespace(turn=state.turn)),
        character=SimpleNamespace(name=actor, office_type="文官"),
        player_message=player_message,
        reply="臣请招抚张献忠，归顺后授游击将军。",
        message_text=player_message,
        explicit_prefixed=False, has_directive=False, pend_for_minister=[], out={},
        intent=None, intent_kind="none", llm_config=None, intent_candidates=candidates,
    )
    run_materialize_pipeline(ctx)
    pending_id = ctx.out["pending_action_id"]
    payload = json.loads(db.conn.execute(
        "SELECT payload_json FROM pending_actions WHERE id=?", (pending_id,)
    ).fetchone()["payload_json"])
    assert payload.get("mode") == expected_mode
    assert db.commit_pending_actions(state, content=content)
    dossier = next(d for d in db.list_decree_dossiers() if d["action_type"] == "pacification")
    assert dossier["mode"] == expected_mode


def test_pacification_update_preserves_existing_mode(game):
    """C2/C4：同目标修订保留既有 mode，不因补充句无声明而掉 ordinary。"""
    db, state, content = game
    _activate_canonical_bandit(db, content)
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]
    first = candidates_from_classifier_payload(
        {"kind": "pacification", "target_id": "张献忠", "mode": "midzhi"}, soft=False,
    )
    ctx1 = MaterializeCtx(
        session=SimpleNamespace(db=db, state=SimpleNamespace(turn=state.turn)),
        character=SimpleNamespace(name=actor, office_type="文官"),
        player_message="中旨直发招抚张献忠。",
        reply="臣请招抚张献忠。",
        message_text="中旨直发招抚张献忠。",
        explicit_prefixed=False, has_directive=False, pend_for_minister=[], out={},
        intent=None, intent_kind="none", llm_config=None, intent_candidates=first,
    )
    run_materialize_pipeline(ctx1)
    pending_id = ctx1.out["pending_action_id"]
    pending_row = db.conn.execute(
        "SELECT id, payload_json, kind, minister_name FROM pending_actions WHERE id=?",
        (pending_id,),
    ).fetchone()
    pend = [dict(pending_row)]
    second = candidates_from_classifier_payload(
        {"kind": "pacification", "target_id": "张献忠"}, soft=False,
    )
    ctx2 = MaterializeCtx(
        session=SimpleNamespace(db=db, state=SimpleNamespace(turn=state.turn)),
        character=SimpleNamespace(name=actor, office_type="文官"),
        player_message="再补：授游击将军。",
        reply="臣再请授游击将军。",
        message_text="再补：授游击将军。",
        explicit_prefixed=False, has_directive=False, pend_for_minister=pend, out={},
        intent=None, intent_kind="none", llm_config=None, intent_candidates=second,
    )
    run_materialize_pipeline(ctx2)
    rows = [
        r for r in db.list_pending_actions(state.turn, minister_name=actor)
        if r["kind"] == "directive"
    ]
    assert len(rows) == 1
    assert int(rows[0]["id"]) == int(pending_id)
    payload = json.loads(rows[0]["payload_json"])
    assert payload["mode"] == "midzhi"
    assert "游击" in payload["text"] or "游击" in ctx2.reply


def test_pacification_same_target_updates_candidate_different_target_independent(game):
    """C4：同大臣同目标未确认招抚更新既有行；异目标独立。"""
    db, state, content = game
    _activate_canonical_bandit(db, content, "张献忠")
    _activate_canonical_bandit(db, content, "李自成")
    actor = db.conn.execute(
        "SELECT name FROM characters WHERE power_id='ming' AND status='active' LIMIT 1"
    ).fetchone()["name"]

    ctx_a = _ctx(
        db, actor,
        candidates_from_classifier_payload(
            {"kind": "pacification", "target_id": "张献忠"}, soft=False,
        ),
        state.turn,
    )
    run_materialize_pipeline(ctx_a)
    first_id = ctx_a.out["pending_action_id"]
    pend = list(db.list_pending_actions(state.turn, minister_name=actor))

    ctx_a2 = MaterializeCtx(
        session=SimpleNamespace(db=db, state=SimpleNamespace(turn=state.turn)),
        character=SimpleNamespace(name=actor, office_type="文官"),
        player_message="招抚张献忠，再许免死。",
        reply="臣请招抚张献忠并许免死。",
        message_text="招抚张献忠，再许免死。",
        explicit_prefixed=False, has_directive=False, pend_for_minister=pend, out={},
        intent=None, intent_kind="none", llm_config=None,
        intent_candidates=candidates_from_classifier_payload(
            {"kind": "pacification", "target_id": "张献忠"}, soft=False,
        ),
    )
    run_materialize_pipeline(ctx_a2)
    same_target = [
        r for r in db.list_pending_actions(state.turn, minister_name=actor)
        if r["kind"] == "directive"
        and json.loads(r["payload_json"]).get("dossier_action_type") == "pacification"
        and json.loads(r["payload_json"]).get("target_id") == "张献忠"
    ]
    assert len(same_target) == 1
    assert int(same_target[0]["id"]) == int(first_id)
    assert "免死" in json.loads(same_target[0]["payload_json"])["text"]

    pend2 = list(db.list_pending_actions(state.turn, minister_name=actor))
    ctx_b = MaterializeCtx(
        session=SimpleNamespace(db=db, state=SimpleNamespace(turn=state.turn)),
        character=SimpleNamespace(name=actor, office_type="文官"),
        player_message="另旨招抚李自成。",
        reply="臣另请招抚李自成。",
        message_text="另旨招抚李自成。",
        explicit_prefixed=False, has_directive=False, pend_for_minister=pend2, out={},
        intent=None, intent_kind="none", llm_config=None,
        intent_candidates=candidates_from_classifier_payload(
            {"kind": "pacification", "target_id": "李自成"}, soft=False,
        ),
    )
    run_materialize_pipeline(ctx_b)
    pac_rows = [
        r for r in db.list_pending_actions(state.turn, minister_name=actor)
        if r["kind"] == "directive"
        and json.loads(r["payload_json"]).get("dossier_action_type") == "pacification"
    ]
    targets = {json.loads(r["payload_json"])["target_id"] for r in pac_rows}
    assert targets == {"张献忠", "李自成"}
    assert len(pac_rows) == 2


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






def test_pacification_successful_promulgation_closes_dossier(game):
    """C3 r6：招抚纳入 terminal 集；成功易主后 fulfilled/closed，不滞留 executing。"""
    from ming_sim.decree_vocabulary import dossier_action_policy

    db, state, content = game
    assert dossier_action_policy("pacification")["execution_surface"] == "terminal"
    dossier = _promulgate_pacification(db, state, content, "张献忠")
    row = db.get_decree_dossier(dossier["id"])
    assert row is not None
    assert row["status"] == "closed"
    assert row["execution_outcome"] == "fulfilled"
    assert db.conn.execute(
        "SELECT power_id FROM characters WHERE name='张献忠'"
    ).fetchone()["power_id"] == "ming"


def test_pacification_promulgation_refreshes_target_after_outer_commit(game):
    """#672：招抚易主成功后经 outer-commit callback 刷新 registry。"""
    from ming_sim.decree import settle_with_delta

    db, state, content = game
    _activate_canonical_bandit(db, content)
    target_name = "张献忠"
    ctx = _stage_pacification(db, state.turn, target_name)
    db.commit_pending_actions(state, content=content)
    dossier = next(
        d for d in db.list_decree_dossiers(status="proposed")
        if d["action_type"] == "pacification"
    )

    class _Reg:
        def __init__(self):
            self.refreshed = []

        def refresh(self, name):
            self.refreshed.append(name)

    reg = _Reg()
    settle_with_delta(
        state, db, {}, before_turn=int(state.turn), content=content, registry=reg,
        dossier_verdicts=[{"dossier_id": dossier["id"], "decision": "promulgated"}],
        delta_applier=lambda *a, **k: {},
    )
    assert target_name in reg.refreshed
    assert db.conn.execute(
        "SELECT power_id FROM characters WHERE name=?", (target_name,),
    ).fetchone()["power_id"] == "ming"
